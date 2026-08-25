# Plans, steps and templates

How work is structured while it runs, and how that structure is read back afterwards to
improve the system.

**Only Andrew edits this file.** Every line is something he has confirmed. No agent adds,
reworks or "improves" an entry, and nothing arrives here by inference — not from the code,
not from a conclusion another agent reached, and not because it seems to follow. Absence is
not a decision: what is missing is undecided rather than free. Held to the same bar as
`DESIGN-TRUTH.md`, which remains the authority wherever the two meet.

---

## Why this exists

What agents do, how they do it, and how deep verification goes each time is disorganised.
The recurring moments of a job — design, design review, implementation review, merge review
and the like — get reinvented on every task. Structuring them is the fix. Those four are
examples rather than a required set: this can ship with no gates at all and still be worth
having.

Today everything asks Andrew, three times over: whether to create the PR, whether to merge,
whether to clean up. Each is a decision he is made to take one at a time. Removing them is a
large part of the point. Two of those are the system's; the first is this repo's own house
rule, and could be loosened today by editing one line — worth knowing before building
anything.

**The two gates are a ceiling, not a floor.** Today's three approvals are guaranteed. A gate
is a step's exit condition and a step may be skipped with a reason, so under this design he
is asked at most twice and possibly not at all. The exchange is that a skip is recorded and
visible where a missing approval never was — which is a duty to look rather than a promise to
be asked, and he accepts it deliberately.

**Cost per decision goes up as the count goes down, and that is the trade.** Today's three
sit at the end of a job, are close to yes or no, and never need him to understand the fix.
Change Approval lands mid-job, asks him to judge a change contract before any code
exists, and holds the lead and everything under it while he thinks. Catching a wrong design
before it is built is worth that; it is a trade rather than a removal.

It is also how the work process becomes legible, though that half is a bet rather than a
delivery. What lands immediately is that a running job can be looked at — its shape, and who
is on what. Everything beyond that is addressed to a later reader: a finished plan as evidence
of how a job actually ran, and an analysis pass that reads many of them. The known limitations
below concede three defects that all land on that same future reader, so it is worth building
and is not yet worth leaning on.

---

## Vocabulary

Three words. `task` was not available for any of them: it is already the agent's own task —
its store column, its `sb delegate` argument, and the protocol's "the task you were given".
Neither was `preset`, which is already prompt text injected at spawn.

`plan` is not perfectly clear either. The lead role already says "Plan, then re-plan", of a
plan a lead holds in its head and never writes down. That is the same activity, which is why
the word was taken — but a lead can read the two as already satisfied, so the lead role has
to say plainly that the plan is now a thing it writes.

**Step** — the unit. What an agent owns, what gets ticked, what carries a try count and
notes.

**Plan** — a group of steps, with an identity, a worktree, a changelog and a kept record.
The steps are the substance; the rest is what makes it a thing that can be found, shown and
read back.

**Template** — a preconfigured plan, in the ordinary sense of the word. A starting point
you can do as you like with: a plan may be a template plus whatever else the job needs, and
nothing holds a plan to the shape it started from. Using one is copy and paste — the copy is
edited afterwards if it needs it, and nothing links it back to what it came from.

---

## Plans

A plan is the live state of one job: what is being done, by whom, and what is left.

**A plan is a DAG.** One step may fan out to several, and those may join back into one.

**A join waits because the lead does not start it.** Nothing enforces the wait — the lead
holding the plan is what reads the shape and acts on it, which is what being interpreted
rather than executed means. Fan-out and join are how the lead is told what may run at once
and what must not; they are not control flow something else runs.

**Redoing work is not an edge.** Where part of a job must be redone, the lead or sole
worker goes back to it. The graph stays acyclic, and the flexibility comes from it being
agent-driven rather than modelled.

**Semi-structured and changeable at any time.** More structured than a todo list, less
rigid than a fixed workflow. Not Claude's internal todos, not a flat list.

**Changed through the plugin's commands, not by editing the file.** Being interpreted rather
than executed is about what a plan *means*; it is still written through one door. Obliged
steps are added on that path, and a plan hand-edited around it gets none of them.

**A command changes the steps it names, never the whole plan at once.** Two agents ticking
different steps is already safe, but a lead re-planning is a read, a think and a write, and a
tick landing in that gap would be overwritten by a wholesale rewrite — leaving the changelog
showing a tick the plan does not have.

**Interpreted, never executed.** A plan is read and acted on by an agent, not run by a
machine. Nothing evaluates it, and there is no workflow engine around it.

**One plan per job.** A lead may define one plan or several, or collapse everything into a
single plan. Both must work gracefully, since the union of the steps involved is much the
same either way — a design that does not handle both is wrong.

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
A plan never spans two worktrees: everything below a lead shares that lead's worktree, so
work spanning two of them is two plans, and one plan across both would be a different
feature.

**Defining a plan upfront is the point, not overhead.** More effort can be spent getting it
right when it is defined early, and the payoff is that an agent reaching a step already
knows what that step pulls in.

**Plans never store liveness.** A step names its owning agent; whether that agent is alive
is always read from the agent, never copied onto the step. Two records both claiming to
know who is working will disagree.

---

## When a plan exists

**A plan exists exactly when the work is heading for a change that will land.** Everything
else runs without one: investigation, questions, scouting, review-only work, anything a
single agent answers and reports, and everything a dispatcher does. Small is not exempt — a
one-line docs change bound for a PR gets a plan, only a short one.

**Investigation produces a plan rather than living inside one.** The plan is created once
the outcome is known and there is a clear path from what was found through to a merged PR.
Investigation still appears as a step when it is one piece of an already-shaped job.

**There is a plan-making instruction for the lead**, explaining clearly how all of this is
done. It is read when the job comes up rather than carried on every spawn.

**The trigger travels at spawn, even though the instruction does not.** Every agent is told
the one line that makes the lookup happen — if your work is heading for a change that will
land, go and read the plan-making instruction. Knowing plans exist is not the same as knowing
when to make one, and an agent that has to infer the second will not. This is the difference
from the adversarial procedure, where a human says the words that start it.

**The worktree's owner creates the plan and chooses the template** — the lead of that
worktree, or the sole worker where there is no lead. A sole worker counts as a lead here, and
its role has to say so: the worker role otherwise tells it to carry one task and do nothing
beyond it, which reads as a reason not to.

**Templates are browsable, and one is found rather than named up front.** Nobody has to
know at the start of a job that a template exists for it: the lead looks once the work is
shaped, and takes one if it fits.

**A dispatcher is never involved in a plan.** It relays work and orchestrates the creation
of agents and worktrees; it does not plan, own, tick or read one.

**A plan may be created with some of its steps already done.** Nothing requires one to
start empty — but not a step whose exit condition is a gate. A gate exists to be reached
before the work it guards, so a plan authored after the fact does not get to mark it already
passed. If the work is already past that point, that step is skipped with a reason, which is
visible, rather than born complete, which is not.

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

**A lead that wants a variant writes an on-the-fly step, never an edited link.** There is no
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

**A step is ticked before its command runs, never after.** The agent that tears down its own
workspace is gone the instant it succeeds, so a teardown step ticked afterwards is never
ticked. Nothing enforces the order; it is an instruction, and the reason for it is that the
tick has to outlive the agent. What this buys is that "merge, clean up, delete the
worktree, close the agents" stops being five things an agent has to remember — and it is the
only way the last agent standing gets closed at all.

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

**Who runs a step is the lead's choice unless the step defines it.** A step need not spawn
an agent at all: design-review confirmation, for example, may happen inside the designer
agent rather than in a new one.

### What makes something a step

Two criteria, held in tension. A step is what satisfies both; neither is the answer alone.

- **It can be fully owned by one accountable agent.** Owning it may mean coordinating
  others — an adversarial review is fully owned by the review lead running its own agents
  underneath, and that counts as one owner.
- **Its neighbours plausibly go to different agents.** If a step and the one after it, or a
  run of three, would sensibly be done by the same agent in the same context, the split is
  too fine and they are one step.

Granularity is a balance, and four costs are all real: specific and structured against
flexible and changeable, how it looks when displayed, how many tool calls it takes, and
that finer steps mean more chances to drift out of sync.

**Having no plan and having no step are different things.** Inside a plan, what becomes a
step is settled by the two criteria above — so a lead's children are not automatically
steps, and a plan is never a mirror of the agent tree.

---

## Progress

**Nothing ticks automatically.** `sb done` does not mark a step complete.

**A step shows two things and only one of them is ticked.** Its progress is set by a lead
or the owning agent. Its owner's status — working, blocked — is read from the agent and
never set on the step.

**The lead assigns every step its owner.** If an owner dies the lead dispatches a
replacement and assigns the step to it, the same act as assigning it the first time.

**The lead learns of a death by reading the plan, not by being told.** A step's owner need
not be the lead's own child — an adversarial review is owned by the review lead beneath it —
and switchboard's own failure notice goes to the dead agent's parent in the agent tree, which
may be neither. Since liveness is read off the agent whenever the plan is displayed, the lead
sees a dead owner the moment it looks, and nothing has to be routed to it.

**Reassigning a step means closing the agent it came from.** Until a core verb can tell a
running agent anything, the old owner is never told it lost the step — and a stalled agent
that recovers, or a closed one that is restored, resumes believing it still owns the work.
Two agents in one worktree on one step is the collision nothing prevents.

**If the lead itself dies, the plan dies with it.** Nobody else can carry it: the agent above
is a dispatcher, and dispatchers are never involved in plans. This is accepted rather than
solved — but what Andrew does about it is written down rather than left to the moment. He
starts a new lead, which makes a new plan, and the gates he has already cleared are skipped
with the reason naming the plan that cleared them. He never edits a plan to recover one, since
that would be the second write path this design exists without.

**On a child's report the lead verifies progress and decides whether to tick.** Quickly,
from the child's report. It does not spawn another agent to verify progress unless that is
genuinely needed.

**A child may tick its own step when confident, and hand the decision up when not.** The
moment to say so is when it calls `sb done`. Prompting it there means decorating a core
verb, which is deferred, so until then it is told at spawn.

**A step carries a try count, and a count above one is rendered.** Rework is a step
re-entering progress after being done — a failed review sends its step back — so repetition
is a number on the step rather than an edge in the graph.

**Ticks downstream of a re-entered step are stale, and the lead decides which to reopen.**
Nothing un-ticks them by itself. A review that passed against code since rewritten is the
case that matters: leaving it ticked merges work nothing reviewed, and reopening everything
reachable throws away a day of good review. Which is why it is a judgement rather than a
rule, and why the lead has to be told it is one.

**No visit ceiling on rework.** A loop that will not converge ends the way everything else
does: the lead eventually blocks. Being agent-driven is what makes a ceiling unnecessary.

**Rework after a gate is rejected is handled however the lead likes.** It may edit the plan
to add a fix step between two reviews, or simply run the review a second time. Neither breaks
anything, which is what matters for the running job. It does matter to the record, since one
leaves a try count and the other leaves a step that looks like a recurring pattern — so a
lead adding a step for rework says so in the changelog, and the analysis pass can tell the
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

**A child at a gate does not finish the lead.** The protocol has a parent report done and
step aside when a child blocks, so that only one agent waits on a person. That is right for a
child's own question and wrong here: a gate is the plan's, and the lead is what assigns the
next step once it clears. So the lead stays until its plan is complete, and says who is
waiting without standing down.

**A gate's message may show the plan** where showing it helps, **and may name the other plan
this job is part of.** Plans stay isolated as state; that isolation must not reach the message,
or a change spanning two worktrees asks him to approve half a contract twice with the sentence
that would explain it ruled out.

**Two blocks is the shape of a job, not a ceiling.** A plan that lands a change has a
Change Approval gate and a merge gate, and everything else resolves without him. Nothing
enforces a count — several plans on one worktree means several of each, and that is fine.

### Change Approval

**Change Approval is the design gate.** There is one gate before implementation, not two: it
supersedes and replaces the older "design gate" everywhere, and it lives in the step library
rather than in convention, so a plan gets it by naming it.

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

**The gate is prose, not a field.** The step's definition says it is a gate and says what the
block is for, the way the merge step already does; nothing writes a string into the step's
`gate` field. That is deliberate rather than an omission: a gate left on a step that has been
ticked is a defect the plan draws red, and Change Approval's whole lifecycle ends in a tick.
The cost is that `show` prints no gate line for the step, and a reader has to know the
definition.

**The approved text is carried forward.** On approval the agent puts the full approved text —
both sections, entire — in the step's `output`, and only then ticks. `output` is the one step
field that is content rather than a reference, and it is that because it is dumped: the PR
comment carries what he approved verbatim instead of a fresh re-summary of it.

**It obliges `review`, and `create-pr` obliges it.** So naming `create-pr` lands all three in
one act, and the contract he approved is checked against what was actually built before the
PR is opened. A `review` standing alone, in a plan with no Change Approval step, is a plain
review and nothing is missing from it. Change Approval is an early root of the plan whatever
order it was added in — an obligation lands a step beside its obliger, so its deps have to be
made to say so.

**A trivially small change may skip this step, with the reason recorded.** The relief is the
ordinary one every step has, and it is named here so nobody has to assemble it from three
sections: a behavioural contract for a typo is a block nobody wants.

### The merge gate

The gate creates the PR and writes the description. He is not asked whether to create it.

Testing steps are given only when actually needed — anything the agent has already tested
does not need him, and asking wastes his time, his effort and his reading.

The review-and-review-again behavioural gate has been run by this point. The message mimics
Change Approval: concise, simply explained.

Once he approves, everything else happens automatically — merge, cleanup, delete worktrees,
close agents. No further questions **means no routine ones**: if any part of that chain fails
— the merge conflicts, checks are red, a teardown does not complete — the agent blocks. The
approval covers the routine path, and it is given before the merge is attempted, so the
failure case is the one thing it cannot have covered.

### Both gates

Neither is end to end, so both are step-sized rather than template-sized, and each may turn
out to be one step or several — each being a step whose exit condition is a gate. Both are general enough for any and all PRs. Every agent runs them for
any PR-creating task, and agents and leads should recognise them and adopt them when the
work calls for it.

These replace what came before rather than sitting beside it. Where the scattered prose
about approval, pushing and merging conflicts with a gate, the gate is the authority and
the prose is cut back to a pointer. `DESIGN-TRUTH.md`'s rule that almost none of the
human-facing guidance may become something to copy was an exaggeration and is set aside
here: a step may specify an output format exactly.

The lead role survives with cuts rather than a rewrite. Its planning is right up to the
point of implementation and needs trimming, not replacing — once the basic steps exist a
lead can and should plan around them, and the two should not conflict.

---

## What a plan must contain

There is logic around what a plan may contain; you cannot create just any plan. Creating a
PR, for example, obliges certain steps, and those guidelines are part of the design rather
than left to each agent.

**An obliged step is added automatically and may be skipped, never omitted.** Adding a
merge step brings its merge review with it. Skipping is allowed at the lead's or the
agent's discretion, with the reason recorded, and is expected to be rare and conservative —
a one-line docs change should not be reviewed as if it were a migration.

What this buys is that **a skip is a state rather than an absence**. An omitted step is
invisible; a skipped one is on the board with its reason, so a bad call can be seen and
questioned. A gate that could not be skipped would simply be routed around by never
creating the step, which is enforcement in appearance only.

---

## Visibility

**A plan is displayable** — its current structure, and who is working on what.

**Agents learn their step through output they already read**, never through a command they
have to remember. What they are told is asymmetric: a lead needs the plan, a worker needs
only its own step, so sending the whole plan to a worker is context spent for nothing. The
spawn prompt is the carrier for now; decorating the core verbs — a step line on `sb inbox`,
a prompt on `sb done`, a column on `sb status` — is deferred rather than dropped.

**So a step applied to an agent already running is deferred with them.** Until a core verb
carries it, a step reaches its owner at spawn and nowhere else, which means the in-place path
— confirmation inside the designer agent rather than in a new one — waits for the same work.

---

## Records, and what they are for

**Live, dormant and finished are read, never written.** Nothing tells a plugin that an agent
was closed, a worktree deleted or a session restored — there are no lifecycle hooks and the
sweep runs with nothing of the plugin's alive. So a plan stores which worktree it belongs to
and nothing about its own condition, exactly as it stores an owner's name and never its
liveness. Everything else is worked out when the plan is displayed.

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

**Anyone may write notes, and two moments are expected:** the lead as it creates the plan,
and whoever finishes a step as it is ticked.

**Steps carry references to briefs and artifacts as checkpoints** — references, never
content. The one exception is a step's `output`, which is content because the whole point of
it is being dumped: it is what the PR comment carries forward, and a reference does not dump.

**A recurring analysis pass reads the records and proposes what to add.** Something like a
skill run every so often — analyse switchboard usage — that looks over past jobs and says
what should become a new step, template, preset, role, optimisation or piece of tooling.
This is what saving the records buys, and why they must be worth reading cold.

**The catalogue is a mix, and grows from use.** A few steps are fixed and named — merge
review is one — and everything else is created by the lead at plan time. What should be
promoted into the fixed part, and what a default template should contain, is read off real
runs after a while rather than decided up front. The system must work with the catalogue
almost empty.

---

## Shipping it

**It ships as a plugin. Switching it off stops plans being made, and does not restore the
old prose.** Disabled means no agent is ever told plans exist, so none are made; deleting the
folder behaves like off and putting it back behaves like on. What does not come back is the
approval, push and merge guidance the gates replaced — that text is in the protocol and the
role files, not in the plugin, so once it is cut back to a pointer it stays cut. Off is
therefore today's behaviour minus that prose, which is a weaker promise than off being
identical, and is the honest one.

**The merge gate cannot ship before those cuts land.** Until they do, an agent running it
reads the gate telling it to merge and three separate texts telling it never to merge without
its parent — the protocol, the house rules and `DESIGN-TRUTH.md`. The last time an injected
instruction contradicted the protocol about pushing, four agents in one session resolved it
differently, some pushing and some handing the work back. Same change, or not yet.

**The board needs a hook for it.** Rendering plans under their worktree is the one thing the
plugin cannot do from outside, so the board grows an extension point rather than knowledge
of plans.

**Everything else lives in the plugin** — its commands, its state, and the prompt text that
tells agents plans exist.

---

## Known limitations

Named because they are real and accepted for now, not because they are solved.

**A plan that was never made is invisible, and stays that way.** The design is careful that a
skipped step is a state with a reason rather than an absence, and the same argument applies one
level up — a worktree whose owner decided no plan was needed looks exactly like one whose owner
never considered it. Recording a declared no-plan would close it and was considered; it is not
worth the ceremony on every investigation, question and scouting job that will never have a
plan. No plan means nothing to show.

**Step sets from different leads are not really comparable.** Granularity is a judgement,
so two leads splitting the same job into three coarse steps and twelve fine ones produce
records that count differently — while the analysis pass exists to count what recurs. Library
steps are the part that does compare, since a name means the same thing wherever it appears,
and that is an argument for the catalogue growing rather than a reason to fix granularity by
rule.

**The granularity criteria are for splitting, and do not invalidate a plan later.** If the
lead ends up handing three consecutive steps to one agent, the split was finer than it needed
to be and that is all. It may merge them, keeping the highest try count and both sets of
notes, or leave them; the plan is not wrong mid-run for having been split optimistically.

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

**What the PR description should contain.** "To his liking" is not yet specified, and it
does not block building the rest.

**Whether step checkpoints supersede the brief mechanism on restore.** To be investigated
rather than assumed.
