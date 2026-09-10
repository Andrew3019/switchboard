# Switchboard — Product and Architecture Specification

Switchboard is a visibility and control system for many concurrent coding agents.

It exists because running many Claude Code/Codex sessions otherwise means opening each one to find out what it is doing, whether it is working, blocked, waiting, done, or needs review.

> **Note for implementation.** Treat the behavioural invariants in this document as requirements, and prefer the simplest implementation that satisfies them. The explanatory machinery here — state tables, object shapes, named timers — exists to make those invariants checkable, not to mandate additional abstractions where existing Switchboard behaviour already satisfies the same invariant.

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
* Steps in a Plan are ordered. A Step becomes **eligible** when every preceding Step is complete; Switchboard derives that transition on predecessor completion. An eligible, incomplete Step is `active` unless it is `blocked` or `failed` (Section 4). Every `active` Step has exactly one accountable owner, or is explicitly `unowned` and surfaced. Assigning an owner to a not-yet-eligible Step is legal and pre-stages ownership; the unowned-Step attention item fires only for `active` Steps.
* Agents are represented as a flat pool inside a Task. Parent/child relationships exist operationally and are useful internal metadata, not the product abstraction.
* Agents do not create Tasks. Task creation is a human action, through the browser or Auto Task. Delegated work stays inside the current Task as a Plan, a Step, or another agent.
* Pieces of a larger change are Plans or Steps, never nested Tasks. A new Task means a genuinely separate scope, not another implementation chunk.

### Removed from the current system

| Removed | Replaced by |
| --- | --- |
| Dispatcher | Task-level coordination (below) and the Switchboard Advisor (Section 10) |
| `lead` role | `worker` as the general-purpose default; delegation available to every agent |
| `builder`, `qa`, `py-qa` roles | folded into `worker`; a repo wanting them keeps them as custom roles (Section 5) |
| First-class `Workflow` | The Plan is the execution and lifecycle structure |
| `sb block` | Waiting derived from behaviour (Section 7) |
| Universal Stop-hook enforcement | A passive turn-end signal (Section 7) |
| Separate `Quick Task` / `Quick Agent` | The normal New Task flow is already the lightweight path |
| `next turn` vs `when idle` delivery | `NORMAL` (next turn boundary) and `INTERRUPT` (Section 7) |

### Task-level coordination

There is no mandatory permanent Task coordinator, and most Tasks never need one.

When coordination across a Task is genuinely required — sequencing Plans, reconciling results from several Plans, keeping the Task document current — that responsibility is assigned explicitly at Task creation or moved later by handoff.

If nobody holds it and coordination is required, the fallback coordinator is the most able **eligible** agent: eligible means `live` and neither `completed` nor `stalled`; among those Switchboard prefers one that owns an `active` Step in the Task, falling back to earliest `created_at` (preserved across restore, agent-ID tie-break) only if none does — so the hat lands on an agent actually driving work rather than systematically on a parked, handed-off researcher. If no agent is eligible, the human assigns one; a Task where nothing is advancing is already covered by `Stalled` (Section 6) and needs no separate attention item.

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

By default the UI shows the proposed configuration for review and editing before anything is spawned, consistent with "the Advisor proposes; it does not own". A repo setting (`auto_task.skip_review`, Section 11) may start directly from the proposal instead.

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
| Plan document | Plan summary; editable step *structure* — IDs, names, order, and the kind of a Step being created | Agents |
| System-held Plan state | step *ownership*, step *completion*, step *kind*, the Plan's branch/worktree binding, PR/CI facts | Switchboard |
| Derived state | PR status, Plan progress, active/idle state, pending question counts, liveness, worktree state, last activity, timestamps, Needs You state | Switchboard |
| Event log | append-only history of all of the above | Switchboard |
| Handoff | scoped instructions for one receiving agent (Section 6) | Agents, at spawn or handoff |
| Question | one structured request and its lifecycle (Section 7) | Agents |

Derived state lives **outside** the editable documents. An agent's write can never set or revert it, and agents must not maintain facts Switchboard can determine itself. In particular, a Step's *completion*, *ownership* and *kind* are system-held, not fields in the agent-submitted Plan document: a whole-document `sb plan edit` carries step names, order, and the kind of *newly added* Steps only, and can never revert `Open PR ✓` or `Merge ✓`, write itself in as a Step's owner (bypassing the `take`/`--assign-step`/`--steal` guards), or change an existing Step's kind. Ownership changes go exclusively through the ownership verbs (Section 4). Judgment-based completion (a Review the Lead Reviewer declares finished) is recorded through a dedicated verb, not by writing a completion flag into the document (Section 4, Section 12).

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
* Serialization orders concurrent writes but does not by itself prevent a lost update: an agent that read the document before another agent's write would otherwise clobber it by writing back its whole stale copy. Switchboard prevents this with an implicit base version the agent never reasons about: `sb task show` / `sb plan show` return an opaque version token, and `sb task edit` / `sb plan edit` carry it back automatically. On a stale write Switchboard compares the submitted document to the current one **field by field** against the shared base: fields the submitter did not touch are taken from the current document, and the write is accepted as a merge. Only a genuine conflict — both writers changed the *same* field to different values — is rejected, and then with the current document and a one-line "re-read and re-apply" instruction. This keeps the common case (a researcher writing `scope` while another agent writes `decisions`) collision-free without any agent-facing locking protocol, and confines the cost of a real conflict — one re-read-and-reason turn — to the rare true overlap rather than to every concurrent edit. An edit that carries no version token is not refused: with no base to merge against it is applied as a plain write of the agent-writable fields it contains. Agents never construct or compare version tokens by hand, and a true conflict is expected to be rare — this must not become a read-before-write ceremony on every edit.
* An agent may edit the Task it belongs to; it does not create Tasks.
* Because the scribe writes the very scope it is later measured against, *narrowing* it is recorded rather than silent: an edit that **removes** an item from `scope.in`, `constraints`, or `success criteria` is logged as a scope-narrowing event naming the removed item and the agent, and shown in Activity (Section 13). Additions and clarifications are free. This is a visibility record, not an approval gate — the human is not made an approver of their own agents' bookkeeping.
* `decisions` entries carry a `source` (`human`, `research`, or `agent-judgment`), rendered wherever a decision is read, so an ambiguity the agent resolved itself is not mistaken downstream for settled human authority.

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

The line between asking and deciding is a rule, not a feeling, because the costs are lopsided — asking the Advisor is free, deciding alone is free, asking the human is the only option that creates a durable object and holds the Task open, so an agent left to "judge" will drift toward not asking. The rule: **ask the human when resolving it would change scope, constraints, or user-visible behaviour; otherwise decide it yourself and record it in `decisions` with `source: agent-judgment`.** That gives two agents (or one agent twice) the same answer, and makes the self-decided calls visible rather than laundered into settled authority.

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

**The reminder to do this is delivered, not carried.** It is a turn-start hint (Section 12), not a line in the standing spawn prompt. This is an observed result in the current system, not a preference: the same instruction sitting in the spawn prompt is widely ignored, while the same instruction delivered at turn start, or relayed by another agent as a message, is complied with. Section 12 records why. A Plan-creation norm that lives only in the standing prompt should be assumed not to fire.

A Plan always has at least one Step: `sb plan create` without `--steps` starts from the default Plan below, never from an empty one, and `sb plan edit` refuses an edit that would leave zero Steps. A Plan with no incomplete Steps is `complete` only if it has at least one Step; the vacuous "all zero Steps complete" is not a completion. This keeps a freshly created or mid-reshape Plan from flipping to `complete` (and its Task to `Ready to Close`) before any real Step exists.

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

### Step states

A Step is in exactly one of:

```text
pending   preceding Steps not all complete; not yet eligible
active    eligible (all preceding Steps complete), incomplete, not blocked or failed; has
          an owner or is unowned
blocked   `Merge` awaiting the human authorization to merge — the one merge precondition
          no agent can act on. Not idle, not an attention item on its own. When the
          authorization lands the Step returns to `active` for the owner to merge; if a
          human merges directly, Switchboard observes it and the Step goes straight to
          `complete`. A red CI or an unresolved `major` Finding does *not* block the Step:
          those are agent-actionable, so `Merge` stays `active` (Section 4)
failed    a bundled operation half-succeeded or a local check failed (Section 4); or a
          terminal system Step whose remote fact was later observed false (its PR was
          closed); carries what failed and is retryable
complete  finished (a judgment Step may still be reopened; see below)
```

There is no `skipped` state: unnecessary Steps are never created rather than created and skipped. Completion is derived state (system-held), never a flag in the agent-submitted document. Two ways a Step reaches `complete`:

* **System-completed** Steps (`Open PR`, `Merge`) — Switchboard sets `complete` when it establishes the fact itself. Agents cannot complete these, and cannot revert them. A system Step leaves `complete` in only two ways, both driven by Switchboard, never by an agent write: (a) its established fact is later observed false — the derivation tick finds the PR closed, superseded, or gone — and it moves `complete → failed` carrying the reason, after which `sb plan step retry` opens a fresh PR (the "at most one primary PR" invariant counts the live PR, so replacing a dead one is legal); or (b) an earlier judgment Step is `reopen`ed, which *suspends* it to `pending` while keeping its established facts (the PR stays open); when eligibility returns the Step goes back to `active` and its owner is woken to re-run the bundle against the new head — reusing the existing PR, refreshing the summary comment and re-running the local checks (so it can re-enter `failed`) — as the requested-changes loop below describes. A retry after a `failed` bundle — as opposed to a dead PR — reuses the live PR rather than opening a second one.
* **Judgment-completed** Steps (`Review`, `Implement`, `Research`, `Design`) — the accountable owner declares completion with `sb plan complete --step <Step>` (Section 12). Switchboard accepts it only from that owner and rejects it for system-completed Steps.

**Steps have a stable identity and a fixed kind.** This is what makes "an agent's whole-document write can never revert completion" actually hold.

* Each Step carries an opaque **ID** assigned at creation, distinct from its display name. All system-held state — completion, ownership, kind, PR/CI facts, events — is keyed to the ID, never to the name.
* Each Step carries a **kind** — `implement`, `review`, `research`, `design`, `open_pr`, `merge`, or a repo-defined kind — set at creation from the declared step type, immutable thereafter, independent of the display name.
* **Kind, not name, confers powers.** Kind decides whether a Step is system-completed (`open_pr`, `merge`) or judgment-completed, and which Step the review-independence record applies to (`review`). Renaming `Open PR` to `Raise PR` cannot turn a system Step into one the agent completes itself; naming a Step `Ship it` cannot smuggle in a merge the agent declares done — an unrecognized name is a judgment Step with no special powers.
* **Edits are read against IDs.** A renamed Step keeps its ID, kind and completion; a Step submitted with no ID is new; a previously-present ID that is absent is a deletion.
* **Structural edits are validated, and refused with a reason.** Because eligibility depends on order and order is agent-writable, Switchboard rejects an edit that reorders or deletes a `complete` system Step, or moves an incomplete Step ahead of a `complete` one. It also refuses more than one `open_pr`- or `merge`-kind Step, and an `open_pr`/`merge` pair out of order or half-present — the two appear together and in order or not at all — so `Implement, Merge, Open PR`, or a `Merge` with nothing to merge, is caught at authoring time.
* A change that puts commits on a branch cannot reach Plan `complete` without a completed `merge`-kind Step; otherwise the Plan stays `in progress` and surfaces.
* Commands name a Step by display name for convenience; Switchboard resolves it to the ID and errors on an ambiguous or unknown name (Section 12).

### Step ownership

Every active step has exactly one accountable owner — or is explicitly `unowned` and surfaced (below) — responsible for completing it, delegating inside it, collecting results from contributors, keeping step information accurate, and deciding when it is done.

Ownership is per step, not per Plan; different agents own different stages over time:

```text
Research → Researcher      Implement → Worker           Open PR → Worker
Design   → Researcher      Review    → Lead Reviewer    Merge   → Worker
```

Human approval is not a Step owner. An approval, or a pre-approval (both defined under "Changes requested, approval, and merge" below), is a condition authorizing the owning agent to execute `Merge`.

If an owner intentionally releases a step without a successor, the step becomes explicitly `unowned` and is surfaced as an attention item, so work cannot silently strand.

The ownership operations (`take`, `release`, `complete`, `reopen`, `--steal`) are serialized through Switchboard exactly as document edits are, so the "exactly one accountable owner" invariant is mechanized, not merely asserted: two agents racing `take` on the same `unowned` Step resolve to one winner and one refusal, and `complete` racing a `--steal` resolves deterministically by arrival order. `--steal` takes an owned Step. It is recorded as an event and delivers a `NORMAL` message to the previous owner naming the Step and the new owner, so a steal is never silent; the notification, not a restriction on when it may be used, is the safeguard. Its normal use is recovering a Step from a stopped owner, but stealing from a live owner is not blocked — that is a coordination problem better surfaced than prevented.

### Review

The Review step has one accountable owner, the **Lead Reviewer**. That is a position — the agent that owns the Review step — not a role; it will normally use the `reviewer` role.

**Review should be independent**, and where it is not, that is recorded rather than hidden. The implementing agent may still review its own work at a basic level — roles are not permission classes (Section 5), and blocking it would deadlock a small change on a second session. But "independently reviewed" is a claim a delegator relies on, so Switchboard tests it instead of taking it on trust: if the agent completing the `review`-kind Step owns, owned, or is a recorded contributor to an `implement`-kind Step on this Plan, the completion is recorded as `review_independence: self-reviewed` and surfaced on the PR comment. Step contributorship is already tracked, so this needs no commit-attribution heuristic (agents on one Plan share a worktree and one git identity, so git authorship could not distinguish them anyway). The default expectation stays a separate reviewer; the record makes the exception visible.

If the change needs one review, the Lead Reviewer performs it. If it needs several specialized reviews (correctness, UI, regression, security), it delegates them and aggregates the results: deduplicating overlapping findings, removing nits and noise, reconciling severity, and returning one concise set of actionable findings to the implementing agent, rather than several parallel duplicated messages.

Specialized reviewers report only to the Lead Reviewer and do not get their own Plan steps unless their reviews are genuinely independent outcomes worth tracking separately.

An agent receiving delegated work should be able to trust a report such as "implemented, verified, independently reviewed, ready for integration" without recreating the review itself.

A review produces durable **Findings**, not just a chat message — because "no unresolved major review finding" is a merge precondition (below) and a precondition needs something real to test. A Finding is a small durable object `{id, plan, step, severity (major|minor|nit), title, body, raised_by, resolved_by, resolved_at, resolution_note}`, created with `sb plan finding raise` and cleared with `sb plan finding resolve <id>`. The `title`/`body` are what the implementing agent and the `Needs You` item render; `resolution_note` records how it was addressed. Nits are dropped rather than recorded; minors may be fixed in place by the reviewer and named; a major returns to the implementing agent. An unresolved `major` Finding blocks `Merge`. This is also the reviewer's reopen path: a Lead Reviewer that raises a major Finding requiring code changes reopens `Implement` (the same requested-changes loop the user path uses), rather than the loop being reachable only when *the user* asks.

`reopen` suspends every later Step (Section 4 above), so it is always recorded as an event naming the agent that called it. It is rejected once the Plan's `merge`-kind Step is complete: a merged Plan is terminal, and a post-merge concern is a new Plan, not a reopening of a landed one.

Review completion is declared explicitly by the Lead Reviewer, and Switchboard rejects the declaration while an unresolved `major` Finding stands on the Plan, so a review cannot be closed over an open major. Switchboard never infers that a review finished.

### What Switchboard completes automatically

Switchboard only completes what it can establish as fact:

```text
Switchboard Open-PR operation succeeds → Open PR complete
CI finished                            → recorded on the Plan
PR successfully merged                 → Merge complete
```

`Open PR` is a bundled Step, so it completes when the whole operation succeeds, not merely because a PR exists. Observing a PR on the remote attaches the PR reference; it does not by itself imply the local checks and PR-comment portions succeeded. The "required checks" it runs are the repo-configured list of **local** commands (Section 11), defaulting to the repo's test command; a repo may add lint, build or type checks. These run before completion; if one fails, or the PR opens but the summary comment does not post, the Step enters `failed`, carrying which sub-operation failed, and its owner retries with `sb plan step retry`. The operation is idempotent: retrying reuses the existing PR rather than opening a second one.

**Remote CI is a Plan-level fact, not part of `Open PR`.** After the PR exists, the remote's checks are tracked on the Plan as `ci: pending | green | red`, updated by the derivation tick (Section 7). CI is therefore not something `Open PR` waits on and not a Step of its own; a red CI does not reopen the terminal `Open PR` Step. Instead, CI status is a **merge precondition**: `Merge` requires a live authorization *and* CI not `red` *and* no unresolved major review finding.

The three preconditions are not alike, and Switchboard treats them differently. A missing authorization is external — no agent can supply it — so `Merge` is `blocked` and the wait surfaces as `Needs Human Review`. A red CI or an unresolved `major` Finding is **agent-actionable**: `Merge` stays `active`, the `merge` operation refuses while the condition stands, and Switchboard wakes the responsible owner to fix it. Its owner is therefore not excused from stall derivation, and the human is not paged for work an agent should be doing. Only if the condition is still unrecovered past `attention_timeout`, or the responsible agent explicitly asks, does it become a `Needs You` item.

Everything judgment-based, review completion included, is declared by the accountable agent.

### Plan completion and landing

A Plan is complete only when the change it represents is actually finished:

```text
Implement → Review → Open PR → Human review/approval as needed → Merge → Plan complete
```

Implementation completion or PR creation alone does not complete the Plan. Because a Plan has at most one primary PR, this state is unambiguous.

Once a PR is opened, Switchboard derives that the Plan is waiting on human review and surfaces it. No agent turn is spent declaring "now waiting for Andrew".

```text
Open PR ✓   Merge ○   → Needs Human Review   (→ awaiting merge if an authorization is already live)
```

The worker that owns the change end-to-end owns the incomplete `Merge` Step while the PR waits. That Step is `blocked` (awaiting the human's approval, an external event Switchboard already tracks), so the worker is **not** derived as stalled: its derived state is `awaiting external`, which is excluded from stalled-agent attention because the `Needs Human Review` item on the Plan already represents the same wait. For the same reason `sb done` is not blocked by a `blocked` Step (Section 6) — the owner may stay live-and-idle, or `sb done` and be reactivated. When approval lands the `Merge` Step returns to `active`, and Switchboard delivers a message to its owner — the same reactivation mechanism `sb tell` uses, which wakes a `completed`-but-live owner and is held for a not-live one until restore — so an approved PR is actually driven to merge rather than sitting under a stopped owner. The owner performs the merge; if a human merges directly from the browser or GitHub instead, Switchboard observes the merge (Section 9, remote-fact observation) and completes the Step. Either way the wait for review surfaces only as `Needs Human Review` (a red CI raises its own item only if the owner fails to act on it) — never a phantom stall or a phantom unowned Step — and an approved-but-unmerged PR whose owner never resumes is surfaced by the stopped-owner backstop (Section 6).

The existing PR comment format remains the primary summary presented for human review — what changed, Plan summary and history, verification performed, review result, remaining human checks or decisions, relevant metadata. The browser surfaces or links to it rather than inventing a competing summary format.

### Changes requested, approval, and merge

If the user requests changes, the Plan structure does not change, but the judgment-completed Steps it must redo are reopened: `sb plan reopen --step Review` (and `Implement` if needed) moves a `complete` judgment Step back to `active`, recorded as an event, so the redone work is tracked and owned rather than happening invisibly outside any Step.

Reopening a Step **suspends every later Step to `pending`** (a defined `complete`/`blocked`/`active → pending` transition used for this cause only), because eligibility depends on predecessors being complete and they no longer are. This closes the gap where a `pre-approval` — which by design survives the fixes' push — could otherwise let `Merge` execute while the re-review is still open: a suspended `Merge` is not eligible, and `Merge` never executes while any earlier Step is incomplete, whatever authorization exists. System-completed Steps keep their established facts while suspended (the PR stays open); once eligibility returns, the suspended `Open PR` Step goes from `pending` back to `active` and its owner is woken (the same wake the merge path uses) to re-run the bundle against the new head with `sb plan open-pr` — refreshing the PR summary comment and re-running the local required checks, and reusing the existing PR rather than opening a second one — which is what keeps the PR-facing information current after the fixes land. When the reopened Step re-completes, the suspended Steps re-eligibilize in order. Throughout, the same worker fixes, re-reviews, and pushes the updated PR, which invalidates any plain `approval` on the old head; the Plan log and PR-facing information stay current.

**Merge authorization is a durable object**, like a Question or a Handoff, not a transient message. It records `{id, plan, kind, pr_head, granted_by, granted_at, confirmed, revoked}` and comes in two `kind`s, because a human authorizing a merge means one of two different things:

* **`approval`** — bound to a specific PR head (`pr_head` set). It authorizes merging *that* content and is invalidated by any later push, so a merge of an approved head always reflects content the human actually saw. This is the default and the only path for "I have reviewed this exact diff."
* **`pre-approval`** — Plan-scoped, not head-bound (`pr_head` empty). It authorizes merging this Plan once the agreed fixes land, without another review round. It survives the fixes' push by design — that is its whole purpose — and is the human explicitly trading review of the final diff for speed. It is therefore the one path that can merge content the human has not seen, and remains valid until used or revoked.

`Merge` requires a live authorization: an `approval` whose `pr_head` matches the current head, or an unrevoked `pre-approval` for the Plan. There is no repo-wide standing authorization; both kinds are scoped to one Plan. Authorization is necessary but not sufficient: the full merge precondition is a live authorization **and** CI not `red` **and** no unresolved major review finding **and** no earlier Step incomplete (see "What Switchboard completes automatically" and the requested-changes loop above). `Merge` re-fetches the live PR head and re-checks the authorization against it at execution time (Section 7), so a push since the last tick cannot slip through a stale-but-matching `approval`.

Both entry paths write this same object, but they differ in how far they are trusted.

* **Browser `Approve`** is the human acting in a Switchboard-visible way. It resolves the `Needs Human Review` item outright, and is the only path that can grant a `pre-approval` — the human picks that explicitly.
* **Agent-relayed** — the user tells the agent "looks good, merge it" — is equally valid but carries the risk the agent misread a "looks good" that was about a design or a summary rather than this diff. The agent records it with `sb plan approve`, quoting the user's words into the event log. It may record only an `approval`, never a `pre-approval`, so an agent cannot upgrade a casual "looks good" into standing merge authority. It is marked `granted_by: agent-relayed`, `confirmed: false`.

A relayed approval is a live authorization: the merge proceeds and the Plan moves to `awaiting merge`, so the fast path is not blocked when the relay was correct. It also raises its own durable `Needs You` item — `Merge (this diff) authorized by <agent> from your message — confirm or flag` — derived from the authorization being `agent-relayed`, not `confirmed`, and not `revoked`. That item is **independent of the merge**:

* it survives the merge, becoming `Merged on a relayed approval — confirm or flag`, so a merge racing ahead never destroys the human's chance to notice a misread
* it clears when the human confirms or flags/revokes it (browser actions, Section 13); a revoke after the merge does not un-merge — it records the misread for the human to unwind deliberately
* it also clears if a later push invalidates the approval before any merge, with an event recorded, so a fix cycle does not leave a stale item or accrete one per round

Whether review is needed at all is the human's call, expressed by which kind they grant; absent any, an agent does not merge.

Approval stays flexible. After requested changes the user may want to review the updated result again — a plain `approval` was invalidated by the fixes' push, so a fresh one is required — or may have granted a `pre-approval` up front so agents merge once the fixes are made without another round.

### Multiple Plans in a Task

Plans may run concurrently or sequentially, share agents, and use different worktrees.

Plans do not know about other Plans, and there is no built-in cross-Plan dependency graph. If Plan C should begin after Plans A and B, the agent holding Task-level responsibility knows that and decides when to start C. That dependency is Task-level reasoning, not Plan internals.

### Task completion

Task completion is a user decision. A Task with every Plan merged may stay open if the user wants to keep working in that scope; Switchboard never closes or finalizes a Task because its known work finished.

A Task is `Ready to Close` when all of the following hold: **work has actually happened** — a completed Plan, or (for a Plan-less Task) its initiating agent has called `sb done`, which for a blank no-prompt agent means after it has taken at least one turn (so a just-created Task is not vacuously ready) — **and** every Plan is complete, no Step is incomplete, no Question is unresolved, and no agent is working. This one predicate is used everywhere `Ready to Close` is referenced (Section 6, Appendix A), and covers Plan-less question Tasks, blank Tasks and multi-Plan Tasks alike. `Ready to Close` is a mechanical *work-exhausted* signal — no tracked work remains — not a claim that the objective or every success criterion was met; the human judges that at close, which is why closing stays a human action and Switchboard never closes a Task itself.

```text
completed work present, every Plan complete, no open Step/Question, no agent working
    → Ready to Close
```

`Ready to Close` is a normal state, not an error and not an attention item. It is distinct from `Stalled` (Section 6).

Closing a Task is a strong user action meaning *this is finished and I no longer need its live execution state*. Switchboard then cleans up everything safe to remove: live agents, temporary runtime sessions, Herdr resources, worktrees whose removal predicate is satisfied (Section 8; one holding unpushed or uncommitted work is retained and surfaced, not destroyed), other Task-scoped runtime resources. All of the Task's `Needs You` items leave the queue on close, including any that by design survive their triggering event (a post-hoc relayed-approval `confirm or flag`) — closing the Task is the human disposing of them. Durable history remains. This applies equally to large multi-Plan Tasks, single-Plan changes and small question Tasks.

An unfinished Task simply stays open. The user should never need to close Tasks merely to keep the interface manageable.

---

## 5. Agents: roles, models, and presets

Agents remain fundamentally normal Claude Code/Codex sessions. A role describes the job the agent was launched to do; it is not a permission class.

### Roles

```text
worker (general-purpose default)   researcher   reviewer   planner
```

A worker completes work directly, investigates, delegates, spawns agents and coordinates what it spawned. Delegation is a normal agent capability, not the privilege of a special role. A researcher may investigate and clarify a problem with the user, then spawn a worker to implement the result. A reviewer critiques a change and reports findings. A planner shapes and sequences a larger body of work — breaking an objective into Plans and Steps and recommending how to stage them — without owning the implementation; it is the role reached for when a Task needs deliberate up-front structuring rather than a worker that plans as it goes. None of these are permission classes.

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

A Handoff is a durable Switchboard object, not a prompt blob. It is created in the same operation that reaches the receiving agent: `sb spawn --handoff …` when the receiver is new, or `sb tell --handoff …` when handing to an existing agent. Either way Switchboard stores it linked to sender, receiver, Task and Plan, together with any Step or assignment transfer it carries.

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

Switchboard gates `done` on more than Step ownership, because assignment scope — not Step ownership — is what `done` actually means, and the two differ (a Worker assigned end-to-end is not done at Implement). So assignment scope is made machine-visible via end-to-end Plan ownership. The agent that runs `sb plan create` is recorded as the Plan's end-to-end owner by default (the normal path, since the working agent creates the Plan when it commits to a change); `sb plan create --no-own` opts out when the creator is only scaffolding for someone else, and `sb spawn --own-plan <plan>` or a `--handoff` that transfers the Plan assigns it to another agent. While an agent holds end-to-end ownership of a Plan, `done` is blocked while that Plan still has any `active` or `failed` Step, or until ownership is handed off. A Plan whose only incomplete Step is `blocked` (its `Merge` awaiting the human authorization) does **not** block `done` — the owner stays reactivatable and is woken to merge when the block clears, exactly as the `blocked`-Step exemption on the Step gate allows. This still closes the two one-command false-completion exits: the spawn-a-child-and-`done` case leaves `Implement` `active` (end-to-end ownership unmet), and escaping work by releasing a Step leaves the Plan with an `active`/`failed` gap — both block `done`.

Switchboard also blocks `done` while the agent owns an **incomplete Step that is not `blocked`** — that is, an `active` or `failed` owned Step; only a `blocked` Step (`Merge` awaiting the human authorization) is exempt, because its owner stays reactivatable and the `Needs Human Review` item already represents the wait. To clear such a Step the agent completes it, hands it off, or explicitly releases it as `unowned`. `release` requires a reason, and a `done` in the same assignment reports the released Steps to the delegator ("released: Implement — <reason>"), so dropping scope reaches the delegator and not only the human queue. A `blocked` Step cannot be released — releasing it would strand an approved PR with no owner to merge — so an end-to-end owner awaiting merge either stays live-and-idle or `sb done`s and is reactivated when approval lands.

Because the completion report is the sole evidence the delegator relies on to *not* redo the work, `sb done` requires a minimal shape, enforced by the command rather than by prose: **what was done**, **what was verified and by what command** (or explicitly "not verified"), and **what was not done** (or "nothing outstanding"). The third field is the one that matters — it makes a dropped or deferred piece of scope visible in the report itself rather than only in a queue the delegator does not watch, and it costs an honest agent one line. Everything else stays minimal: this is three short fields, not a narrative.

`done` is not permanent. If the delegator needs more, it messages the agent, which becomes active again, completes the new assignment and reports done again. There is no separate acceptance ceremony; the completion report is enough unless the delegator decides more work is necessary.

### Derived idle and stalled state

Switchboard distinguishes why an agent is idle from observable state. Crucially, the *reason* is derived from what the agent currently owns and awaits — a standing obligation — not from having observed the moment it stopped. This matters because the turn-end signal is only an optimization (Section 7): an agent with a pending human Question and no activity is `waiting on human` whether or not a turn-end signal ever arrived. An agent is idle-with-a-reason when any of these holds, and none is an attention item:

```text
awaits a live/restorable delegated-subtask child's result   → waiting on child
holds an unresolved human Question it asked                  → waiting on human
holds an unresolved Question targeted at a live/restorable
  agent, or owns a Plan end-to-end whose only incomplete
  Steps are owned by other live/restorable agents           → waiting on agent
owns ≥1 blocked Step and no active Step                      → awaiting external
called sb done                                               → completed
```

`pending` Steps (not yet eligible) are not work the agent can act on, so they do not defeat `awaiting external`. Only an `active` Step counts as actionable owned work. A `Merge` Step is `blocked` (not `active`) only while it awaits the human authorization to merge — the one precondition no agent can act on — so its owner is `awaiting external`, never `stalled`, and the `Needs Human Review` item already represents that wait. The other two merge preconditions are different in kind: a red CI or an unresolved `major` Finding is work an agent can act on, so `Merge` stays `active`, its owner is not excused from stall derivation, and Switchboard wakes it to act rather than paging the human (Section 4). A worker fixing red CI reopens `Implement` for a code fix, or its push simply resets things; either way it is working, not waiting.

`waiting on child` is **structural but scoped**: it holds only for a child spawned as a delegated subtask of the agent's own current assignment and from which it has not yet received a report — not merely for having *any* live child, which would let one `sb spawn` of an unrelated long-running helper buy the parent indefinite stall immunity. It is also bounded, to stop a chain of parked agents mutually explaining itself all the way up: `waiting on child` breaks — the parent becomes `stalled` — only when the parent is idle past `stall_threshold` **and** the awaited child is itself `stalled` or itself `waiting on child`. A child that is idle for a *surfaced* reason (it is `waiting on human`, or `awaiting external`) does not break the parent's wait, because that reason is already in the queue; only an unproductive, unexplained-or-chained child does.

`waiting on agent` is bounded the same way — it breaks if every agent it awaits is itself `stalled` or waiting, so a ring of agents cannot mutually explain each other — and it has the same escape as a dead asker: if a Question's *target* becomes not restorable, the Question is auto-`withdrawn` (Section 7), and an end-to-end owner whose driving agents all become not restorable falls through to the stopped-owner and stalled derivations rather than waiting on the dead forever. This is the state `sb tell`-style waits and end-to-end coordination sit in, and the one §14's "time waiting on another agent" metric measures.

If none of those explains it and the agent has done nothing for longer than `stall_threshold` (a repo-configurable default, Section 11), it is `stalled` — the single derived state for unexplained inactivity. An agent that has never been given an assignment (the blank agent of a no-prompt Task, Section 2) is exempt: with nothing assigned, its idleness is expected, not a stall, and its Task reaches `Ready to Close` per the single predicate in Section 4 — once that agent has taken at least one turn and called `sb done`. "Activity" that resets the clock is a turn end, any `sb` command, or any runtime tool call Herdr exposes; a session that died and one thinking for a few minutes are told apart by the threshold. There is one agent-level stalled state, not a graded "suspicious / potentially / confirmed" ladder. `stall_threshold` does not run against an agent whose Task is `Ready to Close`: its inactivity is fully explained by there being no work left.

**A stopped owner does not hide an incomplete Step.** An owned incomplete Step that is not `blocked` (an `active` or `failed` Step) is normally covered by its owner being at work; the backstop covers the case where the owner has *stopped* (`completed`, `stalled`, or not restorable) while the Step is still open. It is evaluated on the derivation tick, not only at a transition, so an owner that goes `stalled` while already holding an `active` Step is caught like one that stopped earlier. Switchboard first wakes the owner — delivering a message that reactivates a `completed`-but-live owner, held for a not-live one until restore — which keeps an ordinary Step-to-Step handoff inside the agent tree rather than poisoning `Needs You`. If the owner is not restorable, or the wake has not been acted on within `attention_timeout`, the Step surfaces as a `Needs You` item (Section 13). (A `blocked` Step is excluded from this backstop because its owner is by definition reactivatable and the PR item already represents the wait; it also can never be released, so it never becomes unowned.)

At Task level, a Task with unfinished work is `Stalled` — an attention item — whenever no agent is actively advancing that work: any agent is `stalled`, or every agent is idle with no idle-with-a-reason explanation, or (the empty case) no agent is `live` **and none is restorable**. The restorable qualifier matters: right after a machine restart every agent is `not live, restorable`, and this must not flood `Needs You` — the same reason agent-level stall is suppressed for a restorable agent (Section 9). A Task whose agents are all merely awaiting restore is not `Stalled`. All known work complete while the Task remains open is `Ready to Close` and is not an attention item. The goal is not to enforce a rigid ownership graph but to prevent work disappearing because every agent involved happened to stop.

### Cleanup

> Clean agents up whenever doing so is clearly safe and useful, but do not aggressively close important sessions just to keep the tree visually small.

The browser makes large numbers of agents manageable, so automatic cleanup matters less than it did.

* An agent is **never automatically** cleaned up while it owns an incomplete Step or holds an unresolved Question it asked. Closing a Task (Section 4) is an explicit human action that overrides this: its agents are cleaned up and their unresolved Questions withdrawn.
* An agent that **completed a judgment Step on a Plan that is not yet complete** is also not auto-cleanable until that Plan completes. This is a structural guard, not a judgment call: it keeps a Lead Reviewer available for the requested-changes loop (which can `reopen` its `Review`) rather than relying on "context-bearing" being assessed correctly by the owner that benefits from a small tree.
* Short-lived helpers whose contribution is fully consumed — reviewers after findings are consolidated and fixed — are cleaned up.
* Context-bearing agents, such as a researcher that handed off to a worker, stay available.

The existing cleanup rules are not carried over blindly: they were written against the dispatcher/lead tree, where parentage determined ownership, placement and eligibility. They are audited during migration and the behaviors worth keeping are rewritten in this vocabulary. The replacement must not be a complex new lifecycle system.

---

## 7. Communication, Questions, and attention

### Messaging

`sb tell` is the point-to-point primitive. Switchboard is the authoritative communication and logging layer; Herdr is the runtime delivery mechanism.

Two delivery modes:

```text
NORMAL     queued and delivered at the target's next turn boundary, without interrupting
           its current turn
INTERRUPT  stop the current turn and deliver immediately, for genuinely urgent course
           corrections
```

`NORMAL` replaces both old delivery modes. The old `next turn` mode is exactly `NORMAL`. The old `when idle` mode (hold until the target finishes) is dropped deliberately: a message delivered at the next turn boundary costs the receiver nothing until it chooses to act on it, so there is no need for a separate hold-until-idle mode — the receiver decides when a queued message is worth acting on. "Turn boundary" means the target's next turn, not the end of its current Step or assignment.

Both modes reactivate a `done`-but-live target: delivery makes it active again. If its runtime session is gone, the message is held and delivered when the session is restored, never dropped.

Messaging stays point-to-point. There is no shared Task chat or channel by default, and normal behaviour favours direct relationships — parent↔child, delegator↔delegate, reviewer→worker — but nothing hard-prevents messaging another relevant agent in the same Task.

> `sb tell` should be uncommon. Prefer completing a bounded unit of work and sending one concise result over continuously reporting progress.

**`--no-reply`.** A sender that does not need an answer says so: `sb tell <agent> --no-reply "<message>"` appends a short line to the delivered message telling the receiver that no reply is expected and that it should not reply unless something is actually wrong or blocking.

It is **prompt text, not a gate**. Switchboard does not refuse, drop or warn on a reply to a `--no-reply` message; a receiver that has something the sender genuinely needs still sends it. Enforcing it would turn a courtesy into a trap — the one case worth hearing about is exactly the case a gate would silence.

It is also orthogonal to delivery mode: `NORMAL` and `INTERRUPT` say *when* a message arrives, `--no-reply` says what response it invites. Both combine freely.

The reason it earns a flag rather than being left to the sender's phrasing is that the default is expensive. An unmarked message reads as an opening, and a courteous acknowledgement costs a turn on both sides plus the context it drags along; across a Task that is most of the message traffic the Plan never needed. Most `tell`s — a status hand-off, a "your Step is unblocked", a heads-up — want no answer, so marking them is the common case, not the exception.

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

`sb ask <target>` creates a durable Question associated with the asking agent and its Task. The target is one of `human`, `advisor`, `parent`, or an explicit `<agent-name>` (a Task's initiating agent has no `parent`, so it targets `human` or a named agent). A `human`-targeted Question surfaces in the browser attention queue; an agent-targeted one is visible in the Task view but does not enter `Needs You`, since no human action is useful on it. Creating one does not by itself mean the agent is blocked.

Human- and agent-targeted asks always create a durable Question; `advisor` asks never do — they are synchronous, answered in the command result. The two shapes are one verb but do not overlap: the target determines which, so an agent knows from its own target whether to expect a Question ID or an inline answer.

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

`answered` is an optional intermediate state, set when Switchboard itself records that a response arrived — the browser path, or an agent answering with `sb ask answer`. When the user answers in the terminal instead, Switchboard cannot see it, so the asking agent moves the Question straight from `pending` to `resolved` in its own turn — `pending → resolved` is a valid transition, and is the normal terminal path, not an edge case. An agent-targeted Question is answered by the target with `sb ask answer <qid>`, which sets `answered`; a bare `sb tell` does not resolve a Question.

A Question stays associated with the Task, and visible in the Task view, until the requesting agent resolves or withdraws it. It leaves the attention queue once answered. An agent holding an unresolved Question is never automatically cleaned up (closing its Task is the exception, and withdraws the Question). The UI does not need to expose every internal state prominently.

Two escapes keep the cross-Task queue from accreting stale items:

* **Human resolve.** The browser lets the human authoritatively answer a Question. The answer's *content* is delivered to the asking agent (reactivating it like any delivered message), not merely flipped to a resolved state — otherwise the agent would lose the answer and, with no pending Question left, fall through to `stalled`. This is not "manual dismissal" of a derived item — it changes the underlying state by supplying the answer — so it is consistent with the `Needs You` no-dismissal rule.
* **Orphaned Question.** A Question whose asker will not come back to process it is auto-cleared after `attention_timeout` (Section 11), with an event recorded, so it cannot permanently block progress. Three cases: an asker that is neither live nor restorable (its Task was closed, or it was cleaned up) has its Question auto-`withdrawn`; an asker that is `completed`-but-live and has left a Question `pending` or `answered` unprocessed past the timeout has it auto-`resolved` (the answer, if any, is preserved in the event log); and an agent-targeted Question whose *target* becomes not restorable — the answer can never arrive — is auto-`withdrawn`, which also releases the asker's `waiting on agent`. Without this, an agent-targeted Question answered after its asker had already gone `done` — a reviewer answering a worker that has finished — would keep the Task out of `Ready to Close` forever, unsurfaced (agent-targeted Questions are not in `Needs You`). This timer is separate from `stall_threshold` so tuning stall detection does not change how long an orphaned Question survives.

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
unanswered human question + agent stopped                                → waiting on human
owns an active (non-blocked) Step, no child awaited, no activity past
  stall_threshold                                                        → stalled
Task has unfinished work + every agent idle + no idle-with-reason        → Task needs attention
```

Targeted mechanical checks remain where they are high-confidence, such as blocking `done` while the agent owns an incomplete non-`blocked` Step (`active` or `failed`) or an end-to-end Plan that still has an `active` or `failed` Step (Section 6).

### How derived state is maintained

Most derivation is a pure function of current authoritative state and recomputes on the event that changed that state. But several transitions are functions of elapsed time (`stall_threshold`, `attention_timeout`) or of remote state that emits no local event (a PR merged, a head force-pushed, a CI conclusion). These are produced by an explicit periodic **derivation tick**: on each tick Switchboard re-evaluates the time- and remote-dependent conditions and updates derived state and the attention queue accordingly. An `sb`-driven event and the tick are the two things that can move derived state; nothing depends on an agent taking a turn to declare a transition.

Remote facts reach Switchboard by webhook where the host provides one and by polling on the tick otherwise; a webhook is an optimization, polling is the correctness floor, exactly as the terminal input hook is treated for Questions. Because polling has latency, any operation whose safety depends on a remote fact **re-fetches it at execution time** rather than trusting a cached value — in particular `Merge` re-reads the live PR head and re-checks the authorization against it (Section 4) before merging, so a push that landed since the last tick cannot slip an unapproved head through.

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

There is no rigid `one Task = one worktree` or `one Plan = one worktree` rule. A Task may contain several worktrees; a Plan may use the Task's worktree or another one. A Plan nonetheless has one **primary branch and worktree**, recorded as system-held state (Section 3) at `sb plan create` or when its first commit is observed. That binding is what the branch-dependent rules read: review independence tests authorship against this branch (Section 4), the completion guard tests whether it carries commits, and `Open PR` asserts the PR head is this branch. Auxiliary worktrees an agent creates inside a Plan are folded back into that primary branch before the PR opens.

**The delegator chooses placement.** When an agent spawns another, it decides whether the new agent works in the same worktree, a new one based on it, or another isolated one. This is part of the spawn decision, not inferred from role or parentage.

Agents working on the same coherent Plan normally share one worktree, especially when the Plan is one PR. Reviewers inspect the exact worktree and change they are reviewing rather than being isolated by default. Agents may still create additional worktrees inside a Plan — an isolated branch later folded back in — and nothing artificially prevents it.

Worktrees are visible in Task and Plan detail, not a prominent global abstraction. The primary user-facing objects remain Tasks, Plans and Agents.

A worktree is removable only when it holds no useful live state, checked explicitly: its branch has no uncommitted or untracked changes, no commits absent from its remote, and no live or restorable agent assigned to it. When **all** of those hold — commonly satisfied once a Plan's PR merges and its agents have ended — the worktree is removed. Otherwise it is retained and surfaced as `Needs You: worktree retained — unpushed work in <path>`, never silently destroyed. Removal on Task close (Section 4) follows the same predicate rather than a blanket "where appropriate". A Task may stay open with other Plans and worktrees after one Plan's worktree is removed.

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

A missing runtime session therefore never deletes a Switchboard agent. Liveness has three values: `live`, `not live, restorable` (the session is gone but can be reconstructed — a machine restart, a killed pane), and `not restorable` (the session is gone for good). A `not live, restorable` agent keeps its identity, assignments and last derived status, waiting to be restored; suppressing stall detection for it is what stops a machine restart flooding `Needs You` with false stalls. A `not restorable` agent is different: its work has genuinely stopped and cannot resume itself, so Switchboard raises an attention item (`Agent <x> is not restorable — <n> Steps/Questions held`) and treats any parent that was `waiting on child` on it as no longer waiting, so the parent's own idleness begins to derive normally rather than the dead child masking it forever. `waiting on child` requires a child that is still `live` or `restorable`.

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

Agent processes rarely crash outright, but the underlying session can hit runtime errors or become unexpectedly idle. Where the runtime exposes a clear error signal, record and surface it. Otherwise the derived-state model catches it as `stalled` once activity ceases past `stall_threshold`. Avoid fragile heuristics that parse arbitrary terminal text unless they prove reliable.

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

Advisor context goes stale when its inputs change. Staleness is computed over a defined watched set — a hash of `.switchboard/**` (roles, presets, models, review and Plan defaults, repo Switchboard conventions) plus the Switchboard version string — so the check is deterministic rather than firing on any unrelated repo commit. The browser exposes **Refresh Advisor**, which produces a new authoritative base session from current configuration; Switchboard indicates staleness when the watched hash changes. Conventions living outside that set do not auto-trigger staleness and are picked up by a manual **Refresh Advisor**. If nothing in the watched set changed there is no reason to rebuild.

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

Named tunables referenced elsewhere in this document resolve through the same two levels, each shipping a Switchboard default and repo-overridable:

* `stall_threshold` — inactivity before an unexplained-idle agent is `stalled` (Sections 6–7).
* `attention_timeout` — the general "long enough to be sure" interval before an un-recovered condition raises an attention item, and the only other timer in the system: a wake delivered to a stopped owner and not acted on (a wake held for a not-live owner counts as not acted on, Section 6), an un-retried `failed` Step, and a Question whose asker will not return (Section 7). It is deliberately separate from `stall_threshold` so tuning stall detection does not change how long these survive.
* the derivation-tick interval and remote-poll interval (Section 7).
* the `Open PR` required-checks command list (Section 4).
* `auto_task.skip_review` — whether Auto mode spawns from the proposal without review (Section 2).

Repo-defined roles, presets and **step kinds** (Section 4) are repo configuration in the same two-level scheme.

Most configuration is editable from the browser: toggles, model/role/preset selections, default review configuration, default Plan behaviour and other structured options. The UI distinguishes Switchboard default, repo override and effective value, and offers an easy reset to default. Raw prompt text may stay easier to edit directly as files.

Repos may define custom roles and presets without changing Switchboard code (Section 5).

Role, model, presets and other starting configuration resolve at spawn. Presets are the exception that may also be invoked later, loading only when needed. Changing repo configuration affects new agents and never silently mutates running sessions; when relevant configuration changes, the Advisor is marked stale.

> Strong defaults, easy repo-specific overrides, minimal configuration context passed to agents.

Validation catches obviously invalid values. Beyond that, configuration stays permissive: do not hard-code restrictions on combinations of roles, presets, models or Task structures.

---

## 12. Agent context and the command surface

The overriding goal is that Switchboard agents feel close to ordinary Claude Code/Codex sessions. They must not carry broad Switchboard documentation unless the current job requires it.

### Context layers

1. **Minimal universal context.** Every agent knows only: that it belongs to a Switchboard Task; its Task identity; its current assignment; that it can delegate and spawn; how to message relevant agents; how to ask the human, its parent, or the Advisor; how to report `done`; how to inspect its own context; how to discover further capabilities. Detailed spawn and worktree options load only when needed.
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
Pending questions: none  Status: working
```

This lets agents recover their state instead of Switchboard continuously reinjecting it into prompts.

### Targeted hints

Switchboard injects guidance only from clear authoritative state transitions:

```text
Agent assigned a Plan Step             → inject Step-owner guidance once
Agent in a working role takes its first turn in a Task that has no Plan
                                       → inject the Plan-creation trigger once (Section 4)
Agent takes ownership of a Review step → inject review-orchestration guidance once
Agent recorded as end-to-end Plan owner (via plan-create default, --own-plan, or handoff)
                                       → inject done-semantics (done only when the Plan lands) once
Agent completes its first judgment Step → inject the completion-report shape once
Agent reaches a reconcile checkpoint (decision resolved, research shifts scope,
  before a handoff, before sb done)     → inject the summary/state reconciliation shape once
Agent becomes Task coordinator     → inject the coordination hint once
Agent attempts sb done while owning an incomplete active or failed Step
                                       → block until it completes, hands off, or releases the Step
Agent receives human approval while responsible for Merge
                                       → expose the relevant landing action
```

This resolves a tension the layered-context model would otherwise create: Sections 3–6 state behavioural norms (done means the assigned scope landed; summaries stay minimal; narrowing scope is surfaced; review is independent), while the minimal universal context deliberately does *not* carry them. The reconciliation is a division of labour, not a hope that agents fetch the right page. **A norm the system can check is enforced or recorded, not merely taught** — the `done` gate and its required report shape, the merge preconditions, the review-independence record, the scope-narrowing event — so an uninformed agent cannot violate it silently. **A norm that must stay prose gets an explicit delivery trigger in the list above**, injected at the transition it governs, so it reaches the agent at the moment it applies rather than only if the agent thinks to look. The hint list is therefore derived from the norms of Sections 3–6, not an independent short list; a norm with neither enforcement nor a delivery trigger does not belong in the spec as an agent duty at all.

**Delivery channel is not a presentation detail — it decides whether a norm fires at all.** Standing instructions and delivered messages are not interchangeable, and the difference is large enough to design around:

* **Standing prompt** — orientation that must be true from turn one: identity, role, what the agent may do. It arrives before any work exists, competes with everything else in the payload, and its structure is lost when fragments are flattened for the provider.
* **Delivered at the governing moment** — a turn-start hint, a command's own output, or a message from another agent. It arrives when the condition it describes is true, on the same channel a human instruction arrives on.

A conditional norm placed in the standing prompt under-fires badly, and the more indirect its payload the worse: a line that asks the agent to notice a condition, judge whether it applies, and then spend a call fetching the real instruction has four independent places to be dropped. The same words delivered at the moment the condition holds are acted on. This is why every hint above is keyed to a transition, and why a norm should not be added to the standing prompt as a substitute for having a trigger for it.

Two rules follow, and both are load-bearing.

**A trigger carries a pointer, not the instruction.** The hint says the condition and where the real instruction lives — one or two sentences and a command to run. It does not inline the procedure. This is what keeps the just-in-time channel cheap enough to use freely, and it is sufficient: a pointer delivered at the governing moment is complied with, where the same pointer in the standing prompt is not. The failure was never that the standing text was too short to act on; it was that it arrived before there was anything to act on, among everything else that arrived then.

**A norm that gains a trigger is removed from the standing prompt, not duplicated.** A rule carried in both places is paid for twice on every spawn, and the two copies drift. Reminder-shaped guidance moves to the trigger; identity and orientation prose stays in the standing prompt, because it has no later moment to wait for and must be true from turn one. That division — *what this agent is for* stays, *what to do when something becomes true* moves — is also the rule for role prompts.

**Triggers are keyed to every role the norm applies to.** A norm delivered to one role and not to the others that need it is the same failure as no trigger at all, and it is harder to see: the roles that were covered comply, so the norm looks like it works. When a trigger is added, the set of roles it fires for is part of the requirement.

No speculative hints such as "seems like it might need review" or "has been coding for a while". Where the moment cannot be identified deterministically, rely on `sb context`, `sb help` and the Advisor.

### Command surface

The primary agent-facing surface is small:

```text
sb spawn   sb tell   sb ask   sb done   sb context   sb plan   sb task   sb restore   sb help
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
  --assign-step Review
```

`--assign-step` names the Step the spawned agent takes (it is about the spawnee, not the caller). Any agent working in a Plan may assign an *unowned* Step; reassigning an already-owned Step requires the current owner to release it first, or an explicit steal (`sb plan take <step> --steal`, or `sb spawn --assign-step <step> --steal`). A steal records an event and notifies the previous owner (Section 4), so the "exactly one accountable owner" invariant holds and recovering a stopped owner's Step, its normal use, is expressible in the CLI. `--preset` is repeatable, and one call carries both the handoff content and any Step/assignment transfer. This may internally create relationships, associate Task/Plan state, configure the runtime session and attach the assignment. The caller must never need a sequence of spawn → set role → set model → attach preset → assign Plan → assign Step → configure worktree → send initial instructions.

`sb plan` and `sb task` expose high-level operations rather than a collection of low-level mutations:

```text
sb plan create | show | take <step> | release <step> | complete --step <step>
              | reopen --step <step> | open-pr | merge | step retry <step>
              | finding raise|resolve | approve | edit
sb task show | edit
sb ask <target> | answer <qid> | resolve | withdraw | escalate
```

| Verb | What it does |
| --- | --- |
| `take <step>` / `release <step>` | takes a Step for the calling agent; release gives up ownership, leaving it `unowned` |
| `complete --step <step>` | records judgment-based completion by that Step's owner; rejected for system-completed Steps |
| `reopen --step <step>` | moves a `complete` judgment Step back to `active` for a requested-changes loop; rejected for system-completed Steps |
| `open-pr` | runs the `Open PR` bundle — checks, PR, summary comment — idempotently, reusing a live PR |
| `merge` | executes the `Merge`, re-fetching the head and re-checking the four preconditions at execution time (Section 4) |
| `step retry <step>` | re-runs whichever bundle is `failed`, idempotently |
| `finding raise\|resolve` | creates and clears the durable review Findings that gate `Merge` |
| `approve` | records a human approval; a relayed `approve` records only a head-bound approval, never a pre-approval (Section 4) |
| `sb ask answer <qid>` | how an agent answers a Question targeted at it |

`open-pr` and `merge` are Switchboard-owned operations — that is what makes them idempotent and re-checkable — so an agent completes those Steps by calling these verbs, never by running `gh` itself. Each verb is accepted only from the owner of the corresponding Step (or an agent that first `take`s it), so the accountable owner the wake and stopped-owner backstop target is also who acts.

**End-to-end Plan ownership** (which the `done` gate holds until the Plan lands, Section 6) is recorded on the agent that runs `sb plan create` by default, with `--no-own` to opt out. It is assigned to a new agent with `sb spawn --own-plan <plan>`, and handed to an already-running agent with `sb tell --handoff --own-plan <plan>` — the same handoff path of Section 6, and one of the two ways the `done` gate is satisfied (land the Plan, or hand ownership off).

**Declaring structure.** A Plan's initial structure comes in one operation (`--title "OAuth migration" --steps "Research,Design,Implement,Review,Open PR,Merge"`). Each step may state its kind as `Display Name:kind` (`"Land it:merge"`); a bare name resolves to the built-in kind of a recognized default step (`Open PR`→`open_pr`, `Merge`→`merge`, `Review`→`review`, `Implement`→`implement`, …) and otherwise to a plain `implement` judgment kind with no special powers. `sb plan edit` carries the kind for any Step it adds, in the same `Name:kind` form, so a Plan can grow a real `open_pr`/`merge` Step later — kind is never inferred from a display name after creation.

Further high-level operations may be added if they represent genuine recurring lifecycle actions. Underlying database operations may remain granular internally; agents interact with the higher-level transaction. Editing semantics — whole documents, agent-writable fields only, serialization handled by Switchboard — are defined in Section 3.

`sb context` is the general-purpose inspection and reorientation command; avoid creating many overlapping top-level inspection commands. `sb plan show` remains for Plan-specific inspection.

Three primitives stay semantically distinct even though they share underlying infrastructure:

| Command | Why it stays separate |
| --- | --- |
| `sb done` | Switchboard must know the agent believes its assigned scope is complete; it is not an ordinary `tell` |
| `sb ask` | Routes structured requests for information; human and agent asks always create durable Questions, while Advisor asks are synchronous |
| `sb tell` | Lightweight point-to-point delivery; takes `--no-reply` (Section 7) and `--handoff`; must not acquire question or lifecycle semantics |

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

This list is illustrative of the item *types*; the authoritative set is the union of every attention item named in Appendix A and its owning sections (a `Needs You` column marked **yes**, or an item a section explicitly raises). The recurring types:

* unanswered human Questions
* PRs ready for review (the Plan's `Needs Human Review` state; see Appendix A)
* a merge authorized by an agent from your message, pending your confirm/flag (survives the merge — Section 4)
* PRs whose checks (CI) failed, or an unresolved `major` review Finding, where the responsible agent has not acted within `attention_timeout`
* stalled agents and Tasks
* agents that are not restorable (their held Steps/Questions cannot resume themselves)
* unowned `active` Steps on incomplete Plans
* `active` or `failed` Steps whose owner has stopped and whose wake did not land or was not acted on within `attention_timeout`
* Steps whose bundled operation failed and was not recovered
* a Plan carrying unmerged commits whose Steps are all complete but which has no `merge`-kind Step, so it cannot reach `complete` as structured (Section 4)
* a worktree retained because it holds unpushed or uncommitted work (Section 8)
* surfaced runtime errors
* other explicit user decisions

Items are derived from current authoritative state and disappear automatically when the condition resolves — question answered, the human authorizes or the PR merges (the separate relayed-approval confirm item clears only on confirm/flag), stalled agent resumes, failed Step retried, worktree reclaimed. No manual dismissal. When one condition would raise two items — a `stalled` agent that also owns an `active`/`failed` Step raises both a stalled-agent item and a stopped-owner Step item — the Step item is shown and subsumes the bare agent item, since it names the actionable work; they are not counted twice. It must not become a general notification feed, and `Ready to Close` Tasks belong in the Tasks view, not here.

**Activity.** A lightweight cross-Task history of meaningful events, useful for visibility and debugging, secondary to the other two, and never interrupting the user.

### Actions

New Task, Auto Task, open/focus an agent terminal, answer a Question, approve a PR (as a head-bound `approval` or a `pre-approval`), confirm or flag a relayed authorization, optionally merge, request changes (reopen), retry a failed Step, assign a Task coordinator, close a Task, restore the environment, refresh the Advisor, edit repo configuration, and spawning an agent as a convenience.

Humans generally do not edit Plans in the browser. Plans are agent-managed execution structures, and human interaction with them is decisions and approvals rather than low-level maintenance. Inspecting Plans should nonetheless be easy.

Browser actions and CLI/agent actions operate through the same underlying state and operations. There are no browser-only orchestration semantics: browser `Approve` and telling an agent "looks good, merge" enter through different interfaces but update the same Task/Plan/message state.

> Organize around Tasks and human attention, not a global wall of agents.

The first browser implementation should focus on rendering real Tasks with their live agents and status, navigating into a Task, and jumping to the correct Herdr terminal. The state vocabulary the CLI and browser share is fixed in Appendix A; beyond that fixed set, presentational status vocabulary and precedence, card layouts and queue organization are deliberately left open and should be iterated on once the core framework works.

---

## 14. Logging, history, and analytics

Claude Code and Codex already persist full agent transcripts, so Switchboard does not copy them. Each agent retains enough identifying information to locate its underlying session and transcript when deeper inspection is needed.

```text
Claude Code / Codex → full agent transcript
Switchboard         → structured orchestration history + references to those sessions
```

Switchboard stores normal mutable current state plus an append-only event log. The product is not otherwise event-sourced unless that later becomes clearly useful.

Logged events include: Task creation and close; Plan creation, change and completion; Step assignment, completion, release, reopen and steal; review Findings raised and resolved; merge authorizations granted, confirmed, invalidated and revoked; scope narrowings; agent spawn, done and cleanup; parent/child relationships; handoffs; `tell` (including whether it was `--no-reply`), `ask` and `done` messages; question answers, escalations and withdrawals; review activity; worktree creation and cleanup; PR creation and merge; role/model/preset used; important status transitions; timestamps and durations.

Full Switchboard message text is retained. Storage efficiency is not an important constraint.

Task, Plan, Step and Agent history are different filtered views of this one event history, never independently maintained logs.

No large fixed analytics system initially. Store enough raw structured information that useful metrics can be derived later: time waiting on human, time waiting on another agent, agent and message counts, review loops and turnaround time, model/role/preset usage, Plan and Task duration, failure and retry patterns.

Keep structured history locally and retain it indefinitely for now. Export, dashboards, aggregation and retention policies can be added later if they become useful.

> Record rich operational data now; decide what to analyze later.

---

## Appendix A — State reference

This is the single authoritative list of the states this document relies on: their entry and exit triggers, who sets each, and whether it raises a `Needs You` attention item. Where Section 13 leaves "task status vocabulary and precedence, card layouts and queue organization" open to iteration, this is the fixed set it iterates *beyond* — the derivation engine, `sb context`, and the browser must all agree on these.

### Agent

| State | Entry | Exit | Set by | Needs You |
| --- | --- | --- | --- | --- |
| `working` | actively taking turns / running tools | goes idle, or `done` | derived | no |
| `waiting on child` | idle awaiting a report from a `live`/`restorable` delegated-subtask child of this agent's assignment | child reports or becomes not restorable; or parent idle past `stall_threshold` while the child is itself `stalled` or `waiting on child` → parent `stalled` (§6) | derived | no |
| `waiting on human` | holds an unresolved human Question it asked | Question answered/resolved/withdrawn | derived | no |
| `waiting on agent` | idle holding an unresolved Question targeted at a `live`/`restorable` agent, or owning a Plan end-to-end whose only incomplete Steps are owned by other `live`/`restorable` agents | the Question resolves/withdraws, or those Steps complete/hand off; every awaited agent itself `stalled`/waiting or not restorable → `stalled` (§6) | derived | no |
| `awaiting external` | idle owning ≥1 `blocked` Step and no `active` Step | the awaited event fires | derived | no (the PR item covers it) |
| `completed` | called `sb done` | reactivated by a delivered message | derived | no |
| `stalled` | none of the above and no activity for `stall_threshold`; runtime session live; Task not `Ready to Close` | any activity, or cleanup | derived | **yes** |

The explained-idle rows are derived from what the agent owns and awaits (a standing obligation), not from having observed the moment it stopped, so they hold whether or not a turn-end signal arrived (Section 7). Only one applies at a time; rows are evaluated top-to-bottom, so an explained idle always beats `stalled`. `pending` Steps are not actionable owned work and do not defeat `awaiting external`. The displayed row is separate from whether the agent has *finished*: where another rule refers to an agent being `completed` (the orphan-Question rule in Section 7, coordinator eligibility in Section 1), it means the agent has called `sb done`, whatever explained-idle row it currently displays — an agent that `sb done`d and is now shown `waiting on agent` because a Question it left open is still `completed` for those rules.

**Liveness is orthogonal** to derived status, not a row in this table: Switchboard owns status, the runtime owns whether the session is `live` / `not live, restorable` / `not restorable` (Section 9). A `not live, restorable` agent keeps its last derived status rather than decaying — `stall_threshold` does not run against it — so a machine restart does not flood `Needs You` with false stalls. A `not restorable` agent instead raises an attention item and releases any parent that was `waiting on child` on it. Separately, an `active` Step whose owner is `completed`, `stalled`, or not restorable is surfaced directly (Section 6, "a stopped owner does not hide an incomplete Step"; §13 queue), so a stopped owner cannot mask incomplete work.

### Question

| State | Entry | Exit | Set by | Needs You |
| --- | --- | --- | --- | --- |
| `pending` | `sb ask <human/agent>` | answered, resolved, or withdrawn | asking agent | yes (human target) |
| `answered` | Switchboard recorded a response (browser path, or `sb ask answer`) | asker resolves | Switchboard | no |
| `resolved` | asker processed the answer (incl. direct `pending → resolved` on the terminal path) | terminal | asking agent, human resolve, or Switchboard (orphan auto-resolve) | no |
| `withdrawn` | answer no longer needed, or orphaned Question auto-cleared after `attention_timeout` | terminal | asking agent, or Switchboard | no |

`advisor` asks create no Question (synchronous). An orphaned Question — asker not restorable, or `completed`-but-live and unprocessed past the timeout — is auto-`withdrawn` or auto-`resolved` respectively (Section 7).

### Step

| State | Entry | Exit | Set by | Needs You |
| --- | --- | --- | --- | --- |
| `pending` | created with preceding Steps incomplete, or suspended by a `reopen` of an earlier Step | predecessors complete → `active` (or `blocked`); a `merge`-kind Step whose PR is observed merged → `complete` from any state | derived | no |
| `active` | eligible (all preceding Steps complete), incomplete, not blocked or failed | completed; or an earlier Step is `reopen`ed → back to `pending` | derived | **yes** if `unowned`; or if its owner has stopped and is not restorable, or the wake was delivered but not acted on within `attention_timeout` |
| `blocked` | eligible, awaiting the human authorization to merge — the one merge precondition no agent can act on | authorization lands → `active` (owner merges); merge observed → `complete`; earlier Step reopened → `pending` | derived | no |
| `failed` | a bundled sub-operation or local check failed; or a system Step whose remote fact was later observed false (PR closed) | `step retry` succeeds → `complete`; retry fails → stays `failed` | Switchboard | **yes** if its owner has stopped and is not restorable, or the wake was delivered but not acted on within `attention_timeout`; else if unrecovered past `attention_timeout`; a `failed` owned Step also blocks the owner's `sb done` |
| `complete` | system fact established, or owner declared it | terminal, except: a judgment Step may be `reopen`ed → `active`; a later `reopen` suspends it → `pending`; a system Step whose fact is observed false → `failed` | Switchboard (system Steps) / owner (judgment Steps) | no |

A Step also carries an immutable **kind** (`implement`, `review`, `open_pr`, `merge`, …), set at creation, which — not the display name — decides system-vs-judgment completion and which Step the review-independence record applies to; a Plan with commits cannot reach `complete` without a completed `merge`-kind Step (Section 4). A review produces durable **Findings** (`major`/`minor`/`nit`); an unresolved `major` blocks both `Review` completion and `Merge` (Section 4).

Ownership is orthogonal to state: an `active` Step is owned or explicitly `unowned` (attention item); a not-yet-eligible Step may carry a pre-staged owner. Steps are keyed by a stable ID, not their display name, and Switchboard rejects a structural edit that reorders/deletes a `complete` system Step or moves an incomplete Step ahead of a `complete` one (Section 4). `reopen` (requested-changes loop) applies only to judgment-completed Steps and **suspends every later Step to `pending`** until the reopened Step re-completes; system Steps keep their established facts while suspended, and `Merge` never executes while any earlier Step is incomplete. Remote CI is a Plan-level fact, not a Step (Section 4).

### Plan

| State | Entry | Exit | Set by | Needs You |
| --- | --- | --- | --- | --- |
| in progress | created (always ≥1 Step) | → `Needs Human Review` when `Open PR` completes with no live authorization; → `awaiting merge` when `Open PR` is complete and an authorization is live; → `complete` (no-PR Plan, all Steps complete) | derived | no |
| `Needs Human Review` | `Open PR` complete, `Merge` incomplete, no live merge authorization | authorization recorded → `awaiting merge`; PR merged → `complete`; earlier Step reopened, or `Open PR` fact observed false (PR closed) → back to `in progress` | derived | **yes** |
| `awaiting merge` | `Open PR` complete, a live authorization, `Merge` incomplete | `Merge` complete → `complete`; authorization invalidated (push/revoke) → `Needs Human Review`; earlier Step reopened → `in progress` | derived | no (the owner drives it) |
| `complete` | `Merge` complete, or a no-PR Plan with ≥1 Step all complete; a Plan with commits requires a completed `merge`-kind Step | terminal (a post-merge concern is a new Plan, not a reopen — Section 4) | Switchboard | no |

Alongside its state, an open-PR Plan carries `ci: pending | green | red` (set by the derivation tick, Section 4) — a tracked fact rather than a Plan state: it gates the `merge` operation, and a `red` wakes the owner to fix it — raising a `Needs You` item only if the owner does not act (Section 4) — but it does not by itself move the Plan between the rows above. The three middle states span the whole PR-open-to-merged interval, so a Plan is never without a state. `Needs Human Review` is what the `Needs You` queue heads as "PRs ready for review". A browser approval moves the Plan to `awaiting merge` outright; an agent-relayed approval also moves it there but raises a separate `confirm or flag` item that survives the merge (Section 4), so it does not silently clear. A Plan is never `complete` with zero Steps — the vacuous case is `in progress` (Section 4).

### Task

A Task has **two independent things**, not one state machine: a human-owned lifecycle, and a derived condition that only exists while it is `open`. A Task is routinely both `open` and `stalled`. An implementation that collapses these into one mutually exclusive field is wrong.

**Lifecycle** — set by the human, never derived:

| Lifecycle | Entry | Exit |
| --- | --- | --- |
| `open` | created (human action) | closed (human action) |
| `closed` | human closes it | terminal |

**Derived condition**, evaluated only while `open`:

| Condition | Holds when | Set by | Needs You |
| --- | --- | --- | --- |
| `working` | work remains and at least one agent is advancing it | derived | no |
| `stalled` | unfinished work and no agent advancing it: a `stalled` agent, or every agent idle with no explanation, or no agent `live` and none `restorable` | derived | **yes** |
| `ready_to_close` | the single Section 4 predicate: work has happened (a completed Plan, or a Plan-less Task's initiating agent has `sb done`), every Plan complete, no open Step/Question, no agent working | derived | no |

These are the canonical names; the prose elsewhere in this document writes them `working`, `Stalled` and `Ready to Close`. Exactly one condition holds at a time. `ready_to_close` never coexists with `stalled` — the latter requires unfinished work, the former requires none. A Task's condition is independent of its Plans' states: `stalled` and a Plan's `Needs Human Review` can hold together (a stalled agent on a Task that also has a PR out), and both surface as distinct `Needs You` items.
