# The other two closes

Finishes `notes/close-resolved-by-terminal-id.md`, whose "not touched" section names
exactly these two: `_close_workspace`'s `_stop_panes` and `_close_board`, both still
closing a pane by an untrusted `pane_id` with no identity check at all. Same hazard, same
resolution, no second mechanism. Scope: those two closes, and nothing else.

## 1. Why a second and third fix rather than one

The first fix put the resolution in `Broker._close_target(row) -> (pane, refusal)` and
wired `cleanup` to it. It did not wire the other two because they were out of that PR's
scope, and the note said so. The hazard does not care:

- **`_stop_panes`** is `sb workspace close`'s step 2. It closes a pane per row in the
  workspace, so one command is several wrong closes rather than one, and what follows it
  is the deletion of a checkout.
- **`_close_board`** closes a pane switchboard opened beside an agent. It had a guard,
  `_board_is_only_for`, but that asks the STORE whether another live agent's board is
  recorded on the same pane — a different question from "is anybody in that pane now",
  which only herdr can answer. A board pane id is handed straight back out when the pane
  closes, exactly like an agent's.

Both are now the one call:

```python
target, wrong = self._close_target(a)
if wrong is not None:
    ...refuse...
```

## 2. What each does with a refusal

| | on refusal | why that and not the other |
|---|---|---|
| `_stop_panes` | raises — the whole `workspace close` stops, nothing deleted | the step exists to confirm the panes are stopped, and a pane we may not touch is not confirmed stopped. It is the voice that step already had for a pane that would not close. |
| `_close_board` | leaves the pane, logs `board_close_refused`, drops the meta row | the agent's own close is not the board's hostage; and the record is of a pane we have just failed to prove is ours, so keeping it would have the next `_open_board` (or a `restore` under this name) believe a stranger's pane is our board. |

`--confirm` does not lift the `workspace close` refusal, for the reason `--force` does not
lift `cleanup`'s: those flags are intent, this is identity.

The refusal is not permanent. It lifts when whoever holds the recycled id goes.

**A board carries no terminal id.** Nothing records one and herdr lists agents rather than
panes, so a board goes through `_close_target`'s no-identity case: an empty pane may be
closed, an occupied one may not. That catches a board id recycled onto an AGENT's pane,
which is what herdr can be asked about. A board id recycled onto **another board** is
invisible to it — stated rather than claimed fixed.

## 3. Live before/after, in isolated clones

Two `git clone`s under the session scratchpad, each with its own store, driven by their own
`./bin/sb`. Clone B ran real top agents through the ordinary `sb start`. Clone A held rows
whose `terminal_id` was dead and whose `pane_id` was clone B's live pane — the state a
recycle produces, constructed rather than waited for, so the run is deterministic. The
non-destructive AFTER runs went first, so one spawn covered both sides.

### `_stop_panes` — `sb workspace close`

```
clone B, live:   main       pane w1GY:p1   term_6591d6dbadacfda5
clone A, row:    api-lead   pane w1GY:p1   term_deadbeefdeadbeef   state done, workspace api
```

```
=== AFTER ===
sb: cannot close 'api': api-lead's recorded pane cannot be confirmed as its own —
    pane w1GY:p1 is now main's (term_6591d6dbadacfda5), not this row's
    (term_deadbeefdeadbeef) — its own pane is gone and the id was recycled under it.
    Nothing here is confirmed stopped, so nothing is deleted

  herdr agent list  →  main still there.     clone B's agent survives, checkout intact.

=== BEFORE (34cc5d6, main) ===
closed 1 pane(s): api-lead
retired api: worktree removed

  herdr agent list  →  gone.                 clone A closed clone B's agent.
```

### `_close_board` — `sb cleanup`

Same construction one level down: clone A's `board_pane:ghost` meta row named clone B's
live agent pane, the row's own pane id being long dead.

```
=== AFTER ===
closed: ghost
  event board_close_refused: pane w1GY:p1 holds main, and there is no terminal id on
  this row to prove it is the same one — refusing rather than closing a stranger's pane

  herdr agent list  →  main still there.     and the row still closed: see the table above.

=== BEFORE (34cc5d6, main) ===
closed: ghost

  herdr agent list  →  gone.                 the board close took clone B's agent.
```

### The moved pane, which the first note left unproven

Staged for real this time, with `herdr pane move <pane> --new-workspace`. Two findings,
and the second is not what was expected:

- The move behaves as herdr documents and as `_close_target` assumes: `w1H3:p1` →
  `w1H4:p1`, `terminal_id` unchanged. The fixed `workspace close`, given a row still
  recording `w1H3:p1`, called `pane close w1H4:p1` — where herdr says the terminal is —
  and the agent went. The branch is now live-proven, not unit-only.
- The BEFORE run, given the stale id, called `pane close w1H1:p1` and **herdr closed the
  moved terminal anyway**, rc 0. So on herdr 0.8.0 a freshly-moved pane still answers to
  its old id, and the moved case is not an observable wrong close today. It is still the
  resolution that makes the recycle case safe, and the recycle case is the one that was
  reported and is proven above; do not read this fix as repairing a miss that herdr does
  not currently have.

**Teardown**: all four clone workspaces closed (`w1GY`, `w1G0`, `w1H1`, `w1H3`; the two
moved-pane workspaces went with their panes), the worktrees registered by clone A removed
by the closes themselves, both clones deleted. No `pkill`.

## 4. Tests

Four, all verified to FAIL against `34cc5d6` and pass here:

`tests/test_workspace_close.py`, new `PaneIdentityTest`:

- `test_a_recycled_pane_stops_the_close_before_anything_is_deleted` — the near-miss under
  the other verb: nothing closed, nothing deregistered, no mark left behind.
- `test_confirm_does_not_lift_it` — intent is not identity.
- `test_the_close_follows_the_terminal_id_when_the_pane_has_moved` — closes `w9:p7`, where
  herdr says the terminal is, and leaves the recorded `w9:p1` alone.

`tests/test_workspace.py`, in `ClosingTakesTheBoardWithItTest`:

- `test_a_board_pane_an_agent_now_holds_is_not_closed` — and the meta row still goes.

Each uses the fake herdr's existing `live` dict; the fake grew nothing.
Whole suite: `1281 passed` (`/Users/andrew/anaconda3/bin/python -m pytest tests`).

## 5. Still not touched

- **`release_agent`** still passes `a["name"]` as `--agent <LABEL>` on both paths.
  Unchanged for the first note's reason: the pane id is the target and the label rides
  along, so it cannot select a stranger. It is now the RESOLVED pane id on all three
  paths.
- **A board pane recycled onto another board**, per §2. herdr lists agents; nothing asks
  it about a plain pane's occupant, and inventing that question was outside this.
- **A workspace-close refusal has no escape hatch of its own.** `--confirm` deliberately
  does not lift it and there is no `--force` on this verb, so a workspace whose row names
  a stranger's pane waits for that stranger to go. That is the fail-closed side of the
  same mandate: a refusal costs a retry, a wrong close costs a checkout.
