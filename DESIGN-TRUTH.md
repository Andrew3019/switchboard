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

Entry format: one short claim, plus the date it was confirmed.

---

## Critical user journeys (CUJs)

**Starting work.** On some terminal in a repo, I call `sb start`. It makes a new bare
space on main. This is a top orchestrator. — confirmed 2026-08-09

**Anything that might need code changes.** It gets a workspace/worktree, and an
orchestrator. That agent can be called `<name>-lead`. — confirmed 2026-08-09

**When a workspace lead finishes.** It should clean up, push the PR if relevant,
summarize, and `sb block`. (More to come as part of a general process CUJ.) — confirmed
2026-08-09

---

## Product decisions

**The top orchestrator's job is to orchestrate the creation of worktrees and new
orchestrators and workspaces.** — confirmed 2026-08-09

**The top orchestrator can also spawn well-directed bare agents, if the task is clear
and unambiguous enough** — e.g. small changes. This skips extra layers that are not
needed. — confirmed 2026-08-09

**Like any orchestrator, it can spawn discovery or scout or research agents or
whatever, to improve its decisions and actions.** — confirmed 2026-08-09

**A workspace orchestrator's job is to orchestrate other agents and stuff.** — confirmed
2026-08-09

**The orchestrator prompt is mostly good already.** — confirmed 2026-08-09

**Top and workspace orchestrators must be clearly differentiated, and some mechanism
other than the prompt must make that true as well.** — confirmed 2026-08-09

**Every single view I see that is made by sb — `sb start`, orchestrators, agents, etc.
— needs to be a split pane with `sb board`.** — confirmed 2026-08-09

**`sb board` is navigation: I can click on an agent and it jumps to that pane.** It is
like a fake UI I can use to move around quickly. — confirmed 2026-08-09

**`sb start` should focus the pane. Anything else should never focus on spawn.** —
confirmed 2026-08-09

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
