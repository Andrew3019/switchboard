# Part C — the reconciler loop, and failure detection

Evidence tree: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch worker-2, HEAD a9dd319)
unless stated. **Every file cited below is byte-identical in the two checkouts** — I diffed
`switchboard/{status,board,collector,broker,cli}.py`, `defaults/prompts.toml`,
`defaults/settings.toml` against `/Users/andrew/Code/switchboard` (main, caa6d20): all SAME.
So the runtime observations (`sb --help`, `sb status`, run against main's `sb`) are valid
evidence for the worktree too.

---

### line 111 — "**A reconciler runs on a loop — maybe the same loop `sb board` runs on.** If an agent is idle and neither blocked nor done, it pings that agent to say it should probably report done or blocked, unless it is awaiting instructions. The ping goes to the agent itself rather than to its parent, because the agent has more context on what its true status is. That is how we avoid stale idle agents."

**Verdict:** BROKEN

No reconciler exists. The *detection* half is fully and correctly built; the *acting* half —
the loop that pings — does not exist anywhere. Clause by clause:

- **Does a reconciler exist at all — NO.** Nothing in `switchboard/` sends a message to an
  agent because it is idle. Grep across `switchboard/*.py`, `bin/sb`, `defaults/` for
  `reconcil|nudge|liveness|heartbeat` returns only `store._reconcile` (a *schema* migration,
  `switchboard/panel.py:14`) and `cli.py:558` ("nothing reconciles the schema at all") —
  both about the database, not agents. The only messages ever sent are the ones an agent
  itself calls for: `tell`/`ask`/`done` (`broker.py:2752, 2856`).
- **Is the trigger condition "idle AND not blocked AND not done" — YES, and exactly.**
  `switchboard/status.py:466`:
  `stalled=bool(running and alive and hstate in IDLE_LIKE and not awaiting)`.
  `running` is `row["state"] in RUNNING and row["ended_at"] is None` (status.py:423), and
  `RUNNING = ["working"]` (`defaults/settings.toml`, `[states] running`) — so a `blocked`,
  `done` or `failed` row can never be stalled. `IDLE_LIKE = ["idle", "done"]` is herdr's
  "no turn is running".
- **Is "awaiting instructions" excluded — YES.** `status.py:449`
  `awaiting = "awaiting_task" in row.keys() and bool(row["awaiting_task"])`, fed into the
  `not awaiting` term at :466. status.py:437-443: "An agent nobody has asked for anything
  yet is idle for the only reason it could be, and calling that STALLED says something
  false about it."
- **Does it run on a loop, and is it the board's loop — NO.** There are two loops and
  neither can act. `board.main()`'s loop (`board.py:502-541`) only calls `refresh(sup)`,
  which is `sup.tick(); panel.read(...)` (`board.py:352-367`) — reads a file, touches
  neither store nor herdr. The collector's loop (`collector.py:180-188`) calls
  `status_mod.collect(db, Herdr(), reap=False)` on a **read-only** connection
  (`collector.py:110-112`), and `collector.py:13` states that is load-bearing:
  "`readonly=True` and `reap=False` are load-bearing here, not tidy-ups." So the one
  process that ticks every 2 s is architecturally forbidden from writing anything, which is
  the exact place the design puts the reconciler.
- **Does the ping go to the agent rather than the parent — N/A, no ping exists.** The
  nearest thing is a *suggestion printed to the human*: `status.py:1139-1140` ends the DRIFT
  block with `→ sb inspect <name>, then: sb tell <name> "wrap up and run sb done"`. That is
  the right target and roughly the right words, but it is a person's manual action, not a
  loop's.
- **Does the ping say what the design says it says — N/A.** `defaults/prompts.toml:61-95`
  (`[notify]`) has exactly four doorbells: `mail`, `mail_question`, `child_done`,
  and the interrupt text. There is no stalled/wrap-up string to send.
- **"That is how we avoid stale idle agents" — observably not avoided.** Live run of
  `sb status` in this repo: `168 agents · 20 alive · 13 stalled`, with DRIFT listing 13
  STALLED rows, the oldest `quiet 15h59`. Nothing has pinged any of them.

**Gaps** (each a build task):
- Build a reconciler that, per tick, selects rows where `AgentStatus.stalled` is true and sends each one a ping — the predicate already exists at `status.py:466` and needs no new detection work.
- Decide and implement where that loop lives: the collector is read-only + `reap=False` by design (`collector.py:13`), so it needs either a writable reconciler process or an explicitly-carved write path.
- Add the ping text as a `[notify]` key in `defaults/prompts.toml` (alongside `mail`/`child_done`), wording it as "you look idle — report `sb done` or `sb block`".
- Address the ping to the stalled agent via the existing `_ring`/`put_message` path (`broker.py:3401+`), not to its parent.
- Add re-ping suppression (a `last_nudged_at` column or event check) so a stalled agent that stays stalled is not rung every 2 s.
- No idle threshold is configurable today: add one (`[timeouts] stall_nudge_after`-style) so a nudge is not sent the instant a turn ends.

---

### line 102 — "**We should detect failures, and can start with just telling the parent that it has failed.**" (how detection works, retry, and half-finished work are DEFERRED)

**Verdict:** PARTIAL — failure detection exists; the parent is not told.

**Evidence — detection exists:**
- `status.py:544 _record_gone()` writes the verdict: `UPDATE agents SET state='failed', ended_at=COALESCE(ended_at, ?)` (status.py:568-570), plus `store.log_event(db, kind="gone", agent=name, state=GONE_STATE)` (status.py:575-577). Its docstring: "an agent herdr no longer has is not working any more… Nothing else closes a row that died abnormally — a crash, a pane closed from the outside, a herdr restart, a reboot."
- The signal is computed at `status.py:467`: `gone=bool(running and alive is False and not spawning)`, debounced by `_confirmed_gone` (status.py:501) over `GONE_CONFIRM_GRACE` (`timeouts.gone_confirm_grace = 60.0`, `defaults/settings.toml`), so one herdr hiccup does not kill a live agent.
- Confirmed live: `sb status` shows rows in state `failed` (`fix-options-2`, `split-fixer`) that no agent ever reported.
- Caveat on *when* it runs: the write is gated on `if consulted and reap:` (status.py:489), and the only continuously-running process passes `reap=False` (`collector.py:112`). So detection fires only when a human or agent happens to run a writing `sb` command (`cli.py:556-561`: "`collect` reaps"). There is no loop that detects failure on its own.

**Evidence — the parent is NOT told:**
- `_record_gone` (status.py:544-577) writes a state and an event and nothing else — no `store.put_message`, no `_ring`. Grepping `child_done` finds one call site, `broker.py:2868`, inside `Broker.done()` only. So a child that dies fires no doorbell and leaves no mail; a parent whose own turn has ended is never woken by its child's death.
- The failure surfaces only to whoever *looks*: `sb status`'s DRIFT block (status.py:1122-1141) and the board's red `✗`/"GONE — herdr has no such agent" (`board.py:164, 196`). Both are human-facing readouts, not the parent's mailbox. Note that DRIFT shows GONE only while the row still reads `working` — once `_record_gone` flips it to `failed` the row drops out of DRIFT entirely, so the loudest notice of a death is transient.
- The one place a *waiting* agent learns of it is `Broker.ask`, which gives up on a target absent past `GONE_GRACE` and logs `ask_target_vanished` (broker.py:2775-2779) — but that only helps a parent already blocked in `sb ask`, and it returns `None` rather than saying the child died.

**Deferred, and correctly not counted against this verdict:** how detection works (any mechanism is fine), whether anything retries (nothing does — not a gap), and what becomes of half-finished work (nothing handles it — not a gap).

**Known hole, current status:** nothing today notices or surfaces a dead agent's leftover edits. The only uncommitted-work check in the codebase is `Broker._ignored_weight` (`broker.py:1087-1115`), which runs `git status --porcelain --ignored` during **workspace close** to warn a human before deleting a checkout. It is per-workspace, human-triggered, and attributes nothing to an agent — so a dead agent's half-finished edits sit unowned exactly as the design says, and are visible only if someone later tears the workspace down.

**Gaps** (each a build task):
- On `_record_gone`, deliver mail to the dead agent's parent — `store.put_message(kind="failed", body=…)` — so the failure lands in `sb inbox` rather than only in `sb status`.
- Ring the parent on that mail (a `[notify] child_failed` string beside `child_done` in `defaults/prompts.toml`), so a parent whose turn has ended is restarted by a child's death as it is by a child's completion.
- Make failure detection run without a human: today `reap=True` only happens on an ad-hoc `sb` command, so a fleet nobody is watching records no deaths at all.

---

## Seen in passing
- `sb board` is a hidden CLI verb (`cli.py:121`) and refuses to run for an agent (`cli.py:699`) — DESIGN-TRUTH names it as a loop but it is a human-only view, worth checking against whatever entry owns the board.
- `sb status` here shows 168 agents / 135 archived and three agents with mail "never announced" for 12–16 h (`waiting_to_be_rung`) — undelivered-doorbell backlog, owned by whoever audits messaging.
