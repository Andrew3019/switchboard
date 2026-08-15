# Task: narrow the cleanup bar to the row switchboard actually gave up on

This revises your own `65dcd53`. **The bar I gave you in
`notes/tasks/stalled-cleanup-fix.md` was wrong, and that is my error, not yours** — I told
you `stalled` was debounced by a 45-minute window. It is not. Read the review before
anything else: `notes/reviewer-23-stalled-cleanup-blast-radius.md`.

## What the review established

`stalled = idle and excuse is None`, and there is **no idle-duration term in it at all**.
The 45-minute debounce exists only on the path where the turn edge is *stuck at `working`*
— there `stalled` stays false until `_forget_turn` NULLs the edge. The normal end of a turn
(the Stop hook writing `turn='idle'`) makes `stalled` true **at zero seconds**.

Reproduced against the repo's own fake herdr, no new tricks taught to it:

- A healthy child that ran `sb tell parent "…" --needs-reply` and ended its turn to wait
  for the answer is `stalled=True, idle=0s`, and a bare `sb cleanup` closes its pane.
- Closing that child removes its parent's only excuse ("waiting on children"), so two
  consecutive bare sweeps walk a live branch upward one level at a time.
- A freshly delegated worker that has not run `sb` yet has no session id, is past its 72 s
  `starting` grace after 72 s, and once swept **cannot be restored at all** — `restore`
  refuses without a session id.
- `given_up_on` never consults `snap.herdr_error`, so a list-only herdr failure
  (`alive=None`) still sweeps.

And on the named bar: `turn_doubted` is a **single** herdr reading past 30 minutes. Its own
docstring says "one disagreement must never be enough to move a row — that is the finding
this design is built on rather than around", and `settings.toml` records that a live agent
goes 139 minutes without an `sb` call at p99.9 while herdr reads a mid-tool-call agent as
`idle`. A worker 35 minutes into a long test run can be closed by name on one bad reading.

## The new bar — decided, both halves

Gate on **the row whose turn edge switchboard itself gave up on**: `_forget_turn` has fired
for it (the debounced verdict — `turn_doubted` sustained continuously across the full
`turn_doubt_grace`, recorded as a `turn_forgotten` event) and it has not taken a turn since.

- **Bare sweep:** that bar.
- **Named agent:** the same bar. `turn_doubted` is dropped entirely — an undebounced single
  reading must not cost a pane. The window below the bar is served by `--force`, which the
  refusal now names; that is what change 1 was for and it stays exactly as you built it.

This is deliberately narrower than what I asked for the first time, and it is the shape the
filed incident actually needs: `turn_forgotten` fired at 14:01 for both agents while
`state` sat at `working` until a human forced it at 19:05.

Note what the tighter bar buys you, and check each of these rather than trusting me:

- A row that has a `turn_forgotten` must have had a `turn_start`, so it ran hooks, so it
  **has a session id** — the unrestorable class in the review's finding 4 is excluded by
  construction.
- `_sustained` resets its clock on any reading that does not flag the row, so a herdr
  outage cannot accumulate toward the verdict — most of finding 5 goes with it. Decide
  whether any residue justifies consulting `snap.herdr_error` as well, and say what you
  concluded either way.
- A parent is only swept on its own `turn_forgotten`, not on losing its children, which
  answers finding 2. Confirm that.

**Mechanics are yours.** `turn IS NULL` alone is not the test — it is also true of a row no
hook ever fired for. You need "gave up on it *after* it had a turn edge". The `turn_forgotten`
event is a durable record of exactly that; whether you read the event log, add a stored
column, or find something better is your call — but say which you chose and why, and make
sure it survives a row that takes a fresh turn afterwards (the agent came back).

## Also fix, since you are changing what the verb does

`cli.py:250-252` describes cleanup as closing "every finished agent in your subtree", and
`protocol.md:219` says the same to every agent in the fleet. After this change a bare sweep
also takes rows nobody reported an end for. Update both so they are true. Keep it short and
match the surrounding voice.

`DESIGN-TRUTH.md` is the only trusted document and **only Andrew edits it** — if you think
it needs a change, say so in your report, do not make it.

## Still out of scope

`_revive` and the `sb done` delivery block (`revive-gate` owns them); `herdr.py`
`deliver`/`_took_prompt`/`_running_turn` and `broker.py`'s `_spawn` delivery block /
`_took_a_turn` (`task-delivery-fix` owns them); `status.py`'s grace constants; the board
showing STALLED sooner; the `cleanup_refused` idle-clock bug you filed
(`2026-08-15-111506`) — report it, do not fix it.

## Verification

Same rules as before, and the review's probes are the bar to clear:

- Re-run the review's scenarios against your new bar. **The healthy `--needs-reply` waiter,
  the parent-unwinding sequence, and the no-session-id newcomer must all now be refused by
  a bare sweep and by name.** The reviewer's probe file is
  `notes/reviewer-23-stalled-cleanup-blast-radius.md`; its scratch probe script is outside
  the checkout, so rebuild what you need.
- Live proof in an isolated `git clone`, driving **that clone's own `./bin/sb`**. Never run
  a clone's `sb` from outside it. Tear down everything — herdr is machine-global, so your
  agents show in Andrew's spaces UI. Kill only by verified pid after checking cwd; never an
  unscoped `pkill`. No endurance testing.
- Prove the row from the filed incident still closes: turn edge stuck at `working`,
  `_forget_turn` has fired, `state` still `working`. That is the whole point of the change.
- Rework your four tests to pin the new bar, and **check they fail against `65dcd53`**, not
  just against `87572c1` — a test that cannot tell the old bar from the new one pins
  nothing. Suite green: `/Users/andrew/anaconda3/bin/python -m pytest tests`.
- Never teach the fake herdr new tricks. Skip the test and state what is unproven instead.

## Landing

Commit on `stalled-agent-cleanup`, on top of what is there — do not rewrite `65dcd53`, add
to it. Do not push, no PR, do not touch `main`. Shared checkout: no `git stash`, never leave
files staged, re-read before editing.

Report with `sb done`: the new bar and how you expressed it, which of the review's five
findings are now closed and which survive, what the live run proved, and what is unproven.
