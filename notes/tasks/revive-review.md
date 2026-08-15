# Review: the _revive block gate and the done() repeat guard

Review only. Change no code. Report what you find; do not fix it.

## What to review

Two commits on the current branch `revive-gate`: `79d31f0` and `8db0f30`. They touch
`switchboard/broker.py` (`_revive` and a new `_turn_passed_since`, ~603-730; `done()`,
~3530), `switchboard/cli.py` (a note on the done path), and add 3 tests in
`tests/test_broker.py`.

## Why it matters

`_revive` is on the path of **every** `sb` command — every verb resolves its caller through
`Broker.whoami()` (`cli.py` ~784). A wrong fix here wedges the whole fleet, so the bar is
high and the failure modes are asymmetric.

## Background, read it

- `notes/tasks/revive-fix.md` — what the worker was asked to do.
- `notes/triage/revive-scout.md` — the design the fix implements.
- The docstring of `_revive` itself. It argues that reviving a *blocked* agent is deliberate,
  because it is how a human typing an answer into a stopped agent's pane clears the block.
  That behaviour had to be preserved.

## The questions I actually want answered

1. **Does the fix preserve the docstring's behaviour?** A human typing an answer into a
   blocked agent's pane must still clear the block. If that regressed, the fix is worthless
   however well it handles the bug.
2. **Does the gate actually hold?** The discriminator is whether a `turn_end` event for the
   agent exists after its `blocked` event. Attack it: are there orderings, races, or event
   sequences where a blocked agent's own same-turn command still slips through, or where a
   genuine human answer is wrongly refused and the agent stays blocked forever?
3. **Does it fail open where it must?** A session carrying no hooks has no `turn_*` events
   ever. That case must revive immediately, exactly as today. Check the no-hooks, no-anchor
   and query-error paths really do fail open and cannot leave a row stuck blocked.
4. **The `done()` guard.** A second `sb done` must leave the parent one notification and the
   board the FIRST summary. Check the guard cannot be reached in a state where it eats a
   legitimate *first* report, and that the repeating agent is told clearly what happened.
5. **Are the 3 tests worth their weight?** They exist to pin decisions, not for confidence.
   Flag any that cannot fail in the way production fails — and say so plainly rather than
   asking for more tests.

## Known and accepted — do not report these as findings

- A later turn started by a doorbell delivery or a child notification still clears a block
  with nobody having answered. Deliberate, documented in the code, out of scope.
- The worker did not drive a real spawned Claude agent end to end (`sb start` refuses an
  agent caller inside a clone and the guard was correctly not bypassed), so "Claude Code
  really fires these hooks" is inherited from the existing activity signal. Known.
- `sb cleanup` refusing a revived child is NOT a bug and needs no work.

## Rules

Read-only: no edits, no commits, no pushing. Several agents share this checkout — no
`git stash`, never leave files staged. Two other leads are editing `broker.py` in parallel
in other line ranges; ignore their work, it is not yours to review.

If you want to prove something live, `git clone` into a scratch directory, check out this
branch there, and drive that clone's own `./bin/sb`. Never run a clone's `sb` from outside
the clone. Tear down anything you create; never an unscoped `pkill`.

Run the suite with `/Users/andrew/anaconda3/bin/python -m pytest tests`.

## Reporting

Put your verdict in your `sb done` summary, in plain language: does this ship, and if not,
what is the single most serious thing wrong with it. Lead with that. Detail goes in
`notes/triage/revive-review.md` — that file is yours alone, and it is the only file you may
write. Commit only that file.
