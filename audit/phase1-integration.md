# Phase 1 integration report — branch `phase-1`

Cut from `main` (f6bcd58) and merged, in this order, each as `--no-ff`, no rebase, no
squash, every original commit message intact:

`scope-phase1`, `verify-prompt-drop`, `fix-doorbell-3`, `fix-spawn-2`,
`fix-cleanup-restore`, `fix-block-misuse`.

`main` untouched, nothing pushed, no PR.

## Conflicts: none

Despite the doorbell and spawn branches both editing the delivery path, both editing
`tests/test_broker.py`, and two branches extending `defaults/settings.toml`, git merged
all of it textually clean. Nothing was hand-resolved, so there is no resolution of mine
for anyone to second-guess.

Because "clean" is not the same as "correct", I checked it three ways rather than
trusting it:

1. **Nothing dropped.** Every source line added by any of the four code branches is
   present in the merged tree — checked mechanically across `switchboard/` and
   `defaults/`, zero missing.
2. **No tests lost.** Collected count is 1685 (main) + 15 + 11 + 10 + 10 = 1731 exactly,
   matching the four branches' additions.
3. **The overlap reads coherently.** I read the merged delivery path end to end:
   `Broker.delegate`/`_fork_for`, `_ring`/`_unblock_if_needed`/`_binding_lost`,
   `collector.ring_doorbell`, `status.needs_human`, and the `block`/`tell`/`cleanup`/
   `flush` handlers in `cli.py`. The two branches' fixes sit side by side without
   overlapping: spawn owns `Herdr.deliver` on the spawn path, doorbell owns `Herdr.prompt`
   on the ring path, and they touch different functions.

## Suite

`python -m pytest -q` on the merged branch: **1731 passed**, 98s. Baseline on `main` was
1685 passed. Package byte-compiles; `defaults/settings.toml` parses; `sb --help` and
`sb flush --help` both run.

## Disagreements between agents

None found. No conflict of intent surfaced between any two branches.

## Safe to install from?

Yes, as far as can be told without installing:

- No `store.py` or schema change (`awaiting_task` already existed on `main`).
- No new dependencies — only stdlib `shutil`/`subprocess` newly imported, in
  `collector.py`.
- CLI starts and the new hidden `flush` verb is present.

The known caveat holds: the collector's timed doorbell works by shelling out to `sb flush`
from PATH, and PATH `sb` symlinks to `/Users/andrew/Code/switchboard/bin/sb` — the main
checkout, still on `main`, which has no `flush` verb. Until that is rebuilt from this
branch, that half is inert; it fails into the collector's `doorbell_error` counter rather
than taking the collector down. Nothing was rebuilt or installed.

## Noticed, not fixed

- The `verify-prompt-drop` commit itself edits `BUILD-PLAN.md` (17 lines), so that file
  does change on `phase-1`. That is that branch's own content, not an edit made here.
- This worktree is now checked out on `phase-1`; the branch `integrate-phase1` still
  points at `main`.
