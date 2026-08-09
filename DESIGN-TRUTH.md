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
space on main. This is a top orchestrator. — confirmed 2026-08-09

**Anything that might need code changes.** It gets a workspace/worktree, and an
orchestrator. That agent can be called `<name>-lead`. — confirmed 2026-08-09

**Where each spawn lands.** `sb start` = new bare space + orchestrator. Top spawns a
bare agent = new worktree/space and agent, and that agent cannot spawn other agents.
Top spawns an orchestrator = same thing. An orchestrator spawning anything = new tab in
the same exact space. So only the top ever creates a space: a sub-orchestrator a lead
spawns is a tab in the lead's space, and its whole subtree stays in that one space.
(This has not been the case.) — confirmed 2026-08-09

**When a workspace lead finishes.** It should clean up, push the PR if relevant,
summarize, and `sb block`. (More to come as part of a general process CUJ.) — confirmed
2026-08-09

---

## Product decisions

### General

**Everything an agent might need to know about arrives at spawn** — that the thing
exists, and when to use it. The agent can then go in and poke it. Agents cannot be
trusted to take the initiative and work out what is available. Put anything an agent
might need at spawn for now; we can clean up and prune later, but we want to get things
working first. — confirmed 2026-08-09

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

**A workspace orchestrator's job is to orchestrate other agents and stuff.** — confirmed
2026-08-09

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

**Agents the top orchestrator spawns directly can only talk to their parent, which is
the top orchestrator, and it owns them — no other agent does.** — confirmed 2026-08-09

### Interface

**Every single view I see that is made by sb — `sb start`, orchestrators, agents, etc.
— needs to be a split pane with `sb board`.** There is no `--no-board`. — confirmed
2026-08-09

**`sb board` is navigation: I can click on an agent and it jumps to that pane.** It is
like a fake UI I can use to move around quickly. — confirmed 2026-08-09

**`sb start` focuses the pane and nothing else ever does.** Focus is not a flag; nothing
can ask for it. — confirmed 2026-08-09

**When something needs me, the board shows it, and `sb block`.** (To be explained
later.) — confirmed 2026-08-09

### Commands

**`sb delegate` figures out where a spawn lands rather than the caller passing flags for
it.** The top can spawn a space with either an orchestrator or a single worker. —
confirmed 2026-08-09

**The `--keep` / `--ephemeral` flags are removed.** The orchestrator handles cleanup
itself, and it should do this aggressively — probably literally every agent that is
done. `--include-kept` and `--leave-children` go with them: cleaning up an orchestrator
always cleans its children. — confirmed 2026-08-09

**`sb done` keeps the agent open.** It is just a status update and a message for the
orchestrator, which then decides whether to close it. — confirmed 2026-08-09

**Cleanup closes the agents, closes the tab, and closes the entire space and deletes the
worktree if everything else is closed too.** — confirmed 2026-08-09

**`sb status` is not for Andrew — only `sb board` is.** — confirmed 2026-08-09

**`sb ask` is removed — there is `tell` only, and nothing an agent does blocks.** Its
one useful part becomes `tell --needs-reply`, which inserts a static prompt saying you
must reply to that agent at some point, since it is waiting for a reply. — confirmed
2026-08-09

**`sb tell` has three delivery modes, and the `sb interrupt` verb is deleted — that is
now one of them.** — confirmed 2026-08-09

- **next turn** (the default). The doorbell is sent instantly; the agent's own system
  queues it and delivers it at its next turn boundary — the same as sending a message to
  Claude while it is working. It waits for nothing and cancels nothing.
- **when idle.** sb holds the doorbell and rings it only once the agent is idle: no more
  turns, not doing any more work.
- **interrupt.** Injected mid-turn. What the agent was doing is cancelled.

**`sb tell` is for agents only, both ways round.** Andrew does not use it — he types
directly into the session — and it cannot address a human. Anything needing a human is
`sb block`. There is no human inbox. — confirmed 2026-08-09

**An agent blocking writes the full message in the chat first — "need human input: ..."
at full length — and then calls `sb block`.** Andrew will not see the `why`; it is just
for bookkeeping. This must be made clear. — confirmed 2026-08-09

**`sb inspect` is how Andrew reads a blocked agent's full message, and it should show
more tail — like 100 lines.** — confirmed 2026-08-09

**`sb restore` is gone if the worktree is gone.** — confirmed 2026-08-09

**`sb inbox --peek` stays, and it must be clear that once a message is read it will not
be brought up again.** — confirmed 2026-08-09

**A workspace forks from `origin/main` by default.** — confirmed 2026-08-09

**`sb wait` has no reason to exist.** — confirmed 2026-08-09

**`sb log` is not for Andrew either, but it stays — it could be useful.** — confirmed
2026-08-09

**`sb presets` needs a parameter to list, and one to apply the prompt to the current
chat or just read it.** Picking a preset should inject a prompt. This must be known to
all sessions. — confirmed 2026-08-09

**`sb models` is fine as it is.** — confirmed 2026-08-09

**Andrew will never call these commands himself other than `sb start`.** — confirmed
2026-08-09

---

## Explicitly rejected

*Empty until Andrew confirms entries. Things ruled out belong here, so they stay ruled
out.*

---

## Open / undecided

*Questions Andrew has named as open — listed here so they are visibly undecided rather
than quietly assumed.*

**What the mechanism is that makes the top/workspace orchestrator difference true,
beyond the prompt saying so.** We need to find it. It can be different prompts with
conditional routing, or a reminder, preset, etc. Not to be found now. — raised
2026-08-09
