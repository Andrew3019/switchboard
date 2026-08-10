# BUILD-PLAN.md — closing the gap between switchboard and DESIGN-TRUTH

Handoff for the orchestrator that will run this work. Written 2026-08-09, from a
read-only audit of all 52 entries in `DESIGN-TRUTH.md` (65 checkable claims: 11
satisfied, 31 partial, 22 broken, 0 unverified) plus the 15 bugs in the `report-bug`
store.

**This file is derived and disposable.** It dies when the gaps close. `DESIGN-TRUTH.md`
is the only thing that outlives it.

## Rules for whoever runs this

- **`DESIGN-TRUTH.md` is the only trusted document.** `FEATURES.md`, `PRINCIPLES.md`,
  `POC.md`, `PLAN.md`, `design/`, `reference/` and every README are UNTRUSTED — they
  describe intent that was never built, or behaviour that has since changed. Code
  comments must be verified against the code.
- **This file is second.** Its evidence was true at the commit it was written on; check
  before you build on it, and correct it in place when it is wrong.
- **Never edit `DESIGN-TRUTH.md`.** Only Andrew adds entries there. If a task looks like
  it requires contradicting one, stop and ask him.
- **Read it first anyway** — everything below exists to make one of its entries true.

## Hazards that will cost you agents if you do not know them

1. **A spawn can silently fail to start.** Two modes, both of which report success:
   the task is pasted into the prompt box and never submitted, or it never arrives at
   all. Filed twice (`2026-08-08-023237`, `2026-08-09-151916`) and again as an empty
   prompt (`2026-08-09-161323`).
   - **Detect:** `sb inspect <name> -n 25` and look for `0% 1M │ $0.00` — an agent that
     has spent nothing has never run. The state column says `working` and lies.
   - **Recover:** pasted-but-unsent → one `sb tell <name> "..."`, which pastes and
     presses enter, carrying the stuck text with it. Empty prompt → cleanup and respawn.
   - Check this after **every** fan-out, before waiting on anything.
2. **The doorbell does not reliably ring.** A parent in a long turn is never woken, and
   mail to an idle agent can sit undelivered for 40 minutes. `flush_pending` runs at the
   start of every `sb` command, so a heartbeat loop calling `sb status` every 20s is a
   working stand-in until phase 3 lands.
3. **`sb` on your PATH may be built from a different checkout than the worktree you are
   editing.** Check before concluding anything about live behaviour, and check whether
   `main` already fixes it before calling something broken.
4. **`sb delegate` rejects any task containing a newline.** Long briefs go in a file and
   the task says "read this file".
5. **`sb cleanup` can silently close nothing** — it refuses agents holding undelivered
   mail and reports `closed: (nothing)` with no reason. `--force` is the way through.

---

# Phase 1 — fleet reliability

**Start with 1.2, before any building at all.** If spawns really are dropping every
system prompt but the last, then agents are running without the protocol, their role and
their presets — which changes what the rest of this plan even means, and would make much
of phase 6 unverifiable. Confirm or refute it first, and say which in your first report.

Nothing else is worth doing first: every later phase is built by agents, and agents are
currently unreliable to spawn, to wake, and to close. Fixing this phase makes every
subsequent phase cheaper.

| # | what | evidence |
|---|---|---|
| 1.1 | Spawn delivery: the task must arrive and be submitted, or the spawn must fail loudly. Never report success for an agent that has not started. | `2026-08-08-023237`, `2026-08-09-151916`, `2026-08-09-161323`; ~8 agents lost in one session |
| 1.2 | **Every spawn silently drops all system prompts but the last one.** Verify first — if still true, agents are running without protocol, role and presets, and much of phase 6 is invisible until it is fixed. | `2026-08-08-031337` |
| 1.3 | Doorbell: mail to an idle agent must be announced; a parent must be woken when a child reports. `flush_pending` has only two callers. | `2026-08-09-004538`, `2026-08-09-035933`, `broker.py` `flush_pending` |
| 1.4 | `sb cleanup` must never silently do nothing — say what it refused and why. | `2026-08-09-010647`, `2026-08-09-071134` |
| 1.5 | An interrupted turn leaves an agent recorded working forever, so nothing ever rings it again. | `2026-08-09-045325` |
| 1.6 | Agent name binding can be lost while the agent is alive, leaving it permanently unreachable. | `2026-08-09-004626` |
| 1.7 | A failed worktree fork is swallowed into a log line and the agent lands in Andrew's own checkout and writes there. Refuse the spawn and tell the parent instead. `sb start` inside a worktree must refuse, naming the main checkout. | audit group 1 |
| 1.8 | `sb restore` after the worktree is deleted reports success and reopens the agent in `$HOME` with no context. Fail cleanly. | audit group 3 |
| 1.9 | Blocking pushes the agent to `IDLE` (`broker.py:2902`), so any sibling's ordinary mail clears the block and drops it off `needs-me` — Andrew's answer arrives buried under it. | audit groups 2 and 4, both probed |

**Done when:** a fan-out of six agents starts six agents, every `done` wakes its parent
without a heartbeat, `cleanup` always explains itself, and a blocked agent stays blocked
until Andrew answers.

# Phase 2 — the human path

Andrew's only surfaces are the board, the session he types into, and `sb inspect`.

- **2.1** An agent that needs him writes the full question in its own chat, then calls
  `sb block`. The `why` is bookkeeping he never reads. The shipped prompts teach the
  opposite, and that private text is displayed to him in six places.
- **2.2** Answering by typing into the pane must clear the block — the agent clears its
  own block on receiving his reply. Today only `sb tell` clears it, which he never uses.
- **2.3** A top-level agent's `done` reaches nobody. It goes idle or blocks; he monitors
  tops himself.
- **2.4** `sb inspect` shows ~100 lines of tail (currently 40, `display.output_lines`).
- **2.5** Board click lands on the wrong agent: row width is measured in characters
  (`board.py:331` `_visible_len`), not terminal columns, so one emoji or CJK character
  wraps a row and every row below is off by one. Not the side panel.
- **2.6** `sb status` is documented and pointed at him in four places; only the board is
  his.

# Phase 3 — messaging

- **3.1** `sb tell` gains three delivery modes: **next turn** (default), **when idle**,
  **interrupt**. Only *when idle* exists today (`broker.py:3348` holds while `_busy`);
  *next turn* — paste now, land at the agent's next step boundary — is the herdr path
  that only `sb interrupt` uses (`force=True`, `broker.py:3224`).
- **3.2** Delete the `sb interrupt` verb once it is a mode. Do not delete it before, or
  the capability goes with it.
- **3.3** Every sb message carries `[sb: from <name>]` — nothing sb sends is marked today.
- **3.4** A blocked agent is not idle: hold when-idle mail until its block is answered.
- **3.5** The reconciler: on the board's loop, any agent idle but neither blocked nor
  done gets pinged to report one or the other — unless it is awaiting instructions. It
  also covers an unanswered `--needs-reply`. Detection already exists and is exact;
  nothing pings. 13 stalled agents at the time of writing, oldest quiet 16 hours.
- **3.6** `sb ask` is still in the shipped protocol and the store holds live ask rows —
  agents wait on each other today. Remove after 3.1, not before.

# Phase 4 — removals

Cheap, mechanical, and it unblocks phase 6: the prompts cannot be rewritten while they
still name flags that are supposed to be gone.

- `--keep`, `--ephemeral`, `--include-kept`, `--leave-children`, `--no-board`, and focus
  as a flag are all still live CLI options.
- `keep`/`ephemeral` are persisted state: a store column, a settings default, a field on
  every role, and all five shipped role prompts tell agents to use them.
- `sb wait` and the human inbox: the inbox is genuinely gone; `sb wait` is not.
- `sb workspace new` is deleted once phase 5 covers space creation.

# Phase 5 — structure

- **5.1** `sb start` is the only path that creates a top orchestrator. Stamp it there.
- **5.2** `sb delegate` branches on that stamp: a top's spawn gets a new space and
  worktree; anyone else's gets a tab in the caller's space. This is the mechanism that
  makes top and workspace orchestrators different — not the prompt, which only explains
  it. Today they share a role name, a byte-identical prompt, and no code branches on it.
- **5.3** A bare agent's `delegate` is refused outright. Nothing enforces this now: any
  agent at any depth can spawn, and could create a space.
- **5.4** Tree boundary: another top's whole tree is invisible. `tell`, `ask`, `status`,
  `inspect`, `log` and `restore` are all global today — only `cleanup` checks scope.
  Siblings inside one tree stay visible to each other.

# Phase 6 — prompts and shipping

Last, because it describes behaviour the earlier phases must first make true.

- **6.1** The block rules (2.1) and the five reasons an agent may block — three are
  missing from every prompt and one is contradicted.
- **6.2** Human-facing output must be concise, skimmable, bulleted, questions numbered
  with a recommended answer. Taught nowhere today.
- **6.3** Every agent is told at spawn what roles exist, generated from the roles
  themselves, never hardcoded. Nothing lists them today.
- **6.4** `sb presets` gains list / read / apply-to-this-chat; applying pastes the prompt
  in, the same path as any message. Only orchestrators are told presets exist.
- **6.5** Shipping work: branch named for the workspace, push, open the PR, URL in the
  summary. Merging needs Andrew's explicit approval — a prompt rule for now, no merge
  verb, and no agent merges without asking. None of this appears in any prompt.
- **6.6** A lead assigns disjoint files across its shared worktree and serialises overlap.

---

## Ordering rationale

Phase 1 first because everything after it is executed by agents. Phase 2 next because it
is Andrew's only way in, and a broken block means a stalled fleet he cannot rescue.
Phase 3 before 4 so nothing is deleted before its replacement exists. Phase 4 before 6 so
prompts are not rewritten twice. Phase 5 before 6 for the same reason — the prompt should
explain a rule the code already enforces.

## Counts

19 consolidated gaps: 8 never built, 5 built-but-wrong, 6 shipping the opposite of what
was decided. Ten of the 22 broken claims are in phase 4 — decisions already taken and
never carried out.
