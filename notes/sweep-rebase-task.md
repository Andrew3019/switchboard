# Task: bring the sweep branch up to date with main, and re-prove it

The branch `worktree-model` in this worktree carries a new automatic worktree sweep, built
against a base that is now **10 commits behind `main`**. One of those ten —
"Prevent the herdr worktree-group outage, and make recovery one command" — touches worktree
handling directly, so this is a real integration, not a formality.

You own every file in this worktree for the duration. No other agent is writing here.

## Read first

- `/private/tmp/switchboard-sweep-report-2026-08-16.md` — what was built, what was proved live,
  and what is unproven. Read it before you touch anything.
- `notes/worktree-model-findings.md` — how worktree creation, lifecycle and cleanup work.
- `DESIGN-TRUTH.md` — the only trusted document. Do **not** edit it; only Andrew does.

The new code is `switchboard/sweep.py`, `Broker.sweep` / `Broker._sweepable` in `broker.py`,
a hidden `sb sweep [--dry-run]` verb in `cli.py`, a board trigger in `board.py`, a `[sweep]`
block in `defaults/settings.toml`, and `tests/test_sweep.py`. Commits `f5a023c` and `7e70c0e`.

## What to do

1. **Rebase `worktree-model` onto the current `origin/main`.** Fetch first. Resolve every
   conflict on the merits — read both sides, and where the ten new commits changed worktree
   handling, make the sweep sit correctly on top of the new behaviour rather than reinstating
   the old. If a conflict needs a judgement call you cannot make from the code, stop and tell me
   rather than guessing.
2. **Re-read the sweep against what main now does.** The gates it delegates to
   (`workspace_close`, the inventory gate, the process scan, the primary-checkout refusal) may
   have moved or changed. The sweep must still act only through them, never around them.
3. **Run the full suite**: `/Users/andrew/anaconda3/bin/python -m pytest tests`. It was green at
   1296 before the rebase.
4. **Re-prove it live** in an isolated instance — `git clone` this repo to a scratch directory
   outside the live tree, check out the rebased branch there, drive **that clone's** `./bin/sb`.
   Never run a clone's `sb` from outside the clone. Rebuild enough of the original 13-case
   fixture to show the decisive behaviour still holds after the rebase: swept — landed-old,
   squash-merged, pushed-not-merged, unpushed-docs; held — dirty, live-agent, live-process,
   unpushed-code, unpushed-DESIGN-TRUTH, young-commit, young-agent. You do not need the
   three-board dedup run again unless the rebase touched `board.py`'s trigger; say which you
   chose and why.
5. **Tear down everything you created** in the clone — worktrees, agents, processes. Agents
   spawned in a clone are invisible to the live fleet but visible to herdr, so they show up in
   Andrew's spaces UI. Never an unscoped `pkill`.

## Do not

- Do not change the sweep's policy. The rules are Andrew's and are settled: live agent, dirty
  tree, unpushed non-docs commits, or under 24h on either clock all hold a worktree; landed
  means merged or pushed; docs-only is path-based with `DESIGN-TRUTH.md` carved out.
- Do not resolve the open question about whether ignored files hold a worktree back
  (`sweep.ignored_content_holds`). Andrew is deciding that separately. Leave the setting as it is.
- Do not push, do not open a PR, do not touch `main`. I integrate.

## Report

A few plain sentences: whether the rebase conflicted and how you resolved anything substantive,
whether the ten new commits changed anything the sweep depends on, the suite result, what you
re-proved live, and anything now unproven that was proved before.
