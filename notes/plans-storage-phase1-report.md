# Phase 1 — per-plan JSON storage: what landed

Commits `117ba58` (the change) and `1d84d4b` (last stale prose), branch
`plans-board-ui-implement`. Full suite green: **1528 passed**.

## What changed

- One plan is one file: `p-<n>.json`, flat in the state dir, beside `_meta.json`
  (`{"format": 2, "next_plan": N, "next_step": M}`). Meta is primary; a missing or
  mangled one self-heals by scanning the files, as before.
- `_check` is **per file**. A corrupt `p-7.json` costs p-7 and nothing else — the other
  plans load and the board draws them. This is the whole point of the change.
- Cross-file invariants are checked once over the assembled store, not per file: a plan
  lives in the file its id names, and a step id is unique across the store (`tick s-7`
  with no plan named still works).
- `_write` writes only the plans a command actually touched, decided by comparing against
  the text `_read` saw. Append-only / never-dropped enforcement is per file now.
- Eager one-time migration. Old file kept as `plans.json.migrated`, never deleted.
- `FORMAT` bumped to 2, plus a **tombstone**: a `plans.json` holding `{"format": 2, ...}`
  is left in place of the old store. Without it the bump does nothing on the legacy path —
  an old plugin would find no `plans.json`, read the repo as having no plans, and write a
  second store beside the real one.

## Files

| File | What |
|---|---|
| `defaults/plugins/plans/__init__.py` | the I/O core, GUIDE path, prose |
| `defaults/plugins/plans/board.py` | prose only — the read seam at line 117 needed **no** change |
| `tests/test_plans_plugin.py` | helpers rewritten to the per-file store; new `MigrationTest` |
| `tests/test_board.py` | `write()` writes the new layout; new broken-file test |
| `defaults/plugins/plans/analysis/{evidence.py,SKILL.md}` | prose only |

## What Phase 2 needs to know

- `_read` returns **`doc["broken"]`** — a list of `{"id", "file", "why"}` for files that
  did not load. That is what the board's red-drawing / `_defects` should consume. Do not
  re-glob the directory.
- Enumeration helpers: `_files(d)` (plan files in id order) and `_fnum(f)`.
- `list` already prints one `! p-N did not load, and nothing here will overwrite it — …`
  line above the plans that did load.

## Beyond the brief (all small, all deliberate)

- The tombstone, above.
- `_no_such` counts broken ids, so "the highest is p-8" cannot lie while a broken
  `p-9.json` sits on the disk and p-9 is the plan being asked about.
- The `list` broken line. A silently skipped file is how a plan quietly stops existing;
  blast-radius isolation means it must not be fatal, not that it must be invisible.
- Prose in `board.py` and `analysis/` — comment-only, outside the brief's file list, but
  they literally said the store was one file.

## Live impact — needs Andrew

The **real** store at `/Users/andrew/Code/switchboard/.git/agentflow/plugins/plans` is
already migrated: an agent on this branch ran the plugin against it before I finished.

- Verified faithful: 11 plans, every changelog byte-identical, counters 13/67 preserved,
  legacy archived as `plans.json.migrated`.
- But the format-2 tombstone is now there, and I proved in an isolated clone that **main's
  old plugin refuses every plans command against it** ("was written by a newer plans
  plugin (format 2; this one speaks 1)").
- So every worktree not on this branch has lost its plans verbs and the board's PLANS
  section until this merges.
- Reverting the live store is pointless — any agent on this branch re-migrates it on the
  next plans command. Merging fast is the fix.

## Verification

Live, in a `git clone` of the repo with a copy of the real store:

- The real legacy store migrates and lists all 11 plans.
- A `note` on `s-1` rewrites **only** `p-2.json` (mtime-checked); the other ten untouched.
- A corrupted `p-7.json` is named on its own line and the other ten plans still list;
  exit 0; the broken file is byte-identical afterwards.
- Main's plugin against the migrated store refuses, as designed.

Clones torn down; no agents or workspaces were created.

## Unproven

- Two processes racing the migration. Idempotent by construction and serialised by the
  dir lock, but nothing in the suite provokes it.
- `board.py`'s `_read` can trigger the migration **without the lock** — the board does not
  go through the plugin framework. Atomic per-file writes make it benign as far as I can
  reason, but it is not proven.
- The lock is **not** re-scoped, as briefed. This buys blast radius, not write contention.
