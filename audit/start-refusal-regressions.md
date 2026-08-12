# Does refusing `sb start` for agents break our own testing?

**No.** Both exposures were run live against `start-is-humans` (23bc4df, PR #18). The
acceptance gate passes all four checks, and a fleet still bootstraps in a fresh clone with
`sb delegate`. Nothing was changed on the branch; no fix was needed.

Run 2026-08-11 by agent `start-regressions`.

## What the branch does, as read

`switchboard/cli.py`, `_agent_caller` (added in b0f5973), gates only the `start` branch of
`_dispatch`. Two signals: `whoami() != HUMAN`, or `CLAUDE_CODE_SESSION_ID` /`CLAUDECODE`
present. No other command is gated. `Broker.mints_space` (`switchboard/broker.py:2518`) is
untouched, and it still returns `True` for a caller with no row — which is the caller in
every fresh clone.

## Exposure 1 — the acceptance script

`./acceptance/accept.py` never calls `sb start`. It creates every agent with
`sb delegate` (`accept.py:380, 472, 570, 585, 661`), from a script whose store has no rows
for it. `Clone.sb` shells out with `subprocess.run` and no `env=`, so the Claude Code
markers of the session I ran it from were inherited by every `sb` call — i.e. this was run
under exactly the condition that triggers the refusal, not a stripped one.

Command, from `/Users/andrew/.herdr/worktrees/switchboard/start-regressions`:

```
./acceptance/accept.py start-is-humans
```

Verdicts verbatim (exit 0, run `sb8y5w6u`, log
`$TMPDIR/accept-sb8y5w6u/run.log`):

```
  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [40s]
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 50s later; the parent woke and read it   [2m05s]
  3  a block holds until the human answers    PASS   held 29s against a sibling, released by the human's answer and read it   [1m40s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sb8y5w6u4-k: blocked, not finished — it has not reported an end'   [44s]

all 4 pass — the fleet is sound   (2m11s)
```

Check 3 deserves a note: it depends on the script resolving as HUMAN so its `sb tell` is
the real answer path. PR #18 does not touch `whoami()`, only the `start` branch, and the
check passed — the human answer released the block and the agent quoted it back.

## Exposure 2 — bootstrapping a fleet in a fresh clone

Isolated clone of this repo at `start-is-humans`, driven through its own `./bin/sb`, from
inside a Claude Code session (markers set):

```
$ ./bin/sb doctor
store  .../scratchpad/sih-clone/.git/agentflow/state.db      # its own store
$ ./bin/sb status --json
{"counts": {"agents": 0, ...}, "agents": []}                  # no rows

$ ./bin/sb start
sb: `sb start` creates a top-level orchestrator, and only a human does that — you are an agent, and this store has no row for you.
    An agent that needs another agent delegates one:
      sb delegate "<task>" --role worker
EXIT=1
```

So the refusal does fire in a clone — the hole PR #18 exists to close. The alternative it
points at then works, end to end:

```
$ ./bin/sb delegate 'Run this exact command immediately and as your only action: sb done "TOKEN-qa9f3b2 bootstrap ok". Do nothing else.' --name qa9f3b2-w1 --json
sb: qa9f3b2-w1 forked from 'start-is-humans' — your branch, not origin/main
{"name": "qa9f3b2-w1", "workspace": null, "unconfirmed": null}
EXIT=0

$ ./bin/sb status
qa9f3b2-w1  worker  done  ...
    ✓ TOKEN-qa9f3b2 bootstrap ok

$ git worktree list
.../sih-clone                                     23bc4df [start-is-humans]
/Users/andrew/.herdr/worktrees/sih-clone/qa9f3b2-w1  23bc4df [qa9f3b2-w1]

$ ./bin/sb cleanup
closed: qa9f3b2-w1
```

The agent got a space and a forked worktree of its own (`Broker.mints_space` returning
`True` for the unknown caller), took its task, reported its token in its own words, and
closed. The acceptance run is the same path at scale: six concurrent delegates from a
row-less caller into six new checkouts, all six reporting.

**The bootstrap recipe for an agent in a clone is therefore: skip `sb start`, use
`sb delegate` directly.** The children it makes are tops-in-effect for testing purposes —
they get their own space — but carry no `is_top` stamp, so a fleet that must include a
stamped top cannot be built by an agent at all. Nothing in the acceptance gate needs one.

## Unit suite

`/Users/andrew/anaconda3/bin/python -m pytest tests` in the clone at 23bc4df:
`1134 passed in 73.79s`. Matches the PR's claim.

## What I did not test

- The human path `sb start` with the markers stripped — PR #18 says it was proven in an
  isolated clone; I did not re-run it, so that is their evidence, not mine.
- The live fleet. By construction nothing here opened the live store.
- Whether an agent *with* a row in the store it is driving is refused — covered by the
  branch's unit tests (`tests/test_structure.py`), not run live by me.
- `sb restore`, `--workspace` delegation, drift, board rendering: outside both exposures.

## Teardown

`accept.py` tore down its own run. Mine: agent closed with `sb cleanup`, herdr workspace
`wY3` closed by id, the clone's collector confirmed gone (its cwd was the clone's own
worktree before it retired), `~/.herdr/worktrees/sih-clone/` and the clone removed. No
`pkill`. `herdr workspace list` afterwards shows only pre-existing live workspaces.
