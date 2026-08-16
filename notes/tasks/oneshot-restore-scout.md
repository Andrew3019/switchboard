# Task: design one-command recovery after a herdr restart

**Question:** what would it take for a single `sb` command to bring back
everything that was live before a herdr restart — into the same herdr space and
panes it came from?

Andrew's words: recovery today is "five commands typed by hand"; he wants one
command that restores everything that was live, into the same herdr space and
panes it came from.

## Rules

Design and code-reading only, this round. Do NOT implement anything yet, do NOT
run any state-changing `sb` command against the live fleet (no restore, no
cleanup, no delegate), do not kill or restart anything. Query switchboard's store
only through the read-only URI:
`file:/Users/andrew/Code/switchboard/.git/agentflow/state.db?mode=ro`.

Your only writes are to `notes/herdr-oneshot-restore-design.md` in this worktree,
which you commit on branch `herdr-outage-prevention`. Other agents are working in
the same worktree on different files — touch nothing else.

## Background already established

Read these first (they live on another branch):

```
git show herdr-state-recovery:notes/herdr-recovery-scout-design.md
git show herdr-state-recovery:notes/herdr-restore-list.md
git show herdr-state-recovery:notes/herdr-recovery-scout-live.md
```

Key facts from that work, to verify rather than assume:

- The signal that marks "this agent vanished in the restart" is
  `agents.absent_since` — set on the first status read that finds a pane gone,
  cleared when it is seen again. Seven agents shared one `absent_since` value.
- Five were restorable; two were not, because no `session_id` was ever recorded.
  (The session-id gap is a separate agent's task — note where it bites you, but do
  not solve it.)
- `sb restore` refused to reach across into another dispatcher's tree, so **only
  Andrew** could run the five restores. That restriction is central to this task:
  understand exactly what it is, why it exists, and whether a one-command recovery
  can honour it or must change it.

## What to work out

- What `sb restore` does today, end to end: what it needs, what it validates,
  what it recreates, and how it decides which herdr space/pane an agent lands in.
- Whether "the same space and panes it came from" is even recoverable from what is
  stored — pane/terminal ids are documented as **not stable** across a herdr
  restart, so say what identity a restored pane can actually be given, and what is
  irretrievably lost.
- What the one command should be: its name and shape, what it selects by default
  (the crash cohort? everything with `ended_at IS NULL` and a live absence?), what
  it does about agents it cannot restore, whether it is idempotent if run twice,
  and what it prints.
- Who may run it, given the cross-tree restriction. If it needs to be run by the
  human, say so; if the restriction can be safely relaxed for this one path, say
  exactly why and what the blast radius is.
- Failure modes: worktree gone, transcript gone, workspace retiring, agent already
  live, herdr not up yet, two people running it at once.

## Deliver

In `notes/herdr-oneshot-restore-design.md`: a design a worker could implement
without rediscovering anything — command shape, selection rule, ordering
(parents before children?), the exact code paths in `switchboard/` that change,
and the two or three tests that would pin it. Flag anything you could not
determine from the code and would need to prove live.

Cite file:line for every claim about current behaviour. Every document in this
repo except `DESIGN-TRUTH.md` is untrusted until you have checked it against the
code.
