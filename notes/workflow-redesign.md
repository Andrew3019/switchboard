# Switchboard Workflow Redesign

## Why this review is happening

The current Switchboard workflows are going badly. This is one connected system problem,
not a collection of small independent defects.

### Plan workflow

For work that needs shaping, the intended workflow is roughly:

1. Investigate the problem and understand its context.
2. Propose a solution and compare it with credible alternatives.
3. Reason about scope, cleanliness, completeness, targeting, and overreach.
4. Design the solution and, when useful, have a fresh agent challenge the design.
5. Create the execution plan, then obtain human approval for both the plan and change contract.
6. Implement the complete change.
7. After implementation, run the appropriate tests, builds, and agent-driven walkthroughs.
8. Obtain independent agent review: omit nits, let the reviewer fix safe minor issues, and
   return defensible major issues to the main agent.
9. Open the pull request and post a clear human-first comment.
10. Ask the human only for manual verification the agents could not perform.
11. Merge after human approval.

Clear, bounded work instead uses a direct path: one agent carries it end to end without a
placeholder plan or separate change-approval ceremony. If that work reveals meaningful
uncertainty, it moves to the shaped path before implementation continues.

The current workflow does not reliably preserve these paths or their ordering. Change
approval appears too late, even though it must happen before implementation. The PR comment
prioritizes the plan record over the human's next actions. The first thing a human sees should be exactly what
they need to test or decide; observability and execution history come afterwards.

Shaped work starts with a lightweight placeholder that prevents divergence during
investigation, solution design, design review, and formal plan writing. The planner expands
that same plan in place. Completed shaping work stays in the record, while human-facing
rendering may summarize it.

### Roles, delegation, and execution

The dispatcher is too brittle. For example, a request for a `gpt5.6sol` worker was passed
directly as a model argument even though the command uses a different canonical model name.
Operational requests like this need reliable resolution rather than literal forwarding that
fails.

The lead role is based on an obsolete design. It currently behaves like a second dispatcher
whose main purpose is delegating work. A lead should instead own and perform its task end to
end, delegating only when independence, specialization, genuine parallelism, extensive
research, planning, review, or change size makes another agent valuable.

Delegation briefs are too prescriptive and fragmented. They often divide straightforward
work into tiny steps and remove the receiving agent's judgment. Briefs should state a broad
but firm scope, objectives, constraints, acceptance criteria, and ownership boundaries. The
receiving agent should gather context, reason about the work, and choose the detailed
approach without overstepping or under-delivering.

Implementation and verification are also inefficient. A small set of related edits should
normally be completed as one coherent change, followed by proportionate verification. Agents
should not edit one file, run a large test suite, edit the next file, and repeat. Full suites
should be reserved for the end and only used when the scope or risk justifies them.

### Prompt system and framework

Every prompt an agent can receive needs review. This includes each prompt by itself and the
effective combined prompt after protocol text, role instructions, plugin fragments, presets,
guidance, overrides, and briefs are assembled.

The current layers contain inefficiencies, duplication, and contradictions. In particular,
the plans plugin, the intended workflow recorded in prior issues, and the original
Switchboard role prompts do not describe one cohesive system. Prompt changes alone may not
be enough: behavior that must always hold may belong in runtime structure or validation
rather than prose.

The goal is one coherent operating model in which roles, prompts, plans, lifecycle state,
testing policy, review, human interaction, and runtime enforcement reinforce the same
workflow.

## Design sections

1. **Workflow lifecycle and placeholder plan**
  - Investigation, design, formal planning, approval boundaries, and plan evolution.
2. **Roles and ownership**
  - Dispatcher, lead, worker, planner, researcher, reviewer, and QA responsibilities.
3. **Agent coordination and lifecycle**
  - Communication, handoffs, waiting, blocking, completion, notifications, and cleanup.
4. **Delegation and briefs**
  - When delegation helps and how to write broad but correctly scoped assignments.
5. **Implementation and verification**
  - Coding sequence, test timing, builds, walkthroughs, proportionality, and evidence reuse.
6. **Agent review**
  - Review timing, independence, substantive findings, fixes, and targeted re-verification.
7. **PR, human review, and merge**
  - Human-first PR output, uncovered manual checks, approval, reviewed commits, and landing.
8. **Complete prompt-system audit**
  - Every prompt surface individually and every effective composed prompt by role and state.
9. **Prompt rules versus runtime enforcement**
  - Which behavior belongs in prose, code, validation, aliases, state transitions, or gates.
10. **Validation, dogfooding, and rollout**
  - Focused mechanism checks, ordinary real-work observation, and migration sequencing.
11. **Final synthesis and implementation plan**
  - Reconcile all decisions, resolve remaining conflicts, and design the coordinated repair.



## 1. Workflow lifecycle and placeholder plan

### Adaptive lifecycle

#### Core decision: one evolving plan, only when useful

The placeholder and formal execution plan are one evolving plan. The placeholder is expanded,
not replaced. Completed shaping work remains in its history; rendering may summarize it, but
the record is not deleted or rewritten.

This plan is not mandatory for every change. It is a tool for work that benefits from
investigation, design, tradeoff analysis, coordination, or risk management. A clear, bounded
change that one agent can safely carry end to end should not pay for a placeholder, planner,
or separate design ceremony.

The workflow adapts to the job instead of forcing every job through the maximum process.

#### Entry paths

##### Direct change

Use when the desired behavior, scope, and reasonable implementation direction are already
clear.

- One agent owns the work end to end.
- No placeholder or planner is required.
- The human's directed request is the controlling scope.
- If investigation reveals a real design choice, widening scope, or unexpected risk, the
  agent moves into the shaped-change path before continuing.

Examples include a trivial fix, a directed prompt correction, or a bounded change in a
well-understood area.

##### Shaped change

Use when the work needs investigation, solution design, meaningful tradeoff analysis, or
coordination before implementation can be responsibly authorized.

- The first task-owning agent creates the lightweight placeholder.
- It selects only the shaping steps this job needs.
- A planner expands that same plan when the solution is ready.
- The solution, formal plan, and change contract receive one combined human approval.
- A main agent then owns execution end to end.

Examples include an unclear bug, a cross-cutting change, a migration, or a new feature with
technology and architecture choices.

##### Research or discussion first

Use when the immediate objective is understanding, advice, or a decision rather than a code
change.

- No plan is required merely to investigate or talk one on one.
- The agent may research, compare technologies, explain tradeoffs, and iterate with the human.
- If the conversation later produces a clear direct change, use the direct path.
- If it produces a change that still needs shaping, create the placeholder at that point.
- Existing findings become inputs to the plan; they are not retroactively invented as plan
  steps that supposedly ran earlier.

Examples include open-ended research, architecture discussion, technology selection, and a
debugging conversation that may or may not result in code.

#### The placeholder is adaptive

The placeholder prevents drift by recording the current objective, known constraints, open
questions, and the route to an approved execution plan. It is not a universal checklist.

Possible shaping steps include:

- Establish context or reproduce a problem.
- Identify the root cause.
- Clarify desired behavior with the human.
- Compare technologies or solution approaches.
- Write a feature specification or solution design.
- Review the design with a fresh agent when formal review is warranted.
- Expand the formal execution plan.
- Obtain combined human approval.

The task owner chooses the smallest useful subset. Steps may be collapsed, skipped, added,
or revisited as evidence changes. Extra process needs justification; omitting irrelevant
process does not.

The placeholder must not guess files, implementation steps, tests, agents, or solutions that
are not yet knowable.

#### How different work enters the system

| Work shape | Starting path | Likely progression |
| --- | --- | --- |
| Trivial or fully directed fix | Direct change | One agent implements and verifies it, then obtains one proportionate fresh-agent review before landing. |
| Clear multi-file change | Direct change | One agent keeps the coherent change together unless risk emerges. |
| Bug with unknown cause | Shaped change | Investigate, determine cause, design the fix, plan, approve, execute. |
| Open-ended research | Research or discussion | Report findings; create a change path only if the human chooses one. |
| One-on-one design discussion | Research or discussion | Iterate freely, then choose direct or shaped change when ready. |
| New feature with technology choices | Shaped change | Compare options, write feature design, review, plan, approve, execute. |
| Feature whose design is settled | Direct or shortened shaped change | Skip discovery; plan only if coordination or risk needs it. |

#### Shaped-change handoff

The handoff model is:

1. The first task-owning agent creates and carries the placeholder through shaping.
2. Its last shaping step hands the accumulated context to a planner.
3. The planner expands the same plan into the formal execution plan.
4. The human approves the solution, plan, and change contract in one response.
5. The first agent chooses the main agent: continue itself when continuity is valuable and
   the work fits, or spawn a fresh worker or lead when context, specialization, independence,
   or execution size justifies the handoff.
6. A newly spawned main receives the formal plan plus a cleaned, decision-complete context
   handoff.
7. The main agent owns implementation, verification, fixes, review coordination, PR creation,
   human review, and landing.

`Main agent` is intentionally used instead of `worker` or `lead`. The distinction between
those roles, and whether the first agent may itself become the main agent, belongs in the
roles section.

The planner is a bounded specialist, not automatically a long-lived load-bearing parent.
The task-owning lead remains accountable while the planner owns formal plan construction;
planner failure and later replanning follow the coordination rules.

#### Approval semantics

The shaped path has one combined approval interaction covering:

- The problem, root cause, or feature specification.
- The selected solution and important tradeoffs.
- The formal execution plan.
- The change contract: intended behavior, scope, exclusions, and success conditions.

No tracked implementation begins on the shaped path before this approval. Rejection returns
to the earliest affected shaping work rather than merely rewording the approval message.

The direct path does not manufacture a second planning ceremony. The human's directed request
authorizes that bounded work. If the agent discovers that the request does not settle the
important design choices, it changes paths and asks for approval before proceeding.

#### Shared milestones, not one mandatory sequence

The lifecycle is organized around milestones that apply when relevant:

- The problem or requested outcome is understood well enough for the chosen path.
- Important design choices are resolved.
- Shaped work is approved before implementation.
- A coherent implementation is complete before normal verification begins.
- Material review findings are resolved before the PR opens.
- The PR tells the human what remains for them to do.
- The reviewed change lands only after human approval.

How the job reaches a milestone may vary. A phase may collapse into another, repeat after new
evidence, or be absent when it adds no value.

#### PR continuity

The final human-facing record must preserve why the work exists, not only how it ran. Root
cause or feature specification and the selected solution remain prominent alongside the
human's required manual checks. Exact PR layout and compression of completed shaping steps
belong in the PR section.

## 2. Roles and ownership

### Roles define authority, not compulsory behavior

A role should say what an agent owns, what it may do, and where its responsibility ends. It
should not force the agent to exercise every capability it has. In particular, permission to
delegate is not an instruction to delegate.

The system needs one accountable task owner, supported by specialists when they add value.
Agent boundaries should follow context, independence, specialization, or genuine parallelism;
they should not mirror every plan step or file.

### Dispatcher

The dispatcher is an operational router, not a technical task owner.

- Preserve the human's intent and route it without designing the solution.
- Choose a worker for clearly bounded one-agent work.
- Choose a lead when shaping, delegation, or coordination may be needed.
- Keep follow-up work with the agent that already holds its context.
- Resolve operational vocabulary such as supported roles, models, and command arguments
  through authoritative system information rather than guessing or forwarding invalid text.
- Ask the human only when routing would require choosing between materially different jobs.
- Do not investigate, implement, review, or manage a plan.

The dispatcher must be reliable enough for operational translation. Whether that comes from
a stronger model, better commands and aliases, or both belongs in the enforcement section.

### Lead

The lead is a task owner with orchestration authority.

- Own the assigned job end to end.
- Investigate, reason, design, edit, test, self-review, and integrate directly when
  appropriate.
- Delegate only when another context produces a concrete benefit.
- Keep work that benefits from continuous context in one agent.
- Coordinate specialists and synthesize their evidence into decisions.
- Remain accountable for delegated work and for the final outcome.

The lead is not a second dispatcher. Its defining difference from a worker is the authority
to create and coordinate other agents, not an obligation to avoid doing work itself.

### Worker

The worker is a task owner without standing orchestration responsibility.

- Carry a bounded assignment end to end.
- Gather its own context and choose implementation details within scope.
- Make coherent multi-file changes when the task requires them.
- Verify, self-review, and report the completed outcome.
- Return work that truly needs decomposition or new authority rather than silently narrowing
  it.

A worker is not a mechanical executor. It receives a scoped objective, not a sequence of
keystrokes. A worker may be the main agent for an entire job.

### Main agent

`Main agent` is a responsibility within a job, not necessarily a distinct role.

- Own implementation through landing under the approved scope.
- Preserve context across coding, verification, review fixes, PR creation, and human review.
- Be a worker when execution fits one agent.
- Be a lead when execution itself may need specialists or parallel work.
- Avoid replacement between ordinary phases; continuity is the default.

For shaped work, the original lead may become the main agent or appoint a fresh one. Continue
with the original lead by default: it already understands the problem, decisions, and risks,
and another handoff should have to earn its cost. Use a fresh main when shaping consumed
substantial context, execution needs different capabilities, or separation materially
improves focus.

### Planner

The planner is a first-class specialist role. It owns formal plan construction, not the
overall job.

- Receive the shaped problem, decisions, constraints, and evidence.
- Turn them into a proportional execution plan.
- Challenge missing dependencies, unclear scope, unjustified delegation, and weak verification.
- Challenge infeasible assumptions, internal contradictions, and design choices that cannot
  support the stated objectives.
- Avoid casually reopening settled product or technical decisions; raise them only when
  evidence shows the plan cannot responsibly execute them.
- Return the completed plan to the task-owning lead.
- Take no implementation ownership merely because it wrote the plan.

### Researcher

The researcher owns an evidence question.

- Investigate a bounded uncertainty and report evidence, implications, and confidence.
- Preserve distinctions between facts, inference, and recommendation.
- Avoid turning research into an unauthorized design or implementation task.
- Return findings in a form the task owner can use without repeating the investigation.

Research may support a lead, planner, reviewer, or direct human discussion.

### Reviewer

The reviewer owns an independent judgment.

- Review a design, plan, or implementation against its stated objectives and relevant risks.
- Focus on substantive correctness, omissions, scope, and maintainability.
- Classify findings as major, minor, or nit.
- Omit nits: they do not justify work or human attention.
- Apply minor fixes directly when they are local, unambiguous, inside the approved contract,
  and safely verifiable without a design choice.
- Receive scoped write authority for those minor fixes; the reviewed scope and intended
  direction bound that authority.
- Surface major findings to the main agent with their impact and required outcome.
- Preserve independence on the reviewed design and implementation; fixing a small discovered
  defect does not make the reviewer the author of the overall change.

A reviewer records every applied fix and its targeted verification in the report back. The
main agent remains responsible for the resulting diff. Anything that changes behavior, scope,
architecture, or risk is major even if the edit itself is small.

Every formal review uses a fresh agent. The task owner decides the review breadth in the
brief: one general review for ordinary work, or several independent reviewers with distinct
facets for larger or higher-risk work. A self-check by the author is useful preparation but
does not count as independent review.

### QA

QA owns independent verification evidence.

- Verify behavior that benefits from a separate environment, perspective, or specialty.
- Focus on exploratory flows, integration behavior, UI, devices, external systems, and other
  surfaces the main agent cannot adequately establish itself.
- Reuse tests and evidence already tied to the same commit rather than rerunning them.
- Identify what remains unverified and what evidence would settle it.
- Return material defects to the main agent with a focused reproduction.

The main agent owns ordinary tests and builds. QA is not a routine downstream test runner:
that creates a slow implement-test-return loop while separating failures from the agent best
placed to fix them. Separate QA is justified only by meaningful independence, environment,
specialization, or risk.

### Routing before the work is understood

The dispatcher often cannot know the eventual work shape without doing investigation it does
not own. Initial routing therefore uses only what is already evident:

- Send clearly bounded one-agent work to a worker.
- Send explicitly research-only work to a researcher.
- Send everything uncertain, open-ended, potentially shaped, or likely to need helpers to a
  lead.

This is safe because a lead may do the work itself. Choosing a lead does not commit the job
to delegation or a plan; it only ensures the initial owner has enough authority if the scope
changes.

After investigation, that owner chooses the work path:

- Finish as research or discussion when no change is wanted.
- Execute directly when the change is now clear and bounded.
- Enter or continue the shaped-plan path when design, approval, or coordination is valuable.
- Reclassify again if later evidence materially changes the job.

The work shape is a live judgment, not something the dispatcher has to predict perfectly.
Every landing change receives a formal review from a fresh agent. This is the one predictable
agent boundary: the task owner scopes one general review for ordinary work or distinct facets
for larger or higher-risk work. Research or discussion that produces no change needs no
implementation review.

### Temporary delegation from a worker

A correctly routed worker may discover one bounded need for another context: an independent
review, specialized research, environment-specific verification, or a genuinely parallel
subproblem. Returning the entire job merely to obtain that helper is wasteful.

A worker may receive scoped, temporary delegation authority for that need. It remains the
task owner and must give the helper a bounded objective. If the work now requires continuing
coordination, several helpers, or decomposition of the whole job, it should move to a lead
rather than becoming an undeclared lead through repeated grants.

### Ownership rules

- One agent is accountable for the job at any moment.
- Delegating work does not delegate away accountability.
- A specialist owns its bounded output, not the parent job.
- The main agent owns execution decisions inside the approved contract.
- Plan steps are units of progress, not automatic agent boundaries.
- A lead may perform all shaping, implementation, and verification itself without delegating
  execution; the required fresh-agent review remains independent.
- Using the shaped-plan path does not require a fresh execution agent; the lead may remain
  the main agent after planning and approval.
- Ownership transfers must be explicit and carry decisions, evidence, constraints, and open
  risks—not a compressed task sentence alone.
- A role or model label never substitutes for a clear objective and scope.

## 3. Agent coordination and lifecycle

### Coordination model

Keep the parts of the current system that work: parent-child ownership, durable messages,
human blocking, explicit completion, restoration, and preserved work. Strengthen them with
clear waiting states, direct delivery, batched results, and causal identity.

The task owner remains responsible for the job while specialists own bounded contributions.
Coordination should let that owner work, wait, recover, and synthesize without becoming a
passive dispatcher or spending turns moving messages between agents.

### Lifecycle states

| State | Meaning |
| --- | --- |
| Active | The agent has work it can perform now. |
| Waiting | Background work outside Switchboard's child model is still running. |
| Waiting for any | Progress can resume when any current child finishes or fails. |
| Waiting for all | Progress depends on a current cohort reaching terminal states. |
| Blocked | A human decision, approval, or external action is required. |
| Done | The agent's owned assignment is complete and reported. |
| Failed or cancelled | The current assignment cannot or should not continue. |

These are truthful states, not workflow tricks. Waiting is not completion. Blocking is not
ordinary coordination. Done is terminal unless the agent is explicitly restored.

### Waiting

[Issue #190](https://github.com/Andrew3019/switchboard/issues/190) supplies the child-waiting
foundation. The complete shape is:

#### `waiting`

A plain no-argument state for native subagents, background commands, tool calls, or other
asynchronous work with no Switchboard child row.

- Avoids the Stop hook while the agent intentionally has nothing else to do.
- Ends the current turn without reporting done or blocking the human.
- Clears when the underlying result or another instruction resumes the agent.
- Does not pretend Switchboard can schedule or inspect the background operation.

#### `waiting --any`

Wait for the first terminal result from the current child set.

- Snapshot the relevant children when waiting begins.
- Wake once with the first completion, failure, or cancellation.
- Deliver that result with the wakeup.
- Leave the remaining children running unless the parent changes course.

#### `waiting --all`

Wait for a cohort rather than waking once per child.

- Snapshot the relevant children when waiting begins.
- Accumulate results without waking on each arrival.
- Wake once when the entire cohort is done, failed, or cancelled.
- Deliver the complete result set together.
- Allow cancellation or an explicit proceed-with-partial-results escape hatch.
- Do not silently add children spawned after the wait began.

A parent may leave waiting whenever new evidence makes the original condition unnecessary.
No wait should force it to remain stuck behind a dead or irrelevant child.

### Message delivery

The mailbox remains the durable source of truth, but normal delivery should not require a
notification turn followed by an inbox-fetch turn.

- `sb tell` delivers the message body directly.
- An idle recipient begins its next turn with the message.
- A working recipient receives it at the next safe turn boundary.
- `--interrupt` cancels the superseded instruction and delivers immediately.
- `--when-idle` waits until current work finishes.
- `--needs-reply` remains attached to the message as a tracked dependency.
- `sb inbox` remains available for history, recovery, and manual inspection.

Large context still travels by artifact path. Direct delivery improves transport; it does not
turn messages into briefs.

Messages should include the identity needed to remain correct over time:

- Job or plan where applicable.
- Assignment or plan step.
- Attempt or task generation.
- Commit when discussing code, tests, or review evidence.
- Sender and whether a reply is required.

The system may infer and attach this metadata where it already knows it. Agents should not
manually fill a form for every message.

### Child results and cohorts

A child's completion report should arrive with the completion event. The parent should not
receive “a child finished” and spend another turn fetching what it said.

- Normal completion delivers that child's report directly.
- `waiting --any` delivers the first relevant result once.
- `waiting --all` delivers one cohort result after all members terminate.
- Every individual report remains stored even when delivery is batched.
- A partial result may be recorded without waking a parent whose declared condition is not met.
- Failure wakes the parent when it requires a recovery decision.

This preserves simple one-child behavior while making multi-agent review, research, and
parallel work efficient.

### Causality and stale work

Messages and notifications must describe the current attempt, not merely an event that once
happened.

- Deduplicate repeated delivery of the same result.
- Suppress wakeups made obsolete by cancellation, reassignment, a newer attempt, or merge.
- Preserve late results in the record while marking them stale.
- Never let an old completion satisfy a newer assignment.
- Tie verification and review evidence to the commit it evaluated.
- Invalidate evidence because its relevant inputs changed, not merely because another phase
  began.

This prevents stale completion rings and late messages from restarting work that has already
moved on.

### Ownership and human interaction

The task owner is the normal human-facing agent for the job.

- Specialists report evidence and recommendations to the owner.
- The owner synthesizes results and decides the next action.
- Specialists ask the owner for missing decisions instead of independently blocking the human.
- Only one agent waits on the human for a particular decision.
- Active one-on-one conversation stays with the agent holding that context.
- A deep follow-up may be explicitly handed to the specialist that owns the reasoning rather
  than repeatedly relayed through the parent.

`sb block` is for input only the human can provide: material design decisions, change
approval, uncovered manual PR checks, landing approval, or a genuine external blocker. Child
waits, progress updates, and routine coordination do not block the human.

### Completion, failure, and recovery

An agent reports done when its bounded outcome and report are complete. The task owner may
accept the result, request focused follow-up, or restore the agent for rework.

When an agent fails or is cancelled:

- Preserve its assignment, artifacts, messages, edits, and last known commit.
- Wake the task owner with enough context to choose recovery.
- Allow restoration, replacement, reassignment, or absorption by the owner.
- Give a replacement a new attempt identity and the preserved relevant context.
- Do not let the failed attempt silently complete the replacement's work.

Agent failure is usually an orchestration decision, not automatically a human blocker. Tool
failure remains visible and is not silently worked around.

### Cleanup

Cleanup follows ownership and likely follow-up, not visual tidiness alone.

- Close specialists after their results are accepted and no follow-up remains.
- Keep the main agent available through PR review and landing.
- Keep genuinely waiting or blocked agents open in the corresponding state.
- Preserve transcripts, reports, commits, artifacts, and messages after closure.
- Restore the original agent when its retained reasoning is more useful than a fresh context.

Safe cleanup may be automated from lifecycle state, while the task owner retains control when
an expected follow-up makes a live context valuable.

### Coordination invariants

- Every job has one accountable task owner.
- Waiting never masquerades as completion or human blocking.
- Background work may wait without tripping the Stop hook.
- One message normally requires one recipient turn.
- A cohort wait wakes once rather than once per child.
- Direct and batched delivery preserve the durable record.
- Events, reports, and evidence remain tied to the attempt and commit they describe.
- Cancellation makes superseded work terminal.
- Recovery preserves work without confusing old and new attempts.
- Cleanup never destroys the job record.

## 4. Delegation and briefs

### Delegation must earn its cost

The task owner does the work unless another agent provides a concrete advantage. Delegation
adds a context boundary, communication, waiting, review, and integration. It is worthwhile
when those costs buy something the owner cannot get as effectively alone.

Good reasons to delegate include:

- Independent review or verification.
- Specialized knowledge, tools, environment, or model characteristics.
- Research that can proceed independently of the owner's current work.
- Truly parallel work with separable outputs.
- A bounded context reset after a long shaping phase.
- An execution unit large enough to deserve its own accountable owner.

These are not reasons to delegate:

- A plan contains another step.
- The work touches another file.
- Delegation is available.
- The lead wants to avoid implementation.
- A small edit can be described more quickly than it can be performed.
- Several agents could do the same work without distinct perspectives.

One coherent change should normally stay with one agent. A four-file prompt correction is one
task when the same reasoning and verification govern all four files.

### Choose the work boundary before the agent

Delegate an outcome that can be owned and accepted independently. Do not begin with a desired
agent count and divide the work until that count is filled.

A useful delegated unit has:

- One clear objective.
- A scope boundary that prevents overlap or overreach.
- Enough context for the agent to investigate intelligently.
- An acceptance condition the task owner can evaluate.
- A reason that separate ownership improves the job.

Plan steps are units of progress, not automatic delegation boundaries. Several steps may stay
with the main agent, and one delegated investigation may inform several plan steps.

### Briefs are broad but bounded

A brief gives the receiving agent a problem to own. It should preserve judgment while making
the limits unmistakable.

Include what materially changes how the agent should work:

- The desired outcome in one clear statement.
- Why the work matters and which decision or objective it supports.
- Scope, including important exclusions.
- Constraints and product or technical decisions already settled.
- Acceptance criteria or the evidence that will make the result usable.
- Relevant starting context, artifacts, commits, plan, or prior findings.
- Ownership and coordination boundaries, including overlapping work.
- Required role, capabilities, environment, or independence.
- What the agent should return.

Omit material that removes useful reasoning or duplicates another source:

- A file-by-file implementation sequence.
- Exact edits the agent is expected to rediscover.
- One prescribed command after every small change.
- Repeated copies of the plan or design.
- Unrelated repository context.
- A predetermined conclusion disguised as research.
- Mandatory sections whose absence would not change the work.

Implementation detail belongs in the brief only when it is already a settled constraint.
Otherwise, the agent gathers context, compares reasonable approaches, and chooses the local
implementation.

### Proportional detail

Brief depth follows uncertainty and handoff cost.

- A familiar bounded task may need one sentence plus a path.
- A scoped implementation needs objectives, boundaries, decisions, and acceptance criteria.
- A specialist investigation needs the question, evidence boundary, and decision it informs.
- A main-agent handoff after shaping needs the approved design, plan, constraints, and open
  risks without replaying the entire discovery transcript.

More sections do not make a brief safer. A short brief with a precise objective and boundary
is better than a long brief that dictates every move while leaving the actual success
condition implicit.

### Plans, briefs, and source artifacts

Each artifact has one job:

- The plan records outcomes, dependencies, ownership, progress, and gates.
- The design records root cause or feature intent, selected solution, and tradeoffs.
- The brief gives one agent the context and boundaries for its assignment.
- Evidence artifacts hold detailed findings, logs, screenshots, or analysis.

Reference these artifacts instead of copying them into one another. The receiving agent gets
a concise orientation plus paths to the authoritative detail. If an upstream artifact
changes materially, update the reference or decision summary rather than maintaining several
competing copies.

### Main-agent handoff

When a shaped job uses a fresh main agent, the handoff should be decision-complete rather than
transcript-complete.

It includes:

- The human's objective.
- Root cause or feature specification.
- The selected solution and deciding tradeoffs.
- The approved scope, exclusions, and change contract.
- The formal plan and current progress.
- Relevant code and evidence starting points.
- Known risks and unresolved items.
- The main agent's authority and ownership through landing.

Discarded alternatives and exploratory dead ends are omitted unless they prevent the main
agent from repeating a known mistake. The main agent may challenge the handoff when new
evidence exposes a material flaw; it does not reopen settled decisions merely to repeat the
design phase.

### Research briefs

A research assignment names the uncertainty, not the desired answer.

- State the question and why it matters.
- Define which systems, sources, or code are in scope.
- Say what decision the findings will inform.
- Request evidence, inference, confidence, and recommendation as distinct outputs.
- Give a proportional context or pass budget when the search could expand indefinitely.
- Stop when additional research is unlikely to change the decision.

The researcher reports useful conclusions rather than a diary of searches performed.

### Review briefs

Every formal review goes to a fresh agent. The brief supplies:

- The exact artifact or commit under review.
- Objectives and the approved contract.
- Relevant risks and known uncertainty.
- The requested review facet or the instruction to review generally.
- The major, minor, and nit classification rules.
- Scoped write authority for safe minor fixes.
- Verification expected for any applied fix.
- The report format: major findings, minor fixes applied, and remaining uncertainty.

For larger work, use several reviewers only when they receive meaningfully different facets,
such as correctness, concurrency, security, migration safety, or user experience. Duplicate
general reviews are justified only when intentionally seeking independent agreement.

### Parallel delegation

Parallel work is appropriate when agents can make progress without consuming one another's
unfinished output.

- Give parallel agents separable outcomes.
- Assign disjoint write surfaces or isolated worktrees when edits could conflict.
- Name the shared assumptions each branch relies on.
- Define whether the task owner needs any result or the whole cohort.
- Use `waiting --any` or `waiting --all` to match that join condition.
- Reconcile conclusions before downstream implementation when branches disagree.

Parallelism that produces overlapping edits, repeated investigation, or serial dependencies
is concurrency theater and should remain one agent's work.

### Scope changes during delegated work

The receiving agent owns reasonable local decisions inside the brief. It does not need
permission for every implementation detail.

It returns to the task owner when evidence reveals:

- A materially different objective or behavior.
- Scope outside the stated boundary.
- A new risk that changes the approved approach.
- A dependency on another agent's overlapping work.
- Missing authority, environment, or information it cannot obtain safely.

The task owner may widen the brief, split the work, absorb it, or revise the plan and approval.
The agent should not silently narrow the result to the portion it could finish.

### Choosing the agent and capabilities

Select role, model, tools, and capabilities from authoritative system vocabulary. Human
shorthand may need resolution; it should not be forwarded blindly into strict command
arguments.

- Use a native subagent for short, bounded, read-only research, code search, or analysis that
  needs no durable ownership.
- Use a Switchboard agent for tracked edits, formal review, specialized verification,
  long-running work, or anything needing visibility, messaging, restoration, or its own
  accountable lifecycle.
- Use a worker for bounded end-to-end ownership.
- Use a lead when ongoing coordination may be needed.
- Use the planner, researcher, reviewer, or QA role for its independent specialty.
- Give only the authority required by the assignment.
- Grant a worker temporary delegation when one bounded helper becomes useful.
- Move continuing multi-agent coordination to a lead.

The role and capability choice supports the brief. It does not replace the brief.

### Delegation invariants

- Delegation has a stated benefit beyond reducing the parent's work.
- Every delegated assignment has an independently acceptable outcome.
- Briefs constrain scope and success without prescribing unnecessary implementation detail.
- One coherent reasoning context is not split by file or plan step.
- The receiving agent investigates and reasons for itself inside the boundary.
- Formal reviews always use fresh agents.
- Parallel agents have separable work and an explicit join condition.
- Scope expansion returns to the task owner; local implementation judgment does not.
- Plans, briefs, designs, and evidence reference rather than duplicate one another.

## 5. Implementation and verification

### Keep implementation coherent

The main agent implements the approved or directly authorized change as one coherent unit.
It should not alternate between editing one small surface and running the full verification
stack before moving to the next related surface.

During implementation:

- Make all related production, test, fixture, documentation, and prompt changes that belong to
  the same reasoning unit.
- Preserve the approved scope and resolve local implementation details directly.
- Inspect the evolving diff for omissions and accidental scope expansion.
- Keep one main context across the complete change.
- Avoid broad test, build, lint, or packaging runs until the coherent implementation is ready.

A diagnostic command may still run when it answers an active engineering question. That is
part of investigation or implementation feedback, not the start of repeated verification.

### Verification follows the coherent change

Once implementation is complete enough to evaluate as a whole, the main agent begins the
normal verification phase.

1. Review the complete diff against the objective and contract.
2. Run the smallest checks that can distinguish the intended behavior from failure.
3. Build, lint, type-check, or package only the affected surfaces where those checks add
   relevant evidence.
4. Exercise realistic flows the agent can perform itself.
5. Record the remaining uncertainty.
6. Broaden verification only when the affected behavior or risk justifies it.

Verification scope follows behavior and blast radius, not merely the list of edited files.
A small core change may justify broad checks; a large mechanical change may justify only a
focused validator.

### Test execution policy

- Do not run the full suite after each file, step, agent handoff, or commit.
- Do not repeat a passing check for an unchanged commit and environment.
- Run focused checks while distinguishing the changed behavior.
- Run the full suite once on the final candidate commit when cross-cutting risk warrants it.
- Skip the full suite when it cannot meaningfully fail because of the change.
- Explain a skipped broad suite through the verification scope, not as an apology.

Writing or updating tests is part of implementing the change. Executing the verification
stack is normally deferred until the coherent code and test changes are ready. A narrow
failing discriminator may be run earlier when reproducing a bug or settling an uncertain
design; it should not trigger repeated broad suites.

### Main-agent ownership

The main agent owns ordinary verification because it is best placed to understand and fix a
failure.

- It runs the focused tests and affected builds.
- It diagnoses failures and corrects in-scope defects.
- It distinguishes regressions from pre-existing or environmental failures.
- It does not hand routine failures to QA and wait for them to return.
- It does not fix unrelated baseline defects without authorization.

QA is reserved for verification that benefits from another environment, perspective, device,
account, or specialty. Independent QA adds value only when that value outweighs the return
loop it creates.

### Agent-driven manual verification

Agents perform every realistic check available to them before asking the human.

Depending on the change, this may include:

- Running the real CLI or service in an isolated instance.
- Exercising an end-to-end workflow.
- Inspecting generated output or persisted state.
- Using browser or UI tools to walk changed screens.
- Checking upgrade, rollback, compatibility, or failure paths.
- Comparing behavior before and after the change.

The human receives only checks requiring access, perception, hardware, credentials, or
judgment the agents genuinely lack. Human testing is residual verification, not a repeated
version of the agent's checklist.

### Proportional verification examples

| Change shape | Appropriate evidence |
| --- | --- |
| Prompt or documentation wording | Relevant rendering, snapshot, or prompt-composition tests; inspect final output. |
| Local behavior change | Focused unit or module tests plus the affected live path. |
| Shared core primitive | Focused discriminator, affected integration tests, and one justified final suite. |
| UI behavior | Component checks, affected build, agent walkthrough, then only uncovered human checks. |
| Migration or compatibility change | Forward path, compatibility boundary, failure behavior, and rollback where supported. |
| Mechanical refactor | Structural checks and targeted behavior tests; broad suite only if semantics could drift. |

These are examples, not fixed templates. The main agent chooses evidence that can actually
disprove the change's correctness claims.

### Verification after review fixes

Formal review occurs after the initial implementation evidence is ready. When review changes
the code:

- The reviewer verifies any safe minor fix it applies and records that evidence.
- The main agent verifies major fixes it implements.
- Rerun checks whose relevant inputs changed.
- Do not rerun unaffected checks merely because review happened.
- Expand back to broader verification only when the fixes alter the wider risk.
- Do not repeat a justified full-suite run unless review fixes change the risk it covered.

### Reusable evidence

Verification evidence belongs to the commit and environment it evaluated.

Record:

- The commit or exact working state.
- The command or manual flow.
- The behavior covered.
- The environment when relevant.
- The result and meaningful caveats.

Agents receive the evidence summary and artifact paths rather than rerunning checks to gain
confidence secondhand. A new run is required when relevant code, configuration, environment,
or test inputs change—not because ownership moved between agents.

### Failure handling

When verification fails:

- Determine whether the failure distinguishes an in-scope regression.
- Fix the coherent cause rather than patching individual symptoms blindly.
- Rerun the smallest failed or affected checks first.
- Broaden only after the discriminator passes.
- Compare suspected baseline failures against a relevant known-good state when practical.
- Report anything left unproven instead of silently treating infrastructure failure as success.

A failing tool or environment is visible evidence. The agent does not work around it by
inventing a weaker check that cannot catch the same defect.

### Implementation and verification invariants

- Related edits are completed as one coherent implementation before normal verification.
- Diagnostics may run early; repeated broad verification may not.
- The main agent owns ordinary tests, builds, failure diagnosis, and fixes.
- Verification is proportional to behavior and risk.
- Every check must contribute evidence that could affect confidence or the next action.
- Passing evidence is reused for the same commit and environment.
- Review fixes invalidate only the evidence they can affect.
- Human checks contain only verification agents could not complete.

## 6. Agent review

### Purpose

Formal review supplies independent judgment before the change reaches the human or PR. It is
not a style pass, a repeated implementation phase, or a ritual rerun of evidence the main
agent already produced.

Review asks whether the change is correct, complete, appropriately scoped, maintainable, and
supported by evidence. It checks the actual artifact against the stated objective and
contract rather than reviewing the summary alone.

### Independence

Every formal review begins with an agent that did not author the implementation being
reviewed. Scoped minor fixes made during that review do not compromise the independence of
its initial judgment.

- The reviewer receives the exact artifact or commit.
- It reads the relevant surrounding code and context for itself.
- It may rely on recorded test evidence without trusting unverified claims.
- It is not prompted toward approval or toward finding a quota of issues.
- Its model, perspective, or specialty should fit the risk being reviewed.

The author's self-review remains part of implementation quality, but it does not replace the
independent pass.

### Review breadth

The task owner chooses review depth and facets before spawning reviewers.

- Ordinary work receives one general independent review.
- Larger or higher-risk work may receive several reviews with distinct facets.
- Facets may include correctness, concurrency, security, migration safety, performance,
  compatibility, or user experience.
- Multiple general reviews are used only when independent agreement itself has value.
- Review effort remains proportional; a bounded fix should not acquire a review committee.

Each reviewer gets a brief naming its facet. The task owner synthesizes overlapping or
conflicting findings rather than forwarding several raw reports independently.

### Review inputs

A review brief includes:

- The objective and approved change contract, if one exists.
- Root cause or feature specification and selected solution.
- The exact commit or artifact under review.
- Relevant scope boundaries and exclusions.
- Verification evidence already produced.
- Known uncertainty and the requested review facet.
- Scoped write authority for safe minor fixes.

The reviewer may inspect beyond edited files when necessary to understand integration or
blast radius. That inspection does not authorize unrelated changes.

### What the reviewer examines

The reviewer follows the risks of the change rather than a universal checklist. Relevant
questions may include:

- Does the implementation satisfy each objective?
- Does it match the approved behavior and scope?
- Is the root cause addressed rather than hidden?
- Are important failure paths, boundaries, and interactions handled?
- Did the change introduce unnecessary mechanism or duplicate an existing abstraction?
- Are compatibility, data, concurrency, security, or UI consequences accounted for?
- Can the recorded verification actually detect the failures it claims to cover?
- Did anything unrelated enter the diff?

The reviewer may run a focused discriminator when evidence is missing or doubtful. It does
not rerun the full verification stack merely to reproduce confidence.

### Practical risk and remediation value

Finding a technically possible defect is not enough. The reviewer also evaluates whether it
is reachable, consequential, and worth changing now.

For any finding that could drive rework, consider:

- **Reachability:** Can this occur through a live path today, or only through a hypothetical
  future use or impossible state?
- **Frequency:** If reachable, how often is the triggering condition likely?
- **Impact:** Does it block work, corrupt data, weaken security, mislead a person, or merely
  create a recoverable inconvenience?
- **Recovery:** Is the failure obvious and easily corrected, or silent and destructive?
- **Fix cost:** Is the correction local and clear, or broad, complex, and likely to create new
  risk?
- **Scope fit:** Does fixing it belong to the approved objective, or would it turn this job
  into a different project?

Use the combined judgment:

- A live, frequent, or destructive defect usually warrants correction.
- A rare path may still warrant correction when impact is severe or silent.
- A theoretical path may be worth hardening when the fix is simple and low-risk.
- A rare, non-blocking, recoverable issue with a large or risky fix should usually be accepted,
  deferred, or explicitly left alone.
- Speculative future-proofing does not become required work merely because a reviewer can
  imagine it.

The report separates defect validity from remediation priority. “This can happen” and “this
should block the change” are different claims, and each needs its own evidence.

### Finding levels

#### Major

A major finding requires the main agent's judgment or changes material behavior, scope,
architecture, risk, data, compatibility, or the approved contract.

- Do not fix it silently.
- Report the live or plausible path, evidence, frequency, impact, recovery, and fix tradeoff.
- State whether the recommendation is fix now, defer, accept, or investigate further.
- Avoid prescribing an implementation unless only one safe correction exists.
- Mark whether it blocks PR creation or landing.

A major finding must be defensible under challenge. The reviewer should be able to show why
the path is real or prudently worth guarding, why its impact matters, and why the recommended
remediation is proportionate. Unsupported possibility is not a major finding.

The size of the edit does not decide severity. A one-line authorization bug is major; a
twenty-line mechanical cleanup may be minor.

#### Minor

A minor finding is local, unambiguous, inside the approved direction, and safely correctable
without a product or design choice.

- Apply the fix directly under scoped write authority.
- Keep the fix within the reviewed work's boundary.
- Run the smallest verification that can distinguish the correction.
- Record the file, change, reason, and evidence in the report.
- Leave the resulting diff or commit for the main agent to accept.

Examples include a missed local edge case with an obvious intended behavior, an incorrect
nearby assertion, or a small consistency defect required by the existing contract.

#### Nit

A nit does not materially improve correctness, scope, maintainability, or user outcome.

- Do not report it.
- Do not fix it.
- Do not spend task-owner or human attention on it.

Optional personal preferences, speculative cleanup, and unrelated polish are nits.

### Reviewer write authority

Implementation reviewers receive a scoped write role so minor fixes do not require a full
return-and-redispatch loop.

- The review target and approved direction define the boundary.
- The reviewer does not widen scope or redesign the solution.
- Every edit appears in the report back.
- The main agent remains accountable for the combined result.
- If the reviewer becomes uncertain whether a fix is minor, it reports a major finding
  instead of editing.

Plan and design review preserve their artifact ownership rules. A plan reviewer reports
shape changes to the planner unless the plan mechanism explicitly grants a safe, serialized
edit path.

### Review output

The report is compact and action-oriented:

- Overall result: ready, ready after applied minor fixes, or major findings remain.
- Major findings, ordered by practical risk, with their remediation recommendation.
- Minor fixes applied, with targeted verification.
- Important uncertainty left unverified.
- The exact commit or artifact reviewed and produced.

No nit section exists. Passing checks already recorded elsewhere are referenced rather than
repeated in full.

### Resolving major findings

Major findings return to the main agent.

1. The main agent evaluates the finding against the objective and evidence.
2. It evaluates live reachability, impact, recovery, fix cost, and scope fit.
3. It fixes the issue, defers or accepts it with a defensible reason, challenges unsupported
   reasoning, or raises a material design delta.
4. It reruns only affected verification when code changes.
5. The original reviewer checks closure or responds to the challenge when its context remains
   useful.
6. A fresh additional reviewer is used when the fix materially changes scope, approach, or
   the risk requiring independence.

Re-review focuses on the changed and previously deficient surfaces. It does not restart the
entire workflow by default.

### Review and PR boundary

The PR opens only after:

- Required review facets are complete.
- Major findings are resolved or explicitly accepted by the proper authority.
- Reviewer-applied minor fixes are incorporated.
- Verification affected by review changes is current.
- The final review evidence names the commit it supports.

The human is not expected to repeat code review. The PR explains what agents reviewed and
what remains for the human to verify manually.

### Review invariants

- Formal review is independent from authorship.
- Review breadth follows risk and has an explicit owner.
- Major findings return to the main agent.
- Major findings are evidence-backed, reachable or prudently worth guarding, and proportionate
  to their remediation recommendation.
- Minor findings are fixed and verified by the reviewer within scoped authority.
- Nits consume no further work or reporting.
- Review does not duplicate passing verification without cause.
- Re-review follows changed risk rather than restarting automatically.
- Review evidence identifies the artifact or commit it covers.
- The PR does not open with unresolved required review work.

## 7. PR, human review, and merge

### The PR is a human decision interface

By the time the PR opens, agents have already implemented, verified, and independently
reviewed the change. The human is not expected to reconstruct the work, read the code, rerun
agent checks, or discover what remains unverified.

The PR must make the next human action obvious while preserving enough design and execution
context to understand what is being approved.

### PR entry conditions

Open the PR only when:

- The coherent implementation is complete.
- Relevant tests, builds, and agent walkthroughs are current.
- Required review facets are complete.
- Major findings have defensible dispositions.
- Reviewer-applied minor fixes are incorporated and verified.
- The branch represents the intended human-review candidate.
- Remaining human-only checks are known.

The PR is not the place where agents first discover whether the change is ready.

### PR description

The description is the durable repository summary. It should let a future reader understand:

- Why the change exists.
- Root cause for a bug, or feature intent and specification for new behavior.
- The selected solution and important tradeoffs.
- User-visible or system-visible behavior changes.
- Scope and meaningful exclusions.
- Verification and independent review completed.
- Important accepted or deferred risks.

It stays concise and links to detailed artifacts rather than reproducing the plan or review
log.

### Human-review comment

Post or update one authoritative comment. It is structured for the human's next move, not for
the order in which the work happened.

#### 1. What you need to do

This is always first.

- List only checks agents could not complete.
- Give exact routes, screens, controls, accounts, devices, or environments.
- State the expected result for each action.
- Say what failure looks like and what to report back.
- Keep steps ordered as the human should perform them.
- End with the requested decision: approve landing or report a problem.

If no manual verification remains, say so plainly:

> No manual testing remains. Review the summary below and approve landing if it matches the
> intended outcome.

Do not ask the human to read the diff, rerun automated tests, repeat agent walkthroughs, or
perform generic “sanity checks.”

#### 2. What changed and why

Explain the change at the level needed to judge its intent:

- Root cause and why the old behavior failed, or the feature specification and user need.
- Selected solution and the reason it was chosen.
- Important behavior changes.
- Scope and exclusions that affect expectations.

Root cause or feature intent is as important as the manual checklist. The human should know
both what to exercise and what outcome the change is supposed to create.

#### 3. What agents established

Summarize evidence without asking the human to reproduce it:

- Focused tests and affected builds.
- Agent-driven live or UI walkthroughs.
- Independent review facets.
- Minor fixes applied by reviewers.
- Major findings and their dispositions.
- Residual uncertainty or accepted risk.
- The reviewed commit.

Use compact results and artifact links. Raw logs do not belong in the primary reading path.

#### 4. Plan and execution record

The plan is observability, not the human's action interface.

- Show the approved contract and meaningful plan outcome.
- Preserve completed shaping, implementation, verification, review, and landing steps.
- Keep detailed step output, attempts, and logs behind links or collapsed detail.
- Highlight material deviations and reapprovals.
- Omit empty fields and internal bookkeeping that communicate nothing.

Direct-path changes with no plan use the same human-first structure and simply omit the plan
record.

### One authoritative comment

The comment is updated in place throughout PR review and landing.

- Use stable identity rather than “edit the latest comment.”
- Never create competing current versions.
- Preserve the human checklist while approval is pending.
- Update evidence when the reviewed commit changes.
- After merge, replace pending actions with the final outcome and retain the completed record.

The event store may preserve prior renderings. The PR should present one current version.

### Human-review block

After opening the PR and posting the comment, the task owner blocks for human review.

The message to the human includes:

- The PR link.
- The same concise “What you need to do” actions shown first in the comment.
- The decision requested after those actions.

It does not paste the whole PR record into chat. The human should be able to act from either
entry point without finding conflicting instructions.

### Handling human feedback

If manual verification finds a problem:

- Record the exact observed behavior and environment.
- Return it to the main agent as a live-path defect.
- Fix the coherent cause.
- Rerun only affected agent verification and review facets.
- Update the same PR comment and human checklist.
- Ask the human to repeat only the manual checks invalidated by the fix.

Do not restart unrelated testing or review merely because the PR returned to implementation.

### Landing approval

Human approval applies to the reviewed commit and the stated manual-check result.

- Bind approval to the PR head commit.
- Use the required checks and review evidence already recorded for that commit.
- Merge without another routine question.
- Update the authoritative comment with the final merged state.
- Complete the plan and cleanup after the merge succeeds.

One approval should cover the normal landing chain. Push, merge, comment update, and cleanup
must not each become another human gate.

### Changes after approval

A changed PR head does not automatically mean the same approval still applies.

- Code or configuration changes receive affected verification and review.
- Repeat human checks only when their relevant behavior changed.
- Request renewed landing approval when behavior, risk, evidence, or the reviewed result
  materially changed.
- Do not request renewed approval for metadata-only updates that cannot affect the change.

The reason for reapproval is invalidated judgment, not merely a different commit hash.

### Merge safety without re-verification

Landing uses the evidence and approval already produced. It does not rerun tests, review, or
manual checks merely because the merge step began.

- Carry the approved head as the expected merge target.
- Compare the current head and required status once when landing begins.
- If the head and relevant evidence are unchanged, merge directly.
- If something changed, evaluate only whether that change invalidates approval or evidence.
- Use existing evidence for known baseline or infrastructure failures.
- Do not rerun passing checks to make the merge step feel safer.
- A hold received before landing begins stops it; once landing has committed, report the real
  outcome rather than pretending it can be undone.
- Report merge and cleanup failures according to what actually completed.

Runtime should make the short transition from accepted approval to merge unambiguous. It does
not need to turn that transition into another verification phase.

### PR and merge invariants

- The human's required actions appear first.
- Root cause or feature intent remains prominent.
- Agents never ask the human to repeat completed agent verification.
- The raw plan is secondary observability, not the primary interface.
- One authoritative PR comment represents current state.
- Human approval names the reviewed result being landed.
- Material post-approval changes invalidate only the judgment and evidence they affect.
- Normal approval leads directly to merge without additional routine gates.
- Failed merge or cleanup remains visible and unfinished.

## 8. Complete prompt-system audit

### Audit the delivered instruction system

The unit of review is not a Markdown file. It is the complete instruction set an agent
receives in a particular role, workflow path, capability state, and turn.

Every prompt surface must be reviewed twice:

1. By itself: clarity, accuracy, scope, efficiency, and internal consistency.
2. In composition: how it reinforces or contradicts everything delivered before and after it.

The audit follows the code that assembles prompts. A file name that looks prompt-like is not
proof it is delivered, and generated or conditional text must not be missed because it does
not live in an obvious prompt file.

### Prompt-surface inventory

Inventory every source that can instruct or steer an agent:

- Universal protocol text.
- Role prompts and role metadata.
- Spawn identity, workspace, capability, and task fragments.
- Plugin-provided spawn fragments.
- Plan guide, planner instruction, step definitions, templates, and generated catalogue.
- Presets and procedures applied during a session.
- Just-in-time guidance and reminder rules.
- Notification, interrupt, reply, restoration, and lifecycle messages.
- Command help, errors, and generated next-step instructions.
- Repository overrides and local role or prompt configuration.
- Delegation briefs and main-agent handoffs.
- System or host instructions outside Switchboard's control that still constrain behavior.
- User instructions and agent-to-agent messages as the final task-specific layer.

For each source, record:

- Where it is defined.
- Which code path loads it.
- Who receives it.
- When it is delivered.
- What condition activates it.
- Its precedence relative to other instructions.
- Whether Switchboard can edit or only accommodate it.

### Render effective prompts

Build a development-only way to render the exact effective instruction set for a chosen
scenario, with source boundaries preserved.

The renderer should support:

- Role and model.
- Top-level, shared-worktree, isolated, or bare placement.
- Capability seed and later grants.
- Enabled plugins and repository overrides.
- Initial task, delegated task, or no-task startup.
- Relevant guidance and lifecycle state.
- Applied presets.

It displays the delivered text in delivery order and identifies the source of every segment.
It should render what the agent actually receives after flattening, substitution, filtering,
and size limits—not an idealized concatenation.

This renderer is an inspection tool, not another runtime prompt layer.

### Canonical ownership of instructions

Each rule needs one authoritative prompt layer.

| Instruction kind | Canonical owner |
| --- | --- |
| Universal communication, lifecycle, and safety | Protocol |
| Role purpose, ownership, and standing authority | Role prompt and role metadata |
| Plugin-specific concepts and procedures | Plugin instruction or guide |
| Exact command syntax and validation | Command implementation and help |
| Turn-specific reminders | Just-in-time guidance |
| Task objective, scope, and constraints | User instruction or delegation brief |
| Human-approved behavior and boundaries | Change contract and plan |
| Repository-specific policy | Repository override or bound procedure |

Other layers may point to the canonical instruction. They should not independently rewrite
it. When a critical rule must appear in several effective prompts, generate it from one
shared source rather than maintaining several prose copies.

A pointer is useful only when the agent knows when to follow it. Moving all detail behind
lookups can be as ineffective as duplicating it everywhere.

### Individual prompt review

Review every owned prompt surface for:

- One clear purpose and audience.
- Accurate commands, roles, models, capabilities, and paths.
- Direct language that survives flattening and composition.
- Scope appropriate to its layer.
- No obsolete workflow assumptions.
- No examples that accidentally become mandatory templates.
- No commentary or rationale delivered when only an instruction is needed.
- No instruction asking the agent to infer information the runtime already knows.
- No rule that depends on a capability the recipient lacks.
- No task-specific behavior embedded in a universal prompt.

Long explanatory comments may remain in source when they are not delivered. The audit measures
delivered text separately from maintainer documentation.

### Composed prompt review

Review effective prompts across these shared dimensions:

- Task and job ownership.
- Scope and authority.
- Direct work versus delegation.
- Research, shaping, planning, and approval.
- Implementation and verification timing.
- Independent review and reviewer fixes.
- PR creation, human interaction, and merge.
- Waiting, communication, completion, and cleanup.
- Model, role, tool, and capability selection.
- Failure, cancellation, and recovery.
- Human-facing output.

For each dimension, ask:

- Do two layers give different instructions?
- Does a later generic rule undo an earlier role-specific rule?
- Is one instruction repeated enough to dominate behavior unintentionally?
- Does the agent have the authority and tools required to comply?
- Does a role receive irrelevant workflow that increases confusion or token cost?
- Is a just-in-time instruction delivered too early, too late, or repeatedly?
- Would a reasonable agent following all instructions reach the intended workflow?

### Runtime truth audit

Check every operational prompt claim against the implementation.

- Command names, parameters, aliases, and defaults.
- Supported model and role identifiers.
- Capability meaning and inheritance.
- Workspace, branch, isolation, and file ownership behavior.
- Mail, waiting, blocking, completion, restoration, and cleanup behavior.
- Plan composition, dependencies, gates, rendering, and ownership.
- PR comment identity and update behavior.

Prompt wording should not compensate for avoidable command brittleness. For example, human
model shorthand should be resolved by authoritative aliases or discovery rather than relying
on a dispatcher to guess a strict internal identifier.

When prose and runtime disagree, decide which behavior is intended before editing either.
Do not automatically make documentation match a defect.

### Prompt efficiency

Measure the effective cost by role and scenario.

- Delivered characters and tokens.
- Repeated claims and near-duplicates.
- Instructions irrelevant to the recipient's role or current state.
- Procedures that could arrive only when applicable.
- Long examples that bias agents toward one workflow shape.
- Pointers that cause avoidable lookup turns.
- Notifications that cause avoidable inbox turns.

Subtraction is the default optimization. Compress only after deciding the instruction belongs;
otherwise concise duplication remains duplication.

The goal is not the shortest prompt. It is the smallest instruction set that reliably
produces the intended behavior without hiding essential context behind extra turns.

### Representative composed paths

Render and inspect the effective instructions for the paths that exercise each distinct
composition boundary. The audit should include these paths where they exist:

- Dispatcher routing a clear direct change.
- Dispatcher routing an ambiguous or shaped request.
- Dispatcher resolving human shorthand for a role or model.
- Worker carrying a bounded change end to end.
- Worker discovering a bounded need for temporary delegation.
- Lead performing the work directly, with only the later independent reviewer as a child.
- Lead shaping work, using a planner, then continuing as main agent.
- Lead handing shaped work to a fresh main agent.
- Planner challenging an infeasible or over-delegated plan.
- Research-only and one-on-one discussion that never becomes a change.
- Research or discussion that later becomes direct or shaped work.
- Reviewer applying minor fixes and returning defensible major findings.
- QA performing specialized verification without rerunning ordinary tests.
- Generic, any-child, and all-child waiting.
- Direct mail, reply-required mail, interrupt, and batched completion.
- PR with human-only checks and PR with no remaining manual checks.
- Material post-approval change and metadata-only post-approval change.

These are composition inspections, not a synthetic behavior benchmark. Passing an isolated
prompt review does not establish that the combined instruction path is coherent.

### Finding classification

Classify audit findings by the layer that should own the correction:

- **Design conflict:** intended behaviors disagree and require a product decision.
- **Prompt contradiction:** intended behavior is settled but instructions conflict.
- **Wrong layer:** valid instruction is delivered from the wrong source or to the wrong roles.
- **Duplication:** one rule has several maintained prose copies.
- **Runtime defect:** implementation cannot support or contradicts the intended instruction.
- **Missing runtime affordance:** prompts ask agents to compensate for absent aliases, state,
  validation, or atomic behavior.
- **Brief defect:** task-specific context is too narrow, too broad, or overly prescriptive.
- **Efficiency defect:** behavior is correct but costs unnecessary agents, turns, tokens, or
  verification.

Fix the owning layer rather than adding another instruction around the symptom.

### Audit sequence

1. Finalize the intended workflow and role model in this document.
2. Discover prompt assembly from runtime code.
3. Inventory all delivered and conditional sources.
4. Render representative effective prompts with provenance.
5. Review every source individually.
6. Review each role and scenario in composition.
7. Check operational claims against runtime behavior.
8. Assign every finding to its canonical owner.
9. Remove contradictions and duplication before polishing wording.
10. Render the revised effective prompts again.
11. Exercise focused behavior checks for changed mechanisms, then observe judgment-heavy
    behavior through ordinary work.

Do not edit prompts piecemeal while the intended ownership and composition are still unknown.

### Durable verification

After the rewrite, preserve confidence through:

- Structural tests for assembly order, conditions, provenance, and size limits.
- Targeted tests for exact command names and generated operational text.
- Focused behavior checks for concrete runtime mechanisms.
- Observation of role and workflow decisions during ordinary use.
- A small set of readable effective-prompt fixtures where exact composition is itself the
  contract.

Avoid giant full-prompt snapshots that turn every wording improvement into mechanical churn.
Tests should pin decisions and failure modes, not freeze all prose forever.

### Prompt-audit invariants

- Every delivered instruction has a known source, audience, condition, and precedence.
- Every rule has one canonical owner.
- Effective prompts contain no contradictory task-ownership or workflow instructions.
- Operational vocabulary matches runtime truth.
- Role prompts describe authority without forcing unnecessary delegation.
- Plugin instructions do not override the broader workflow accidentally.
- Task briefs preserve scope without removing agent judgment.
- Just-in-time guidance replaces universally delivered reminders when safe.
- Prompt cost is measured on effective compositions, not individual files.
- Ordinary real-work observation validates judgment-heavy behavior in the combined system.

## 9. Prompt rules versus runtime enforcement

### Use the lightest reliable mechanism

Not every desired behavior should become a hard gate, and not every invariant should depend
on an agent remembering prose.

Choose the mechanism by the nature of the decision:

1. **Runtime enforcement** for identity, state integrity, authorization, destructive actions,
   idempotency, and transitions that must never be ambiguous.
2. **Structured validation** for detectable defects that should normally stop or warn before
   downstream work.
3. **Generated vocabulary and help** for exact names, parameters, capabilities, and available
   choices.
4. **Prompts and briefs** for contextual engineering judgment, proportionality, tradeoffs, and
   communication quality.
5. **Real-use observation and focused behavior checks** for decisions that cannot be reliably
   reduced to syntax.

Choose the least restrictive mechanism that can carry a rule reliably. Observation verifies
the combined system but does not replace a needed state safeguard. Hard enforcement has its
own failure cost: it can turn flexible engineering work into a brittle workflow engine.

### What runtime should enforce

Runtime owns facts and transitions it can know exactly.

- Agent, job, plan, step, attempt, message, and commit identity.
- Role and capability existence.
- Model and command argument normalization.
- Parent-child, workspace, isolation, and branch relationships.
- Serialized plan-shape writes and valid dependency structure.
- Approval identity and the commit or contract it covers.
- Stable PR-comment identity and idempotent update.
- Waiting, blocking, completion, cancellation, restoration, and cleanup state.
- Direct message delivery, reply tracking, and cohort wake conditions.
- Deduplication and stale-event suppression.
- Merge targeting the approved and reviewed head.
- Refusal of unsafe, invalid, or ambiguous state transitions.

Runtime does not need to execute the engineering plan. It protects the record and sanctioned
transitions while agents continue to interpret and adapt the work.

### What validation should catch

Validation handles structure that is objectively inspectable but may not justify a hard
runtime refusal in every context.

- Missing or invalid plan dependencies.
- An approval step placed after work it is meant to authorize.
- Implementation or PR steps claiming completion while required predecessors remain open.
- A formal reviewer who authored the implementation before review began. Scoped fixes made
  during an independent review do not violate this rule.
- Evidence that names no commit or relevant artifact.
- A PR comment missing its human-action section.
- A completed gate that still appears to be waiting for input.
- Unsupported role, model, capability, step, or command names.

Use refusal when continuing would corrupt state, bypass approval, target the wrong artifact,
or perform an unsafe action. Use a warning when the structure is unusual but may be a valid
engineering choice.

Warnings must say what is wrong and how to inspect or correct it. A red indicator with no
actionable explanation only moves the ambiguity to the agent.

### What prompts should decide

Prompts own decisions that depend on evidence and context.

- Direct path versus shaped-plan path.
- Whether investigation, design review, a fresh main, QA, or multiple review facets add value.
- How to scope a brief without prescribing implementation.
- Which solution is cleanest and most proportionate.
- Which verification can actually disprove the change's claims.
- Whether a reviewer finding is reachable and worth fixing now.
- What constitutes a material scope, behavior, or risk change.
- Which manual checks genuinely require the human.
- How much explanation the current reader needs.

The runtime may expose facts that improve these judgments. It should not pretend to make the
judgment because a few fields happen to be machine-readable.

### Generated operational vocabulary

Agents should not memorize strict internal identifiers.

- Generate role, model, capability, plugin, step, preset, and command catalogues from current
  runtime configuration.
- Accept documented human-friendly aliases where ambiguity is low.
- Normalize common spelling and formatting variants.
- On failure, show valid nearby choices and the exact accepted form.
- Let prompts instruct agents to resolve vocabulary through the catalogue rather than guess.

The `gpt5.6sol` failure belongs here. A dispatcher should preserve the requested model intent;
the command layer should resolve a supported alias or return an actionable choice instead of
depending on prompt intelligence to manufacture an internal identifier.

### Plan-path enforcement

The direct and shaped paths require different structure.

#### Direct path

- The human's directed request authorizes the bounded change.
- No placeholder, formal plan, or change-approval gate is manufactured.
- Normal verification, independent review, PR review, and merge rules still apply.
- Discovery of material uncertainty moves the work to the shaped path.

The path choice remains agent judgment. Runtime records the chosen path and can validate the
requirements that follow from it.

#### Shaped path

- The evolving plan records shaping, formal planning, and combined approval.
- Approval depends on completed planning and required design review.
- Recorded implementation steps depend on approval.
- PR creation depends on current implementation review and evidence.
- Merge depends on human landing approval for the relevant result.

Plan commands should preserve these dependencies when composing known steps. Validation
should reject or flag structures that place a gate after the work it governs.

Switchboard cannot honestly guarantee that no raw filesystem edit occurred before approval.
Its capability system is not a security boundary. It can still make the sanctioned path
clear and difficult to misuse:

- Keep researchers and planners without tracked-write authority by default.
- Spawn or activate the main execution owner only after approval when a fresh main is used.
- Record unauthorized or out-of-phase tracked work when detected.
- Prevent that work from being presented as an approved, review-ready change without resolving
  the mismatch.

Do not claim stronger enforcement than the system possesses.

### Review enforcement

Formal review has a few machine-checkable properties and many judgment calls.

Runtime or validation should establish:

- The reviewer is independent from the author.
- The review names its target commit or artifact.
- Reviewer write authority is scoped to the reviewed change.
- Reviewer-applied fixes produce a new identifiable result.
- PR creation does not proceed with unresolved blocking review state.

Prompts establish:

- Review breadth and facets.
- Major, minor, and nit judgment.
- Live-path risk and remediation value.
- Whether a fix remains local and unambiguous.
- Whether re-review or another independent facet is warranted.

Filesystem scope cannot be perfectly enforced through prompts or capabilities. Review diffs
and post-action checks remain necessary for detecting overreach.

### Verification enforcement

Do not encode “implementation before normal verification” as a prohibition on test commands.
Diagnostics and discriminating checks are legitimate during investigation and implementation.

Runtime can help by:

- Attaching commit and environment identity to evidence.
- Reusing current evidence instead of requesting another run.
- Showing when relevant inputs changed.
- Distinguishing focused, broad, manual, and human-only evidence.

Prompts decide which checks are proportionate. Ordinary-use observation catches
repeated-suite behavior, verification theater, and delegation of ordinary failures to QA.

### Human-review rendering

The PR's human-first structure should be implemented in the renderer or template, not rebuilt
from memory by every agent.

Runtime should guarantee:

- One authoritative comment per PR and job.
- “What you need to do” appears first.
- Root cause or feature intent and selected solution remain visible.
- Agent evidence and reviewed commit are represented.
- Detailed plan and execution output remain secondary.
- Empty internal fields do not dominate the rendering.
- Updates preserve identity and replace current state rather than adding competing comments.

Agents still decide the actual manual checks, explanation, risks, and evidence summary.

### Merge enforcement

The merge mechanism consumes approval and evidence rather than recreating them.

- Carry the approved head and relevant review identity.
- Compare current state once when landing begins.
- Merge directly when approval and evidence remain applicable.
- Refuse an unexpected target or unresolved required state.
- Do not automatically rerun tests, builds, reviews, or manual checks.
- Record which landing actions completed when a later action fails.

This protects identity and state without turning merge into another workflow cycle.

### Fail-closed and fail-open boundaries

Fail closed when the system would otherwise:

- Target the wrong repo, branch, plan, step, PR, comment, or commit.
- Bypass a required human gate.
- Lose or overwrite durable work.
- Perform a destructive or externally visible action without authority.
- Accept malformed state that cannot be interpreted safely.

Prefer warnings or agent judgment when the question is:

- How much process the work deserves.
- Whether another agent would help.
- Which implementation is cleanest.
- Whether a rare issue merits a complex fix.
- Which evidence is sufficient for the current risk.
- Whether unusual but coherent plan structure is appropriate.

Safety and identity failures must not be waved through. Engineering judgment must not be
replaced by a growing collection of rigid gates.

### Enforcement invariants

- Runtime owns facts, identity, durable state, and irreversible transitions.
- Validation catches objective structural defects without rejecting valid flexibility.
- Generated vocabulary replaces guessed operational identifiers.
- Prompts own contextual engineering judgment.
- Focused behavior checks and ordinary-use observation cover behavior that schemas cannot
  express.
- Direct work remains lightweight.
- Shaped work cannot appear approved when its recorded approval came later.
- Review and evidence remain bound to what they evaluated.
- Human-facing layout is generated consistently while its content remains agent-authored.
- Merge consumes existing approval and evidence without repeating verification.
- No layer claims enforcement stronger than the mechanism actually provides.

## 10. Validation, dogfooding, and rollout

### Validate through real use

The real test is the human using Switchboard for normal work and observing how agents behave.
Do not create a large evaluation program that costs as much as the workflow it is meant to
improve.

Use the redesigned workflow on the natural mix of tasks that already occurs:

- Trivial and directed fixes.
- Unclear bugs.
- One-on-one research and design discussion.
- New features with tradeoffs.
- Larger changes using planners, reviewers, or parallel work.
- PRs with and without human-only checks.

The variety arrives through real use. It does not need to be manufactured up front.

### What to observe

Judge each run by practical questions:

- Did the initial agent choose a sensible direct or shaped path?
- Did the lead work directly when another agent added no value?
- Did briefs preserve agent judgment while holding scope?
- Did approval occur before shaped implementation?
- Did implementation remain coherent before verification?
- Were tests, builds, and evidence repeated unnecessarily?
- Did reviewers omit nits, fix minors, and defend majors?
- Did waiting, mail, and child completion waste turns?
- Did the PR clearly say what the human needed to do?
- Did merge use existing approval and evidence without reopening the workflow?
- Did any prompt contradiction or missing runtime affordance confuse the agent?

No numeric score is required. The important evidence is the observed behavior, the point where
it diverged, and what instruction or mechanism caused it.

### Focused proof for code changes

Runtime fixes still receive small tests that distinguish fixed from broken.

- Reproduce the concrete failure.
- Prove the intended path.
- Cover one important safety boundary when needed.

Prompt changes are checked by rendering the affected effective prompts and then observing them
in real tasks. Avoid giant prompt snapshots, synthetic agent tournaments, and repeated full
suites.

Use an isolated instance only when a runtime change could disturb active Switchboard state or
when the failure cannot be safely demonstrated in normal use.

### Rollout

1. Implement the runtime and prompt changes in compatible dependency order.
2. Inspect the effective prompts for the main roles and remove obvious contradictions.
3. Run focused tests for changed runtime behavior.
4. Enable the new workflow for new tasks.
5. Use it for the human's normal work.
6. Record concrete friction or incorrect behavior when it appears.
7. Fix the responsible prompt, runtime mechanism, or design decision.
8. Continue until the workflow is consistently easier and more reliable.

Do not change the operating rules underneath active jobs unless the human explicitly chooses
to migrate one. Existing work may finish under the behavior it started with.

### Feedback discipline

Respond to real failures without turning every incident into another narrow rule.

- Fix the general cause when several behaviors share it.
- Prefer deleting contradictions over adding reminders.
- Move objective state problems into runtime instead of more prose.
- Leave engineering judgment flexible when the agent made a reasonable call.
- Do not optimize one unusual task at the cost of common work.
- Revisit this design when repeated real use shows the model itself is wrong.

The workflow is accepted through sustained ordinary use, not a one-time validation verdict.

## 11. Final synthesis and implementation

### The system in one view

Switchboard should route work to one capable task owner, then add structure and specialists
only when the work earns them.

```text
human request
    |
dispatcher routes from what is already known
    |
    +-- clear bounded work ----------> worker or lead executes directly
    |
    +-- research or discussion ------> investigate and converse
    |                                      |
    |                                      +-- no change: report and finish
    |                                      +-- clear change: direct path
    |                                      +-- uncertain change: shaped path
    |
    +-- uncertain or complex work ---> lead shapes the job
                                           |
                                           +-- evolving placeholder
                                           +-- planner builds formal plan
                                           +-- human approves solution, plan, and contract
                                           +-- lead or justified fresh main executes

execution -> proportionate verification -> fresh-agent review -> PR -> human checks -> merge
```

The plan path is selected by uncertainty, tradeoffs, coordination, and risk—not by whether a
file will change or whether a lead has delegation authority.

### Operating model

- The dispatcher routes and resolves operational vocabulary; it does not investigate or
  design.
- A worker owns bounded work end to end.
- A lead owns work end to end and may delegate, but normally preserves one coherent context.
- A planner is a first-class bounded specialist for formal plan construction.
- The main agent is the lead or worker carrying execution through landing.
- Native subagents handle short read-only assistance.
- Switchboard agents handle durable ownership, tracked work, formal review, and specialized
  verification.
- Every formal review uses a different agent from the author.
- Reviewers fix and report safe minor issues, omit nits, and defend major findings.
- The main agent owns ordinary tests, builds, failures, and fixes.
- QA exists only where another environment or perspective adds real value.

### Workflow model

- Direct work skips placeholder planning and separate change approval.
- Shaped work uses one evolving plan from discovery through landing.
- Research and one-on-one discussion remain planless until a change path is chosen.
- Shaped approval covers the solution, execution plan, and change contract in one response.
- Coherent implementation precedes normal verification.
- Passing evidence is reused for the commit and environment it covers.
- Formal review completes before the PR opens.
- The PR puts human actions first, then intent, agent evidence, and plan observability.
- Human review covers only what agents could not verify and the decision to land.
- Merge consumes current approval and evidence without starting another verification cycle.

### Coordination model

- Parent-child ownership, durable messages, blocking, completion, restoration, and cleanup
  remain familiar.
- Plain `waiting` covers native subagents and background work.
- `waiting --any` and `waiting --all` cover child results without Stop-hook workarounds.
- Messages and child reports are delivered directly rather than through notification-only
  turns.
- Cohort waits return one combined result.
- Attempt and commit identity prevent stale work from satisfying current work.
- Only one task owner presents a given decision to the human.

### Prompt and runtime model

- Protocol owns universal communication, lifecycle, and safety.
- Roles own purpose, task ownership, and standing authority.
- Plugins own their concepts and procedures.
- Briefs own task-specific objective, scope, constraints, and acceptance.
- Runtime owns identity, state, vocabulary, idempotency, and irreversible transitions.
- Validation owns objectively detectable structural defects.
- Prompts own contextual engineering judgment.
- Behavioral observation through real work tests the combined result.

One rule has one canonical owner. Effective prompts are rendered and audited in composition,
not inferred from individual files.

### Repair strategy

Treat this as one coordinated redesign with one accountable implementation owner. Do not split
it into unrelated prompt tweaks or use the currently broken workflow to manage its own repair.

The implementation owner works directly with the human, retains context across the audit and
change, and delegates only independent review or a genuinely specialized investigation. The
current plans plugin is not required to coordinate this repair; a human-reviewed written
change plan is enough until the replacement behavior exists.

### Authority baseline

`DESIGN-TRUTH.md` and `design/PLANS-AND-STEPS.md` carry this workflow as trusted authority.
Implementation and review use them to resolve any disagreement with existing prompts or
runtime behavior.

### Audit and repair contract

`notes/workflow-audit.md` contains the effective-prompt/runtime audit, concrete vocabulary,
surface map, findings, coordinated repair contract and preservation boundaries.

### Formal implementation plan

`notes/workflow-repair-plan.md` is the approved execution plan. It defines the change-record
architecture, compatibility, implementation phases, final verification, fresh review and
landing sequence.

### Step 1: implement runtime foundations

Implement only the objective foundations the audit confirms are missing, before prompts
depend on them. The expected surface is:

- Model and role vocabulary resolution with actionable errors.
- Generic, any-child, and all-child waiting.
- Direct mail and child-report delivery.
- Batched cohort completion.
- Attempt, message, evidence, and commit identity where missing.
- Stable PR-comment identity and human-first rendering support.
- Approval and merge identity sufficient to avoid repeated verification.

Keep additions backward-compatible until the new prompt bundle is ready.

### Step 2: reshape the plan workflow

- Support direct work without manufacturing a plan.
- Support one evolving placeholder for shaped work.
- Make planner ownership bounded and explicit.
- Place combined approval after shaping and before implementation.
- Preserve review, PR, human-check, and merge order.
- Carry evidence and human-facing output without dumping empty internal fields.
- Keep plans interpreted and adaptable rather than turning them into an executor.

### Step 3: rewrite the instruction system

Update the aligned bundle together:

- Protocol.
- Dispatcher, lead, worker, planner, researcher, reviewer, and QA roles.
- Spawn fragments and lifecycle messages.
- Plan guide, planner instruction, steps, templates, and catalogue wording.
- Delegation and main-agent brief guidance.
- Verification, review, PR, and merge procedures.
- Repository overrides and just-in-time guidance.

Delete superseded and duplicated rules. Do not leave compatibility prose telling agents both
the old and new workflows.

### Step 4: verify the repair

- Render the revised effective prompts and inspect their composition.
- Run focused tests for changed runtime mechanisms.
- Review the full diff against this document and the updated trusted design.
- Use fresh review facets for runtime correctness and combined prompt behavior.
- Fix safe minor findings directly; resolve defensible major findings proportionally.
- Run only verification affected by review changes.

No large synthetic evaluation program is required.

### Step 5: land and learn through use

- Open one coordinated PR unless the audit proves a backward-compatible runtime prerequisite
  must land separately.
- Present exact human actions, system intent, evidence, and residual risk.
- Enable the new behavior for new tasks after approval.
- Let active jobs finish under the behavior they started with.
- Use the workflow for ordinary human tasks and observe real behavior.
- Correct general causes when repeated friction appears.

Separate commits may preserve reviewable boundaries inside the coordinated change. They do
not turn the redesign into independent projects with different sources of truth.

### Scope boundaries

This repair does not aim to:

- Build a general workflow engine.
- Enforce engineering judgment through rigid schemas.
- Replace ordinary agent reasoning with mandatory templates.
- Guarantee filesystem security through capabilities that are not a security boundary.
- Create a large synthetic evaluation or benchmarking program.
- Fix unrelated Switchboard defects encountered during the audit.
- Migrate active jobs silently.

### Completion conditions

The repair is complete when:

- Trusted design, runtime behavior, prompt layers, and plan semantics describe one system.
- Direct work stays direct and lightweight.
- Leads work directly and delegate only when valuable.
- Shaped work receives meaningful planning and approval before implementation.
- Briefs preserve scope and agent judgment.
- Implementation, verification, and review avoid repeated cycles.
- Review findings receive proportionate, defensible treatment.
- Waiting and messaging remove avoidable coordination turns.
- The PR clearly tells the human what to do and why the change exists.
- Merge uses existing approval and evidence without reopening completed work.
- Normal human use shows the workflow is materially clearer, faster, and more reliable.

### Immediate next action

Begin Phase 1 of `notes/workflow-repair-plan.md`: make operational vocabulary and effective
instructions inspectable before changing the workflow prompts.
