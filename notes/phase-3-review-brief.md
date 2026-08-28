# Fresh review brief — Phase 3: change record and adaptive plan lifecycle

You are a fresh, independent reviewer. Review the Phase 3 implementation on branch
`worker-prompt-audits-2`. Do NOT reshape it or expand scope — review it.

## What to review

The diff from `436212a` (Phase 2) to `HEAD`. Five commits:
- `3870c23` design note
- `892826a` change-record model (kind discriminator + change object)
- `8a36fca` direct-work `record` verb + rendering
- `6e6c1da` library semantics wired to the change record
- `8c2039a` coherence prose (docstring, guide) + board

Primary files: `defaults/plugins/plans/__init__.py`, `board.py`, `library/*.json`,
`tests/test_plans_plugin.py` (new `RecordTest`, `LibrarySemanticsTest`).

## What Phase 3 was asked to do

`notes/workflow-repair-plan.md` §"Phase 3", the handoff at
`.switchboard/briefs/phase-3-change-record/brief.md`, and the realization decision in
`notes/phase-3-change-record-design.md` (Option B chosen: embedded `change` sub-document +
plan-less record document, `kind` discriminator).

Exit condition: **direct work reaches review and PR without a plan; shaped work carries one
evolving plan whose approval truly precedes implementation.**

## What was built (verify each against the code)

- `change` document-level object (never a step field — the pinned fresh-step schema is
  untouched); `_change()` builder; `KIND_PLAN`/`KIND_RECORD`, `DIRECT`/`SHAPED`, `_PHASES`.
- `create` attaches a sparse shaped record + `kind:plan`; kept out of the auto-walk
  renderers (`_MACHINERY`, `_SHOWN_PLAN`) so a fresh plan renders exactly as before.
- `record` verb: a plan-less `kind:record` document for a direct change; shares the store,
  ids, locking, crash-safety; no step graph.
- `_change_section` renders path/phase/landing-facts in `show`; markdown walk renders a
  record; board says "record".
- Library `about` semantics (additive) connecting the six definitions to the change record.
- Legacy compat: no `kind`/`change` ⇒ read as a plain plan; nothing silently migrates.

## Focus your review on

1. **Correctness of the additive claim.** Does a legacy document (no `kind`/`change`) really
   read/render/validate exactly as before? Any path that assumes `steps` and breaks on a
   record? Any renderer that now leaks `kind`/`change` where it should not?
2. **Storage/crash-safety unchanged.** `_read`/`_write`/`_split`/`_migrate` untouched by the
   record — confirm a record round-trips through both store shapes and migration.
3. **The direct path actually works.** Can a record be created, shown, listed, and posted to
   a PR (`comment`/`show --markdown`) with no plan and no crash?
4. **Validation.** A record produces no false defects; a mangled `change` costs one rendering
   (falls back), not the file.
5. **Test quality.** Are the new tests pinning real behavior, or tautologies?

## Reviewer protocol (from the brief)

- Omit nits. Classify findings **major** / **minor**.
- Apply safe **minor** fixes yourself and list them with the commit.
- Return defensible **majors** — reachable path, likelihood, impact, why a fix is
  proportionate — for the author (worker-prompt-audits-helper) to resolve.
- A rare, non-blocking issue with a large fix is a skip candidate, not a major.

## Explicitly OUT of scope (deferred to later phases — do not flag as missing)

- The human-first PR-comment renderer (**Phase 4**).
- The full composition-aware prose de-dup across protocol/roles/guide/library
  ("definitions stop carrying procedure owned by roles/runtime/protocol") (**Phase 5**).
- Any change to the model/role/waiting work from Phases 1–2.

Report findings to me (`worker-prompt-audits-helper`) with `sb tell`. Do not edit the plan
of record, do not push, do not open a PR.
