# Audit part B — blocking, and the finishing chain end to end

Audited tree: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch worker-2, HEAD
a9dd319). Every file cited below is **byte-identical** in the `sb`-on-PATH checkout
(`/Users/andrew/Code/switchboard`, main @ caa6d20) — verified with `diff -q` on
broker.py, board.py, status.py, cli.py, protocol.md, prompts.toml, roles/orchestrator.md,
settings.toml. So the runtime behaviour I observed is evidence for the audited tree too.

Live checks run: `sb status`, `sb status --needs-me`, `sb inspect`, `sb cleanup --dry-run`,
one throwaway agent `audit-sim-block` (spawned, then `sb cleanup --force` — gone, no pane,
no worktree, it was a tab in the existing worker-2 space).

---

### line 239 — "**A parent is not told that its child blocked.** It is not needed: that is more layers and more out-of-sync problems, and the board already shows it."
**Verdict:** SATISFIED

**Evidence:**
- `switchboard/broker.py:2871-2904` — `block()` in full does four things and none of them
  touch the parent: `store.set_state(db, me, "blocked")` (2891), `self._push_state(a, IDLE, why)`
  (2902 — herdr state for the agent's OWN pane), `self._surface(me, why)` (2903), and
  `store.log_event(kind="blocked")` (2904). No `store.put_message`, no `_ring`, no parent
  lookup at all. Contrast `done()` at 2864-2868, which does both (`put_message(... to_agent=parent)`
  and `self._ring(parent, ...)`).
- `switchboard/broker.py:2872` docstring: `"""Stop and surface to the human — never to the parent."""`
- `_surface` is the only outbound call: `broker.py:3464-3468` → `self.h.notify(...)` — a
  desktop notification, not a message to any agent.
- Justification holds — the board shows it: `switchboard/board.py:200-201`
  `if a.blocked: return f"BLOCKED — {a.blocked_why or 'no reason recorded'}"`, glyph `◐`
  at `board.py:166`, coloured yellow (`board.py:216`). `blocked_why` is populated from the
  event log for exactly the blocked rows (`status.py:474`, `status.py:643-653`), and
  `AgentStatus.blocked` is `state == "blocked"` (`status.py:226-227`).

---

### line 242 — "**A lead may only clean up a blocked child if it reads the block as stale** — already resolved elsewhere, or the status simply has not updated."
**Verdict:** PARTIAL

**Mechanism** half-holds; the **rule is nowhere in the prompt text**, and the refusal is
silent.

**Evidence:**
- A blocked child is not sweepable: `defaults/settings.toml:130` `finished = ["done", "failed"]`
  → `broker.py:86 FINISHED = tuple(config.setting("states.finished"))`, and
  `broker.py:3001-3003` `if not force: if a["state"] not in FINISHED: continue`. `blocked`
  is not in that tuple, so `sb cleanup` (sweep) leaves it. Good.
- But a **named** blocked child is skipped by the same `continue` — silently. The only gate
  that refuses out loud is live-descendants (`broker.py:2977-2985`, raises with
  "still working underneath"); the state gate just `continue`s and does not even log
  `cleanup_held` (that log line, `broker.py:2995-2998`, is the descendants gate only).
  The CLI then prints the empty list: `cli.py:866-870` → `"{verb}: {', '.join(names) or '(nothing)'}"`.
  Observed live: `sb cleanup --dry-run audit-sim-block` (state `working`, same gate) →
  `would close: (nothing)` — no reason, no warning.
- `--force <name>` closes a blocked child with **no** stale check and no warning:
  `broker.py:3001` skips every gate under `force`; the only "say it out loud" branch is
  `state == WORKING` (`broker.py:3019-3027`, logs `cleanup_forced_live`) — `blocked` is not
  `working`, so forcing a blocked child logs nothing special and prints nothing.
  Observed live: `sb cleanup --force audit-sim-block` → `closed: audit-sim-block`.
- The "only if stale" rule is **absent from every prompt an agent receives.** What the
  orchestrator is told is a KEEP rule with no exception:
  `defaults/roles/orchestrator.md:149-151` — "Two things stay open, and nothing else does:
  an agent blocked waiting on a human, and finished implementation work someone may
  actually want to open." Nothing about stale blocks, resolved-elsewhere, or a status that
  has not updated. `defaults/protocol.md` mentions cleanup once ("`sb cleanup [names]`
  closes finished ones beneath you") and says nothing about blocked children. `grep -rn stale
  defaults/ switchboard/roles.py` finds only the shared-worktree re-read line
  (`prompts.toml:43`) — unrelated.

**Gaps:**
- `cleanup`: refuse a NAMED blocked agent out loud (same shape as the live-descendants
  refusal) instead of silently returning "(nothing)".
- `cleanup`: log `cleanup_held` (with the state) when a named agent is skipped by the state
  gate, so the log can answer "why is that one still here".
- `cleanup --force` on a `blocked` agent should log/print the way `cleanup_forced_live`
  does for a working one — closing an agent that stopped to ask a human is currently silent.
- Orchestrator prompt: state the exception — a blocked child may be cleaned up only if the
  lead reads the block as stale (already resolved elsewhere, or the status has not caught
  up), and name `--force` as the way to do it.

---

### line 58 — the CUJ "When work finishes"

Quoted in full from DESIGN-TRUTH.md:58-67:

> **When work finishes.** It depends who is done and who is reporting it. A worker that is
> done reports done, and its parent orchestrator sees it. Once all of its children are
> done, that orchestrator either reports done or blocks, depending on whether the task is
> fully complete: fully complete, report done; Andrew's input needed to finish it, block.
> Once that is done it reports done, and the top orchestrator blocks. A lead cleans up its
> children, pushes the PR if relevant, and summarizes — it does not close itself, since
> cleaning an orchestrator takes its children and it still has to report. A bare agent
> under the top pushes and opens its own PR; the top blocks for it. Once a block is
> resolved the agent finishes and reports done, and the parent cleans up. — confirmed
> 2026-08-09

**Clause 1 — "a worker that is done reports done, and its parent orchestrator sees it."**
**Verdict:** SATISFIED
- `broker.py:2861-2868`: `store.put_message(from_agent=me, to_agent=parent, kind="done", body=f"[done] {summary}")`, then `self._ring(parent, self._say("notify.child_done"))`.
- Doorbell text: `defaults/prompts.toml:82` — "A child finished. Run: sb inbox. Waking is not a reason to report — if other children are still running, wait for them."
- Told to the worker: `defaults/protocol.md` — "To finish: commit your work, then call `sb done \"<summary>\"` as your last action … That summary is the only thing your parent ever sees of you".

**Clause 1a (supporting truth, line 200) — `sb done` keeps the agent open, always "when idle", and that is how an idle top learns a child finished.**
**Verdict:** PARTIAL
- Keeps it open: `done()` never closes a pane — it only sets state and messages (`broker.py:2856-2869`). Confirmed.
- "When idle" is real but is a *poll*, not an idle trigger: `_ring` defers on a busy target
  (`broker.py:3426-3428` `if not force and self._busy(who): log ring_deferred; return False`),
  and the held doorbell only fires when `flush_pending` next runs — which is "at the start of
  every `sb` command" (`broker.py:3304-3310`), i.e. when some *other* process happens to touch
  the store, not when the target goes idle. `broker.py:3325` admits it: "This is the stand-in
  for an events daemon."
- There is no per-message delivery mode stored at all — `store.put_message` has no mode
  column; every message uses the one held-while-busy path. So `done` is "when idle" only by
  virtue of there being nothing else.
- Contradicts the same line's "a blocked agent is not idle; when-idle mail is held until its
  block is answered": `_ring` has no blocked guard — it calls `_unblock_if_needed`
  (`broker.py:3429`, `3439-3461`), which pushes `working` to herdr and sets the store state
  back to `working`. So a child's `done` doorbell arriving at a **blocked parent** cancels
  that parent's block. `flush_pending`'s own docstring names this hazard
  (`broker.py:3312-3317`) and only mitigates it for *already-read* mail, not for a fresh
  `done`.

**Clause 2 — "once all its children are done, that orchestrator either reports done or blocks (fully complete → done; Andrew's input needed → block)."**
**Verdict:** PARTIAL
- "Wait for all children" is stated: `prompts.toml:82` (above) and
  `orchestrator.md:64-66` — "Treat a fan-out as one cohort … `sb status` tells you who is
  still out. When the cohort is complete, synthesise".
- The done/block *choice* is stated only as a prohibition, not as the fork the CUJ
  describes: `orchestrator.md:193-195` — "`sb block \"<why>\"` is your only path to a human
  and it ends your turn … Use it when a decision is genuinely theirs. Do not use it to hand
  over work, and do not use it to report — that goes to your parent through `sb done`."
  Nothing says "when your children are all done: report done if the task is fully complete,
  block if Andrew's input is needed to finish it".
- `done()` explicitly permits reporting done with children still running
  (`broker.py:2839-2847`), which is fine but is the opposite instruction to the CUJ's, and
  no prompt closes that gap.

**Clause 3 — "once that is done it reports done, and the top orchestrator blocks."**
**Verdict:** BROKEN (prompt); mechanism is fine
- Mechanism: a root has `parent=None` (`broker.py:2582` `parent=(None if me == HUMAN else me)`),
  so its `done` writes no mail — `broker.py:2832-2838` "A ROOT agent has no parent and the
  human has no mailbox, so its summary is not mail — it is a record."
- Nothing tells the top to block instead. There is one orchestrator prompt for every tier
  (`defaults/roles/orchestrator.md`, header comment: "THE orchestrator role — there is only
  one, deliberately"), and it tells every orchestrator to report "to your parent through
  `sb done`" (line 195) and "Your reader is your parent, in virtually every case" (line 58).
  A top orchestrator following that calls `sb done` into the void — the human is never
  surfaced, since `_surface`/`notify` only happens in `block()`.

**Clause 4 — "a lead cleans up its children, pushes the PR if relevant, and summarizes — it does not close itself."**
**Verdict:** PARTIAL
- Cleans up children: `orchestrator.md:145-154` — "`sb cleanup [names]` closes finished
  agents in your subtree. Use it constantly, as part of the job rather than a tidy-up at the
  end". Scope enforced at `broker.py:2963-2965` (an agent may clean only its own subtree).
- Does not close itself: enforced (`broker.py:2992-2993` `if a["name"] == me: continue  # never
  close the caller`) and stated (`orchestrator.md:153` "no agent closes itself").
- Summarizes: `orchestrator.md:56-89` ("What you say").
- **"pushes the PR if relevant" appears nowhere.** `grep -rn "push\|PR\|pull request"` over
  `defaults/protocol.md`, `defaults/prompts.toml`, `defaults/roles/*.md`, `defaults/presets/*`
  returns one unrelated hit (`reviewer.md:22`, the phrase "Some thoughts on this PR"). The
  protocol says only "commit your work, then call `sb done`". Nothing in the spawn prompt
  chain (`broker.py:2548-2556`: protocol + identity + workspace + role prompt + presets) adds it.

**Clause 5 — "a bare agent under the top pushes and opens its own PR; the top blocks for it."**
**Verdict:** BROKEN
- Same grep as above: no prompt an agent receives mentions pushing or opening a PR, and
  nothing distinguishes a bare agent's finishing duties from any other worker's — the
  fragments a bare agent gets are exactly protocol + identity + workspace + role + presets
  (`broker.py:2548-2556`).
- "the top blocks for it" is the same missing instruction as clause 3.

**Clause 6 — "once a block is resolved the agent finishes and reports done, and the parent cleans up."**
**Verdict:** SATISFIED
- Resolution path: the human's `sb tell` rings, and `_unblock_if_needed` (`broker.py:3439-3461`)
  pushes `working` and clears the store state — "answering a blocked agent IS unblocking it".
- Told to the agent: `defaults/protocol.md` — "`sb block \"<why>\"` … ends your turn, puts you
  in front of them, and you are poked the moment they answer", and the general finish
  contract "commit your work, then call `sb done`".
- Parent cleans up: once the state is `done` it is in `FINISHED` and both the sweep and a
  named cleanup close it (`broker.py:3001-3013`), which `orchestrator.md:147` instructs.

**Overall verdict for the CUJ (line 58): PARTIAL.** The message plumbing (done → mail +
doorbell → parent, block → human only, cleanup scoped to subtree, caller never closes
itself) is all there and correct. What is missing is entirely on the *instruction* side:
nothing tells the top orchestrator to block instead of reporting done, and nothing anywhere
tells a lead or a bare agent to push or open a PR — two of the six clauses are behaviours no
agent is ever asked for.

**Gaps:**
- Orchestrator prompt: state the finishing fork — when the cohort is complete, `sb done` if
  the task is fully complete, `sb block` if the human's input is needed to finish it.
- Orchestrator prompt (or a top-only fragment at `sb start`): a top-level orchestrator with
  no parent must `sb block` to report, because `sb done` from a root reaches nobody.
- Add the push/PR duty to the prompt chain: a lead pushes and opens the PR for its space
  before it summarizes; a bare agent under the top pushes and opens its own PR.
- `_ring` must not unblock a blocked target for a `done`/`mail` doorbell — hold it until the
  block is answered (design truth line ~210: "A blocked agent is not idle").
- Delivery of a held doorbell depends on some other process running an `sb` command
  (`flush_pending`); an idle top with no other traffic is not woken by anything.

---

## Seen in passing
- `sb delegate` handed my throwaway child its task but the text sat unsubmitted in the
  Claude input box for 5+ minutes (`sb inspect audit-sim-block` showed the prompt at the `❯`
  with `state working / herdr idle / STALLED`) — a spawn-delivery problem, not mine to fix.
- `sb status --needs-me` currently lists three agents with mail "never announced to it,
  oldest 12–16h" (fix-options-2, split-fixer, board-teardown) — undelivered doorbells that
  `flush_pending` has never cleared.
