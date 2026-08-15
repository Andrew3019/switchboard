# The session-id guard on the turn-edge sweep (worker-62)

Task: `notes/tasks/stalled-cleanup-session-guard.md`. One condition, one test, one live
confirmation. Nothing else on the branch was touched.

## The condition, as expressed

In `Broker.cleanup`'s `given_up_on`, after the verdict holds (`state` RUNNING, `turn` NULL,
`turn_forgotten` in the log, `_busy` disagreeing): a row with **no `session_id`** is put in
`unrestorable` and the verdict is refused. It is not part of the verdict — the verdict is
still one thing — it is a guard on top of it, because `restore` refuses a row with no
session id and `cleanup`'s own promise is that closing costs only the pane.

The refusal names the fact that holds it, and is deliberately **not** `expected`, so a bare
sweep prints it:

```
refused wgs1: its turn edge was given up on, but it never ran sb — no session id,
so sb restore could not bring it back
```

Named, it gains `. --force closes it anyway`, matching every other refusal on this gate.

## What the test pins

`tests/test_broker.py::…test_a_forgotten_row_restore_cannot_reach_is_refused_and_says_why`
— a row with `session_id=None` driven through the real repair (`status.collect` twice, a
doubt window apart) until `_forget_turn` fires, then: bare sweep closes nothing and its
refusal is in `notable` (a sweep must not swallow it), naming it refuses and names
`--force`, and `--force` closes it. Checked against `HEAD` before the change: **fails** —
`AssertionError: ['kid'] != []`, the sweep took the row. Nothing was added to the fake
herdr. Suite: 1241 passed (was 1240).

## The live run

`git clone` of this worktree into a scratch dir at `866aedb`, driven only by that clone's
own `./bin/sb`; store confirmed as the clone's own by `sb doctor`, `sb status` empty at the
start. `turn_stale_grace 1800 → 10` and `turn_doubt_grace 900 → 10` via a copied `defaults/`
and `SWITCHBOARD_DEFAULTS` (`diff -rq`: `settings.toml` the only differing file). The one
thing simulated is the lost `Stop`-hook write — a single `store.set_turn(db, name,
'working')` against a real, live, idle agent; everything after it is the real repair path.

**The unrestorable row.** `wgs1`, a real `--model cheap` delegate told not to run any `sb`
command. It ended its turn with `session_id=None, turn='idle'` — the class the task is
about, observed again. After the simulation and two real `./bin/sb status` calls 15 s apart:
`turn_forgotten {"target": "wgs1", "held": 20}`, `turn` NULL, `state` still `working`.

```
=== bare sweep ===   closed: (nothing)
  refused wgs1: its turn edge was given up on, but it never ran sb — no session id, so sb restore could not bring it back
=== named, no force ===
  refused wgs1: … . --force closes it anyway
=== force ===        closed: wgs1
=== restore ===      sb: wgs1 has no session id; nothing to restore   (rc=1)
```

The last line is the cost the guard now prevents by default, and `--force` is still the way
through.

**Control — the gate still opens.** `wgs3`, a real agent that did run `sb` (session id set),
put in the same state by the same simulation and the same repair: the bare sweep closed it,
and `sb restore wgs3` brought it back into a live pane. So the promise now holds for every
row a sweep takes.

**Teardown.** All three agents closed, three workspaces retired with their worktrees
removed (`~/.herdr/worktrees/wg1` gone), the clone's herdr workspace `w1FP` closed, the
clone and the copied defaults deleted. One process killed, by pid after `lsof -d cwd`
confirmed its cwd was inside my run: the clone's own collector, pid 93892. No `pkill` of any
kind. The live fleet's collector (pid 40401, cwd `…/switchboard/accept-concurrent`) was
checked and left alone.

## Unproven, and judgement calls

- **`--force` on a *sweep* is still illegal** and untested here; unchanged by this.
- The live run has one agent per case, once. No endurance, by instruction.
- `wgs3`'s route to `state=working` involved a real `sb block` and a real human `sb tell`
  answer (the model called `sb block` unasked); its stuck edge, like every other, was the
  one simulated `set_turn`.
- **Docs I did not change**, and why: `defaults/protocol.md:220` and
  `defaults/roles/lead.md:195` both say a sweep takes "any whose turn switchboard gave up
  on" and then, in the same sentence, that closing costs only the pane because `sb restore`
  brings the agent back. That second half is what this change makes true, so the sentence
  now holds as written; narrowing the first half costs a line in every agent's prompt for a
  corner they will meet as a self-explaining refusal. `cli.py`'s `cleanup` description —
  where a person reads the verb's contract — now says "as long as sb restore can still bring
  it back".
- **The out-of-scope option, as asked**: teaching `restore` to work from the pane id was not
  built and I do not think it is the better answer here. A pane id is not a session; the
  agent that never ran `sb` has no conversation to resume, so `restore` from a pane id would
  bring back a fresh agent wearing an old name — which is not what "closing costs only the
  pane" promises. Refusing the row is the honest bar.
