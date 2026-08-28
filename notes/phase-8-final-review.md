# Phase 8 — final fresh review of 64aec5a and 637e16e

Scope: the two repairs made after the Phase 8 re-review — the case-1 eval clause
(`64aec5a`) and the bounded explicit wait (`637e16e`). Nits omitted.

## Verdict

One major, returned rather than fixed. One minor, applied here. Everything else the
brief asked me to check holds.

## Verified and sound

**Case 5 is material again, and case 1 is not over-corrected.** `64aec5a` takes the
re-review's own recommended repair — delete "without invoking a provider command or
stopping for login" from case 1's brief. What made case 1 SHAPED survives: the delivered
brief still says the task owner classified it as shaped, still asks the planner to decide
what doctor "can truthfully establish", and still leaves "the boundary between configured,
resolved and executable" open. Case 5's delta now carries all three of its parts as new
evidence — the codex routing of three tiers, the invocation cost, and the over-claim — and
its premise ("cannot verify those three the way it verifies the rest") no longer
contradicts a brief that forbade invocation for every tier. `test_plans_evals.py` pins
both directions: the two shaped phrases present, the deleted clause absent.

**The expiry fires once per declaration on the happy path.** `Broker.wake_expired_waits`
re-reads the wait row rather than trusting the collector snapshot, so a declaration
renewed between snapshot and prompt is not pinged on the old timestamp; the clear is
conditional on that exact `wait_started_at`, so it cannot erase a newer declaration; a
`HerdrError` leaves the row for a later pass instead of silently dropping the wait.

**It is not the retired broad nudge.** The trigger is a flag derived only from an explicit
`sb waiting` row. `test_status.ReconcileWaitNudgeTest.test_a_stalled_agent_is_told_nothing`
still holds: an ordinary stalled agent is told nothing.

**Composition.** `notify.wait_expired` is placeholder-free and reached through `_say`;
`test_config` pins it in the shipped-defaults set; `settings.toml`, `FEATURES.md`,
`cli.py` and `collector.py` all now describe the same mechanism. Nothing in
`protocol.md`, `guidance.toml` or the roles promised an unbounded wait, so no agent-facing
text is left contradicting the new one.

**Authority (unchanged from the re-review's Major 2).** `DESIGN-TRUTH.md:230` ("only a
causally relevant event wakes it") and the Explicitly-rejected entry ("nothing speaks to
the agent about it any more") both still read as written. Andrew's decision supersedes
them; the amendment is his to make. Nothing in the code or tests depends on the old
wording — `test_design_truth_refs.py` passes.

## Major — the wake has no liveness gate, so a wait nobody can answer is retried forever

**Where.** `status.collect` (`switchboard/status.py:1364`) sets `wait_expired` from the
timestamps alone. Unlike `stalled` and `idle_excuse`, it is not gated on the row being
running, alive or idle. `cli.py:1086` and `collector.run_reconciler` both act on the raw
flag.

**Reachable path.** An agent declares `sb waiting` and its pane then dies — a crash, a
reboot, a pane closed from outside, a herdr restart. Nothing clears its wait row:
`hooks.mark_turn` clears only on a turn that starts, `_ring` only on a causal wake, and
`_record_gone` does not touch the wait columns. The row keeps `wait_expired=True` after it
is reaped to `failed`, and forever after.

**Likelihood.** The protocol tells agents to end the turn with `sb waiting` rather than
poll, and dying while waiting is the exact failure the ageing exists to notice.

**Impact.** `collector.run_reconciler` treats a non-empty `expired` list as due, so it
spawns `sb reconcile` every `RECONCILE_GAP` (10 s), permanently. Each run does a herdr
`agent list` plus a `collect(reap=True)`, attempts a prompt that raises, and writes a
`wait_expiry_ping_failed` row (~8.6k events a day per stuck row). It never self-heals:
`sb cleanup` leaves the row, so only manual SQL stops it. Two lesser shapes come from the
same missing gate: a finished (`done`/`failed`) row whose pane is still up is woken once
with "your declared wait expired", and a `--any`/`--all` parent whose children are
visibly still working is woken at 30 minutes even though switchboard knows nothing is
wrong.

**Reproduced.** `sb reconcile` run four times against a dead waiter: 4 prompt attempts, 4
`wait_expiry_ping_failed` events, wait row still set, and `run_reconciler` still returning
True. Repeated after the row was reaped to `failed`: 3 more attempts.

**Proportionate repair — one line, verified.** Gate the flag on the row actually being a
stalled one:

```python
wait_expired=wait_expired and idle and excuse is None,   # status.py:1458
```

`stalled` is exactly `idle and excuse is None`, so this keeps every case the mechanism is
for — a plain background wait with nothing else to say, and a cohort wait whose children
have all ended — and drops every case it cannot help: dead rows, reaped rows, finished
rows, blocked rows, and parents whose children are demonstrably still running. Tested in
an isolated clone: all three bad shapes stop, and `tests/test_status.py`,
`test_panel.py`, `test_config.py`, `test_broker.py` still pass (578).

## Minor — applied

The wake's own events were counted as the woken agent's activity. `wait_expiry_pinged`
and `wait_expiry_ping_failed` are written with `agent=`, and `status._last_activity`
counts every event naming an agent unless it is in `DONE_TO_THE_AGENT`. Measured before
the fix: an agent silent for 7200 s read `idle 0s`, `stalled=False` immediately after
being pinged — the poke resetting the clock of the silence it was sent to break, which is
the bug `DONE_TO_THE_AGENT` was added for. Both kinds are now on that list
(`status.py:414`), which the existing
`test_a_doorbell_held_for_a_busy_agent_is_not_that_agents_activity` pins automatically
because it iterates the tuple. After the fix the same row reads `idle 7200s`,
`stalled=True`.

## Tests run

Focused only, as the brief asked: `test_status`, `test_panel`, `test_broker`,
`test_config`, `test_hooks`, `test_legibility`, `test_structure`, `test_plans_evals`,
`test_design_truth_refs`, `test_store` — 639 passed, 580 subtests. No full suite, no push,
no PR.
