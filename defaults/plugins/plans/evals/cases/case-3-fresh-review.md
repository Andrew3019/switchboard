# Case 3 — fresh review

`plan-review` is optional in the strict sense: nothing composes it and nothing obliges it,
so it is in a plan because the planner named it. Not naming it is a decision. This case is
built so that naming it is the right decision, and so that naming it is only half the job —
the edge into the approval has to be wired by hand in the same edit.

## Brief — hand over exactly this half, and nothing below it

You are the plan writer for one job in the switchboard repo. The checkout you are standing
in is the whole of it; read it freely.

**The job.** The plans store keeps one file per plan under the git common dir, and
`sb plugin plans list --all` reads every one of them to answer. That is fine at a dozen
plans and will not be at a few hundred. Add an index alongside the per-plan files so the
list can be answered without opening them all, keeping both correct when several worktrees
on the same repo write concurrently, and keeping the existing `migrate` path — the one-way
move from a single `plans.json` — working for a repo that has not run it yet.

**What is not settled.** Whether the index is authoritative or a cache that can be rebuilt;
what happens when it disagrees with the files; whether concurrent writers take a lock, and
what that costs a worktree that only wanted to read. Those are yours to decide and to put in
front of Andrew.

**Recorded departure, and it is not optional.** Your `change-approval` step's definition
says to present the two sections in chat and then `sb block`. Do not. There is nobody here
to answer a block. Instead: write the two-section contract to
`.switchboard/evals/case-3-contract.md`, then `sb tell parent "contract at
.switchboard/evals/case-3-contract.md"` and stop.

Do not spawn a main agent, and do not hand off. If you put up a plan reviewer of your own,
that is yours to decide; it counts as part of the plan you are writing either way.

## Expected signal — never handed to the planner

**Met** when `plan-review` is in the plan **and** wired: the `plan-review` step's id in
`change-approval`'s `deps`, and `change-approval`'s `root` set to `false`. Both halves, in
the plan file. Wiring is the part that is easy to lose — the two steps share the `design`
band, so both are minted as marked starts and neither edge is drawn for the planner.

`sb plugin plans validate <plan>` in the clone is the mechanical check: a step carrying a
start mark *and* a dep is a defect it reports, so a half-done wiring shows up there.

**Partly met** when `plan-review` is named but left unwired — the plan then reads as one
whose approval can be reached without the review.

**Not met** when `plan-review` is absent. The brief hands the planner three unresolved
design questions, a concurrency risk and a migration path that must keep working; that is
the described trigger almost word for word.

## Known confound, found in the first live run

The brief's handed-over half ends "If you put up a plan reviewer of your own, that is yours
to decide". Case 3 is the case whose expected signal is that `plan-review` is **named**, and
case 1 — whose signal is its **absence** — carries no comparable sentence. The one case that
raises the idea in its brief is the one that expects it, and 1-against-3 is the central
contrast of the whole pass.

As with case 2 the bias runs against the observed result: the planner did not name
`plan-review` even with the idea in front of it, so the `not met` is if anything stronger
than the case deserves. Take the sentence out before a run where a `met` here would be the
finding.
