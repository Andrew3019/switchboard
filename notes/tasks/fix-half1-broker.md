# Fix half 1 — a live agent must not be stamped GONE because herdr lagged

You own **`switchboard/broker.py` and `tests/test_broker.py` only**. Another agent is working
in `switchboard/herdr.py` and `tests/test_herdr.py` at the same time. Do not touch those two
files, or any other file, for any reason. If you believe your fix needs a change outside your
two files, stop and `sb tell parent "<what and why>" --needs-reply` instead of doing it.

## Read first

1. `notes/scout-task-delivery.md` in this worktree — a scout's map of this code, checked
   line-for-line against HEAD. Sections A, B ("Half 1"), C and D are yours. Trust it as a map
   but verify anything you are about to change.
2. The original bug evidence: `git show bug-triage:notes/triage/group-2-task-delivery.md`,
   section `2026-08-14-172112`, point 1.
3. `sb presets house-rules` and `sb presets verify` — both bind you.

## The bug

`sb delegate` confirms task delivery by watching for the task text in the child's own Claude
Code transcript. When that proof lands just after the last poll, `Herdr.deliver` raises, and
`Broker._spawn`'s except block falls back to `Broker._took_a_turn` as its safety net. That
safety net consults only (a) the store row and (b) one instantaneous herdr status probe. It
never looks at the transcript — and herdr has not caught up to a prompt submitted a second
ago. So a genuinely running agent is stamped `GONE_STATE`, `task_undelivered` is logged, and
`sb delegate` exits 1.

Measured in the filed incident: the proof was written at `00:16:32.619Z` and delegate gave up
at `00:16:33.475Z` — 0.9 seconds later.

The cost is real: the parent is told a running agent is lost, so it either duplicates the work
or force-closes a working pane.

## The fix

Make the safety net consult the transcript — the same evidence `deliver`'s own `proof`
callback already trusts — before it concludes anything.

- `output.task_arrived(cwd, text, *, since=...)` already exists and already takes `since`.
  Nothing needs adding in `switchboard/output.py`, and you must not change it.
- `Broker._spawn` needs the timestamp of its first send. Capture it immediately before the
  `self.h.deliver(...)` call.
- `_took_a_turn` currently takes only `name`. Giving it what it needs (the task text, the
  resolved cwd, and that timestamp) is fine and is inside your files.
- The transcript check is the strongest of the three signals. Order it so that a spawn is
  never concluded failed without it having been asked.

Keep the existing two checks — they cover cases the transcript does not. Do not change the
distinction between a *soft* failure (`task_unconfirmed`, agent still returned, delivery note
set) and a *hard* one (`GONE_STATE`, `TaskUndelivered` raised); a transcript hit belongs on
whichever side of that line the existing "herdr says working" check sits on, and you should
say in your summary which you chose and why.

Smallest honest change. Do not refactor anything you were not asked to fix, and do not fix
other things you notice — report those to me instead.

## Proof

Two things, both required.

**Automated.** One or two tests in `tests/test_broker.py`, in the shape of the three delivery
tests already there (around lines 287–361). The gap the scout names: no test exercises the
transcript branch, because there is no transcript branch yet. Write the test so it *fails
without your change* — the fake herdr reports the agent not working, the store row is not
done/blocked, but a real transcript file containing the task text, timestamped after the send,
exists on disk. `tests/test_output.py::TaskArrivedTest` already has a `write_transcript`
helper and a faked-`HOME` pattern; reuse that approach rather than teaching the fake herdr any
new trick. Growing the fake is forbidden — if something cannot be tested without growing it,
skip the test and say plainly in your summary what is therefore unproven.

Run the whole suite: `/Users/andrew/anaconda3/bin/python -m pytest tests`. Report failures you
did not cause rather than fixing them.

**Live.** Prove it in an isolated `git clone` of this repo in a scratch directory, checked out
on this branch, driving that clone's own `./bin/sb`. Never run a clone's `sb` from outside the
clone. The smallest run that tells fixed from broken, per the scout: force the exact race by
overriding `timeouts.deliver_ms` and `timeouts.deliver_working_ms` down to near-zero for that
clone only (a clone-local settings override — do not edit `defaults/settings.toml`), then
spawn one agent. Broken looks like: exit 1, row stamped gone, agent visibly running anyway.
Fixed looks like: the spawn survives and the row does not go to gone. Show the before/after if
you can get both; if you can only get one side, say which and why.

Tear down every agent and pane you create, and delete the clone. Never an unscoped `pkill` —
one of those killed the live fleet's collector once.

## Landing

Commit to the current branch when done. **Commit with explicit pathspecs only** — e.g.
`git commit switchboard/broker.py tests/test_broker.py -m "..."`. Never `git add -A`, never
`git commit -a`, never `git stash`, and never leave anything staged: another agent is writing
in this same worktree and you will destroy its work. If git reports an index lock, wait a
moment and retry — that is the other agent committing.

Do not push, do not open a pull request, do not touch `main`. I integrate.

## Report

`sb done` with a plain few lines: what you changed, what you proved live and what you only
proved in tests, and anything you left unproven. Unproven and stated is fine; unproven and
silent is not. Write any longer detail to `notes/fix-half1-broker.md` (yours alone) and point
me at it.
