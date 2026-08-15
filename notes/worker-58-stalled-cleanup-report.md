# Stalled-agent cleanup — implementation report (worker-58)

Task: `notes/tasks/stalled-cleanup-fix.md`. Commit `65dcd53` on `stalled-agent-cleanup`
(`switchboard/broker.py`, `tests/test_broker.py`). Suite green: 1237 pass.

## What changed — all inside `Broker.cleanup`

1. **The refusal names `--force`.** Gate 4a's string, for an agent named outright, now
   ends `. --force closes it anyway`. A sweep's wording is unchanged, because `--force`
   is illegal on a sweep and promising it there would point at a refusal.
2. **Gate 4a admits a confirmed-stalled row.** New closure `given_up_on(name)`: a bare
   sweep admits a row `status.py` calls `stalled`; an agent named outright also gets
   `turn_doubted`. It asks `status.collect(..., reap=False)` rather than re-deriving
   anything, so there is no second notion of "stalled" in `broker.py`.
   - **Cost.** Memoised to **one `collect` per `cleanup` invocation**, taken lazily and
     only when some candidate is unfinished — a sweep whose candidates are all finished
     asks herdr nothing. One `agent list` plus one pass over the store, priced by fleet
     size and not by candidate count; the same call the collector's `reconcile` already
     makes on its own timer (`cli.py:661`).
   - `reap=False` for the reason `reconcile` passes it: a reading taken to decide one
     command must not also write `failed` rows and clear turn edges halfway through the
     loop that is reading it.
3. **Mail.** Gates 3, 4b and 4c all still apply on top. A stalled row with unread mail is
   still refused — mail is cleared by the close (`_clear_unreadable_mail`) and by nothing
   else, exactly as decided — and the refusal now names *that* gate rather than repeating
   "unread mail it could still read", and for a named agent says `--force` closes it with
   the message surviving in the inbox for `sb restore`. `flush_pending` untouched.

Not touched, per the task's constraints: `_revive`, the `sb done` delivery block,
`herdr.py`, `_spawn`'s delivery block, `_took_a_turn`, `status.py`'s grace constants.

New event `cleanup_stalled{state, named}` records a close nobody typed `--force` for —
otherwise a sweep taking a `working` row logs identically to closing a finished one.

## Live proof

Isolated `git clone` into a scratch directory, its own store, driven by that clone's own
`./bin/sb`. Three real agents.

- **Old vs new on the same live rows.** With `87572c1`'s `broker.py` checked out:
  `refused worker-1: working, not finished — it has not reported an end` (named and
  sweep). With the branch's `broker.py`: bare `sb cleanup` closed `worker-2`
  (`state=working`, `stalled`), `sb cleanup worker-1` closed `worker-1`. Both logged
  `cleanup_stalled` then `cleanup{forced: false}`; panes closed, rows `done`.
- **A genuinely mid-turn agent is still refused.** `worker-3` running a foreground sleep,
  herdr reading `working` and `agents.turn = working`: refused by name with
  `... it has not reported an end. --force closes it anyway`, and the same row in a bare
  sweep refused without the `--force` clause.
- **Teardown.** All three workspaces retired, worktrees removed, the clone's herdr
  workspace closed, clone deleted. Two leftover processes killed **by verified pid** (the
  clone's own collector, and a `caffeinate`) after checking each one's `cwd` — never an
  unscoped kill. The live fleet's collector (pid 40401, cwd in a `switchboard` worktree)
  was identified and left alone.

## Tests — four, pinning decisions

In `tests/test_broker.py`, helper `_stalled_kid`:

- a sweep closes a row whose turn ended without a report;
- a working agent is still refused, the named refusal names `--force`, the sweep's does
  not;
- a named cleanup takes a `turn_doubted` row that a sweep will not;
- a stalled row holding mail is still refused, and the refusal says `stalled`.

## Unproven, and one bug found

- **The stalled + unread-mail refusal is pinned by unit test only.** I could not build it
  live: a stalled agent whose session is still alive gets rung, wakes and reads the mail
  (observed — `unread` went to 0 and the row then closed cleanly). The real shape needs a
  dead session, i.e. killing a Claude process, which I judged out of proportion to the
  claim.
- **Bug found, not fixed** (filed: `report-bug 2026-08-15-111506`). `cleanup_refused` is
  logged with `agent=<name>` and is missing from `status.DONE_TO_THE_AGENT`, so every
  refusal resets the refused agent's idle clock (`status._last_activity`). That suppresses
  `turn_doubted` (30-minute window) and renews the `starting up` excuse — repeated sweeps
  can keep the stale-turn repair from ever running on the very rows they keep refusing.
  Reproduced live, and it is the same shape as the `ring_deferred` finding already written
  into `_last_activity`'s docstring. One-line fix in `status.py`, which is outside this
  task's scope. It also forced one test's sweep half to be a `--dry-run`, which logs
  nothing.
- **Risk worth naming, not reopening.** `stalled` rows were already being *pinged* by
  `reconcile`; they are now also *swept*, so a false positive in `stalled` costs a pane
  rather than a ping. Live, a worker that legitimately backgrounded a long shell command
  and ended its turn read as `stalled`. `sb restore` brings such a row back, and the bar
  was decided in the task, so this is a flag and not a re-opening.
