# Task: implement the one-command restore sweep

Andrew wants one command that brings back everything that was live before a herdr
restart, into the same herdr space it came from — instead of five `sb restore`
calls typed by hand.

The design is already done and is not yours to redo. Read
`notes/herdr-oneshot-restore-design.md` in this worktree — it has the command
shape, the selection query, ordering, idempotency, a failure-mode table, four
tests, and exact file:line references. Implement it.

## Scope — yours and nobody else's

You own `switchboard/broker.py`, `switchboard/cli.py`, and `tests/test_broker.py`.
Another agent is working in this same worktree on `acceptance/accept.py` and
documentation — do not touch those. A third change to `switchboard/output.py` and
`broker._spawn` (session-id capture at spawn) is queued **behind** you and will be
done by someone else after you commit; leave it alone, do not anticipate it.

Two pieces, both in the design:

1. **The workspace-id fallback bug.** Restore today puts an agent back in a random
   tab rather than its named herdr space, because the recorded `workspace_id` is
   stale after a restart and 404s, and the code never falls back to re-resolving
   the space by name — the fallback exists but is dead on this path
   (`broker.py:4603-4604`, resolve via `self._workspace_id(a["workspace"])`). Fix
   that first; it is small and it is what makes "the same space it came from"
   actually true. Pane/terminal ids are genuinely unrecoverable — do not attempt
   them.
2. **The sweep itself.** Selection keys off confirmed-gone rows
   (`state='failed'` + `ended_at`) unioned with the transient `absent_since`
   window — not `absent_since` alone, which clears itself before a human gets to
   running recovery. Parents before children. Idempotent: a second run refuses
   already-live agents cleanly rather than erroring.

## Constraints

- **Keep the cross-tree boundary.** The design recommends *not* relaxing it: an
  agent-run sweep only ever recovers its own tree, and only the human sees the
  whole store. That means "one command that gets everything" is a command the
  human runs — say so plainly in `--help`. Do not widen the boundary.
- Agents with **no recorded session id** cannot be restored. Exclude them from the
  selection, but **name them in the report** — silently dropping them is the
  failure mode Andrew explicitly cares about.
- A herdr that is unreachable must refuse the whole sweep once, with one clear
  message. It must never be read as "nothing to restore".

## Verification

- Automated tests: the design names four; write two or three of them — enough to
  pin the decisions, not to build confidence. Run the suite with
  `/Users/andrew/anaconda3/bin/python -m pytest tests`. Do not teach the fake
  herdr new tricks to make a test possible — skip the test and say what is
  therefore unproven.
- Live proof is what this is judged on, and it must be **isolated**: `git clone`
  this repo into a scratch directory, check your branch out there, and drive that
  clone's own `./bin/sb`. Never run a clone's `sb` from outside the clone — that
  silently touches the live store. Agents you spawn in the clone are invisible to
  the live fleet but **do** appear in Andrew's herdr UI, so tear down everything
  you create. Never an unscoped `pkill`.
- **Do not** run `herdr workspace close` for teardown, ever, on any workspace. That
  single command is what caused the outage this whole investigation is about — it
  closes every workspace that is a linked git-worktree of the same repo. Tear down
  with `sb`. See `notes/herdr-close-mechanism.md`.
- The smallest run that tells fixed from broken is: agents live in the clone, kill
  their panes, run the sweep, confirm they come back in their named spaces.

## Deliver

Commit on branch `herdr-outage-prevention`. Do not push, do not open a PR, do not
merge — your parent integrates. In your `sb done` summary: what you implemented,
what you proved live, and anything you left unproven, stated plainly.
