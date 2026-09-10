# Switchboard — Product and Architecture Specification

Switchboard is a visibility and control system for many concurrent coding agents.

It exists because running many Claude Code/Codex sessions otherwise means opening each one to find out what it is doing, whether it is working, blocked, waiting, done, or needs review.

---

## 1. Core abstractions

| Object | What it is |
| --- | --- |
| **Task** | The top-level user-facing scope: a grouping and supervision boundary around agents, Plans, worktrees, Questions, state and history. Not equivalent to a PR, branch, plan or implementation. |
| **Plan** | One coherent, independently landable workstream inside a Task, covering the full lifecycle of that change. |
| **Step** | A meaningful outcome or lifecycle stage inside a Plan. |
| **Agent** | An ordinary Claude Code/Codex session participating in a Task, with minimal Switchboard scaffolding. |
| **Question** | A durable structured request for information, created by an agent. |
| **Handoff** | A durable scoped artifact passing responsibility from one agent to another. |
| **Worktree** | A working environment used by agents. Not a primary user-facing object. |

```text
Task
 └─ Plan(s)
     └─ Step(s)

Agents work on those objects but are not the objects themselves.
```

A Task may contain no Plans (a codebase question), one Plan (a change), or several (a migration).

### Invariants

* One Task is isolated conceptually from another. Work in one Task must not accidentally cross into another.
* A Plan has at most one primary PR. Work needing several independently landable PRs is several Plans.
* Every active Step has exactly one accountable owner, or is explicitly `unowned` and surfaced.
* Agents are represented as a flat pool inside a Task. Parent/child relationships exist operationally and are useful internal metadata, not the product abstraction.
* Agents do not create Tasks. Task creation is a human action, through the browser or Auto Task. Delegated work stays inside the current Task as a Plan, a Step, or another agent.
* Pieces of a larger change are Plans or Steps, never nested Tasks. A new Task means a genuinely separate scope, not another implementation chunk.

### Removed from the current system

| Removed | Replaced by |
| --- | --- |
| Dispatcher | Task-level coordination (below) and the Switchboard Advisor (Section 10) |
| `lead` role | `worker` as the general-purpose default; delegation available to every agent |
| First-class `Workflow` | The Plan is the execution and lifecycle structure |
| `sb block` | Waiting derived from behaviour (Section 7) |
| Universal Stop-hook enforcement | A passive turn-end signal (Section 7) |
| Separate `Quick Task` / `Quick Agent` | The normal New Task flow is already the lightweight path |
| `next turn` vs `when idle` delivery | `NORMAL` and `INTERRUPT` (Section 7) |

### Task-level coordination

There is no mandatory permanent Task coordinator, and most Tasks never need one.

When coordination across a Task is genuinely required — sequencing Plans, reconciling results from several Plans, keeping the Task document current — that responsibility is assigned explicitly at Task creation or moved later by handoff.

If nobody holds it and coordination is required, the default coordinator is the oldest relevant agent in the Task that is not done.

This is a fallback so cross-Plan work always has a defined actor. It is not an ownership hierarchy and does not reintroduce a dispatcher.

---

## 2. Creating and starting Tasks

### Manual mode

The default flow behaves almost exactly like spawning a normal Claude Code agent: a prompt field and Create.

* prompt only → a Task containing one normal Claude agent started with that prompt
* no prompt → a Task containing one blank agent

Optional and never required: model, role, preset(s), worktree (Section 8), other initial parameters.

Nothing is added beyond what a normal session would have. A Task that is only a question gets no Plan, no review and no extra agents.

### Auto mode

Auto mode has its own separate input. The user enters a desired outcome; the request goes to a fork of the Switchboard Advisor, which proposes the initial setup — prompt(s), initial agents, roles, models, presets, worktree configuration, other Switchboard parameters — starting from the normal Task template and overriding only what this request needs.

The UI may start directly from the proposed configuration, or show it for review and editing first.

The Advisor proposes; it does not own. Once the Task is running, working agents own the Task and Plan documents and may reshape anything proposed, including any initial Plan shape.

A proposed Plan shape is a recommendation only. No Plan object exists until the working agent commits to making a code change (Section 4).

### Initial configuration is not permanent structure

Everything chosen at creation is only the starting configuration. The Task's agent population, role mix, models in use, Plans, worktrees and review shape can evolve. An existing agent's model remains fixed for its session, and agents do not generally mutate their own role (Section 5).

Initial Task customization is explicitly visible and configurable. Agents may subsequently evolve execution structure as part of doing the work, with those changes persisted in Switchboard.

---

## 3. Task and Plan state: ownership, editing, and history

### Core principle

> The human provides intent. The working agent acts as the scribe. The schema is maintained for the user, not by the user.

The user interacts through normal conversation. Agents translate that conversation into structured state. The user never populates fields and never maintains summaries.

"Build Google OAuth for now. Do not include enterprise SSO. Existing users need to keep their accounts." becomes:

```json
{
  "objective": "Add Google OAuth",
  "scope": { "in": ["Google OAuth", "existing account linking"], "out": ["enterprise SSO"] },
  "constraints": ["Existing users must retain their accounts"]
}
```

### Where information lives

| Store | Content | Written by |
| --- | --- | --- |
| Task document | title, objective, scope, constraints, success criteria, decisions, summary, notes/references | Agents |
| Plan document | Plan summary, steps, step owners, structure | Agents |
| Derived state | PR status, Plan progress, active/idle state, pending question counts, liveness, worktree state, last activity, timestamps, Needs You state | Switchboard |
| Event log | append-only history of all of the above | Switchboard |
| Handoff | scoped instructions for one receiving agent (Section 6) | Agents, at spawn |
| Question | one structured request and its lifecycle (Section 7) | Agents |

Derived state lives **outside** the editable documents. An agent's write can never set or revert it, and agents must not maintain facts Switchboard can determine itself.

The document schema stays flexible enough to add durable fields where useful.

### Who writes Task fields

| Field | Normal writer |
| --- | --- |
| title | Agent, inferred from the work; human may rename |
| objective, scope, constraints, success criteria, summary, notes | Agent |
| decisions | Agent, recording decisions established by the human or by research |
| open / closed | Human |
| operational status | Switchboard |

The human remains the authority; agents record the resulting structured state. The writer is whichever agent currently holds the relevant understanding — a researcher shaping the problem, a worker discovering a cross-cutting constraint, the agent that received a user decision, or the agent holding Task-level responsibility.

The Switchboard Advisor never writes Task or Plan documents, including their summaries.

### Editing semantics

Documents are read and written whole, not mutated field by field:

```text
read compact document → reason about the desired shape → write it back once
```

`sb task edit` and `sb plan edit` accept the complete desired document. Not: add step, rename step, assign owner, move step, add another step.

* Every edit goes through Switchboard and is serialized against other edits.
* System-owned state lives outside agent-editable documents, so agent writes cannot revert system facts.
* A submitted document contains only agent-writable fields.
* Switchboard handles rare write contention internally wherever possible, rather than requiring agents to perform explicit version-management bookkeeping. No agent-facing optimistic-locking protocol unless implementation proves it necessary.
* An agent may edit the Task it belongs to; it does not create Tasks.

### When agents update state

Not after every message. Batch changes at durable boundaries:

* after several turns of scoping finish
* when an important decision is resolved
* when research materially changes scope or constraints
* before handing off responsibility
* before `sb done`

Switchboard may remind agents to reconcile at exactly these deterministic checkpoints. It must not create speculative hooks that nag during ordinary conversation, and there is no separate background scribe process watching conversations — the working agent already has the context.

Agents ask the user only when there is a real unresolved decision, never because a field is empty.

```text
Bad:  "What should I put in the success_criteria field?"
Good: "Should Google OAuth replace password login or coexist with it?"
```

### Summary versus history

The **summary** is a short replaceable field answering *what does another agent need to know now?* It is rewritten as understanding changes and stays compact: not a transcript, not an execution history, not a completion report, not a copy of every finding. Agents tend to over-document, so summary updates are explicitly constrained to the minimum another agent would actually need.

The **history** is an automatic append-only event log answering *what happened over time?* Whenever an agent edits a Task or Plan, Switchboard records the change with enough information to reconstruct before/after state. Agents never maintain a changelog by hand.

### Task context versus Plan context

```text
Task    broad, durable, compressed context
Plan    specific context for one shaped workstream
Log     detailed underlying record
```

Plan context is more detailed and specific than Task context. Information is not copied between them; only what matters across the whole Task is promoted upward, usually compressed when it is.

```text
Plan summary: "Webhook retries use database-backed idempotency. Legacy exponential retry path can be removed after migration."
Task summary: "Webhook migration design settled."
```

Agents know this context exists and how to fetch it. It is not injected automatically into every spawn prompt.

---

## 4. Plans, Steps, review, and landing

### Creating a Plan

Any Task that results in a code change has a Plan. Creating one is extremely cheap and requires no planning ceremony.

The working agent creates the Plan at the point it commits to making a code change. Switchboard does not create Plans speculatively at Task creation, and no scaffolding appears before a change is actually being made.

The default Plan is:

```text
Implement → Review → Open PR → Merge
```

Larger changes extend it:

```text
Research → Design → Confirm with user → Implement → Review → Open PR → Merge
```

Start from the smallest useful default and add steps when needed; do not create every possible step up front and mark unnecessary ones skipped. Plans stay editable, and their structure changes only when the shape of the work changes.

A Task that is only research, discussion or a codebase question needs no Plan.

### Steps

Steps are meaningful outcomes or lifecycle stages, not implementation todos. A step may bundle several operations internally: `Open PR` includes running required checks, collecting Plan summary information, opening the PR and posting the PR summary comment. Those internals do not become separate steps.

Split a step only when the pieces have independently meaningful completion states:

> If one piece could finish while another remains incomplete, and that distinction matters for progress, ownership, recovery or review, they may deserve separate steps.

Many agents working on one step is not a reason to split it. One `Implement` step may have several contributing agents and still be one coherent outcome.

### Step ownership

Every active step has exactly one accountable owner, responsible for completing it, delegating inside it, collecting results from contributors, keeping step information accurate, and deciding when it is done.

Ownership is per step, not per Plan; different agents own different stages over time:

```text
Research → Researcher      Implement → Worker           Open PR → Worker
Design   → Researcher      Review    → Lead Reviewer    Merge   → Worker
```

Human approval is not a Step owner. Approval, or a standing pre-approval, is a condition authorizing the owning agent to execute `Merge`.

If an owner intentionally releases a step without a successor, the step becomes explicitly `unowned` and is surfaced as an attention item, so work cannot silently strand.

### Review

The Review step has one accountable owner, the **Lead Reviewer**. That is a position — the agent that owns the Review step — not a role; it will normally use the `reviewer` role.

If the change needs one review, the Lead Reviewer performs it. If it needs several specialized reviews (correctness, UI, regression, security), it delegates them and aggregates the results: deduplicating overlapping findings, removing nits and noise, reconciling severity, and returning one concise set of actionable findings to the implementing agent, rather than several parallel duplicated messages.

Specialized reviewers report only to the Lead Reviewer and do not get their own Plan steps unless their reviews are genuinely independent outcomes worth tracking separately.

An agent receiving delegated work should be able to trust a report such as "implemented, verified, independently reviewed, ready for integration" without recreating the review itself.

Review completion is declared explicitly by the Lead Reviewer. Switchboard never infers that a review finished.

### What Switchboard completes automatically

Switchboard only completes what it can establish as fact:

```text
Switchboard Open-PR operation succeeds → Open PR complete
CI finished                            → recorded on the Plan
PR successfully merged                 → Merge complete
```

`Open PR` is a bundled Step, so it completes when the whole operation succeeds, not merely because a PR exists. Observing a PR on the remote attaches the PR reference; it does not by itself imply the checks and PR-comment portions succeeded.

Everything judgment-based, review completion included, is declared by the accountable agent.

### Plan completion and landing

A Plan is complete only when the change it represents is actually finished:

```text
Implement → Review → Open PR → Human review/approval as needed → Merge → Plan complete
```

Implementation completion or PR creation alone does not complete the Plan. Because a Plan has at most one primary PR, this state is unambiguous.

Once a PR is opened, Switchboard derives that the Plan is waiting on human review and surfaces it. No agent turn is spent declaring "now waiting for Andrew".

```text
Open PR ✓   Merge ○   → Needs Human Review
```

The existing PR comment format remains the primary summary presented for human review — what changed, Plan summary and history, verification performed, review result, remaining human checks or decisions, relevant metadata. The browser surfaces or links to it rather than inventing a competing summary format.

### Changes requested, approval, and merge

If the user requests changes, the Plan structure does not change. The same worker fixes, re-reviews, pushes the updated PR, and the Plan log and PR-facing information stay current.

The browser may expose `Approve`, and optionally `Merge`, as a convenience for telling the responsible agent the current result is approved. The agent-driven path — "looks good, merge it" — remains equally valid; both enter the same underlying state.

Approval stays flexible. After requested changes the user may want to review the updated result again, or may authorize merge once the fixes are made. An explicit pre-approval lets agents merge without another round.

### Multiple Plans in a Task

Plans may run concurrently or sequentially, share agents, and use different worktrees.

Plans do not know about other Plans, and there is no built-in cross-Plan dependency graph. If Plan C should begin after Plans A and B, the agent holding Task-level responsibility knows that and decides when to start C. That dependency is Task-level reasoning, not Plan internals.

### Task completion

Task completion is a user decision. A Task with every Plan merged may stay open if the user wants to keep working in that scope; Switchboard never closes or finalizes a Task because its known work finished.

```text
All current Plans complete → Ready to Close
```

`Ready to Close` is a normal state, not an error and not an attention item. It is distinct from `Stalled` (Section 6).

Closing a Task is a strong user action meaning *this is finished and I no longer need its live execution state*. Switchboard then cleans up everything safe to remove: live agents, temporary runtime sessions, Herdr resources, worktrees where appropriate, other Task-scoped runtime resources. Durable history remains. This applies equally to large multi-Plan Tasks, single-Plan changes and small question Tasks.

An unfinished Task simply stays open. The user should never need to close Tasks merely to keep the interface manageable.

---

## 5. Agents: roles, models, and presets

Agents remain fundamentally normal Claude Code/Codex sessions. A role describes the job the agent was launched to do; it is not a permission class.

### Roles

```text
worker (general-purpose default)   researcher   reviewer   planner
```

A worker completes work directly, investigates, delegates, spawns agents and coordinates what it spawned. Delegation is a normal agent capability, not the privilege of a special role. A researcher may investigate and clarify a problem with the user, then spawn a worker to implement the result.

Roles affect prompt guidance, what Switchboard-specific context is included at spawn, and expected focus. They do **not** impose hard capability restrictions: a researcher can still edit code, run commands, delegate and spawn. Where functionality is irrelevant to a role, omit it from that role's context rather than mechanically prohibiting it. The goal is to avoid permission systems that constrain more capable future agents.

Repos may define custom roles (`frontend-reviewer`, `migration-researcher`) without changing Switchboard code.

Agents do not generally mutate their own role. If work evolves into a fundamentally different job, spawn an appropriately configured agent instead of transforming this one.

### Model

Model is an initial property of the session. There is no dynamic model switching inside a session; if another model is needed, spawn another agent with it.

### Presets

A preset is a reusable prompt or set of prompt instructions for a procedure — `adversarial-review`, `security-review`, `investigate-regression`, `architecture-critique`. It behaves like a custom skill.

```text
preset = reusable instructions
not      role + model + configuration bundle
```

A preset never selects role, model, permissions, hierarchy or runtime configuration; those are separate choices, so the same preset can apply to a different role or model.

Presets may be supplied at spawn or invoked later. A spawn-time preset enters the agent's initial context; one invoked later is loaded only at the point it is needed. Multiple presets may apply to the same agent, and repos may define arbitrary custom presets.

Because presets are only instructions, applying or invoking one does not change the agent's identity.

### Prompt separation

Starting configuration stays conceptually separate rather than mashed into one opaque generated prompt:

```text
Role guidance | Custom agent prompt | Preset A | Preset B | Task/Plan assignment
```

Agents should be able to tell which instructions came from their role, which from presets, and which are specific to their current assignment.

---

## 6. Delegation, handoff, and agent lifecycle

### Delegation

Any agent may spawn or delegate. There are no hard spawning limits; role prompts carry guidance about when delegation is useful, because rigid rules constrain more capable future agents.

Relationships stay local:

```text
A spawns B → A knows B, B knows A
B spawns C → B knows C, C knows B
A does not automatically need to know about C
```

This keeps agent context small and avoids exposing the whole Task population to every agent.

There are two patterns.

**Delegated subtask.** A remains responsible for the larger outcome; B owns a bounded piece, works independently, manages its own helpers locally, and reports one concise result when finished. A does not need constant progress updates from deeper descendants.

**Ownership handoff.** One agent finishes a phase and another becomes responsible for continuing — a researcher settling design, a worker taking over implementation through landing. The first does not remain a relay: findings are preserved in Task/Plan state, the Plan advances, the successor becomes the active agent, and the predecessor stays available for clarification but is otherwise done.

### Handoffs

A Handoff is a durable Switchboard object, not a prompt blob. It is created in the same operation that spawns or hands off to the receiving agent, and Switchboard stores it linked to sender, receiver, Task and Plan, together with any Step or assignment transfer it carries.

It contains only what the receiving agent needs: what it is responsible for, relevant conclusions and findings, important constraints, current state, what remains to be done, and where deeper supporting context lives.

A handoff is never written into a Task or Plan summary. It is transiently specific to one receiving agent, while summaries are broad durable context.

### Reporting

Agents report completion to the agent that delegated the work, without creating relay chains. If work has been fully handed off, the new agent drives the Plan to completion directly rather than reporting back through obsolete ancestors. When a Plan reaches an externally meaningful point its state surfaces at the Task level (`PR opened → Needs Human Review`, `Plan complete → Done`).

Continuity lives in durable Task/Plan state rather than agent ancestry, so agents can come and go without the parent/child tree being the only carrier of context.

### `sb done`

> `sb done` means: I have finished everything that was assigned to me.

It does not mean one message was answered, one Step was completed, or the whole Task is finished, and it does not immediately destroy the agent. Its meaning depends on assigned scope, not role:

```text
Reviewer assigned "review this change"          → done when the review result is delivered
Researcher assigned "settle design, then hand off" → done when the handoff is complete
Worker assigned "own this change end-to-end"    → done only after the PR is merged
```

Assignment scope is not the same as Step ownership. A Worker assigned to own the change end-to-end is not done after Implement: it remains responsible for driving the work through independent Review, Open PR and Merge, even though the Review Step is owned by a Lead Reviewer. Step completion and agent completion are separate concepts.

Switchboard blocks `done` while the agent still owns an incomplete required Step. The agent must complete it, hand it off, or explicitly release it as `unowned`.

`done` is not permanent. If the delegator needs more, it messages the agent, which becomes active again, completes the new assignment and reports done again. There is no separate acceptance ceremony; the completion report is enough unless the delegator decides more work is necessary.

### Derived idle and stalled state

Switchboard distinguishes why an agent is idle from observable state:

```text
has an active child whose result it awaits    → waiting on child
has an unresolved human question and stopped  → waiting on human
called sb done                                → completed
none of the above, and not working            → suspicious / unexplained idle
```

At Task level, unfinished work with unexplained inactivity is `Stalled` and is an attention item; all known work complete while the Task remains open is `Ready to Close` and is not. The goal is not to enforce a rigid ownership graph but to prevent work disappearing because every agent involved happened to stop.

### Cleanup

> Clean agents up whenever doing so is clearly safe and useful, but do not aggressively close important sessions just to keep the tree visually small.

The browser makes large numbers of agents manageable, so automatic cleanup matters less than it did.

* An agent is **never** cleaned up while it owns an incomplete Step or holds an unresolved Question it asked.
* Short-lived helpers whose contribution is fully consumed — reviewers after findings are consolidated and fixed — are cleaned up.
* Context-bearing agents, such as a researcher that handed off to a worker, stay available.

The existing cleanup rules are not carried over blindly: they were written against the dispatcher/lead tree, where parentage determined ownership, placement and eligibility. They are audited during migration and the behaviors worth keeping are rewritten in this vocabulary. The replacement must not be a complex new lifecycle system.

---

## 7. Communication, Questions, and attention

### Messaging

`sb tell` is the point-to-point primitive. Switchboard is the authoritative communication and logging layer; Herdr is the runtime delivery mechanism.

Two delivery modes:

```text
NORMAL     deliver once the target finishes its current active work
INTERRUPT  stop current work and deliver immediately, for genuinely urgent course corrections
```

If the target is done but still live, delivery reactivates it. If its runtime session is gone, the message is held and delivered when the session is restored, never dropped.

Messaging stays point-to-point. There is no shared Task chat or channel by default, and normal behaviour favours direct relationships — parent↔child, delegator↔delegate, reviewer→worker — but nothing hard-prevents messaging another relevant agent in the same Task.

> `sb tell` should be uncommon. Prefer completing a bounded unit of work and sending one concise result over continuously reporting progress.

Messages carry only what changes what the receiver needs to know or do:

```text
Review clean. No actionable findings.
2 actionable findings: 1. … 2. …
```

not a review narrative. Detailed evidence stays in logs and artifacts.

Switchboard logs communication far more comprehensively than it delivers it. A short message may carry rich structured metadata — sender, recipient, Task, Plan, Step, timestamp, type, delivery timing, associated artifacts, delivery/read state — so future analysis never requires agents to consume verbose context.

### Questions

```text
ask       an agent needs information
Question  a durable structured object
waiting   derived state, when the unresolved question actually prevents progress
withdraw  the question is no longer needed
```

`sb ask <target>` creates a durable Question associated with the asking agent and its Task, and surfaces it in the browser attention queue. Creating one does not by itself mean the agent is blocked.

Agents ask whichever party is most likely to know the answer:

| Need | Target |
| --- | --- |
| local delegated-work context | parent, or another relevant agent |
| Switchboard mechanics or configuration | Advisor — synchronous, answer returned in the command result, no durable Question |
| product or design authority | human |

`sb ask` also owns the rest of the lifecycle: `resolve`, `withdraw`, `escalate`.

```text
pending    waiting for a response
answered   a response was received, not yet consumed by the requesting agent
resolved   the agent processed the answer
withdrawn  the answer was no longer needed
```

A Question stays associated with the Task, and visible in the Task view, until the requesting agent resolves or withdraws it. It leaves the attention queue once answered. An agent holding an unresolved Question is never cleaned up. The UI does not need to expose every internal state prominently.

Withdrawal matters: if another agent discovers the answer first, the asker withdraws it so stale items do not sit in the queue.

**Escalation.** If a child asks its parent and the parent cannot answer, the parent escalates — an explicit `sb ask escalate` — retargeting the existing Question to the human while it still belongs to the original child. The answer returns directly to the child; the parent does not block or relay it.

### Waiting is derived

```text
asked and continued working  → status working,           pending questions 1
asked and then stopped       → status waiting on human,  pending questions 1
```

Switchboard derives this from actual behaviour rather than requiring agents to toggle a blocked state.

Stop-hook *enforcement* is removed: ending a turn must never require an agent to prove why it stopped, produce a message, or spend another turn. The turn-end *signal* is kept wherever the runtime provides one — passive, updating derived state at no cost to the agent. On top of that signal Switchboard infers:

```text
unanswered human question + agent stopped                              → waiting on human
owns an incomplete Step, no dependency, no child awaited, no activity  → potentially stalled
Task has unfinished work + every agent idle + no known dependency      → Task needs attention
```

Targeted mechanical checks remain where they are high-confidence, such as blocking `done` while the agent owns an incomplete Step.

### Question format

Questions reach the human out of context, mixed with questions from unrelated Tasks, so they use a compact standard format carrying the minimum needed to decide without reopening the agent session:

```text
TASK      OAuth migration
AGENT     Worker · implementing callback flow
CONTEXT   Google returns an email but the current identity model keys users by provider ID.
QUESTION  Should existing email accounts be automatically linked to matching Google identities?
OPTIONS   A. Auto-link matching verified emails
          B. Require explicit linking
RECOMMENDATION
          A — avoids duplicate accounts and matches current behaviour.
```

### Answering

**From the browser.** Switchboard knows exactly which Question is being answered, so the delivered message carries structured metadata:

```text
[sb: answer to q-17]
Andrew: Preserve the old behavior.
```

**In the terminal.** The user may instead open the agent in Herdr and talk normally. Question correctness must never depend on intercepting raw terminal typing.

Where Switchboard delivers the message itself, it attaches a reminder to the message already being delivered — this creates no extra turn:

```text
[sb: pending human question q-17]
Andrew: Yeah, preserve it for now.

[sb: pending questions q-17 "retry behavior", q-18 "migration cutoff"]
```

Where the user types directly into the session, the same minimal pending-question metadata is injected at the agent's next turn or next Switchboard-aware interaction. If Herdr later exposes a reliable input hook it is an optimization, not a correctness requirement.

The agent decides whether the user's message answers a pending Question and resolves it in the same normal turn.

Direct conversation should feel like an ordinary Claude Code session: an agent may ask follow-up questions repeatedly without mechanically cycling through blocked/unblocked states every turn. The structured system sits underneath so unanswered questions still surface elsewhere when the user is not present.

---

## 8. Worktrees, branches, and isolation

A new Task normally starts with its own worktree, giving it an isolated working environment by default. This is configurable in the Task-creation UI, so a Task that only asks a question can run in the existing checkout. The branch name need not mirror the Task name.

There is no rigid `one Task = one worktree` or `one Plan = one worktree` rule. A Task may contain several worktrees; a Plan may use the Task's worktree or another one.

**The delegator chooses placement.** When an agent spawns another, it decides whether the new agent works in the same worktree, a new one based on it, or another isolated one. This is part of the spawn decision, not inferred from role or parentage.

Agents working on the same coherent Plan normally share one worktree, especially when the Plan is one PR. Reviewers inspect the exact worktree and change they are reviewing rather than being isolated by default. Agents may still create additional worktrees inside a Plan — an isolated branch later folded back in — and nothing artificially prevents it.

Worktrees are visible in Task and Plan detail, not a prominent global abstraction. The primary user-facing objects remain Tasks, Plans and Agents.

Cleanup happens when the work associated with a worktree is complete and it holds no useful live state, commonly when a Plan's PR merges. A Task may stay open with other Plans and worktrees after one Plan's worktree is removed.

---

## 9. Persistence, restoration, and resilience

> Runtime processes are disposable. Orchestration state is not.

```text
Herdr / WSL / Switchboard / machine dies
  → durable Task and Agent state survives
  → one restore operation
  → working system reconstructed
```

### Durable active state

Switchboard persists live state continuously as it changes, so recovery never depends on a recent manual snapshot. For every open Task it knows at minimum: which agents were active, their Claude/Codex session IDs, Task/Plan/Step assignments, parent/child relationships, roles/models/presets, worktree and session mappings, pending Questions and messages, and whatever runtime metadata is needed to recreate the session.

Periodic snapshots may exist as an additional mechanism, never as the source of truth.

### Ownership of liveness

Switchboard owns durable agent identity, assignment, Task relationships and restoration metadata. The runtime owns whether the underlying process/session is currently alive.

A missing runtime session therefore never deletes a Switchboard agent. It marks the agent not currently live and restorable, with identity and assignments intact.

This split also underpins the browser↔terminal mapping: each Switchboard agent maps stably to its Herdr pane/session, which is a foundational requirement because the two surfaces remain separate but connected.

### Restore

```text
start WSL → start Herdr → sb restore
→ all open Tasks reconstructed
→ every previously live agent restored
→ Herdr/session mappings recreated
→ worktrees and assignments reconnected
→ browser returns to the previous working state
```

Restore operates from durable Task/Agent state, not heuristics such as how recently an agent was used: an agent belonging to an open Task is eligible however old it is. Restoration scope follows Task lifecycle — an open Task restores its agents, an explicitly closed Task does not.

Restored agents keep the same identity: agent ID, Task, Plan/Step assignment, role, model, parent/children, worktree, pending Questions, message and history relationships. A restored session is the same agent returning, not a newly spawned replacement. Messages and answers held for a non-live agent are delivered on restore.

The current restore system is audited during migration rather than preserved by default; anything assuming dispatcher/lead relationships does not carry over. The major improvement is making restoration complete and deterministic for all agents of active Tasks, including older long-lived sessions.

### Runtime errors

Agent processes rarely crash outright, but the underlying session can hit runtime errors or become unexpectedly idle. Where the runtime exposes a clear error signal, record and surface it. Otherwise the derived-state model catches it as potentially stalled. Avoid fragile heuristics that parse arbitrary terminal text unless they prove reliable.

During normal operation Switchboard surfaces problems rather than automatically restarting or poking agents. Automatic restoration is for explicit environment recovery after a crash or restart.

### Replaceable helpers

Not every failed agent needs restoring. A disposable helper — one reviewer inside a multi-review process — can simply be replaced by its owner: log the failure, spawn a replacement, continue. Unexpected Switchboard or runtime failures are also recorded through the existing bug-reporting mechanism. Context-bearing agents are restored rather than silently replaced.

---

## 10. The Switchboard Advisor

Each repo has a persistent **Switchboard Advisor** session: a specialist in Switchboard itself, not in the application codebase.

It knows Switchboard, configured roles, models and presets, Task/Plan/Step concepts, delegation and spawn behaviour, worktree options, the available commands, the repo's `.switchboard` configuration and other repo-specific Switchboard conventions.

It does not own Tasks, Plans or agents, receives no completion reports, and is not a general codebase expert.

### Forking

The Advisor's base session ID is saved. When Switchboard needs Advisor intelligence it forks that persistent base session and sends the request to the fork, so independent requests do not serialize through one live conversation.

A warm pool of pre-forked sessions is unnecessary; fork on demand unless startup latency later proves materially problematic. Prompt/session caching may make repeated forks cheap, but correctness and architecture must not depend on cache hits.

### Refresh

Advisor context goes stale when Switchboard itself, `.switchboard` configuration, roles/models/presets, or relevant repo conventions change. The browser exposes **Refresh Advisor**, which produces a new authoritative base session from current configuration. Switchboard detects when relevant inputs have changed and indicates staleness. If nothing relevant changed there is no reason to rebuild.

### Boundary

The Advisor makes Switchboard orchestration decisions, never product or implementation decisions.

```text
In scope:  "This request begins with substantial uncertainty, so start with a researcher."
           "This change should use the adversarial-review preset."
           "Use a separate worktree for this delegated agent."
Out:       "The application should use Redis instead of Postgres."
           "The auth architecture should use JWTs."
```

Those belong to agents actually working on the Task with codebase context. The Advisor also never writes Task or Plan documents or their summaries: it proposes configuration, and working agents own durable state.

### Uses

* **Auto Task setup** (Section 2) — proposed, not owned.
* **Answering agents' Switchboard questions** — "what preset should I use for this review?", "how do I spawn this worker into another worktree?", "how should this be represented in the Plan?", "what does this Switchboard operation mean?". These are synchronous: fork, answer, return in the command result. The Advisor is an available specialist rather than context every agent carries at spawn.
* **Explicitly requested changes** to a running Task's Switchboard configuration, such as "add an adversarial reviewer to this Task". The Advisor may make the change directly, but only at configuration level.

> Advisor actions are reactive to explicit requests. It never independently reorganizes running Tasks.

---

## 11. Configuration

Two levels only:

```text
Switchboard defaults → repo-specific overrides → effective value
```

Switchboard ships defaults for roles, presets, models, review behaviour, Task and Plan defaults, worktree behaviour and other common orchestration settings. A repo may override any of them. Changing a value in the UI creates or updates the repo override rather than modifying Switchboard's global defaults.

Most configuration is editable from the browser: toggles, model/role/preset selections, default review configuration, default Plan behaviour and other structured options. The UI distinguishes Switchboard default, repo override and effective value, and offers an easy reset to default. Raw prompt text may stay easier to edit directly as files.

Repos may define custom roles and presets without changing Switchboard code (Section 5).

Role, model, presets and other starting configuration resolve at spawn. Presets are the exception that may also be invoked later, loading only when needed. Changing repo configuration affects new agents and never silently mutates running sessions; when relevant configuration changes, the Advisor is marked stale.

> Strong defaults, easy repo-specific overrides, minimal configuration context passed to agents.

Validation catches obviously invalid values. Beyond that, configuration stays permissive: do not hard-code restrictions on combinations of roles, presets, models or Task structures.

---

## 12. Agent context and the command surface

The overriding goal is that Switchboard agents feel close to ordinary Claude Code/Codex sessions. They must not carry broad Switchboard documentation unless the current job requires it.

### Context layers

1. **Minimal universal context.** Every agent knows only: that it belongs to a Switchboard Task; its Task identity; its current assignment; that it can delegate and spawn; how to message relevant agents; how to ask the human or the Advisor; how to report `done`; how to inspect its own context; how to discover further capabilities. Detailed spawn and worktree options load only when needed.
2. **Role-specific guidance.** Only what the role needs — "review for actionable issues, report clean reviews concisely"; "investigate the assigned uncertainty, preserve durable findings, may delegate or hand implementation off". No unrelated landing, cleanup, review or Plan documentation.
3. **Assignment-specific context.** The exact scope owned: Task, Plan, assigned Step, worktree, parent, relevant handoff. Not all Task history, not every Plan, not previous Plan artifacts, not unrelated agent state.
4. **On demand.** Everything deeper is fetched when needed.

Plan knowledge stays conceptual and small:

```text
Plan = coherent landable workstream
Step = meaningful outcome inside the Plan
Each active Step has one accountable owner
Create a Plan when you commit to changing code
Inspect the Plan before acting, and keep its state accurate as work progresses
```

Correct Plan usage comes from good APIs and state enforcement, not from large prompt instructions.

### `sb context`

A cheap authoritative re-orientation command, which `sb whoami` may alias:

```text
Agent: worker-a          Task: OAuth migration     Plan: Google OAuth
Assignment: Review       Parent: worker-main       Children: reviewer-2, reviewer-3
Pending questions: none  Status: active
```

This lets agents recover their state instead of Switchboard continuously reinjecting it into prompts.

### Targeted hints

Switchboard injects guidance only from clear authoritative state transitions:

```text
Agent assigned a Plan Step             → inject Step-owner guidance once
Agent takes ownership of a Review step → inject review-orchestration guidance once
Agent attempts sb done while owning an incomplete required Step
                                       → block until it completes, hands off, or releases the Step
Agent receives human approval while responsible for Merge
                                       → expose the relevant landing action
```

No speculative hints such as "seems like it might need review" or "has been coding for a while". Where the moment cannot be identified deterministically, rely on `sb context`, `sb help` and the Advisor.

### Command surface

The primary agent-facing surface is small:

```text
sb spawn   sb tell   sb ask   sb done   sb context   sb plan   sb task   sb restore
```

Additional commands exist only for a clear repeated need. Commands whose state can now be derived — notably `sb block` — are gone.

> One conceptual action should normally require one command.

Commands accept enough information to complete one logical operation atomically. Spawning specifies the complete initial configuration in one call:

```text
sb spawn \
  --role reviewer \
  --model opus \
  --preset adversarial-review \
  --preset security-review \
  --worktree same \
  --assignment "Review the current implementation" \
  --handoff "<what the receiving agent needs to know>" \
  --take-step Review
```

`--preset` is repeatable, and one call carries both the handoff content and any Step/assignment transfer. This may internally create relationships, associate Task/Plan state, configure the runtime session and attach the assignment. The caller must never need a sequence of spawn → set role → set model → attach preset → assign Plan → assign Step → configure worktree → send initial instructions.

`sb plan` and `sb task` expose high-level operations rather than a collection of low-level mutations:

```text
sb plan create | show | take | complete | edit
sb task show | edit
sb ask <target> | resolve | withdraw | escalate
```

A Plan's initial structure is provided in one operation (`--title "OAuth migration" --steps "Research,Design,Implement,Review,Open PR,Merge"`). Operations such as `reopen` may be added if they represent genuine recurring lifecycle actions. Underlying database operations may remain granular internally; agents interact with the higher-level transaction. Editing semantics — whole documents, agent-writable fields only, serialization handled by Switchboard — are defined in Section 3.

`sb context` is the general-purpose inspection and reorientation command; avoid creating many overlapping top-level inspection commands. `sb plan show` remains for Plan-specific inspection.

Three primitives stay semantically distinct even though they share underlying infrastructure:

| Command | Why it stays separate |
| --- | --- |
| `sb done` | Switchboard must know the agent believes its assigned scope is complete; it is not an ordinary `tell` |
| `sb ask` | Routes structured requests for information; human and agent asks may create durable Questions, while Advisor asks are synchronous |
| `sb tell` | Lightweight point-to-point delivery; must not acquire question or lifecycle semantics |

### Output

Every command defaults to the minimum information the caller needs for its next decision, and accounts for who is asking. A reviewer running `sb plan show`:

```text
Plan: OAuth migration

✓ Implement — Worker A
→ Review — you
○ Open PR
○ Merge

Implementation: complete
PR: not opened
```

Not all prior artifacts, full design and research text, the entire Plan changelog, every ownership transition, unrelated agents or verbose metadata.

Three levels, applied consistently:

```text
default  compact, readable, context-aware
--json   stable structured output, large fields summarized or truncated
--full   complete detail when explicitly requested
```

Even `--json` avoids embedding large artifact bodies; artifacts appear as `{id, type, summary}` and their content is fetched explicitly.

### Migration

The CLI is an API simplification pass, not a renaming exercise. Every existing command is audited against: is this still a real concept; can its state be derived instead; does it overlap another command; do common operations require several calls that could be one transaction; is its default output too large; does it expose implementation detail unnecessarily. That audit determines the final CLI rather than assuming the existing surface survives.

The API optimizes for agents — predictable semantics, low token usage, stable structured interfaces, minimal round trips, easy discovery — because humans increasingly use the browser. Old agent-facing commands may break where that materially simplifies the system. Compatibility is kept only where cheap and harmless, never at the cost of carrying two conceptual models.

---

## 13. Browser surface

```text
Browser  visibility and control
Herdr    live terminal sessions and processes
```

The browser does not replace Herdr. Clicking an agent opens or focuses that exact agent's terminal session, using the stable agent↔pane mapping described in Section 9.

Three top-level views:

**Tasks.** The main organizational unit. Each open Task shows enough to understand its current state — objective/name, its live agents and their status, Plan progress, whether human attention is needed, recent meaningful activity. Opening a Task exposes its agents, Plans, Questions, history and worktrees. It should be easy to see which agents are alive, which Task each belongs to, and which one to inspect.

**Needs You.** The cross-Task human attention queue, containing only items where human action is useful:

* unanswered human Questions
* PRs ready for review
* stalled agents and Tasks
* unowned Steps on active Plans
* surfaced runtime errors
* other explicit user decisions

Items are derived from current authoritative state and disappear automatically when the condition resolves — question answered, PR approved or merged, stalled agent resumes. No manual dismissal. It must not become a general notification feed, and `Ready to Close` Tasks belong in the Tasks view, not here.

**Activity.** A lightweight cross-Task history of meaningful events, useful for visibility and debugging, secondary to the other two, and never interrupting the user.

### Actions

New Task, Auto Task, open/focus an agent terminal, answer a Question, approve a PR, optionally merge, close a Task, restore the environment, refresh the Advisor, edit repo configuration, and spawning an agent as a convenience.

Humans generally do not edit Plans in the browser. Plans are agent-managed execution structures, and human interaction with them is decisions and approvals rather than low-level maintenance. Inspecting Plans should nonetheless be easy.

Browser actions and CLI/agent actions operate through the same underlying state and operations. There are no browser-only orchestration semantics: browser `Approve` and telling an agent "looks good, merge" enter through different interfaces but update the same Task/Plan/message state.

> Organize around Tasks and human attention, not a global wall of agents.

The first browser implementation should focus on rendering real Tasks with their live agents and status, navigating into a Task, and jumping to the correct Herdr terminal. Beyond the states defined in this document, task status vocabulary and precedence, card layouts and queue organization are deliberately left open and should be iterated on once the core framework works.

---

## 14. Logging, history, and analytics

Claude Code and Codex already persist full agent transcripts, so Switchboard does not copy them. Each agent retains enough identifying information to locate its underlying session and transcript when deeper inspection is needed.

```text
Claude Code / Codex → full agent transcript
Switchboard         → structured orchestration history + references to those sessions
```

Switchboard stores normal mutable current state plus an append-only event log. The product is not otherwise event-sourced unless that later becomes clearly useful.

Logged events include: Task creation and close; Plan creation, change and completion; Step assignment, completion and release; agent spawn, done and cleanup; parent/child relationships; handoffs; `tell`, `ask` and `done` messages; question answers, escalations and withdrawals; review activity; worktree creation and cleanup; PR creation and merge; role/model/preset used; important status transitions; timestamps and durations.

Full Switchboard message text is retained. Storage efficiency is not an important constraint.

Task, Plan, Step and Agent history are different filtered views of this one event history, never independently maintained logs.

No large fixed analytics system initially. Store enough raw structured information that useful metrics can be derived later: time waiting on human, time waiting on another agent, agent and message counts, review loops and turnaround time, model/role/preset usage, Plan and Task duration, failure and retry patterns.

Keep structured history locally and retain it indefinitely for now. Export, dashboards, aggregation and retention policies can be added later if they become useful.

> Record rich operational data now; decide what to analyze later.
