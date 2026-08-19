# Phase 2 — board UI: what landed, and the calls I had to make

Worker `plans-board-ui-feat`, 2026-08-18. Commit `e8c1e64` on `plans-board-ui-implement`.
Full suite green: 1547 passed (`/Users/andrew/anaconda3/bin/python -m pytest tests`).

## Landed

- **Plan `display`** — `create --display`, `template use --display` (or the template's own).
  The board header draws it INSTEAD of the title; `show` prints both (`board` line).
- **Step `display` required, no cap.** `NAME_W = 22` and the per-cell clip are gone; the
  pane's clip from the right is the only one left.
- **Deps required** past the plan's first step. A second root warns and is accepted.
- **Arrows** are `──→` off a named `STUB = 1` in `board.py::_gap`, shared by `span` and
  `ch`. Fan-out, fan-in and long-edge placeholder cases all re-checked and line up.
- **Three doors.** Shape verbs refuse with a worked example (`_no_display`, `_SHORTEN`);
  every other write appends `_defects` and still writes (`_changed`/`_added`/`_plan_result`,
  `data["incomplete"]`, `ok` stays true); `show`/`list`/board draw it, board in RED.
  `_check` untouched — completeness is never a file refusal.
- **Authoring**: one flag, `--step "invstgt = the full name"`; `add-step --display`;
  `create --step` auto-chains in the order given.
- `_line`'s workspace column now uses the two-space floor (`_col`, shared with `_key_col`).
- `docs` template: plan display + `after` between entries. GUIDE has the whole rule.

## Calls I had to make (the brief left these open)

1. **Plan display is REQUIRED at `create` and `template use`**, not just warned about. §4's
   door-1 list names steps only; Andrew's "a display name should be made for every step +
   plan overall name too" reads as required, and the board falling back to the title covers
   every plan made before this. Cheap to soften to a warning if he disagrees.
2. **Templates express order with `after`** — 1-based entry positions, wired by `_chain` to
   each entry's roots and the previous entry's sinks. Auto-chaining a template the way
   `create` chains its steps would have put the obliged human review AFTER the merge.
3. **An obliging step now comes after what it obliged** (`_mint` adds the edge): `merge`
   waits on `merge-human-review`, which is what the library's own prose says the review is
   for. Without it every obliged step lands as a second root. This is the one change
   outside the brief's letter; it is two lines and reversible.
4. **`name-step` refuses a definition with no `display`** rather than inventing one — the
   label lives in the library so the plan stays a link, not a copy.
5. **`list` gained a leading `!`/space column** for the defect marker, so every listing line
   is one character further right than it was.

## Unproven

- No live board pane was driven: rendering was proven by calling `board_lines` against a
  real store in an isolated clone (header, red defect, chains, arrow width all as intended),
  not by looking at tmux. The seam itself is unchanged.
- A defective step with no display still falls back to its whole sentence, and that widens
  its column — the chain after it is pushed right. Inherent to dropping the cap; only an
  incomplete step can do it, and it is drawn red.
