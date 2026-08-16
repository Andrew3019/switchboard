# Task: record an agent's session id at spawn, so it is always recoverable

This is the sharpest half of the recovery problem. An agent with no recorded
session id cannot be restored at all — no tooling fixes that after the fact. Two
agents were permanently lost in the 2026-08-16 outage for exactly this reason.

The investigation is done and is not yours to redo. Read
`notes/herdr-session-id-gap.md` in this worktree — it has the mechanism, the
evidence, the recommendation, the concrete code change, and three tests.

The finding, in short: `session_id` is only ever written when the agent itself runs
an `sb` command (`Broker._claim_session`, fired from `whoami()`). herdr's spawn
reply never carries one. So this is **not** a narrow spawn-time race — any agent
that goes its whole life without calling `sb` once is unrecoverable for that whole
life, and the store has plenty of hour-plus examples. Recovering the id afterwards
from cwd plus timing is unreliable, because `delegate` shares one cwd between a
parent and all its children.

The recommendation to implement: reuse `output.task_arrived`'s existing
content-match — already used to confirm a spawn's first task landed — to also
capture and persist the matched transcript's session id right at spawn, before the
agent has run anything.

## Scope

You own `switchboard/output.py`, the spawn path in `switchboard/broker.py`, and
tests. Two siblings have already finished and committed in this worktree; their
work is on your branch already. **Re-read any file before you edit it** — your
copy may be stale, and `broker.py` in particular was changed after the note you
are working from was written, so its line numbers may have moved. Trust the code,
not the line numbers.

Cover the `sb start` path (`_top`) as well as `delegate`, not just one of them —
the note calls this out, and one of the two lost agents was a root dispatcher
created by `sb start`.

## Verification

- Two or three tests, in the repo's existing style, enough to pin the decision.
  Run the suite with `/Users/andrew/anaconda3/bin/python -m pytest tests`. Note:
  several agents run suites concurrently in this shared worktree, so an unrelated
  single failure that differs between runs is load, not you — re-run to confirm
  before chasing it.
- Do not teach the fake herdr new tricks to make a test possible. Skip the test and
  say what is therefore unproven.
- Live proof in an **isolated** instance is what this is judged on: `git clone` the
  repo to a scratch directory, check out this branch there, drive that clone's own
  `./bin/sb`. Never run a clone's `sb` from outside the clone. The proof that tells
  fixed from broken: spawn an agent, and before it has run any `sb` command at all,
  confirm its session id is already in the store — then confirm `sb restore` can
  actually bring it back.
- Tear down everything you create, with `sb`. **Never run `herdr workspace close`**
  — that command is what caused the outage this work exists to prevent. Never an
  unscoped `pkill`. Do not touch the live fleet.

## Deliver

Commit on branch `herdr-outage-prevention`. Do not push, do not open a PR, do not
merge — your parent integrates. In your `sb done` summary: what you changed, what
you proved live, and anything left unproven, stated plainly.
