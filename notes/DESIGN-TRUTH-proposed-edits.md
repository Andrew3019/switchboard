# DESIGN-TRUTH.md — proposed wording changes (for Andrew only)

The board-UI change makes step display names **required** and **removes the per-cell clip**,
adds a **plan-level display name**, and makes **deps required**. That contradicts the
confirmed "display is optional / falls back to name clipped" entry. Per the standing
consistency-pass rule I re-read § Plans and § Interface; below are the exact edits. **Only
you edit DESIGN-TRUTH.md** — I have not touched it.

Storage (per-plan JSON files) needs **no** DESIGN-TRUTH edit — there is no storage-shape
entry there today, and it does not contradict anything in the doc.

---

## 1. REPLACE the display entry (currently lines ~422-428)

**Current:**
> **A step may carry a short display name for the board, separate from its full name.** …
> It is optional, and it pairs with the name exactly … a step without one falls back to its
> name clipped. …

**Proposed replacement:**

> **Every step carries a short display name for the board, and so does the plan.** A step's
> name is a sentence and a board cell is a few columns, so a step named "list every claim the
> document makes about the code" is authored with a display like "list claims" — as short as
> it can be made, abbreviating and dropping middle vowels where that helps. It is **required**
> on every step, not optional: a cell with no display drew the name clipped mid-clause and the
> informative half was the half cut, so the board was unreadable until it was authored. It
> pairs with the name exactly — a named step's display lives in its definition and an edit to
> it reaches every plan naming that step; an on-the-fly step's lives on the step. A **plan**
> carries its own display too, **longer** than a step's since it owns the whole header line,
> and a display *version* of the title rather than an abbreviation of it; the board draws it
> **instead of** the title, and a plan authored without one falls back to its title. There is
> no per-cell clip any more — display names are short by construction, and the only clipping
> left is the board's own from the right when the pane is narrow. — confirmed 2026-08-18

## 2. ADD a new entry, right after it, for deps + enforcement

> **A step names what it comes after, and every step but the plan's first must.** The board
> is a DAG drawn from the deps, so a plan recording no order between its steps renders as a
> loose vertical stack with no arrows — which is what every early plan did. The first step is
> the exempt root; a plan with a genuine second start reports it, since nothing can tell a
> deliberate second root from a forgotten edge and the warning is survivable. Display and deps
> are required in more than one place, because a plan is edited by hand as often as by command:
> the shape verbs (`create`, `add-step`, `name-step`, `template use`) **refuse** to mint a step
> with no display; every other write **warns and still writes**, naming the offending steps —
> a `tick` that would not land because of a rendering rule is worse than the rendering; and the
> board draws the defect **red**. Completeness is never a whole-file refusal — that is
> `_check`'s job and it stays structure-only. — confirmed 2026-08-18

## 3. TOUCH the § Interface board entry (currently lines ~460-468)

The entry ends: *"…as a left-to-right flowchart, coloured by progress rather than columned,
with the short display name of each step in the cell."* Consider appending one clause so it
stays current:

> … with the short display name of each step in the cell, the plan's own display as the
> header, and any plan or step still missing a display or a dep drawn in red.

(Optional — the entry is not wrong without it, only less complete.)
