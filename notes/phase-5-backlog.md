# Phase 5 backlog / process findings

Notes carried forward for the Phase 5 (delivered-instruction-system rewrite) work and for
the workflow redesign generally. Not code to write in Phase 3 — pointers and process rules.

## Authority drift: an agent may not unilaterally defer, re-phase, or narrow approved work

Recorded 2026-08-27, from a Phase 3 review finding (relayed via worker-prompt-audits-2).

**The rule.** An agent may *propose* deferring approved work, but may not *unilaterally*
defer, re-phase, or narrow it. Any scope reduction requires **explicit approval recorded in
the change record**. Completion review treats **every unmet contract / exit-condition item as
unresolved** unless that approved change is on record.

**Why it's here.** This is authority drift, and it is **not** a reason to stop leads / main
agents from coding — it is a constraint on *scoping*, not on *doing*.

**Concrete instance (Phase 3).** The Phase 3 brief listed "definitions stop carrying
procedures owned by roles/runtime/protocol" as an in-scope requirement. The first Phase 3
pass *appended* record-semantics prose to the six definitions and *declared the de-dup
requirement deferred to Phase 5* — a unilateral narrowing with no recorded approval. Review
correctly treated it as unresolved. The bounded six-definition de-dup was then performed in
Phase 3 (change-approval, create-pr, merge-human-review, review trimmed of preset/role/runtime
procedure); only the **composition-wide** rewrite across protocol/roles/guide/library remains
for Phase 5. The line between "bounded per-definition cleanup" (Phase 3) and "composition-wide
rewrite" (Phase 5) is itself a scoping call that should be explicit, not assumed.

**Design implication for the workflow (Phase 5 prose).** The change record already carries a
combined-approval identity (`change.approval` = plan revision + contract digest). A scope
*reduction* is the same kind of act as the original approval and should be representable the
same way — an approved change to the contract, recorded — so that a later completion review
can tell "descoped with approval" from "silently dropped". Worth stating in the reviewer /
lead / planner prose: unmet contract items are unresolved unless an approved descope is on
record.
