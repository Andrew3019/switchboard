# Board-UI + per-plan-storage — lead's plan and locked decisions

Lead: `plans-board-ui-implement`. Combines the settled board-UI change
(`notes/board-ui-required-display-deps-brief.md`) with the new storage-model change
(one JSON file per plan). Storage scout map: `notes/plans-storage-scout-findings.md`.

## Shape

Two implementation phases, **sequenced** (both heavily edit `__init__.py` + `board.py` +
the same test files, so they must not run concurrently):

1. **Phase 1 — storage.** Reshape the I/O core to one-file-per-plan + migration. Foundation.
2. **Phase 2 — board-UI.** Required display/deps, 3-door enforcement, authoring syntax,
   rendering (header/clip/arrows/red-defects), on top of Phase 1's per-file world.

Then: verify in an isolated clone + full suite, open PR, merge (pre-approved). Hand Andrew
the DESIGN-TRUTH wording (board-UI §6) + the storage decisions below for confirmation.
Command removal (board-UI §8) stays a separate decision — not in this work.

## Locked storage decisions (lead's calls, parent said use judgment)

- **One file per plan**, flat `p-<n>.json`, under the existing state dir
  (`$(git rev-parse --git-common-dir)/agentflow/plugins/plans/`).
- **Small sidecar meta file** (`_meta.json`) holds `format`, `next_plan`, `next_step`.
  Self-healing backstop: recompute by scanning `p-*.json` when meta is missing/corrupt
  (preserves today's self-heal behaviour).
- **Global step-id uniqueness PRESERVED.** `tick s-7` must keep working with no plan named
  (deliberate UX contract in `_locate`, __init__.py:2179). `_read` enumerates the plan
  files; `_locate` finds the step across them.
- **`_check` becomes per-file.** A corrupt `p-7.json` refuses only p-7; the board draws the
  other plans and flags p-7 broken. This blast-radius isolation is the primary real win.
- **`_write` writes only the touched plan's file** (+ meta when a counter advances).
  `_seal`/append-only enforcement becomes per-file.
- **Eager one-time migration.** Read current `plans.json` → N per-plan files + meta,
  archive/remove old file, preserving every changelog byte-for-byte. Only 10 plans live.
- **Lock NOT re-scoped.** It stays dir-scoped (`switchboard/plugins.py:670`). Therefore this
  change does **not** reduce write contention — the real benefit is blast-radius, not
  concurrency. Re-scoping the lock per-file is a separate change; NOT done here. Flag to
  Andrew in case contention was his motivation.
- **GUIDE + prose.** Hand-edit path (__init__.py:558) becomes the per-plan path; reword the
  ~5 prose "plans.json" references to not name one file.

## Locked board-UI decisions (lead's calls, brief left open)

- **Authoring syntax:** single flag `--step "invstgt = the full name"` (`display = name`,
  one flag because two parallel lists desync silently) + `add-step --display`.
- **`create --step`:** auto-chain steps in the order given; author reshapes with `dep`.
  Makes the common one-shot `create` compliant instead of instantly warning.

## Forks surfaced to Andrew (not blocking; proceeding with above)

Filename convention, counters location, migration approach, step-id uniqueness — all
decided above with justification; Andrew can veto cheaply since all are reversible. The one
worth his active attention: the **contention finding** (per-file ≠ less contention).
