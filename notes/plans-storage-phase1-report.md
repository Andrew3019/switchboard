# Phase 1 — per-plan JSON storage: what landed

Branch `plans-board-ui-implement`. Commits `117ba58`, `1d84d4b`, `c8dd5bc`, `2b23601`,
`<this one>`. Full suite green: **1537 passed**.

Revised after the first cut broke the live fleet — see "How this changed" below.

## Two shapes, and the disk says which

| On disk | Mode | Behaviour |
|---|---|---|
| `p-<n>.json` files, or `_meta.json` | **split** | one plan per file, all the Phase 1 machinery |
| a single `plans.json`, or nothing yet | **legacy** | read AND written as format 1, byte for byte what an older plugin writes |

`_read` probes the directory. **Nothing that reads or writes ever changes the shape.**
A fresh store starts legacy, so a repo with a new plugin stays readable by an old one.

## `sb plugin plans migrate`

The only thing that moves a store across. It is a verb because the store belongs to the
repo, every worktree shares one, and worktrees adopt a new plugin one at a time.

- Writes `p-<n>.json` per plan + `_meta.json` (format 2), archives the old file as
  `plans.json.migrated`, leaves a format-2 tombstone at `plans.json`.
- Idempotent — says "already one file per plan" rather than pretending.
- Its output **is** the warning: this flips the store for the whole repo, worktrees still
  on the old plugin will refuse everything, and here is how to put it back.
- An empty store migrates too, so a repo that migrates before its first plan does not
  silently stay old.

## What the split shape buys

- `_check` is **per file**: a corrupt `p-7.json` costs p-7 and nothing else. The other
  plans load and the board draws them.
- Skipped is not silent — `list` names every file that did not load, with its path.
- `_write` writes only the plans a command actually touched.
- Cross-file invariants are checked over the assembled store: a plan lives in the file its
  id names, and a step id is unique across the store (`tick s-7` names no plan).

## Files

| File | What |
|---|---|
| `defaults/plugins/plans/__init__.py` | the I/O core, the `migrate` verb, GUIDE, prose |
| `defaults/plugins/plans/board.py` | prose only — the read seam at line 117 needed **no** change |
| `tests/test_plans_plugin.py` | dual-mode helpers; new `LegacyStoreTest` and `MigrationTest` |
| `tests/test_board.py` | a legacy-store test and a broken-file test |
| `defaults/plugins/plans/analysis/{evidence.py,SKILL.md}` | prose only |

## What Phase 2 needs to know

- `_read` returns **`doc["broken"]`** in both modes: `{"id", "file", "why"}` per file that
  did not load in split mode, and **always `[]`** in legacy mode (one file means a plan
  that did not load means none of them did — the read refuses instead). So Phase 2 can
  read `doc["broken"]` unconditionally without knowing the shape.
- Enumeration helpers: `_split(d)`, `_files(d)` (plan files in id order), `_fnum(f)`.
- `list` already prints one `! p-N did not load …` line above the plans that did load.
- **The live store is legacy** and will stay that way until somebody runs `migrate`. Any
  Phase 2 work must not assume the split shape.

## How this changed (the revision)

The first cut migrated on read. The real store flipped to format 2 the moment one worktree
ran the new plugin, and every worktree still on main's single-file plugin then refused
every plans command. Migration is now a verb, an un-migrated store is read and written as
format 1, and the live store has been restored.

**Live store restored.** `plans.json.migrated` was verified byte-identical to the per-file
store (11 plans p-2..p-12, counters 13/67, no drift since the migration), the whole
directory was backed up, and the restore ran under the same `flock` every plans command
takes: the archive moved back over the tombstone, then the `p-*.json` files and
`_meta.json` were removed. The store is now exactly the format-1 single file it was, having
lost no records.

## Verification (live, in `git clone`s, all torn down)

- **Interop, the claim that matters.** One store, alternating plugins between commands:
  main's plugin created p-13, the new plugin read it and created p-14, main's plugin read
  that back and wrote again. Format stayed 1, one `plans.json`, no fork.
- The restored live store is accepted by main's old plugin again.
- Reading the live store from this worktree does **not** re-create the split layout.
- `migrate` on a 13-plan store moved every plan, printed the warning, was a clean no-op on
  a second run — and main's plugin then refused, which is the intended coordinated break.
- A corrupted `p-7.json` in split mode is named on its own line and the other plans still
  list; exit 0; the broken file is byte-identical afterwards.
- A `note` in split mode rewrites only that plan's file (mtime-checked).

## Unproven

- Two processes racing `migrate`. It is under the dir lock and is a thing a person types
  once, but nothing provokes the race.
- The lock is **not** re-scoped. The split shape buys blast radius, not write contention.
- Nothing tests an old plugin and a new one writing the same legacy store *concurrently* —
  only interleaved. The dir lock is shared between them, so this should hold, but it is
  reasoning rather than proof.
