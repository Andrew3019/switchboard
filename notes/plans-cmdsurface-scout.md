# Scout: plans command surface + sb hook system, for the "edit JSON directly" redesign

Repo: board-UI + per-plan-storage branch. Plugin: `defaults/plugins/plans/__init__.py` (3283
lines), board drawer `defaults/plugins/plans/board.py` (608 lines), tests
`tests/test_plans_plugin.py` (92 tests, 10 classes).

## 1. The full verb list

Registered in `register()`, `defaults/plugins/plans/__init__.py:400-502`.

| verb | file:line (handler) | what it does | sugar or load-bearing? |
|---|---|---|---|
| `guide` | `652` `guide()` | prints the static plan-making instruction (`GUIDE` string, `532-646`) | pure text, no store access |
| `create` | `662` `create()` | new plan + chained steps, resolves workspace via `_workspace()` (shells to `sb inspect`/`sb workspace list`), mints ids from the shared counter, refuses missing display names | **load-bearing** — id-minting, workspace resolution (subprocess), display refusal can't be done by hand-editing a file that doesn't exist yet |
| `list` | `734` `ls()` | plans on this worktree, resolves library + liveness (`_Live`) | load-bearing (read path, not a mutation) |
| `show` | `784` `show()` | one plan, library-resolved, liveness-resolved | load-bearing (read path) |
| `changelog` | `804` `changelog()` | changelog only | load-bearing (read path) |
| `assign` | `826` `assign()` | writes `step["owner"]`, logs a changelog entry | **pure sugar** — a hand-edit of `owner` + appending a changelog entry does the same; the only thing the verb buys is the changelog append and the "was X" diff line |
| `tick` | `851` `tick()` | writes `progress: "done"`, `why: null`, changelog entry | **mostly sugar** — a hand-edit could set the two fields; the changelog append is the only thing not reproducible without care. Design docstring (`33-42`) makes a point of `tick` being the *only* thing that writes `done` — that's a stated design invariant currently enforced only by convention (no code stops a hand-edit from writing `progress: "done"` directly) |
| `skip` | `866` `skip()` | writes `progress: "skipped"`, `why: reason`, changelog; **refuses without `--reason`** | **sugar + one real check** — the only thing a hand-edit can't trivially replicate is "reason is mandatory," and that's a soft rule (nothing stops writing `progress:"skipped", why:null` by hand either) |
| `gate` | `886` `gate()` | writes `step["gate"]`, changelog; **refuses if step is already `done`** (`917-923`) | **the one verb with a real invariant** — "no gate on a done step" is enforced in code, not just convention. A hand-edit has nothing stopping it from setting `gate` on a done step. This is Andrew's own candidate for removal, and it's the one with an actual guard behind it, however small |
| `note` | `931` `note()` | append a note to a step or a plan (dispatches on prefix of `target`) | **pure sugar** for a step note; plan-note path does a bit more (`_lib` before write, per module convention) but nothing a hand-edit + changelog append can't do |
| `checkpoint` | `972` `checkpoint()` | append `{ref, by, at}` to `step["checkpoints"]`; **refuses a ref with a newline** | sugar + one refusal (multi-line-paste guard) — a hand-edit could still write a checkpoint with a newline in it; nothing at read time re-checks this (see §4) |
| `rework` | `999` `rework()` | bumps `tries`, resets `progress` to `open`, sets `why` | pure sugar |
| `add-step` | `1031` `add_step()` | mints a new step id from the shared counter, appends to `plan["steps"]`, **refuses missing display** | **load-bearing for the id mint** — a hand-edit adding a step needs to know the current `next_step` counter (stored in `_meta.json` / doc, not obvious) and get it right or risk an id collision that `_check` will only catch on next read. The refusal-on-no-display is also enforced nowhere else for a brand-new step |
| `library` | `1164` `library()` | read-only catalogue browse | load-bearing (nothing to hand-edit; it's a read of `library/*.json`) |
| `name-step` | `1194` `name_step()` | expands a library definition into steps + obligations, mints ids, links via `def`, **wires up `deps`/`obliged_by`** (`_mint`, `1763-1831`) | **the most load-bearing mutation verb**. Composition + obligation expansion (recursive, cycle-checked, `_flatten`/`_mint`, `1728-1831`) is real logic — hand-typing the resulting steps, deps and `obliged_by` links correctly is exactly the kind of error-prone busywork the module docstring says this exists to prevent (`149-179`) |
| `template` | `1242` `template()` | `list` (read-only) / `use` (copies a template, expanding library links same as `name-step`, chaining `after` positions — `_chain`, `1340-1376`) | **load-bearing** (`use` half) — same reasoning as `name-step`, plus template `after`-position resolution logic |
| `dep` | `1067` `dep()` | appends an edge to `step["deps"]`, **refuses self-edges, cross-plan edges, edges to nonexistent steps** | **sugar + real checks** — the three refusals (`1067-1121`) are exactly the kind of typo-catching a hand-edit loses. Nothing at read time re-validates a `deps` edge (see §4) |
| `migrate` | `1131` `migrate()` | one-time store format migration | infrastructure verb, unrelated to the "edit-vs-verb" question |

**The redundant/load-bearing split, plainly stated:**

- **Pure sugar** (a careful hand-edit + changelog append reproduces it exactly): `assign`,
  `note` (step half), `rework`. `tick`/`skip` are sugar too, but `tick` carries a stated
  design invariant ("only `tick` writes `done`") that today is enforced by nobody typing
  anything else, not by code.
- **Sugar with one real guard that a hand-edit bypasses**: `skip` (`--reason` required),
  `checkpoint` (no-newline), `dep` (three shape refusals), `gate` (no-gate-on-done).
- **Genuinely load-bearing** (does something a hand-edit can't safely do at all):
  `create`/`add-step`/`name-step`/`template use` — all four mint step/plan ids from the
  one shared counter (`doc["next_plan"]`/`next_step"]`, `202-217` region), and `name-step`/
  `template use` additionally run the composition+obligation expansion. **Andrew's brief
  doesn't ask about these four** — they weren't named as candidates — but they're the ones
  where "just edit the JSON" is actually risky (id collisions silently possible if the
  counter is guessed wrong; see `_check_all`/`_check` at `2161-2187`/`2381-2431`, which
  catches a collision only on the *next* read, not at write time).

**Test coverage / removal cost** (`tests/test_plans_plugin.py`, 92 tests / 10 classes):
- `gate` has its **own dedicated class**, `GateTest` (line `2076`, 8 tests: `2106`-`2270`).
  Highest removal cost of the named candidates — it's testing a real invariant (no-gate-
  on-done, no-verb-clears-a-gate, forgery guards).
- `assign`/`tick`/`skip`/`note`/`checkpoint`/`rework`/`add-step`/`dep` are all covered
  inside one shared class, `StepsTest` (line `762`), one or two tests each (`795`-`1082`).
  Lower removal cost individually — no dedicated class per verb.
- `name-step`/`template` are covered in `CatalogueTest` (line `1083`), which is large
  (~400 lines) because of the composition/obligation expansion logic — this is the
  expensive class to keep passing, and it's testing logic that would still need to exist
  if a "build" hook validated hand-edited composition instead.

## 2. Init/copy → path (does anything print the file the lead should go edit?)

**No.** Checked every mutation verb (`create`, `add_step`, `name_step`, `template`) — none
prints or returns the plan's `p-<n>.json` path. What they return (`_plan_result` /
`_changed`, both wrapping `Result(human=..., data=...)`) is the **rendered plan**, not a
file reference. `migrate` is the only verb that prints paths, and only for the migration
report (`1146-1161`).

The `guide` text (`612-646`) tells an agent **the directory**, not the file:

```
$(git rev-parse --git-common-dir)/agentflow/plugins/plans/
```

...and says "one plan is one `p-<id>.json` in that directory" — the lead has to compute
the filename from the plan id it already knows from the command's own printed output
(`p['id']` is in every `Result.human`/`.data`). That's a small, findable gap, not a large
one.

**State dir resolution:** `ctx.state_dir` is set by `switchboard/plugins.py:state_dir()`
(`613-627`), which resolves to `state_root(scope, worktree) / plugin_name`
(`state_root()`, `~600-610`) — ultimately `<git-common-dir>/agentflow/plugins/plans/` for
`SCOPE = "repo"` (set at `__init__.py:314`). The plugin never computes this path itself;
it's handed `ctx.state_dir` as a `Path` on every call.

**Smallest change to return a path**, if Andrew wants `create`/`template use` to hand the
lead something to go edit directly: add `str(ctx.state_dir / f"p-{plan['id'].split('-')[1]}.json")`
(or reuse the `_fnum`/id-parsing helpers already in the file, `2265-2267`) to the `data`
dict `_plan_result`/`_plan_result`-equivalent returns, and mention it in the `human` line.
This is genuinely small — one field, computed from data the function already has in hand
(`plan['id']`, `ctx.state_dir`) — **but only after `migrate`**: before migration the store
is one shared `plans.json` (format 1), and there is no single "this plan's file" to point
at. A path-returning `create` would need to special-case the legacy single-file shape (say
nothing, or point at the whole `plans.json`) or refuse to run until migrated.

## 3. The sb hook system — is there a seam for "build/validate the plan"?

Two, and only two, hook mechanisms exist in switchboard. **Neither is a generic
plugin-event hook system**, and neither fires on a raw file edit.

**(a) `switchboard/hooks.py`** — Claude Code's own `Stop`/`UserPromptSubmit` hooks,
wired per-spawn via a settings file (`settings_file()`, `91-162`). This is entirely about
one agent's own turn lifecycle (`stop_gate()`, `mark_turn()`) — it fires when *that
agent's* Claude Code session ends a turn or starts one. It has nothing to do with plan
files, commands, or plugins in general; it's a fixed, single-purpose mechanism (the report-
or-block gate + the working/idle signal) that isn't extensible by a plugin author at all.
**Not a candidate seam** — wrong shape entirely, wrong trigger, and not plugin-authorable.

**(b) `switchboard/board.py`'s `board_hooks()`** (`723-737`, discovery at `740-816`) — this
*is* a real, plugin-authorable seam. Any plugin with a `board.py` exposing `board_lines(state_dir, workspace, rows)` gets called **every time the board redraws** (board redraws
"every couple of seconds" per the module comment at `708-712`), once per workspace shown
on screen. It's given the plugin's own state dir, the workspace name, and the row data —
enough to read the plan files and report on them. **The plans plugin already uses this
seam** (`defaults/plugins/plans/board.py`, 608 lines) to draw incomplete plans in red via
`_defective()` (imported at `board.py:63`, used at `board.py:149`).

**This is the honest answer to Andrew's "sb only hook" idea: it already exists and the
plans plugin is already using it for exactly this class of problem** (drawing a defect that
a hand-edit introduced). What it is *not*:

- **Not triggered by a file edit.** There's no file-watch anywhere in switchboard (grepped
  `switchboard/*.py` for hook/watch mechanisms — only the two above exist). A hand-edit to a
  `p-<n>.json` is invisible until *something* reads the store: the next `sb plugin plans`
  command, or the next board redraw. In practice the board redraws every few seconds, so
  the effective latency for "a defect shows up somewhere" is small (seconds) *if a board is
  open* — but if nobody has a board open, a bad hand-edit sits silently until the next
  command touches that plan.
- **Not a "build" step that can refuse or halt anything.** `board_lines()` can only draw
  text; it can't block a command, refuse a write, or fail a CI-style check. It's read-only,
  best-effort, and every failure in it is swallowed (`_hook_lines()` docstring, `960-978`:
  "every failure is nothing at all").
- **Attaches per-workspace, not per-plan-write.** The hook is asked "what do you have to say
  about this workspace's rows," not "validate this specific plan file." Reusing it for a
  "build" report is natural for board display, awkward for anything wanting a synchronous
  pass/fail on a specific edit.

**Cost verdict:** attaching a validate/report line to the *existing* `board_lines()` seam
is cheap — it's already wired, already imported by the plans plugin, already draws
`_defective()` output. Making it *block* or *build* something (Andrew's exact word) — i.e.
something that runs synchronously against a specific edit and can refuse — has **no
existing seam at all**. That would be new machinery: either (a) a new plugin-authorable
verb the lead is expected to run by hand after editing ("`sb plugin plans build`" or
similar — cheap, but relies on the lead remembering to run it, the same trust problem
verbs already have), or (b) genuine file-watch machinery (expensive, unprecedented in this
codebase, and the module docstring for the plans plugin is explicit that "nothing here
watches" is a *design choice*, not an oversight — see `__init__.py:1-13`).

## 4. Where validation lives now, and when a bad edit gets noticed

Three layers, all already in the file, all already designed for "the file is meant to be
hand-edited" (module docstring says this outright, `612-646` guide text, `280-296`
storage section):

1. **`_check`/`_check_all`** (`2381-2431`, `2161-2187`) — **structural refusal**. Runs
   inside `_read()` on *every* command (`_read_one`/`_read_split`, `2112-2247`), before
   anything else happens. Catches: missing/duplicate ids, non-list `deps`/`notes`/
   `checkpoints`/`changelog`, non-string `def`/`obliged_by`. A file failing this **refuses
   the whole command** — "nothing here will overwrite it" (`_refuse`, `2370-2378`) — and,
   critically, costs *only that one plan* in the split-store shape (each plan is its own
   file), but costs **every plan in the repo** in the legacy single-file shape. This is a
   read-time gate, triggered by the next command touching the store — **not** by the edit
   itself.

2. **`_defects`/`_faults`/`_defective`** (`1918-1978`) — **completeness warning, never a
   refusal**. Checked by every mutating verb after its write (`_plan_result`, `1980-1989`)
   and by `show`/`list`/the board (`_defective`, called from `board.py:149`). Catches:
   missing plan/step `display`, steps with no `deps` (rootless past the first). This is
   the "warn and still write" door the module docstring calls the *second* door
   (`1898-1907`) — explicitly designed to survive hand-edits, since refusing here would
   make the file itself brittle to edit.

3. **`_lib`/`_catalogue`/`_flatten`/`_mint`** (`1652-1831`) — catalogue-side checks
   (composition cycles, obligation cycles, "composes and obliges" conflict, missing
   `display` on a definition). These only run when a plan is *rendered* through a link
   (`show`, `list`, `name-step`, `template use`) — a hand-edited plan whose `def` points at
   a broken definition is invisible until something resolves that link.

**What is NOT re-checked anywhere, ever:** `dep` edges to nonexistent steps written by
hand (the `dep` *verb* refuses this, `1067-1121`, but nothing re-validates a `deps` list
that was hand-typed — it just renders whatever's there, including a reference to a step
that doesn't exist, since `_check` only checks `deps` is *a list*, not that its contents
resolve). Same for a `checkpoint` with a newline hand-typed directly into the JSON —
`checkpoint` the verb refuses it, `_check` doesn't. Same for `gate` on an already-`done`
step — the verb's own refusal (`gate()`, `917-923`) is the *only* place that rule is
enforced; a hand-edit sails straight past it.

**So: does the existing read-time machinery suffice, or is a new build/validate step
needed?** Depends what Andrew wants "build" to mean:
- If "build" means "catch structural corruption (bad JSON shape, duplicate ids)" — **already
  done**, by `_check`, on every command, no new work needed.
- If "build" means "catch incompleteness (missing display/dep)" — **already done**, by
  `_defects`/`_defective`, on every command and every board draw, no new work needed.
- If "build" means "catch the specific per-verb guards that today only live inside the verb
  handlers" (gate-on-done, dep-to-nonexistent-step, checkpoint-with-newline, "only tick
  writes done") — **this is the actual gap**. None of these is re-checked at read time
  today; they're enforced only by the verb that currently exists, which is exactly the
  thing the redesign proposes to remove for shape edits. **This is the concrete argument
  for a build/validate step if the "conscious verbs" (`gate`, `dep`, `checkpoint`) are the
  ones removed** — without one, those three specific invariants have literally nothing
  behind them once their verbs are gone.

## 5. Teardown coupling — does removing a verb break anything downstream?

**No code coupling exists.** Grepped the plugin and `design/PLANS-AND-STEPS*.md` for
"teardown" — the only hits are prose:

- `GUIDE` text itself: "TICK A STEP BEFORE ITS TEARDOWN RUNS, never after" (`__init__.py`
  guide string, `643-645`) — an **instruction to the agent**, not a mechanism. Nothing in
  the plugin calls or is called by `sb workspace close` / agent-close / teardown commands.
- `design/PLANS-AND-STEPS.md:225` and `design/PLANS-AND-STEPS-IMPLEMENTATION.md:279-280`
  say the same thing in prose: a step must be ticked before the command that tears down its
  worktree runs, because the plan can't be reached to tick it afterward (the worktree/agent
  is gone).

This means: **removing `tick` as a verb (not on Andrew's candidate list, but worth being
explicit) would break this** — an agent would have nothing to type before teardown except a
hand-edit, and a hand-edit to a plan whose worktree is about to disappear is exactly the
kind of "conscious, deliberate act" the redesign wants anyway, so it's not obviously wrong,
just worth flagging since `tick` wasn't named as a removal candidate.

For the verbs actually named (`gate`/`skip`, plus `assign`/`checkpoint`/`rework`/`dep`/
`note`/`tick`/`add-step`): **none of them run, call, or gate any teardown/close/merge
mechanism in code.** The module docstring is explicit and repeated on this point — "nothing
in this file blocks, merges, tears down or watches" (`1-13`, and again `77-86` for gates
specifically: "a plugin that shelled out to `gh` or `git merge` on a plan's behalf would be
the evaluator this design deliberately does not have"). Removing any of the nine step verbs
costs only: (a) the changelog-append convenience, (b) whichever narrow guard that verb
enforced (see §1/§4), (c) its dedicated tests. No hidden side effect, no downstream verb or
process depends on any of them having run.

## Options (not a recommendation — for the lead to weigh)

**Which verbs to remove**, three shapes:

- **A. Remove `gate`+`skip` only** (Andrew's own framing). Cheapest, matches what was
  named. Cost: `GateTest`'s 8 tests need rewriting against hand-edits (or deletion), and the
  "no gate on a done step" + "skip needs a reason" guards move entirely to convention/GUIDE
  prose unless a validate step picks them up (see §4's gap).
- **B. Remove all the "conscious edit" verbs** — `gate`, `skip`, `assign`, `checkpoint`,
  `rework`, `note`, `dep` — keeping only `tick`/`add-step` (id-minting) and the read/
  catalogue verbs (`create`, `name-step`, `template use`, `library`, `show`, `list`,
  `changelog`, `guide`, `migrate`). Matches Andrew's stated model most literally ("the lead
  edits the plan directly in JSON"). Cost: loses every narrow guard in §1/§4 at once
  (newline-in-checkpoint, dep-shape refusals, gate-on-done) — makes the case for a
  build/validate step strongest, since without one *nothing* catches those anymore, not
  even after the fact.
- **C. Keep all verbs, add a `validate`/`build` command instead** (additive, not
  subtractive). Lowest risk to existing tests and workflows; doesn't address Andrew's
  actual complaint, which is that lots of small verbs is friction he wants gone, not a
  missing check.

**The hook**, two shapes:

- **Attach to the existing `board_lines()` seam** (§3b). Cheap — already wired, already
  imported by this plugin, already draws `_defective()`. Gets: a periodic (every-few-
  seconds), read-only, best-effort report visible *only while a board is open*. Does NOT
  get: a synchronous "build" step the lead can run on demand right after an edit, and can't
  block/refuse anything.
- **New file-watch or a `validate`/`build` verb** (§3, §4c). The verb form is cheap to
  build (it's just `_check` + `_defects` + the catalogue checks, already-written functions,
  called on demand and printed) but relies on the lead remembering to run it — the same
  trust problem the whole redesign is trying to get away from by making editing
  "conscious." True file-watch machinery is unprecedented in this codebase and the module
  docstring treats "nothing watches" as load-bearing design, not a gap — building it would
  be a genuinely new piece of infrastructure, not a small addition.

## Sharpest open question for Andrew

The "sb only hook" idea, taken literally (something that watches an edit and validates it
unprompted), **does not exist and would be new infrastructure** — the only real hook seam
(`board_hooks()`) is draw-time and best-effort, not edit-triggered and not able to refuse
anything. If what he actually wants is "a lead can ask, after editing, whether the file is
still sound" — that's cheap, and is really just exposing `_check`+`_defects` (both already
written, already run on every command) as an explicit `sb plugin plans validate <id>`
verb, no board/hook involvement needed at all. Worth confirming which of those two he
means before scoping the hook work.
