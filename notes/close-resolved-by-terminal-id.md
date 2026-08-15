# The close half of the ghost-name problem

Follows `notes/ghost-sessions-name-vs-identity.md`, whose last section names exactly this
as what it did not touch: "the close itself, which herdr resolves **by name** — a `--force`
close of a colliding name is the near-miss reported against another clone's live worker."
Scope: `Broker.cleanup`'s close, and nothing else.

## 1. It is not a name, it is a pane id — and that is the same bug

The close never asked herdr for a name at all. It did this:

```python
self.h.release_agent(a["pane_id"], a["name"], seq)
self.h.close_pane(a["pane_id"])
```

`herdr pane close` takes a `<pane_id>` and nothing else (`--help`, 0.8.0). So the wrong
target does not arrive through a name lookup — it arrives through a pane id taken on
trust, which fails for the same reason a name does:

- a `pane_id` moves with its pane. herdr documents `terminal_id` as the STABLE handle and
  `pane_id` as the one that changes on a cross-workspace move — the comment at
  `herdr.py:176` already said so, for the board's benefit.
- pane ids are **recycled** once a pane closes. Not inferred: the store has carried a test
  about it since long before this change (`test_session_id_wins_over_a_recycled_pane` —
  "Pane ids are recycled once a pane closes; a stale row must not capture a new agent").
- herdr is machine-global, so the agent that inherits a recycled id can belong to a
  different clone with a different store — and two clones name their workers the same way,
  which is why the near-miss was noticed as "another clone's `worker-1`".

The name is how a human spots the collision; the pane id is how the close reaches it. Both
are what PR #59 fixed one half of: switchboard holding a handle that has stopped meaning
what it meant when it was written down.

## 2. What changed

`Broker._close_target(row) -> (pane, refusal)`. One new gate in the cleanup loop, one
changed call:

```python
target, wrong = self._close_target(a)
if wrong is not None:
    refuse(a, wrong); continue
...
self.h.release_agent(target, a["name"], seq)
self.h.close_pane(target)
```

The target is **resolved** from `terminal_id`, not merely checked. Asked in order:

| the row | herdr says | outcome |
|---|---|---|
| any | cannot be asked | **refuse** |
| has a `terminal_id` herdr still lists | it is in pane P (recorded or not) | close **P** — a pane that moved is followed |
| has one, not listed | nobody in the recorded pane | close the recorded pane (the ordinary already-closed path, still landing on `pane_not_found`) |
| has one, not listed | somebody IS in the recorded pane | **refuse** — recycled under us |
| has none | nobody in the recorded pane | close it |
| has none | somebody IS in the recorded pane | **refuse** — nothing to prove it is ours |

The lookup is keyed by pane and by terminal id, **never** by name: "where is `worker-1`" is
the one question with two answers, "where is `term_6591c642…`" has one. It comes off the
same single `agent list` per process that `_end_still_holds` uses (`_pane_cache`, filled in
`_fill_agent_caches`).

**Placement.** Below `--force` and above the dry run, both deliberately. `--force`
overrides intent — every gate above it is a policy question about whether the operator
meant it — and this is not intent, it is whether the thing about to be destroyed is the
thing they named. It matters more since PR #58: `--force` now takes live descendants with
the row, so a wrong close is a stranger's whole subtree. A dry run reports the refusal
because it is asked what a real run would do, and a real run refuses.

**Fails closed**, on the mandate that a refusal costs a retry and a wrong close costs
work nobody can get back. Note this is the OPPOSITE default from `status.collect`'s guard,
which fires on disagreement only and lets a blank id through: that one is a readout that
errs toward drawing a row, this one is irreversible.

## 3. Live before/after, in isolated clones

Two `git clone`s under the session scratchpad, each with its own store (`store.repo_root()`
is `git rev-parse --git-common-dir`), driven by their own `./bin/sb`. Clone B ran a real
agent through the ordinary `sb delegate`; clone A held a row of the same name whose
`terminal_id` was dead and whose `pane_id` was clone B's live pane — the state a recycle
produces, constructed rather than waited for, so the run is deterministic.

```
clone B, live:   worker-1  pane w1GR:p1  term_6591d48384120d92
clone A, row:    worker-1  pane w1GR:p1  term_deadbeefdeadbeef   state done
```

Same herdr, same pane, same name, two stores. `sb cleanup worker-1 --force` from clone A:

```
=== AFTER  (d0ad116) ===
closed: (nothing)
  refused worker-1: pane w1GR:p1 is now worker-1's (term_6591d48384120d92), not this
  row's (term_deadbeefdeadbeef) — its own pane is gone and the id was recycled under it

  herdr agent list  →  worker-1 still there.        clone B's agent survives.

=== BEFORE (b9d83ad, main) ===
closed: worker-1

  herdr agent list  →  worker-1 gone.               clone A closed clone B's agent.
```

AFTER was run first so one spawn covered both: the refusal changes nothing, and the
destructive run then had something left to destroy.

**Teardown**: both clone workspaces closed (`w1GQ`, `w1GR`), the child's git worktree
removed, both clones deleted. No `pkill`.

## 4. Tests

`tests/test_broker.py`, three, all three verified to FAIL against `b9d83ad` and pass here:

- `test_force_will_not_close_a_pane_a_stranger_now_holds` — the near-miss, under `--force`.
- `test_the_close_follows_the_terminal_id_when_the_pane_has_moved` — closes `w9:p7`, where
  herdr says the terminal is, and not the recorded `w9:p1`.
- `test_a_row_with_no_terminal_id_will_not_take_an_occupied_pane` — identity unavailable is
  a refusal.

Each stubs `list_agents` in the test itself; the shared fake herdr grew nothing. Whole
suite: `1275 passed` (`/Users/andrew/anaconda3/bin/python -m pytest tests`).

## 5. Not touched, and what is unproven

- **`_close_workspace`** (`broker.py:~2331`) closes every pane of a workspace's rows by the
  same untrusted `pane_id`, with no identity check. Same hazard, different verb, out of
  scope here — reported, not fixed.
- **`_close_board`** closes a recorded board pane. It has its own guard
  (`_board_is_only_for`), which is a store question and not a herdr one, so a recycled
  board pane id is still reachable. Also not touched.
- **`release_agent`** still passes `a["name"]` as `--agent <LABEL>`. Unchanged: the pane id
  is the target and the label rides along, so it cannot select a stranger.
- The **pane-moved** row of the table is the one case with no live proof — a
  cross-workspace pane move was not staged, only the unit test covers it. The recycle case,
  which is the reported one, is proven live.
- A row that is **mid-spawn** (no `terminal_id` yet) whose own pane is occupied by itself
  is now refused, and comes back on the next sweep once `_spawn` writes the id. Cheap, and
  `SPAWN_GRACE` already keeps sweeps off those rows.
