# The doorbell's working directory — the crash, the fix, and the first ring that landed

Run 2026-08-10 01:05–02:05 by agent `fix-doorbell-cwd`, in an isolated `git clone` of the
repo driven only by its own `./bin/sb`. Nothing installed, nothing pushed, nothing merged;
`main`, `DESIGN-TRUTH.md`, `BUILD-PLAN.md` and the installed symlink untouched.

## What was wrong

`collector._run_doorbell` ran `sb flush` with

```python
cwd = str(db_path.parent.parent)
```

`db_path` is `<git-common-dir>/agentflow/state.db`, so that is the **`.git` directory**.
`cli.main` resolves `store.worktree_root()` for every verb, `git rev-parse --show-toplevel`
refuses to run inside `.git`, and the command died before it did anything. One directory,
on every machine, whatever was on PATH — which is why the doorbell had never once rung
(`audit/phase1-acceptance-2.md` §3.3 found this; this run fixed it).

Reproduced in the clone, both halves:

```
$ cd <clone>/.git && <clone>/bin/sb flush
RuntimeError: not inside a git repo: fatal: this operation must be run in a work tree
$ cd <clone>       && ./bin/sb flush
rang nobody
```

## The fix

`collector._doorbell_cwd(db_path)` picks a work tree by the same rule
`store.main_checkout` follows: whatever `sb init` recorded in the store's `config.json`,
else `.git`'s parent. It reads that file directly rather than importing `store`, so the
spawned half stays importless and cannot become the thing that makes this read-only,
version-stale process write.

Tests: `tests/test_panel.py::TheDoorbellsWorkingDirectory` — five cases against **real**
repositories, because what was wrong was a real path. The load-bearing one asserts that
`store.worktree_root()` accepts the directory the doorbell picked, which is the question
the counters could not answer. Full suite: **1754 passed**.

## Does it deliver — the thing nobody had seen pass

Yes. Measured end to end in the clone, with the branch's collector running by hand
(PATH pointing at the clone's `bin/`) and `panel/demand` stamped every 5 s in place of a
board renderer:

| time | what |
|---|---|
| 01:42:19 | `dbc-lead` (an `sb start` agent, so on the branch build) delegates `worker-2` |
| 01:43:39 | `worker-2` runs `sb done "doorbell probe 2"`; the parent is mid-turn (`sleep 600`) → event `ring_deferred dbc-lead`, message 5 `delivered_at = NULL` |
| 01:43:49 … 01:59:29 | the collector spawns `sb flush` every 10 s (`DOORBELL_GAP`), each one held back because the target is still working. **`doorbell_error` stays `None` throughout** — before the fix every one of these was a traceback |
| 01:59:39 | the parent's turn ends. The next doorbell finds it idle and delivers: `herdr agent prompt dbc-lead "You have mail. Run: sb inbox"` |
| 01:59:45 | the parent has read it (`read_at`) |

Final counters: `doorbells 9, errors 0, doorbell_error None`, `last_doorbell` equal to the
second of the delivery. No `sb` command was run by me or by any agent between 01:42:05 and
the delivery, so the only thing that could have rung it is the collector — and the 10 s
cadence in the event log is `DOORBELL_GAP` exactly.

**A parent is genuinely woken by a child's report, with no heartbeat and no human.**

## What the doorbell still depends on — read this before calling it done

1. **A collector must be running, and only a board keeps one alive.** `ring_doorbell` is
   called from `collector.tick` and nothing else; the collector exits
   `panel.collector_idle_exit` (60 s) after the last stamp of `panel/demand`, and only
   `board.py` stamps it. In this run *I* stamped it. With no board open anywhere, nothing
   ticks and nothing rings — unchanged by this fix, and structural.
2. **The board that is open must be running code that has the doorbell.** A board opened
   by `sb delegate` runs with `PYTHONPATH` set to the child's worktree, which is forked
   from `origin/main` (`audit/phase1-acceptance-2.md` §2, §3.2). So on the live fleet
   today the elected collector is an `origin/main` collector, which has no doorbell at
   all. That is the fork-base problem, owned by another agent; I did not touch it.
3. **The board's own `sb` is never pinned** (§6.3 of the same audit). The collector
   spawns whatever `sb` its PATH resolves to. Until this branch is installed, that is the
   `main` build, which has no `flush` verb — so the fixed cwd alone does not make the live
   fleet ring.

In short: the crash is gone and the mechanism demonstrably works, but it only works while
a board is open *and* both that board's Python and the `sb` on its PATH are current.

## Teardown

Four throwaway agents (`dbc-lead`, `worker-1`–`worker-3`), all inside the clone, all closed
with `cleanup --force`; `herdr workspace list` afterwards holds none of them. The two
processes I started (collector, demand stamper) were killed **by pid** — no `pkill`. The
clone and `~/.herdr/worktrees/sbclone/` were deleted. The live fleet's own `worker-2`
workspace was checked before and after and is untouched.
