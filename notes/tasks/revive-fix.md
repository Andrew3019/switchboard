# Fix: _revive cannot tell the human answering from the agent itself

You own both bugs below. They are two separate code changes in one file, and you do them in
order. Do not start bug 4 until bug 3 is done and its tests pass.

## Read first, in this order

1. `notes/triage/revive-scout.md` in this worktree — the design has already been settled by
   a scout. It names the exact event query and the guard shape. **Follow it.** If you
   believe it is wrong, do not improvise: `sb tell parent` and say why.
2. The docstring of `Broker._revive` in `switchboard/broker.py` (~603-664). It argues at
   length that reviving a blocked agent is deliberate, because it is how a human typing an
   answer into a stopped agent's pane clears that agent's block. **That reasoning is sound
   and your fix must not delete the behaviour** — you are making the function able to tell
   the human answering from the agent itself, nothing more.
3. Evidence, committed on branch `bug-triage`, not pushed:
   `git show bug-triage:notes/triage/qa-revive.md`, and
   `git show bug-triage:notes/triage/group-5-block-status-misc.md`.

## BUG 3 (high) — a blocked agent un-blocks itself by running any sb command

Every `sb` command reaches `_revive`, because every verb resolves its caller through
`Broker.whoami()` (`cli.py` ~784). So a blocked agent that runs `sb status`, `sb inbox`, or
`sb plugin report-bug file` flips its own row back to `working` and logs
`unblocked reason=answered_in_pane` (broker.py:657-663) while it is still stopped waiting on
a person. It reproduced in the wild exactly that way. `sb block` is the only channel to a
person, so losing that signal means a wedged agent nobody is coming for.

**The fix, per the scout.** In `_revive`'s `blocked` branch, before flipping state back to
`working`, check whether a `turn_end` event for this agent exists with an id greater than
the `blocked` event's id. `sb block` puts the agent in `REPORTED`, so a genuine turn
boundary writes `turn_end`; an agent's own next call inside the same turn has no `turn_end`
between, because `Stop` has not fired. That is the discriminator.

- `turn_end` present after the block → a real turn boundary passed → revive as today.
- absent → the agent is still inside its own blocked turn → **leave the row blocked**, do
  not log `unblocked`, and let the command it was running proceed normally. A read-only
  command must stay read-only.
- **Fail open.** A session carrying no hooks has no `turn_*` events at all, ever. Detect
  that (`turn IS NULL` and no `turn_end` ever logged for the agent) and revive immediately,
  exactly as today. The scout's section 1 spells this out. Do not close this case.

Apply the same gate to `_revive`'s other branch (the `ended_at`/done one) as the scout
recommends.

**Known residual hole — document it in a comment, do NOT try to fix it.** If a blocked
agent's turn genuinely ends and a *later* turn is started by something other than a human
answering (a doorbell delivery, a child's notification), `turn_end` exists and the block
clears without a person having answered. That is strictly narrower than today's behaviour
and consistent with the docstring's own reasoning. Write it down; leave it.

## BUG 4 (medium-high) — a repeat `sb done` mails the parent twice

Each `sb done` call writes another `[done]` message (broker.py ~3510-3512); nothing dedupes
or refuses a repeat, and between the calls the child's own `sb` commands revive it to
working (broker.py:653). Live, one piece of work produced two reports and two parent
notifications, and the board showed only the SECOND — so a junk second summary replaced the
real one. A parent cannot tell "my child has not finished" from "my child finished and then
said something else".

**The fix, per the scout.** Bug 3's fix does not stop this on its own. `done()` itself needs
a guard: if state is already `done` at entry, log the repeat under a distinct event kind
instead of re-sending mail and ringing the parent, so the original summary stays what the
board shows. The scout's section 3 gives the shape. Follow it, including its call on whether
the second call refuses loudly or no-ops — and make sure the agent running the repeat gets a
clear message about what happened either way.

## Ruled out — do not touch it

`sb cleanup` refusing a revived child is NOT a bug. The gate is right to refuse a working
row and it costs one `--force`. Report 2026-08-11-043126 needs no work.

## File ownership — two other leads are editing broker.py right now

You own **only** `_revive` (~603-664) and `done()`'s delivery block (~3510-3512), plus your
tests. Confirmed disjoint with:
- `task-delivery-fix` — `_spawn`'s delivery block (~3244-3286) and `_took_a_turn`
  (~3288-3318);
- `stalled-agent-cleanup` — the cleanup gate (~3721-3754), the sweep exemption near
  `_finished_and_unreachable` (~4093), and `status.py`.

Do not edit inside those ranges. **If your fix turns out to need a line in the cleanup gate,
stop and `sb tell parent` before you edit it** — I have promised that lead I would serialise
behind them.

Commit `broker.py` with **explicit pathspecs only** — never `git add -a` or `-A`. Several
agents share this checkout: no `git stash`, and never leave files staged.

## Verification

**Live proof is what this is judged on, and it is the primary evidence.** Isolate with a
`git clone` of this repo into a scratch directory, check out your branch there, and drive
that clone's own `./bin/sb`. Never run a clone's `sb` from outside the clone — that silently
touches the live store. Agents you spawn in a clone are invisible to the live fleet but DO
appear in Andrew's herdr UI, so tear down everything you create. Never an unscoped `pkill`.

Prove, in the smallest runs that can tell fixed from broken:
1. A blocked agent runs `sb status` in the same turn → row STAYS blocked, question intact on
   the board, no `unblocked` event.
2. A human answering in the pane (a real new turn) → block still clears, as the docstring
   intends. This is the regression that matters most; the fix is worthless if it breaks it.
3. A second `sb done` → parent gets one report, and the board still shows the FIRST summary.

**Tests: two or three, to pin the decisions — not for confidence.** Run with
`/Users/andrew/anaconda3/bin/python -m pytest tests`. Do not teach the fake herdr new tricks
to make a test possible; skip the test instead and say plainly what is therefore unproven.

## Reporting

Commit on the current branch. Do NOT push, open a PR, or touch `main` — that is my call, not
yours. Anything you left unproven goes in your `sb done` summary: unproven and stated is
fine, unproven and silent is not. Keep the summary to a line or two of plain language and
give file paths for detail.
