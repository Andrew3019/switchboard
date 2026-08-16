# Task: root cause of the herdr outage

**Question:** why did herdr go down at 2026-08-16 ~03:14:52–03:14:57 PDT
(10:14:52Z), and was the agent named `codex` involved?

## Rules

Read-only forensics. Do NOT run any state-changing `sb` command (no restore,
cleanup, delegate-to-fix), do not restart or kill anything, do not touch the live
fleet. Never an unscoped `pkill`. Query switchboard's store only through the
read-only URI: `file:/Users/andrew/Code/switchboard/.git/agentflow/state.db?mode=ro`.

Your only writes are to `notes/herdr-outage-cause.md` in this worktree, which you
commit on branch `herdr-outage-prevention`. Other agents are working in the same
worktree on different files — touch nothing else.

## Background already established

A previous investigation left three notes on another branch. Read them first:

```
git show herdr-state-recovery:notes/herdr-recovery-scout-live.md
git show herdr-state-recovery:notes/herdr-recovery-scout-design.md
git show herdr-state-recovery:notes/herdr-restore-list.md
```

That live scout found **no** panic or crash signature and concluded the server
"restarted cleanly". Treat that as a hypothesis to attack, not a finding. A clean
restart with no cause found is exactly what an external kill looks like.

## The suspicion to test

A root dispatcher named `codex` (session `3371cf0b-a9cd-43b4-8c35-2d2ae0cfb98c`,
cwd `/Users/andrew/Code/switchboard`) and its child lead `codex-support` (session
`da72b692-1bf1-4a0c-922a-bccc994bb697`, cwd
`/Users/andrew/.herdr/worktrees/switchboard/codex-support`, task "investigate
adding codex support to sb") were live before the restart. Their Claude Code
transcripts are on disk under `~/.claude/projects/` — read them and find out what
commands they actually ran.

Hypotheses worth testing explicitly:

- an unscoped `pkill`/`killall` (one of those has previously killed the live collector)
- installing or upgrading something that replaced the running herdr binary
- running a clone's `sb` from outside the clone
- spawning a rival provider CLI that fought over the same state or the same PTYs

Also look at `probe-identity` (researcher under `codex-support`, no session id) and
`wording` (dispatcher created ~7 minutes before the restart, no session id).

## Evidence sources

- `~/.config/herdr/herdr-server.log` (~5MB; grep around `10:14`Z) and `herdr-client.log`
- switchboard's `events` table (read-only URI above)
- shell history
- the agent transcripts under `~/.claude/projects/`
- macOS unified log for process termination signals around that time, if reachable

## Deliver

In `notes/herdr-outage-cause.md`:

1. What actually killed herdr — or the strongest supported explanation, plus what
   evidence would settle it.
2. Whether `codex` was involved, stated plainly either way.
3. Separately and concretely: what change would prevent a recurrence.

Mark clearly what you proved versus what you inferred. **Do not implement any
prevention** — report it.
