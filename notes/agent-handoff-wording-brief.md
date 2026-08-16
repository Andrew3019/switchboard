# Brief: agent-handoff-wording

Andrew's message, verbatim and unaltered. Do not change anything yet — inspect only.

---

we had a few recent commits about changing prompt wording so that human facing text from agents are more readable. i dont think they did enough. take this example

PR #63 merged, CI green — that's everything closed out. Nothing running.

In its words:

- Both remaining closes now resolve through the same Broker._close_target as cleanup. _stop_panes (sb workspace close) refuses and deletes nothing when a row's recorded pane can't be proved its own — --confirm does not lift it, intent is not identity. _close_board leaves the pane and logs board_close_refused but still drops the meta row, so an agent's own close isn't the board's hostage.
- Proven live in two isolated clones, before and after, for both paths: before, clone A's workspace close and its board close each killed clone B's live agent; after, both refuse and B survives.
- Closed the moved-pane gap by staging a real herdr pane move — and found that a freshly moved pane still answers to its old id on herdr 0.8.0, so the moved case isn't an observable wrong close today. The recycle case is the real one, and it's proven.
- 4 tests, each verified to fail pre-fix; suite 1281 passed. Detail: notes/close-paths-resolved-by-terminal-id.md.
- Still unfixed, stated: a board pane id recycled onto another board is invisible to herdr, and a workspace close blocked by this refusal has no escape hatch until the stranger holding the pane goes.

---
Where the whole run ended up

- Merged: #55 worktree leak · #56 cleanup aliveness · #57 interrupt delivery · #58 --force subtree · #59 ghost rows · #60 auto-mode dialog · #61, #63 close-by-identity · #62 dead-parent recording
- Issues: #40, #53, #38 closed by their merges; #41 closed as answered, status quo kept
- No PR needed: suggestions symlink, made to match bugs exactly

Two things left on your desk, neither urgent:

1. #38's original symptom is still unexplained — the modal fires after an agent's first turn, not on a cold pane, so agents wedging before any session existed had some other cause. Its own issue?
2. The escape hatch for a workspace close refused by a stranger's pane — today you wait for them to go.

All 25 agents closed; only this dispatcher is alive.

⏺ Ran 1 stop hook
  ⎿  Stop hook error: switchboard: your turn cannot end without a report. Call `sb done "<summary>"` if the work is finished — your summary is the only thing your parent ever sees — or `sb block "<why>"` if you need a human. Nothing you write in this pane reaches anyone. You will only be stopped once; if neither verb applies, say why and stop.

  Ran 1 shell command

Blocked — everything dispatched is merged, and the two open questions in my message above (the unexplained #38 wedging, and the escape hatch for a refused workspace close) are waiting on you.

✻ Cogitated for 30s

❯ explain both more ? if not urgent, just drop it since there are better thigns to work on


1.
- Merged: #55 worktree leak · #56 cleanup aliveness · #57 interrupt delivery · #58 --force subtree · #59 ghost rows · #60 auto-mode dialog · #61, #63 close-by-identity · #62 dead-parent recording
- Issues: #40, #53, #38 closed by their merges; #41 closed as answered, status quo kept
- No PR needed: suggestions symlink, made to match bugs exactly

this would be so much better formatted as a table or a list or something. instead its just all condensed into a chunk of text that i cant skim or quickly read.

2.
the sumary above that is also hard to read. it seems to be trying to force bulletpoitns while still keeping all the context possible. this is not what we want. its fine to lose some information/context as long as it isnt crutial to my understnading of it. right now, i cant understand with a skim, so my understanding is 0%. word for word, i could understand 90%. what i want is a condensed, bulletpoint version (and my claudes are running in half pane so the bulletpoitns are 2-3 lines each), 1-2lines max, easily skimmable, simple language, no random terminology that i need to stop and think about what it means, and like 70% understanding achieved.

3. Two things left on your desk, neither urgent:

1. #38's original symptom is still unexplained — the modal fires after an agent's first turn, not on a cold pane, so agents wedging before any session existed had some other cause. Its own issue?
2. The escape hatch for a workspace close refused by a stranger's pane — today you wait for them to go.

All 25 agents closed; only this dispatcher is alive.

⏺ Ran 1 stop hook
  ⎿  Stop hook error: switchboard: your turn cannot end without a report. Call `sb done "<summary>"` if the work is finished — your summary is the only thing your parent ever sees — or `sb block "<why>"` if you need a human. Nothing you write in this pane reaches anyone. You will only be stopped once; if neither verb applies, say why and stop.

  Ran 1 shell command

Blocked — everything dispatched is merged, and the two open questions in my message above (the unexplained #38 wedging, and the escape hatch for a refused workspace close) are waiting on you.

✻ Cogitated for 30s

❯ explain both more ? if not urgent, just drop it since there are better thigns to work on

  Ran 2 shell commands

Asked both — the agents that found each leftover, since they hold the detail. Each will explain what it is, what it looks like when it bites, and say plainly whether it's worth chasing or should be dropped. I'll relay their answers and you can drop either on the spot.

✻ Sautéed for 27s

※ recap: Goal was triaging and fixing all GitHub issues: all four are closed and nine PRs are merged. Two minor leftovers remain, and I've asked the two agents that found them to explain each and say whether it's worth chasing or dropping. (disable recaps in /config)

❯ herdr crashed, i was able to restore u. please restore any children u had, and tell them to restore subchildren etc. only active ones that are still working

  Ran 5 shell commands

Both restored and nudged.

- auto-mode-dialog and close-paths-identity were the only two children still working — both had gone (panes closed under them, 28m quiet, my questions never picked up). Restored, and told to read the pre-crash message and answer.
- Neither had children of its own, so there's nothing deeper to restore.
- The two "failed" notices in my inbox were from the crash itself, not real failures — their work was already merged before it.

Everything else was closed before the crash, so nothing else needs bringing back. Answers on your two questions should come through shortly.

✻ Crunched for 40s

❯ [sb: from auto-mode-dialog] You have mail. Run: sb inbox

  Ran 2 shell commands

close-paths-identity is still writing its half. Holding the #38 answer until both are in, so you get them together.

✻ Crunched for 19s

❯ [sb: from auto-mode-dialog] A child finished. Run: sb inbox. Waking is not a reason to report — if other children are still running, wait for them.

  Ran 2 shell commands

Still waiting on close-paths-identity for the second half. auto-mode-dialog is closed (its worktree kept — only a __pycache__ in it).

✻ Baked for 11s

❯ [sb: from close-paths-identity] A child finished. Run: sb inbox. Waking is not a reason to report — if other children are still running, wait for them.

  Ran 2 shell commands

Both explained, and both agents say drop it.

1. #38's unexplained wedging — drop

- It's a contradiction, not a confirmed second bug. #38 says panes sat on the auto-mode dialog before any session existed, but in v2.1.233 that modal is raised only at query_end — turn end. There's no startup-time path, so both can't be literally true.
- Most likely: the first turn did run briefly, the modal came up at its end, and everything sent after was swallowed. Hours later the task looked untouched and "it never ran" was a reasonable but wrong inference. Fits every observation, including the dismissedAt stamp showing a human answered it later.
- Second candidate: a different first-run screen — #38 never reproduced the literal dialog, only a same-shaped one, and trust-folder / auto-mode-default notice / re-login / theme picker all wedge a pane identically.
- The deciding evidence (whether those panes had a transcript) was never captured and is gone.
- Cost of ignoring: low — no data loss, just wall-clock and a confusing board. Both expensive halves are already fixed: #60 suppresses the dialog in switchboard checkouts, #57 stops an eaten interrupt reading as delivered.
- Worth carrying forward instead, if anything: the board saying "waiting on a human keypress" rather than STALLED. That covers every modal, including ones nobody has seen, and needs no diagnosis of this one.

2. The two close-path leftovers — both drop

- Board id recycled onto another board: a board pane silently vanishes from someone's screen during an unrelated cleanup. Needs a board to die on its own and land on another board and that board to be another clone's. Costs a view, not work — sb start reopens it. It corrected itself: herdr pane list does return a terminal_id for every pane, so boards could get real identity in ~a dozen lines; "invisible to herdr" was true of agent list, not pane list.
- Blocked workspace close: a workspace can't be retired until the stranger's pane goes, and --yes won't lift it. Nothing is destroyed, it self-heals as pane ids turn over, and there's an unstick today — clearing that one row's pane_id in .git/agentflow/state.db lets the close proceed without touching the stranger's pane. A proper hatch would be a "stop claiming that pane" flag (never a --force — force must not override identity), ~15 lines. Leave it unbuilt until it actually blocks you.

Both agents closed; their worktrees kept, since each holds only __pycache__/.pytest_cache. Nothing running.

⏺ Ran 1 stop hook
  ⎿  Stop hook error: switchboard: your turn cannot end without a report. Call `sb done "<summary>"` if the work is finished — your summary is the only thing your parent ever sees — or `sb block "<why>"` if you need a human. Nothing you write in this pane reaches anyone. You will only be stopped once; if neither verb applies, say why and stop.

  Ran 1 shell command

Blocked, waiting on you.

Everything dispatched this session is merged, and nothing is running. Both leftovers are explained above and both agents recommend dropping them — neither is urgent, neither risks data.

The only thing either suggested keeping is the board reporting "waiting on a human keypress" instead of STALLED. It covers every modal, including ones we've never seen, and doesn't depend on ever diagnosing the August incident. Say the word and I'll dispatch it; otherwise I'll drop all three.


followups are not good. the dispatcher should avoid piping outputs between me and agents. this should be a design truth or principle somewhere. in this case, it didnt explain the issues peoperly. i dont have context, so i dont know what decisino to make on it. im either guessing or asking for more context. here i asked for more context. And you can see that when I ask for more context, it restored the agents, and then it sent them a text and then told them to reply to the dispatcher... or the dispatcher or the lead, I think, would tell me itself. But that's not what I want. In this case, the dispatcher should restore the agents and then tell the agents to explain this specifically more and then tell them to block and then tell... and then set itself as done. So the dispatcher has done. So that way the two agents with actual contacts on this will block. I will read it. I will discuss with them. And once I reply to them, they will reply to the parent. They'll mark themselves as done and reply to the parent. see the difference here and why this is so much better. I'll first look at our prompts, inspect these scenarios that I just mentioned here, and just figure out what is wrong overall. Do not change anything yet. Do not edit anything yet.
