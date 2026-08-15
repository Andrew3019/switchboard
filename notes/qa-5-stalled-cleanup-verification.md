# Independent verification of `65dcd53` (stalled-agent cleanup) — qa-5

Verify-only run. No source file changed, no commit made. Everything below is either a
command I ran or a line of code I read; where I inferred rather than ran, it says so.

## How the live runs were done

- `git clone` of this worktree into
  `/private/tmp/.../scratchpad/qa5`, branch `stalled-agent-cleanup`, driven only by that
  clone's own `./bin/sb`. Its store is the clone's own
  (`.../scratchpad/qa5/.git/agentflow/state.db`, confirmed by `./bin/sb doctor`).
- Five real Claude agents were spawned in it (`qa5a`…`qa5e`, `--model cheap`).
- Old-vs-new comparisons were done by checking out `87572c1`'s `switchboard/broker.py`
  into the clone and running the *same command against the same live rows*, then checking
  the branch's copy back.
- Two constants were shortened for the `turn_doubted` run only, via the sanctioned
  `SWITCHBOARD_DEFAULTS` env var pointed at a copy of `defaults/`:
  `turn_stale_grace 1800 → 10`, `turn_doubt_grace 900 → 10`. Nothing else was changed, and
  the graces are not what any claim is about.
- One store write was made by hand, with `store.set_turn`, to give a live agent the stuck
  `working` turn edge that a lost `Stop` hook write leaves behind (see claim 2). This is
  the one thing I simulated rather than caused; every other row was produced by a real
  agent doing a real turn.
- Teardown: all five agents closed, all four fixture workspaces retired and their
  worktrees removed (`/Users/andrew/.herdr/worktrees/qa5/` is empty), one leftover
  `switchboard.collector` killed **by pid 64793 after confirming its cwd** was
  `/Users/andrew/.herdr/worktrees/qa5/qa5a`. No unscoped kill was used. The live fleet's
  collector was not touched.

## Verdicts

### 1. A `stalled` row is closed by a bare sweep — PROVED (live)

`qa5e` was a real agent that ended its turn without reporting: `state=working`,
`turn=idle`, herdr `done`, `stalled=true`, no excuse. The same command, same row, seconds
apart:

```
=== PRE-CHANGE broker (87572c1), dry-run sweep ===
would close: qa5a
  refused qa5c: still working underneath: qa5d
=== branch broker, dry-run sweep ===
would close: qa5a, qa5e
```

and then for real:

```
$ ./bin/sb cleanup
closed: qa5a, qa5b, qa5e
```

The event log records `qa5e cleanup_stalled {"state": "working", "named": false}` followed
by `cleanup {"forced": false}`; the row is now `done` with no pane.

### 2. A named agent is also taken when merely `turn_doubted`, and a sweep is not — PROVED (live)

`qa5e` was given the stuck edge (`store.set_turn(db, 'qa5e', 'working')`), leaving
`stalled=false`, `turn_doubted=true` (with `turn_stale_grace=10`). Both commands run at the
same instant against that row:

```
=== sweep (dry-run) ===        would close: qa5a        # qa5e NOT taken
=== named (dry-run) ===        would close: qa5e
```

Because `turn=working` makes `stalled` false, the only branch that can have opened gate 4a
for the named call is `bool(names) and s.turn_doubted`. Against `87572c1` the same named
call refused: `working, not finished — it has not reported an end`.

One thing worth knowing, found the hard way: any `sb status` run (`reap=True`) can *repair*
the doubted edge mid-experiment — my first attempt at this claim failed because a status
call I made for observation had already run `_forget_turn`. `cleanup`'s own read is
`reap=False`, so it does not do this. Not a defect; a trap for anyone re-running it.

### 3. A genuinely mid-turn agent is still refused — PROVED (live)

`qa5b`, running a foreground `sleep 420`, herdr `working`, `agents.turn=working`:

```
$ ./bin/sb cleanup qa5b
  refused qa5b: working, not finished — it has not reported an end. --force closes it anyway
$ ./bin/sb cleanup
  refused qa5b: working, not finished — it has not reported an end
```

Neither closed it. Note also that a real 7-minute tool call kept `turn=working` throughout,
so it never came near `stalled` (`idle` reached 296 s with `stalled=false`).

### 4. `--force` named in the named refusal only, and still illegal on a sweep — PROVED (live)

Both halves are in the run above (the named refusal carries `. --force closes it anyway`,
the sweep's does not), and:

```
$ ./bin/sb cleanup --force
sb: --force needs the name of the agent to close: it lifts every safety gate, so it is never a sweep
(rc=1)
```

### 5. The other gates — PROVED live except one; one wording defect

- **unread mail on a stalled row — PROVED LIVE.** The implementer could not build this one;
  I won the race. `./bin/sb tell qa5e ...` immediately followed by `./bin/sb cleanup qa5e
  --dry-run`, before the doorbell woke the session:

  ```
    refused qa5e: stalled, but holding unread mail — that gate stands on its own, and only
    closing the row clears the mail. --force closes it: the message survives in its inbox
  ```

  The row was `stalled` with `unread=1` at that instant. So the stalled+mail refusal is not
  unit-test-only any more.
- **live descendants — PROVED LIVE, including under `--force`.** `qa5c` with live child
  `qa5d`: bare sweep gave `refused qa5c: still working underneath: qa5d`, and
  `./bin/sb cleanup qa5c --force` was refused outright (rc=1). The gate sits above the
  changed code (broker.py:3769) so nothing in this commit can reach past it.
- **already closed — PROVED LIVE.** A second sweep after the first gave
  `refused qa5a/qa5b/qa5e: already closed`.
- **self — held, but not by the gate the docstring points at.** An agent naming itself does
  not reach the `that is you` refusal at broker.py:3761 at all: an agent's scope is
  `self._descendants(me)`, which excludes the agent itself, so `b.cleanup(['qa5c'],
  me='qa5c')` raises `KeyError: not yours to clean up, or no such agent: qa5c` (run
  directly against the clone's live store). The protection holds; the named self-gate looks
  unreachable. **Pre-existing, untouched by this commit, not fixed.** I could not run this
  from inside the agent's own pane — Claude Code's auto-mode permission classifier blocked
  `./bin/sb cleanup qa5c` in that pane.
- **gone-but-unconfirmed — NOT tested live, and unreachable by this change.** The gate
  needs `state='failed'`, which is in `FINISHED`, and `stalled` is computed as
  `a["state"] not in FINISHED and given_up_on(...)` (broker.py:3778) — so a `failed` row
  never consults the new predicate and reaches that gate exactly as before. Producing one
  live means killing a session, which the task ruled out. Also worth knowing: `grep` finds
  **no test anywhere** covering that gate (`_end_still_holds` / "nobody reported this end"
  appear in no test file). That gap predates this commit.
- **blocked rows — safe by construction.** `states.running = ["working"]`, and both
  `stalled` and `turn_doubted` require `state in RUNNING`, so a `blocked` row can never be
  given up on. Read, not run.

**Wording defect (minor, real).** The mail refusal calls a row "stalled" whenever
`given_up_on` opened the gate — including the *named* `turn_doubted` case, where the board
shows the row as plain `working` with no STALLED marker. Observed live: with `qa5e`
`stalled=false, turn_doubted=true` and one unread message, `./bin/sb cleanup qa5e` printed
`refused qa5e: stalled, but holding unread mail …`. Someone who then runs `sb status`
finds nothing calling that row stalled. The local variable is named `stalled` but means
"given up on"; the message inherits the wrong word.

**Behavioural consequence worth a decision, not a bug.** `stalled` is "idle, and no excuse",
where the only excuses are *awaiting first task*, *live children*, *starting up*
(status.py:858). There is no excuse for **waiting on a reply**: an agent that did what the
protocol tells it to do — send `sb tell --needs-reply` and end its turn — is `stalled`, and
after this change a bare `sb cleanup` closes its pane rather than refusing. Before the
change such a row was only *pinged*. `sb restore` brings it back, and the task set the bar,
so this is a flag, not a re-opening. (Read from `status.py`; `grep` finds no `needs_reply`
handling in that file. Not run live.)

### 6. The suite — GREEN, and the four tests pin something

- `/Users/andrew/anaconda3/bin/python -m pytest tests` → **1237 passed** in 77 s.
- With `87572c1`'s `broker.py` checked out in the clone, all four new tests **fail**:
  `test_a_sweep_closes_a_row_whose_turn_ended_without_a_report`,
  `test_a_sweep_still_refuses_a_working_agent_and_names_the_way_through`,
  `test_a_named_cleanup_takes_a_doubted_turn_that_a_sweep_will_not`,
  `test_a_stalled_row_holding_mail_is_still_refused_and_says_so`
  (`4 failed, 212 deselected`). None of them passes either way.

## The mail unit test — does it exercise the real path?

Yes for the code, partly for the shape.

- **The code path is real.** `_stalled_kid` builds an ordinary `working` row with a session
  id and a fake herdr answering `idle`; `stalled` is then computed by the real
  `status.collect`, gate 4a is opened by the real `given_up_on`, and the refusal comes from
  the real mail gate reading `store.unread_for`. Nothing is stubbed between the predicate
  and the gate. The one thing the test does not reproduce is how the mail got there: it
  calls `store.put_message` directly, where production goes through `broker.tell`, which
  also rings the doorbell.
- **The shape does occur in production.** A ring is a prompt injection; it does not read
  anything. Any stalled row whose session does not act on the ring keeps `unread > 0` while
  herdr still lists the pane and reads it idle — which is `stalled=true` with mail. My live
  race caught exactly that state, which settles it: the row shape is real, not synthetic.
- **What is still unproven:** the *durable* version — a row that sits stalled-with-mail for
  a long time because the session can never read it. Mine lasted about a second before the
  doorbell woke the agent. I did not test what happens to that gate against a session that
  is alive to herdr but permanently unable to read, and I did not kill a Claude process to
  find out.

## The `cleanup_refused` idle-clock bug (`2026-08-15-111506`) — CONFIRMED

Real, reproduced live, and it bears directly on whether rows ever reach `stalled`.

```
--- before sweep ---   qa5a working idle= 45   qa5b working idle= 7
--- bare sweep ---     refused qa5a / qa5b: working, not finished …
--- after sweep ---    qa5a working idle= 1    qa5b working idle= 1
```

Mechanism, read in code: `refuse()` logs `cleanup_refused` with `agent=<name>`
(broker.py:3711); `status._last_activity` counts *every* event naming an agent as that
agent acting, minus the `DONE_TO_THE_AGENT` denylist (status.py:312), which lists only
`ring_*`, `mail_*`, `notify_failed`, `read_output`. `cleanup_refused` is not on it, so a
refusal is recorded as the refused agent having done something.

Consequences: it renews the `starting up` excuse (`STALL_GRACE` = 72 s) and restarts the
30-minute `turn_stale_grace` window that `turn_doubted` needs. A person who sweeps every
few minutes while waiting for a wedged row to become sweepable is pushing it away from the
gate they are waiting for. `cleanup_held` and the new `cleanup_stalled` /
`cleanup_forced_live` are missing from the same denylist, though those two only fire on
rows that are being closed anyway. Not fixed, as instructed. It is a one-line change in
`status.py`.

## One more thing I noticed and did not fix

A row swept as stalled is written `state='done'` (broker.py:3896) — the same word an agent
writes when it reports. After the sweep, `qa5e` reads `done` in `sb status` exactly like
`qa5a`, which really did report; the only surviving distinction is the `cleanup_stalled`
event in the log. That is pre-existing behaviour for `--force` too, and the new event was
added deliberately for it, so it is a note rather than a finding.

## Scope warning — this verifies the commit, not the working tree

Everything above is `65dcd53` as committed (my clone was made from it, and the suite run
was before this appeared). While I was working, another agent left
`switchboard/broker.py` **uncommitted and heavily rewritten** in this shared worktree
(122+/68-, alongside `notes/tasks/stalled-cleanup-revise.md`). That rewrite replaces the
predicate I verified: one bar for named and swept alike, built on `_forget_turn` having
fired rather than on `stalled` / `turn_doubted`. **None of my verdicts carry over to it** —
claims 1 and 2 in particular are about a distinction that revision removes. It needs its
own run.

## What I did not test

- Any `--force` path other than the two above.
- The gone-but-unconfirmed gate, live (see claim 5).
- Anything about restore of a swept-stalled row.
- Endurance / repeated sweeps over a long period.
