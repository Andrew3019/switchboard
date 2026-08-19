# reviewer-30 — adversarial review: the reporting / CLI / result-shape surface of cascade-close

Artifact: `8494b3f`, `30c1e62`, `5e060f3`, `227c3c3` on `fix-orphaned-dispatcher-children`,
read as they are at HEAD (`227c3c3`). Lens: what the command HANDS BACK and what it SAYS.
Not selection correctness, not recursion/deletion.

**Verdict: needs changes.** The result *shape* is clean — the divergence, the emptiness
promise and the degenerate rendering all check out. The *words* and the *counts* do not:
the bare route's headline sentence contradicts the cascade lines directly below it, the
pane count under-reports every pane the cascade closed, and one ordinary shape drops a
space out of BOTH lists with no line at all.

All three findings were reproduced live against the real broker via the repo's own close
harness (`tests/test_workspace_close.py:CloseHarness`); the scratch scripts are quoted in
full below so anyone can re-run them.

---

## 1. CONFIRMED — "nothing was deleted" is printed one line above a deleted worktree

`cli.py:1323-1325` (`_workspace_closed`):

```python
if r["kind"] == "bare":
    lines.append(f"retired {r['workspace']} — no checkout of its own, so nothing was "
                 f"deleted")
```

then `cli.py:1340-1341`:

```python
if r["spaces"]:
    lines.append(f"  closed space(s): {', '.join(r['spaces'])}")
```

That sentence was true when `_close_bare` really did delete nothing. Since `8494b3f` the
bare route runs `_cascade` (`broker.py:1911`), and `spaces` is the list of worktrees this
very command *destroyed*.

Reproduced (bare `main-2`, one finished child `worker` with a clean forked space):

```
closed 1 pane(s): main-2
retired main-2 — no checkout of its own, so nothing was deleted
  closed space(s): worker
```

`worker`'s directory is gone from disk and deregistered from git at that point (the
branch's own test `test_a_finished_childs_forked_space_is_closed_too`,
`tests/test_workspace_close.py:753-765`, asserts exactly that). A human who reads top-down
reads "nothing was deleted" and stops; "closed space(s)" is one indented line and does not
say *deleted a directory*. Both halves of the claim are wrong in the same direction, and
this is the one command in here that cannot be undone.

Why it counts as a defect and not taste: the docstring of `_workspace_closed`
(`cli.py:1309-1318`) states the rule this breaks — "Which of the three routes the
workspace took is the first thing to say, because 'bare' doing nothing to a directory and
'worktree' deleting one are the same word otherwise." The cascade made "bare" a route that
deletes directories, and the sentence written to keep those two apart was not revisited.

Shape of a fix (not applied): make the bare sentence conditional on `r["spaces"]` — e.g.
"retired main-2 — no checkout of its own" plus "deleted 1 forked space(s): worker" — so the
word *deleted* appears where deletion happened.

## 2. CONFIRMED — the pane count reports only the bare workspace's own panes

`_close_bare` reports `closed=` from its own `_stop_panes` (`broker.py:1910, 1918`). The
cascade below it calls `self.workspace_close(name, me=me)` per child space
(`broker.py:4711`) and **discards the returned dict**, which carries that close's own
`"closed"` list — the panes `_close_checkout` → `_stop_panes` took down in the child space
(`broker.py:2088`, `broker.py:2584-2600`). `_stop_panes` closes a pane for every row filed
under the workspace that still has one, and a *finished* row can still hold a pane (that is
what `test_its_own_panes_come_down_with_it`, `tests/test_workspace_close.py:718-725`, pins).

Reproduced — bare `main-2` with its own drawn pane `w1:p1`, child `worker` with a drawn
pane `w2:p2` on a `done` row:

```
RESULT closed: ['main-2'] spaces: ['worker'] refused: []
PANES actually closed: ['w1:p1', 'w2:p2']
---- rendered ----
closed 1 pane(s): main-2
retired main-2 — no checkout of its own, so nothing was deleted
  closed space(s): worker
```

Two panes left the board; the command said one, and named the wrong single one as the whole
of it. `--json` is no better — it carries the same short `closed` list
(`cli.py:1204-1206` passes `{**r, ...}` through unchanged).

This is new with the artifact: before `8494b3f` the bare route never reached another
workspace's panes, so there was nothing to under-count.

Scenario cost: an agent's pane disappearing without being named is precisely the case
`CleanupResult`'s docstring calls out as "closed: (nothing) is not a report", and the same
file's `cleanup` path prints `closed` per pane. A person looking for `worker`'s pane on the
board has nothing in the transcript that says where it went.

Shape of a fix (not applied): have `_close_empty_spaces` keep the nested result's `closed`
(it already has the dict in hand at `broker.py:4711`) and fold those names into the report,
or say the count separately as "and N pane(s) in the spaces below".

## 3. CONFIRMED — a child space held by the caller's own cwd is dropped from BOTH lists

`_close_empty_spaces` skips three shapes in silence (`broker.py:4703-4708`): unrecorded /
already retired / bare, the caller's own workspace *name* (`w not in my_names`, line 4700),
and the caller's own *directory* —

```python
if any(live.is_under(d, row["checkout"]) for d in my_dirs):
    continue                       # the caller's own directory under another name
```

`my_dirs` is `os.getcwd()` for a human (`_my_spaces`, `broker.py:4728`). So: a human
standing inside a child's forked worktree — the ordinary place to be while tidying that
subtree up — types `sb workspace close <dispatcher>` and the child space is neither closed
nor reported.

Reproduced (cwd set to `worker`'s checkout, everything else identical to finding 1):

```
closed: [] spaces: [] refused: []
worker workspace row retired: None
---- rendered ----
retired main-2 — no checkout of its own, so nothing was deleted
```

The output is indistinguishable from "this dispatcher had no forked spaces at all". And it
is not recoverable by re-running: the dispatcher is retired, so the second run takes
`workspace_close`'s `already` branch (`broker.py:1819-1821`) and prints "was retired
already — nothing left to do". The one command whose stated job is to take these spaces
has left one standing and said nothing, permanently.

That silence is deliberate *for a sweep* — `_close_empty_spaces`'s docstring argues it, and
`tests/test_workspace_close.py:1089` pins it (`# skipped in silence, not refused`). The
argument is "none of them is news", and it holds for a fleet-wide `sb cleanup`. It does not
hold here: `sb workspace close <name>` is one named workspace a person asked about, and
`_workspace_closed`'s own comment (`cli.py:1336-1339`) says so out loud — "this is a
command a person typed about one named workspace, and a space left standing is the thing
they will trip over later." The cascade inherited the sweep's silence policy along with the
sweep's helper.

Same hole, less likely, for `w not in my_names` (line 4700) and for the bare/unrecorded
skips at line 4705 — those last are genuinely not news (nothing to delete).

Shape of a fix (not applied): give `_close_empty_spaces` a way to record "skipped: you are
standing in it" into `spaces_refused` when it is being driven by `_cascade` rather than by
a sweep.

## 4. Nit (PLAUSIBLE, cosmetic) — "Nothing has been touched." inside a kept-space reason

The reason strings come straight from the gates. `_inventory_gate` ends its ignored-content
refusal with "Nothing has been touched. `sb workspace close <child> --yes` deletes them
with the checkout." (`broker.py:2304-2311`). Rendered by `_workspace_closed`:

```
  closed space(s): l1
  kept space l2: /x/y holds 3 ignored file(s) ... Nothing has been touched. `sb workspace close l2 --yes` deletes them with the checkout.
```

"Nothing has been touched" is true of `l2` and false of the command, which has just retired
the dispatcher, closed panes and deleted `l1`. Low severity — the sentence sits inside a
line that names `l2` — but it is the second place (with finding 1) where a sentence written
for a single close reads wrong once it is quoted inside a cascade report.

The advice half of that message is CORRECT and I checked it specifically: the `--yes` it
suggests names the *child*, and `sb workspace close l2 --yes` genuinely works after the
dispatcher is retired. `--confirm` does not propagate down the cascade
(`_space_ready(..., confirm=False)`, `broker.py:4785`; `workspace_close(name, me=me)` at
line 4711 passes no `confirm`), so re-running the dispatcher close with `--yes` would NOT
get past it — but the message never suggests that, so there is no lie here.

## 5. Nit (PLAUSIBLE, latent) — the `already` branch emits the result dict unreshaped

`cli.py:1200-1206`:

```python
if r["already"]:
    _emit(args, f"{r['workspace']} was retired already — nothing left to do", r)
    return 0
_emit(args, _workspace_closed(r),
      {**r, "spaces_refused": [{"name": n, "reason": why} for n, why in r["spaces_refused"]]})
```

The early return skips the tuple→dict reshaping. Harmless today: that route builds the dict
via `_closed(..., already=True)` (`broker.py:1820`) with both cascade lists empty, and `[]`
serialises the same either way. It is a shape divergence waiting for the day something
fills those lists on an `already` return.

---

## What I checked and found CLEAN (the brief asked; saying so plainly)

- **tuple-vs-dict divergence is deliberate and consistent.** `_closed` returns
  `spaces_refused` as tuples (`broker.py:2172`) and `CleanupResult.spaces_refused` holds
  tuples (`broker.py:495`); *both* CLI emitters reshape to `{"name","reason"}` dicts —
  `cleanup` at `cli.py:1165-1166`, `workspace close` at `cli.py:1205-1206`. Same convention
  as the neighbouring `refused`, `skipped`, `unrestorable` lists. A `--json` consumer sees
  dicts everywhere; a Python caller sees tuples everywhere. No mixed field.
- **No consumer indexes the wrong shape.** The only Python readers are the tests
  (`dict(r["spaces_refused"])`, `tests/test_workspace_close.py:773, 850, 863, 1074`) and
  they read tuples, correctly. `_close_empty_spaces` ignores the nested return entirely
  (which is finding 2, not a shape bug).
- **`spaces`/`spaces_refused` really are present-and-empty on every route.** Every exit of
  `workspace_close` that returns a dict goes through `_closed` — bare (`broker.py:1917`),
  already-retired (`1820`), gone and checkout (both via `_finish`, `2148`) — and `_closed`
  always emits both keys (`broker.py:2171-2172`). The other exits raise. Verified by
  reading every `return` in `workspace_close` and both routes.
- **Degenerate rendering is clean.** With both lists empty the output is exactly
  `retired disp — no checkout of its own, so nothing was deleted` — no stray
  `closed space(s): ` header, because `if r["spaces"]` guards it (`cli.py:1340`) and the
  refusal lines are a `lines.extend(...)` over an empty list (`cli.py:1342`).
- **The `already` early return skips the cascade lines correctly** — it never calls
  `_workspace_closed` at all (`cli.py:1201-1203`).
- **No refusal reason contains a newline**, so no `kept space X: ...` line can break apart
  and lose its indent or its name. Checked every `raise ValueError` body in `broker.py`.
- **Reasons read sensibly to someone who typed `sb workspace close`.** `_cascade`'s own
  reason ("`qa-1 is still working underneath lead-3, whose space this is`",
  `broker.py:1948-1950`) names the agent, the space and the relation. The gate-sourced ones
  are `workspace_close`'s own words and carry a `cannot close 'l3':` prefix that duplicates
  the name already in `kept space l3:` — redundant, but that is taste and I am not counting
  it.
- **`tests/test_workspace_close.py` passes at HEAD**: `73 passed in 13.94s`
  (`/Users/andrew/anaconda3/bin/python -m pytest tests/test_workspace_close.py -q`).

## What I did NOT check

- The `sb cleanup` text path's own space lines (`cli.py:1148-1166`) beyond confirming the
  reshaping matches — cleanup's reporting policy is not this artifact.
- Anything about *which* spaces the cascade selects (`_forked_under`) or the recursion and
  deletion dynamics — other lenses, and reviewers 28 and 29 have them.
- No live-clone run. All three findings are reproduced through the repo's own fake-herdr
  close harness, which drives the real `broker.workspace_close`, the real gates and the real
  git worktrees in a temp repo; the pane closures in finding 2 are the fake herdr's record
  (`self.h.closed`), not a real tmux. The *rendering* in findings 1 and 4 is the real
  `cli._workspace_closed` on real result dicts.

## Reproduction scripts

Both were run from the repo root with
`/Users/andrew/anaconda3/bin/python -m pytest <file> -s -q`. Neither is committed — they
live only in this session's scratchpad; paste them into a file to re-run.

```python
# finding 2 — the under-counted panes
import unittest, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
from tests.test_workspace_close import CloseHarness
from switchboard import store
from switchboard.broker import HUMAN

class T(CloseHarness, unittest.TestCase):
    def test_child_panes_unreported(self):
        store.record_workspace(self.db, "main-2", None)
        self.row("main-2", workspace="main-2", cwd=str(self.repo), state="done")
        store.update_agent(self.db, "main-2", pane_id="w1:p1"); self.h.panes.add("w1:p1")
        path = self.space("worker", commit=True)
        self.agent("worker", workspace="worker", cwd=path, state="done")
        self.db.execute("UPDATE agents SET parent=? WHERE name=?", ("main-2", "worker"))
        store.update_agent(self.db, "worker", pane_id="w2:p2"); self.h.panes.add("w2:p2")
        r = self.b.workspace_close("main-2", me=HUMAN)
        print("RESULT closed:", r["closed"], "spaces:", r["spaces"])
        print("PANES actually closed:", self.h.closed)
        from switchboard.cli import _workspace_closed
        print(_workspace_closed(r))
```

```python
# finding 3 — the space dropped from both lists
import unittest, sys, os
sys.path.insert(0,'.'); sys.path.insert(0,'tests')
from tests.test_workspace_close import CloseHarness
from switchboard import store
from switchboard.broker import HUMAN
from switchboard.cli import _workspace_closed

class T(CloseHarness, unittest.TestCase):
    def test_human_standing_in_child_space(self):
        store.record_workspace(self.db, "main-2", None)
        self.row("main-2", workspace="main-2", cwd=str(self.repo), state="done")
        path = self.space("worker", commit=True)
        self.agent("worker", workspace="worker", cwd=path, state="done")
        self.db.execute("UPDATE agents SET parent=? WHERE name=?", ("main-2","worker"))
        old = os.getcwd(); os.chdir(path)
        try: r = self.b.workspace_close("main-2", me=HUMAN)
        finally: os.chdir(old)
        print("closed:", r["closed"], "spaces:", r["spaces"], "refused:", r["spaces_refused"])
        print("worker retired:", store.get_workspace(self.db,"worker")["retired_at"])
        print(_workspace_closed(r))
```
