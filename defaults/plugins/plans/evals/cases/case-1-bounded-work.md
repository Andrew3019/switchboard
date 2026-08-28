# Case 1 — bounded work

The smallest SHAPED job: the implementation is bounded, but the user-visible claim needs a
real design choice before anybody can honestly write it. The task owner has already chosen
the shaped path for that reason. A plan that turns this into several implementation owners
or adds a planning handoff has repeated the failure the design was built to fix.

Case 5 is a delta into **this** planner. Snapshot this case's plan file, contract text and
manifest before you send it, or there is nothing left to compare case 5 against.

## Brief — hand over exactly this half, and nothing below it

You are the plan writer for one job in the switchboard repo. The checkout you are standing
in is the whole of it; read it freely. The task owner classified this as shaped because the
meaning of the new health claim must be settled before implementation, not during it.

**The job.** `sb doctor` reports the herdr version, the store path and the panel's health.
It says nothing about this repo's model tiers, though `sb models` resolves all of them and
`sb models --json` already carries the resolution per tier. A user wants doctor to say
whether this repo's declared tiers are usable. Investigate what doctor and models can
truthfully establish, choose the meaning and shape of that output, and plan the bounded
implementation.

**What is settled already.** Do not add a new top-level command. The exact output shape and
the boundary between configured, resolved and executable are yours to reason about. The
change lands as a pull request on this repo.

**Recorded departure, and it is not optional.** Nobody here presents the contract to a
human: your instruction says approval is the task owner's to obtain, and the task owner in
this exercise is the harness. So write the two-section contract to
`.switchboard/evals/case-1-contract.md` instead of handing it over in words, then finish the
way your instruction says to — clear the plan's `planner` field, `sb tell parent "contract at
.switchboard/evals/case-1-contract.md"`, and `sb done`. Everything else in the approval
step's definition still applies — the two sections, in that format, with nothing added.

Do not spawn anything. This job ends when the plan exists, the contract is written and you
have handed the shape back.

## Expected signal — never handed to the planner

**Met** when the plan is short and linear, one main agent owns the implementation steps,
and `plan-review` is **not** in it. The approval, the PR, the review of the implementation
and the merge are all fine — they are composed or obliged, not a judgement call. The
contract exists in the two-section format and adds no third section.

**Not met** when `plan-review` appears, when a fresh agent is proposed for a step one agent
could carry, or when the plan runs long enough that the reader cannot hold it.

Read this case's length **against case 3**, not on its own. A five-step plan here is only
excessive if case 3's is not meaningfully longer.
