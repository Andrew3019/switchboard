# BRIEF — plans plugin changelist

Collected from Andrew over one session on 2026-08-20 by `plans-changelist`, then
investigated read-only against the code. **Nothing here has been implemented.** This file is
the whole handoff: a lead should be able to orchestrate from it without re-deriving anything.

Paths are relative to the repo root. `plans/__init__.py` means
`defaults/plugins/plans/__init__.py`. Line numbers are as of commit `434caf1` and will drift
— they are pointers, not addresses.

---

## 0. Status of every decision

Everything below is **decided** unless a line says otherwise. Andrew ruled on each item
during the session; the two defaults in §3 were put to him and he answered "sounds good".

| # | Item | Decided | Depends on |
|---|------|---------|-----------|
| 1 | Per-plan step numbering, real storage change | yes | — |
| 2 | Ready-to-run CLI commands in the step library | yes | — |
| 3 | Human-readable ids (`plan-1`, `Step 1`) — display only | yes | 1 |
| 4 | Consistency audit of `sb plugin plans guide` | yes, runs LAST | 1, 2, 3, 5 |
| 5 | Schema: template exemplifies every field; every field populated by CLI or by guide | yes | — |

---

## 1. Per-plan step numbering (`_locate` stops being global)

### What Andrew asked for

> "for steps, can we numerate frmo 1 for each plan? instead of a running count globally? and
> maybe step-1 etc."

and, when told global ids were deliberate:

> "can we make locate nonglobal. i still want it nonglobal. who uses it? all plan agents run
> in the same worktree right now. also plan id and step id would be unique keys. i feel like
> it makes more sense now that we have split plans into their own files as well. 2 plans
> should be completely independent."

### Why this is safe — the investigation

Step ids come from ONE store-wide counter (`_meta.json: next_step`, at 91 on the live store).
The live store is 15 plans / 90 steps; `p-16`'s steps are `s-84`..`s-90`. The pain is real.

**It is not a migration artifact.** The global counter is from PR1 (`54758e0`, 2026-08-16),
the first skeleton, when the whole store was one `plans.json`. The per-file split
(`117ba58`) came later and never revisited it.

**Its only justification is bare-id addressing**, and the code says so itself.
`_read_split`'s docstring on the cross-store step-uniqueness check:

> "The second is a **UX contract** — `tick s-7` names no plan — so it survives the split by
> being checked over the assembled set."

Not a structural invariant. The module docstring's defence ("two plans on a worktree would
otherwise both have an `s-1`, and a lead handing a worker 'your step is s-1' would be saying
nothing") is an argument about ergonomics, answered by §1.2 below.

**The whole surface that uses a bare step id is three verbs:**

- `tick <step>`
- `note <target>` — tells a step from a plan by the `s-`/`p-` prefix; still works with
  `step-`/`plan-`
- `dep <step> --after <step>`

**Nothing outside the plugin prescribes an id format.** No preset, role, or protocol text
names `s-<n>`; how a lead tells a worker its step is freeform `sb delegate` prose, so "plan
p-16, step 3" costs nothing. Verified by grep across `defaults/` and `switchboard/`.

**Trusted-doc check.** `DESIGN-TRUTH.md` is silent on id format and numbering scope, and so
is `design/PLANS-AND-STEPS.md`. Only `design/PLANS-AND-STEPS-IMPLEMENTATION.md:81` records
`p-<n>`/`s-<n>` monotonic, and that is a derived implementation note, not trusted. **So this
needs no DESIGN-TRUTH edit and no Andrew-only change.** `PLANS-AND-STEPS.md` and
`PLANS-AND-STEPS-IMPLEMENTATION.md` are the lead's to update.

**Live store shape**: 14 of 15 worktrees hold exactly one plan;
`plans-board-ui-implement` holds two. So bare-id ambiguity is rare in practice.

### 1.1 What changes

1. **Mint step ids from a per-plan counter** held in the plan's own file, floored on read by
   that plan's own highest step id. Ids are still never reused *within a plan*.
   - Mint sites: `plans/__init__.py:750` (`create`), `:1029` (`add_step`), `:1392`
     (`_from_template`), `:1790` (`_mint`, library expansion). All four currently read
     `doc['next_step']`.
   - `_meta.json: next_step` becomes **vestigial**. Keep it for un-migrated (format 1)
     stores, which still have one counter for one file. Do not delete the key — an older
     plugin on the same repo reads it.
2. **Delete the cross-file step-twin check** in `_read_split` (`:2352-2356`, the `steps_seen`
   dict) and the equivalent in `_check_all` (`:2303-2311`, single-file store). `_check`'s
   per-file twin check (`:2536-2541`) already gives per-plan uniqueness and stays.
   - `_check_all`'s twin-plan-id check stays. Only the step half goes.
3. **`_locate` (`:3068`) takes a plan.** See §1.2 for the addressing it accepts.
4. **`_no_step` (`:1463`)** message becomes per-plan: "no step X in p-16 — the highest there
   is step-7". Today it says "the highest is s-7" across the whole store.
5. **`_STEP_ID` (`:412`)** accepts `step-<n>` as well as `s-<n>` and a bare number. Same
   leniency `_PLAN_ID` already has. `_PLAN_ID` (`:411`) likewise gains `plan-<n>` — see §3,
   where storage does NOT change but a pasted readable id should still resolve.
6. **`analysis/evidence.py:553` and `:559`** — both regexes are `s-\d+`; widen to
   `(?:s|step)-\d+`. `_named(p, sid)` already resolves within one plan, so analysis is
   otherwise unaffected.
7. **`board.py`** needs nothing beyond the shared regex — it matches ids for deps
   (`board.py:241,246`) and draws none.

### 1.2 Addressing — DECIDED

- `tick p-16/step-3` always works. The plan qualifier is a `/`-separated prefix on the step
  argument; the same for `note` and for `dep`'s positional.
- A **bare** `step-3` resolves when exactly one plan in the store holds it, and otherwise
  refuses, naming the candidate plans. This keeps the ergonomics that justified globality
  (14/15 worktrees hold one plan) without keeping the constraint.
- `dep p-16/step-3 --after step-2` — once the step argument is qualified, `--after` values
  are plan-local. A qualified `--after` naming a different plan stays refused, as today
  (`dep` already refuses an edge into another plan).
- `note` keeps taking either a step or a plan and telling them apart by prefix.

### 1.3 Existing plans — DECIDED

**The 15 existing plans keep their `s-<n>` ids. Nothing is renumbered.**

Rationale, and it is the load-bearing one: changelog `detail` strings quote ids as free text
(`"s-47 open → done"`, `"3 steps (s-1, s-2, s-3)"`) and `evidence.py` parses ids back out of
them. Renumbering either rewrites changelog entries — which the guide explicitly forbids
("NEVER drop or rewrite an entry that is already there") — or leaves history quoting ids
that no longer exist.

Because `_STEP_ID` accepts both forms, old plans stay addressable. New plans get `step-1`
from 1. The store reads mixed for a while; that is accepted.

### 1.4 Two bonuses, worth taking while in here

- **The mint lock shrinks.** `_minting` (`:2096`) is held today by `create`, `add-step`,
  `name-step` and `template use` because the step counter is store-wide. With a per-plan
  counter in a per-plan file, step minting is a same-plan race only — which the design
  already declares unguarded ("one writer per plan — the worktree's owner"). So
  `add-step` and `name-step` no longer need the lock; `create` and `template use` keep it,
  for the PLAN id. Update `_minting`'s docstring, which names all four.
- **It closes a gap the code admits to.** `_read_split`'s docstring: a broken `p-<n>.json`
  stops reserving its step ids, and only `_meta.json`'s `next_step` keeps them from being
  re-minted — "a real gap ... at which point a step id may be reused". With per-plan
  counters no other plan could mint them at all. Delete that paragraph when it stops being
  true.

---

## 2. Ready-to-run CLI commands in the step library

### What Andrew asked for

> "for steps library, can we add ready to run cli commands? e.g. for create pr, we can add a
> cli command to post the pr comment right? this would save some tokens, agent only needs to
> input the pr and plan path or something"
> "for 2, same with merge pr and other steps that have standard cli comamnds that need to be ran"
> "can we just add in the commands for the steps needing it with placeholder inputs, and
> agents can just run that command directly without finding it each time. **no need to have
> an actual runner for it**"

### It is already sanctioned by the design

`design/PLANS-AND-STEPS.md:224`:

> "**A step may carry a command**, which may live in a script shipped alongside it. How it
> gets called is settled when it comes up. **The agent owning the step is what runs it** —
> nothing watches a plan and fires commands, because that would be the evaluator this design
> does not have."

So a `command` field on a definition is in-design. **The plugin running it is not, and must
not be built.** No runner, no shelling out to `gh`, no new verb that executes anything.

### 2.1 The gap that has to be closed first

`_resolve` (`plans/__init__.py:1823`) pulls only `name` and `display` out of a definition.
**`about` never reaches a plan's steps** — it appears only under
`sb plugin plans library <name>` (`_def_lines:3479` → `_about:3507`, and only with
`full=True`, i.e. when a name was given).

So a `command` field added to a definition would be **invisible where the work happens**
unless `_resolve` carries it and `_step_lines` (`:3179`) renders it. Andrew's phrase was
"without finding it each time" — that is precisely this. Both changes are required.

Recommended shape, matching how `about` is treated: carry `command` through `_resolve` onto
the rendered copy only (never into the stored step, exactly as `name`/`display` are not
copied), and give it its own indented line under the step in `_step_lines`, beside
`ref` and `note`.

### 2.2 What to write

Definitions live in `defaults/plugins/plans/library/*.json`. Today's keys, and the only ones
read: `name`, `display`, `about`, `obliges`, `steps` (compose). Add `command`.

- **`create-pr.json`** — push, open the PR, then post the plan as a comment. The plan-comment
  half is roughly
  `gh pr comment <PR> --body "$(sb plugin plans show <PLAN> --markdown)"`.
- **`merge.json`** — merge, then **edit that same comment in place** (its `about` is explicit
  that a second comment is wrong), roughly
  `gh pr comment <PR> --edit-last --body "$(sb plugin plans show <PLAN> --markdown)"`.
- **`merge-human-review.json`** — no command; it is a human's checklist.

Placeholders should be obviously placeholders (`<PR>`, `<PLAN>`), and the exact argv is the
implementing lead's to verify against the installed `gh`. **Verify each command actually
runs before shipping it** — a ready-to-run command that does not run is worse than none.

Note the interaction with `about`: several definitions currently spell the command out in
prose inside `about`. Once `command` exists, that prose should point at the field rather
than repeat it, or the two go stale against each other.

---

## 3. Human-readable ids — display only

### What Andrew asked for

> "for planid as well and any other ids. can we put this into a more human readable way. like
> plan-1 instead of p-1"

then, after being shown the migration cost:

> "how about just UI changes for these ids then. when dumping the markdown."

### DECIDED: rendering changes only. Storage keeps `p-<n>` and the `p-<n>.json` filenames.

- **Markdown** (`_markdown:3267`) renders a plan as `plan-1` and its steps as `Step 1`,
  `Step 2` … per plan.
- Step numbering in markdown follows §1 — with per-plan storage ids the rendered number and
  the stored number agree, which is the point of doing §1 first.
- **`_PLAN_ID`/`_STEP_ID` must accept the readable forms as input** even though nothing mints
  them, or a reader copies `plan-1` out of a PR comment and it does not resolve.

### 3.1 The constraint on `_markdown` — read this before touching it

`_markdown` is **deliberately schema-blind**. Its own comment block (`:3243-3264`) explains
why: it goes into a PR comment, so a rendering with the schema written into it "stops being
true the week a field is added and raises the week one is dropped — in front of somebody's
merge". It knows exactly two things about the schema: `_HEADS` (`:3264`) and that `at`/`*_at`
integers are timestamps.

`tests/test_plans_plugin.py` pins this with
`test_a_field_nobody_wrote_this_renderer_for_still_renders`.

So: **prefer making the id string itself read `plan-1` / `step-1`** over special-casing steps
into `### Step 1` headings. If Andrew's "do Step 1" genuinely requires headings, that is a
third schema fact added in the same falls-back-rather-than-fails style as `_HEADS` — see §6,
where an in-flight spec adds a fourth one the same way.

---

## 4. Consistency audit — runs LAST

> "also after all this, audit the plan guide for agents and make sure everythign is consitent"

The subject is `GUIDE` in `plans/__init__.py:548` (`sb plugin plans guide`) and the spawn
fragment `defaults/plugins/plans/agent.md`. It has to run **after** items 1, 2, 3 and 5 land,
because each of them changes what the guide must say.

At minimum the audit must reconcile:

- every command example in `GUIDE` that names a step id (addressing changed — §1.2)
- the `p-<id>.json` sentence and the store path (unchanged, but re-verify)
- the "ADD A LIBRARY STEP with `name-step`" paragraph (now also: a definition may carry a
  `command` — §2)
- whatever §5 adds about who populates which field
- `design/PLANS-AND-STEPS.md` and `design/PLANS-AND-STEPS-IMPLEMENTATION.md:81`, both of
  which describe the id scheme
- the module docstring in `plans/__init__.py`, which states the one-counter rule at ~line 210
  and the step record sketch at ~line 30

**`DESIGN-TRUTH.md` is Andrew's alone — do not edit it.** Nothing in this changelist requires
a change to it; if the lead concludes otherwise, that is a `sb block`, not an edit.

---

## 5. Schema — make the shape real

### What Andrew asked

> "is there a set plan schema? or are there certain fields that are 'used', and others that
> can be added but not used anywhere except for manual reading / agent information / context
> / markdown dump? basically comapring code reading plan jsons, the template json, and the
> agent guide"

then:

> "make sure the template has all these baked in as example. make sure these are all
> populated, either by creation/cli or by agent via documentation in plan guide."

### 5.1 The answer, as investigated — three tiers

**Tier 1 — STRUCTURE, refused at read** (`_check:2505`, per file). This is the entire set of
things that are ever refused:

- plan `id` present and numeric-parseable
- `steps` a list of dicts
- every step `id` numeric-parseable, and unique — today across the whole store, after §1
  within the plan
- step `deps` / `notes` / `checkpoints` are lists
- step `def` / `obliged_by` are strings or null
- plan `changelog` / `notes` are lists

**Tier 2 — USED BY CODE** (a wrong value changes behaviour):

| Record | Field | What reads it |
|---|---|---|
| plan | `id` | lookup, filename, `_write`'s seal |
| plan | `checkout` | `list` matching, worktree-gone reading |
| plan | `workspace` | board grouping (`board.py:134`) |
| plan | `workspace_from` | only to word "(unresolved)" vs "(no workspace)" (`:3116`) |
| plan | `display` | board header, red-defect rule |
| plan | `title` | fallback when no display |
| plan | `steps`, `changelog`, `notes` | everywhere |
| step | `id` | lookup, board graph nodes |
| step | `def` | library lookup |
| step | `name` | rendering; resolved from library when `def` is set |
| step | `display` | board cell, red-defect rule |
| step | `deps` | board arrows, red-defect rule |
| step | `progress` | `tick`, board colour, analysis |
| step | `why` | warned if `skipped` without it (`_wrong:1919`) |
| step | `gate` | warned if set on a `done` step |
| step | `owner` | owner-status lookup |
| step | `obliged_by` | dep wiring at mint, rendering |
| step | `tries` | rendered; analysis flags >1 with no note |
| step | `checkpoints` | ref warned if multi-line or containing `|` |

**Tier 3 — STORED, NEVER ACTED ON**: plan `created_by`, `created_at`. Plus any field a human
or agent invents.

**Derived at render time, never stored, never in the file**: `condition`, `worktree`, step
`owner_status` (`_viewed:3044`).

### 5.2 The asymmetry that needs deciding

Where an invented field actually shows up:

| Surface | Renders an unknown field? |
|---|---|
| `show --json` | yes — the whole record |
| `show --markdown` | yes — the walker renders any scalar/list/dict |
| `show` (terminal) | **no** |
| board | no |

`_full` (`:3141`) and `_step_lines` (`:3179`) are hand-written templates that know every
field by name, so an invented field is silently invisible in the terminal view — while the
module docstring claims "a step carrying a field this file has never heard of is a feature
and not corruption".

**Recommendation, put to Andrew and not objected to: fix it** — have the terminal renderer
print unknown scalar fields under the step it belongs to, in the same falls-back-rather-than-
fails spirit as `_markdown`. If the lead disagrees on cost, say so rather than leaving the
docstring claiming something untrue.

### 5.3 The work

1. **The template exemplifies every field.** `defaults/plugins/plans/templates/docs.json`
   today uses only `title`, `display`, `about`, `notes`, and `steps` (each entry being
   `name`+`display`, or `def`, plus `after` as 1-based ENTRY numbers). It should demonstrate
   the rest as a worked example.
   - Sanity: **not every step carries a `gate`, an `owner` or a `checkpoint`.** "All
     populated" means the template shows one worked example of each field and the guide says
     who fills it — not that every step gets a gate. This reading was put to Andrew and not
     objected to.
2. **Every field is populated by something.** For each field in tier 2, it must be either
   minted by `create`/`template use`/`add-step`/`name-step`, or documented in `GUIDE` as
   something the agent writes by hand into the file. Any field that is neither is the gap
   this item exists to close — list them and fix each.
3. **The guide documents who populates what.** The plan record and the step record sketches
   in the module docstring (lines ~25-32) are the reference shape; `GUIDE` is where an agent
   is told to fill one in.

---

## 6. Coordination — an in-flight spec touches the same code

`.switchboard/notes/plans-change-approval-spec.md`, written by a sibling agent
(`plan-discussion`'s tree) on the same day, adds two library definitions (Change Approval,
Review) and — §5 of that spec — **adds a new step field `output` plus a `_BLOCK` schema fact
to `_markdown`**, so that multi-line prose survives the markdown dump.

That file also carries a **decision Andrew locked** (its §0): Change Approval replaces the
design gate everywhere, in six named places.

Overlaps with this changelist:

- **`_markdown`** — that spec adds `_BLOCK`; item 3 here changes how ids render. Same
  function, same session. Sequence them, do not run them in parallel on one file.
- **`library/*.json`** — that spec adds two definitions; item 2 here adds a `command` field
  to the existing ones. A new definition should get a `command` too, or the two land
  inconsistent.
- **The step record and the template** — that spec adds `output`; item 5 here bakes every
  field into the template and documents who populates it. `output` must be in that list.
- **`GUIDE`** — item 4's audit must cover whatever that spec lands.

**The lead must read that spec before starting and decide the order.** Suggested: let the
Change Approval spec land first, then run this changelist on top, so item 4's audit and item
5's template pass see the final field set. If they run concurrently, item 4 must be the last
thing either of them does.

---

## 7. Verification

Per this repo's standing rules:

- **Live proof in an isolated instance is what this is judged on.** `git clone` the repo into
  a scratch directory, check out the branch there, drive that clone's own `./bin/sb`. Never
  run a clone's `sb` from outside the clone. Tear down everything created, with `sb`
  (`sb cleanup`, `sb workspace close`) — never raw `herdr workspace close`, never an
  unscoped `pkill`.
- **Tests pin decisions, they do not buy confidence.** Two or three per fix. Run with
  `python -m pytest tests`; on Andrew's machine use `/Users/andrew/anaconda3/bin/python`.
- **Test surface to expect**: `tests/test_plans_plugin.py` (2638 lines) and
  `tests/test_plans_analysis.py` (304 lines) hold roughly 400 id literals. Most are `p-1`
  and `s-1`. Because old ids stay valid (§1.3), tests that merely *use* an id keep passing;
  tests that assert a *minted* id (`s-1` after a create) all need re-pinning to `step-1`.
  That re-pinning is the bulk of item 1's work and should be scoped as such.
- Specific tests known to constrain this work:
  - `test_a_field_nobody_wrote_this_renderer_for_still_renders` — pins `_markdown`'s
    schema-blindness (§3.1)
  - `test_a_forged_row_cannot_forge_one_here_either`, `test_a_gate_cannot_forge_a_row` — pin
    that every rendered value is flattened through `_flat`
- **Anything left unproven goes in the report.** Unproven and stated is fine; unproven and
  silent is not.

---

## 8. Verbatim record of what Andrew asked

Kept so nothing above is the only account of his words.

1. > "for steps, can we numerate frmo 1 for each plan? instead of a running count globally?
   > and maybe step-1 etc. for the markdown version, do Step 1, etc. for board, it shouldnt
   > show step id so on chnage needed."
2. > "for steps library, can we add ready to run cli commands? e.g. for create pr, we can add
   > a cli command to post the pr comment right? this would save some tokens, agent only
   > needs to input the pr and plan path or something right (or something even simplier)"
3. > "for 2, same with merge pr and other steps that have standard cli comamnds that need to
   > be ran"
4. > "for planid as well and any other ids. can we put this into a more human readable way.
   > like plan-1 instead of p-1"
5. > "also after all this , audit the plan guide for agents and make sure everythign is
   > consitent"
6. > "also, is there a set plan schema? or are there certain fields that are 'used', and
   > others that can be added but not used anywhere except for manual reading / agent
   > information / context / markdown dump? basically comapring code reading plan jsons, the
   > template json, and the agent guide"
7. > "schema: make sure the template has all these baked in as example. make sure these are
   > all populated, either by creation/cli or by agent via documentation in plan guide."
8. > "item2: can we just add in the commands for the steps needing it with placeholder
   > inputs, and agents can just run that command directly without finding it each time. no
   > need to have an actual runner for it"
9. > "item 1: why does locate need to be global. is this a migration artifact. look into this"
10. > "item 3. how about just UI changes for these ids then. when dumping the markdown."
11. > "can we make locate noonglobal. i still want it nonglobal. who uses it? all plan agents
    > run in the same worktree right now. also plan id and step id would be unique keys. i
    > feel like it makes more sense now that we have split plans into their own files as
    > well. 2 plans should be completely independent."
12. > "sounds good" — confirming the two §1.2 / §1.3 defaults.

The working notes behind this brief, including the raw investigation, are at
`.switchboard/notes/plans-changelist.md` (gitignored, so it does not travel to a forked
worktree — this file is the one that does).
