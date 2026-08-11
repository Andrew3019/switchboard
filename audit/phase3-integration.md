# Phase 3 integration — the merge, and the one live cross-check of the merged branch

Branch `phase3-messaging`, cut from `main` at `5998a43`. It merges the five build branches
that carried phase 3's eight items, plus the two documentation branches that are their
evidence trail. This file records what the merge had to decide, and the one live run that
put the pieces in a fleet together — which none of them had ever been.

## What was merged, and in what order

| merged | carries |
|---|---|
| `scope-3.7`, `probe-delivery-primitive` | `audit/phase3.7-scope.md`, `audit/phase3-delivery-primitive.md` — documentation only |
| `phase3-tell-modes` (on top of `phase3.5a-needs-reply`) | 3.1 delivery modes, 3.3 sender tag, 3.2 `sb interrupt` deleted, 3.6 `sb ask` removed, 3.5a `--needs-reply` |
| `phase3.5-reconciler` (on top of `phase3.7-collector-staleness`) | 3.5 the reconciler, 3.7 the collector noticing its own source changed |
| `phase3.8-stop-hook` | 3.8 the Stop hook |

`scope-phase4` was deliberately left out; it belongs to the next phase's PR.

## The three conflicts, and how each was resolved

1. **`defaults/prompts.toml`** — both sides appended a new prompt at the same place: 3.5a's
   `needs_reply` and the reconciler's `stalled`. Kept both, in that order. Neither touches
   the other's text.
2. **`tests/test_status.py`** — the one test that asserts the exact set of verbs. Tell-modes
   removed `interrupt` and `ask` from it; the reconciler added `reconcile`. The merged list
   is tell-modes' list plus `reconcile`, which is what `build_parser()` now offers.
3. **`switchboard/broker.py`** — flagged by the reconciler's author as the risky one, and it
   merged cleanly: the reconciler appended `reconcile`/`_nudge`/`_last_pings`/`_has_live_child`
   after `_surface`, and tell-modes rewrote the tell/interrupt/ask cluster several hundred
   lines above it. Read after merging rather than trusted: `reconcile` calls nothing that
   tell-modes deleted, and `_nudge` deliberately does not go through `_ring`.

One thing the merge made false that neither author could have seen: `_nudge`'s docstring
justified its busy guard with "`agent prompt` INTERLEAVES", which is exactly what
`audit/phase3-delivery-primitive.md` — merged alongside it — disproves. The guard is right
and stays; its reason was rewritten to the measured one.

## Evidence

- **Suite:** `python -m pytest tests` — **1118 passed**, no skips introduced. (The
  branches disagreed at 1108 and 1122; 1118 is the merged number.)
- **`./acceptance/accept.py phase3-messaging`** — all four checks pass, 3m20s:
  1. a cold fan-out of six starts six — 6/6 took their task and reported into 6 new
     checkouts, 0 spawns misreported
  2. a child's report wakes its parent — deferred while the parent worked, then delivered
     by the doorbell 57s later; the parent woke and read it
  3. a block holds until the human answers — held 53s against a sibling, released by the
     human's answer and read it
  4. a sweep names what it refused — closed 1, refused 1 and said why

## The live cross-check

One isolated `git clone` of this repo at `phase3-messaging`, driven through that clone's own
`./bin/sb`, three agents, torn down at the end (agents through `sb cleanup`, the workspaces
by checkout path, the clone's own collector by the pid it published). Run `sbx4m8t2`.

**A — a default `tell` to a busy agent, with the sender tag (3.1 + 3.3). PASS.**
The target was inside a single `sleep 150` tool call and herdr had it `working` both at the
moment of the tell and ten seconds after. The tell carried no mode flag, so it took the new
default. It was rung immediately — **zero `ring_deferred` events**, where the old when-idle
default would have logged one and held the ring for the rest of the turn. `delivered_at`
equals the second the tell was sent; the agent did not act on it for **44 seconds**, and
then read `[1] [sb: from human] TOLD-sbx4m8t2` and reported it. Both halves are the point:
the ring goes out while the agent is busy, and it does not cut the agent off.

**B — the Stop hook (3.8). PASS.** An agent told to run one `echo` and end its turn
without reporting was refused: `stop_gate_blocked` in the store, and the agent given
another turn.

**C — the reconciler leaves a blocked agent alone (3.5). PASS.** An agent that ran
`sb block` was still `blocked` after two explicit `sb reconcile` runs and the collector's
own periodic ones, and appears in no `reconcile_ping`. `sb status` still had it in
`needs_human`.

### What this run also showed — two rough edges, reported here and since fixed

Both are integration behaviour between 3.5 and 3.8 that no single author could have seen.
They were out of scope for the merge and are recorded below as they were observed; both
were then fixed on this branch, with their causes and live proof in
`audit/phase3-edges-fix.md`. Neither was what its symptom suggested: the first is `stalled`
being true before the agent had started, and the second is that `stop_hook_active` caps a
single stop-chain and every poke starts a new one.

1. **The reconciler pings an agent inside its spawn window.** `sbx4m8t2-busy` was sent
   `[sb] Your turn ended … without a report` **two seconds after its `delegate` event**, by
   the collector's own reconciler run — the agent's row said `working`, herdr had not yet
   seen its first turn start, and it is not `awaiting_task` because the task had been
   delivered. The nudge is false at the moment it is read. It did no visible harm here (the
   agent went on to do its task and report correctly), but it is a spurious ping in the one
   window where every fan-out puts every agent.
2. **The Stop hook blocked the same agent twice, twelve seconds apart.**
   `sbx4m8t2-silent` has two `stop_gate_blocked` events, where `stop_gate`'s docstring says
   at most one stop per stop-chain — the cap depends on `stop_hook_active` being set on the
   turn the gate itself caused. Either the flag did not arrive or these were two separate
   chains; this run cannot tell which. The agent still never reported, and the reconciler
   then pinged it, which is the designed division of labour (the hook prevents the ordinary
   case, the reconciler names the pathological one).

Also worth knowing for anyone re-running this: a first attempt at check A sent the tell
about seventy seconds after the delegate, by which time the agent had finished its sleep,
found an empty inbox and reported. It then read the tell and reported a second time. The
check was rewritten to tell the agent thirty seconds into a 150-second window and to assert
herdr's own view of the target at that moment, because "was it actually busy?" is the whole
of what check A measures.
