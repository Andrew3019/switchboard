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
a workspace does. This is a dispatcher, and its home is whatever directory `sb start` was
run from. — confirmed 2026-08-09, the dispatcher's home confirmed 2026-08-14

**Anything that might need code changes.** It gets a workspace/worktree, and a lead with
it — which is also what such an agent was already being called, `<name>-lead`. Whether a
part of the work underneath is small and clear enough for one agent end to end is then
that lead's judgement to make. — confirmed 2026-08-09, the role named `lead` and the
routing judgement moved to it 2026-08-14

**Only `sb start` ever creates a dispatcher — that is the only path.** Being a top is
stamped at that moment, and `sb delegate` branches on the stamp: a dispatcher's spawn gets
a new space and worktree, anyone else's gets a tab in the caller's space. A bare agent's
delegate is refused outright. That stamp, not the prompt, is what decides where an agent's
children land. What an agent may do *itself* is a different question, and the answer to it
is the role it was spawned as: dispatcher and lead are two roles with two prompts, not one
role told its scope. — confirmed 2026-08-09, the second half confirmed 2026-08-14

**Only a human may create a dispatcher; `sb start` is refused for agents.** —
confirmed 2026-08-11

**A fork that fails refuses the spawn and tells the parent.** It never falls back to
Andrew's own checkout. `sb start` run inside a worktree is refused too, naming the main
checkout to run it from. — confirmed 2026-08-09

**Where each spawn lands.** `sb start` = new bare space + dispatcher. A dispatcher spawns
a bare agent = new worktree/space and agent, and that agent cannot spawn other agents.
A dispatcher spawns a lead = same thing. A lead spawning anything = new tab in the same
exact space. So only the dispatcher ever creates a space: a sub-lead a lead spawns is a
tab in the lead's space, and its whole subtree stays in that one space. — confirmed
2026-08-09

**A worktree belongs to a space, not to an agent.** Everything in a lead's space shares
that lead's worktree, since a lead's spawns are tabs in it. A bare agent gets its own
worktree because it gets its own space. — confirmed 2026-08-09, read-only exception
dropped 2026-08-12

**While the work runs.** The dispatcher is just idle. It should not be monitoring. It
persists until Andrew closes it. — confirmed 2026-08-09

**When work finishes.** It depends who is done and who is reporting it. A worker that is
done reports done, and its parent lead sees it. Once all of its children are done, that
lead either reports done or blocks, depending on whether the task is fully complete:
fully complete, report done; Andrew's input needed to finish it, block. Once that is done
it reports done, and the dispatcher blocks. A lead cleans up its children, pushes the PR
if relevant, and summarizes — it does not close itself, since cleaning a lead takes its
children and it still has to report. A bare agent under the dispatcher pushes and opens
its own PR if the dispatcher said so; the dispatcher blocks for it. Once a block is
resolved the agent finishes and reports done, and the parent cleans up. — confirmed
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
carry more — the sender agent's name and the like: `[sb: from <name>]`. The channel is
the same as Andrew typing; the prefix is what tells them apart. — confirmed 2026-08-09

**switchboard is personal, for now.** — confirmed 2026-08-09

**The role list is lightly audited and fine as it is** — as long as it is known that
there are roles, and what roles there are. Every agent is told at spawn what roles exist,
and that text is generated from the roles themselves, never hardcoded. — confirmed
2026-08-09

**Which model an agent gets is set in config, and does not really matter.** — confirmed
2026-08-09

**We should detect failures, and can start with just telling the parent that it has
failed.** How detection works, whether anything retries, and what becomes of
half-finished work are all deferred for now. One known hole to be aware of while it is
deferred: a dead agent's half-finished edits sit in the worktree its whole space shares,
and nobody owns them. — confirmed 2026-08-09

**How many spaces and agents are alive at once is fine as it is right now.** — confirmed
2026-08-09

**There should not be too many hard guidelines and rules.** The reconciler catching the
general case is worth more than a rule for each one — e.g. a reply that was asked for and
never came surfaces through the idle state, and pinging either agent or a parent is
enough for them to notice and chase it. — confirmed 2026-08-09

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
explicitly told to block; an ambiguous instruction; going back and forth with the agent
itself; or finished work that needs Andrew's input or approval to complete. — confirmed
2026-08-09, ambiguous instruction confirmed 2026-08-12

### Dispatchers and leads

**The hierarchy, and what a dispatcher sits above.** A dispatcher is above spaces and
worktrees and repos — its scope is the whole of its own tree — though in practice it is
usually specific to one repo. Below it is a lead or a worker in a worktree of its own,
then another lead or worker below that, to no fixed depth: unlimited levels are allowed,
but stupid levels of it are not wanted and have not been observed. — confirmed
2026-08-09, hierarchy restated 2026-08-14

**One space per repo, and one space per dispatcher.** That is what the herdr UI should
show: a single space for each repo, a single space for each dispatcher, and everything
else nested under a repo. — confirmed 2026-08-14

**Where that model can bend, and it is deliberately left bending.** herdr picks one pane
already sitting in a repo's folder to serve as that repo's group parent. A dispatcher's
home is in that folder, so a dispatcher is a candidate like any other pane. In practice
Andrew's own manually opened pane on the repo has always been picked first, so dispatchers
have stayed separate — the other outcome has been seen once, in a throwaway clone, and
never in the live fleet. If a dispatcher were picked, that repo's space would *be* the
dispatcher, and every worktree agent for the repo, including other dispatchers' children,
would nest inside it. Nothing breaks functionally; the view is muddled. The only real fix
is a small flag in herdr, which Andrew has chosen not to take; the alternative of moving
dispatchers outside the repo would mean separating a dispatcher's home from the repo it
dispatches into, which `sb start` does not support today. So this is a known limitation,
not pending work. — confirmed 2026-08-14

**A dispatcher relays; it does not interpret.** Its job is basically to relay Andrew's
words to new leads, and to orchestrate the creation of the worktrees, workspaces and leads
that takes — without assuming too much, and without adding instructions of its own about
how the work should be approached. Whether a piece of work is to be carried end to end, or
investigated with the questions brought back first, is his to say and not the dispatcher's
to guess. If that is unclear, it does not start: it asks him to clarify intent before
dispatching. — confirmed 2026-08-14, superseding the 2026-08-09 rules that the top routes
a small, clear task straight to a bare agent itself and that it spawns scout or research
agents to improve its own decisions; both of those are a lead's judgement now

**Work that belongs in another repo is a question, not a spawn.** A dispatcher may hand
work into a different repo — but it asks first, and it blocks without starting the task.
This is a separate thing from the grouping limitation above, and the two should not be run
together: here the work was in a repo switchboard had never been set up in, and an agent
with no way to root a child there forked a worktree of *this* repo instead and appeared in
this repo's space. Nothing was adopted by anything; an agent was simply in the wrong repo.
— confirmed 2026-08-14

**A lead's children share its worktree, so the lead assigns disjoint files and
serialises anything that overlaps.** — confirmed 2026-08-09

**A lead's job is to orchestrate other agents and stuff.** Review is coordinated by it.
— confirmed 2026-08-09

**A lead can spawn discovery or scout or research agents or whatever, to improve its
decisions and actions.** — confirmed 2026-08-09

**The lead prompt is mostly good already.** It is the old orchestrator prompt, carried
through the split. — confirmed 2026-08-09

**Dispatcher and lead must be clearly differentiated, and some mechanism other than the
prompt must make that true as well.** The mechanism is the `is_top` stamp, which decides
where each one's children land. Past that, the prompt is the mechanism and is judged
enough — see Explicitly rejected. — confirmed 2026-08-09, prompt-is-enough confirmed
2026-08-14

**`orchestrator` is retired as a role name.** It survives only as a config alias for
`lead`, resolving all the way through — so a stale `--role orchestrator` gets a lead
rather than falling through to a role that cannot delegate at all. — confirmed 2026-08-14

### Scope

**Siblings are not invisible to each other; any other dispatcher's entire tree is
invisible.** Across that boundary agents cannot `sb tell` or anything else. Separating
two subtrees inside one dispatcher's tree is not something we have to do. —
confirmed 2026-08-09

**Only agents have the scope constraints.** The board is shared, and from it Andrew
crosses freely into any tree. — confirmed 2026-08-09

**Agents the dispatcher spawns directly are owned by it — no other agent owns
them — and they answer to it.** They can talk to each other, but they should not: keeping
it simple is the point. — confirmed 2026-08-09

### Interface

**Every single view I see that is made by sb — `sb start`, dispatchers, leads, agents,
etc. — needs to be a split pane with `sb board`.** — confirmed 2026-08-09

**`sb board` stays as it is right now.** It shows the full tree with its nest structure;
an archived agent shows collapsed, which it already does. Clicking an agent's name in
the tree brings that agent into focus automatically — it is like a fake UI to move
around quickly. That is all it needs for now; the rest of what it has works fine and
auditing it comes later. — confirmed 2026-08-09

**The click is not working sometimes.** Andrew first suspected the side panel; the
evidenced cause is that board rows are measured in characters rather than terminal
columns, so one wide character (an emoji, CJK) wraps a row and every row below it is off
by one — the narrow default pane is why it looked like the panel. — confirmed 2026-08-09

**`sb start` focuses the pane. Nothing else ever focuses on spawn.** Clicking a name on
the board is navigation, not a spawn, and does bring that agent into focus. — confirmed
2026-08-09

**When something needs me, the board shows it, and `sb block`.** (To be explained
later.) — confirmed 2026-08-09

### Commands

**`sb delegate` figures out where a spawn lands rather than the caller passing flags for
it.** The dispatcher can spawn a space with either a lead or a single worker. —
confirmed 2026-08-09

**The lead handles cleanup itself, and it should do this aggressively** — probably
literally every agent that is done. Cleaning up a lead always cleans its children. What
stays open below a dispatcher is not the dispatcher's call: it is decided from the board
by the person watching it. — confirmed 2026-08-09, the dispatcher half 2026-08-14

**`sb done` keeps the agent open.** It is just a status update and a message for the
parent, which then decides whether to close it. It always uses the **when idle**
delivery mode — which is also how an idle dispatcher learns a child finished: the held
doorbell fires the moment it is idle, so it is woken rather than monitoring. — confirmed
2026-08-09

**Cleanup closes the agents, closes the tab, and closes the entire space and deletes the
worktree if everything else is closed too.** Work is usually pushed before its worktree
is deleted. — confirmed 2026-08-09

**`sb status` is for agents; `sb board` is Andrew's view of the tree.** A soft
convention about what each is for, not an enforced gate. — confirmed 2026-08-09, soft
rather than gated confirmed 2026-08-12

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

**After Andrew answers a block, the agent just continues.** It clears its own block on
receiving his reply, so answering by typing into the pane is what works. — confirmed
2026-08-09

**A parent is not told that its child blocked.** It is not needed: that is more layers
and more out-of-sync problems, and the board already shows it. — confirmed 2026-08-09

**A lead may only clean up a blocked child if it reads the block as stale** — already
resolved elsewhere, or the status simply has not updated. Not a hard rule for now: an
agent clearing its own block covers most of it, and we will see how it plays out. —
confirmed 2026-08-09

**`sb inspect` is how Andrew reads a blocked agent's full message, and it should show
more tail — like 100 lines.** — confirmed 2026-08-09

**`sb restore` is gone if the worktree is gone.** Aggressive cleanup therefore destroys
it, and that is accepted: the push is the recovery path for the work, not restore. —
confirmed 2026-08-09

**`sb inbox --peek` stays, and it must be clear that once a message is read it will not
be brought up again.** — confirmed 2026-08-09

**A workspace forks from `origin/main` by default.** — confirmed 2026-08-09

**Pushing and merging are decided by the parent, which may or may not be a human.** An
agent can push if its parent says so; a lead can push if the dispatcher says so;
any agent can merge if Andrew tells some dispatcher and it passes that instruction
down. So it is never merge without asking your parent. The default shape of shipping work
is branch named for the workspace, push, open the PR, and put its URL in the summary. —
confirmed 2026-08-12, superseding the 2026-08-09 rule that merging needed Andrew's own
explicit approval and that no agent merges without asking first

**`sb workspace new` is deleted, provided the other commands cover it fully and it is
clear how to use them.** — confirmed 2026-08-09

**`sb log` is likewise for agents rather than Andrew — also soft — but it stays, it
could be useful.** — confirmed 2026-08-09, soft rather than gated confirmed 2026-08-12

**`sb presets` needs a parameter to list, and one to apply the prompt to the current
chat or just read it.** Picking a preset should inject a prompt: sb pastes it in, the
same path as any other message. This must be known to all sessions. — confirmed
2026-08-09

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

**`--keep`, `--ephemeral`, `--include-kept`, `--leave-children`.** Cleanup is the lead's,
and it always takes the children. — confirmed 2026-08-09

**Hard tool-layer enforcement of what a dispatcher may do.** No gate, no blocked verbs: a
dispatcher legitimately writes a handoff file and legitimately reads one, and a rule that
cannot tell those from doing the work would either block the job or wave the work through.
A well-written prompt is judged sufficient. — confirmed 2026-08-14

**`--no-board`.** Every sb-made view is split with the board. — confirmed 2026-08-09

**Focus as a flag.** Only `sb start` focuses on spawn, and nothing can ask for it. —
confirmed 2026-08-09

---

## Open / undecided

*Questions that are open — listed here so they are visibly undecided rather than quietly
assumed.*

*The item that used to sit here — the mechanism distinguishing the top agent from a
nested one — was answered on 2026-08-09 by the `is_top` stamp and moved to Product
decisions. That answer covered where an agent's children go; it never covered what an
agent may do itself, which is now answered too, by the split into two roles with two
prompts. Both are in Product decisions and neither is open. What follows is.*

**Real cross-repo dispatch does not exist and is not close.** The store is per repo, so a
child in another repo would have no parentage, no messaging, no status, no board row and
no cleanup reaching it — that is a multi-store fleet, not a flag. What ships instead is a
stopping rule: the dispatcher notices, asks, and starts nothing. Whether the missing thing
is ever built is undecided. — open 2026-08-14
