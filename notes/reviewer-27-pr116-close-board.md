# Adversarial review — PR #116, `_close_board` keep + retry

Reviewed: commit `530f998` on `herdr-cleanup-gaps`
(`switchboard/broker.py`, `tests/test_workspace.py`). Review only; nothing edited.

**Verdict: needs one change before merge.** The asymmetric classification itself is
right, `--force` is right, the docstring is close to right. But the *mechanism* chosen to
carry the retry — holding the agent row open with a `pane_id` that points at a pane
cleanup has just successfully closed — creates a new permanent wedge when herdr recycles
that pane id before the next sweep. I reproduced it.

---

## 1. (blocker) A deferred row wedges forever if its freed pane id is recycled

`switchboard/broker.py:4437` — on a defer, cleanup `refuse`s and `continue`s *after*
`release_agent` + `close_pane` have already succeeded on the agent's own pane
(`broker.py:4396-4400`), and *before* `store.update_agent(..., pane_id=None)`
(`broker.py:4460`). So the row is left claiming a pane that is definitely gone.

`_close_target`'s own docstring (`broker.py:5340-5374`) says a pane id "is recycled the
moment a pane closes, and herdr is machine-global". When that happens between sweeps:

- sweep 2 reaches the identity gate at `broker.py:4372`,
- `_close_target` returns the recycled-id refusal (`broker.py:5395-5397`),
- cleanup refuses and `continue`s **before** `_close_board` is ever reached.

The row can then never be closed by any sweep, and the board pane the PR set out to save
is never closed either — so in this branch the change is strictly worse than the old
behaviour, which ended the row `done` cleanly and lost only the pane. `--force` is the
only exit. It also blocks `sb workspace close` for that whole workspace: `_stop_panes`
*raises* on the same refusal (`broker.py:2485-2491`).

Reproduced against the real broker with the repo's own fake herdr (scratch probe, not
committed — the shape is: run `cleanup` with the board's `close_pane` raising
`HerdrError("close_failed")`, then drop the agent from `h.live` and put a stranger with a
different `terminal_id` on the freed pane id, then sweep again):

```
RECYCLED sweep2: closed=[] refused=[('worker-1', "pane w1:p3 is now stranger's
  (term-theirs), not this row's (term_worker-1) — its own pane is gone and the id was
  recycled under it")] pane_id=w1:p3 board_row=w1:p3s4 board_closed=False
RECYCLED sweep3: [] [same refusal]
```

Control (no recycling) converges as the PR intends: `GONE sweep2: ['worker-1']
board_closed=True`.

**Direction, not a design I am asking for:** the retry does not have to ride on a stale
`pane_id`. If the "already closed" branch (`broker.py:4263`) called `_close_board` before
refusing — it is a no-op when the meta row is gone — then a defer could clear `pane_id`
and mark the row `done` honestly, and the board would still be retried on every later
sweep with no stale id to be recycled under it. That also removes finding 2 below.

## 2. (risk, unverified) The retry re-issues `release_agent` against a dead pane

`broker.py:4396-4400` calls `release_agent` before `close_pane`, inside one `try`. Sweep 2
of a deferred row calls it against a pane sweep 1 already closed. The handler only
tolerates `e.code == "pane_not_found"` (`broker.py:4406`); anything else refuses and the
row wedges again.

I could not verify what herdr returns for `pane release-agent` on a missing pane.
`reference/herdr-adapter-reference.md:188` documents the params but no error codes, and
`research/01-herdr.md:569` lists `agent_pane_not_found` as a distinct code from
`pane_not_found`. The exposure is pre-existing (the hand-closed-pane path has the same
ordering, and `tests/test_broker.py:2009` only stubs `close_pane`, never `release_agent`),
but the defer path now walks it routinely rather than rarely. Worth one check against a
live herdr, or closing before releasing.

## 3. (must-fix wording, cheap) The `_stop_panes` comment states something untrue

`broker.py:2507-2510` justifies ignoring the deferred return with "the pane is still
reachable through it". It is not. `board_pane:` rows have exactly three readers
(`broker.py:1392`, `1483`, `1532`). After `_stop_panes`, that row's agent has
`pane_id=None` and `ended_at` set, so every later `cleanup` takes the "already closed"
exit at `broker.py:4263` and `_close_board` is never called for it again. The row is a
dead pointer, not a retry handle.

**Verdict on the `_stop_panes` wrinkle (brief #5): acceptable to merge, comment must be
corrected.** The leaked pane is the same pane the old code leaked; nothing regresses. The
one new hazard is narrow: the stale row survives, and if herdr later recycles that pane id
onto a live pane, `_open_board` (`broker.py:1395-1396`) silently gives a restored agent no
board, and a later `_close_board` on an *unoccupied* recycled pane (a stranger's board
pane carries no agent, so it is absent from `_pane_cache`) would close it —
`_close_target` returns `(pane, None)` at `broker.py:5385`. Low probability, real
consequence; worth a line in the comment rather than a code change.

## 4. (minor) The defer refusal names no way out

`broker.py:4447`: `refuse(a, "herdr could not close its board pane", log=False)`. Every
neighbouring refusal that `--force` lifts says so (`broker.py:4288`, `4306`, `4331`,
`4356`), and the sibling agent-pane refusal carries the herdr error text
(`broker.py:4411`). A persistently unclosable board refuses on every sweep with neither
the reason nor the escape hatch in the line the operator reads.

## 5. (minor) Two `return True` paths are not "proven", contrary to the docstring

The docstring (`broker.py:1426-1429`) says True means "closed, already gone, or proven not
ours". Two paths return True on a *database* failure, having proven nothing:
`broker.py:1487` (meta read raises) and `broker.py:1531-1533` → `broker.py:1492`, where
`_board_is_only_for` returns False on any DB exception and the row is then dropped. The
second is the exact orphan-the-pane-forever shape this PR removes from the herdr side,
left in place on the store side. Pre-existing and very unlikely (the same table was read
successfully one line earlier); listed for completeness, not as a merge gate.

## What checks out

- **Classification (brief #1).** `NO_HERDR_ANSWER` is now a shared constant
  (`broker.py:595`, `broker.py:5379`), so the one refusal that proves nothing is matched
  by identity rather than by a duplicated string. Every other `_close_target` refusal
  (`broker.py:5390-5397`) names a live agent in the pane — proof, correctly forgotten.
  `pane_not_found` from `close_pane` is read as the close having happened, matching the
  agent-pane path at `broker.py:4406`.
- **Exception ordering.** `except HerdrError` precedes `except Exception`
  (`broker.py:1506-1521`); the `else:` success log cannot fire on the `pane_not_found`
  path; `_forget_board` runs exactly once on every True return. No double close.
- **`--force` (brief #3).** Reaches `_close_board` only via `force=force` at
  `broker.py:4437`; every defer becomes a drop, the row ends `done`. Verified by the PR's
  own `test_force_drops_a_board_it_could_not_close`. No use-after-forget.
- **Partial teardown (brief #4).** The defer `continue`s above `forget_prompt_file`,
  `set_state("done")`, `pane_id=None` and `_clear_unreadable_mail` — so the prompt file,
  the state and the mail are all untouched, and the retry re-runs the whole tail. The one
  thing already spent is `release_agent` + `close_pane` on the agent's own pane, which is
  findings 1 and 2.
- **No parent cascade.** A held-open row keeps a finished `state`, so it does not enter
  `live_descendants` and does not gate its parent. `pane_holding_descendants`
  (`broker.py:4895`) reads `pane_id` and would name it, but it gates nothing — only the
  wording of an "already closed" refusal.
- **Dry runs** exit at `broker.py:4374` before any board close.
- **Docstring (brief #6)** otherwise matches the code, including the `force` paragraph.
- **DESIGN-TRUTH.md** says nothing about board panes or `_close_board`; nothing here
  contradicts its cleanup entries (lines 489-515).

Stale prose elsewhere still describes the old rule — `notes/close-paths-resolved-by-
terminal-id.md:36`, `notes/agent-handoff-wording-brief.md:13`. Both are dated records
rather than live documentation; flagged, not asked to be changed.

## Suite

`/Users/andrew/anaconda3/bin/python -m pytest tests -q` on this branch: **1515 passed**
in 162s. The three new tests in `ClosingTakesTheBoardWithItTest` pass and test what they
claim. None of them covers the recycled-pane-id sweep in finding 1.

---

# Re-review — the rework (commit `52234fe`)

**Verdict: clear to merge.** The blocker is genuinely fixed, not papered over, and I could
not break the new mechanism. Two cosmetic notes below; neither holds the merge.

## The blocker is gone, verified against the recycle

`broker.py:4273-4284` puts the retry in the already-closed branch, and `broker.py:4459`
lets a defer fall straight through to `set_state("done")` / `pane_id=None`. So the row
ends honestly and there is no pane id left to be recycled under it.

Confirmed by re-running my own repro (scratch probe, not committed) — and, unlike the
committed test, with the broker's herdr caches cleared between sweeps so it actually
*observes* the recycle:

```
sweep1: pane_id=None board_row=w1:p3s4
sweep2: closed=[] refused=[('worker-1','already closed')] board_closed=True
        board_row=None agent_pane_closes=1
```

Converges on the next sweep, and the stranger who inherited the freed pane id is never
touched. Old mechanism on the same input wedged forever.

## The re-review questions

1. **Convergence / candidate-set.** A `done` row with no pane is still a candidate:
   `candidates = scope` (`broker.py:4141`), and `scope` is every agent for a human or
   `_descendants(me)` otherwise (`broker.py:4119-4123`) — neither filters on state or
   `ended_at`. Probed a board that never closes: sweeps 2 and 3 both retry, both refuse
   `already closed` with `expected=True`, so the sweep stays quiet and the row is already
   `done` — a leak that cannot wedge anything. Both exits also reach a retry: a row with
   `ended_at` takes `broker.py:4284`, and a hypothetical `done` row without one falls
   through to `broker.py:4459` with `target=None`. No path leaves the meta row with
   nothing ever calling `_close_board` again — including `_stop_panes`'s rows, which the
   next sweep now reaps (see below).
2. **Safe for done agents.** True no-op once the row is gone: `broker.py:1490-1492`
   returns on the first `SELECT`. Where a row *does* survive, the pane is resolved through
   `_close_target`'s no-identity rule (`broker.py:5387-5399`) — an occupied pane is
   refused and the row dropped, an empty one may be closed. Same-store collisions are
   caught earlier by `_board_is_only_for` (`broker.py:1532-1541`): another *live* agent's
   board row over the same pane forgets ours instead of closing. The residual is a
   cross-store recycle onto an unoccupied foreign pane, which is inherent to "keep the row
   and retry later" — the approved direction — and is the exposure `_close_target` was
   written to bound. Not new to this diff.
3. **Cost.** One primary-key `SELECT` on `meta` per ended row per sweep, returning on the
   first statement in the overwhelmingly common case. Cleanup already does `_descendants`
   and `live_descendants` per candidate. Not a regression.
4. **The new test.** `tests/test_workspace.py:864-886` reproduces my exact break — agent
   dropped from `h.live`, stranger with a different `terminal_id` on the freed pane id —
   and asserts the three things that matter: `pane_id` is None after sweep 1, the board
   row survives, and a later bare sweep closes the board with
   `self.h.closed.count(agent_pane) == 1`. It fails against the old mechanism at its very
   first assertion (old sweep 1 returned `[]`, not `[kid]`). One weakness, worth knowing
   rather than fixing: `Broker` caches `agent list` per process (`broker.py:5262-5276`),
   and the test never clears `_alive_cache`/`_pane_cache`, so the injected stranger is
   invisible to sweep 2 — the test proves "the row is not held open on a dead pane", not
   "the recycle is resolved correctly". My probe covers the second half and it passes.
5. **`_stop_panes` comment** (`broker.py:2511-2521`) — now names the real hazard, but one
   clause is still false: "that branch's retry finds a `board_pane:` row nobody will ever
   act on again". The retry *does* act on it — it calls `_close_board`, the workspace's
   pane is gone by then, `close_pane` answers `pane_not_found` and the row is reaped
   (`broker.py:1507-1511`). The code is better than the comment claims: the stale row
   lives for one sweep, not forever, which narrows the very hazard the next sentence
   warns about. Cosmetic; the comment oversells the cost, it does not hide one.
6. **Findings 2 and 4 are actually gone.** No `release_agent`/`close_pane` is re-issued —
   a retry enters at `broker.py:4273` and never reaches `broker.py:4396`. The defer
   refusal that named no way out is deleted outright; nothing new refuses.

## One new wrinkle (minor, not blocking)

`broker.py:4284` passes `force=force`, so `sb cleanup --force <name>` on a row that is
already `done` silently **discards** a pending board retry (`_close_board` drops the row
without closing the pane) while refusing the row as `already closed`. Probed: `refused=[
('worker-1','already closed')]`, `board_row=None`, pane still open. Defensible — `--force`
is documented to stop caring what herdr did — but under `--force <parent>` it applies to
the whole subtree via `_leaves_up`, and the operator is told only "already closed". If
that is not intended, `force=False` at that one call site keeps the retry alive; the
first-close path at `broker.py:4459` is where `--force` needs to drop it.

## Suite (rework)

`pytest tests -q` on `52234fe`: **1516 passed** in 161s — the worker's count, confirmed.
