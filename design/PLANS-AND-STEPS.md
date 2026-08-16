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
The recurring moments of a job — design, design review, implementation review, merge
review — get reinvented on every task. Structuring them is the fix.

Today everything asks Andrew, three times over: whether to create the PR, whether to merge,
whether to clean up. Each is a decision he is made to take one at a time. Removing them is a
large part of the point.

It is also how the work process becomes legible. A finished plan is evidence of how a job
actually ran, and that evidence is what shows where the system should be faster, more
abstracted, or better tooled. Integral to the system, though nothing else is load-bearing
on it.

---

## Vocabulary

Three words, chosen to collide with nothing else in the system. `task` is not available for
any of them: it is already the agent's own task — its store column, its `sb delegate`
argument, and the protocol's "the task you were given". Neither is `preset`, which is
already prompt text injected at spawn.

**Step** — the unit. What an agent owns, what gets ticked, what carries a try count and
notes.

**Plan** — a group of steps. Nothing more than that.

**Template** — a preconfigured plan, in the ordinary sense of the word. A starting point
you can do as you like with: a plan may be a template plus whatever else the job needs, and
nothing holds a plan to the shape it started from. Using one is copy and paste — the copy is
edited afterwards if it needs it, and nothing links it back to what it came from.

---

## Plans

A plan is the live state of one job: what is being done, by whom, and what is left.

**A plan is a DAG.** One step may fan out to several, and those may join back into one; a
join waits for every branch feeding it.

**Redoing work is not an edge.** Where part of a job must be redone, the lead or sole
worker goes back to it. The graph stays acyclic, and the flexibility comes from it being
agent-driven rather than modelled.

**Semi-structured and changeable at any time.** More structured than a todo list, less
rigid than a fixed workflow. Not Claude's internal todos, not a flat list.

**Composed, not executed.** The composition is the point; there is no workflow engine
around it.

**One plan per job.** A lead may define one plan or several, or collapse everything into a
single plan. Both must work gracefully, since the union of the steps involved is much the
same either way — a design that does not handle both is wrong.

**A plan belongs to one worktree, and a worktree may hold several plans.** So the board
renders plans inside the worktree grouping it already has, rather than in a section of
their own. From inside a plan the others are invisible and irrelevant: nothing in a plan
refers to another, and anything a step needs from the world outside is an input it takes.
The merge gate takes a PR, so several plans mean several PRs and no plan has to know that. A job is owned by a lead, and everything below a lead shares that lead's
worktree, so a job and a worktree are the same span. Work spanning two worktrees is two
plans; one plan spanning both would be a different feature.

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
done.

**The worktree's owner creates the plan and chooses the template** — the lead of that
worktree, or the sole worker where there is no lead.

**A dispatcher is never involved in a plan.** It relays work and orchestrates the creation
of agents and worktrees; it does not plan, own, tick or read one.

**A plan may be created with some of its steps already done.** Nothing requires one to
start empty.

---

## Steps

**Steps compose.** A step may itself be a combination of steps, so long as nothing is
circular.

**Steps come from a library or are made on the fly.** Both are first class: a plan may name
a step that already exists and invent the rest as it goes. A named step is a link to the
library rather than a copy of it — steps are units, and there is little about one to change
once it exists. Templates work the other way, being copied and then edited freely.

**A step may be word-only.** Nothing has to be defined behind it; the name alone is worth
having.

**Effort and scale flex inside a step; the shape does not.** The same step covers a trivial
change and a large one.

**A preset may exist only for steps to name**, rather than being offered to spawns at
all — the design gate's bullet format is one.

**A step names presets always, and a role only when it spawns a new agent.** A role is what
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

**On a child's report the lead verifies progress and decides whether to tick.** Quickly,
from the child's report. It does not spawn another agent to verify progress unless that is
genuinely needed.

**A child may tick its own step when confident, and hand the decision up when not.** The
moment to say so is when it calls `sb done`: that output prompts it to mark the step done
if confident, and to return it to the parent if not.

**A step carries a try count, and a count above one is rendered.** Rework is a step
re-entering progress after being done — a failed review sends its step back — so repetition
is a number on the step rather than an edge in the graph.

**No visit ceiling on rework.** A loop that will not converge ends the way everything else
does: the lead eventually blocks. Being agent-driven is what makes a ceiling unnecessary.

**Rework after a gate is rejected is handled however the lead likes.** It may edit the plan
to add a fix step between two reviews, or simply run the review a second time. Which one is
chosen does not matter; what matters is that neither breaks anything.

---

## Gates

**A gate is a step's exit condition, not a step of its own.** Every step has a condition
saying when it is complete; a gate is one that requires a human. So a design step ending in
"no implementation until he confirms" needs no second step for the confirmation, and
collapsing a step into the agent before it never loses the gate.

**A plan is never a control surface.** Andrew talks only to agents and never edits a plan.
Where a gate needs him the owning agent blocks, the step shows its owner blocked, and
answering the agent clears both. There is no unblocking a gate through the plan.

**A gate's message may show the plan** where showing it helps.

**Two blocks is the shape of a job, not a ceiling.** A plan that lands a change has a
design gate and a merge gate, and everything else resolves without him. Nothing enforces a
count — several plans on one worktree means several of each, and that is fine.

### The design gate

After planning and before implementing, the agent summarises the problem and the planned
behavioural contract of the fix. Two sections, ordered step by step: what is causing the
problem, and what the fix will be — not necessarily a step-by-step capture of the fix
itself, but an ordered account for his understanding.

The format is fixed: bullets indented with `-`, then `---`, then `-----`, each bullet
twelve words at most. Implementation begins only after he confirms.

### The merge gate

The gate creates the PR and writes the description. He is not asked whether to create it.

Testing steps are given only when actually needed — anything the agent has already tested
does not need him, and asking wastes his time, his effort and his reading.

The review-and-review-again behavioural gate has been run by this point. The message mimics
the design gate: concise, simply explained.

Once he approves, everything else happens automatically — merge, cleanup, delete worktrees,
close agents. No further questions.

### Both gates

Neither is end to end, so both are steps rather than templates, and each may turn out to be
one step or several. Both are general enough for any and all PRs. Every agent runs them for
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

---

## Records, and what they are for

**A plan stops being live with its worktree; the record of it is kept.** Plans are plain
text and losing one is cheap — nothing about it compares to losing a worktree or an agent —
so they are not deleted. Cleanup means dropping out of the UI and no longer counting as
active, never erasing. When every agent on a worktree is closed the plan goes dormant and
is restored when they are; when the worktree goes, the plan stops being live and its record
survives.

**A plan has a changelog, append-only, that whoever edits it adds to.** A plan is flexible
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
content.

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

**It ships as a plugin, and switching it off restores today's behaviour exactly.** Disabled
means no agent is ever told plans exist, so none are made. Deleting the folder behaves like
off, and putting it back behaves like on.

**The board needs a hook for it.** Rendering plans under their worktree is the one thing the
plugin cannot do from outside, so the board grows an extension point rather than knowledge
of plans.

**Everything else lives in the plugin** — its commands, its state, and the prompt text that
tells agents plans exist.

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
