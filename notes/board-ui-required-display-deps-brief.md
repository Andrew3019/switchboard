# Board UI: required display names and deps — handoff to a lead

Written 2026-08-18 by `plans-board-ui-discuss` (a worker) after three rounds of live
discussion with Andrew. Andrew stopped the implementation and asked for a lead to take it
on. **Everything settled with him is below; nothing here is open unless it says so.**

Andrew has given **full approval to ship this end to end. Merging is pre-approved.
Cleanup is pre-approved.** He is asleep as of writing.

---

## 0. Start from latest main

Andrew asked explicitly that this be built on **latest `main`**. At the time of writing
that is `409b9bb` (`block: only one agent waits on a person for one question (#119)`).
The `plans-board-ui-discuss` branch is 3 commits behind and holds nothing but this file.

---

## 1. The original complaint

Andrew, verbatim: *"still dont like the board ui. what does it look like now? is it what i
wanted?"*

The board UI had already been through PR #107 (plans as a PLANS section, steps as a
left-to-right DAG flowchart coloured by progress), #110 (board agreeing with `show`,
measuring in columns, numeric deps), #108 (optional short `display` label per step) and
#112 (library listing column glue). He still didn't like it.

## 2. Why he didn't like it — the diagnosis

**The flowchart has never once been drawn.**

- Not one plan in the store sets `deps` on any step. All 28 steps across the 5 live plans
  have `deps: []`.
- With no deps every step is a root, every step lands in column 0, and `_chart` renders a
  vertical stack with zero arrows.
- Almost no hand-written step sets `display` either, so cells fall back to the full name
  and get clipped at `NAME_W = 22` — producing a column of half-sentences
  (`Investigate: find the…`, `add ~3 tests for _clo…`) where the clipped half is the
  informative half.

The renderer itself is fine. Fed real deps it draws exactly what #107 promised.

**Root cause of the empty fields:** `GUIDE` tells the plan's owner to edit `plans.json`
in an editor — *"past the commands above you edit it the way you edit any file — steps,
owners, gates, deps, order, progress, all of it"*. So the commands were never the path
most plans were authored through, and command-layer defaults/requirements caught nothing.
Andrew spotted this himself and it is the reason enforcement has to live in more than one
place (§4).

## 3. What Andrew decided — the settled design

### 3a. Plan header shows the display name INSTEAD of the title

He was shown `p-2 ci-rich   Fix red CI on main: …` (both) and rejected it:

> *"is this display name and full name? i want display name longer (since this one has the
> entire line unlike steps). it should be a more 'display' versoin of full name, and we just
> dont show full name."*

So: a plan carries its own `display`. It is **longer than a step's** — it owns the whole
line — and it is a *display version of the title*, not an abbreviation. The full title is
**not drawn on the board at all**. Fall back to the title when `display` is absent.

Target shape:

```
p-2  fix red CI: rich assertions on main   ·  finished  ·  5 steps
  invstgt ──→ decide fix ──→ implmnt ──→ verify ──→ PR+merge

p-6  _close_board orphans panes on herdr failure   ·  live  ·  5 steps
  implmnt ──→ tests ──→ PR ──→ merge ──→ hmn revw
```

### 3b. Step display names: required, no length cap

> *"a display name should be made for every step + plan overall name too. must be as short
> as possible, can u abbreviations or like shortening or even like removing middle vowels"*
>
> *"lets not cap display length for steps either. lets see how it goes."*

- Required on every step.
- **No cap.** A cap was what produced the half-sentences; length is the author's judgement.
- Authored aggressively short: abbreviate, drop middle vowels, cut what the plan title
  already says. `investigate the failing assertions` → `invstgt`; `human review` → `hmn revw`.

### 3c. Deps required

> *"deps and display name should be required. block if a step wihtout deps (other than
> first step) makes sense still"*

Every step **except a root** names what it comes after. A plan's first step is the
exempt root. (A plan that genuinely has two starts will report the second — that is
accepted; nothing can distinguish a deliberate second root from a missing edge, and the
warning is survivable.)

### 3d. Clipping is the pane's job, not the cell's

> *"make sure it handles clipping, i.e. works if i expand the pane, clips if pane is small
> (fine for now)"*

Remove the per-cell `NAME_W = 22` clip entirely. Display names are short by construction
now. The only clip left is the board's own from the right: wide pane shows everything,
narrow pane cuts the tail of the longest chain.

### 3e. Arrows are too long — **his last note, do not miss it**

> *"the dependency arrows are too long. it should be like 2-3 chars max. right now its
> -----> or something like that."*

Currently a linear hop draws as `───→` (4 columns) plus a padding space each side.

The knob is in `board.py::_gap`. `span = 2 + len(order) + 1` is *stub(2) + one channel per
bundle + the arrowhead column*, and `ch = 2 + k` places each channel past that same stub.
Dropping the stub from 2 to 1 gives `──→`; to 0 gives `─→`. Introduce it as a named
constant rather than leaving the `2` twice as a literal, and check the fan-out/fan-in and
long-edge (placeholder) cases still line up — `_cell` pads placeholders with `─` on the
assumption that a through-edge arrives and leaves unbroken.

## 4. Enforcement — three doors, agreed with him

He asked *"a. refuse when authoring or editing? no need to change the current ones. make
sure it doesnt break anythign running (or at least agents know to fix it)"*, then raised
the JSON-editing point himself. The agreed answer:

1. **Shape verbs refuse.** `create`, `add-step`, `name-step`, `template use` will not mint
   a step with no display name. Refusal message must say *what a good one looks like* —
   "display is required" alone just gets the full name typed again.
2. **Every other write warns and still writes.** After the write, recompute completeness
   and append a warning naming the offending step ids and the fix. **Warns, never refuses**
   — a `tick` that will not land because of a rendering rule is worse than the rendering.
   This is the door that catches hand-edited JSON.
3. **`show`, `list` and the board draw the defect.** A hand-edited plan nobody has run a
   verb against is still visibly wrong where it matters. Board draws it red.

**`_check` must NOT become a door.** It refuses the whole *file*, which would take the
board down — and every existing plan is missing both fields. `_check` is for structure;
completeness is a separate, always-survivable check.

**Existing plans are left alone** (`"no need to change the current ones"`). They will show
warnings until someone fixes them; that is the intended discovery path.

### Suggested implementation shape (not binding)

- `_defects(plan) -> list[str]` over a **resolved** plan (`_shown`), since a linked step's
  `display` correctly lives in its definition, not on the step.
- `_incomplete(plan, lib)` / a `_with_defects(result, plan, lib)` wrapper that appends to
  `human` and adds an `incomplete` key to `data`, preserving `ok=True`.
- Pass `lib` in rather than fetching it — this runs *after* `_write`, and a read that could
  refuse there turns a landed mutation into a reported failure. (`_shown` already documents
  this rule.)
- **Authoring syntax is open.** The worker proposed inline `--step "invstgt = the full
  name"` (one flag, because `--step` repeats and two parallel lists desync silently) plus
  `add-step --display`. Andrew's answer was *"idk"* — **he did not choose. The lead picks.**

## 5. Open decision the worker deliberately did not take

`create --step a --step b …` currently produces steps with no deps, which the new rule
makes immediately non-compliant. Two options:

- **Auto-chain** them in the order given (the order typed *is* an order) and let the author
  reshape with `dep`. Makes the common case right in one command.
- **Refuse**, forcing explicit `dep` calls. Truer to "deps are authored", but makes
  one-shot `create` with steps nearly unusable.

The worker leaned auto-chain but did not want to infer intent unilaterally. **Lead's call.**

## 6. DESIGN-TRUTH conflict — needs Andrew, do not edit it yourself

`DESIGN-TRUTH.md` (§ Plans, confirmed **2026-08-18**, i.e. the same day) currently says:

> **A step may carry a short display name for the board, separate from its full name.** …
> **It is optional**, and it pairs with the name exactly … and a step without one falls back
> to its **name clipped**.

This change makes it **required** and **removes the clip**. It also adds a plan-level
display name and a deps requirement, neither of which the doc mentions. Only Andrew edits
`DESIGN-TRUTH.md`.

**Action for the lead:** ship the code, and hand Andrew the exact wording changes needed —
at minimum (a) display optional → required, (b) fallback "name clipped" → no per-cell clip,
(c) a new entry for the plan-level display name, (d) a new entry for deps being required.
The § Interface entry at line ~460 also describes the board and may need a touch. Per the
standing memory *"DESIGN-TRUTH.md consistency pass"*, that means re-reading the whole doc,
not appending.

## 7. Third issue he raised — board inconsistent across tabs (INVESTIGATED, not a bug)

> *"very inconsistent display of plans on differrent tabs of sb board right now. not sure
> if just due to board collector version"*

**It is not the collector.** Each board pane imports the plans plugin **from its own
worktree's checkout**, and `board.board_hooks()` caches the import **once per process**
(`_HOOKS`, keyed on worktree). Live right now:

| version of `defaults/plugins/plans/board.py` | worktrees |
|---|---|
| `d8a6a663` (current main) | 12 |
| `5aa12640` | 4 |
| `a1ef4a7e` | 2 |
| `de930308` | 2 |
| **plugin absent entirely** | **5** |

Four renderers live at once, and five worktrees are on branches predating the plugin — those
tabs draw **no PLANS section at all**. Every tab is faithfully running its own branch's code.

Two smaller contributors, both by design in `richboard.layout`: a short pane **drops the
entire PLANS section** rather than half-drawing it (`if room < 1 and below: below = []`),
and a narrower pane truncates more.

**This converges as branches merge.** Andrew was told this and did not ask for a change.
Making the board read one pinned version rather than its own worktree's would be a real and
separate change — **do not do it as part of this work.**

## 8. Command removal — "consider", explicitly optional

> *"if it makes things better, consider reomving some sb notes comands. ones that are
> completely redundant and superseeded by the lead/sole worked editing the json files
> directly."*

`GUIDE` already says only two verbs are worth typing: *"Two verbs are worth typing rather
than editing, being frequent and small — `tick <step>` … and `note <step> --text` … They
write the changelog entry for you, which is the whole of what they buy."*

By that logic the redundant candidates are `assign`, `checkpoint`, `rework`, `gate`, `skip`.

**The worker's recommendation was to NOT remove them in this PR**, for two reasons:
`gate` and `skip` carry design significance recorded in `DESIGN-TRUTH.md` (gates as exit
conditions; "a skip is a state, never an absence") and have dedicated test classes
(`GateTest`), so removing them is a design change needing Andrew, not a cleanup. If the
lead disagrees, it should be a **separate PR** from the board work.

## 9. Bonus defect spotted, not yet fixed

`sb plugin plans list --all` glues the workspace column to the title:

```
p-4   6 steps   finished   design-truth-plans-applyapply the 8 approved DESIGN-TRUTH.md edits…
```

`_line` uses `f"{_where(p):<24}"`, which pads a short value and does nothing to a long one.
Exactly the bug `_key_col` was written to fix for the library listing in PR #112 — same
class, different column. `_key_col`'s two-space floor is the pattern to copy. Small, safe,
worth folding in.

---

## 10. Code map

| what | where |
|---|---|
| plugin core, all verbs, `_check`, `_step`, `_resolve`, `_shown`, `GUIDE` | `defaults/plugins/plans/__init__.py` (2474 lines) |
| board drawer: `board_lines`, `_header`, `_chart`, `_layers`, `_route`, `_place`, `_draw`, `_cell`, `_label`, `_paint`, `_gap` | `defaults/plugins/plans/board.py` (569 lines) |
| `NAME_W = 22` (the per-cell clip to remove) | `board.py` |
| arrow stub constant (`span = 2 + len(order) + 1`, `ch = 2 + k`) | `board.py::_gap` |
| plan header (`_header`) — switch to plan `display` | `board.py` |
| `_line` workspace column glue | `__init__.py` |
| step record shape (already has a `display` field) | `__init__.py::_step` |
| display resolution from the library | `__init__.py::_resolve` |
| the board seam, `_HOOKS` cache, `_hook_lines` | `switchboard/board.py` |
| section sizing / drop-on-short-pane | `switchboard/richboard.py::layout`, `_plugin_sections` |
| library defs (already carry `display`) | `defaults/plugins/plans/library/*.json` |
| `docs` template (carries `display`, **no deps** — needs them now) | `defaults/plugins/plans/templates/docs.json` |
| tests | `tests/test_plans_plugin.py` (1695), `tests/test_board.py` (1633), `tests/test_plans_analysis.py` |

**Test blast radius:** many tests call `create --step "…"` with no display name. Making
display required at authoring breaks them. Mechanical but broad — budget for it.

`GUIDE` (in `__init__.py`, printed by `sb plugin plans guide`) must gain the rule: every
step needs a display name and deps, plus how to shorten one. It currently mentions deps
only in passing (*"a template brings steps but no order between them … or the plan renders
as a loose stack"*) and never mentions `display` at all.

## 11. Housekeeping

- The worker created plan **`p-10`** on workspace `plans-board-ui-discuss` for this work
  before being stopped. Records are never erased — the lead should make its own plan and
  can leave `p-10` alone or note it as superseded.
- **No code changes were made.** The worker's only edit was rejected mid-flight; the
  working tree is clean apart from this file.

## 12. Testing and verification (repo standing rules)

- `python -m pytest tests` — on Andrew's machine use `/Users/andrew/anaconda3/bin/python`.
- Live proof belongs in an **isolated clone** (`git clone` of this repo into a scratch dir,
  check out the branch, drive that clone's own `./bin/sb`). Never run a clone's `sb` from
  outside it. Tear down with `sb cleanup` / `sb workspace close` — **never** raw
  `herdr workspace close`, and never an unscoped `pkill`.
- Board rendering can be exercised without a live board by importing
  `defaults.plugins.plans.board` and calling `board_lines(state_dir, workspace, rows)` or
  `_chart(steps)` directly against the real `plans.json` at
  `$(git rev-parse --git-common-dir)/agentflow/plugins/plans/plans.json`.
