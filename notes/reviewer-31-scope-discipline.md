# reviewer-31 — adversarial review, lens: scope discipline / regression to the SHARED
# cleanup + sweep machinery that the cascade-close fix reuses

Artifact: `8494b3f`, `30c1e62`, `5e060f3`, `227c3c3`, `bae8691` on
`fix-orphaned-dispatcher-children`, read at HEAD (`bae8691`). The branch's hooks/plans/
presets/block-gate work is ignored throughout — it is not part of this feature.

## Verdict

**Good to go on this lens.** No regression to `sb cleanup` or the half-hourly `sb board`
sweep. Everything they return, print, serialise and do is byte-identical to `main` in a
differential run (below). Three notes follow; none is a defect in what ships.

## What the feature actually touched in shared code

Hunk headers, per commit (`git show <c> -- switchboard/broker.py switchboard/cli.py |
grep '^@@'`). Only three shared sites are touched at all:

| site | commit | change |
|---|---|---|
| `CleanupResult` (broker.py:475, :493) | `bae8691` | new `panes` kwarg + attribute, last in the signature |
| `_closed` (broker.py:2164) | `8494b3f`, `227c3c3` | two new dict keys, `spaces` / `spaces_refused` |
| `_close_empty_spaces` (broker.py:4670, :4703) | `bae8691` | new `named` kwarg (default `False`); nested close's `["closed"]` kept |

Everything else in the five commits lives in `_close_bare`, `_cascade`, `_forked_under`
(broker.py:1877–2010) and the `workspace close` emitter in cli.py — routes nothing else
reaches. **Not touched by any of the five commits:** `_close_checkout`, `_close_gone`,
`_gate`, `_records_gate`, `_filed_gate`, `_space_ready`, `_my_spaces`, `_inventory`,
`live_descendants`, `sweep`, `_sweepable`, `cleanup`'s body above its
`_close_empty_spaces` call, and the whole `cleanup` emitter in cli.py (its `--json`
literal at cli.py:1161-1167 sits outside every hunk).

## The one structural claim, and why the cascade cannot leak into cleanup or the sweep

`_cascade` runs only from `_close_bare`, and `workspace_close` reaches `_close_bare`
only when `row["checkout"] is None` (broker.py:1832-1835).

- `_close_empty_spaces` skips exactly that row before it can nest-close anything:
  `if row is None or row["retired_at"] or row["checkout"] is None: continue`
  (broker.py:4735-4737). So `cleanup`'s nested `workspace_close` can never land on the
  bare route, and never cascades.
- `sweep` skips it one level earlier: `if w["verdict"] != store.CHECKOUT_OK: continue
  # bare, retired, already gone, unreadable` (broker.py:4886-4887).

Both proven live, not just read — see probe 3 and probe 2 below.

## Live differential proof

Method: one probe script per scenario, importing the real `CloseHarness` (real git, faked
process scan), run twice with `sys.path` pointed at (a) a fresh `git clone` of this repo
checked out at `main` (`b9466d1`) and (b) this checkout at HEAD, then `diff`ed. Scripts
are in the session scratchpad (`probe.py`, `probe2.py`, `probe3.py`); each prints a JSON
transcript.

1. **probe.py** — a bare dispatcher `main-2` with a finished child `worker` that forked
   its own space; `b.cleanup(me=HUMAN)`, a caller-owned-space cleanup
   (`me="api-lead"` standing in `api`), and `b.sweep()`.
   Output identical except one line: `vars(r)` on the `CleanupResult` gains `"panes"`.
   `closed`, `refused`, `expected`, `spaces`, `spaces_refused`, which directories
   survived, which panes came down — all identical. The caller-owned skip is still
   **silent** (`own.spaces_refused == []`) on both.
2. **probe2.py** — a sweep that actually DELETES: `worker`'s space aged past the floor,
   with the bare `main-2` workspace present in the same fleet. `swept == ["worker"]`,
   `held == []`, `looked == 1` (the bare workspace not even looked at), `main-2` NOT
   retired, worktree gone. Identical on both. Also compares `cleanup`'s exact `--json`
   payload: identical.
3. **probe3.py** — `cleanup` closing the bare dispatcher's OWN row, with a child space
   below it. Identical on both, down to the full ordered `events.kind` stream:
   `closed == ["main-2","worker"]`, `spaces == ["worker"]`, `bare_retired == false`.
   This is the direct disproof of "cleanup now cascades".

Suite: `/Users/andrew/anaconda3/bin/python -m pytest tests` → **1530 passed** (154.91s).

## Notes (none blocking)

### 1. `CleanupResult.panes` is filled on the cleanup path and read by nobody — dead data with a double-count trap in it. PLAUSIBLE (latent, not a live defect)

broker.py:4749, `closed.panes.extend(self.workspace_close(name, me=me)["closed"])`, runs
on BOTH callers, not only the cascade. On a `cleanup` those same agent names are already
in the `CleanupResult`'s own list (cleanup closed them itself, broker.py:4613), so `panes`
holds a duplicate of names already reported. Harmless today: nothing reads it — cli.py's
cleanup `--json` is an explicit five-key literal (cli.py:1161-1167) and its text emitter
never touches it, both verified identical in probe 1 and 2. The class docstring
(broker.py:478-481) says as much: "`cleanup` closes those agents itself and so never reads
it". The trap is for the next person: a future emitter that prints `closed + panes` for
cleanup double-counts, and the field looks safe to print because it is on the shared class.
A `named`-style guard, or filling it only for the cascade, would remove the trap. Not a
change I would ask for now.

### 2. Only one of `_close_empty_spaces`'s two silent skips is pinned by a test. CONFIRMED (coverage, not behaviour)

The `named` default is guarded: `tests/test_workspace_close.py:1140`
(`test_the_space_the_caller_is_standing_in_is_never_swept`) asserts
`r.spaces_refused == []` for the **`my_names`** branch, and flipping the default to `True`
would fail it. The **second** silent skip — `any(live.is_under(d, row["checkout"]) ...)`
at broker.py:4741, the caller's own directory under a different workspace name — has no
cleanup-side test asserting its silence; the only test of that branch is the cascade's
(`tests/test_workspace_close.py:826`, which asserts it *does* speak, `named=True`). So one
of the two silences is a default away from being unpinned. Probe 1 covers it live today.

### 3. `named=True` records a `my_names` refusal without marking the workspace seen. PLAUSIBLE (unreachable today, cascade-only)

broker.py:4722-4728: the `w in my_names` branch appends to `spaces_refused` and `continue`s
without `seen.append(w)`, so two candidate rows sharing that workspace would produce two
identical "the workspace you are working in" lines. Unreachable from `_cascade`, whose
`_forked_under` returns one row per namesake workspace (broker.py:2011-2019), and
unreachable from `cleanup`, where `named` is `False`. Cosmetic, cascade-only, and outside
this lens except that it lives in the shared function.

## Also checked, clean

- `CleanupResult.panes` is initialised on every construction path: the `None`-default in
  `__init__` (broker.py:504); the only two constructions are `CleanupResult()` at
  broker.py:4289 (`cleanup`) and :1954 (`_cascade`), both no-arg. New kwarg is last, so no
  positional caller could shift.
- `_closed` always returns `spaces`/`spaces_refused`, on all three routes and the `already`
  route (broker.py:2180-2182), so `sb workspace close --json` gains two always-present
  empty keys on the non-bare routes. Additive; the only consumer is cli.py:1204, and
  `_workspace_closed`'s unconditional `r["spaces_refused"]` read (cli.py:1354) is safe
  because of it.
- `closed.panes.extend(... ["closed"])` cannot `KeyError`: every `workspace_close` return
  goes through `_closed`, which always sets the key (broker.py:1828, :1835, :1838, :1845).
- Reentrancy: the cascade holds the parent's `retiring` mark for the whole nested run
  (`_claim` at broker.py:1915, `retire_workspace` moved to last by `5e060f3`). A concurrent
  `cleanup`/sweep meeting a marked row is refused by `_claim`/`_take_over` with a
  `ValueError`, which `_close_empty_spaces` (broker.py:4750) and `sweep`
  (broker.py:4899-4900) both already catch and record as a held space. Marks are never
  stolen without `--resume`. No new failure mode; the window is longer than before.
- `workspace_retired` event payload gained the cascade's panes on the bare route only
  (broker.py:1925). Nothing reads that event — no consumer anywhere in `switchboard/` or
  `tests/`.
- No DESIGN-TRUTH drift found on this lens: its cleanup/sweep entries (lines ~489-535,
  595-601) describe the gates and the sweep policy, both untouched.

## Not checked

- The cascade's own correctness (`_forked_under`'s set, the live-descendants gate,
  recursion depth) and its wording — other reviewers' lenses, excluded by the brief.
- No live `sb` fleet run: the differential probes drive the real broker against the test
  harness's real git and fake process scan, which is what makes main-vs-HEAD comparable.
  A real-tmux cascade is qa-15's proof (`notes/`), not re-run here.
