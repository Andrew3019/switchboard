# Final adversarial review — plans board-UI + per-plan storage

Branch `plans-board-ui-implement`, diff vs `origin/main` over `defaults/plugins/plans/`,
`tests/test_plans_plugin.py`, `tests/test_board.py`.

**Verdict: SAFE TO MERGE.** No blocker. The two invariants the brief names both hold, and I
proved each of them by running the code rather than by reading it. Three should-fix defects
and two nits below; none of them can lose a landing write or flip a live store's shape.

---

## What I verified held (with evidence)

Probe scripts (throwaway, in the session scratchpad, driven through `PlansSandbox` so every
case goes through the real CLI + real store):
`.../scratchpad/t_adv.py`, `.../scratchpad/t_adv2.py`.

### 1. No implicit migration; legacy writes stay format 1

* `_read` (`__init__.py:1999`) dispatches on `_split(d)` — `bool(_files(d)) or (d/META).exists()`
  — and neither `_read_one` nor `_read_split` writes anything. Grepped every write site in
  the module (`_atomic`, `_tomb`, `write_text`, `os.replace`): they occur only in `_write_one`,
  `_write_split` and `_migrate`. Nothing on a read path.
* `_write` (`__init__.py:2415`) re-asks `_split(d)` and dispatches to the *same* shape. In
  legacy mode `_write_one` forces `out["format"] = LEGACY_FORMAT` and drops the `broken`
  key, so the on-disk file is byte-shaped exactly as main's plugin writes it.
* **Ran it** (`t_adv.py::test_d`): `create` + `tick` on a legacy store left the state dir as
  `['.lock', 'plans.json']` with `"format": 1`. No `_meta.json`, no `p-*.json`, no tombstone.

### 2. The board read path takes no lock and needs none

`board.py:117` is `_read(Path(state_dir))[0]["plans"]`. `_read` → `_read_split`/`_read_one` →
`_meta`/`_files`/`_load`, all read-only. The report's worry is unfounded: no write, no
subprocess (`_Rows` overrides `_Live.agents()`), no migration. Exceptions out of `board_lines`
are swallowed by the seam (`switchboard/board.py::_hook_lines`), so a refusal there costs the
plan block and never the board.

### 3. `migrate` is idempotent and preserves the changelog byte-for-byte

* **Ran it** (`t_adv.py::test_e`): second `migrate` prints `already one file per plan —
  nothing to move` and writes nothing.
* **Ran it** (`t_adv2.py::test_h`): after `create` + `tick` + `note`, the pre-migration plan
  dict and the post-migration `p-1.json` compare **equal in full**, changelog included.
  `_migrate` re-serialises the plan object it parsed and never touches `changelog`.
* `_migrate` is reached only from the `migrate` verb (grepped: one call site, `__init__.py:1152`),
  under the plugin flock (`LOCK = True`, `switchboard/plugins.py:461,669`).

### 4. Global step-id uniqueness survives the split

`_read_split` (`__init__.py:2110`) carries `steps_seen: dict[int, Path]` across files and
refuses the second file that claims an id another already holds.
**Ran it** (`t_adv2.py::test_i`): forging `s-1` into `p-2.json` made `list` print
`! p-2 did not load … holds an s-1 that p-1.json holds as well`, and p-1 rendered normally.
So `tick s-7` with no plan named stays unambiguous — two files cannot both be live with one id.

### 5. Every non-shape write warns and still lands

* `_on_step` (`__init__.py:1391`) is the single funnel; the only `Result` any `change`
  callback returns is `gate`'s refusal on an already-done step, which is a progress rule and
  not a completeness one. `_defects`/`_faults`/`_defective` return lists and never a `Result`.
* `_changed`/`_added`/`_plan_result` recompute defects **after** `_write` and append them;
  `ok` stays true.
* **Ran it** (`t_adv.py::test_c`): hand-edited a plan to be maximally defective (no plan
  display, no step display, an extra step with no dep), then `tick s-99`. The command
  succeeded, printed all three warning lines, and the file on disk showed
  `progress: done` and `format: 1`, with the dir still `['.lock', 'plans.json']`.

### 6. The shape-verb refusal cannot be bypassed, and its message carries a real example

`create` refuses an empty `--display` and refuses any `--step` that `_authored` splits to
`(None, …)` or to an empty half — `"= x"`, `"x ="`, `"  "` all refuse. `add-step`,
`name-step` (on the *definition's* display) and `template use` each refuse likewise.
The message is `_no_display` + `_SHORTEN`, which spells out
`investigate the failing assertions` → `invstgt`. Confirmed all three library definitions
ship a `display`, so the shipped catalogue never trips its own refusal.

### 7. `_check` is structure-only

`__init__.py:2288` checks id presence/parse, twin step ids inside one plan, list-ness of
`deps`/`notes`/`checkpoints`/`changelog`, and string-ness of `def`/`obliged_by`. Nothing
about `display` or `deps` content. Identical in intent to main's `_check`, so no new
whole-store refusal was introduced.

### 8. The board draws something for every degenerate shape

**Ran it** (`t_adv2.py::test_j`): a plan with a 3-cycle, a dep on a non-existent `s-404`, a
second root, and an unknown `progress` value drew

```
p-1  board: j1  ·  live  ·  4 steps       (header in red)
  orph   b ──→ c ──→ a
```

No exception. `_layers` breaks cycles by contributing 0 for a back edge; `_deps` drops the
dangling `s-404`; the backward edge is dropped in `_gap` because its source is in a later
column. Wrong picture of a wrong plan, in finite time — which is the stated design.

---

## Findings

### F1 — a template's `after` join silently drops all but the first edge (should-fix)

`defaults/plugins/plans/__init__.py:1345-1347` (`_chain`):

```python
for st in landed[n]:
    if not st["deps"]:
        st["deps"] = list(waited)
```

The `if not st["deps"]` guard is what makes the *second* `after` a no-op: the first
iteration fills the roots' `deps`, so every later `after` on the same entry finds them
non-empty and skips.

**Inputs → wrong result.** A template entry `{"name": "c", "display": "c", "after": [1, 2]}`.
**Ran it** (`t_adv.py::test_b`): the copy came out as `s-3 c ['s-1']`. The `s-2` edge is gone,
with no warning and no changelog trace. Fix is `st["deps"] += [w for w in waited if w not in st["deps"]]`
tracked per-entry rather than per-step.

Not urgent: `after` is new on this branch and the only shipped template (`templates/docs.json`)
is a pure chain, so nothing in the repo triggers it today. But it is a silent wrong answer in
the one place the feature exists to be used.

### F2 — `name-step merge` always lands a step the plugin then calls incomplete (should-fix)

`_mint` (`__init__.py:1783-1790`) makes the *obliging* step depend on the *obliged* one:
`merge.deps = [<review id>]`. The review step itself gets no dep, so `_faults` reports it as
rootless and `board.py` paints it red.

**Ran it** (`t_adv.py::test_a`): `create` then `name-step p-1 merge` printed

```
! p-1 is incomplete — the board draws it red until this is fixed, and nothing here refused the write
    no dep: s-3 — every step but the plan's first says what it comes after …
```

So the plugin's flagship library path immediately trips the plugin's own second door, and
`show` repeats the warning on every read until a lead types an extra `dep s-3 --after <step>`
by hand. `_mint`'s own comment claims the edge stops the obliged step "landing as a second
root of the plan" — the edge points the wrong way for that; the obliged step *is* the second
root. Either chain the obliged step onto the plan's current sink, or exempt an `obliged_by`
step from the rootless check.

Severity is UX, not correctness: nothing refuses, and the write lands.

### F3 — a broken plan file forfeits its step-id reservation, and repairing it does not work (should-fix)

`_read_split` (`__init__.py:2153-2163`) derives `next_plan` partly from the filenames
(`max(_fnum(f) …) + 1`), so a plan that failed to load still reserves its plan id. It derives
`next_step` only from `meta` and from the plans that **did** load. A file that did not parse
therefore stops reserving its step ids.

**Inputs → wrong result** (`t_adv2.py::test_g`): split store with p-1 (s-1) and p-2 (s-2);
`p-2.json` is corrupted **and** `_meta.json` is lost (both are hand-edit hazards the file
layout explicitly invites). `add-step p-1 …` then mints **s-2** — an id p-2 already owns.
Repairing `p-2.json` afterwards does not recover it: `list` now prints
`! p-2 did not load … holds an s-2 that p-1.json holds as well`, permanently.

Needs both hazards at once, because `_write_split` keeps `_meta.json` current, so likelihood
is low. But `_read_split`'s docstring ("the counters know its id is taken from the filename
alone") overclaims — that is true of plan ids only, and the doc should say so even if the
code is left as is.

### F4 — a crash inside `_migrate` leaves a silently halved store the verb cannot repair (should-fix)

`_migrate` (`__init__.py:2262-2273`) writes each `p-<n>.json`, then `_meta.json`, then
`os.replace(legacy, MIGRATED)`. The flock serialises writers but does not survive a kill.
After the first `_atomic` lands, `_split(d)` is already true.

**Ran it** (`t_adv.py::test_f`): two plans in a legacy store; simulate a crash by writing
`p-1.json` only. Then

* `list --all` shows **only p-1** — p-2 has vanished from every command with no message,
* `migrate` re-run answers `already one file per plan — nothing to move`, so the verb has no
  repair path,
* `plans.json` is still there, still `format: 1`, still holding **both** plans — i.e. an
  old-plugin worktree reads and writes a different store from a new-plugin one. Split brain,
  and the "put `plans.json.migrated` back" undo instructions in the verb's output do not
  apply, because the rename never happened.

Cheap fix: write the plan files to a staging name (or write `_meta.json` **last**, after the
`os.replace`, and have `_split` require the meta file when a legacy `plans.json` is still
present as format 1) so a half-done migration reads as still-legacy.

### N1 — `p-0.json` is invisible (nit)

`_files` filters on `if _fnum(f)` and `_fnum` returns `0` both for "no number" and for zero,
so a file literally named `p-0.json` is skipped. No verb can mint `p-0` (counters floor at 1),
so this is unreachable except by hand.

### N2 — `template use` does not check displays as strictly as `name-step` (nit)

`name_step` refuses a definition with no `display`; `_from_template` checks the display of
every minted def-step too, but only `_defkey` steps — a *composite* whose parts lack one is
covered, so this is consistent. The asymmetry that remains is that `template use` refuses on
the template's own `display` and on the library's, but a plan copied from a template still
warns about the obliged step from F2. Same root cause as F2.

---

## What I did not check

* I did not re-run the full suite for pass/fail beyond `tests/test_plans_plugin.py` and
  `tests/test_board.py` (189 passed, 82s).
* I did not test two real `sb` processes racing on one store — the lock is asserted in
  `test_plans_plugin.py`, not proven across processes, and provoking it is an endurance run.
* I did not review anything outside the four paths the brief scoped.
* I did not exercise `migrate` against the live fleet store; every probe ran in a throwaway
  `PlansSandbox` temp repo.
