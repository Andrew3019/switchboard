# Plans plugin storage scout — one-JSON-file-per-plan

Investigation only, no code changed. Repo: `plans-board-ui-implement` worktree, plans
plugin at `defaults/plugins/plans/__init__.py` (2474 lines) and `defaults/plugins/plans/board.py`
(569 lines).

## 1. Read path

Single choke point: `_read(d: Path) -> tuple[dict, dict]` at `__init__.py:1649`. Every verb
that reads calls `_read(ctx.state_dir)` — 7 call sites: lines 611, 651, 681, 696, 848, 938,
975, 1073, 1131, 1193. `ctx.state_dir` is resolved by the sb plugin framework (not this
file) to `$(git rev-parse --git-common-dir)/agentflow/plugins/plans/`.

The board does **not** have its own read path — `board.py:59` imports `_read` straight from
`__init__` and calls it at `board.py:117`: `_read(Path(state_dir))[0]["plans"]`. So board and
every verb share the exact same function. This is the best possible starting point for a
storage-format change — there is nowhere else to touch for reads.

`_read` also does double duty as validator-and-counter-deriver: it computes `next_plan` and
`next_step` as `max(stored counter, 1 + highest id seen)` (lines 1690-1694), so the counters
self-heal from a hand-edited file even if the stored counter field is wrong or missing.

## 2. Write path

Single choke point: `_write(d: Path, doc: dict, seal: dict) -> None` at `__init__.py:1789`.
Called at the 7 sites paired with the `_read` calls above (612→632, 848→858, 938→950,
975→1007, 1073→1084, 1131→1152, 1193→1205 roughly — see grep, `_write` appears at lines 632,
858, 950, 1007, 1084, 1152, 1205).

It's a **whole-file rewrite**, unconditionally: `tmp.write_text(json.dumps(doc, indent=2,
...))` then `os.replace(tmp, d / FILE)` (lines 1826-1828). Every verb reads the *entire*
plans.json, mutates the one plan (and its steps) it cares about in memory, and writes the
*entire* file back — even a `tick` on one step of one plan out of ten rewrites all ten
plans' JSON to disk.

`_log`/changelog: appended in-memory to `plan["changelog"]` before `_write` is called (see
`_log` helper at line ~1635, e.g. `plan.setdefault("changelog", []).append(...)`). It is not
a separate write — it's baked into the same whole-document write. `_write` then enforces
append-only-ness as a safety check (see below), not as the mechanism.

Atomicity: yes — temp file + `os.replace` (atomic within a directory), guarding against a
reader (e.g. someone `cat`-ing plans.json, or the board mid-poll) seeing a half-written file.
No `fsync`, so a power-loss between rename and disk flush can still lose the last write —
documented as a deliberate, accepted trade (`_write` docstring, lines 1805-1808).

`_write` also enforces two invariants against the "seal" taken at `_read` time (the
changelog-as-JSON per plan id, from `_seal` at line 1778): (a) no plan present at read time
may be missing at write time (`gone` check, lines 1810-1815) — this is what makes "records
never erased" load-bearing; (b) no plan's changelog may be shortened or have its existing
entries rewritten (lines 1816-1825) — append-only enforcement.

## 3. Locking / concurrency

**Not a single-file-implies-safe assumption — there's an explicit lock**, but it's coarser
than per-file: `switchboard/plugins.py:670`, `locked(d: Path, want: bool = True)`. It takes
an exclusive `flock` on `<state_dir>/.lock` (one file, sibling to `plans.json`) for the
**entire duration of a handler call**, per plugin's `LOCK` flag. `plans/__init__.py:308` sets
`LOCK = True`, so every plans-plugin command (not just writes) is serialized against every
other plans-plugin command in the same worktree, via one lock file.

**Key finding for the storage-model question**: the lock is scoped to the plugin's whole
`state_dir`, not to `plans.json` itself. So splitting `plans.json` into `p-2.json`,
`p-3.json`, etc. does **not** automatically reduce write contention — the existing lock
already serializes *all* plans-plugin commands in a worktree regardless of how many files
back them, because it locks the directory, not a file. To actually get the "per-plan files
reduce contention" benefit Andrew may be hoping for, the lock itself would need to become
per-plan-file (e.g. `<state_dir>/.lock.p-2`) — that's a design decision, not a free side
effect of the storage change. Flagging this because the brief asked to note if per-plan
files reduce contention "if true" — as currently structured, it is **not** true unless the
lock is also re-scoped.

## 4. Structure of the file today

Top-level shape (from `_read`'s default and real file inspected below):
```json
{"format": 1, "next_plan": 12, "next_step": 61, "plans": [ {...}, {...}, ... ]}
```
`plans` is a **list**, not a dict keyed by id (each plan dict carries its own `"id": "p-N"`
string). `format` is a plugin-private version marker (`FORMAT = 1` at line 313) — `_read`
refuses to load a file with a higher format number than the running plugin understands
(lines 1677-1683).

Globals that do **not** belong to any one plan and need a new home if plans split into
files:
- `next_plan` — the plan-id counter.
- `next_step` — the step-id counter. **Important**: step ids are unique *across the whole
  file*, not per-plan (`_check` tracks `steps_seen` as one set spanning all plans, line
  1725, and rejects a duplicate `s-N` in two different plans, line 1747-1749). If plans
  split into separate files, step-id uniqueness becomes a **cross-file** invariant that
  can no longer be checked by looking at one plan file alone — this is the single biggest
  structural wrinkle in this change.
- `format` — could plausibly live per-file (each plan file stamps its own format) or stay
  as one global marker in a small sidecar file; either works, low stakes.

Real store right now (`.git/agentflow/plugins/plans/plans.json`, resolved via
`git rev-parse --git-common-dir`): `next_plan=12`, `next_step=61`, `format=1`, **10 plans**,
ids `p-2` through `p-11` (no `p-1`, and no gaps otherwise — ids are otherwise dense and
already in the canonical `p-N` string form nothing needs renormalizing).

## 5. Board / display seam

No separate enumeration logic today — `board.py:117` calls the same `_read` and gets
`doc["plans"]`, a list, then filters by workspace (`board.py:117-`). If storage moves to
one-file-per-plan, `board_lines` would need to enumerate a directory (e.g. glob
`state_dir/p-*.json`) instead of trusting a single `plans` list — that glob would become the
new choke point for "what plans exist," replacing the in-memory list `_read` currently
builds. Whoever implements this should keep that enumeration inside (or immediately
downstream of) `_read`, not duplicate it separately in `board.py`, to preserve the "board
reads the same way as every verb" property that holds today.

## 6. `_check` and validation / blast radius

`_check(f: Path, plans: list)` at line 1709 runs **once per whole-file read**, against
*all* plans at once, and raises (refusing the entire file) on any structural problem in
*any* plan — bad id, duplicate id, non-list `steps`/`deps`/`notes`/`checkpoints`, a step
with no usable id, a duplicate step id **anywhere in the file**. Right now: one corrupt plan
takes down the **whole board and every plans command** in the worktree (this is exactly
the risk the board-UI brief warned "don't make `_check` a completeness door" about, and per
the module docstring at lines 264-267 the file-wide refusal is very much the current
behavior, not a strawman).

With per-plan files, `_check` naturally becomes per-file: read/validate one `p-N.json` at a
time, and a structurally broken `p-7.json` would refuse only `p-7` (the board could then
draw the other 9 plans and flag `p-7` as broken) instead of refusing everything. This is a
real, positive blast-radius reduction — probably the strongest argument for the migration.

The one thing that does **not** decompose cleanly per-file: cross-file uniqueness of step
ids (see point 4). A per-file `_check` can validate everything *within* one plan, but
catching "two different plan files both claim `s-42`" requires either (a) a global index
that's checked/rebuilt on each read (partially reintroducing the current whole-store-scan
cost, just for ids not full validation), or (b) accepting that this particular invariant is
no longer enforced synchronously and drifts silently until something notices — that's a
design fork, not something to decide unilaterally (see point 9).

## 7. GUIDE's hand-edit instructions

`GUIDE` (module-level string, starts line 503) tells owners to hand-edit the file directly.
The exact text to change is at **line 558**:
```
      $(git rev-parse --git-common-dir)/agentflow/plugins/plans/plans.json
```
This is inside the "EDITING IT" section (lines 553-569), which also states three rules
(append changelog, never drop/rewrite an entry, never hand-add library steps) that stay true
per-file unchanged — only the *path* line needs to become something like
`.../agentflow/plugins/plans/p-<id>.json` (exact naming pending the fork in point 9). Note
there are two other prose references to `plans.json` as a concept (module docstring line
264, line 1320, line 1473, line 1794, line 2160) that describe *behavior* ("a `plans.json`
somebody edited by hand") rather than a literal path — those read fine generically but a
careful pass should reword them to not literally say "plans.json" once it's no longer one
file, per the [[design-truth-consistency-pass]]-style expectation of leaving prose
consistent rather than stale.

## 8. Migration

**10 plans** currently live in the real store (ids `p-2`..`p-11`; verified by loading the
actual `plans.json` at `.git/agentflow/plugins/plans/plans.json` and printing
`next_plan`/`next_step`/plan count/ids). No id collisions, no non-numeric or malformed ids —
the store is clean. A natural id→filename mapping exists for free: plan ids are already the
regex-validated form `p-<digits>` (`_PLAN_ID = re.compile(r"^(?:p-)?(\d+)$")`, line 358), so
`p-2` → `p-2.json` is direct, no renormalizing needed.

Migration shape: because every plan's changelog must be preserved byte-for-byte (repo rule:
records are never erased) and `_write`'s append-only check already guards against a bug
*losing* entries, a **one-time eager script** (read `plans.json` once, write N per-plan
files + one small file for `{next_plan, next_step, format}`, then remove or archive the old
`plans.json`) is materially simpler and safer than lazy-on-first-write: lazy migration means
`_read`/`_write` have to understand *both* formats indefinitely, doubles the validation
surface, and risks a half-migrated state (some plans in the old file, some split out) if a
process dies mid-way. With only 10 plans in the live store today, there's no scale argument
for lazy migration either.

## 9. Design forks only Andrew should decide (not decided here)

1. **Filename/location convention.** e.g. `p-2.json` directly under the existing
   `agentflow/plugins/plans/` state dir, vs. a subdirectory (`plans/p-2.json`) to keep the
   dir listing clean when a global counters file and `.lock` sit alongside plan files.
   *Recommendation*: flat `p-<n>.json` in the existing state dir — one directory, no new
   nesting concept, and `state_dir` already resolves correctly for every verb.

2. **Global next-id counters: own small file vs. derived from max-on-disk.** Today `_read`
   already recomputes both counters as a floor over every id present (self-healing against a
   stale/missing counter). Splitting into per-plan files could either (a) keep a tiny
   `_counters.json` (or similar) as the one remaining shared file, updated under the same
   lock, or (b) drop the stored counter entirely and always derive `next_plan` /
   `next_step` by scanning every `p-*.json` on disk (glob + read each file's max id).
   *Recommendation*: keep a small shared counters file — deriving `next_step` by scanning
   every plan file on every `create`/step-add reintroduces the "read everything" cost this
   migration is meant to reduce, and the self-healing floor logic can still apply as a
   backstop (recompute from a scan whenever the counters file is missing/corrupt) rather
   than as the primary path.

3. **Migration approach: eager one-time script vs. lazy on first write.** Recommendation
   above (point 8) is eager — simpler, safer, small dataset (10 plans) makes lazy's main
   selling point (avoid a big one-shot cost) moot.

4. **Cross-file step-id uniqueness enforcement** (surfaced in point 6, not explicitly asked
   for in the brief but load-bearing for `_check`'s per-file blast-radius win): whether to
   keep a synchronously-checked global step-id index (partial re-centralization) or accept
   it as a soft/eventual invariant. Recommendation: fold this into the counters-file design
   (fork 2) — if `next_step` already requires knowing the high-water mark, that same file
   can double as (or be checked alongside) a step-id-to-plan-id index built incrementally on
   each write, avoiding a full-store rescan for the common case while still catching
   collisions synchronously.

## Notes for the implementing worker

- Everything funnels through `_read`/`_write` at `__init__.py:1649` / `__init__.py:1789` and
  is called from exactly 7 read/write site-pairs in the verbs plus 1 read-only call from
  `board.py:117` — there is no other reader/writer to hunt down.
- `_check` (line 1709) and `_seal`/append-only enforcement in `_write` (lines 1810-1825) are
  the two invariant-checking systems that need to become per-file-aware; both are currently
  written assuming `plans` is the full in-memory list, so they'll need reshaping (likely:
  `_check` runs against one plan instead of a list; the append-only seal becomes per-file
  keyed on nothing since a file *is* one plan).
- Tests: `tests/test_plans_plugin.py` (64 tests), `tests/test_board.py` (98 tests, many
  plans-adjacent), `tests/test_plans_analysis.py` (15 tests) all currently assume the
  single-file shape (e.g. `test_plans_plugin.py:114` hardcodes `self._dir() / "plans.json"`,
  line 1655 references the literal GUIDE path string) — these will need updating alongside
  the implementation, not just the plugin code.
