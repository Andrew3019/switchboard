# Scout: how should _revive tell the human apart from the agent?

SCOUT ONLY — investigate and report, change NO files except the one report named at the
bottom. You are answering a design question for me; do not implement anything.

## Context

Two bugs, both centred on `Broker._revive` in `switchboard/broker.py` (around lines
603-664). Every `sb` command reaches `_revive`, because every verb resolves its caller
through `Broker.whoami()` (`cli.py` around line 784).

**BUG 3 (high).** A blocked agent silently un-blocks itself the moment it runs ANY other
`sb` command, including read-only ones like `sb status` or `sb inbox`. The row flips back
to working and logs `unblocked reason=answered_in_pane` (broker.py:657-663) while the
agent is still stopped waiting on a person. Reproduced in the wild: an agent blocked, then
filed a bug report with `sb plugin report-bug file` — itself an `sb` command — and the
human saw no blocked row. Every shipped prompt tells agents to file bugs and tidy up, and
all of that is `sb`, so this is not an exotic path.

Two further facts proved live, which make it worse than filed:
- The row does come back to the human's attention list, but as STALLED, and the QUESTION IS
  STRIPPED — the board says only "its turn ended without sb done" and tells the human to
  reply "wrap up and run sb done", which names the wrong problem.
- In one of two live runs the stop gate pushed the agent into an `sb done` with a
  fabricated summary, taking the row off the human's list entirely and sending its parent a
  success report for work that was actually stopped waiting on a person.

**READ `_revive`'s DOCSTRING FIRST.** It argues at length that reviving a blocked agent is
deliberate: it is how a human typing an answer into a stopped agent's pane clears that
agent's block. That reasoning is sound and must be preserved. What is broken is only that
the function cannot tell the human answering from the agent itself calling `sb`.

**BUG 4 (medium-high).** The same child done report is delivered to the parent once per
`sb done` call. Each call writes another `[done]` message (broker.py around 3510-3512) with
nothing deduping or refusing a repeat; between the calls the child's own `sb` commands
revive it to working (broker.py:653). Observed live: one piece of work produced two reports
and two parent notifications, and the board showed only the SECOND — so a junk second
summary replaced the real one. A parent cannot tell "my child has not finished" from "my
child finished and then said something else".

## What I need back — a written recommendation, not code

1. **What signals actually exist** in the store to tell "a new turn started because a human
   typed into the pane" from "the same turn continuing after `sb block`". Look at the
   `agents` table schema, the `turn` column, `blocked_at`/`ended_at` or equivalent
   timestamps, the `UserPromptSubmit` and `Stop` hooks and what they write, session ids,
   and anything herdr provides. Say concretely which are reliable and which are not — note
   that a session may carry no hooks at all, which the docstring discusses.

2. **Your recommended mechanism for bug 3**, with the runner-up and why you rejected it.
   Two shapes were offered to me, not binding:
   - (a) revive only on verbs an agent takes to ACT, not on read-only ones;
   - (b) have `sb block` stamp a marker so a same-turn `sb` call by the blocked agent itself
     does not count as an answer.

   Evaluate both and anything better. For (a), enumerate which verbs would fall on which
   side and say whether that partition is actually stable. For (b), say exactly what would
   be stamped and what would clear it.

3. **Bug 4**: where the right place is to refuse or dedupe a repeat `sb done`, and what the
   behaviour should be on the second call — refuse loudly, silently no-op, or update in
   place. Say whether fixing bug 3 alone already fixes bug 4, or whether they are
   independent.

4. **Collisions.** Two other leads are working in `broker.py` in parallel:
   `task-delivery-fix` owns `_spawn`'s delivery block and `_took_a_turn`;
   `stalled-agent-cleanup` owns the cleanup gate and board status. Flag any line ranges
   where a fix to the above would collide with theirs.

## Ruled out — do not propose work on it

`sb cleanup` refusing a revived child is NOT a bug. The gate is right to refuse a working
row and it costs one `--force`.

## Evidence — read it

Committed on branch `bug-triage`, not pushed:
- `git show bug-triage:notes/triage/qa-revive.md`
- `git show bug-triage:notes/triage/group-5-block-status-misc.md`
- `git show bug-triage:notes/triage/group-4-lifecycle.md`

These contain both the reading and the live-run transcripts.

## Output

Write your findings to `notes/triage/revive-scout.md` in this worktree. That file is yours
alone; touch nothing else. Commit only that file. Then put the recommendation itself, in a
few plain sentences, in your `sb done` summary — I act on the summary, not the file.
