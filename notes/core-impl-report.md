# core-impl report — plan p-18, step s-95

Commit `17c210d` on `change-approval-build`. Full suite green: 1645 passed.

## What landed

- **New definitions** — `defaults/plugins/plans/library/change-approval.json`,
  `review.json`. `create-pr.json` obliges `change-approval`, which obliges `review`, so
  naming `create-pr` lands three steps; its `about` now says two of the three need
  re-deping by hand.
- **New step field `output`** — `defaults/plugins/plans/__init__.py`. Written by hand by
  the agent that did the step, no verb, never through `_cap`. Documented beside `gate` in
  `_step()` and in the module docstring's step sketch.
- **The dump** — `show --markdown` renders `output` as a blockquoted BLOCK
  (`_BLOCK = ("output",)`) instead of flattening its newlines. `_tabular` refuses a table
  for any step carrying one; a block is never a bullet's label; a non-string value falls
  back to the old path. Terminal `show` prints `out <line>` per line, split first.
- **Preset re-sectioned** — `defaults/presets/design-gate.md`: bullet mechanics separated
  from the sections, which the naming step now owns. Same filename, still
  `sb presets design-gate`. `merge-human-review.json` repointed to the format, not the
  sections.
- **Docstring staleness** — both places enumerating the catalogue now include the pair.
- **Tests** — `tests/test_plans_plugin.py`: 13 new (obligation chain ×4, markdown dump ×6,
  definitions ×3), plus re-pins of the step-schema assertion and the preset section test.

## Locked decisions honoured

Prose-only gate (`gate` stays null, `_wrong` untouched, pinned test unchanged); hand
re-dep accepted, no new schema field; the worker writes its own `output`; the preset owns
bullet mechanics only; `output` written as markdown-ready two-space nesting.

## Unproven

No live end-to-end run of a real change-approval step through a real block → approve →
tick cycle, and no dumped `output` has been posted onto a real PR comment. The tests drive
the real `bin/sb` against a sandbox store, and I eyeballed both the markdown and terminal
renderings directly — both correct.

## Not done (not my scope)

`design/*.md` reconciliation, including `design/PLANS-AND-STEPS.md:367-388`, which still
specifies the old design gate. The design-docs worker owns that.
