# 3.5 — the reconciler: read-only pass, written before any code changed

Base: `phase3.7-collector-staleness` (`9751d0f`). What the code says today, the rule the
reconciler applies, and the pass/fail tests the build is held to. Results are recorded at
the bottom, against these tests and nothing else.

## What exists today

- **Detection is exact and nothing acts on it.** `AgentStatus.stalled` (`status.py:211`,
  computed `status.py:508`) is `True` exactly when the row is `working` with no `ended_at`,
  herdr lists the agent alive, its herdr state is `idle`/`done`, and `awaiting_task` is 0.
  `blocked` and `done` rows are excluded for free: `states.running = ["working"]`
  (`defaults/settings.toml:141`), so a blocked or finished agent is never `stalled`.
  "Awaiting instructions" is `agents.awaiting_task`, set at spawn and cleared by the first
  real task (`broker._first_task`).
- **Nothing pings.** `grep -rn reconcil` finds `collector.py:172-174` saying this is
  unbuilt and `store._reconcile` (schema, unrelated). `status.py` shows a stalled agent on
  the board and in `--needs-me` (`needs_human`); no code sends it anything.
- **The one loop in the fleet is the collector.** `collector.tick()` collects every
  `display.board_refresh` seconds and has exactly one trigger hanging off it —
  `ring_doorbell`, which spawns `sb flush` rather than writing, because the collector is
  read-only and version-stale on purpose (module note, `collector.py:1-70`).
- **The stop hook (3.8) is the complement, not a substitute.** `hooks.stop_gate` blocks at
  most one turn-end per stop-chain (`stop_hook_active`) and then lets the agent go; its own
  scope doc says the agent it releases is 3.5's. Its exemptions are: `stop_hook_active`, a
  caller it cannot name, a reported state, `awaiting_task`, and a parent with a live child.

## The rule this applies

Work list = `a.stalled` from a *fresh* `status.collect`, minus:

| Skipped | Why |
|---|---|
| blocked, done, failed | not `stalled` at all — `states.running` is `working` only |
| awaiting instructions | `awaiting_task`; DESIGN-TRUTH's stated exemption |
| a parent with a live child | 3.8 exempts it deliberately: the protocol tells a delegating parent to end its turn and wait for the poke. Pinging it would push it to report over work still running. Logged, not silent. |
| pinged already for this stall | the re-ping rule, below |
| not started yet | ADDED AFTER THIS PASS. An agent with no `session_id` has never run an `sb` call, so "herdr says idle" may mean "has not begun" — which is how a freshly delegated agent was pinged two seconds in. `status.STALL_GRACE` holds the label off, so this list never sees it; `audit/phase3-edges-fix.md`. |

The ping goes to the agent itself, never its parent (`DESIGN-TRUTH.md:129-133`).

**The re-ping rule: at most one ping per stall, and never two pings to one agent inside
`REPING_GAP` (10 minutes).** A second ping needs the agent to have *done something* since
the last one — `status`'s own `last_activity`, which counts its `sb` calls, mail it sent
and mail it read — meaning it woke, acted, and stalled again. A stall that just sits there
is pinged once and then left alone; the board, `--needs-me` and the human are what carry it
from there. The gap is the backstop for the pathological case: an agent that wakes on the
ping, runs one `sb` command, and stops again would otherwise be pinged every cycle forever.

The ping event is logged with `agent=NULL` and the target in its payload, deliberately.
`status._last_activity` counts every event with an `agent` set, so logging it against the
target would reset the idle clock on exactly the silent agent the mechanism exists to spot
— the failure that function's own docstring warns about for arriving mail.

**Delivery** is `Herdr.prompt`, guarded but *not* `Broker._ring`: `_ring` calls
`store.mark_delivered` for the whole mailbox, so a nudge that says nothing about mail would
silently mark undelivered mail as announced. The doorbell owns that; this must not touch it.

**The trigger** is the collector, which spawns `sb reconcile` (hidden verb, exactly like
`sb flush`) rather than deciding anything itself — a stale process must not be the one
holding the rule. It spawns when a name is stalled that it has not already spawned for, and
at most once per `RECONCILE_SWEEP` (10 min) for a stall that persists, so a stalled agent
nobody attends to does not cost a process every two seconds for the rest of the day.

## Pass/fail tests

Live, in an isolated clone (primary evidence):

- **L1** a real agent whose turn ends without `sb done` or `sb block` is pinged within one
  reconciler cycle, and the text it gets names both verbs.
- **L2** a blocked agent is not pinged.
- **L3** an agent that reported `done` is not pinged.
- **L4** an agent awaiting instructions (spawned with the placeholder, never given a task)
  is not pinged.
- **L5** the same stalled agent is not pinged twice while it stays stalled.

Automated (three, no more; no new tricks in the fake herdr):

- **T1** `reconcile()` pings a stalled agent, and pings neither a blocked one, a done one,
  nor one still awaiting its task.
- **T2** the re-ping rule: a second pass over the same stall pings nobody; a pass after the
  agent has acted and the gap has passed pings it again.
- **T3** the collector's trigger spawns `sb reconcile` when something is stalled, once, and
  not again for the same stalled set.

## Not built, and why

- **`--needs-reply` (3.5a) gets no special case here, on purpose.** DESIGN-TRUTH's own
  example — "a reply that was asked for and never came surfaces through the idle state"
  (`:124-127`) — is an argument *against* a rule for it: the agent that owes the reply ends
  its turn without reporting, which is a stall, which this pings. 3.5a is on a branch this
  one is not based on (`phase3.5a-needs-reply`), and a `messages.needs_reply` read here
  would be a second rule for a case the general one already catches.
- **Delivery modes.** This uses the one mode that exists on this base: a plain prompt to an
  idle agent, which is the only kind of agent it ever addresses. If `tell`'s modes (3.1)
  land, nothing here needs to change — a stalled agent is by definition not mid-turn.

## Result — run 2026-08-11

A `git clone` of this repo into a scratch directory, this branch checked out there, driven
by that clone's own `./bin/sb` and its own store
(`<clone>/.git/agentflow/state.db` — confirmed by `sb doctor`, and `sb status` empty). Four
real agents, one per case, all since closed, their herdr workspaces gone and the clone
deleted. The loop was the collector itself, run from the clone
(`collector.run(max_ticks=8)`), not a hand-called `reconcile`.

- **L1 — pass.** `rc35quiet`, told to run one command and then stop without reporting, ended
  its turn and `sb status` showed it `STALLED`. The collector spawned `sb reconcile` on its
  **first tick** (`started_at` → `last_reconcile`: 0.2s, i.e. within one cycle), and the
  agent's own pane shows the text arriving verbatim:

      ❯ [sb] Your turn ended 2m ago without a report, so nothing in the fleet knows where
        you are. If you are finished, run `sb done "<summary>"`; if you are stuck or need a
        person, run `sb block "<why>"`; if you are neither, carry on with your task — this
        is asked once, not repeatedly.

  It read the ping, said so, and — still under its original instruction not to report —
  declined. That is the agent's call, which is the point of pinging the agent rather than
  its parent.
- **L2, L3, L4 — pass.** `rc35block` (blocked), `rc35done` (reported done) and `rc35wait`
  (started with no task, `awaiting_task=1`) were live in the same store for the whole run.
  The event log holds exactly one `reconcile_ping` row, and its target is `rc35quiet`.
- **L5 — pass, and it exercised both layers.** The collector spawned `sb reconcile` twice
  (10s apart): the ping made the agent take a turn, so it left `stalled` and re-entered it,
  which is a new name to the trigger's in-process set. The store-side rule refused —
  `pinged nobody` — because the agent had run no `sb` command, so its `last_activity` had
  not moved. Two further `./bin/sb reconcile` runs by hand: `pinged nobody`, `pinged
  nobody`. One ping, for a stall that is still there now.

Automated: **T1** is
`test_only_an_agent_that_went_quiet_is_pinged` plus
`test_a_parent_with_a_live_child_is_left_alone`, **T2** is
`test_a_stall_is_pinged_once_and_not_every_cycle` (`tests/test_broker.py`), **T3** is
`TheReconcilerTrigger` (`tests/test_panel.py`). Suite: 1122 passing.

**Unproven, and worth saying.** The live run never exercised the *second* ping — an agent
that wakes, runs an `sb` command, stalls again and outlives `REPING_GAP` — only T2 pins
that. Nor was a parent-with-a-live-child exemption seen live; it is pinned by the store
logic alone, the same gap `audit/phase3.8-scope.md` records for the same exemption. And
the `sb reconcile` spawned by a collector whose `sb` had to come off PATH rather than out
of its own `bin/` was not exercised — the clone had its own.
