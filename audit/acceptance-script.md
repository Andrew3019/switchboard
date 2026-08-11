# The four criteria as a command, and the proof it goes red

Written 2026-08-10 by agent `acceptance-script` (role worker). The command is
`acceptance/accept.py`; what it is and what it cannot do is in `acceptance/README.md`.
Nothing in `switchboard/`, `tests/`, `.switchboard/`, `DESIGN-TRUTH.md` or `BUILD-PLAN.md`
was changed, and nothing was pushed or merged. The deliberate breaks below were made in a
throwaway clone under `$TMPDIR`, never in this repo.

## It passes on `main` — 2 m 18 s

`./acceptance/accept.py main`, against `main` at `19fc485`, four isolated clones:

```
switchboard fleet acceptance — branch main, cloned from …/acceptance-script
run sbarldov — logs and evidence: …/accept-sbarldov

  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [2m14s]
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 43s later; the parent woke and read it   [1m58s]
  3  a block holds until the human answers    PASS   held 54s against a sibling, released by the human's answer and read it   [1m40s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbarldov4-k: blocked, not finished — it has not reported an end'   [1m08s]

all 4 pass — the fleet is sound   (2m18s)
```

Teardown afterwards: `herdr workspace list` back to its pre-run set, `~/.herdr/worktrees`
back to its pre-run set, every clone deleted, only `run.log` left. No `pkill` was used at
any point.

Check 2 is the one runs 2 and 3 never managed to isolate, and this is the deferred path
proper: `ring_deferred` at the child's report, `delivered_at` NULL, then delivery 43 s
later with the collector's `doorbells` counter moving and **no `sb` command run by anyone**
in that clone in between (the script reads the store with read-only sqlite for the whole
window). The parent then reported `WOKEN [1] from …-c: [done] CHILD-…` in its own words.

## It goes red — each check, against a break aimed at it

A checker nobody has seen fail is not a checker. Two throwaway branches in a throwaway
clone of the repo (`/tmp/…/broken-src`), each break a single line:

| break | where | check it should redden |
|---|---|---|
| (a) `ring_doorbell` returns False immediately | `switchboard/collector.py` | 2 |
| (b) the `_is_blocked` guard in `_ring` disabled | `switchboard/broker.py` | 3 |
| (c) the sweep's `refused.notable` line disabled | `switchboard/cli.py` | 4 |
| (d) `_took_prompt` returns False — a spawn can never prove delivery | `switchboard/herdr.py` | 1 |

`./acceptance/accept.py broken-234 --repo …/broken-src --only 2,3,4` — (a)(b)(c) together:

```
  2  a child's report wakes its parent        FAIL   the report was deferred and then never delivered at all   [4m28s]
  3  a block holds until the human answers    FAIL   the sibling's message was delivered to a blocked agent   [1m10s]
  4  a sweep names what it refused            FAIL   it closed sbqxwehd4-d and said nothing at all about sbqxwehd4-k, which it refused   [1m04s]
```

with, in the evidence: `ring_deferred: 1` and `delivered_at=None` for (a);
`ring_held events: 0` for (b); `closed: sbqxwehd4-d` and nothing else printed, while
`--json` on the next sweep still carried
`{"name": "…-k", "reason": "blocked, not finished — …"}`, for (c).

`./acceptance/accept.py broken-1 --repo …/broken-src --only 1` — (d):

```
  1  a cold fan-out of six starts six         FAIL   5/6 reported; 0 false success, 5 false failure   [4m28s]
      delegate exit codes: w1=1, w2=1, w3=1, w4=1, w5=1, w6=1
      reported with their token: 5/6
      REPORTED FAILURE FOR A WORKING AGENT: …-w2 … (and w3, w4, w5, w6)
      never reported: ['…-w1']
```

which is run 4 §3's regression — a working agent reported as a failed spawn — reproduced
on purpose and caught by name.

Each break reddened its own check and left the others alone, so the four are independent
and none of them passes by accident.

## What this script found and did not fix

**Two `sb delegate`s issued at the same moment in one checkout race in `git worktree add`.**
The first version of check 1 fanned out six delegates concurrently; one died with

```
sb: herdr [fork_failed] <name> could not be given a worktree of its own, so it was not
spawned — could not open or create workspace '<name>' … [worktree_create_failed]
Preparing worktree (new branch '<name>')
error: could not lock config file .git/config: File exists
error: unable to write upstream branch configuration
```

Two forks writing `.git/config` at once; git takes `config.lock` and the loser is not
retried. It reproduces at two concurrent delegates, not six. It matters because a parent
that hands out work in one turn can easily issue two at once, and because the failure is
reported as "it was not spawned" — which is true here, so it is not the false-failure
family, but it is a fan-out that silently comes up short of what was asked for.

The script now issues its six one at a time and says so in `acceptance/README.md`, which
costs it the busy window that made run 4's false failure appear twice in forty-two spawns.
That is the one thing this command is materially worse at than an agent-hour was, and it
is worth fixing the fork race and then putting the concurrency back.
