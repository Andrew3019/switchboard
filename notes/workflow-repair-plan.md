# Switchboard Workflow Repair Plan

## Goal

Implement the approved workflow redesign and coordinated repair contract as one cohesive
system change.

The result must support lightweight direct work, investigation-first shaped work, and
planless research or discussion without contradictory prompts. It must also make ownership,
verification, review, PR guidance, and landing reinforce the selected path.

## Execution shape

- One main agent owns the implementation from approved plan through PR.
- The current task owner continues by default; no fresh main is required merely because
  planning finished.
- Delegation is reserved for bounded specialist work or fresh review.
- Related runtime and prompt changes stay on one branch and land in one PR so no intermediate
  version advertises a workflow its runtime cannot support.
- Implementation phases complete before automated tests and builds begin.
- Early commands during implementation are limited to inspection, syntax checks, or a
  diagnostic needed to choose the implementation—not routine verification.
- Fresh review begins only after implementation and verification are complete.

## Architecture

### Change record, with an optional plan

Introduce a small durable change record for work that is heading toward a PR. It is not an
execution plan and does not turn the direct path into a planned path.

The change record owns landing facts shared by both paths:

- Work-path identity: direct or shaped.
- Task owner and repository/workspace identity.
- Human request or approved change contract.
- Root cause or feature intent and selected solution when applicable.
- Verification evidence and the commit/environment it covers.
- Independent review identity, target commit, findings state, and reviewer-applied fixes.
- Human-only checks or the explicit statement that none remain.
- PR identity and current head.
- Human landing approval and the head it covers.
- Landing and cleanup outcome.

A shaped change attaches its evolving plan to this record. A direct change has no plan.
Research or discussion creates neither until it actually heads toward a change.

This separation prevents two bad outcomes:

- Calling a delivery record a plan and recreating mandatory planning for trivial work.
- Making review, evidence, PR rendering, and landing safety available only to shaped work.

Use the plans plugin's existing repository-scoped persistence, locking, validation,
rendering, and PR-comment identity where that is clean. Keep the change record logically
separate from the step graph even if it shares the plugin package and storage utilities.

### Evolving shaped plan

The shaped plan begins sparse and becomes execution-ready in place.

Its lifecycle is:

1. `shaping`: objective, constraints, open questions, and only the investigation/design
   steps currently justified.
2. `approval`: root cause or feature specification, selected solution, tradeoffs, formal
   execution steps, and change contract are complete.
3. `execution`: combined approval is recorded and implementation may begin.
4. `review`: implementation and verification are complete; fresh review owns the next move.
5. `human-review`: PR is open and only human-required actions remain.
6. `landing`: human approval applies to the current reviewed head.
7. `finished`: merge and required cleanup outcomes are recorded.

These phases describe and validate the record. They do not execute engineering steps or ban
legitimate diagnostic commands.

Completed shaping steps remain in the plan history. Human-facing rendering summarizes them
rather than deleting, replacing, or displaying every field prominently.

### Identity instead of repeated work

Bind decisions and evidence to identifiable artifacts:

- Combined change approval covers the plan revision and change-contract digest.
- Verification evidence covers a commit, command or walkthrough, environment, result, and
  timestamp.
- Implementation review covers a commit and names the independent reviewer.
- Reviewer fixes create a new commit identity and list the resulting evidence state.
- Human landing approval covers the current reviewed PR head.

Landing compares these identities once. It does not recreate confidence by rerunning every
earlier activity.

### Compatibility

- Existing plan stores remain readable throughout rollout.
- New change-record and identity fields are additive or use an explicit migration command.
- No ordinary read or write silently migrates shared storage.
- Legacy plans render through a compatibility path and are not falsely presented as having
  structured approvals or evidence.
- Existing PR comment markers continue identifying the authoritative comment.
- Existing message delivery, blocking, reply, interrupt, restore, cleanup, and ring-holdback
  semantics remain intact unless this plan explicitly changes them.

## Implementation phases

The authority baseline is `DESIGN-TRUTH.md` and `design/PLANS-AND-STEPS.md`. Both carry the
adaptive workflow model this plan implements.

### Phase 1: make vocabulary and effective instructions inspectable

Primary surfaces:

- `switchboard/models.py`
- `switchboard/roles.py`
- `switchboard/config.py`
- `switchboard/presets.py`
- `switchboard/broker.py`
- provider adapters
- CLI/help surfaces

Implement:

- Exact configured model and role names remain valid.
- A normalized key handles case and safe punctuation/spacing variants.
- Normalized input resolves only when it has one exact live target.
- Ambiguous or unknown input returns nearby valid names and the command that lists them.
- Raw provider model escape remains available only through explicit syntax; it is no longer
  indistinguishable from a misspelled configured tier.
- Custom prompt behavior remains available without silently treating an unknown role as a
  configured worker role.
- A development-only effective-instruction renderer follows the real assembly path.
- Renderer output preserves delivery order, source boundary, activation condition, resolved
  binding, flattening, size, provider, and whether the source is Switchboard-owned or
  external.
- Representative role/path scenarios can be rendered without spawning an agent.

Exit condition: `gpt5.6sol` resolves safely to the configured `gpt-5.6-sol`, bad names fail
actionably, and the exact Switchboard-owned instruction composition can be inspected.

### Phase 2: add coordination affordances

Primary surfaces:

- `switchboard/cli.py`
- `switchboard/broker.py`
- `switchboard/store.py`
- `switchboard/status.py`
- `switchboard/hooks.py`
- `defaults/prompts.toml`

Implement:

- `sb waiting` marks an agent as intentionally waiting for generic background work.
- `sb waiting --any` wakes when any member of the declared/default live-child cohort reaches
  a terminal result.
- `sb waiting --all` wakes when the whole declared/default cohort reaches terminal results.
- Wait state records its cause and cohort so stale or unrelated events cannot wake it.
- Stop hook and stalled detection recognize valid waiting state.
- A new instruction or interrupt clears incompatible waiting state.
- Ordinary mail wakes include the tagged payload when transport and size allow.
- Durable inbox rows remain the source of record and still support reply tracking.
- Oversized, blocked, held, or provider-constrained delivery falls back to the existing
  doorbell/inbox path without losing content.
- Completion bursts for a declared cohort produce one useful wake rather than one turn per
  child.
- Existing holdback, cancellation, and blocked-human behavior remain authoritative.

Exit condition: agents can wait without polling or tripping the stop hook, and common mail
and cohort completion no longer require avoidable inbox/notification turns.

### Phase 3: implement the change record and adaptive plan lifecycle

Primary surfaces:

- `defaults/plugins/plans/__init__.py`
- plans storage and validation helpers
- plan guide/catalog generation
- plan library definitions and templates
- plan board and terminal rendering

Implement the change record described above, then adapt the plan layer:

- Direct change creates a change record only when landing metadata becomes necessary.
- Shaped change creates the change record and sparse plan at shaping entry.
- Planner expands the existing plan rather than creating a replacement.
- Plan revision and change-contract digest are recorded at combined approval.
- Implementation steps cannot be presented as sanctioned execution before shaped approval.
- Direct work never receives a synthetic change-approval step.
- Plan author can add, collapse, skip, or revisit shaping steps as evidence changes.
- Planner ownership is bounded and can return cleanly to the task owner.
- Fresh-main handoff is optional and recorded only when used.
- Existing early approval anchoring and dependency validation are preserved.
- Review, evidence, PR, human-action, and landing state are shared change-record concerns,
  not features available only because a plan exists.

Update library behavior:

- `change-approval` becomes the shaped-path combined approval and covers solution, plan, and
  contract.
- `plan-review` remains optional and fresh.
- `review` requires independent implementation review and structured target identity.
- `merge-human-review` is prepared before PR creation and contains only uncovered human work.
- `create-pr` requires current verification and resolved implementation review.
- `merge` consumes current approval/evidence identity without requesting routine reruns.
- Definitions stop carrying procedures owned by role prompts, runtime commands, or the
  universal protocol.

Exit condition: direct work can reach review and PR without a plan; shaped work carries one
evolving plan whose approval truly precedes implementation.

### Phase 4: replace the PR renderer with a human-first view

Primary surfaces:

- plans/change-record markdown renderer
- PR comment upsert path
- create-PR and merge definitions

Render one authoritative comment in this order:

1. `What you need to do`
   - Human-only checks or decisions.
   - Exact routes, controls, and expected results where manual testing is required.
   - Explicit `Nothing—agent verification covers this change` when none remain.
2. `What changed and why`
   - Root cause or feature intent.
   - Selected solution and important scope boundaries.
3. `Agent evidence`
   - Reviewed commit.
   - Verification results and environments.
   - Independent review result and reviewer-applied minor fixes.
   - Known relevant limitations or evidenced baseline failures.
4. `Detailed record`
   - Collapsed shaped plan when present.
   - Execution history, ownership, timing, and other observability detail.

Preserve the existing hidden marker, duplicate detection, and idempotent update. Update the
comment when review fixes, human feedback, head identity, or landing state materially changes
what the human should see—not only after merge.

Exit condition: the first screenful tells Andrew exactly what remains for him, and a direct
change renders correctly without an empty or invented plan.

### Phase 5: rewrite the delivered instruction system

Primary surfaces:

- `defaults/protocol.md`
- `defaults/roles/*.md`
- `defaults/plugins/plans/agent.md`
- `defaults/plugins/plans/planner.md`
- plans guide and library prose
- `defaults/guidance.toml`
- `defaults/presets/*.md`
- `.switchboard-shared/presets/house-rules.md`
- `defaults/prompts.toml`

Rewrite all affected surfaces as one composition-aware pass:

- Protocol keeps universal communication, scope, lifecycle, and safety rules.
- Dispatcher routes direct, shaped, and research/discussion work to a suitable initial owner
  and uses generated vocabulary.
- Lead owns and performs the task; delegation is optional and justified.
- Worker owns a bounded outcome and may receive explicitly scoped temporary help authority.
- Planner challenges and expands the evolving plan, then returns ownership.
- Researcher stays read-only unless a later change path is explicitly entered.
- Reviewer is fresh, classifies major/minor/nit, applies safe minor fixes, and reports those
  fixes against the reviewed result.
- QA is invoked only for specialized additional coverage and consumes existing evidence.
- Brief guidance specifies outcome boundaries without prescribing internal steps.
- Implementation guidance puts routine verification after the coherent change.
- Plan instructions describe only shaped work and link to runtime-generated syntax.
- JIT guidance replaces spawn-time text whose relevance depends on later state.
- Notifications describe only the remaining fallback or lifecycle action after inline
  delivery and waiting support exist.
- House rules retain repository-specific commands and trust boundaries without imposing a
  universal full-suite or repeated-test workflow.

After rewriting, render every representative path from the audit and remove remaining
contradictions, irrelevant fragments, and duplicate canonical rules.

Exit condition: a reasonable agent following the full composed prompt reaches the approved
workflow without needing exceptions that say other injected rules do not apply.

### Phase 6: complete implementation consistency pass

Before running automated verification:

- Review every changed runtime path against the prompt claims it supports.
- Confirm direct and shaped paths share change-record review/landing behavior without sharing
  plan ceremony.
- Confirm legacy plan and message state still has an explicit interpretation.
- Confirm role capabilities match their new authority.
- Confirm generated catalogs and help are the only source of exact operational vocabulary.
- Confirm no old delegate-everything, universal-plan, QA-runs-tests, read-only-reviewer, or
  observability-first-human wording remains in any delivered source.
- Render representative effective prompts and inspect source order and relevance.
- Finish all code, prompt, schema, help, fixture, and migration edits before continuing.

Exit condition: implementation is coherent and no known code or prompt edit remains.

### Phase 7: verification

Only after implementation Phases 1–6 are complete:

1. Add or update focused tests for concrete changed mechanisms.
2. Run the smallest relevant test files together once.
3. Fix failures in the owning implementation.
4. Rerun only failed or affected tests until they pass.
5. Run the full suite once after focused verification is green.
6. Run applicable lint/build checks once.
7. Exercise focused live scenarios in an isolated clone for mechanisms that mocks cannot
   establish.
8. Record commit, command, environment, result, and limitations in the change record.

Focused coverage must include:

- Model/role normalization, ambiguity, suggestions, and explicit raw/custom escape paths.
- Effective-instruction provenance and provider-specific delivery rendering.
- Generic, any, and all waiting; causal wakes; stop-hook and stalled-state behavior.
- Inline mail, fallback inbox delivery, reply tracking, interrupts, and completion coalescing.
- Direct change record without a plan.
- Sparse shaped plan expanded in place and approved before execution.
- Legacy plan compatibility and explicit migration behavior.
- Independent reviewer identity, target head, scoped fixes, and unresolved-major state.
- Human-first comment ordering, no-human-action case, optional plan detail, and stable upsert.
- Approval/review/evidence/head comparison without automatic verification reruns.

Do not expand fake infrastructure merely to simulate behavior it cannot reproduce. State any
unproven boundary and verify it through the smallest isolated live run available.

### Phase 8: fresh review and repair

Run fresh review after all implementation and verification are complete.

Minimum facets:

- Workflow and prompt-composition review across every representative path.
- Runtime/state and backward-compatibility review.

Add a security/concurrency or provider-specific facet only if the completed diff warrants it.

Reviewer behavior:

- Omit nits.
- Apply safe local minor fixes and list them.
- Return defensible major issues with reachable path, likelihood, impact, evidence, and why
  remediation is proportionate.
- Do not demand a large repair for a rare low-impact condition unless its destructive
  potential justifies it.

The main agent resolves major findings. Reviewer-applied fixes receive targeted verification;
material author fixes receive a fresh review of the affected result. The full suite is not
rerun automatically unless the fix invalidates broad evidence.

Exit condition: no defensible unresolved major finding remains, reviewer fixes are recorded,
and evidence identifies the final reviewed commit.

### Phase 9: PR, human review, and landing

- Push the final reviewed branch and open one PR.
- PR description explains the system problem, architectural repair, compatibility, and
  verification summary.
- Post or update the authoritative human-first change comment.
- Ask Andrew only for manual checks or decisions not already covered by agent evidence.
- Record landing approval against the current reviewed head.
- If the head changes materially, invalidate only the approval or evidence affected by that
  change and explain what must be redone.
- At merge, compare expected and current identity once.
- Merge without routine test/build/review repetition when evidence remains applicable.
- Record merge and cleanup failures precisely instead of claiming completion.

Exit condition: the approved reviewed head is merged, the authoritative comment reflects the
final state, and required cleanup is complete or explicitly reported unfinished.

## Representative composed paths to inspect

- Dispatcher routing a bounded direct fix.
- Dispatcher routing an uncertain bug to an initial task owner.
- Dispatcher resolving `gpt5.6sol` and rejecting an ambiguous model.
- Lead completing a direct change with no implementation children.
- Lead using one bounded researcher, planner, or native read-only helper.
- Lead carrying a shaped plan through approval and continuing as main.
- Lead choosing a justified fresh main after approval.
- Research-only conversation that never creates a change record.
- Research that later becomes direct work.
- Research that later creates a shaped placeholder.
- Planner challenging an infeasible or over-delegated design.
- Reviewer applying minor fixes and reporting a defensible major issue.
- QA adding specialized coverage without rerunning ordinary tests.
- Generic background wait, first-child wait, and whole-cohort wait.
- Inline mail, fallback inbox mail, reply-required mail, and interrupt.
- Direct PR with no human checks.
- Shaped PR with UI/manual checks.
- Human approval followed by an unchanged head.
- Human approval followed by a material head change.

## Scope boundaries

Included:

- Trusted workflow authority.
- Active Switchboard-owned prompt and procedure surfaces.
- Prompt assembly and development inspection.
- Model/role vocabulary resolution.
- Waiting, mail delivery, and cohort completion.
- Direct and shaped change records.
- Plan lifecycle, planner ownership, approval, review, evidence, PR rendering, and landing.
- Compatibility for current stored plans and messaging behavior.

Excluded unless implementation evidence proves necessary:

- General redesign of the board UI.
- Replacing herdr or provider adapters.
- Making prompts or capabilities a security sandbox.
- A generic autonomous workflow executor.
- Complexity scoring or automatic path selection.
- Broad GitHub client or CI orchestration unrelated to identity-bound landing.
- Reworking stable blocking, interrupt, restoration, or cleanup behavior.
- Migrating or rewriting historical briefs and completed plan records for cosmetic consistency.

## Approval boundary

Approval of this plan authorizes the implementation described here. It does not authorize
unrelated cleanup discovered during the work.

Any newly discovered decision that materially changes the adaptive path model, change-record
architecture, reviewer write authority, human approval semantics, compatibility guarantees,
or landing authority returns for human discussion before implementation continues.
