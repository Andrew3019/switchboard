# Plans, steps, templates and change records

How work is structured while it runs, and how that structure is read back afterwards to
improve the system.

**Only Andrew decides what enters this file.** He may edit it himself or explicitly ask an
agent in the same conversation to transcribe the decisions he confirmed. Nothing arrives by
inference from code, history or another agent's conclusion. Absence is not a decision: what
is missing is undecided rather than free. Held to the same bar as `DESIGN-TRUTH.md`, which
remains the authority wherever the two meet.

---

## Why this exists

Plans preserve and coordinate work that needs shaping. They are not the entry fee for every
change and are not the universal container for landing facts. A plan records changing
investigation, design and execution shape. The associated change record carries approval,
evidence, independent review, human action and landing identity shared with direct work.

The plan makes uncertain work legible while it runs and useful as evidence afterwards. It
remains agent-interpreted rather than machine-executed: structure helps the owner reason,
delegate and recover without turning engineering judgment into a workflow engine.

Human interaction follows unresolved authority rather than a fixed gate count. Shaped work
has one combined solution, plan and contract approval before implementation. Direct work
uses the bounded human request as authorization. Both paths later require approval of the
current reviewed result before landing.

---

## Vocabulary

**Step** — the unit. What an agent owns, what gets ticked, what carries a try count and
notes.

**Plan** — the live shaping and execution structure of one shaped job: a group of steps with
an identity, worktree, changelog and kept record.

**Template** — a preconfigured plan, in the ordinary sense of the word. A starting point
you can do as you like with: a plan may be a template plus whatever else the job needs, and
nothing holds a plan to the shape it started from. Using one is copy and paste — the copy is
edited afterwards if it needs it, and nothing links it back to what it came from.

**Change record** — the durable landing record for a direct or shaped change. It carries
path, task owner, intent or approved contract, solution, evidence, independent review,
human-only checks, PR/head identity, approval and landing outcome. It may reference one
evolving plan; on the direct path it carries a fixed execution+landing step skeleton
(implementation, review, human checklist, PR, merge) rather than a hand-shaped step graph,
and creates no planning ceremony.

---

## Plans

A plan is the live shaping and execution structure of one shaped job: what is being done,
by whom and what is left.

**A plan is a DAG.** One step may fan out to several, and those may join back into one.

**A join waits because the plan owner does not start it.** Nothing executes the graph. Its
deps are interpreted by the accountable agent and validated as record structure.

**Redoing work is not an edge.** Where part of a job must be redone, its accountable owner
goes back to it. The graph stays acyclic, and the flexibility comes from it being
agent-driven rather than modelled.

**Semi-structured and changeable at any time.** More structured than a todo list, less
rigid than a fixed workflow. Not Claude's internal todos, not a flat list.

**Changed through the plugin's commands, not by editing the file.** Being interpreted rather
than executed is about what a plan *means*; it is still written through one door. Obliged
steps are added on that path, and a plan hand-edited around it gets none of them.

**A command changes the steps it names, never the whole plan at once.** Two agents ticking
different steps is already safe, but a plan owner reshaping is a read, a think and a write, and a
tick landing in that gap would be overwritten by a wholesale rewrite — leaving the changelog
showing a tick the plan does not have.

**Interpreted, never executed.** A plan is read and acted on by an agent, not run by a
machine. Nothing evaluates it, and there is no workflow engine around it.

**One shaped change has one evolving plan.** Several independent changes on one worktree may
have separate plans and change records; one plan does not span several PRs.

**A plan has an identity of its own, and so does every step.** A worktree's name is
reusable and its row is revived when the name comes back, so a plan keyed on that would
reattach to unrelated work weeks later. Plans and steps are addressed by their own ids —
which is also what lets a command say which of several plans it means, and what a spawn
prompt carries alongside the step it hands a worker.

**A plan belongs to one worktree, and a worktree may hold several plans.** So the board
renders plans inside the worktree grouping it already has, rather than in a section of
their own. From inside a plan the others are invisible and irrelevant: nothing in a plan
refers to another, and anything a step needs from the world outside is an input it takes.
A plan has at most one merge step and so at most one PR, which is what makes several plans
mean several PRs without any of them knowing about the others.
A plan never spans two worktrees: one plan belongs to one change workspace, so
work spanning two of them is two plans, and one plan across both would be a different
feature.

**Recording the current shape early is the point; predicting the final shape is not.** The
placeholder prevents drift during investigation. It selects the smallest useful shaping
steps and changes as evidence changes. Formal implementation steps are added only when the
selected solution makes them knowable. Validation requires only what the current phase can
honestly know.

**Plans never store liveness.** A step names its owning agent; whether that agent is alive
is always read from the agent, never copied onto the step. Two records both claiming to
know who is working will disagree.

---

## When a plan exists

**A plan exists when work needs shaping before implementation.** Uncertain bugs,
cross-cutting changes, new features with unresolved choices, migrations or work needing
meaningful coordination begin a lightweight plan. Clear bounded changes, research,
questions, advice and review-only work do not.

**Shaping lives inside the plan.** The first task owner creates it before investigation can
diverge. It initially records only the objective, known constraints, open questions and
justified shaping steps. It must not guess files, implementation steps, tests, agents or
solutions not yet knowable.

**The plan evolves in place.** Investigation, root cause, technology tradeoffs, solution
design, optional fresh plan review and formal execution planning expand the same record.
Completed shaping work remains in its history while human-facing views may summarize it.

**Direct work has no plan.** If it discovers a material design choice, widened scope or
unexpected risk, it creates the shaped plan before continuing implementation. The absence
of a plan is not itself a defect.

**The first task owner creates the plan.** It may browse and copy a template when useful,
and may give bounded shape ownership to a planning specialist. The specialist challenges
feasibility, scope, decomposition and verification, expands the existing plan, then returns
ownership. It does not automatically spawn a fresh main or remain open for the plan's
lifetime.

**Templates are browsable, and one is found rather than named up front.** Nobody has to
know at the start of a job that a template exists for it: the plan owner looks once the work is
shaped, and takes one if it fits.

**A dispatcher is never involved in a plan.** It relays work and orchestrates the creation
of agents and worktrees; it does not plan, own, tick or read one.

**A plan created when direct work changes path starts from the current truth.** Prior direct
work is referenced honestly rather than invented as completed plan steps. Required shaping
and approval still precede further tracked implementation.

---

## Steps

**Steps compose in the library, not in a plan.** A library step may be defined as several
steps, so long as nothing is circular, and naming it puts those steps in the plan. What a
plan holds is always flat: no step contains another, because a step that did would be a plan
by another name, and its parts would fail the granularity test below by sharing one owner and
one context.

**Steps come from a library or are made on the fly.** Both are first class: a plan may name
a step that already exists and invent the rest as it goes.

**A named step is a link to its definition and its own object besides.** The plan holds the
name and everything belonging to this run — progress, owner, try count, notes, checkpoints,
its `output` — while the library holds only the definition. Editing a library step therefore
reaches every plan naming it, including live ones, which is the point: there is little about
a definition to change once it exists, and steps are units.

**A plan owner that wants a variant writes an on-the-fly step, never an edited link.** There is no
forking a library step for one job. This is also what a template copy carries: copying a
template copies the plan, and a named step inside it stays a name.

**A step may be word-only.** Nothing has to be defined behind it; the name alone is worth
having.

**Every step carries a display name — a short label the board draws in place of the full one
— and so does the plan.** A name is a sentence and a board cell is a few columns, so a step
whose name is "list every claim the document makes about the code" is authored with a display
like "list claims" — short but readable, abbreviating and cutting words the title already
implies. It is required, not optional: without one the board drew the name clipped mid-clause,
and the informative half was the half cut. It pairs with the name exactly: a named step's
display name lives in its definition and an edit reaches every plan naming it, an on-the-fly
step's lives on the step. The plan carries its own display too — longer, since it owns the
whole header line — and the board draws it in place of the title, falling back to the title
when there is none. There is no per-cell clip any more: display names are short by
construction, and the only clip left is the board's own from the right when the pane is
narrow. This is the same "the board is a picture and `show` is the full listing" split the
board already makes — the display name is what makes a picture of a real plan legible rather
than a row of ellipses.

**Effort and scale flex inside a step; the shape does not.** The same step covers a trivial
change and a large one.

**A preset may exist only for steps to name**, rather than being offered to spawns at
all — Change Approval's bullet format is one.

**The agent is the interpreter.** There is no compiler, and — `strategy` aside — no schema
to satisfy: a step carries whatever fields are useful and an agent reads them. Inputs if it
wants inputs, a field saying `vibe = bad` if that is what conveys it. None of that needs
specifying in advance, and specifying it is how this turns into a workflow engine.

**One field is shaped, and it is advice.** A step's `strategy` — its recommended
orchestration — has its field names and value types fixed by
`defaults/plugins/plans/strategy.schema.json`, and `validate` reports what does not match
while keeping whatever it found. What is pinned is the REPRESENTATION of a recommendation:
nothing reads a strategy and acts on it, and no check asks whether an agent followed one.
Every other field on a step stays open.

**A step may carry a command**, which may live in a script shipped alongside it. How it gets
called is settled when it comes up. The agent owning the step is what
runs it — nothing watches a plan and fires commands, because that would be the evaluator this
design does not have. What the step buys is that the closing act is written down instead of
remembered, which is why the last agent standing gets closed at all.

**A step is complete only after its outcome succeeds.** A self-terminating cleanup command
records the intended action through runtime before it removes the last agent, and runtime
records success when it can establish it. Pre-ticking an unattempted merge or cleanup would
turn a concrete failure into false completion. Any action whose success cannot be confirmed
remains visibly unfinished.

**No conditionals, and no control flow.** Whatever branching a job needs, the agent does.

**Presets are the field that always applies; a role only matters when a step spawns a new
agent.** A word-only step has neither, and that is fine. A role is what
an agent is, fixed when it is spawned. A preset is behaviour injected into one, and can be
applied to an agent already running. A step has to work both ways — spawned into a new
agent, or applied inside the agent already there — so the preset is the part that always
works and the role is a hint used only on the spawning path.

**A step never restates what a role already says.** Steps describe the work, roles describe
the agent. The same preset named twice is applied once, but overlapping wording is not
something to detect and strip: if a step needs to repeat its role, one of the two is wrong.
Where they genuinely conflict the step wins, being the more specific — though a conflict is
a bug in the files rather than a mechanism to rely on.

**Who runs a step is the task owner's choice unless the step defines an independence or
specialization requirement.** A step does not imply a spawn. The main agent may own many
consecutive steps, and planning or review may happen inside an already-running specialist
where independence is not required.

### What makes something a step

Two criteria, held in tension. A step is what satisfies both; neither is the answer alone.

- **It is one coherent outcome with a meaningful exit condition.** Several related file
  edits, commands or checks are not separate steps merely because they can be listed.
- **Separating it helps ownership, sequencing, review or recovery.** Different agents are
  one possible reason, not the test. A main agent may own the whole plan without making its
  steps invalid.

Granularity is a balance, and four costs are all real: specific and structured against
flexible and changeable, how it looks when displayed, how many tool calls it takes, and
that finer steps mean more chances to drift out of sync.

**Having no plan and having no step are different things.** Inside a plan, what becomes a
step is settled by the two criteria above — so an agent's children are not automatically
steps, and a plan is never a mirror of the agent tree.

---

## Progress

**Nothing ticks automatically.** `sb done` does not mark a step complete.

**A step shows two things and only one of them is ticked.** Its progress is set by the plan
owner or owning agent. Its owner's status — working, blocked — is read from the agent and
never set on the step.

**The plan owner assigns every step its owner.** The main agent may own the implementation
itself. If an owner dies, the current plan owner explicitly reassigns or recovers the step.

**Plan ownership and agent-tree parentage are different.** A step owner need not be the plan
owner's child. Liveness is read from the agent when the plan is displayed, while ownership
changes are explicit durable writes.

**Reassigning a step means closing the agent it came from.** Until a core verb can tell a
running agent anything, the old owner is never told it lost the step — and a stalled agent
that recovers, or a closed one that is restored, resumes believing it still owns the work.
Two agents in one worktree on one step is the collision nothing prevents.

**A lost plan owner does not invalidate the plan or its approvals.** A new task owner may be
explicitly assigned through the same serialized write path. The record identifies the
handoff and preserves completed shaping, approval and evidence; it does not manufacture a
replacement plan or skipped duplicate gates.

**On a delegated owner's report the task owner decides whether the outcome is complete.** It
uses the report and evidence and does not spawn another agent merely to confirm ordinary
progress.

**A child may tick its own step when confident, and hand the decision up when not.** The
moment to say so is when it calls `sb done`. Prompting it there means decorating a core
verb, which is deferred, so until then it is told at spawn.

**A step carries a try count, and a count above one is rendered.** Rework is a step
re-entering progress after being done — a failed review sends its step back — so repetition
is a number on the step rather than an edge in the graph.

**Ticks downstream of a re-entered step may be stale, and the plan owner decides which to reopen.**
Nothing un-ticks them by itself. A review that passed against code since rewritten is the
case that matters: leaving it ticked merges work nothing reviewed, and reopening everything
reachable throws away a day of good review. Which is why it is a judgement rather than a
rule, and why the plan owner has to be told it is one.

**No visit ceiling on rework.** A loop that will not converge ends the way everything else
does: the task owner eventually blocks. Being agent-driven is what makes a ceiling unnecessary.

**Rework after a gate is rejected is handled by the plan owner.** It may edit the plan
to add a fix step between two reviews, or simply run the review a second time. Neither breaks
anything, which is what matters for the running job. It does matter to the record, since one
leaves a try count and the other leaves a step that looks like a recurring pattern — so a
plan owner adding a step for rework says so in the changelog, and the analysis pass can tell the
two apart.

---

## Gates

**A gate is a step's exit condition, not a step of its own.** Every step has a condition
saying when it is complete; a gate is one that requires a human. So a design step ending in
"no implementation until he confirms" needs no second step for the confirmation, and
collapsing a step into the agent before it never loses the gate.

**The step is the thing with a name, and everything is said about the step.** A gate is not
addressable and never appears on its own: what shows on the board, what carries a skip and
its reason, and what an obligation attaches to is always the step whose exit condition the
gate is. A step is either complete or skipped, never both.

**A plan is never a control surface.** Andrew talks only to agents and never edits a plan.
Where a gate needs him the owning agent blocks, the step shows its owner blocked, and
answering the agent clears both. There is no unblocking a gate through the plan.

**The task owner carries a plan gate.** A delegated specialist reports its result to the
task owner; it does not become the permanent human channel for the whole change. Only one
agent waits on Andrew for one question, and that agent remains accountable for the next
transition after the answer.

**A gate's message may show the plan** where showing it helps, **and may name the other plan
this job is part of.** Plans stay isolated as state; that isolation must not reach the message,
or a change spanning two worktrees asks him to approve half a contract twice with the sentence
that would explain it ruled out.

**Human gates follow unresolved human authority, not a fixed count.** Shaped work has one
combined pre-implementation approval covering the problem or specification, selected
solution, formal plan and change contract. Landing later requires approval of the current
reviewed result. Direct work has no pre-implementation change-approval ceremony; its bounded
human request is the authorization. Extra gates exist only for a real decision agents cannot
make.

### Change Approval

**Change Approval is the shaped path's combined approval.** It follows required
investigation, solution design, formal planning and any warranted fresh plan review. It
covers the problem or feature specification, selected solution and tradeoffs, execution
plan, and high-level change contract in one interaction.

After the work is shaped and before any of it is implemented, the owning agent writes the
summary in its own chat — that is what he reads — and blocks with one short line naming what
it is waiting for. Its whole value is that nothing has been built yet.

**Two sections, in this order.** First **Scope & Objectives**: the scope is the agent's to
derive, what the work covers; the objectives are his, inferred from what he actually asked
for and restated so nothing he wanted goes missing. Second the **Change Contract**,
bulletpointed and high-level only — no implementation detail, no jargon, nested where the
nesting carries meaning. It is ordered for reading rather than for building: he goes down it
once, and should finish it knowing what the change looks like at a high level, what behaviour
changes, and which modules are touched, with little context on this codebase.

The format is fixed: bullets indented with `-`, then `---`, then `-----`. Bullets run short —
around twelve words, and up to about twenty where the point is genuinely tangled, which
matches the standing human-facing rule rather than tightening it. A change contract is where
the conditions and fallbacks live, so it is the case that needs the loose end of the range:
one proposition with three conditions should not have to fragment into four bullets that each
lose which condition governs which branch.

**A gate message may point at a fuller artifact.** Anything that does not fit the format is
referenced rather than crammed into it, so the short version is never the only version
available to him.

**He answers approve, or rejects with changes.** A rejection sends the agent back to the
design work and not to the wording: re-derive the scope, re-infer the objectives, rebuild the
contract, and only then summarise and block again. Rewording a summary he rejected and
re-blocking answers a different question from the one he asked. Each time round bumps the
step's try count and puts its progress back to `open` — the ordinary rework relief every step
has — so the loop is recorded rather than invisible.

**A gate's pending question is visible in the record.** Reaching it blocks through the
owning agent, and answering clears the waiting state. The durable approval record remains
after the transient question is gone, so a completed gate is neither still waiting nor
dependent on prose hidden in a definition.

**Approval is durable and identity-bound.** The full approved content, plan revision and
change-contract digest, approver and time are recorded before the step is complete.
Implementation steps depend on that approved plan state. Rejection returns to the earliest
affected shaping work rather than merely rewording the gate message.

**Direct changes do not add and skip Change Approval.** The step is absent because the path
does not use it. Independent implementation review and landing approval still apply through
the change record.

### Independent review

**Plan review is optional; implementation review is universal for landing work.** A fresh
plan reviewer challenges the design only when planning risk warrants it. A fresh
implementation reviewer always examines the completed verified result before PR creation,
and its result lives on the change record so direct work receives the same protection.

Implementation review records the independent reviewer, target commit or artifact, major
issues returned to the main agent, safe minor fixes applied by the reviewer, resulting
identity, and whether any major issue remains. Nits are omitted. A major finding has to be
defensible by a reachable live path, likelihood, impact and remediation value.

### Human action and landing approval

**Human action is prepared before the PR opens.** It contains only checks or decisions no
agent covered, or an explicit statement that none remain. It is the first section of the
authoritative PR comment.

**Landing approval covers the current reviewed head.** Approval, reviewed result, evidence
and PR head are compared once when landing begins. An unexpected material change pauses and
explains what became stale. Applicable approval proceeds directly to merge without routine
retesting, rebuilding or re-review.

**Failure remains specific and unfinished.** Relevant red checks, cancellation, merge
failure or cleanup failure are reported as the exact remaining action. Known baseline or
infrastructure failures may be distinguished with evidence. Routine post-approval landing
and cleanup do not create additional questions.

---

## What a plan must contain

Validation follows the plan's current phase. A shaping placeholder must carry its objective,
known constraints, open questions and honest deps; it does not need implementation detail.
An approval-ready plan must carry the selected solution, tradeoffs, execution steps,
verification and change contract. Execution cannot be presented as sanctioned until that
state is approved.

**An obliged step is added automatically and may be skipped, never omitted, inside the path
where it applies.** Direct work does not receive shaped-path obligations — there is no
change-approval on a direct change, so nothing obliges a review off it. Implementation,
review, the human checklist, the PR and merge are instead the fixed execution+landing
skeleton a direct change record is born with: the same step vocabulary as a shaped plan,
minus the shaping half, with the review and landing evidence recorded on the change record.

What this buys is that **a skip is a state rather than an absence**. An omitted step is
invisible; a skipped one is on the board with its reason, so a bad call can be seen and
questioned. A gate that could not be skipped would simply be routed around by never
creating the step, which is enforcement in appearance only.

---

## Visibility

**A plan is displayable** — its current structure, and who is working on what.

**Agents receive the context their outcome requires.** A bounded specialist need not receive
the full plan, but its brief includes enough objective, constraints, decisions and acceptance
context to reason independently. A main agent and plan owner receive the whole current
record. Context is selected by responsibility, not removed merely because the role is
`worker`.

**So a step applied to an agent already running is deferred with them.** Until a core verb
carries it, a step reaches its owner at spawn and nowhere else, which means the in-place path
— confirmation inside the designer agent rather than in a new one — waits for the same work.

---

## Records, and what they are for

**Live agent and worktree condition is read rather than copied.** A plan stores identity and
ownership, while current liveness comes from Switchboard. Workflow phase, approval,
evidence, review and landing outcome are durable change facts and are stored rather than
inferred from liveness.

**A plan whose worktree is gone with steps still open is abandoned, not finished.** The sweep
deletes a worktree on its own gates, which cannot see a plan and are not going to learn to.
So the difference has to be visible in the record afterwards, or the analysis pass reads a
job that fell apart as a job that went well — a second, mechanical source of the bias the
known limitations already name.

**A plan stops being live with its worktree; the record of it is kept.** Plans are plain
text and losing one is cheap — nothing about it compares to losing a worktree or an agent —
so they are not deleted. Cleanup means dropping out of the UI and no longer counting as
active, never erasing. When every agent on a worktree is closed the plan goes dormant and
is restored when they are; when the worktree goes, the plan stops being live and its record
survives.

**The changelog is written by the command; the agent supplies the reason.** It is
append-only. An agent appending by hand would be editing the plan, which is the one thing the
single write path exists to prevent, and it would also be the part of a plan most easily
forgotten. A plan is flexible
and gets reshaped as the job runs, and without this the record keeps only the final shape —
losing the story of what was split, renamed or dropped, which is exactly what the analysis
pass is looking for.

**The shape is loose and JSON-like** — notes, and whatever further columns turn out to be
worth carrying.

**A plan carries enough notes to be worth analysing later.** Its value after the job is as
evidence of how the work actually ran, so it is written to be read cold.

**Anyone may write notes, and two moments are expected:** the task owner as it creates the plan,
and whoever finishes a step as it is ticked.

**Steps carry references to briefs and artifacts as checkpoints** — references, never
content. Step output may be content, but the PR renderer selects information by purpose; it
does not dump every output under one generic heading.

**Change-record facts are structured and identity-bound.** Approval names the plan revision
and contract digest it covers. Evidence names its commit, environment and result. Review
names its independent reviewer, target and applied fixes. Landing approval names the current
reviewed PR head. Legacy records remain readable but never claim identities they did not
store.

**The authoritative PR comment is human-first and stable.** One hidden marker identifies one
idempotently updated comment. It renders, in order: `What you need to do`; `What changed and
why`; `Agent evidence`; and collapsed `Detailed record`. A direct change renders without an
empty plan, and a shaped change includes its plan only in the detailed record.

**A recurring analysis pass reads the records and proposes what to add.** Something like a
skill run every so often — analyse switchboard usage — that looks over past jobs and says
what should become a new step, template, preset, role, optimisation or piece of tooling.
This is what saving the records buys, and why they must be worth reading cold.

**The catalogue is a mix, and grows from use.** A few steps are fixed and named, and
everything else is created by the plan owner at plan time. What should be
promoted into the fixed part, and what a default template should contain, is read off real
runs after a while rather than decided up front. The system must work with the catalogue
almost empty.

---

## Shipping it

**Plans and change records ship through one plugin package but remain separate concepts.**
Disabling shaped planning stops plan creation; it does not remove the direct path's review,
human-action or landing record. Universal role and protocol text points to path-independent
change behavior and does not depend on the plugin guide to restate it.

**Runtime support and prompt cuts ship together.** A prompt never promises a waiting state,
identity field, path or rendering behavior before the runtime has it, and old prose is
removed in the same coordinated change rather than left to compete with the new workflow.

**The board needs a hook for it.** Rendering plans under their worktree is the one thing the
plugin cannot do from outside, so the board grows an extension point rather than knowledge
of plans.

**Everything else lives in the plugin** — its commands, its state, and the prompt text that
tells agents plans exist.

---

## Known limitations

Named because they are real and accepted for now, not because they are solved.

**Planless landing work is visible through its change record.** Research, discussion,
questions and scouting that never become a change remain intentionally unrecorded as plans.
No declaration ceremony is required for them.

**Step sets from different plan owners are not really comparable.** Granularity is a judgement,
so two owners splitting the same job into three coarse steps and twelve fine ones produce
records that count differently — while the analysis pass exists to count what recurs. Library
steps are the part that does compare, since a name means the same thing wherever it appears,
and that is an argument for the catalogue growing rather than a reason to fix granularity by
rule.

**The granularity criteria are for coherent outcomes, and do not invalidate a plan later.**
If one agent owns several consecutive steps, that is ordinary. The plan owner may merge
steps that prove meaningless separately, keeping their history, or leave them when the
boundaries still help sequencing and recovery.

**The record is biased toward jobs that went well.** Ticking and note-writing are voluntary
acts by an agent that is still on top of its job. A run that derails stops being written
down, so the analysis pass reads a sample thinnest in exactly the runs it exists to find.
Accepted because nothing else is load-bearing on the records: the cost is a weaker analysis
pass, not a broken job.

---

## Not doing

**No stop hook for these gates, for now.** The steps are not solid or clear enough to
enforce mechanically at turn end, and building that first would be getting ahead of the
design.

**The `todo` plugin is unrelated and retired.** Not the ancestor of this, and not to be
grown into it.

---

## Deferred

Confirmed as deferred — not open questions, but things deliberately left until later.

**Additional PR-description style beyond the human-first change comment.** The description
still summarizes the system problem, solution and verification; further repository-specific
style is not part of this design.

**Whether step checkpoints supersede the brief mechanism on restore.** To be investigated
rather than assumed.
