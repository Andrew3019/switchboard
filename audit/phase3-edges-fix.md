# The two edges the phase 3 integration found, and what each of them actually was

`audit/phase3-integration.md` closes with two rough edges the live cross-check saw and did
not fix: the reconciler pinging an agent two seconds into its spawn window, and the Stop
hook blocking one agent twice twelve seconds apart. Both are fixed on `phase3-messaging`.
Neither symptom was what it looked like from the outside, so the causes are worth stating
before the evidence.

## 1 — the spurious ping: `stalled` was true before the agent had started

Not a reconciler bug. `AgentStatus.stalled` asks the store for `working`, herdr for idle,
and the row for `awaiting_task` — and in the window between a delegate and the agent's
first turn, all three answer exactly as they do for an agent whose turn ended in silence.
Nothing in the store records that herdr once saw an agent `working`: the collector is the
only process watching continuously and it is read-only by design, so that fact is never
written down. **"Idle" and "has not started yet" are the same reading, and the label
trusted it immediately.**

The one durable trace an agent leaves of having run is its `session_id`, claimed on its
first `sb` call. So `status.STALL_GRACE` holds the stall reading off for a row that has
none, measured from the last thing that happened to it (not from its creation — a slow
`agent start` can put a minute between the claim and the task, and it is the task that
starts the clock that matters). The moment a session id appears the grace is over for good.

The fix is in `status`, not in `Broker.reconcile`, because the label is what the board,
`--needs-me`, `sb inspect` and the collector's own reconcile trigger all read: fixing the
acting half alone would have left four readouts saying STALLED about an agent that is
mid-spawn, and a process spawned per fan-out member to then decide against pinging it.

`STALL_GRACE` is 72 s, derived from the delivery's own worst case
(`deliver_attempts × deliver_ms` plus the same backoff a spawn retry uses) rather than
restated, the way `SPAWN_GRACE` is derived. It was written as one delivery window (20 s)
first, and the live run below is what rejected that number: the agent read idle to herdr
for **26 seconds** after its row appeared, which would have left four seconds of the
window still exposed. Nothing should call an agent stalled before the machinery handing it
its task has given up trying.

**What it costs.** An agent that never runs `sb` at all and genuinely goes quiet is now
pinged up to one grace later than before. That is the cheap direction: the Stop hook
speaks to that agent at the moment it stops, the board shows it throughout, and the
reconciler is the backstop for the case the hook cannot fix — not the first responder.

## 2 — the double block: `stop_hook_active` is per stop-chain, and a chain is one prompt

The flag is real, it arrives, and it was never the cap the design claimed. Measured in an
isolated clone before anything was changed: an agent was blocked, took its extra turn, and
its second stop carried `stop_hook_active: true` and was allowed through — the documented
behaviour, working. Then one `sb tell` reached it; it took a turn, ended without reporting,
and the payload of that stop carried `stop_hook_active: false` **and a new `prompt_id`**.
Blocked a second time. Two blocks, one agent, nothing wrong with the flag.

So a chain is one user prompt, and every poke starts a new one — a doorbell ring, a `tell`,
and in particular the reconciler's own nudge, which is how the integration's run produced
two blocks twelve seconds apart. A cap that resets on every poke is not a cap, and the
block text has been promising "you will only be stopped once" the whole time.

`hooks._already_nudged` asks the store instead, which outlives every chain: the newest of
this agent's `stop_gate_blocked` / `done` / `blocked` events. Our own block on top means we
nudged it and it has said nothing since, so it is let go — logged as `stop_gate_capped`,
against no agent with the target in the payload, for the reason `Broker._nudge` does the
same: `status._last_activity` counts every event that names an agent, and this one must not
reset the idle clock on the silent agent the hand-off exists to pass on. A report re-arms
it, which is the intended door: an agent that called `sb done` and is then spoken to in its
pane is `working` again, and its next silent turn-end is a new silence worth one nudge.

`stop_hook_active` stays as the first check. It is cheap, it is correct within a chain, and
it costs one line.

## Live proof — one isolated clone, run 2026-08-11

A `git clone` of this repo into a scratch directory, this branch checked out there and
driven by that clone's own `./bin/sb` against its own store. Four agents across the run,
all closed, their herdr workspaces retired (`sb workspace close`, and one pane herdr
refused as a worktree group closed directly by id), the clone deleted. `hooks.run` was
temporarily patched **in the clone only** to write each Stop payload to a file — that is
how the flag and the `prompt_id` below were read; nothing of it is committed.

**The defect, first, under the old code.** `fx2silent` — told to run one `echo` and stop
without reporting — has two `stop_gate_blocked` events, 78 seconds apart: one for its own
stop-chain, one for the chain a single `sb tell` started. The payloads say why: `active=
False, prompt_id=0bd2047b` → blocked; `active=True, prompt_id=0bd2047b` → allowed;
`active=False, prompt_id=346fbfc2` → blocked again.

**Both fixes, then, on one agent under the new code.** `fx4quiet`, delegated with the same
task, watched once a second from outside through `sb status --json`:

| what | when | reading |
|---|---|---|
| row claimed; `delegate` logged at t+3 | t+0 | — |
| herdr reports idle/done, no turn started yet | t+1 … t+26 | old rule STALLED, **new rule not** |
| ten `./bin/sb reconcile` runs across that window | t+4 … t+34 | **`pinged nobody`**, ten times |
| the agent's turn actually starts | t+27 | herdr `working` |
| it ends the turn without reporting | t+37 | **one** `stop_gate_blocked` |
| `./bin/sb reconcile` inside the grace | t+77 | `pinged nobody` |
| `./bin/sb reconcile` once the grace has lapsed | t+130 | **`pinged fx4quiet`** — the stall is still caught |
| the ping's turn ends, still without a report | t+135 | **`stop_gate_capped`**, not a second block |

The last two rows are the integration's exact scenario — the reconciler's nudge is the poke
that starts the new stop-chain — and they are the whole point: one block for the agent's
life, and the reconciler picking it up afterwards, which is the division of labour both
scope docs describe and neither could previously keep.

Also seen and worth having: the agent read idle to herdr for 26 s after its row appeared,
which is where `STALL_GRACE`'s size comes from.

## Automated

Four tests, two per defect, and nothing added to the fake herdr:

- `test_an_agent_that_has_never_run_sb_is_not_stalled_yet` (`tests/test_status.py`) — both
  halves of the grace.
- `test_a_freshly_spawned_agent_is_not_pinged_inside_its_own_spawn_window`
  (`tests/test_broker.py`) — the acting half agrees.
- `test_the_cap_survives_a_new_stop_chain` and `test_a_report_re_arms_the_gate`
  (`tests/test_hooks.py`).

Existing tests that asserted an immediate stall now name a `session_id`, which is what
"this agent has taken a turn" has always been spelled as in this suite
(`test_working_but_absent_from_herdr_is_gone` already carried the same comment). Two of
them were passing for the wrong reason once the grace existed —
`test_a_parent_with_a_live_child_is_left_alone` in particular would have agreed with the
reconciler without exercising the exemption at all — and now say which fact they are on.

Suite: **1122 passing** (1118 before, plus these four).

`./acceptance/accept.py`, run twice against this branch:

- run `sb5yas0c`: **all 4 pass — the fleet is sound** (2m58s) — a cold fan-out of six
  started six (6/6 took their task and reported into 6 new checkouts, 0 spawns
  misreported); a child's report woke its parent, deferred and then delivered by the
  doorbell 47s later; a block held 55s against a sibling and was released by the human's
  answer; a sweep closed 1 and refused 1 with its reason.
- run `sb2mwjea`, the run before it: **1 of 4 FAILED — the fleet is not sound** (3m19s).
  Checks 1–3 passed; check 4 could not spawn its fourth agent —
  "the text was sent 3 times and none of them could be confirmed to have arrived", which is
  `deliver`'s documented flake on a cold checkout, and it happened minutes after another
  agent's acceptance run of six agents had finished on the same machine. Nothing in this
  change is on that path: `stalled` is read only by the board, the collector's trigger and
  the reconciler, and the gate only ever runs at a turn end. Recorded rather than dropped,
  because a re-run that passes is not proof the first one was noise.

## Unproven, and worth saying

- The grace is a clock, and a clock is an approximation of the fact nobody records. An
  agent that never runs `sb`, works for less than `STALL_GRACE` and then goes silent is
  pinged one window late rather than promptly; an agent whose task delivery somehow takes
  longer than the delivery machinery's own worst case could still be pinged inside its
  spawn window. The durable fix is a store column written when herdr is first seen
  reporting the agent `working` — which needs a writer that watches continuously, and the
  only process that watches is read-only on purpose.
- Not seen live: the cap re-arming after a report (`test_a_report_re_arms_the_gate` pins it
  alone), and the pane-id fallback in `_agent_row` — both live agents here had claimed a
  session id by the time they stopped, the same gap `audit/phase3.8-scope.md` records.
- `stop_gate_blocked` is still logged against the agent, so a blocked agent's `idle` clock
  restarts on our own event and the grace above is measured from there. Observed rather
  than fixed: it delays the reconciler's ping by one grace and nothing else, and the event
  belongs to that agent for `sb log`'s sake.
