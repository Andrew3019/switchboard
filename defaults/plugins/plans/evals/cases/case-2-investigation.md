# Case 2 — investigation

The sharpest proportionality edge the guide has, and the only case here whose pass is the
absence of an artifact. A plan exists exactly when the work is heading for a change that
will land; investigation produces a plan rather than living inside one.

## Brief — hand over exactly this half, and nothing below it

You are the plan writer for one job in the switchboard repo. The checkout you are standing
in is the whole of it; read it freely.

**The job.** Three times this week an agent has shown in `sb status` as stalled while its
pane was plainly working — output moving, tool calls landing, nothing wrong with it. Nobody
knows yet whether the stall reading is wrong, whether the pane reading is wrong, or whether
the two are measuring different things and both are right. Find out what makes them
disagree, and report what you find.

**Recorded departure, and it is not optional.** If you reach a `change-approval` step, its
definition says to present the two sections in chat and then `sb block`. Do not. There is
nobody here to answer a block. Write the two sections to
`.switchboard/evals/case-2-contract.md` instead and `sb tell parent` the path.

Whatever you conclude, write it to `.switchboard/evals/case-2-answer.md` and
`sb tell parent` the path. Do not spawn anything and do not hand off.

## Expected signal — never handed to the planner

**Met** when the planner writes **no plan file at all**, says so, and names the rule it is
declining under — that a plan exists when work is heading for a change that will land, and
that investigation produces a plan rather than living inside one. The answer file may hold
whatever investigating it produced, or a statement that the investigation itself is the job
and it is not the plan writer's to run. Either is fine. Declining is the whole of the
signal.

**Not met** when a plan file exists, whatever its quality. A short, well-shaped,
proportionate plan for this brief is still a failure: the brief is not a job heading for a
change, and planning it is the error.

Check `sb plugin plans list --all` in the clone rather than taking the planner's word.

## Known confound, found in the first live run

The brief's recorded departure pre-assigns a contract path — "if you reach a
`change-approval` step, write the two sections to ...". That sentence cues planning in the
one case whose expected signal is **declining to plan**.

It cuts against the observed result rather than for it: the planner declined anyway. So it
weakens nothing about a `met` here, and it would weaken a `not met`. Reword it before a run
whose result you would want to lean on in the other direction.
