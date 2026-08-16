# Plans and steps — confirmed design

What Andrew has confirmed about plans, steps and templates — the layer that structures how
agents work and how that work is later analysed.
Same bar as `DESIGN-TRUTH.md`: only what he said, high-level, no implementation detail.
Nothing inferred, nothing proposed-but-unanswered.

Entry format: one short claim, plus the date it was confirmed. An entry marked **decided**
rather than confirmed is one Andrew asked to be settled rather than left open; it follows
from things he did confirm and is his to ratify or overturn on the final read.

---

## Why this layer exists

**What agents do, how they do it, and how deep verification goes each time is currently
disorganised.** The fix is structured steps rather than per-task prose, so the recurring
moments stop being reinvented on every job. The four named are design, design review,
implementation review and merge review. — confirmed 2026-08-16

**Right now everything asks him, three times over.** Whether to create the PR, whether to
merge, whether to clean up. Each of those is a decision he is being made to take one at a
time, and removing them is a large part of the point. — confirmed 2026-08-16

**These steps replace previous decisions, they do not sit beside them.** Where the
scattered prose about approval, pushing and merging conflicts with a step, the step is the
authority and the prose gets cut back to a pointer. — confirmed 2026-08-16

**The lead role survives with cuts rather than being rewritten.** Its planning is right up
to the point of implementation and needs trimming, not replacing: once the basic steps
exist, a lead can and should plan around them, and the two should not conflict. — confirmed
2026-08-16

**A human-facing output shape may be a template.** `DESIGN-TRUTH.md`'s rule that almost
none of the human-facing guidance may become something to copy was an exaggeration, and it
is set aside here. A step may specify an output format exactly. — confirmed 2026-08-16

---

## The two flagship steps

*Both are steps, not templates: neither is end to end, and each may turn out to be one step
or several. Both are general enough for any and all PRs, and every agent runs them for any
PR-creating task. Agents and leads should recognise these steps and adopt them when the
work calls for it. — confirmed 2026-08-16*

### Pre-implementation contract

**After planning and before implementing, the agent summarises the problem and the planned
behavioural contract of the fix.** — confirmed 2026-08-16

**Two sections, ordered step by step: what is causing the problem, and what the fix will
be.** Not necessarily a step-by-step capture of the fix itself — an ordered account for his
understanding is what is wanted. — confirmed 2026-08-16

**The format is fixed: bullets indented with `-`, then `---`, then `-----`, and each bullet
is twelve words at most.** — confirmed 2026-08-16

**Implementation begins only after he confirms.** — confirmed 2026-08-16

**Two blocks for a whole job, and no more: this one and the merge gate.** Everything else
resolves without him. — confirmed 2026-08-16

### Pre-merge gate

**The gate creates the PR and writes the description to his liking.** He is not asked
whether to create it. What "to his liking" means in content is deferred and does not block
building the rest. — confirmed 2026-08-16

**Testing steps are given only when actually needed.** Anything the agent has already
tested does not need him — asking is a waste of his time, his effort and his reading. —
confirmed 2026-08-16

**It mimics the pre-implementation contract: super concise, simply explained.** — confirmed
2026-08-16

**The review-and-review-again behavioural gate has been run by this point.** — confirmed
2026-08-16

**Once he approves, everything else happens automatically: merge, cleanup, delete
worktrees, close agents.** No further questions. — confirmed 2026-08-16

---

## The three words

*Named to collide with nothing else in the system. `task` in particular is already the
agent's own task — its store column, its `sb delegate` argument, and the protocol's "the
task you were given" — so it is not available for any of these. — confirmed 2026-08-16*

**A step is the unit.** It is what an agent owns, what gets ticked, and what carries a try
count and notes. — confirmed 2026-08-16

**A plan is a group of steps.** Nothing more than that; the DAG below is the shape a plan
takes. — confirmed 2026-08-16

**A template is a preset plan.** A plan may be a template plus whatever else that job needs,
so a template is a starting point rather than a container the plan has to stay inside. —
confirmed 2026-08-16

**A step may be word-only, with nothing defined behind it.** Undefined steps are fine and
expected — the name alone is worth having. — confirmed 2026-08-16

---

## Steps

**Steps compose: a step may itself be a combination of steps**, so long as nothing is
circular. — confirmed 2026-08-16

**Loosely a chain, not a workflow engine.** The composition is the point; the machinery
around it is not. — confirmed 2026-08-16

**Effort and scale flex inside a step; the shape does not.** The same step covers a trivial
change and a large one. — confirmed 2026-08-16

**There will be a lot of steps, and only a few are user- or agent-facing.** Most are
internal fragments composed into others. A step may be nothing more than an output format —
the `-` / `---` / `-----` bullet contract is itself a step. — confirmed 2026-08-16

**There is no fixed catalogue of steps yet, and one is not to be invented.** Plans are
saved and carry enough notes to be analysed, so what belongs in a catalogue — and what a
default template should contain — is read off real runs after a while rather than decided
up front. The system must work without one. This supersedes the earlier reading that steps
are named from a shared catalogue from the start; the two gates below are the exception,
being confirmed by name already. — confirmed 2026-08-16

**A step names presets always, and a role only when it spawns a new agent.** A role is what
an agent is, fixed when it is spawned; a preset is behaviour injected into one, and can be
applied to an agent already running. Since a step must work both ways — spawned into a new
agent, or applied inside the agent already there — the preset is the part that always
works, and the role is an optional hint used only on the spawning path. — decided
2026-08-16

**Where a role and a step overlap, the same preset named twice is applied once, and a step
never restates what a role already says.** Overlap of wording is not something to detect and
strip: if a step needs to repeat its role, either the step or the role is wrong. Steps
describe the work; roles describe the agent. Where the two genuinely conflict the step wins,
being the more specific of the two, but a conflict is a bug in the files rather than a
mechanism to rely on. — decided 2026-08-16

**Who runs a step is the lead's choice unless the step defines it.** A step is not required
to spawn an agent: design-review confirmation, for example, may happen inside the designer
agent rather than in a new one. — confirmed 2026-08-16

---

## Plans

**A plan is the run state: what is being done, by whom, and what is left.** Steps are
the static library; the plan is the per-job, mutable thing. A step can name a template,
which is what stops a step being forgotten. — confirmed 2026-08-16

**A plan is a DAG, not a tree.** One step may fan out to several and those may join back
into one, and a join waits for every branch feeding it. This supersedes the earlier reading
of it as a tree. — confirmed 2026-08-16

**Redoing work is not modelled as an edge.** Where part of the job must be redone, the lead
or sole worker simply goes back to it; the graph stays acyclic and the flexibility comes
from it being agent-driven. — confirmed 2026-08-16

**Semi-structured and changeable at any time — more structured than a todo list, less rigid
than a fixed workflow.** Not Claude's internal todos and not a flat list. This was in the
earliest braindump. — confirmed 2026-08-16

**This is an integral part of the system, though not load-bearing.** It is how the work
process itself can be looked back on and improved. — confirmed 2026-08-16

**A recurring analysis pass reads the saved records and proposes what to add.** Something
like a skill run every so often — analyse switchboard usage — that looks over past jobs and
says what should become a new step, template, preset, role, optimisation or piece of
tooling. This is the payoff that saving the records buys, and the reason they must be worth
reading cold. — confirmed 2026-08-16

**One plan per job, with agents attached to its steps.** A lead may define one plan or
several, or collapse everything into a single plan — both must work gracefully, because the
union of the steps involved is much the same either way. A setup that does not handle both
is wrong by design. — confirmed 2026-08-16

**Plans never store liveness.** A step names its owning agent; whether that agent is alive
is always read from the agent, never duplicated onto the step. Two records that both claim to
know who is working will disagree. — confirmed 2026-08-16

**A step carries a try count, and a count above one is rendered.** Rework is a step
re-entering progress after having been done — a review that fails sends its step back — so
repetition is a number on the step rather than an edge in the graph, and the plan stays
acyclic. — confirmed 2026-08-16

**No visit ceiling on rework.** A loop that will not converge ends the way everything else
does — the lead eventually blocks — so steps simply repeat until the work is done. Being
agent-driven is what makes the ceiling unnecessary. — confirmed 2026-08-16

**Losing a plan is cheap.** A plan is files or rows, and nothing about it compares to
losing a worktree or an agent, so its lifetime rules can stay loose. — confirmed 2026-08-16

**A plan stops being live with its worktree; the record of it is kept.** Plans are plain
text and nothing about losing one is expensive, so they are not deleted — cleanup means
dropping out of the UI and stopping being counted as active, never erasing. When every
agent on a worktree is closed the plan goes dormant and is restored when they are; when the
worktree goes, the plan stops being live but the record survives, because those records are
what the catalogue is later derived from. This supersedes the earlier "the plan goes with
it and does not come back". — confirmed 2026-08-16

**A plan carries enough notes to be worth analysing later.** Its value after the job is
evidence about how work actually ran, so it is written to be read cold. — confirmed
2026-08-16

**Steps carry references to briefs and artifacts as checkpoints — references, never
content.** Whether that supersedes the brief mechanism outright on restore is to be
investigated rather than assumed. — confirmed 2026-08-16

**A plan is never a control surface.** Andrew talks only to agents and never edits a plan:
where a gate needs him, the owning agent blocks, the step shows its owner blocked,
and answering the agent clears both. There is no unblocking a gate through the plan. —
confirmed 2026-08-16

**A step shows two different things and only one of them is ticked.** Its progress is set by
a lead or the owning agent; its owner's status — working, blocked — is read from the agent
and never set on the step. — decided 2026-08-16

**Defining the plan upfront is the point, not overhead.** More effort can be spent defining
it correctly when it is defined early, and the payoff is that on reaching a step the agent
already knows which presets that step pulls in. — confirmed 2026-08-16

**A plan is displayable: the current structure, and who is working on what.** — confirmed
2026-08-16

**A dispatcher is never involved in a plan.** It relays work and orchestrates the creation
of agents and worktrees; it does not plan, own, tick or read a plan. — confirmed 2026-08-16

**A plan always belongs to one worktree, and a worktree may hold several plans.** The board
therefore renders them inside the worktree grouping it already has, rather than in a section
of its own. A job is owned by a lead, and everything below a lead shares that lead's
worktree, so a job and a worktree are the same span. Work spanning two worktrees is
therefore two plans, and one plan spanning both would be a different feature than this. — decided 2026-08-16

**Agents learn their step through output they already read, never through a command they
have to remember.** What they are told is asymmetric: a lead needs the plan, and a worker
needs only its own step, so sending the plan to a worker is context spent for nothing. The
carriers are the places they already look — the spawn prompt, `sb inbox`, the response to
`sb done`, and the lead's own `sb status`. Nothing polls, and nothing new has to be run. —
decided 2026-08-16

**Granularity is a balance, and all four costs are real.** Specific and structured against
flexible and changeable; how it looks when displayed; how many tool calls it takes; and
that finer steps mean more chances to drift out of sync. — confirmed 2026-08-16

---

## What makes a step

**Two criteria, held in tension, and a step is what satisfies both.** They guard opposite
extremes and neither is the answer alone. — confirmed 2026-08-16

- **It can be fully owned by one accountable agent.** Owning it may mean coordinating
  others: an adversarial review is fully owned by the review lead running its own agents
  underneath, and that counts as one owner.
- **Its neighbours plausibly go to different agents.** If a step and the one after it — or
  a run of three — would sensibly be done by the same agent in the same context, the split
  is too fine and they are one step.

**A gate is a step's exit condition, not a step of its own.** Every step has a condition
that says when it is complete, and a gate is simply one that requires a human. So the
design step ending in "no implementation until he confirms" needs no second step for the
confirmation, and collapsing a step into the agent that precedes it never loses the gate. —
decided 2026-08-16

## Ticking off

**Nothing ticks automatically.** `sb done` does not mark a step complete. — confirmed
2026-08-16

**On a child's report the lead verifies progress and decides whether to tick.** It does
this quickly, from the child's report, and does not spawn another agent to verify progress
unless that is genuinely needed. — confirmed 2026-08-16

**A child may tick its own step when it is confident, and hand the decision up when it is
not.** The moment to tell it so is when it calls `sb done`: that output prompts it to mark
the step done if confident, and to return it to the parent if not. — confirmed 2026-08-16

---

## When a plan is created

**Investigation produces the plan rather than living inside one.** A plan is created once
the outcome is known and there is a clear path from the investigation's results through to
a merged PR. Investigation still appears as a step when it is one piece of an
already-shaped job. — confirmed 2026-08-16

**The worktree's owner chooses the template** — the lead of that worktree, or the sole
worker where there is no lead. — confirmed 2026-08-16

**A plan exists exactly when the work is heading for a change that will land.** Everything
else runs without one: investigation, questions, scouting, review-only work, anything a
single agent answers and reports, and everything a dispatcher does. Small does not mean
exempt — a one-line docs change bound for a PR still gets a plan, only a short one. —
decided 2026-08-16

**Having no plan and having no step are different things.** Inside a plan, what becomes a
step is settled by the two criteria above, so a lead's children are not automatically steps
and the plan is never a mirror of the agent tree. — decided 2026-08-16

**A plan may be created with some of its steps already done.** Plans are flexible; nothing
requires one to start empty. — confirmed 2026-08-16

**There is logic around what a plan may contain — you cannot create just any task.**
Creating a PR, for example, obliges certain steps. The guidelines are part of the design
rather than left to each agent. — confirmed 2026-08-16

**An obliged step is added automatically and may be skipped, never omitted.** Adding a
merge step brings its merge review with it. Skipping is allowed at the lead's or the
agent's discretion, with the reason recorded, and it is expected to be rare and
conservative — a one-line docs change should not have to be reviewed as if it were a
migration. What this buys is that **a skip is a state rather than an absence**: an omitted
step is invisible and a skipped one is on the board with its reason, so a bad call can be
seen and questioned. A gate that cannot be skipped would simply be routed around by never
creating the step, which is enforcement in appearance only. — decided 2026-08-16

---

## Not doing

**No stop hook for these gates, for now.** The steps are not solid or clear enough to be
enforced mechanically at turn end, and building that first would be getting ahead of the
design. — confirmed 2026-08-16

**The `todo` plugin is unrelated and retired.** It is not the ancestor of this and is not
to be grown into it. — confirmed 2026-08-16

---
