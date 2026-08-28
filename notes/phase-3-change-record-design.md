# Phase 3 design — the change record and adaptive plan lifecycle

Author: worker-prompt-audits-helper. Status: IMPLEMENTED on branch `worker-prompt-audits-2`
(Option B). The storage-boundary choice below was DELEGATED to me — the brief said to choose
the schema/API shape after investigating — not chosen by Andrew; I chose Option B and Andrew
confirmed the choice was mine to make. See the "As built" section for what shipped and what
was deferred. (Phase 3 was committed as one squashed commit; the per-slice commit hashes in
the "As built" section are historical and no longer resolve.)

This note is the concrete realization of Phase 3 of `notes/workflow-repair-plan.md`, written
after a full read of `defaults/plugins/plans/__init__.py` (6018 lines), `board.py`, the six
library definitions, the templates, and an inventory of what `tests/test_plans_plugin.py`
(4812 lines), `test_board.py`, `test_plans_evals.py`, and `test_plans_analysis.py` pin.

## 1. What Phase 3 asks for (recap)

A durable **change record** that owns the shared landing lifecycle — work-path identity,
task owner/repo/workspace, human request or approved contract, root cause / selected
solution, verification evidence (+ commit/env), independent review identity (reviewer,
target commit, findings, reviewer-applied fixes), human-only checks or "none remain", PR
identity + head, human landing approval + head, landing/cleanup outcome — **independently of
whether a plan exists**:

- Direct work creates **no plan** and gains a change record **only when landing metadata is
  needed**.
- Shaped work creates **one sparse plan + its change record** at shaping entry; the plan
  grows in place through the lifecycle (shaping → approval → execution → review →
  human-review → landing → finished).
- Library semantics change: `change-approval` = combined solution/plan/contract approval;
  `review` = independent, structured reviewer + target identity, major/minor/nit, reviewer
  may apply+record safe minor fixes; `create-pr` requires current verification + resolved
  review; `merge` consumes identity without routine reruns; `merge-human-review` prepared
  before PR; definitions stop carrying procedure owned by roles/runtime/protocol.
- Backward compat: legacy plans (format 1, and format-2 plans with today's shape) get an
  **explicit interpretation**, no silent migration, existing PR-comment markers intact.

## 2. THE OPEN DECISION — change-record storage boundary

The plugin today is entirely plan-centric: identity is `p-<n>`, storage is `p-<n>.json`
(or legacy `plans.json`), addressing/rendering/migration all assume a plan. A **direct**
change with **no plan** still needs a durable record — so a record must be creatable and
addressable without a plan. Two viable realizations, with real tradeoffs:

### Option A — change record as the outer object (invert plan-centricity)
New `c-<n>` identity + `c-<n>.json` storage (or a `records` list). A shaped plan *attaches*
to its record; a direct change is a record with no plan.
- **For:** truest to the plan's wording ("a shaped change attaches its plan to this record";
  "plans and change records are not synonyms"). Clean conceptual separation.
- **Against:** a second id space + storage shape + addressing + rendering + migration path,
  invented mid-redesign. Largest blast radius; touches the crash-safe store machinery and
  the migration crash-ordering that tests pin exactly. Highest risk.

### Option B — embedded record sub-document + lazy plan-less record (RECOMMENDED)
The record is a self-contained `change` object under a document in the **same** `p-<n>.json`
store, logically separate from `steps` (no step-graph code reads/writes `change`):
- **Shaped** change: its plan document gains a `change` object at shaping entry.
- **Direct** change: when landing metadata is first needed, a **record-only document** is
  written — same `p-<n>` id/file, but `kind: "record"`, no steps. It is *not* a plan (board,
  guide, completeness doors treat `kind:"record"` differently — no "needs steps" warnings,
  rendered as a change record).
- **For:** reuses the existing crash-safe storage, `_minting` lock, renderer fallbacks (they
  already surface unknown fields), and migration untouched — so most of the 8000-line test
  suite stays intact and compat is additive. The plan explicitly says to reuse the plugin's
  "persistence, locking, validation, rendering, and PR-comment identity where that is clean".
- **Against:** a record shares a document shape with a plan; "not synonyms" is enforced by a
  `kind` discriminator rather than by separate storage. Slightly bends the "outer object"
  reading of the design.

**Recommendation: Option B.** It is the conservative, additive, compat-preserving
realization the plan's "reuse the storage utilities" language points at, it minimizes churn
to the exactly-pinned store/migration tests, and a `kind` discriminator satisfies "logically
separate from the step graph". Option A is cleaner on paper but is a high-risk second storage
shape invented mid-redesign, and it is the harder one to walk back.

**Why this is surfaced and not just chosen:** it is the foundation Phases 4 (PR renderer) and
5 (prompt rewrite) build on, it is hard to reverse once written to disk, and the brief's own
Approval boundary lists "change-record architecture" among decisions that "return for human
discussion before implementation continues." Andrew owns this architecture and is away.

## 3. Realization under Option B (the implementation pass)

### 3a. The record schema (a `change` object; never a step field)
The pinned fresh-step dict (test L319-324) must not change, so the record is **document-level**,
not per-step. `change` is a sparse object; every field explicit-null-or-absent per this file's
conventions. Fields (identity-bound where the design says so):
- `path`: `"direct"` | `"shaped"`.
- `owner`, and repo/workspace identity (reuse the plan's existing `workspace`/`checkout`).
- `request` (human ask) / `contract` (approved change contract) — the latter mirrors the
  `change-approval` step `output` for a shaped plan.
- `cause` / `solution` (root cause or feature intent + selected solution).
- `verification`: `{commit, command_or_walkthrough, environment, result, at}`.
- `review`: `{commit, reviewer, findings_state, fixes:[...]}`.
- `human_checks`: list, or explicit "none remain".
- `pr`: `{number, head}`.
- `approval`: `{head, by, at}` (human landing approval, covers the reviewed head).
- `landing`: `{outcome, cleanup}`.

### 3b. Direct vs shaped
- Direct: no plan; no `change-approval` step ever synthesized. A record-only document is
  created lazily (new lightweight verb or `create --record`) when landing metadata is first
  needed. `create-pr`/`merge` on a direct change read the record, not a plan.
- Shaped: `create` (shaping entry) writes a sparse plan + `change` object. The planner
  **expands the existing plan in place** (no replacement plan). Combined `change-approval`
  records plan-revision + contract digest into the record before execution is sanctioned.

### 3c. Lifecycle
The 7 phases are **descriptive/validating states derived** from the record + step progress,
not an executor. Anchoring (`change-approval` early root) and dependency validation preserved.

### 3d. Library-definition rewrite
Rewrite the 6 JSON `about` fields to the new semantics and **strip procedure owned by
roles/runtime/protocol** (this is the bulk of the prose churn, and many tests assert on the
current prose — they move with it). `review` gains structured reviewer/target identity +
major/minor/nit + recordable reviewer fixes. `create-pr` requires current verification +
resolved review. `merge` consumes identity without reruns.

### 3e. Rendering
`change` renders as its own section in `show`/`--markdown`/board via the existing
schema-agnostic fallbacks; the four coupling frozensets (`_SHOWN_PLAN`, `_SHOWN_STEP`,
`_DRAWN`, `_MACHINERY`) get the new keys they should draw by name. PR-comment marker/upsert
unchanged.

### 3f. Compatibility / migration
No silent migration. A legacy plan (no `change`, or `kind` absent) is interpreted as a
pre-record shaped plan and rendered through the existing path — never falsely shown as having
structured approval/evidence. Store format numbers, migration crash-ordering, and the
tombstone are untouched.

## 4. Test impact (rough)
- Safe/additive: storage/migration/locking tests (untouched), renderer fallback tests.
- Rewritten: the 6 library-definition prose tests (§2 of the test inventory), lifecycle/
  anchor tests that reference approval semantics, new focused tests for the record + direct
  path + legacy interpretation.
- At risk if schema drifts: the exact fresh-step dict (L319-324) — kept unchanged by design.

## 5. What is needed before the implementation pass
Confirmation of the change-record storage boundary (Option B recommended). Everything else in
§3 follows from it and is within the brief's stated design constraints.

## As built (Option B)

One squashed commit on `worker-prompt-audits-2` (the per-slice hashes are gone). Full suite
green. A corrective follow-up then addressed a second review's majors: the combined-approval
identity (plan revision + contract digest), a minimal lifecycle-coherence defect, the optional
fresh-main handoff field, and the bounded six-definition prose de-dup.

**Model.** `change` is a document-level object (never a step field, so the pinned fresh-step
schema is untouched). `kind` discriminates `plan` vs `record`; absent means plan (compat).
`DIRECT`/`SHAPED` path, `_PHASES` lifecycle (advisory/open like `progress`, not policed).

**Direct path.** New `sb plugin plans record` verb: a plan-less `kind:record` document, made
only when landing metadata is needed. Shares the store, ids, `_minting` lock, crash-safety,
and migration; has no step graph. `show`/`list`/`--json`/`comment`/`show --markdown` all
render it (the last two are how a direct change reaches a PR with no plan).

**Shaped path.** `create` attaches a sparse shaped record at shaping entry; it stays out of
the auto-walk renderers so a fresh plan reads exactly as before, and draws (`_change_section`)
once a landing fact lands. Existing change-approval anchoring (approval before implementation)
is unchanged and still works.

**Library semantics** (additive to the six definitions' `about`): review = independent fresh
reviewer + named target commit + major/minor/nit + reviewer-applied minor fixes + recorded in
the record; change-approval = combined solution/plan/contract, recorded; create-pr = requires
verification + resolved review, serves the direct path; merge = consumes identity, no reruns;
merge-human-review = the record's human_checks, prepared before the PR.

**Compat.** No `kind`/`change` ⇒ plain plan. Nothing silently migrates. Store format numbers,
crash-ordering, tombstone all untouched.

**Deliberately deferred (not in Phase 3):**
- The human-first PR-comment renderer — **Phase 4**. A record currently renders via the
  generic markdown walk (functional, not yet human-first).
- The full composition-aware prose de-dup across protocol/roles/guide/library ("definitions
  stop carrying procedure owned by roles/runtime/protocol") — **Phase 5**. Phase 3 added the
  new semantics additively; the trimming/de-dup is Phase 5's one-pass job.
- Phase-coherence validation: `phase` is advisory/open like `progress`, not validated. A
  deliberate choice consistent with the file's open-vocabulary + warn-never-refuse philosophy.

**Unproven / worth a human eye at landing:** the change-record storage boundary (Option B) is
the foundation Phases 4–5 build on; if Andrew wants the outer-object shape (Option A) it is
better changed now than after Phase 4/5 depend on it.
