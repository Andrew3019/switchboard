# `acceptance/` — the four criteria, as a command

```
./acceptance/accept.py                 # the branch you have checked out
./acceptance/accept.py main            # a named branch
./acceptance/accept.py phase-2 --only 1,2
```

Exit 0 = all four pass. Exit 1 = at least one failed, and the failing checks print their
evidence. Takes **two to three minutes** on a good branch; a broken one costs longer, because a
check that fails usually fails by waiting out its deadline (measured: 4m30s).

This is not a pytest test and must not join `tests/`. It spawns real agents, costs real
tokens, and takes minutes; the suite is for things that are true without a fleet.

## What it answers

The four criteria phase 1 was judged against — and the ones every later phase needs:

| # | criterion | how it is decided |
|---|---|---|
| 1 | a cold fan-out of six really starts | six `sb delegate`s into six brand-new checkouts; each agent's own `sb done` carries a token only that agent was given, so "it took its task" is its own words. Then the two directions of misreport: a delegate that exited 0 for an agent that never took anything, and a delegate that exited non-zero for an agent that did the work (`audit/phase1-acceptance-4.md` §3) |
| 2 | a child's report wakes its parent by itself | the parent's delegate and a 45 s turn are ONE shell command, so the child reports while herdr has the parent `working` and the ring can only be **deferred**. From that moment the script runs no `sb` command in that clone at all — it reads the store with read-only sqlite — so the only thing that can deliver is the collector's doorbell. Passing needs all of: a `ring_deferred` event, `delivered_at` set afterwards, the collector's `doorbells` counter moving, and the parent finishing with its child's token in its own summary |
| 3 | a blocked agent stays blocked until the human answers | a sibling agent mails the blocked one; the block must hold and the message must stay undelivered. Then the script — which has no agent row in that clone's store, so `sb` resolves it as HUMAN, the real answer path — answers, and the agent must unblock, read, and quote the answer back |
| 4 | a sweep that refuses something says so | one finished agent and one blocked one, then a plain `sb cleanup`. It must both name what it closed and name the refusal with a reason. This is the case that stayed silent through runs 2, 3 and 4 (§5) |

Each check runs in its **own throwaway `git clone`** of the repo at the branch under test,
driven through that clone's own `./bin/sb`. A clone has its own `.git`, so
`git rev-parse --git-common-dir` finds its own `state.db` and the live fleet's store is
never opened — the method written up in `audit/isolated-instance.md`, re-proven at the
start of every run (`sb doctor` must name the clone's store, and `sb status` must be
empty). The four run at once, in four clones, because they cannot see each other's stores.

herdr is the thing a clone does **not** isolate: one daemon per machine, one global agent
name space. Every agent name here therefore carries a random run id (`sbk3f9a12-w1`), which
is what stops an isolated run from colliding with a live agent.

## What it leaves behind

Nothing: agents (`sb cleanup --force`, by name), herdr workspaces (`herdr workspace close
<id>`, selected by checkout path), the worktrees under `~/.herdr/worktrees/<run>/`, and the
clones. On success, on failure, and on Ctrl-C. There is no `pkill` of any kind; the one
process signalled by pid is each clone's own collector, whose pid the script reads from
that clone's own snapshot and checks with `ps` before sending SIGTERM.

`--keep` leaves everything running, for debugging a failure. It says so loudly. Use it and
you own the cleanup.

The run log — every command, its exit code, its whole output, and each check's raw evidence
— is written to `$TMPDIR/accept-<runid>/run.log` and **survives** the teardown. The path is
printed at the start and the end.

## What it cannot check, and a human still has to

- **The live fleet.** By construction it never touches the real store, so it says nothing
  about how the installed build behaves against Andrew's own fleet.
- **Load, beyond six at once.** The six delegates are now issued concurrently, which is the
  busy window that made run 4's false failure appear twice in forty-two spawns. That is one
  fan-out per run, so a defect of that shape — load-sensitive, ~5% — is sampled, not caught:
  a single run will still often miss it. (This was sequential for a while because six
  simultaneous delegates raced in `git worktree add`, `could not lock config file
  .git/config: File exists`, and one died `fork_failed`. That race is fixed — an flock
  around worktree creation, see `audit/fork-race.md` — so the load is back.)
- **Agent kinds other than `claude`.** The delivery proof is Claude Code's transcript;
  another kind falls through to a weaker check.
- **Anything about the WORDING of what an agent does with its instructions.** Each probe is
  told to run one command; a model that decides to explore first makes a check slower, and
  in the worst case times out and reads as a failure of the fleet. If a check fails, read
  the run log before believing it.
- **`sb restore`, `--workspace` delegation, drift, the board's own rendering.** Not covered
  at all.

## Proving the checker itself

A checker nobody has seen fail is not a checker. To watch one go red, clone the repo
somewhere throwaway, break something on a branch there, and point the script at it:

```
git clone ~/Code/switchboard /tmp/broken-src
cd /tmp/broken-src && git checkout -b broken main
#  ... e.g. make collector.ring_doorbell return False immediately ...
git commit -am "deliberate break"
./acceptance/accept.py broken --repo /tmp/broken-src --only 2
```

Done for all four; the results are in `audit/acceptance-script.md`.
