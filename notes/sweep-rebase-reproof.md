# The sweep branch on current main — rebase and re-proof

Branch `worktree-model`, rebased onto `origin/main` (now `16b7db9`). Re-proved 2026-08-16.
Read `/private/tmp/switchboard-sweep-report-2026-08-16.md` first: this only records what
changed, and what still holds.

## The rebase

**No conflicts, in either pass.** The branch was first rebased onto `41b0520` (the ten
commits named in the brief); `16b7db9` landed on main while the live proof was running and
the branch was rebased again onto that. Nothing was resolved by hand, so no judgement call
was taken.

## What the eleven new commits did to the sweep's dependencies: nothing

The sweep acts only through gates it does not own. Every one of them is byte-identical
between the old base (`cafc7c8`) and current main — `workspace_close`, `_records_gate`,
`_filed_gate`, `_primary_checkout`, `_finish`, `workspace_list`, `_live_under`,
`_my_spaces`. The diff over `broker.py` for that range touches none of them; what it adds
is `restore_sweep`, `_crash_cohort`, `_parents_first`, `_restore_tab` and
`_capture_session_id`, all of them new methods beside the sweep rather than under it.

Two adjacencies worth naming, both checked and both fine:

- **`sb restore --sweep` is not `sb sweep`.** Main added a `--sweep` FLAG to `restore`;
  this branch adds a `sweep` VERB. They are separate argparse subcommands, and `restore`'s
  own validation (`cli.py`, the `elif cmd == "restore"` block) is scoped to that command,
  so neither reads the other's `args.sweep` or `args.dry_run`.
- **`board.py`'s sweep trigger was untouched by main.** Main's board changes are entirely
  in `wants_you` and `marker` — what a row is drawn as. `sweep_tick`, `_sweep` and the
  `armed`/`sweep_note` state in the draw loop rebased with no hunk near them.

`16b7db9` is roles and model tiers only; the sweep files are identical across it.

## Suite

`1347 passed`. It was 1296 before the rebase; the ten commits brought their own tests.

## Re-proved live

An isolated `git clone` of this repo into a scratch directory, with its own bare `origin`,
eleven real worktrees — one per case, real commits with real dates, a real `sleep` — driven
by **that clone's** `./bin/sb`. One dry run, then one real run:

- **swept, and the checkouts gone from disk:** `landed-old` (tip an ancestor of
  `origin/main`), `squash-merged` (subject match, rule 3), `pushed-not-merged` (tip on a
  remote, rule 1), `unpushed-docs` (docs-only).
- **held, each for the right reason and no other:** `dirty` (one untracked file),
  `live-agent` (a `working` row — the records gate's own words), `live-process` (a real
  `sleep` sitting in the directory), `unpushed-code`, `unpushed-truth` (`DESIGN-TRUTH.md`
  named, carved out of docs-only), `young-agent` (activity clock, 10m), `young-commit`
  (commit clock).

The clone's own checkout was never a candidate: twelve worktrees, eleven looked at. That is
the primary-checkout refusal from `7e70c0e` still holding. One `sweep` event was written,
`looked=11 held=7`.

**The three-board pty run was not repeated.** The rebase did not touch `board.py`'s trigger
(above), so the thing that run exists to prove — that twenty boards crossing one boundary
produce one sweep — has no new way to be wrong. What was proved instead, and cheaply: the
exact subprocess a board spawns (`sweep.command()` with `sweep.environ()`) run from a
SUBDIRECTORY of the clone, which is the import bug that run originally caught — `rc 0`, real
output; and `sweep.claim` on one slot answering `True` then `False`.

Everything created was torn down: the `sleep` killed by pid, every worktree removed, the
clone deleted, no process left with a cwd under it. No agent was ever spawned, so nothing
reached herdr and nothing appeared in Andrew's spaces UI. No unscoped `pkill`.

## Unproven

Everything the original report lists as unproven still is. Nothing that was proved before
is unproven now. Two things this run did not re-cover:

- the `rebase-merged` (patch-id, rule 2) and `no-rows` cases from the original thirteen —
  the brief named eleven and those two were not among them;
- `git branch -d` deleting a swept branch's ref. In the clone the primary checkout sat on
  `worktree-model`, which does not contain the fixture's commits, so `-d` refused all four
  and the refs stayed. That is `_finish` failing in its safe direction and is not new; in
  the live repo, whose primary checkout is on `main`, a landed branch's ref would go.
