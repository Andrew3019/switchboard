# Tasks and steps — confirmed design

What Andrew has confirmed about the steps/templates layer and the task tree beneath it.
Same bar as `DESIGN-TRUTH.md`: only what he said, high-level, no implementation detail.
Nothing inferred, nothing proposed-but-unanswered. Open questions live at the bottom,
named as open rather than quietly assumed.

Entry format: one short claim, plus the date it was confirmed.

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

### Pre-merge gate

**The gate creates the PR and writes the description to his liking.** He is not asked
whether to create it. — confirmed 2026-08-16

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

## Steps

**A step is a named unit of how work is done, and steps compose into templates.** A
template is end to end; a step is not. A step may itself be a combination of steps, so long
as nothing is circular. A template is therefore really just steps as well. — confirmed
2026-08-16

**Loosely a chain, not a workflow engine.** The composition is the point; the machinery
around it is not. — confirmed 2026-08-16

**Effort and scale flex inside a step; the shape does not.** The same step covers a trivial
change and a large one. — confirmed 2026-08-16

**There will be a lot of steps, and only a few are user- or agent-facing.** Most are
internal fragments composed into others. A step may be nothing more than an output format —
the `-` / `---` / `-----` bullet contract is itself a step. — confirmed 2026-08-16

**Who runs a step is the lead's choice unless the step defines it.** A step is not required
to spawn an agent: design-review confirmation, for example, may happen inside the designer
agent rather than in a new one. — confirmed 2026-08-16

---

## Tasks

**A task tree is the run state: what is being done, by whom, and what is left.** Steps are
the static library; the task tree is the per-job, mutable thing. A node can name a step,
which is what stops a step being forgotten. — confirmed 2026-08-16

**Semi-structured, and more structured than a todo list without being a rigid DAG.** Not
Claude's internal todos, not a flat list; something like a DAG but dynamic and changeable
at any time. This was in the earliest braindump. — confirmed 2026-08-16

**One task tree per job, with agents attached to its nodes.** A lead may define one task or
several, or collapse everything into a single task — both must work gracefully, because the
union of the steps involved is much the same either way. A setup that does not handle both
is wrong by design. — confirmed 2026-08-16

**Tasks never store liveness.** A node names its owning agent; whether that agent is alive
is always read from the agent, never duplicated onto the node. Two trees that both claim to
know who is working will disagree. — confirmed 2026-08-16

**Defining the tree upfront is the point, not overhead.** More effort can be spent defining
it correctly when it is defined early, and the payoff is that on reaching a step the agent
already knows which presets that step pulls in. — confirmed 2026-08-16

**The tree is displayable: the current structure, and who is working on what.** — confirmed
2026-08-16

**Granularity is a balance, and all four costs are real.** Specific and structured against
flexible and changeable; how it looks when displayed; how many tool calls it takes; and
that finer nodes mean more chances to drift out of sync. — confirmed 2026-08-16

---

## Ticking off

**Nothing ticks automatically.** `sb done` does not mark a node complete. — confirmed
2026-08-16

**On a child's report the lead verifies progress and decides whether to tick.** It does
this quickly, from the child's report, and does not spawn another agent to verify progress
unless that is genuinely needed. — confirmed 2026-08-16

**A child may tick its own node when it is confident, and hand the decision up when it is
not.** The moment to tell it so is when it calls `sb done`: that output prompts it to mark
the node done if confident, and to return it to the parent if not. — confirmed 2026-08-16

---

## When a tree is created

**Investigation produces the tree rather than living inside one.** A tree is created once
the outcome is known and there is a clear path from the investigation's results through to
a merged PR. Investigation still appears as a node when it is one piece of an
already-shaped job. — confirmed 2026-08-16

**A tree may be created with some of its nodes already done.** Trees are flexible; nothing
requires one to start empty. — confirmed 2026-08-16

**There is logic around what a tree may contain — you cannot create just any task.**
Creating a PR, for example, obliges certain steps. The guidelines are part of the design
rather than left to each agent. — confirmed 2026-08-16

---

## Not doing

**No stop hook for these gates, for now.** The steps are not solid or clear enough to be
enforced mechanically at turn end, and building that first would be getting ahead of the
design. — confirmed 2026-08-16

**The `todo` plugin is unrelated and retired.** It is not the ancestor of this and is not
to be grown into it. — confirmed 2026-08-16

---

## Open / undecided

*Asked and not yet answered. Listed so they are visibly open rather than assumed.*

- **What makes something a node.** Two criteria proposed: that a node can be fully owned by
  one accountable agent — where an adversarial review is fully owned by the review lead
  coordinating its own agents — and, as an anti-granularity guard, that neighbouring nodes
  should plausibly go to different agents, since three nodes better done by one agent in one
  context were too finely split. — open 2026-08-16
- **Role versus preset on a step.** Sometimes the role applies more, more often the preset
  does, and sometimes they overlap. Whether the overlap is handled by logic, by deduplicating
  presets a role already carries, or some other way. — open 2026-08-16
- **A merge node without a merge-review node:** a hard logical gate, a rule in a universal
  task-creation prompt, or a required step that a lead or agent may skip at their discretion
  — assuming they stay conservative and skip only when genuinely warranted. Whether anything
  is trivial enough to skip merge review is part of the same question. — open 2026-08-16
- **Whether task trees are always per worktree.** If they are, the board can render them
  under its existing worktree groups; if not, they need a section of their own. — open
  2026-08-16
- **Whether there is a catalogue of named steps**, including steps carrying no logic at all
  — a "merge PR" step that is only a name — so that every tree naming that thing names it
  the same way. — open 2026-08-16
- **How agents are kept aware of their node.** The suggestion is to drop task status into
  the output of commands they already run, such as `sb inbox`, to save tool calls. To be
  locked down once checked. — open 2026-08-16
