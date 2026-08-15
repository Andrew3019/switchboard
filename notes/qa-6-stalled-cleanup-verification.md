# Finishing and proving `9286b5b` — the turn-edge cleanup bar (qa-6)

What I was asked: do the documentation half the previous agent never did, prove the new
bar live, and check the tests pin the *new* bar. Nothing was redesigned.

Everything below is either a command I ran or a line of code I read. Where I inferred, it
says so.

## How the live run was done

- `git clone` of this worktree into
  `<scratchpad>/qa6`, branch `stalled-agent-cleanup` at `c7391cf` (my doc commit on top of
  `9286b5b`), driven only by that clone's own `./bin/sb`. Its store is the clone's own
  (`.../scratchpad/qa6/.git/agentflow/state.db`, confirmed by `./bin/sb doctor`). No
  clone `sb` was ever run from outside the clone.
- Eight real Claude agents (`--model cheap`): `qa6a`, `qa6b`, `qa6c`, `qa6d`, `qa6p`,
  `qa6k` (child of `qa6p`), `qa6q`, `qa6r` (child of `qa6q`), `qa6s`.
- Two graces shortened for the whole run, via `SWITCHBOARD_DEFAULTS` pointed at a copy of
  `defaults/`: `turn_stale_grace 1800 → 10`, `turn_doubt_grace 900 → 10`. `diff -rq`
  against `defaults/` shows `settings.toml` as the only differing file, and those the only
  two changed lines. The graces are not what any claim here is about.
- **The one thing simulated**: the lost `Stop`-hook write. Where a row needed a turn edge
  stuck at `working`, I made a single `store.set_turn(db, <name>, 'working')` call against
  a real, live, idle agent. Everything after that — `turn_doubted`, `_sustained`,
  `_forget_turn`, the `turn_forgotten` event — is the real repair path, driven by real
  `./bin/sb status` calls a doubt window apart. No row's verdict was written by hand.
- **Teardown**: all nine agents closed, all seven fixture workspaces retired and their
  worktrees removed (`/Users/andrew/.herdr/worktrees/qa6/` is empty), the clone's herdr
  workspace `w1FD` closed. Two processes killed **by pid after confirming each one's cwd
  with `lsof -d cwd`**: `switchboard.collector` 57484 (cwd
  `/Users/andrew/.herdr/worktrees/qa6/qa6a`) and `caffeinate` 74493 (cwd
  `.../qa6/qa6q`). No unscoped kill. The live fleet's collector (pid 40401, cwd
  `.../switchboard/accept-concurrent`) was checked and left alone. `herdr agent list`
  after teardown shows no `qa6*` pane.

## Part 1 — the documentation half

Committed as `c7391cf`. Five places said cleanup touches only finished agents:

| file | was | now |
|---|---|---|
| `cli.py` (cleanup help + description) | "close finished agents" / "closes every finished agent in your subtree" | adds "plus any whose turn switchboard itself gave up on — a crashed session nobody reported an end for", and replaces the old "a name also means you want it closed whatever state it is in" with "at the same bar; `--force` is what closes one whatever state it is in" |
| `defaults/protocol.md` (the line every agent reads) | "closes finished ones beneath you" | "closes finished ones beneath you, plus any whose turn switchboard gave up on" |
| `defaults/roles/lead.md:194` | "closes finished agents in your subtree" | same addition |
| `status.py` `needs_human` docstring | "`sb cleanup` will not touch a row that is not finished" | "will not touch it — its turn edge ended cleanly, so it is not a row switchboard ever gave up on, which is the only unfinished row a sweep takes" |
| `status.py` `_record_gone` docstring | "a `sb cleanup` that already gates on the row being finished … `sb cleanup` cannot reach it" | gates "on the row being finished, or on a turn edge switchboard gave up on — which a row whose turn ended cleanly does not have" |

The old `cli.py` sentence "a name also means you want it closed whatever state it is in"
was false under the new bar (naming lifts nothing; `--force` does), so it went with the
same edit.

Two I deliberately left, both outside the claim:

- `switchboard/output.py:14` — "`sb cleanup` closes finished agents", a passing aside
  about why transcripts outlive panes. It does not say *only*. Flagging, not fixing.
- `defaults/roles/dispatcher.md:243` — "close a finished child when they answer" is advice
  about which children to close, not a promise about the verb's reach.

`DESIGN-TRUTH.md` says nothing about what cleanup's bar is (its four `cleanup` mentions are
about policy, aggressiveness and worktrees), so **I see no change it needs**. Not touched.

## Part 2 — the live proof, point by point

### 1. The incident row closes, swept and named — PROVED

`qa6b` and `qa6c`: real agents, `state=working`, session ended its turn, then one
`set_turn(..., 'working')` each, then the real repair ran (`turn_forgotten` logged with
`{"target": "qa6b", "held": 20}`, `agents.turn` NULL, `state` still `working`).

```
=== named close of the incident row qa6c (no --force) ===
closed: qa6c
=== bare sweep ===
closed: qa6b
```

Event log afterwards:

```
cleanup_given_up qa6b {"state": "working", "named": false}   +  cleanup qa6b {"forced": false}
cleanup_given_up qa6c {"state": "working", "named": true}    +  cleanup qa6c {"forced": false}
```

Note the event kind is `cleanup_given_up` — `9286b5b` renamed it from `cleanup_stalled`.
Nothing in `tests/`, `defaults/` or `DESIGN-TRUTH.md` mentions either name, so no test pins
it and nothing else broke.

### 2. The review's three reproduced hazards — ALL NOW REFUSED, by sweep and by name

- **The healthy `--needs-reply` waiter.** `qa6k` really ran
  `sb tell parent 'Which of the two files should I start with?' --needs-reply` (the row is
  in `messages`) and ended its turn. `sb status` showed it `STALLED`, idle 10 s — exactly
  the row the old bar swept.

  ```
  bare sweep : refused qa6k: working, not finished — it has not reported an end
  named      : refused qa6k: working, not finished — it has not reported an end. --force closes it anyway
  ```

- **Parent unwinding.** `qa6q` (lead, live child `qa6r`, `turn='idle'`). I closed the child
  (`sb cleanup qa6r --force` → `closed: qa6r`) and then ran **two consecutive bare
  sweeps**; the review's probe B closed the parent on sweep 2.

  ```
  --- sweep 1 ---  refused qa6q: working, not finished — it has not reported an end
  --- sweep 2 ---  refused qa6q: working, not finished — it has not reported an end
  ```

  `qa6q` was still `state=working` with its pane afterwards. One honesty note: this `qa6q`
  had earlier been given up on and then had its edge restored to `idle` by hand for this
  step, so what it proves is "no verdict standing ⇒ not sweepable"; a parent that never had
  a verdict fails `given_up_on` one test earlier still (the `turn IS NULL` read, which
  precedes the event-log read).

- **The newcomer with no session id.** `qa6s`, a real delegate that never ran an `sb`
  command: `session_id=None`, age 94 s — past the 72 s `starting` grace.

  ```
  bare sweep : refused qa6s: working, not finished — it has not reported an end
  named      : refused qa6s: … --force closes it anyway
  ```

  **But see the finding below — this class is not excluded by construction, and I closed
  one unrecoverably.**

### 3. A genuinely mid-turn agent is still refused, and only the named refusal names `--force` — PROVED

`qa6a`, running a foreground `sleep 420`, herdr `working`, `agents.turn='working'`:

```
$ ./bin/sb cleanup qa6a
  refused qa6a: working, not finished — it has not reported an end. --force closes it anyway
$ ./bin/sb cleanup
  refused qa6a: working, not finished — it has not reported an end
```

What I did **not** isolate live: the `_busy` re-check specifically. `qa6a` is refused at the
`turn` read (`'working'` is non-NULL), one step before `_busy` is ever called, so this run
does not distinguish the two. The `_busy` half is covered by the shipped unit test
(`test_a_sweep_closes_the_row_whose_turn_edge_we_gave_up_on` flips the fake herdr to
`working` on a forgotten row and asserts the sweep closes nothing).

### 4. The other gates still stand on a given-up-on row — PROVED

- **Unread mail.** `qa6d`: `turn_forgotten` fired, `turn` NULL, one unread message:

  ```
  named : refused qa6d: unread mail, and giving up on its turn does not lift that gate —
          only closing the row clears the mail. --force closes it: the message survives in its inbox
  sweep : refused qa6d: unread mail, and giving up on its turn does not lift that gate —
          only closing the row clears the mail
  ```

  (The wording defect qa-5 filed — a refusal calling a merely-doubted row "stalled" — is
  gone with the rewrite; the message now says what actually happened.)

- **Live descendants, and nothing lifts them.** `qa6q` given up on (`turn_forgotten`
  logged, `turn` NULL) with live child `qa6r`:

  ```
  sweep         : refused qa6q: still working underneath: qa6r
  named         : sb: still working underneath: qa6q → qa6r … (rc=1)
  named --force : sb: still working underneath: qa6q → qa6r … (rc=1)
  ```

- Not tested, and out of reach of this change: the gone-but-unconfirmed gate (needs
  `state='failed'`, which is in `FINISHED`, so `given_up_on` is never consulted for it).
  Same gap qa-5 reported; still no test anywhere covers it.

### 5. The verdict is spent when the agent comes back — PROVED

`qa6d` had a `turn_forgotten`. I sent it mail; the doorbell woke it, it took a real turn and
its hooks wrote the edge again (`agents.turn='idle'`, non-NULL, with the `turn_forgotten`
still in the log). The named cleanup then fell back to the ordinary refusal:

```
refused qa6d: working, not finished — it has not reported an end. --force closes it anyway
```

That is the whole of "make sure it survives a row that takes a fresh turn afterwards".

### 6. A refusal no longer resets the refused row's idle clock — PROVED

A real (non-dry-run) bare sweep that refused five rows and logged `cleanup_refused` /
`cleanup_held` against them:

```
--- idle before ---  {'qa6a': 216, 'qa6b': 53, 'qa6c': 50, 'qa6p': 4, 'qa6k': 22, 'qa6d': 24}
--- bare sweep ---   refused qa6a/qa6b/qa6c/qa6k/qa6d …; refused qa6p: still working underneath: qa6k
--- idle after ---   {'qa6a': 216, 'qa6b': 53, 'qa6c': 50, 'qa6p': 4, 'qa6k': 22, 'qa6d': 24}
```

Not frozen output: the same query 12 s later read `{'qa6a': 228, 'qa6b': 65, …}`. The events
were really written (`cleanup_refused qa6a …`, `cleanup_held qa6p {"live_children": "qa6k"}`).
qa-5 saw 45 s → 1 s on the same shape.

## Finding: "a `turn_forgotten` row has a session id by construction" is FALSE

`notes/tasks/stalled-cleanup-revise.md` (and the reasoning behind dropping the review's
finding 4) says a row with a `turn_forgotten` must have run hooks, so it has a session id,
so the unrestorable class is excluded. It is not.

`hooks._agent_row` resolves the caller by **session id first and then `HERDR_PANE_ID`**
(hooks.py:181-200), and `mark_turn` says so in as many words — the fallback exists precisely
because "the store learns an agent's session id on its FIRST `sb` call". So turn edges are
written for agents that have never run `sb`. Observed directly, minutes after spawn:

```
{'name': 'qa6b', 'state': 'working', 'session_id': None, 'turn': 'idle',     …}
{'name': 'qa6d', 'state': 'working', 'session_id': None, 'turn': 'working',  …}
```

Full edges, no session id. And the class is reachable end to end — `qa6s`, a real agent that
never ran `sb`, given the same single lost-`Stop` simulation as every other incident row:

```
{'name': 'qa6s', 'state': 'working', 'session_id': None, 'turn': None}
forgotten: … '{"target": "qa6s", "held": 20}'
=== sweep ===    closed: qa6s
=== restore ===  sb: qa6s has no session id; nothing to restore   (rc=1)
```

So a bare sweep can take a row that `sb restore` cannot bring back — the review's finding 4,
which was believed closed. How narrow it is: the row must lose its `Stop`-hook write (the
crash this whole change is about) **and** never have run a single `sb` command across the
full `turn_stale_grace + turn_doubt_grace`. Both are the same silence. `Broker.cleanup`'s
docstring still promises "closing costs only the pane" for every row it takes.

Not fixed — out of scope, and the fix is a design call (refuse when `session_id IS NULL`, or
let `restore` work from the pane id). Reported, not touched.

## Part 3 — the tests

Method: in the clone, `git checkout e88b8e0 -- switchboard/` (the parent of `9286b5b`;
identical broker/status to `65dcd53`), keeping `tests/` from the branch, then run the seven
tests. Restored with `git reset HEAD switchboard/ && git checkout -- switchboard/`
afterwards — worth saying, because plain `git checkout --` restores from the *index*, which
still held the old files, and that silently ran two of my probes against the wrong code.

As shipped in `9286b5b`, **4 of 7 fail against the parent, 3 pass**:

| test | vs parent |
|---|---|
| `…_a_child_that_ended_its_turn_to_wait_is_not_swept` | FAILS — pins hazard 1 |
| `…_a_newcomer_with_no_session_id_is_never_swept` | FAILS — pins hazard 3 |
| `…_a_forgotten_row_holding_mail_is_still_refused_and_says_so` | FAILS — pins the mail wording + gate |
| `…_refusing_a_row_does_not_reset_the_clock_that_would_free_it` | FAILS — pins the `DONE_TO_THE_AGENT` fix |
| `…_a_doubted_turn_is_not_enough_to_close_a_row_named_or_swept` | **passed** — pinned nothing |
| `…_a_sweep_closes_the_row_whose_turn_edge_we_gave_up_on` | passes both ways |
| `…_sweeping_a_forgotten_row_does_not_unwind_the_parent_above_it` | passes both ways |

**The doubted-turn one I fixed** (one-line reorder, plus a docstring paragraph saying why).
It ran the bare sweep *first*, and under the old code that sweep's own `cleanup_refused`
reset the row's idle clock, so `turn_doubted` was already False by the time the named call
ran — the test passed against the exact bar it was written to rule out. Probe, old code,
named call alone:

```
turn_doubted: True
named-only cleanup -> ['kid']        # the old bar closes it
```

New code, same probe: `refused kid: working, not finished — … --force closes it anyway`.
With the named call moved first, the test now **fails against the parent** — 5 of 7.

The two that still pass either way, and why I left them:

- `…_a_sweep_closes_the_row_whose_turn_edge_we_gave_up_on` — the old bar closed that row
  too (`stalled` is true once `_forget_turn` NULLs the edge). It cannot discriminate, but it
  is the regression test for the incident itself, and its `_busy` half is the only coverage
  of the live re-check. Keep.
- `…_sweeping_a_forgotten_row_does_not_unwind_the_parent_above_it` — **vacuous, in both
  directions.** The fixture's `orch` has no pane and is not in the fake herdr's
  `states_by_name`, so it is never `alive`, never `stalled`, and gets refused on the
  ordinary "not finished" gate whatever the bar is. Probed: aging it out of its `starting`
  grace and giving it a session id does not change that, and giving it a pane makes
  `collect` record it `failed` instead. Making it genuinely reproduce the review's probe B
  means teaching the fake herdr about the parent, so **I did not write it** — the hazard is
  proved live above instead, and this unit test should be read as documentation, not
  evidence.

Seven tests for one decision is more than the two or three the task asks for; the redundant
pair is the sweep/named split inside the incident-row and hazard tests. I did not prune
them — deleting coverage on someone else's commit is not my call — but the set could lose
one or two without losing a pin.

Suite: `/Users/andrew/anaconda3/bin/python -m pytest tests` → **1240 passed** in 74 s, with
both the doc commit and the test reorder in place.

## What I did not test

- Any `--force` path other than the two I used (`cleanup <name> --force` on an ordinary
  live row, and `--force` refused over live descendants).
- The gone-but-unconfirmed gate (`state='failed'`), live or otherwise.
- Restore of a swept given-up-on row *with* a session id (only the no-session refusal).
- The `_busy` re-check in isolation, live (see point 3).
- Endurance: no repeated sweeping over a long period, by instruction.
- A real crashed session: every stuck turn edge here came from one `store.set_turn` call.
