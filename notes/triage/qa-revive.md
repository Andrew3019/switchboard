# QA — is `Broker._revive`'s behaviour a bug, or the documented accepted cost?

Adversarial verification for `bug-triage`. Live proof throughout: an isolated `git clone`
of this repo at `234c3bb` (verified `switchboard/broker.py` byte-identical to the worktree),
driven only by that clone's own `./bin/sb`, with its own store at
`<clone>/.git/agentflow/state.db`. Four real Claude agents (`--model cheap`), all torn down.

## Verdicts

| # | Question | Verdict | Severity |
|---|---|---|---|
| 1 | blocked half — does the human still see it? | **STILL BROKEN** | high |
| 2a | `sb cleanup` refuses a revived child | **NOT A BUG** | low, costs one `--force` |
| 2b | duplicate `done` delivered to the parent | **STILL BROKEN** | medium-high |
| 3a | `broker.py:4114` "safe against `_revive`" | **NOT A BUG** — comment true | — |
| 3b | `status.py:1070` "`_revive` … brings it back" | **NOT A BUG** — comment true, proven live | — |

---

## Q1 — the blocked half. STILL BROKEN, high.

Two live runs, same command in both: an agent whose whole task was to run
`./bin/sb block "TESTQ1… which database should I use" && ./bin/sb log` in one shell line.

### The docstring's own claim is TRUE, and I want that on the record

Agent `blocktest2` (told to stop when the stop gate nagged it):

```
$ ./bin/sb status --needs-me
blocktest2  worker  idle  done  -  33s  23s  blocktest2  << STALLED
NEEDS YOU
  blocktest2  stalled 23s — its turn ended without sb done  →  sb tell blocktest2 "wrap up and run sb done"
```

So `broker.py:622-628` is right that the row "does not vanish" and "comes back to NEEDS YOU
under a different heading". Verified. The event log holds both rows exactly as promised:

```
blocked    {"why": "TESTQ1B which database should I use"}   40s ago
unblocked  {"reason": "answered_in_pane"}                   40s ago   <- same second, no human involved
stop_gate_blocked                                           38s ago
```

### What the docstring does not claim, and what actually breaks

**(a) The question is stripped out of every headline readout.** The board and `--needs-me`
say *"its turn ended without sb done"* and offer *"sb tell blocktest2 'wrap up and run sb
done'"*. A human following the board's own instruction answers a question they were never
shown with "wrap up" — and `DRIFT` repeats the same wrong remedy. The reason survives only
in `sb log` and in `sb inspect <name>`'s RECENT EVENTS, and nothing on the board tells the
human there is a question there to go looking for. Contrast `broker.block`'s docstring at
line 3553: *"`sb status --needs-me` lists this agent with `why` for as long as it stays
blocked"* — after a self-revive it stays listed and the `why` is gone.

**(b) The row can leave the human's list altogether, and this is the real defect.** The
docstring reasons about a turn that simply ends. **The shipped stop gate never lets that
happen on the first stop.** `hooks.stop_gate` returns None for `state in REPORTED =
("done","blocked","failed")` — but `_revive` has already moved the row to `working`, so the
gate fires and hands the agent `hooks.BLOCK_REASON`, whose first offered verb is `sb done`.

Agent `blocktest` (identical command; explicitly told *not* to call `sb done`) did this:

```
t+0   blocked            {"why": "TESTQ1 which database should I use"}
t+0   unblocked          {"reason": "answered_in_pane"}
t+3   stop_gate_blocked
t+17  done               {"summary": "Ran the exact test command as instructed… Block succeeded
                          (status: blocked), then log ran immediately after…"}
```

Final state `done`. Not on `--needs-me`, not STALLED, no drift, `sb cleanup` will happily
close it. The human's question is gone from the board, and the parent received a `done` —
a report of success — for work that was stopped waiting on a person.

**Honest limit:** which of the two outcomes you get is model behaviour, and I have n=1 for
each. I did not measure a rate. What is *structural*, and is not a matter of model choice,
is the pressure: the revive puts the row in the one state the stop gate refuses, and the
gate's own text names `sb done` before `sb block`.

**Call:** file it. The reason-loss (a) alone strands a question nobody will answer; (b)
turns it into a false success report. The docstring's stated cost is accurate as far as it
goes and is not the whole cost.

---

## Q2 — the finished half.

Agent `donetest`, whole task `./bin/sb done "TESTQ2 first report" && ./bin/sb log`:

```
t+0   done               {"summary": "TESTQ2 first report"}
      herdr notification show donetest: done — TESTQ2 first report
t+1   revived
t+3   stop_gate_blocked
t+9   done               {"summary": "TESTQ2 second report: sb done then sb log ran as instructed…"}
      herdr notification show donetest: done — TESTQ2 second report…
```

### 2b — duplicate delivery: STILL BROKEN, medium-high

Two `done` events, two mailbox deliveries, two desktop notifications for one piece of work.
Same root cause as Q1(b), and the same reason it is not an agent whim: revive → `working` →
the stop gate refuses the turn end → the agent's cheapest exit is another `sb done`.

The consequence that makes it worth filing rather than shrugging at: `sb status` renders
only the latest `done` summary, so the second, content-free report **replaces the real one**
on the board:

```
donetest  worker  done  …  ✓ TESTQ2 second report: sb done then sb log ran as instructed…
```

The first summary is recoverable from `sb log`, but a parent acting on the board acts on the
junk one.

### 2a — `sb cleanup` refusing: NOT A BUG, low

Reproduced verbatim on `donetest2` (told not to re-report, so its row stayed revived):

```
$ ./bin/sb cleanup donetest2
closed: (nothing)
  refused donetest2: working, not finished — it has not reported an end
$ ./bin/sb cleanup --dry-run
would close: blocktest, donetest          # donetest2 not offered
$ ./bin/sb cleanup --force donetest2
closed: donetest2
```

This is the gate doing its job — the row genuinely is `working` and closing a working
agent's pane is the irreversible direction. It costs one `--force <name>`, which is exactly
the escape hatch `cleanup --help` documents. The refusal *message* is misleading ("it has
not reported an end" — it did, and the parent has the summary), but that is a wording nit,
not a defect worth a GitHub issue on its own.

---

## Q3 — the safety claims. Both still true.

### `broker.py:4114` — `_finished_and_unreachable` "safe against `_revive`"

True. Probed live against the running fleet in the clone:

```python
b._name_bound("blocktest")            -> True
b._finished_and_unreachable("blocktest")  -> False   # state done, pane alive
b._finished_and_unreachable("donetest")   -> False
# after UPDATE agents SET state='failed' WHERE name='blocktest'
b._finished_and_unreachable("blocktest")  -> False
```

One nuance for whoever reads that comment next, offered as a note and not a bug: in the
*same process* as the revive the guard never reaches `_name_bound` at all — `_revive`
flips `state` to `working` first, so line 4127's `state not in FINISHED` short-circuits.
The comment's stated reason ("herdr knows the name") is what carries the *cross-process*
case — the collector evaluating a done row between the agent's commands — which is the
case that matters. So the claim is sound; it is just doing its work one layer further out
than the sentence suggests.

### `status.py:1070` — "`Broker._revive` for an agent that simply calls `sb` again"

True, and proven live rather than inferred. I wrote the exact row `_record_gone` writes
(`state='failed'`, `ended_at` set) onto a real agent in the clone, then ran a real
`./bin/sb log` from that agent's identity:

```
before: {'name': 'blocktest', 'state': 'failed',  'ended_at': 1786815164}
after : {'name': 'blocktest', 'state': 'working', 'ended_at': None}
events: revived
```

`_revive`'s first branch keys on `ended_at`, not on the state word, so `failed` and `done`
take the identical path. Not stale.

One thing the comment does not claim and I am not filing: the `failed` message
`_record_gone` already put in the parent's mailbox is not retracted by the revive.

---

## What I did not test

- No test of a *human* answering in the pane (the path the design exists to serve). Both
  runs self-revived from the agent's own second command, which is the reported failure mode.
- No rate measurement on Q1 — n=1 per outcome, cheap model (`sonnet`, medium effort).
- Did not exercise the `_already_nudged` cap (a second silent turn end after the gate has
  already fired once). `blocktest2` reached STALLED on its first post-gate stop.
- Did not test `sb restore` on any of these rows.
- No automated test added — task said change no source file.

## Teardown

Everything this run created is gone, verified after the fact:

- four agents (`blocktest`, `blocktest2`, `donetest`, `donetest2`) — `sb cleanup --force`,
  then `sb workspace close <name> --yes`, all four reporting "worktree removed";
- their four worktrees under `/Users/andrew/.herdr/worktrees/clone/` — directory now empty;
- one clone-local collector, `/opt/homebrew/…/Python -m switchboard.collector`, found by
  `lsof -a -d cwd -c Python` filtered to `/worktrees/clone/` and killed **by its single
  PID**. No `pkill`, unscoped or otherwise;
- the machine-global herdr workspace `w1EA` (label `clone`, checkout = my scratch clone) —
  `herdr workspace close w1EA`. `herdr workspace list` afterwards shows only the live
  fleet's six, unchanged. `herdr agent list` has no `blocktest*`/`donetest*`.

No source file was changed, nothing was committed, and no test was added — all three as
instructed. There is therefore nothing in this run for the repo's suite to check.
