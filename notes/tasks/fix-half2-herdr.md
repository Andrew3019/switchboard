# Fix half 2 — a task left sitting unsubmitted in the prompt box must be rescued, not pasted twice

You own **`switchboard/herdr.py` and `tests/test_herdr.py` only**. Another agent is working in
`switchboard/broker.py` and `tests/test_broker.py` at the same time. Do not touch those two
files, or any other file, for any reason. If you believe your fix needs a change outside your
two files, stop and `sb tell parent "<what and why>" --needs-reply` instead of doing it.

## Read first

1. `notes/scout-task-delivery.md` in this worktree — a scout's map of this code, checked
   line-for-line against HEAD. Sections A, B ("Half 2"), C and D are yours. Trust it as a map
   but verify anything you are about to change.
2. The original bug evidence: `git show bug-triage:notes/triage/group-2-task-delivery.md`,
   section `2026-08-14-172112`, point 2.
3. `sb presets house-rules` and `sb presets verify` — both bind you.

## The bug

Sometimes the task text pastes into a fresh agent's prompt box but is never submitted.
`Herdr.deliver`'s recovery for that is another `agent prompt` with the same text — a second
paste into a box that already holds the first. In the filed incident both outcomes were
observed: one agent submitted the task twice as a single message, and another submitted
neither and never started a session at all, sitting forever holding two pasted copies of its
own instructions.

Nothing in the delivery path ever clears the box or sends an explicit enter. `Herdr.send_keys`
exists and would let you; its only caller anywhere in the tree is the interrupt path in
`broker.py` (which is not your file — do not touch it, only read it for the calling
convention).

Note also: `deliver`'s own docstring already *claims* the retry "types and presses enter,
carrying the stuck text in with it". That is not true of the code and never has been. Correct
that docstring as part of this fix, so it describes what the code actually does afterwards.

## The fix

Give the retry a real rescue instead of a blind second paste.

The shape I want, unless you find a reason it is wrong — in which case say so before building
something else:

- On a **retry** (not the first attempt), first try to submit whatever is already sitting in
  the box, rather than pasting again on top of it.
- Give that a short chance to show up as the proof `deliver` already waits for.
- Only if that produced nothing — the box was genuinely empty, the paste never landed at all —
  fall through to sending the prompt again.

That ordering is what keeps the common case from duplicating: if the text is in the box,
submitting it is enough; if it is not, resending is right.

**One thing you must settle before writing it:** what key names `agent send-keys` actually
accepts. Only `esc` and `enter` are attested anywhere in this repo. Find out from herdr's own
CLI (`agent send-keys --help` or equivalent) whether there is a way to *clear* the box, since
"clear then resend" is the cleaner design if it exists and "submit what's there, resend only
if nothing" is the fallback if it does not. Report which you found and which you built.

Smallest honest change. Do not refactor `_took_prompt` or `_running_turn` — the scout confirms
both already carry earlier fixes and neither is the fault here. Do not fix other things you
notice; report those to me instead.

## Proof

Two things, and the second one has a known limit you must state.

**Automated.** One or two tests in `tests/test_herdr.py`, in the shape of the existing
`DeliverTest`/`DeliverProofTest` cases (from ~line 243) — in particular the `takes_on=2` case,
which already models "doesn't take on send 1, takes on send 2". Assert on the **call
sequence**: with your fix, a rescue key call must appear before any second `agent prompt`.
The existing fake already records raw argv for calls it doesn't recognise, so this needs no
new fake capability. **Growing the fake herdr is forbidden.** If something cannot be tested
without growing it, skip the test and say plainly what is therefore unproven.

The known limit, which belongs in your summary in plain words: neither fake has any model of
pane or box *content*. So a test can prove "the retry sends a rescue instead of re-pasting",
and cannot prove "and that stops a real terminal double-submitting". Say that rather than
implying otherwise.

Run the whole suite: `/Users/andrew/anaconda3/bin/python -m pytest tests`. Report failures you
did not cause rather than fixing them.

**Live.** Prove it in an isolated `git clone` of this repo in a scratch directory, checked out
on this branch, driving that clone's own `./bin/sb`. Never run a clone's `sb` from outside the
clone. A cold, freshly created clone's first spawn is the highest-probability repro — no
artificial starving needed. Spawn an agent, then read its transcript for how many times the
task text appears: broken is twice, or absent with no session at all; fixed is exactly once.
This race is only probabilistic, so a handful of cold spawns is the right size of run — house
rules say rare faults are accepted and will surface in real use. **Do not loop hunting for the
race**, and do not endurance-test. If you cannot make it reproduce, say so plainly and report
what you did prove.

Tear down every agent and pane you create, and delete the clone. Never an unscoped `pkill` —
one of those killed the live fleet's collector once.

## Landing

Commit to the current branch when done. **Commit with explicit pathspecs only** — e.g.
`git commit switchboard/herdr.py tests/test_herdr.py -m "..."`. Never `git add -A`, never
`git commit -a`, never `git stash`, and never leave anything staged: another agent is writing
in this same worktree and you will destroy its work. If git reports an index lock, wait a
moment and retry — that is the other agent committing.

Do not push, do not open a pull request, do not touch `main`. I integrate.

## Report

`sb done` with a plain few lines: what you changed, which rescue design you built and why,
what you proved live and what you only proved in tests, and anything you left unproven.
Unproven and stated is fine; unproven and silent is not. Write any longer detail to
`notes/fix-half2-herdr.md` (yours alone) and point me at it.
