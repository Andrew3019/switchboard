# Task: the sweep's landing check fails on Linux

PR #74 (branch `worktree-model`, this worktree) is green on macOS and **red on Linux**, both
3.11 and 3.12, on the same two tests:

```
tests/test_sweep.py::LandingTest::test_a_branch_merged_into_main_is_landed
  AssertionError: Lists differ: ['db1a7da9…'] != []

tests/test_sweep.py::SweptSetTest::test_the_swept_set_is_landed_or_docs_only_and_quiet_on_both_clocks
  AssertionError: Lists differ: ['docs'] != ['docs', 'landed']
```

Logs: https://github.com/Andrew3019/switchboard/actions/runs/31947922782

Both say the same thing: **a branch that is merged into `main` is not recognised as landed** on
Linux. On macOS it is. 1330 other tests pass on both.

## Why this matters

The landing check is the rule the whole sweep turns on. Failing to recognise "landed" is the
conservative direction — it holds a worktree that could have gone — but it means the check is
platform-fragile, and a rule this important cannot be trusted only on one operating system. The
same fragility could plausibly point the other way under some other git version.

## What to do

You own `switchboard/sweep.py`, `switchboard/broker.py`, `tests/test_sweep.py` and anything else
under `switchboard/` and `tests/`. **Do not touch `DESIGN-TRUTH.md`** — another agent is editing
it right now, and it is Andrew's file. Do not touch anything under `notes/`.

1. Find the real cause. Likely suspects, not conclusions: git version differences between the
   runners, `git cherry` / patch-id behaviour, default branch naming, `init.defaultBranch`,
   commit-date or timezone handling, or the test fixture assuming something the Linux runner
   does not provide. Establish which it is from evidence, not from the most plausible story.
2. Decide whether the bug is in the **check** or in the **test**. Say which, plainly. If the
   check is right and the fixture is wrong, fix the fixture and explain why the check was fine.
   If the check is wrong, fix the check — the three landing rules are: tip is on a remote;
   patch-equivalent commit upstream; commit subject in the base's history. Their meaning is
   settled and must not change.
3. Reproduce it somewhere that behaves like the failing runner before claiming a fix. If you
   cannot reproduce locally, say so and push a commit to let CI test your hypothesis — but only
   after you have a specific hypothesis, not as a guessing loop.
4. Run the full suite locally: `/Users/andrew/anaconda3/bin/python -m pytest tests`.

## Landing

Commit on `worktree-model` and **push** — CI must go green on the PR, so pushing is required
here. Do **not** merge the PR and do **not** touch `main`; I do that.

Report in a few plain sentences: the actual cause, whether it was the check or the test, what
you changed, and whether CI went green. If the cause turns out to affect the sweep's real-world
behaviour and not just the test, say so prominently — that changes whether this is safe to merge.
