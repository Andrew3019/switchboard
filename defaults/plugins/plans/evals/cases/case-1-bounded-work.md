# Case 1 — bounded work

The shape most jobs are, and the one the whole design exists to protect: a small change
with an obvious approach. A plan that reaches for a reviewer and a handoff here has
repeated the failure it was built to fix.

Case 5 is a delta into **this** planner. Snapshot this case's plan file, contract text and
manifest before you send it, or there is nothing left to compare case 5 against.

## Brief — hand over exactly this half, and nothing below it

You are the plan writer for one job in the switchboard repo. The checkout you are standing
in is the whole of it; read it freely.

**The job.** `sb doctor` reports the herdr version, the store path and the panel's health.
It says nothing about this repo's model tiers, though `sb models` resolves all of them and
`sb models --json` already carries the resolution per tier. Add the tiers to `sb doctor`'s
output, so one command says whether this repo's agents can actually be spawned on the tiers
it declares.

**What is settled already.** It is one new section in the existing output, no new flag, no
new command. The change lands as a pull request on this repo.

**Recorded departure, and it is not optional.** Your `change-approval` step's definition
says to present the two sections in chat and then `sb block`. Do not. There is nobody here
to answer a block. Instead: write the two-section contract to
`.switchboard/evals/case-1-contract.md`, then `sb tell parent "contract at
.switchboard/evals/case-1-contract.md"` and stop. Everything else in the approval step's
definition still applies — the two sections, in that format, with nothing added.

Do not spawn a main agent, and do not hand off. This job ends when the plan exists and the
contract is written.

## Expected signal — never handed to the planner

**Met** when the plan is short and linear, one main agent owns the implementation steps,
and `plan-review` is **not** in it. The approval, the PR, the review of the implementation
and the merge are all fine — they are composed or obliged, not a judgement call. The
contract exists in the two-section format and adds no third section.

**Not met** when `plan-review` appears, when a fresh agent is proposed for a step one agent
could carry, or when the plan runs long enough that the reader cannot hold it.

Read this case's length **against case 3**, not on its own. A five-step plan here is only
excessive if case 3's is not meaningfully longer.
