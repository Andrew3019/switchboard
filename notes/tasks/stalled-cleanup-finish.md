# Task: finish and prove the stalled-cleanup fix

The agent that wrote this code died mid-turn without reporting (ironically, the exact bug
it was fixing). Its work was complete enough to commit and the suite is green, but it never
did the documentation half and never proved the new bar live. **That is your job: finish it
and prove it. Do not redesign it.**

## Read first, in this order

1. `notes/tasks/stalled-cleanup-revise.md` — the task the code was built from. The bar it
   specifies is decided and is not yours to reopen.
2. `notes/reviewer-23-stalled-cleanup-blast-radius.md` — the review that forced the current
   bar. Its five findings are the hazards you are proving are gone.
3. `notes/qa-5-stalled-cleanup-verification.md` — the verification of the *previous*,
   now-replaced bar. Useful for how it ran things; its verdicts do **not** carry over.
4. `notes/researcher-45-stalled-agent-lifecycle.md` — the map of the machinery.

`DESIGN-TRUTH.md` is the only trusted document, and **only Andrew edits it** — if you think
it needs changing, say so in your report, do not touch it. Every other doc, README and code
comment, including the four above and the new docstrings, is untrusted until you have
checked it against the code.

## The state of things

Branch `stalled-agent-cleanup`. Commit `9286b5b` holds the current bar; `65dcd53` holds the
earlier, wrong one (kept in history deliberately). Suite green at 1240.

The bar as built, in `Broker.cleanup`'s `given_up_on`: `state` is RUNNING, `agents.turn` is
still NULL, a `turn_forgotten` event exists for the row (read from the event log by
`_turns_forgotten`), and a live `_busy` re-check says it is not busy. One bar, the same
whether swept or named. `--force` is the escape below it, and the refusal names it for a
named agent. Separately, `cleanup_refused`/`cleanup_held` were added to
`status.DONE_TO_THE_AGENT` so a refusal stops resetting the idle clock of the row it
declined.

## Part 1 — the documentation half, which was never done

`cli.py` (around 250-252) describes cleanup as closing "every finished agent in your
subtree", and `protocol.md` (around 219) says the same to every agent in the fleet. After
this change a bare sweep also takes a row nobody reported an end for. Make both true. Short,
matching the surrounding voice. Check the line numbers before editing — they are from an
earlier reading of a shared checkout.

Grep for any other place in `switchboard/`, `defaults/` or `bin/` that promises cleanup only
touches finished agents, and fix those too. Do not go on a documentation tour beyond that
claim.

## Part 2 — prove it, which is what this is judged on

Live proof in an isolated instance is the primary evidence.

- `git clone` this repo into a scratch directory; a clone gets its own store via git's
  common dir. Check out the branch there and drive **that clone's own `./bin/sb`**.
- **Never run a clone's `sb` from outside the clone** — that silently touches the live
  store.
- Agents you spawn are invisible to the live fleet's store but **not** to herdr, which is
  machine-global: they appear in Andrew's spaces UI. Tear down everything you create. Kill
  only by verified pid after checking each process's cwd — **never an unscoped `pkill`**,
  one of those once killed the live fleet's collector. Leave the live collector alone.
- Smallest run that can tell fixed from broken. No endurance testing.

What must be shown:

1. **The incident row closes.** Turn edge stuck at `working`, `_forget_turn` has fired,
   `state` still `working` — a bare `sb cleanup` and a named one both close it, no
   `--force`. This is the whole point of the change.
2. **The review's three reproduced hazards are now refused**, by sweep and by name:
   - a healthy child that ran `sb tell parent "…" --needs-reply` and ended its turn;
   - the parent-unwinding sequence — closing a child must not make its parent sweepable on
     the next sweep;
   - a freshly delegated worker with no session id, past its 72 s `starting` grace.
3. **A genuinely mid-turn agent is still refused**, and the named refusal names `--force`
   while the sweep's does not.
4. **The other gates still stand** on a given-up-on row: unread mail still refuses it, live
   descendants still refuse, and nothing lifts the live-descendants gate.
5. **The verdict is spent when the agent comes back** — a row with a `turn_forgotten` that
   then takes a fresh turn (`agents.turn` non-NULL) must be refused again.
6. **The idle-clock fix works**: a refusal no longer resets the refused row's idle clock.
   QA previously observed it going 45 s back to 1 s; show that it no longer does.

## Part 3 — the tests

Check that the tests in `tests/test_broker.py` **fail against `9286b5b`'s parent** — i.e.
that they pin the *new* bar and not merely the old one. A test that passes against the
previous commit pins nothing. Report which ones you checked and how.

Two or three tests are the right number for pinning a decision; if the current set is
larger and some are redundant, say so, but do not go on a test-writing spree. **Never teach
the fake herdr new tricks to make a test possible** — skip the test and write the sentence
saying what is therefore unproven. Suite green:
`/Users/andrew/anaconda3/bin/python -m pytest tests` (the pythons on PATH look broken when
they are not).

## Out of scope

`_revive` and the `sb done` delivery block; `herdr.py` `deliver`/`_took_prompt`/
`_running_turn` and `broker.py`'s `_spawn` delivery block / `_took_a_turn`; `status.py`'s
grace constants; the board showing STALLED sooner. Those belong to other agents or to other
decisions.

## Landing

Commit on `stalled-agent-cleanup`, on top of what is there. **Do not push, do not open a PR,
do not merge, do not touch `main`** — I am integrating this myself and `main` is moving
under us. Shared checkout: no `git stash`, never leave files staged, re-read a file before
editing if it may have changed under you.

Report with `sb done`: what you documented, what the live run proved point by point, which
tests pin what, and anything you could not prove. Unproven and stated is fine; unproven and
silent is not.
