# Follow-up on your _revive / done() fixes

A reviewer attacked your two commits and the verdict is that they ship: the gate holds, and
a human typing an answer into a blocked pane still clears the block. Four things to clean up.
Its full write-up is `notes/triage/revive-review.md` — read that first. Same file ownership
and commit rules as `notes/tasks/revive-fix.md`; that document still binds you.

## 1. Make the `done()` repeat guard independent (the real one)

The guard currently only fires *because* `_revive` declined to revive. On a session with no
hooks, `_revive` fails open, sets the row back to `working`, and so `done()` no longer sees
state `done` at entry — a second `sb done` mails the parent twice and the board takes the
second summary. The reviewer reproduced this.

That means bug 4 is only fixed on hooked sessions, and bug 4 is mine to fix outright. Guard
it on something durable rather than on current state — e.g. whether a done/report event
already exists for this agent — so the repeat is refused regardless of hooks and regardless
of what `_revive` did. Fail-open is right for bug 3; it is not right here. A parent must
never get two reports for one piece of work.

Do this without touching the cleanup gate. If it turns out you need a line in there, stop
and `sb tell parent` before editing — I have promised another lead I would serialise behind
them.

## 2. The test that pins the repeat guard is blind

It passes `me=` and bypasses `whoami`, so it cannot see the failure above. Once the guard is
independent, make that test able to fail the way production fails, or replace it. If it
cannot be made honest without teaching the fake herdr new tricks, **skip it and say plainly
what is unproven** — do not grow the fake.

## 3. The full table scan

`_turn_passed_since` scans the whole events table on every `sb` command issued from a done
or blocked row — 5.4ms on the live 28k-event store, and that store only grows. Bound it:
index, id-range limit, or whatever the schema already supports. Do not redesign the gate to
achieve it; the gate is correct.

## 4. Two small honesty fixes

- A wrong function name in the `_turn_passed_since` docstring.
- Your commit message over-claims bug 4 as fixed. Once item 1 lands the claim becomes true —
  make sure the final commit message says exactly what is and is not covered.

## Verification

Re-prove the three live cases you already ran, plus the new one: a second `sb done` on a
**no-hooks** session must now leave the parent one report and the board the first summary.
Same isolation rules — `git clone` to scratch, drive that clone's own `./bin/sb`, never run
a clone's `sb` from outside it, tear down everything you create, never an unscoped `pkill`.

Suite green with `/Users/andrew/anaconda3/bin/python -m pytest tests` before you report.
Commit on this branch; do not push or open a PR. State anything left unproven in your
summary.
