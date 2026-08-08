# BUGS

Found while working on other things. One entry per bug: what was run, what was expected,
what happened, and the exact error.

Each entry ends with a **STATUS** line. Nothing is deleted when it is fixed — the
measurement and the wrong theories are the useful part.

| # | Bug | Status |
|---|---|---|
| 1 | `Broker._adopt` races on `agents.name` | **FIXED** — 60/60 clean, was 2/25 failing |
| 2 | `Herdr.wait` sends `--until idle,blocked` | **FIXED** in the adapter, not just around it |
| 3 | `Herdr.wait` spins at 100% CPU | **FIXED** in the adapter, not just around it |
| 4 | A schema change deadlocks every running agent | **FIXED**, with one shape still open |
| 5 | `sb wait` returns success while still working | **NOT REPRODUCIBLE** — property pinned by tests |

---

## `Broker._adopt` races on `agents.name` — concurrent `sb workspace new` can crash

**Found:** 2026-08-07, while building `sb status` (unrelated file).

**What I ran**

```
python3 -m unittest discover -s tests
```

Specifically `tests/test_workspace.py::StartWorkspaceTest::
test_concurrent_openers_all_land_in_the_one_workspace` — six threads calling
`workspace_new("api")` at once. It fails roughly **1 run in 25** (measured: 1/25, and
reproduced 1-in-10 in a tighter loop), so a green suite does not mean it is fixed.

**Expected**

The test's own premise: N openers, one workspace name, no coordination, no errors. Same
name means the same lead agent, so a loser should join rather than fail.

**What happened**

One thread raised out of `workspace_new`:

```
Traceback (most recent call last):
  File ".../broker.py", line 409, in workspace_new
    row = store.get_agent(self.db, lead) or self._adopt(lead, ws, role=role, me=me)
  File ".../broker.py", line 575, in _adopt
    store.create_agent(
  File ".../store.py", line 247, in create_agent
    db.execute(
sqlite3.IntegrityError: UNIQUE constraint failed: agents.name
```

**Why it happens**

`workspace_new` does a check-then-act: `store.get_agent(...) or self._adopt(...)`. Two
openers can both find no row, both see the lead alive in herdr, and both try to INSERT it.
`_adopt` (broker.py:559-584) calls `store.create_agent` unguarded.

Note `_spawn_lead` already handles exactly this collision one line further down — it
catches `(HerdrError, sqlite3.IntegrityError)` and joins the winner instead. `_adopt` is
missing the same guard. Likely fix: catch `sqlite3.IntegrityError` in `_adopt` and re-read
the row the winner just wrote (`store.get_agent`), which is the same "what is already
there is somewhere to go" rule the rest of the workspace code follows.

**Not worked around.** `sb status` does not touch this path; `switchboard/broker.py` is
owned by someone else right now.

**Still failing, and it has a second face.** Re-measured 2026-08-07 while building
`sb inspect`/`sb wait`: **5 failures in 25 runs** of that one test, on a tree where only
`cli.py`, `status.py` and their tests had changed. The IntegrityError above is the loud
version; the quiet one is an assertion, and it is the same race:

```
File "tests/test_workspace.py", line 431, in test_concurrent_openers_all_land_in_the_one_workspace
    self.assertEqual(sum(r["created"] for r in results), 1)
AssertionError: 0 != 1
```

Every opener returned `created=False`, so *nobody* recorded having made the lead — each
thread lost the race in `_spawn_lead`'s `agent_name_taken` branch, or adopted a row a
rival had already written. The workspace still ends up correct, which is why this one is
easy to skim past; the count of who created it is what is wrong. Same fix applies: make
`_adopt` re-read the winner's row instead of racing to insert.

Practical note for anyone running the suite: a green `python3 -m unittest discover -s
tests` does not prove this is fixed, and a red one on *this test alone* is probably not
your change.

**Re-measured again 2026-08-07**, after the configuration refactor (`defaults/` +
`switchboard/config.py`): **4 failures in 20 runs** of `tests/test_workspace.py`, both
faces present. Unchanged from the 5-in-25 above, i.e. the refactor neither fixed it nor
made it worse — the contended section is store-and-stub only and no config is read inside
it. Still not worked around, still `_adopt`'s missing guard.

### STATUS: FIXED (review pass, 2026-08-07)

Re-measured before touching anything: **2 failures in 25 runs**, both faces, as described.
After the fix: **60 runs, 0 failures**, plus the full suite green.

The suggested fix — catch `IntegrityError` in `_adopt` and re-read — would have silenced
the loud face and left the quiet one. The `created = 0` face is not `_adopt` racing
`_adopt`; it is `_adopt` racing `delegate`. Thread A started the herdr agent and *then*
tried to write its row, by which time B had already adopted the agent A had just started.
A caught the IntegrityError, concluded it had lost, and reported `created=False` — so the
agent existed and nobody claimed to have made it.

The real defect is the ORDER: `delegate` spawned first and recorded second, so the store —
the only thing the openers share — was consulted after the decision it was supposed to
arbitrate. Fixed by inverting it:

- `store.claim_agent` (`store.py`) is `INSERT OR IGNORE` and returns whether this process
  got the row. The PRIMARY KEY on `agents.name` is the arbiter, which is what a PRIMARY KEY
  is for.
- `Broker.delegate` claims the name **before** `agent start`, and `store.drop_agent`s it if
  the spawn then fails, so a failed spawn cannot hold a name hostage.
- `Broker._adopt` claims instead of inserting, and re-reads on a loss.
- `Broker._spawn_lead` now distinguishes three shapes of prior row rather than two: a
  session id means restore; a pane and no session means another opener is mid-spawn into
  this name, so join it; neither means a husk, so replace it. The middle case did not exist
  before and is exactly what a claim creates.

Two things fell out. `sb delegate --name <existing>` used to raise a bare
`sqlite3.IntegrityError` through the CLI as a traceback; it is now `AgentNameTaken`, a
ValueError, which the CLI already reports properly. And the losers no longer create a tab
at all, so there is nothing to close afterwards — a contested workspace cannot fill with
dead shells because none are made.

---

## `Herdr.wait` sends `--until idle,blocked`, which herdr 0.8.0 refuses

**Found:** 2026-08-07, while building `sb wait` (in cli.py/status.py, not herdr.py).

**What I ran**

```
sb wait busy-test --timeout 5
```

which reaches `Herdr.wait(name, until=(IDLE, BLOCKED))` — the adapter's own default —
and from there `herdr agent wait <name> --until idle,blocked --timeout 5000`.

**Expected**

Block until the agent goes idle or blocked, per the docstring on `herdr.Herdr.wait`.

**What happened**

Every call fails instantly, so nothing ever waits:

```
sb: herdr [cli_failure] invalid agent status: idle,blocked
    (expected idle, working, blocked, done, or unknown)
```

`herdr.py:477` joins the states with a comma:

```python
self._call("agent", "wait", name, "--until", ",".join(until), "--timeout", str(remaining))
```

but `--until` takes ONE status. Verified against the live binary: `--until idle` returns
an `agent_info` result as documented, `--until idle,blocked` is rejected as above.
Repeating the flag (`--until idle --until blocked`) is *accepted*, but there is no sign
it means "either" rather than last-one-wins, so it is not obviously the fix.

`Herdr.wait` has no test that exercises the argv it builds, which is why the default
argument of a public method could be unusable.

**Impact / what I did instead**

`status.wait_for` passes a single-element sequence (`(IDLE,)`, or `(WORKING,)` for
`--for working`), which is the one form herdr definitely honours. The cost is that a
herdr-detected `blocked` — its own detector spotting a permission prompt on screen — no
longer wakes the wait, so `sb wait` on an agent sitting at a TUI prompt blocks until its
timeout instead of returning early. Fixing the adapter would let that go back to waking
on either.

### STATUS: FIXED in the adapter (review pass, 2026-08-07)

`Herdr.wait` now takes `until: str`, one state, defaulting to `IDLE` — the signature
matches what the CLI underneath can actually do, instead of offering a set and joining it
into something that is always refused. An unknown state raises before any subprocess runs.

Repeating the flag was not adopted: it is *accepted* by herdr but there is no evidence it
means "either" rather than last-one-wins, and a wait that silently watches the wrong state
is worse than one that watches a narrower one.

The workaround in `status.wait_for` stays and is now the plain reading of the API rather
than a workaround; `status._next_transition` returns a `str` to match. The cost noted
above is unchanged and is small: `sb block` deliberately never reports herdr's `blocked`
(see QA B2), so the only thing lost is herdr's detector spotting a permission prompt, and
`sb status` reports that separately as AT PROMPT.

**The test that was missing now exists.** `tests/test_herdr.py::test_until_reaches_herdr_
as_one_status` asserts on the argv. That absence is the whole reason a public method's
default argument could be unusable.

---

## `Herdr.wait`'s stale-wait guard spins at 100% CPU on an already-idle agent

**Found:** 2026-08-07, immediately after the `--until` bug above, same feature.

**What I ran**

```
sb wait busy-test --timeout 6      # busy-test is STALLED: herdr idle, store 'working'
```

**Expected**

Six seconds blocked inside herdr, costing nothing.

**What happened**

Right answer, wrong cost — `2.60s user 2.17s system 77% cpu` for a 6-second wait. It is
not waiting, it is hammering herdr in a loop.

`herdr agent wait <name> --until idle` returns **instantly** when the agent is *already*
idle (verified: it came straight back with `agent_status: "idle"`). `Herdr.wait` then does
the right thing for the non-turn-scoped bug it was written for — sees `state_change_seq`
has not advanced past `since_seq` — and loops. With no sleep:

```python
while True:
    remaining = max(1, int((deadline - time.time()) * 1000))
    self._call("agent", "wait", name, "--until", ..., "--timeout", str(remaining))
    a = self.get_agent(name)                     # a second subprocess, every iteration
    if since_seq is None or a.change_seq > since_seq:
        return a
    if time.time() >= deadline:
        raise HerdrError("wait_timeout", ...)
```

Two `herdr` subprocesses per iteration, as fast as they will spawn, for the whole timeout.
A default `sb wait` (900s) would do this for fifteen minutes. The guard is right; it just
assumes `agent wait` blocks, and it does not when the agent is already there.

Likely fix: a small backoff before re-waiting, or have `Herdr.wait` itself ask for the
transition rather than the state.

**Impact / what I did instead**

`status._next_transition` picks the herdr state the agent is **not** in — an idle agent is
waited toward `working`, and the turn-ending `idle` is caught on the next pass of
`wait_for`'s own loop. Every `agent wait` then blocks for real, so there is no spin, and
the same 6-second wait now costs nothing. This only protects `sb wait`; any other caller
of `Herdr.wait` still spins.

### STATUS: FIXED in the adapter (review pass, 2026-08-07)

The last sentence above was the actual problem: the guard was correct, the workaround was
correct, and neither was in the file that could be called by somebody who had not read
this. `Herdr.wait` now sleeps `timeouts.agent_wait_backoff` (0.5s) before re-issuing a
wait that came straight back without the seq advancing, clamped so it never sleeps past
the deadline. Two tests pin it, one for each half.

`_next_transition` stays and is still the better mechanism — it makes every `agent wait`
a real block, so the backoff is a formality rather than the thing doing the work. Both
belong: one is a caller being smart, the other is the adapter refusing to burn a core for
a caller that is not.

This is a C10 violation of the exact shape the principle names, at zero token cost — worth
noting, because "idle costs nothing" is easy to read as being only about tokens.

---

## A schema change deadlocks every running agent — `store.connect` had no way forward

**Found:** 2026-08-07, while adding `agents.workspace_id` (fixing child workspace placement).

**What I ran**

```
# added one nullable column to store.SCHEMA, then any sb command at all:
sb status
```

**Expected**

The new column to appear. The store is documented as disposable (`connect()`: "There are
no migrations... on a schema change we simply drop and recreate"), so at worst a wipe.

**What happened**

`store.LiveAgentsError` out of every single `sb` invocation, for every agent on the
machine at once. Seven agents were live, so `_reset` refused; `connect()` is the first
thing every command does, so the refusal took down `sb done`, `sb ask`, `sb tell` and
`sb inbox` simultaneously. The human had to reach the agents through herdr directly.

The deadlock is structural, not a slip:

- the only migration strategy was wipe-on-hash-change;
- wiping is refused while agents are live — correctly, it would destroy a running workflow;
- the only way to stop being live is `sb done`, which calls `connect()`, which refuses.

So **no schema change could ever be applied while switchboard was running**, and the
failure is unrecoverable from inside the system. Worse, the hash covers the SCHEMA string
verbatim: editing a *comment* in it is enough to trigger the whole thing.

**Fix (applied)**

`store.connect` now tries `_migrate_additive` before `_reset`. It diffs the code's SCHEMA
against `PRAGMA table_info`, and if the only difference is added nullable columns it
applies them with `ALTER TABLE ADD COLUMN` and restamps the hash — no reset, no refusal.
Anything genuinely incompatible (a dropped column, a new table, a `NOT NULL` with no
literal default) still falls through to `_reset`. `_reset`'s live check now asks **herdr**
who is actually running rather than trusting the store's `state` column (which drifts
'working' forever when an agent exits without reporting), and takes a `force` escape hatch
that the error message names.

**Still open**

A non-additive change — dropping a column, adding a table — remains a hard stop while
agents are live, with the same "you cannot get there from here" shape. The escape hatch is
now documented in the error (`sb doctor --reset-store --force`) rather than absent, but the
underlying "operational state is disposable" assumption does not survive contact with
long-lived agents, and probably wants revisiting.

### STATUS: FIXED, and the escape hatch now exists (review pass, 2026-08-07)

The migration half was already done and is verified — `tests/test_store.py` covers it.

The escape hatch was not. `store._reset`'s error told the human to run
`sb doctor --reset-store --force`, and **`sb doctor` had no such flags**: the one way out
of an unrecoverable deadlock was a command that would have exited 2 on unrecognised
arguments. An error message naming a command that does not exist is worse than an error
message naming none, because it costs the reader the time to try it. Both flags added,
plus `store.reset` as the public face of `_reset`.

The remaining hard stop is unchanged and still worth revisiting.

## `sb wait` returns success while the agent is still working

- **Ran:** `sb wait refactor-config --for done --timeout 5400`
- **Expected:** block until the agent reaches `done`, ~an hour later.
- **Got:** exit 0 within minutes, while `sb status` still showed `refactor-config working`.
- Adds to the two `Herdr.wait` bugs already logged. The stale-wait guard (compare
  `state_change_seq` taken *before* prompting) is the thing that is supposed to prevent
  exactly this, so either it is not being applied here or `--for done` maps to a herdr
  state that was already satisfied.
- Consequence: any script that waits on an agent proceeds too early — which is how the
  `$SECONDS` class of false conclusion gets drawn.

### STATUS: NOT REPRODUCIBLE against this code — property now pinned (review pass, 2026-08-07)

Read honestly: **I could not find a path to this, and I did not observe it.** Saying so
rather than closing it, because the report is specific and a live agent was involved.

Both theories in the entry are ruled out by reading `status.wait_for`:

- *"the stale-wait guard is not being applied here"* — it is, but it is not what would
  gate this. `--for done` is a **store** state. `_reached(state, hstate, "done")` is
  `state == "done"` and nothing else; herdr's seq never enters it.
- *"`--for done` maps to a herdr state that was already satisfied"* — it maps to no herdr
  state at all. herdr's enum has no `done` (it derives one read-side), which is precisely
  why `sb done` reports `idle` and records `done` with us.

Every other exit from the loop returns `ok=False`: a finished-but-different state, a
timeout, an immediate herdr failure, a vanished row. So `exit 0` requires the store to
have said `done`, and `sb status` reads that same column — the two readouts in the report
cannot both have been right at the same instant.

The most likely explanation is that the two commands were not the same instant, or that
this predates the current `wait_for`. There is no git history to check against (the tree
has no commits), so that stays a guess and is labelled one.

What is not a guess is that the property had no test. Two now exist
(`tests/test_inspect.py::test_for_done_never_succeeds_while_the_store_says_working` and
`…_reports_failure_rather_than_success_on_a_failed_agent`), including the adversarial case
where herdr transitions repeatedly while the store never moves. **If this recurs, it is a
new bug and these tests will have something to say about where.**

---

## An agent that has called `sb done` becomes `human` — it then reads the human's mail

**Found:** 2026-08-07, by being the agent it happened to (`build-cli`), on the follow-up
turn after reporting done.

**What I ran**

```
sb done "..."          # finish the first task
# ... human sends a follow-up; the doorbell rings: "You have mail. Run: sb inbox"
sb inbox
```

**Expected**

The two unread messages addressed to `build-cli` — one of them a new task from the human.

**What happened**

```
(no new messages)
```

They were still sitting there unread:

```
[9] UNREAD from human (tell): FOLLOW-UP once your current work is done...
[7] UNREAD from fix-workspace (tell): FYI ... 4 tests red on main ...
```

`sb inbox` had read the **human's** mailbox instead of mine. `Broker.whoami` resolves the
caller by pane, with `ended_at IS NULL`:

```python
row = self.db.execute(
    "SELECT name FROM agents WHERE pane_id=? AND ended_at IS NULL "
    "ORDER BY created_at DESC LIMIT 1", (pane,)).fetchone()
...
return HUMAN
```

`broker.done` → `store.set_state(..., "done")` stamps `ended_at`. So from the moment an
agent reports done, every later `sb` call it makes falls through to `HUMAN`. Confirmed
directly:

```
HERDR_PANE_ID env : w1:p2H
whoami            : human
row pane_id       : w1:p2H | ended_at: 1786104294 | state: done
```

**Why it is worse than lost mail**

The fallback is silent and it is *identity*, not just a read. A done-then-poked agent:

- reads and CONSUMES the human's inbox (`sb inbox` marks read) — the human's mail is gone,
  and the agent never sees its own;
- has everything it sends attributed to the human, so `sb tell` arrives as if a person
  wrote it;
- cannot report at all — `broker.done` raises `ValueError("sb done is for agents")` for
  `HUMAN`, so there is no way back out.

`broker.restore` already documents this exact hazard ("leaving ended_at set makes a
restored agent resolve to HUMAN — it then silently consumes the human's mailbox and
everything it sends is attributed to the human. Verified end to end by QA") and clears
`ended_at` for the restore path. The ordinary path — done, then given more work by the
doorbell — has no such clearing, and `_ring`/`flush_pending` will happily ring an agent
whose row is ended.

Likely fix, in the place that already knows: `_ring` reopens a `done` target the same way
`_unblock_if_needed` reopens a `blocked` one (clear `ended_at`, set `working`). Ringing an
agent IS asserting it has more to do. `whoami` could also prefer an ended row over `HUMAN`
rather than falling through to a different identity.

**Not worked around silently.** `switchboard/broker.py` and `store.py` are owned by
someone else. To finish the follow-up task I was sent, I cleared `ended_at` on my own row
(exactly what `restore` does, and true — I am running again) so that `sb done` would
reach me instead of raising. That is a one-row local unstick, not a fix; the bug is live
for every agent that is poked after reporting.

---

## STATUS UPDATE — 2026-08-07 07:0x

**`An agent that has called sb done becomes human` — FIXED.**
`Broker.whoami` matched only on `ended_at IS NULL`, so a finished agent resolved to
`HUMAN`: it read the human's mailbox, attributed its messages to the human, and could not
call `sb done` at all. Reporting done ends a *turn*, not an existence — the pane is still
there and something in it is running `sb`, which is proof enough. A finished row now
resolves and is revived on the spot (`_revive`). Session id is preferred over pane id
because pane ids are recycled once a pane closes. Two regression tests.

**`ask` waiting out its timeout on a child that died recording nothing — FIXED.**
`_will_never_answer` is store-only by design (an agent missing from `agent list` looks the
same whether it died or herdr hiccupped). `ask` now also counts *consecutive* absences
from herdr and gives up after `timeouts.gone_grace` (60s, in `defaults/settings.toml`).
One missing reading is a hiccup; a minute of them is a death. Two tests, including one
asserting a single absence does **not** end the wait.

## `--permission-mode auto` is model-dependent — haiku blocks where opus does not

**Found:** 2026-08-07, after `explore-hooks` (researcher role → `cheap` tier → haiku)
stalled on a permission prompt despite being spawned with `--permission-mode auto`.

**Test:** two agents, same task, same flag, different model.

```
sb delegate "...cd /tmp && mkdir -p X && cd X && date +%s > f.txt..." --model haiku   -> BLOCKED
sb delegate "...same command..."                                     --model opus    -> ran it
```

haiku's pane: *"Multiple directory changes in one command require approval for clarity /
Do you want to proceed?"*. opus wrote the file without prompting.

**Why:** the docs describe auto mode as running a **classifier** that evaluates actions
against configured rules (code.claude.com/docs/en/settings, which also documents
`permissions.disableAutoMode`). That classification is evidently not identical across
models. Not a flag problem — the flag is passed correctly on every spawn.

**Consequence:** a `cheap` tier on haiku is unusable for unattended work; every agent
using it stops for a human on ordinary shell commands.

**STATUS: FIXED in config, not code.** No tier uses haiku at all — `defaults/models.toml`
`tiers.cheap` resolves to `sonnet` at `effort = "low"`. Cheapness comes from effort, not
from a smaller model, because a model that blocks on ordinary commands costs a human's
attention, which is the expensive thing.
