# Phase 4 build — the removals

Branch `phase4-removals`, based on `phase3-messaging` (`8f69642`, PR #10, unmerged), not on
`main`. Scoped by `audit/phase4-scope.md` (branch `scope-phase4`); the authority for *why*
each item goes is `DESIGN-TRUTH.md:305-327`, which was read and not edited.

Removals only. No behaviour was added, and the role prompts were not rewritten beyond
deleting the sentences that named a dead flag — phase 6 owns that rewrite.

---

## What was removed

**The flags (4.1, 4.4).** Deleted from the parser and from every signature underneath:

| flag | command | what replaced the choice |
|---|---|---|
| `--keep`, `--ephemeral` | `sb delegate` | nothing sets a disposition; the column takes its `close` default |
| `--include-kept` / `--all-idle` | `sb cleanup` | the gate stays, read-only (see below) |
| `--leave-children` | `sb cleanup` | the live-descendants gate is now absolute — nothing lifts it, `--force` included, as was already true of `--force` |
| `--no-focus` | `sb start` | `sb start` focuses unconditionally |
| `--no-board` | `sb start`, `sb workspace new` | every sb-made view is split with the board |
| `--focus` | `sb workspace new` | nothing but `sb start` focuses |

`Broker.start`, `_top`, `workspace_new`, `_spawn_lead` and `delegate` lost their `focus`
and `board` parameters with them, so there is no second way in either.

**The write-paths, not the column (4.2).** Per the brief's decision, taken because the live
store carries `cleanup='keep'` rows that were written automatically — `broker.py`'s own
`_top`, `_spawn_lead` and `_adopt` wrote it for top-level orchestrators and workspace leads
— rather than by anyone opting in. Removed: those three internal writes, `delegate`'s
`cleanup` parameter, `Role.cleanup`, `[vocabulary] default_cleanup`, and the `cleanup`
column from `store._INSERT_AGENT` and from `update_agent`'s allowlist. **Kept:** the column
itself, and its read-side gate in `Broker.cleanup`. No migration was run and no row was
rewritten.

**`sb wait` (4.3).** Parser, validation and dispatch in `cli.py`; `status.wait_for`,
`WaitResult`, `WAIT_STATES`, `WAIT_TIMEOUT`, `WAIT_SLICE_MS`, `_reached`,
`_next_transition`; and `[states] wait`, `[timeouts] wait`, `[timeouts] wait_slice_ms`.
The human inbox was confirmed already gone and its deliberate refusals were left alone.

**The prompts.** `grep -rn -- '--keep|--ephemeral|--include-kept|--all-idle|--leave-children|--no-board|--no-focus|sb wait' defaults/` returns nothing. Each of the five role files
lost the clause naming a flag and kept its paragraph.

---

## Pass / fail tests and results

### 1. The flags no longer parse — PASS

Live, in a `git clone` of this branch at `.../scratchpad/clone`, driven through that
clone's own `./bin/sb` (`sb doctor` confirmed the clone's own store at
`clone/.git/agentflow/state.db`):

```
sb delegate t --keep             -> exit 2 | unrecognized arguments: --keep
sb delegate t --ephemeral        -> exit 2 | unrecognized arguments: --ephemeral
sb cleanup --include-kept        -> exit 2 | unrecognized arguments: --include-kept
sb cleanup --all-idle            -> exit 2 | unrecognized arguments: --all-idle
sb cleanup --leave-children      -> exit 2 | unrecognized arguments: --leave-children
sb start --no-focus              -> exit 2 | unrecognized arguments: --no-focus
sb start --no-board              -> exit 2 | unrecognized arguments: --no-board
sb workspace new x --focus       -> exit 2 | unrecognized arguments: --focus
sb workspace new x --no-board    -> exit 2 | unrecognized arguments: --no-board
sb wait w1                       -> exit 2 | invalid choice: 'wait'
```

### 2. Nothing writes the retired state — PASS

Same clone, a real agent: `sb start --name p4main "..."`. It spawned, ran and reported
`done`. Its row read `cleanup='close'` — a top-level orchestrator is exactly the row that
used to be written `'keep'`.

The event log for that spawn also shows `agent focus p4main` (start still focuses, with no
flag involved) and a board pane `wKJ:p2` that was opened beside it and closed with it
(`board_close`).

### 3. A live agent carrying the OLD state still behaves correctly — PASS

The risk the scope doc named, proved rather than assumed. Same clone, same real agent: its
row was set to `cleanup='keep'` by hand — the shape a row written before this change has —
and then swept:

```
$ ./bin/sb cleanup
closed: (nothing)
  refused p4main: p4main was spawned to be kept — name it to close it

$ ./bin/sb cleanup p4main
closed: p4main
```

Held back by the sweep, closed when named: the behaviour it had before the removal, with
its pane genuinely closed (`pane close wKJ:p1`, `ended_at` set). Teardown: the agent was
closed, its herdr workspace went with its panes, the clone was deleted. No `pkill`.

### 4. The suite — PASS, 1102 passing

`/Users/andrew/anaconda3/bin/python -m pytest tests` → **1102 passed**, from 1118 on the
base. 24 test methods removed, 8 added; net −16.

Removed because they pinned behaviour that is gone:
- **19 for `sb wait`** — the whole `WaitTest` class (17), plus
  `test_wait_refuses_a_state_it_cannot_ever_see` and
  `test_wait_says_in_its_help_that_it_is_not_for_agents`. One replacement,
  `test_wait_is_gone_as_a_verb`, pins the refusal.
- **2 for `--no-board`** (`test_no_board_declines_the_split`, in two classes) — replaced by
  `test_the_board_cannot_be_declined`, which asserts the split happens.
- **`test_leave_children_is_the_one_way_to_close_over_a_live_child`** — replaced by
  `test_nothing_at_all_closes_over_a_live_child`.
- **`test_cleanup_names_the_role_that_keeps_its_agents`** — replaced by
  `test_a_row_written_before_keep_was_removed_is_still_held_by_a_sweep` (test 3 above, in
  unit form) and `test_nothing_spawned_now_is_ever_written_kept`.
- **`test_the_lead_is_never_swept_away_by_cleanup`** and the two `cleanup == "keep"`
  assertions inside `sb start`'s tests — rewritten to assert `close`.

`test_a_child_of_a_closed_parent_cannot_deliver_its_summary` was kept and renamed: the harm
it names is still worth pinning, but `cleanup` can no longer produce that state at all, so
the test now takes the parent's pane away directly. Stated plainly because it is the one
place a test no longer reaches its state by the route a user would.

### 5. Acceptance — PASS on the third run; the first two are reported here in full

`./acceptance/accept.py phase4-removals`, verbatim:

```
  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [1m06s]
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 45s later; the parent woke and read it   [2m55s]
  3  a block holds until the human answers    PASS   held 57s against a sibling, released by the human's answer and read it   [2m21s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sb5006rk4-k: blocked, not finished — it has not reported an end'   [2m17s]

all 4 pass — the fleet is sound   (3m01s)
```

Two earlier runs failed, and the reason was the machine, not the branch — recorded because
a run that failed is evidence either way:

- Run 1 (`sby5qkoj`): **4 of 4 FAILED**, every one on `task_undelivered` — the text sent
  three times and never confirmed in the agent's own record.
- A control run of the **base** branch `phase3-messaging` (`sb0eyhac`), taken immediately
  after: **2 of 4 FAILED**, on the identical `task_undelivered`. The base fails the same
  way, so the fault is not phase 4's.
- Run 2 (`sba44kxk`): 3 of 4 passed; check 1 got 5/6 with **no misreport in either
  direction**.
- Run 3 (`sb5006rk`), above: all four.

The machine was running ten herdr workspaces and at least one other agent's concurrent
acceptance run throughout runs 1 and 2. Nothing phase 4 touches is on the delivery path.

---

## What is unproven, and other things worth knowing

- **`Herdr.wait` is now unused by production code.** It is the adapter's mirror of `herdr
  agent wait`, its own tests still cover it, and the scope doc did not list it — so it was
  left. Nothing calls it.
- **A repo whose `.switchboard/roles.toml` still sets `cleanup =` will now raise** on
  `Role(**fields)`, because `Role` no longer has the field. This is exactly how any other
  unknown role field already behaves, and no shipped role and no file in this repo sets it
  — but a repo carrying a stale override gets a loud error rather than a silent ignore.
- **Not tested: two concurrent `sb cleanup` sweeps over a legacy `'keep'` row.** Test 3 is
  single-caller. Making it concurrent would have meant new scaffolding in the fake herdr,
  which is not something to grow for a removal.
- **Untouched by design:** `sb workspace new` itself (phase 5), `DESIGN-TRUTH.md`, and the
  historical docs under `audit/`, `research/`, `design/` and the root `*.md` files that
  still mention these flags as history. `acceptance/accept.py`'s own `--keep` is the
  harness's flag and is unrelated.
