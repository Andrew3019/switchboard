# #4 command-surface implementation — report

Commit `191c85a` on `plans-board-ui-implement`. No branch/PR ops, as briefed. Full suite
green (`1579 passed`), run twice.

## Removed

`assign`, `checkpoint`, `rework`, `gate`, `skip` — handlers and `register()` entries.
Kept `tick`/`note`/`dep`, the minting verbs (`create`, `add-step`, `name-step`,
`template use`) and every read verb. The DATA is unchanged: a step still carries `owner`,
`gate`, `progress: "skipped"`, `why`, `tries`, `checkpoints` — a lead writes them by
editing the JSON.

## Guards moved, not lost

New `_wrong()` in `defaults/plugins/plans/__init__.py`, feeding `_defects` (printed under
every write, and by `show`/`list`/`validate`) and `_defective` (the board paints the step
red). Three rules:

- a `gate` on a step already `done`
- `progress: "skipped"` with no `why`
- a checkpoint `ref` carrying a control character or a `|` (anything that forges a row)

Warn only — never a refusal, never `_check`. This is **wider** than the verbs were: the
verbs never saw a hand-edit, which is how these fields arrive now.

## `validate`

`sb plugin plans validate [<id>...]` — no id checks every plan. Prints `_broke` plus the
`_defects` lines per plan, or `no defects in N plans`.
`data = {ok, plans: [{id, file, defects}], broken}`. **Always exit 0**, including for a
file that will not parse (reported, not raised) and for an id that names nothing.

## Path on create

`create` and `template use` append
`the plan is <path> — edit it there, then sb plugin plans validate` and add `data["file"]`.
Post-migrate that is `p-<n>.json`; on a legacy store it points at `plans.json` rather than
inventing a path.

## The lock decision

`LOCK = False` — no coarse lock on any command, reads included. Two mechanisms replace it:

1. **`_minting()`** — a short `flock` on `<state_dir>/.mint.lock`, held by the four
   allocating verbs only, across their read/mint/write. Step ids come from a store-wide
   counter, so that is the one race per-file storage does not answer by itself.
2. **`_reserve()`** — the new plan's `p-<n>.json` is claimed with `O_EXCL` and the id bumps
   on collision. Needs nobody's cooperation, so it holds where `flock` does not (a network
   mount, another plugin version).

### Residual races (in code comments and here)

- **Two writers on ONE plan**: last write wins. Left to the design's one-writer-per-plan
  convention, as the brief instructed — a hand-edit in an editor takes no lock and never
  could.
- **An un-migrated store** (single `plans.json`): every plan is in one file, so the above
  applies at repo scale, and concurrent minting there can still collide — the mint lock
  serialises the verbs but the counters live in the file the verbs are racing on.
  Transitional; this repo has migrated.

## Vowels

`_SHORTEN` and the GUIDE now say short but READ as words — `list every claim the document
makes` → `list claims`, `human review` → `review`. Every `invstgt`/`hmn revw` example is
gone from code and tests.

## GUIDE

New section head: `EDITING IT — THIS IS THE NORMAL WAY, NOT THE FALLBACK`, with the
create → path → edit → `validate` shape, `tick`/`note`/`dep` as the three worth typing, and
what `validate` is for. The module docstring was reworked to match (verb list, gates,
storage/lock paragraph).

## Tests — moved, not deleted

- `GateTest`'s 8 rewritten as gate-as-a-field, plus the gate-on-done rule as a warning.
- `StepsTest`'s assign/skip/checkpoint/rework cases rewritten as hand-edits asserting the
  same rules; new `PlansSandbox.edit_step()` helper.
- New `HandEditTest` (6): the three moved guards, a sound edit staying silent, `validate`
  on one/all/unknown-id/unreadable, the printed path, the legacy path.
- New `PlansTest` tests: no coarse lock and the mint lock only on minting verbs; the
  `O_EXCL` race.
- New `test_board` test: the moved guards draw red.

## Live proof (isolated clone, torn down)

- `create` printed the `p-1.json` path; `validate` said `no defects`.
- Hand-broke the file (gate on done, skip with no reason, checkpoint with a newline):
  `validate` reported all three, exit 0; `tick` on that plan still landed.
- Made the file unparseable: `validate` reported it, exit 0; `show` still exited 1.
- **6 concurrent real `sb create` processes** → 6 distinct plans, 6 files, 12 unique step
  ids, `no defects`. Only `.mint.lock` is ever created; `.lock` never is.

## Out of scope, noted for the lead

`DESIGN-TRUTH.md` and `design/PLANS-AND-STEPS.md` still describe `gate`/`skip` as verbs and
still carry the stale "optional / falls back to its name clipped" display wording. The doc
pass is yours. I did update `defaults/plugins/plans/analysis/SKILL.md`'s do-not-use verb
list, which named five verbs that no longer exist.

## Unproven

- That the board's few-second redraw surfaces a fresh hand-edit in a live fleet. The
  drawing itself is tested; the interval is switchboard's.
- Endurance/long-run behaviour of the lock-free store.
