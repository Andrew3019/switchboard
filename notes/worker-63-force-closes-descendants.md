# `--force` closes the subtree — issue #53's design call, and the run behind it

Andrew's call on the question issue #53 left open: `sb cleanup --force <name>` means
"close it **and** its live descendants". The live-descendants gate, documented until now
as liftable by nothing, is liftable by `--force`.

## What was actually wrong

The gate's argument was that `--force` overrides facts about the agent you *named*, and
live children are facts about agents you did not. True as far as it goes, and what it left
the operator with was the bug as filed: a row the board plainly draws, refused by name,
refused under `--force`, with no command anywhere that clears it. The way out existed —
find the descendant yourself, close the subtree leaves-up — and nothing in any refusal
pointed at it.

## The shape of the fix

Not an exemption. `_leaves_up` (broker.py) reorders the candidate list under `--force`:
every descendant goes ahead of its parent, deepest first, so each row is closed only once
everything beneath it already is. `live_descendants` is therefore *empty* by the time the
parent is reached, and the invariant — an agent whose pane is closed has no descendant
whose pane is still working — holds at every single step. That is the same walk the old
refusal told the operator to do by hand; the only change is who does it.

Two consequences worth naming:

- **The already-closed row.** Issue #53's filed repro is a parent that was *already*
  closed, still drawn because a descendant kept its pane. `--force` on it now takes the
  descendants and reports what it took, instead of `already closed` about a command that
  did its job. Only when nothing under it was taken is the refusal still printed.
- **`cleanup_forced_subtree`.** One event per row the operator typed, listing what came
  down with it. The per-descendant `cleanup` events cannot answer "why did that subtree
  disappear", and `cleanup_forced_live` only says a row was mid-turn.

What survives of the old argument is the half that was about safety: a **sweep** still
never lifts this gate, and `--force` is still illegal on a sweep. Nothing closes an
unnamed subtree on its own judgement.

DESIGN-TRUTH.md was checked and not edited. It says "Cleaning up a lead always cleans its
children" and "Cleanup is the parent's, and it always takes the children" — the change
moves toward those, not against them.

## Live proof

One throwaway `git clone` at this branch, driven through its own `./bin/sb`, reusing
`acceptance/accept.py`'s `Clone` so the store-isolation check and the teardown are that
code and not a re-implementation. One lead, one child under it on a `sleep 900` — so the
child is unambiguously live, mid-turn, nothing reported, when the force lands.

Run `sbfogvfdu`, 2026-08-15, all 14 checks pass:

- without `--force`, naming the lead is refused and the refusal names the child
- herdr holds both panes going in
- `sb cleanup <lead> --force` exits 0, refuses nothing, and returns `[kid, lead]` — the
  child first, which is the ordering the invariant rests on
- herdr holds neither pane afterwards
- both store rows survive at `done` with `pane_id` NULL, so `sb restore` still has them
- one `cleanup_forced_subtree` on the lead, naming the child

Teardown verified: no agents, no herdr workspace, no worktree, no clone left.

**Unproven live:** the already-closed variant above. Same code path and same ordering,
covered by `test_force_clears_an_already_closed_row_the_board_still_draws`, but no fleet
was run against it.

## Tests

In `tests/test_broker.py`, in the invariant block:

- `test_force_takes_the_live_child_with_the_parent_leaves_first` — replaces
  `test_force_does_not_close_a_parent_over_its_live_child`, which pinned the reversed
  decision.
- `test_only_force_closes_over_a_live_child_and_a_sweep_never_can` — replaces
  `test_nothing_at_all_closes_over_a_live_child`; keeps the half of it that still holds.
- `test_force_clears_an_already_closed_row_the_board_still_draws` — the filed repro.
- `test_force_walks_a_deep_subtree_from_the_deepest_row_up` — three levels, because two
  cannot tell depth-ordering from parent-last.

Suite: 1262 passed.

## Branch

Built on `fix-cleanup-aliveness` (b93a0aa, the refusal-wording half of #53) as instructed,
with `origin/main` merged in first — the stalled-agent cleanup work from PR #54 landed on
main and touches the same sweep. The merge was clean.
