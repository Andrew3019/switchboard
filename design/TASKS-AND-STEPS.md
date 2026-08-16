# Tasks and steps — confirmed design

What Andrew has confirmed about the steps/templates layer and the task tree beneath it.
Same bar as `DESIGN-TRUTH.md`: only what he said, high-level, no implementation detail.
Nothing inferred, nothing proposed-but-unanswered. Open questions live at the bottom,
named as open rather than quietly assumed.

Entry format: one short claim, plus the date it was confirmed.

---

## Why this layer exists

**What agents do, how they do it, and how deep verification goes is currently
disorganised.** The fix is structured steps rather than per-task prose, so the four
recurring moments — design, design review, implementation review, merge review — stop
being reinvented on every job. — confirmed 2026-08-16

**These steps replace previous decisions, they do not sit beside them.** Where the
scattered prose about approval, pushing and merging conflicts with a step, the step is the
authority and the prose gets cut back to a pointer. — confirmed 2026-08-16

**A human-facing output shape may be a template.** `DESIGN-TRUTH.md`'s rule that almost
none of the human-facing guidance may become something to copy was an exaggeration. A step
may specify an output format — for example a bullet contract with fixed indent levels and a
word cap per bullet. — confirmed 2026-08-16

---

## Steps

**A step is a named unit of how work is done, and steps compose into templates.** A
template is end-to-end; a step is not. A step may itself be a combination of steps, so long
as nothing is circular. — confirmed 2026-08-16

**Effort and scale flex inside a step; the shape does not.** The same step covers a trivial
change and a large one. — confirmed 2026-08-16

**There will be many steps, and only a few are agent- or human-facing.** Most are internal
fragments composed into others — an output format is a step. — confirmed 2026-08-16

**Who runs a step is the lead's choice unless the step defines it.** A step is not required
to spawn an agent: design-review confirmation, for example, may happen inside the designer
agent rather than in a new one. — confirmed 2026-08-16

---

## Tasks

**A task tree is the run state: what is being done, by whom, and what is left.** Steps are
the static library; the task tree is the per-job, mutable thing. Creating a task node can
name a step, which is what stops a step being forgotten. — confirmed 2026-08-16

**One task tree per job, with agents attached to its nodes.** A lead may hold several
tasks, or collapse everything into one — both must work gracefully, because the union of
the steps involved is much the same either way. A setup that does not handle both is wrong
by design. — confirmed 2026-08-16

**It is a tree, semi-structured, and changeable at any time.** More structured than a plain
todo list, less rigid than a fixed DAG. Nodes may be added, changed or reordered as the job
proceeds. — confirmed 2026-08-16

**Tasks never store liveness.** A node names its owning agent; whether that agent is alive
is always read from the agent, never duplicated onto the node. Two trees that both claim to
know who is working will disagree. — confirmed 2026-08-16

**Defining the tree upfront is the point, not overhead.** Effort spent getting it right
early pays off later: when an agent reaches a step it already knows what that step pulls
in. — confirmed 2026-08-16

**Both a lead and an agent may tick a node off.** — confirmed 2026-08-16

---

## Ticking off

**Nothing ticks automatically.** `sb done` does not mark a node complete. — confirmed
2026-08-16

**On a child's report the lead verifies progress and decides whether to tick.** It does
this quickly, from the child's report. It does not spawn another agent to verify progress
unless that is genuinely needed. — confirmed 2026-08-16

**A child may tick its own node when it is confident, and hand the decision up when it is
not.** The moment to tell it so is when it calls `sb done`: that output prompts it to mark
the node done if confident, and to leave it to the parent if not. — confirmed 2026-08-16

---

## When a tree is created

**Investigation produces the tree rather than living inside one.** A tree is created once
the outcome is known and there is a clear path through to a merged PR — normally by the
lead, after whatever scouting shaped the job. Investigation still appears as a node when it
is one piece of an already-shaped job. — confirmed 2026-08-16

**A tree may be created with some of its nodes already done.** Trees are flexible; there is
no requirement that a tree starts empty. — confirmed 2026-08-16

---

## Not doing

**No stop hook for these gates, for now.** The steps are not solid or clear enough to be
enforced mechanically at turn end, and building that first would be getting ahead of the
design. — confirmed 2026-08-16

---

## Open / undecided

*Asked and not yet answered. Listed so they are visibly open rather than assumed.*

- **What makes something a node.** Two criteria proposed by Andrew — that a node can be
  fully owned by one accountable agent (which may be a lead coordinating its own children),
  and that neighbouring nodes should plausibly go to different agents or else the split is
  too fine. Not yet settled. — open 2026-08-16
- **Role versus preset on a step, and what happens when they overlap.** — open 2026-08-16
- **A merge node without a merge-review node:** a hard gate, a prompt rule, or a required
  step that a lead or agent may explicitly skip. — open 2026-08-16
- **Whether task trees are always per worktree**, and therefore whether the board renders
  them inside its existing workspace groups or in a section of their own. — open 2026-08-16
- **Whether there is a catalogue of named steps**, including steps that carry no logic and
  exist only so that every tree names the same thing the same way. — open 2026-08-16
- **How agents are kept aware of their node** without new commands or extra tool calls.
  Andrew has asked for this to be locked down once checked. — open 2026-08-16
