# DESIGN-TRUTH.md — what Andrew has actually confirmed

The confirmed design truth for switchboard. Critical user journeys, product decisions,
and the things that have been ruled out — held to a much higher bar than any other doc
in this repo, because everything else may be inferred and this may not.

## The rules of this file

**Everything in here is confirmed by Andrew himself. Nothing enters it any other way.**

- **Agents must not add, edit, reword, or "improve" entries.** Only Andrew adds entries —
  or an agent transcribing something Andrew said verbatim in that same conversation.
- **No inference.** Extrapolation, "this seems consistent with", something read out of
  the code or git history, and conclusions another agent reached are all disallowed. An
  entry is a thing Andrew said, not a thing that follows from what he said.
- **Read this file first when building here, and do not contradict it.** If a task looks
  like it requires contradicting an entry, stop and ask Andrew rather than proceeding.
- **Absence is not a decision.** If something is not in this file it is undecided, not
  free. An unconfirmed assumption gets flagged as one — never silently baked in.
- **If in doubt, leave it out.** Uncertain or half-remembered items do not go in. A thin
  file that is entirely true is the point; a fuller file that is partly guessed is worse
  than no file.
- **Every addition triggers a pass over the whole file.** Whoever writes an entry then
  re-reads all of it and leaves it consistent: contradictions resolved, overlapping
  entries merged, anything redundant removed. Where two statements disagree, the newest
  one wins and the older goes — and Andrew is told what was dropped.

Entry format: one short claim, plus the date it was confirmed.

---

## Critical user journeys (CUJs)

**Starting work.** On some terminal in a repo, I call `sb start`. It makes a new bare
space on main — bare meaning no worktree of its own; forking from `origin/main` is what
a workspace does. This is a top orchestrator. — confirmed 2026-08-09

**Anything that might need code changes.** It gets a workspace/worktree. Unless it is
small and clear enough for one agent end to end, it gets an orchestrator with it, and
that agent can be called `<name>-lead`. — confirmed 2026-08-09

**Where each spawn lands.** `sb start` = new bare space + orchestrator. Top spawns a
bare agent = new worktree/space and agent, and that agent cannot spawn other agents.
Top spawns an orchestrator = same thing. An orchestrator spawning anything = new tab in
the same exact space. So only the top ever creates a space: a sub-orchestrator a lead
spawns is a tab in the lead's space, and its whole subtree stays in that one space.
(This has not been the case.) — confirmed 2026-08-09

**A worktree belongs to a space, not to an agent.** Everything in a lead's space shares
that lead's worktree, since a lead's spawns are tabs in it. A bare agent gets its own
worktree because it gets its own space. The only time we do not use a worktree is a
read-only task that is 100% clear we will not need a write for later on. — confirmed
2026-08-09

**While the work runs.** The top orchestrator is just idle. It should not be monitoring.
It persists until Andrew closes it. — confirmed 2026-08-09

**When work finishes.** A lead cleans up its children, pushes the PR if relevant, and
summarizes — it does not close itself, since cleaning an orchestrator takes its children
and it still has to report. It
blocks Andrew itself while it still needs something from him; when the work is complete
it reports done to the main orchestrator and the main orchestrator blocks. For a bare
agent under the top, the top blocks. The block does not matter to what follows: once it
is resolved the agent finishes and reports done, and the parent cleans up. — confirmed
2026-08-09

---

## Product decisions

### General

**If it needs to be known, it is known at spawn.** An agent needs to know a thing exists
and that it can call it — not specifically how to use it; it can then go in and poke it.
Agents cannot be trusted to take the initiative and work out what is available. What
needs to be known differs by agent and by role: not every plugin for every agent. Put
what is needed at spawn for now; we can clean up and prune later, but we want to get
things working first. — confirmed 2026-08-09

**How herdr actually talks to Claude.** It types into the chat box and presses enter, so
a message from sb arrives looking exactly like one Andrew typed — they are the same
thing to Claude. If Andrew is halfway through typing when a message is sent, the
half-written text goes along with it, because sb pastes and hits enter. While Claude is
working, a message is queued by Claude's own system and delivered on the next turn.
Interrupt is pressing escape on the chat window, which interrupts the model, and then
the message goes in directly without waiting. — confirmed 2026-08-09

**Every sb message is prefixed so it is clearly an sb message**, and the prefix can
carry more — the sender agent's name and the like. The channel is the same as Andrew
typing; the prefix is what tells them apart. — confirmed 2026-08-09

**switchboard is personal, for now.** — confirmed 2026-08-09

**The role list is lightly audited and fine as it is** — as long as it is known that
there are roles, and what roles there are. — confirmed 2026-08-09

**Which model an agent gets is set in config, and does not really matter.** — confirmed
2026-08-09

**We should detect failures, and can start with just telling the parent that it has
failed.** How detection works, whether anything retries, and what becomes of
half-finished work are all deferred for now. — confirmed 2026-08-09

**How many spaces and agents are alive at once is fine as it is right now.** — confirmed
2026-08-09

**A reconciler runs on a loop — maybe the same loop `sb board` runs on.** If an agent is
idle and neither blocked nor done, it pings that agent to say it should probably report
done or blocked, unless it is awaiting instructions. The ping goes to the agent itself
rather than to its parent, because the agent has more context on what its true status
is. That is how we avoid stale idle agents. — confirmed 2026-08-09

**Human-facing output is concise, skimmable and well formatted.** That covers anything
an agent puts in front of Andrew, including what it writes before `sb block`. Prefer
bullet points, lists, nested lists and diagrams — things that can be visually skimmed.
Break into sections where it helps, but do not overdo the spacing. Say what you did,
what the result is, then any questions, numbered, each with a recommended answer. —
confirmed 2026-08-09

**Agents should avoid blocking unless it is really needed** — a genuine, big,
behaviour-changing design question; being blocked on running some command; being
explicitly told to block; or going back and forth with the agent itself. — confirmed
2026-08-09

### Orchestrators

**The top orchestrator is everything: its scope is the whole of its own tree, and its
job is to orchestrate the creation of worktrees and new orchestrators and workspaces.**
It is above that layer. — confirmed 2026-08-09

**A small task that a single agent can do end to end without interruption goes to a bare
agent; otherwise, an orchestrator.** The top spawning a well-directed bare agent
directly is how a clear, unambiguous task — e.g. a small change — skips extra layers
that are not needed. — confirmed 2026-08-09

**Like any orchestrator, it can spawn discovery or scout or research agents or
whatever, to improve its decisions and actions.** — confirmed 2026-08-09

**A lead's children share its worktree, so the lead assigns disjoint files and
serialises anything that overlaps.** — confirmed 2026-08-09

**A workspace orchestrator's job is to orchestrate other agents and stuff.** Review is
coordinated by it. There is no prompt for that yet, so nothing about how it runs is
anchored here — Andrew will have prompts for it. — confirmed 2026-08-09

**The orchestrator prompt is mostly good already.** — confirmed 2026-08-09

**Top and workspace orchestrators must be clearly differentiated, and some mechanism
other than the prompt must make that true as well.** — confirmed 2026-08-09

### Scope

**Siblings are not invisible to each other; any other top orchestrator's entire tree is
invisible.** Across that boundary agents cannot `sb tell` or anything else. Separating
two subtrees inside one top orchestrator's tree is not something we have to do. —
confirmed 2026-08-09

**Only agents have the scope constraints.** The board is shared, and from it Andrew
crosses freely into any tree. — confirmed 2026-08-09

**Agents the top orchestrator spawns directly are owned by it — no other agent owns
them — and they answer to it.** They can talk to each other, but they should not: keeping
it simple is the point. — confirmed 2026-08-09

### Interface

**Every single view I see that is made by sb — `sb start`, orchestrators, agents, etc.
— needs to be a split pane with `sb board`.** — confirmed 2026-08-09

**`sb board` stays as it is right now.** It shows the full tree with its nest structure;
an archived agent shows collapsed, which it already does. Clicking an agent's name in
the tree brings that agent into focus automatically — it is like a fake UI to move
around quickly. That is all it needs for now; the rest of what it has works fine and
auditing it comes later. — confirmed 2026-08-09

**The click is not working sometimes.** Andrew believes this is because of the side
panel. — confirmed 2026-08-09

**`sb start` focuses the pane. Nothing else ever focuses on spawn.** Clicking a name on
the board is navigation, not a spawn, and does bring that agent into focus. — confirmed
2026-08-09

**When something needs me, the board shows it, and `sb block`.** (To be explained
later.) — confirmed 2026-08-09

### Commands

**`sb delegate` figures out where a spawn lands rather than the caller passing flags for
it.** The top can spawn a space with either an orchestrator or a single worker. —
confirmed 2026-08-09

**The orchestrator handles cleanup itself, and it should do this aggressively** —
probably literally every agent that is done. Cleaning up an orchestrator always cleans
its children. — confirmed 2026-08-09

**`sb done` keeps the agent open.** It is just a status update and a message for the
orchestrator, which then decides whether to close it. It always uses the **when idle**
delivery mode — which is also how an idle top learns a child finished: the held doorbell
fires the moment the top is idle, so it is woken rather than monitoring. — confirmed
2026-08-09

**Cleanup closes the agents, closes the tab, and closes the entire space and deletes the
worktree if everything else is closed too.** Work is usually pushed before its worktree
is deleted. — confirmed 2026-08-09

**`sb status` is not for Andrew — only `sb board` is.** — confirmed 2026-08-09

**There is `tell` only. No agent ever waits on another agent.** `tell --needs-reply`
inserts a static prompt saying you must reply to that agent at some point, since it is
waiting for a reply. — confirmed 2026-08-09

**`sb tell` has three delivery modes.** — confirmed 2026-08-09

- **next turn** (the default). The doorbell is sent instantly; the agent's own system
  queues it and delivers it at its next turn boundary — the same as sending a message to
  Claude while it is working. It waits for nothing and cancels nothing.
- **when idle.** sb holds the doorbell and sends it once the agent marks itself idle —
  no more turns, and if we waited an hour there would be no new activity. That is a safe
  idle signal, and herdr's status is the more accurate place to derive it from. A
  blocked agent is not idle: when-idle mail is held until its block is answered, so a
  reply is never buried under it.
- **interrupt.** Injected mid-turn, cancelling what the agent was doing. Used when we
  need to change course, or the agent is doing something wrong.

**`sb tell` is for agents only, both ways round.** Andrew does not use it — he types
directly into the session — and it cannot address a human. Anything needing a human is
`sb block`. — confirmed 2026-08-09

**An agent blocking writes the full message in the chat first — "need human input: ..."
at full length — and then calls `sb block`.** Andrew will not see the `why`; it is just
for bookkeeping. This must be made clear. — confirmed 2026-08-09

**After Andrew answers a block, the agent just continues.** — confirmed 2026-08-09

**A lead may only clean up a blocked child if it reads the block as stale** — already
resolved elsewhere, or the status simply has not updated. — confirmed 2026-08-09

**`sb inspect` is how Andrew reads a blocked agent's full message, and it should show
more tail — like 100 lines.** — confirmed 2026-08-09

**`sb restore` is gone if the worktree is gone.** — confirmed 2026-08-09

**`sb inbox --peek` stays, and it must be clear that once a message is read it will not
be brought up again.** — confirmed 2026-08-09

**A workspace forks from `origin/main` by default.** — confirmed 2026-08-09

**Who merges depends, but merging needs explicit approval from Andrew.** — confirmed
2026-08-09

**`sb log` is not for Andrew either, but it stays — it could be useful.** — confirmed
2026-08-09

**`sb presets` needs a parameter to list, and one to apply the prompt to the current
chat or just read it.** Picking a preset should inject a prompt. This must be known to
all sessions. — confirmed 2026-08-09

**`sb models` is fine as it is.** — confirmed 2026-08-09

**Andrew will never call the spawn and lifecycle commands himself, other than
`sb start`.** The surfaces that are his are the board, the session he types into, and
`sb inspect` for reading a blocked agent. — confirmed 2026-08-09

---

## Explicitly rejected

*Ruled out, so they stay ruled out. The decision each one came from is in Product
decisions; this is the list of what no longer exists.*

**The human inbox — 100% removed.** It is confusing, and Andrew cannot see the messages.
— confirmed 2026-08-09

**`sb ask`.** No agent waits on another agent. — confirmed 2026-08-09

**`sb wait`.** It has no reason to exist. — confirmed 2026-08-09

**`sb interrupt` as a verb.** Interrupting is a delivery mode of `tell`. — confirmed
2026-08-09

**`--keep`, `--ephemeral`, `--include-kept`, `--leave-children`.** Cleanup is the
orchestrator's, and it always takes the children. — confirmed 2026-08-09

**`--no-board`.** Every sb-made view is split with the board. — confirmed 2026-08-09

**Focus as a flag.** Only `sb start` focuses on spawn, and nothing can ask for it. —
confirmed 2026-08-09

---

## Open / undecided

*Questions Andrew has named as open — listed here so they are visibly undecided rather
than quietly assumed.*

**What the mechanism is that makes the top/workspace orchestrator difference true,
beyond the prompt saying so.** We need to find it. It can be different prompts with
conditional routing, or a reminder, preset, etc. Not to be found now. — raised
2026-08-09
