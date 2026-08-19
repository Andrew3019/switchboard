<!--
This file changed AUDIENCE, and that is the whole point of the rewrite.

It used to be a reviewer's disposition — "assume the work is flawed, end with PASS or
REVISE" — bound to the reviewer role so every reviewer spawn carried it. That made every
review adversarial and made "run an adversarial review of this design" impossible to say,
because there was no procedure anywhere, only a mood. One reviewer, one pass, one verdict,
and nothing that converged on anything.

It is now a PROCEDURE FOR THE AGENT RUNNING THE REVIEW — a `lead`, since the split (it was
"an orchestrator" when this was written, and that role is now two). Whoever asked says "run
an adversarial review of X"; a lead reads this and runs the loop. Nothing here is
addressed to a reviewer — the reviewer gets its lens in the task string the lead writes,
which is why the lens can be chosen for the artifact instead of being fixed in a file.

Four things are deliberate:

  - RUN BY A LEAD SPAWNED FOR IT. The body used to open "run it yourself rather than
    delegating the running of it", which was written for an orchestrator and was true for
    exactly one kind of reader. Every round of this procedure is a spawn, so an agent
    without delegate rights is told to run something `sb delegate` refuses it — and briefs
    routinely point workers here to self-review. The named case fixes it: whoever is asked
    and can spawn puts up ONE lead that owns the whole loop, and whoever cannot spawn asks
    its parent for that lead instead of attempting rounds it cannot start. The lead that
    was spawned to run the review does not spawn another — the first line of the body is
    the test that tells the two readers apart, and it is stated as a case rather than a
    condition buried mid-paragraph for exactly that reason.
  - SEQUENTIAL, not a fan-out. Round N reviews what round N-1 produced. Running the
    reviewers in parallel would review the same draft five times, which is five opinions
    on one artifact rather than a thing getting better.
  - ONE proposer kept alive, a FRESH reviewer each round. The proposer needs the history —
    what it already tried and why it rejected it — and re-explaining that every round is
    the cost the whole design is trying to avoid. The reviewer must NOT have it: a fresh
    agent with a named lens is the only thing here that can see what everyone already
    invested in has stopped noticing.
  - A ROTATING LENS, never repeated. Same reviewer prompt every round finds the same class
    of problem every round and converges on nothing. The lens is chosen for the artifact,
    not from a fixed list — the useful lenses for a schema migration are not the useful
    lenses for a CLI's error messages — which is a judgement, so it stays prose here.

The convergence rule is stated as a stop condition rather than a round count because the
failure it guards against is a loop that keeps going while the reviewer invents smaller
objections. The hard cap exists because "converged" is a judgement the lead makes
about its own work, and a judgement with no ceiling is how three rounds becomes nine.

BINDING: none, deliberately. This is not a disposition and must not go back onto the
reviewer role — that would tax every reviewer spawn with a procedure meant for its parent,
which is what it used to do. It is not bound to the lead either, because a procedure used
occasionally should not be paid for on every spawn that might one day use it. It is READ
ON DEMAND: `sb presets adversarial` prints this file (comments stripped, so this note is
not part of what an agent reads), and the lead role points at it by name. That command
exists because of this file — presets could only be listed, not read, so a procedure had
to be stapled to a spawn to reach anyone.

Which means the first rule of editing this file: it is read as prose, not flattened, so
its layout is load-bearing in a way no bound preset's is.
-->

# adversarial

A procedure, not a mood. Use it when you are asked for an adversarial review of something —
a design, a plan, a change.

Every round of it is a spawn, so it is run by a lead put up for it. Which reader you are
decides what you do, and there are three cases:

- You were spawned to run this review. You are that lead: the loop below is yours, and you
  do not put up another lead for it.
- You were asked for one while doing something else, and you can spawn. Delegate one lead
  and give it the whole review — the artifact, where it is, and "read `sb presets
  adversarial` and run it". It owns the rounds; you report from what it reports and do not
  run rounds of your own beside it.
- You cannot spawn — you are a worker, or any role without delegate rights. Then you cannot
  run this and should not try: `sb delegate` refuses you, and there is nothing left of the
  procedure once the spawns are removed. Ask your parent for an adversarial-review lead
  over the artifact, naming where it is, and get on with the rest of your task.

The loop, for the lead running it. Keep one proposer for the whole review: the agent that
produced the artifact, or a fresh one handed it, whose job across every round is to defend
or revise. Keep it alive between rounds so it remembers what it already tried and why it
rejected it.

Then run rounds, one at a time, never in parallel — each round has to see what the last
one produced. In each round, spawn a NEW reviewer whose task names one specific lens to
attack the artifact through, and choose that lens for this artifact: the ways a schema
migration fails are not the ways an error message fails. Never reuse a lens you have
already run, because a reviewer asked the same question finds the same answer. Give the
reviewer the artifact and the lens and nothing else — no earlier verdicts, no defence —
its independence is the only thing here that sees what everyone invested in it has stopped
noticing. Pass its findings to the proposer, let it revise or argue, and start the next
round on the result.

Stop when a round produces nothing that changes the artifact, or nothing beyond taste.
That is convergence and it is the point. Stop anyway after four rounds and say you hit the
cap — a review that will not converge is itself the finding, and usually means the artifact
needs a decision rather than another round.

Then report as you would any cohort: what the artifact is now, which objections actually
changed it, what was raised and rejected and why, and anything still open. Name the round
count. Whoever reads you should not have to open a single agent to know whether the thing
is sound.
