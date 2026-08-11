# A finished agent stays reachable — the measurement

Phase 2, cluster around `Broker.done` (scope items **A** and **2.3**). Run from two
isolated clones on 2026-08-10, herdr 0.8.0. Live, not read from source.

## What was wrong

`Broker.done` called `_push_state(a, IDLE, summary)`. `pane report-agent` does not
annotate a pane's agent, it replaces it, so that one call evicted the name `agent start`
registered — permanently. `sb tell <name>` after a `done` could never land again. `block`
had the identical call removed in phase 1; `done` was the last one, and `herdr.py`'s
docstring recorded it as deliberate.

## Method

Two `git clone`s of this repo (own `.git` → own `state.db`, per `audit/isolated-instance.md`),
driven by each clone's own `./bin/sb`:

- `clone-base` at `19fc485` (main)
- `clone-p2` at `14fa06c` (this branch)

In each: `./bin/sb start 'Immediately run: sb done "proof agent, ignore" ...'`, wait for
the store to say `done`, then ask herdr whether the name still binds, then `sb tell` it a
follow-up.

## Result

| | main (`19fc485`) | this branch (`14fa06c`) |
|---|---|---|
| `herdr agent get <name>` after `done` | `agent_not_found` | resolves; `name` present, `agent_status: done` |
| `sb tell <name> "..."` | `sent (… UNREACHABLE — herdr no longer answers to its name and the doorbell will not ring again …)` | `sent to p2fix-proof` |
| did the agent act on it? | no — nothing to ring | yes: it woke, read the message, and reported `✓ got the follow-up` |
| root `done` notification | none in the log | `herdr notification show p2fix-proof: done — proof agent, ignore` |
| what herdr was told on `done` | `pane report-agent … --state idle` | nothing |

Both throwaway agents closed with `sb cleanup --force`; both clones deleted; neither ever
appeared in the live fleet's store.

## Two things this settles

1. **The eviction was ours, not Claude Code's.** `_finished_and_unreachable`'s docstring
   claimed "a real Claude Code process stops answering to its name the moment that turn
   ends." It does not: on this branch the process's turn ended and the name still resolved.
   The docstring was reading our own `report_state` call as a fact about the harness. It
   has been corrected in place.
2. **herdr derives `done` without being told.** The board showed `HERDR done` for an agent
   we reported nothing about — its own detector (idle + unfocused) got there unaided, which
   was the entire content of what the name binding was being spent on.

## Left unproven

- The clash between a `done` agent's row and a follow-up turn: while the agent works on the
  follow-up, the store still says `done` (herdr says working). Pre-existing — nothing sets
  the state back — and out of this cluster's scope, but now reachable in practice where
  before it was unreachable in principle.
- `_check_integration` was removed with `_push_state`, its only caller and its documented
  blast radius. `sb doctor`'s `check()` is unaffected. Not checked: whether the same
  `claude` integration conflict can also silently eat `pane report-agent-session`
  (`_claim_session`, `Broker.spawn`), which nothing now guards.
