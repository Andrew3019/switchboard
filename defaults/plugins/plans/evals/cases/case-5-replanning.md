# Case 5 — material replanning

The only case that is not a fresh planner. A delta reshapes the plan, never the plan's
identity: the same plan is revised in place, and where the task owner puts the ORIGINAL
planner back on it — the cheap move when that agent's reasoning is still available — the
revision costs a pass rather than a whole planning phase. Starting a new plan here is not
replanning; it is planning again, and the two are different things with different costs.

(The delta reaches the planner through the task owner, which holds the shape back once a
planner has handed it over. This case sends it straight to the planner because that is the
half being scored — what a planner does with a delta, not how the message was routed.)

**Snapshot case 1 first.** Its plan file, its contract text and its manifest: revision
happens in place, so the baseline is gone the moment the delta lands, and the whole
comparison is against that baseline.

**Its planner is still there — do not restore it.** Case 1's planner has reported `done`,
which is not closed: the pane stays, the name still answers, and `sb tell` reaches it. That
is the whole delivery mechanism for this case. `sb restore` is for an agent that was
CLOSED, and the teardown that closes these runs after case 5, so a restore here is refused
(`already running — nothing to restore`) and there is nothing wrong. A fresh planner instead
of this one is case 1 again, not replanning.

**Hand the shape back to it as you send the delta.** Case 1's planner cleared the plan's
`planner` field when it finished, which is what says the shape returned to the task owner —
so write that agent's name back into the field before you send. Skipping this asks a planner
to reshape a plan its own instruction says it no longer holds. This is the one step of the
real lifecycle the exercise performs for the missing task owner; everything else about the
delta is the planner's own.

## Brief — hand over exactly this half, and nothing below it

Sent as a message to **case 1's own planner**, after case 1 is complete and snapshotted.

> A material delta on the plan you wrote, from the main agent running it. The plan's
> `planner` field names you again, so the shape is yours for this revision.
>
> Three of this repo's nine model tiers resolve through the `codex` provider rather than
> `claude` (`deepseek`, `gpt-5.5`, `gpt-5.6-sol`). Checking a codex model id means invoking
> the codex CLI, which is slow and can stop to ask for a login — so `sb doctor` cannot
> verify those three the way it verifies the rest without becoming a command that hangs.
> A doctor line that reported all nine as resolved would be claiming something it did not
> check for a third of them, in the one command whose whole job is to be believed.
>
> Revise the plan. Same departure as before on the approval: write the revised two-section
> contract to `.switchboard/evals/case-5-contract.md` rather than handing it over in words,
> then hand the shape back the same way — clear the `planner` field, `sb tell parent` the
> path, `sb done`.

## Expected signal — never handed to the planner

**Met** when all four of these hold:

- The **same plan id** is revised. No second plan, no `create`.
- The **approval step's `tries` is bumped** and its `progress` is back to `open`, with a
  note saying what the second pass was for.
- The revision is **proportionate to the delta** — the affected steps and the contract
  change; the steps the delta does not touch stay as they were. A plan rebuilt from nothing
  is the failure this case is looking for.
- The revised contract **names the tradeoff** rather than routing around it: which tiers can
  be checked, which cannot, and what the output says about the ones it did not check.

**Not met** when a second plan appears, when `tries` is untouched, or when the delta is
absorbed silently — a plan that changes with nothing in the record to say why is one nobody
can audit later.

**A note on the delta's content.** The three codex tiers are a fact about this repo and
check out against `sb plugin plans catalog`. The claim about what checking a codex model id
costs is supplied by the exercise; it stands in for evidence a main agent would have
gathered. Score the planner's *response* to the delta, not the delta's provenance, and do
not mark the plan down for repeating a premise it was handed.

## Known limit, found in the first live run

The condition "`progress` back to `open`" **cannot be observed in this exercise**, and the
reason is a missing agent rather than a departure. Approval is the task owner's to obtain
and the task owner is who ticks that step; there is no task owner here, only a planner and
the harness. So the approval step is never ticked in the first place and there is nothing to
reopen: in the first run it sat at `waiting on Andrew` before the delta and after it. The
purpose of the condition — that the step is visibly re-owed — is carried by the `tries` bump
and the note beside it.

Score the other three conditions and say this one was unmeasurable. Do not read it as a
failure, and do not quietly drop it either: it is a defect in the case, not in the planner.
