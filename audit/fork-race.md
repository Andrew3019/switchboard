# Two spawns at the same moment, and the git write they cannot share

## What races with what

A fork ends in `git worktree add -b <name> <base>`. When the base is a REMOTE-tracking ref
— `origin/main`, which is what every top-level orchestrator forks from — git also records
the new branch's upstream in `.git/config`, and that write takes `.git/config.lock`.

The lock is a file created with `O_EXCL` and git has **no timeout for it**: it has
`core.filesRefLockTimeout` for loose refs and `reftable.lockTimeout` for reftable, and
nothing at all for the config file. So the loser does not wait. It fails on the spot with

    error: could not lock config file .git/config: File exists
    error: unable to write upstream branch configuration

and `git worktree add` exits non-zero having made no checkout — but having created the
BRANCH. herdr reports the failure, `_fork_for` raises `ForkFailed`, and that spawn's agent
never exists.

A fork from a LOCAL base (a child inheriting its parent's branch) writes no upstream and
does not race. That is why this shows up on a top orchestrator's fan-out and not on a
worker's.

Nothing else in the fork path shares the hazard. `git fetch origin main` in `_fork_base`
was tested at six concurrent, five rounds, thirty calls: no failures, no config write —
FETCH_HEAD is clobbered between them and nothing reads it. Everything after the create
(tab, `agent start`, delivery) is herdr and the store, neither of which touches
`.git/config`.

## Counts, measured

Raw git, in a clone of this repo, `git worktree add -b <n> origin/main`:

| concurrency | rounds | losers |
|---|---|---|
| 2 | 20 | **20** — one dead in every single round |

Through `sb delegate`, isolated clones driven by their own `./bin/sb`, all agents torn
down afterwards:

| branch | shape | rounds | spawns | fork failures |
|---|---|---|---|---|
| `main` | 2 concurrent | 3 | 6 | **2** |
| `main` | 6 concurrent | 1 | 6 | **2** |
| `fix-fork-race` | 2 concurrent | 3 | 6 | 0 |
| `fix-fork-race` | 6 concurrent | 1 | 6 | 0 |

Both clones forked from `origin/main` — the fix side was put on a local branch called
`main` for exactly that reason, since a clone left on its own branch would have inherited
a LOCAL base and never raced at all.

## The fix, and what it costs

`Broker._fork_lock`: an `flock` on `<git-common-dir>/agentflow/fork.lock`, held across the
`worktree create` call and nothing else. Per repo, seen from every worktree, released by
the kernel if the holder dies.

A queue, not a retry: the loser of the race leaves the branch behind, so a second attempt
at the same name meets `BranchTaken`. Waiting for a turn leaves no debris.

The wait is bounded (`timeouts.fork_lock`, 120 s) and expiring is not a failure — the
spawn forks anyway and logs `fork_lock_timeout`, because a process blocked forever on a
wedged holder is a worse version of the failure this removes.

**Cost for six concurrent spawns.** Every spawn logs `fork_queued` when it waited. From
the six-way fan-out on the fix branch:

    224 ms, 396 ms, 642 ms, 955 ms, 1374 ms

Five of six queued; the last one waited **1.4 s**, and each create takes 0.2–0.4 s. Against
a fan-out whose spawns take 28–38 s each (`agent start` dominates), that is ~4% on the
slowest spawn and nothing on the first. Wall clock for the six `sb delegate` calls: 29.3 s
on `main` — but only four of the six agents lived — and 38.0 s on the branch with all six.
Those two numbers are not comparable to each other; the `fork_queued` figures are the real
cost.

## Noticed, not fixed

Two `sb delegate` calls issued at the same moment against a **brand-new** store — one that
no `sb` command has opened yet — collide in schema creation and one dies with `sb: database
is locked`. Seen once, on the first fan-out into a fresh clone; it did not recur after any
`sb` command had run. Out of scope here and reported rather than touched.
