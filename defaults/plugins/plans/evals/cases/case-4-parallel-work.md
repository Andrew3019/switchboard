# Case 4 — parallel work

A step is a unit of work, not an agent boundary. This case offers four genuinely
independent pieces, so a plan that puts a fresh agent on each is right — and it is only
right if the plan says *why* each boundary is real.

## Brief — hand over exactly this half, and nothing below it

You are the plan writer for one job in the switchboard repo. The checkout you are standing
in is the whole of it; read it freely.

**The job.** Four of the repo's longest modules — `switchboard/broker.py`,
`switchboard/board.py`, `switchboard/store.py` and `switchboard/cli.py` — carry module and
function docstrings that describe behaviour the code no longer has. Bring each module's
prose back in line with what its code actually does. No behaviour changes: docstrings and
comments only.

The four are independent of each other. Each is large enough that reading one is a full
sitting.

**Recorded departure, and it is not optional.** Your `change-approval` step's definition
says to present the two sections in chat and then `sb block`. Do not. There is nobody here
to answer a block. Instead: write the two-section contract to
`.switchboard/evals/case-4-contract.md`, then `sb tell parent "contract at
.switchboard/evals/case-4-contract.md"` and stop.

Do not spawn a main agent, and do not hand off.

## Expected signal — never handed to the planner

**Met** when the plan proposes real parallel agents — one per module, or a defensible
grouping — and every boundary carries its reason in that step's own `strategy`, in the
`continuity` or `orchestration` field. "Independent files, no shared state, each is a full
sitting of reading" is a reason. Naming four agents and saying nothing about why is not.

Look also for what the plan does about the parts that are **not** parallel: whichever agent
integrates the four branches, and the fact that a docstring pass over four modules at once
is a single reviewable diff or four of them. A plan that fans out and never says how the
work comes back together has answered half the question.

The repo carries a `docs` template for exactly this shape of job. Using it is a good sign of
grounding; not using it is not a failure, but ignoring it without a word is worth noting.

**Not met** when the plan serialises all four onto one agent with no reason given, or when
it fans out with no stated justification for the boundaries.
