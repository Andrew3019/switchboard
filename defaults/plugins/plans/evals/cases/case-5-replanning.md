# Case 5 — material replanning

The only case that is not a fresh planner. A delta reshapes the plan, never the agent
running it: the same planner, with the original reasoning still in its context, revises the
same plan in place. Starting a new planner here is not replanning — it is planning again,
and the two are different things with different costs.

**Snapshot case 1 first.** Its plan file, its contract text and its manifest. Revision
happens in place, so the baseline is gone the moment the delta lands, and the whole
comparison is against that baseline.

## Brief — hand over exactly this half, and nothing below it

Sent as a message to **case 1's own planner**, after case 1 is complete and snapshotted.

> A material delta on the plan you wrote, from the main agent running it.
>
> Three of this repo's nine model tiers resolve through the `codex` provider rather than
> `claude` (`deepseek`, `gpt-5.5`, `gpt-5.6-sol`). Checking a codex model id means invoking
> the codex CLI, which is slow and can stop to ask for a login — so `sb doctor` cannot
> verify those three the way it verifies the rest without becoming a command that hangs.
> A doctor line that reported all nine as resolved would be claiming something it did not
> check for a third of them, in the one command whose whole job is to be believed.
>
> Revise the plan. Same rules as before on the approval: write the revised two-section
> contract to `.switchboard/evals/case-5-contract.md` and `sb tell parent` the path rather
> than blocking.

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
