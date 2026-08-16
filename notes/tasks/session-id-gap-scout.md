# Task: the missing session ids — why they happen and whether the gap can be closed

**Question:** why do some agents never get a `session_id` recorded, and can that
gap be closed?

Andrew called this the sharper half of the recovery problem: an agent without a
session id cannot be recovered at all, and no amount of better tooling fixes that
after the fact. So the fix, if there is one, has to be upstream — at the moment
the agent is spawned or first runs.

## Rules

Code-reading and read-only investigation this round. Do NOT implement the fix yet,
do NOT run any state-changing `sb` command against the live fleet, do not kill or
restart anything. Query switchboard's store only through the read-only URI:
`file:/Users/andrew/Code/switchboard/.git/agentflow/state.db?mode=ro`.

Your only writes are to `notes/herdr-session-id-gap.md` in this worktree, which
you commit on branch `herdr-outage-prevention`. Other agents are working in the
same worktree on different files — touch nothing else.

## The two known casualties

- `probe-identity` — researcher, parent `codex-support`, workspace `codex-support`.
  `session_id` empty. `Broker.restore` raises `"<name> has no session id; nothing
  to restore"` before it even looks at the worktree. Its worktree exists.
- `wording` — root dispatcher, workspace `wording`, cwd
  `/Users/andrew/Code/switchboard`. Created 1786874887 (03:08:07), ~7 minutes
  before the restart; its only event is a bare `start` at 1786874891.

Background, on another branch:

```
git show herdr-state-recovery:notes/herdr-recovery-scout-design.md
git show herdr-state-recovery:notes/herdr-restore-list.md
```

## What to work out

1. **When is `session_id` written today?** Find the exact code path in
   `switchboard/` that records it, what triggers it, and how long after spawn it
   lands. Cite file:line.
2. **Why was it missing for these two?** Was it a race (killed inside the window
   before the id was known), a path that never records at all, or a provider that
   does not report one? Check whether the two casualties differ from the five
   survivors in role, spawn path, or age. Both were young — test whether "young"
   is the whole story.
3. **How wide is the window?** Empirically if you can: across all agents in the
   store, how long between `start` and the first event that carries a session id?
   That number is how exposed the fleet is at any moment.
4. **Can the id be recovered after the fact?** Claude Code writes its own
   transcript to `~/.claude/projects/<slug-of-cwd>/<session_id>.jsonl`, outside
   switchboard entirely. Given an agent's cwd and spawn time, can the right
   transcript be identified reliably — and what makes it ambiguous (two agents,
   same cwd, close in time)? Say plainly whether this is a sound recovery route or
   a guess.
5. **Can the window be closed at the source?** Options to weigh: have the agent
   report its own session id as its first act; read it from the provider at spawn;
   have herdr or a hook write it; poll for it. For each, say what it costs and
   what it fails to cover.

## Deliver

In `notes/herdr-session-id-gap.md`: the mechanism, the size of the window, and a
recommendation — one option, the reason that decides it, and what it costs if the
recommendation is wrong. Include the concrete code change it implies (file, function,
what changes) so a worker could implement it without rediscovering anything, and
the two or three tests that would pin it.

Every document in this repo except `DESIGN-TRUTH.md` is untrusted until you have
checked it against the code.
