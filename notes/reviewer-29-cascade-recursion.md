# reviewer-29 — cascade-close: recursion / reentrancy / deletion-safety

Lens: what happens DURING and AFTER the cascade fires. Not candidate-set selection
(reviewer-28's), not CLI/reporting.

Artifact: branch `fix-orphaned-dispatcher-children` at HEAD (30c1e62), incl. 8494b3f.

**Verdict: needs changes.** Two real defects (F1, F2), both traced and both reproduced in
the repo's own test harness. Recursion itself is clean — see F3, a positive result.

## Evidence base

- Code read at HEAD: `workspace_close` (broker.py:1782), `_close_bare` (1869),
  `_forked_under` (1911), `_close_gone` (1955), `_close_checkout` (1991), `_finish`,
  `_closed`, `_gate`/`_records_gate`/`_filed_gate`/`_inventory_gate` (2130–2262),
  `_stop_panes` (2507), `_claim`/`_take_over` (2370/2424), `_close_empty_spaces` (4616),
  `_my_spaces` (4677), `_space_ready` (4700), `sweep`/`_sweepable` (4745+),
  `_descendants` (5015); `store.retire_workspace`/`claim_retiring`/`release_retiring`.
- `python -m pytest tests` on this branch: **exit 0** (full suite passes).
- Two scratch probes driven through `tests/test_workspace_close.CloseHarness` (real git,
  real `ps`, faked process scan and herdr — the harness's own posture). Not a live `sb`
  run in a clone; I did not spin up a real fleet for this. Probe scripts are in the
  session scratchpad, not committed.

---

## F1 — CONFIRMED, most severe. A crash mid-cascade orphans the remaining spaces *permanently*

`_close_bare` (broker.py:1899–1907):

```
store.retire_workspace(self.db, name)      # 1903 — sets retired_at, checkout=NULL, clears the mark
...
self._close_empty_spaces(self._forked_under(name), spaces, me=me, dry_run=False)   # 1907
```

`_close_empty_spaces` catches **only `ValueError`** (4670). Anything else — `KeyboardInterrupt`,
`sqlite3.OperationalError` ("database is locked", entirely ordinary in this shared-DB fleet),
any `RuntimeError` — propagates straight out of `_close_bare`. Line 1907 is not wrapped.

By then the bare row is already retired. And `workspace_close` opens with:

```
if row["retired_at"] and not row["checkout"]:
    return self._closed(name, None, already=True, ...)      # 1819–1821
```

So the retry is a **no-op**. `--resume` cannot help either: `retire_workspace` cleared the
retiring mark at 1903, so there is no mark for `_take_over` to resume from.

### Reproduced

Dispatcher `main-2` (bare) with two clean, finished, committed children `aaa` and `bbb`.
`_deregister` raises `RuntimeError` on its first call:

```
bare retired_at: 1787101362          <- retired
aaa dir exists: True                 <- panes already closed, worktree still there, row not retired
bbb dir exists: True                 <- never even looked at
retry: {'already': True, 'spaces': [], 'spaces_refused': []}
bbb still there after retry: True
```

Both spaces are now unreachable by the command that was supposed to take them — they wait
for a DB-wide `sb cleanup`, by which time they are usually too dirty to auto-delete. That
is precisely the bug 8494b3f exists to fix, reintroduced on the failure path.

Aggravating: the CLI turns `HerdrError` and `sqlite3.OperationalError` into a one-line
`sb: ...` and exit 1 (cli.py:735–751). The person reads a failure and has no way to know
the bare space was in fact retired and some panes were in fact closed.

Fix shape (not applied): either widen the swallow at 4670 to `except Exception` for the
cascade's per-space loop, or retire the bare row *after* the cascade, or make the `already`
early-return re-run the cascade when the row is retired but namesake spaces remain.

---

## F2 — CONFIRMED. The cascade has no live-descendant gate; `sb cleanup` does

The commit message claims "every gate ... stays `workspace_close`'s, so a live or dirty
child's space is refused and reported as kept, **exactly as `sb cleanup` refuses it
today**". That is not true for one shape.

`sb cleanup` reaches a space only through rows it actually closed
(`_close_empty_spaces(candidates, ...)` at 4569, where `candidates` are the rows the
cleanup acted on), and cleanup refuses to close a row with **live descendants**. So
cleanup can never take a parent's space while a grandchild is still working.

The cascade builds its candidates straight from `_forked_under` → `_descendants`
(1911–1934) and gates each space only on rows *filed under that space* (`_filed_gate`) or
with *cwd under that checkout* (`_records_gate`). A live grandchild sits in its own space,
under its own name — invisible to both.

### Reproduced

`main-2` (bare) → `lead` (space `lead`, state `done`) → `worker` (space `worker`, state
`working`):

```
live-gc spaces: ['lead']
       refused: [('worker', "... worker is still recorded as working under .../wt/worker ...")]
lead dir: False        <- deleted
worker dir: True
```

`lead`'s worktree is destroyed while its subtree is still live. Bounded damage — the
checkout was clean and committed or the inventory gate would have refused, and
`_finish`'s `git branch -d` leaves an unmerged branch standing — but it is a deletion
`sb cleanup` would have refused, under a command whose stated contract is that it refuses
whatever cleanup refuses. At minimum the claim in the commit message is wrong; at most the
cascade wants the same `live_descendants` check.

---

## F3 — Positive result: recursion, double-close and claim handling are clean

Checked and found sound. Stating it because it was the primary thing the lens was pointed at.

- **No re-entry into `_close_bare`.** Only the bare route cascades. `_close_empty_spaces`
  skips any row whose workspace has `checkout IS NULL` (4661), which is exactly what bare
  means, so a nested bare space can never re-cascade. Every forked space has a checkout and
  therefore takes `_close_checkout` or `_close_gone`, neither of which cascades. The cascade
  is depth-1 per invocation regardless of how deep the agent tree is.
- **Deep trees are still reached, and terminate.** `_descendants` is transitive, so
  grandchild spaces are candidates of the top-level cascade rather than of a nested one.
  Verified: `main-2` → `lead` → `worker` closes `['lead', 'worker']` in one pass.
  (`_descendants` has no cycle guard, but a `parent` cycle would already hang `_leaves_up`
  and `sb cleanup` — pre-existing, not this change.)
- **No double-close.** Two dedup sets: `_forked_under`'s `seen` on row name (1929–1933)
  and `_close_empty_spaces`'s `seen` on workspace name (4652–4656).
- **No claim collision, no dangling mark.** `_close_bare` holds `name`'s mark only across
  `_stop_panes`, releasing on `BaseException` (1897–1902); `retire_workspace` clears it at
  1903, *before* the cascade — so no mark is held across the nested closes and the nested
  closes claim only their own names. Each nested `_close_checkout`/`_close_gone` releases
  its own mark on `except BaseException`. A stale mark on a child from an earlier crash is
  refused by `_take_over` (no auto-steal, `resume=False`) and recorded as kept.
- **Concurrency at the boundary.** A second `sb workspace close <bare>` arriving mid-cascade
  hits the `already` early return; a concurrent `sb cleanup` racing for the same child loses
  the `claim_retiring` conditional write and gets a ValueError recorded as "kept". Both safe.
- **TOCTOU between `_space_ready` and the close.** Every gate `_space_ready` runs read-only
  is re-run inside `workspace_close` before anything is destroyed, so a child that starts
  work in that window is refused. The residual window is gate → `_claim` inside
  `_close_checkout`, which is pre-existing to the command and identical when a human types it.

---

## F4 — LOW, CONFIRMED. The cascade is looser than the automatic sweep on unpushed code

`sweep`'s policy is `live agent > dirty tree > unpushed code > too young > delete`
(`_sweepable`). `_space_ready` (4700) has no unpushed and no age check — it runs
`_records_gate`, `_filed_gate`, `_inventory_gate(confirm=False)`, `_gate` and nothing else.

So `sb workspace close <bare-top>` deletes child worktrees that the half-hourly sweep
deliberately holds. Not data loss: the commits are on the branch and `_finish` uses
`git branch -d`, which refuses an unmerged branch, so the branch stays. It is a worktree
gone earlier than the sweep's own policy would allow, on a human-typed command. Same as
`sb cleanup`'s space half (literally the same function), so this is a delta from `sweep`,
not from `cleanup`.

Answering the brief directly: the "clean idle space" definition **is** `sb cleanup`'s —
same `_close_empty_spaces`, same `_space_ready`, `confirm=False` throughout, so ignored
content and git-visible work both hold the space. It is not looser than cleanup on
content; it is looser than cleanup on *liveness* (F2) and looser than sweep on *policy*
(here).

---

## F5 — LOW. A nested bare space in the subtree is skipped and never retired

Consequence of the (correct) `checkout IS NULL` skip. A descendant that itself holds a bare
space keeps its workspace row registered forever, even though the cascade correctly reaches
and closes the spaces *its* children forked. Verified:

```
nested-bare spaces: ['w2']
w2 dir: False    sub retired: None
```

One row, no worktree, nothing destroyed — cosmetic accumulation, but it is the same class
of leftover the feature was written to stop.

---

## F6 — PLAUSIBLE, exotic, pre-existing. Two workspace names over one checkout

`workspace list` exists partly to show that shape. If two namesake descendants record the
same checkout path, the first close removes the directory; the second then sees
`CHECKOUT_ABSENT`, takes `_close_gone`, and deletes *its own* branch and row without the
inventory gate ever having run against that directory under its name. Not introduced here —
`sb cleanup` has the same shape — and I did not reproduce it.

---

## Not in scope, not examined

Candidate-set selection (`_forked_under`'s namesake test) — reviewer-28's lens. CLI output
and JSON shape. Whether the feature is wanted at all.
