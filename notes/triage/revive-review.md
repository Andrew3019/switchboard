# Review — the `_revive` block gate and the `done()` repeat guard

Commits reviewed: `79d31f0` (gate) and `8db0f30` (done guard), on branch `revive-gate`.
Read-only: no source file changed, nothing committed but this file.

**Verdict: ships.** Both bugs are fixed for a hooked session, the docstring's behaviour
survives, and the fail-open paths are real and are pinned by tests. Nothing here blocks it.
One thing is over-claimed rather than wrong, and it is the first finding below.

## How I checked

- Read `_revive`, `_turn_passed_since`, `whoami`, `done`, `block`, `cleanup`, `restore`,
  `_unblock_if_needed` in `switchboard/broker.py`; `mark_turn`, `stop_gate`, `run` in
  `switchboard/hooks.py`; `set_state`, `set_turn`, `log_event`, `_repair_unhooked_turn`
  and the schema in `switchboard/store.py`.
- Full suite in the worktree: `/Users/andrew/anaconda3/bin/python -m pytest tests` →
  **1236 passed**.
- Live probes in a scratch `git clone` of this branch, driving `Broker`/`hooks` directly
  against a temp store (`probe.py`, `probe2.py` in the clone; both torn down). Cases A–F
  below.
- Mutation checks in the clone, to see whether the tests can actually fail: neutered the
  gate (`return True`), inverted it (`return False`), and removed the `done` guard
  (`if False:`). Results under "Are the tests worth their weight".

## The five questions

### 1. Does the fix preserve the docstring's behaviour? Yes.

A human typing into a stopped agent's pane still clears the block. Proven live (probe E):
with hooks live, `sb block` → `turn_end` (Stop) → `turn_start` (typed answer) → the agent's
next command revives the row to `working` and logs `unblocked reason=answered_in_pane`.
`test_a_human_answering_in_the_pane_still_clears_the_block_with_hooks_live` pins it, and it
fails if the gate is inverted.

### 2. Does the gate hold? Yes for the reproduced shape; one narrow false-refusal class.

Probe E, first line: with hooks live, `sb block "which branch?"` followed by another `sb`
command in the same turn leaves the row `blocked`, writes no `unblocked` event, and leaves
the question on the board. That is the wild shape (`sb block` then `sb plugin report-bug
file`).

Orderings I attacked and found sound:

- The `blocked` event is written inside the tool call, so no `Stop` can interleave before
  it; ids are a single autoincrement sequence, so `last_end > anchor` is a safe ordering.
- Only `hooks.mark_turn` writes `turn_start`/`turn_end`, and only it writes
  `payload.target` for those kinds, so nothing else can be mistaken for the edge.
- A gate-blocked stop writes no `turn_end` (`hooks.run` marks idle only when it lets the
  turn end), so an agent nudged by the stop gate and then blocking cannot slip through.
- Block → answer → block again inside one turn stays blocked afterwards (probe F): the
  anchor is the *latest* `blocked` event, not the first.
- `sb done` then `sb block` in one turn leaves `ended_at` set, so `_revive` takes the
  `ended_at` branch and the `blocked` branch is never evaluated. The next genuine boundary
  then clears both via `revived` rather than `unblocked`. Cosmetic, inside the residual
  hole already documented.

The false-refusal class is finding 2 below.

### 3. Does it fail open where it must? Yes — and it is pinned.

- **No hooks**: probe2 — an agent with no `turn_*` history blocks and revives itself on the
  next command exactly as before the change. (So both bugs remain, deliberately, for an
  unhooked session; see finding 1.)
- **No anchor**: `anchor is None → True`. This is also what saves the one real path that
  could otherwise eat a report — see question 4.
- **Query error**: `sqlite3.OperationalError` → `True`, which covers a store with no
  `events` table and a sqlite without JSON1. Read, not run. Other sqlite errors propagate,
  but the pre-change code wrote to the same connection on the same paths, so that is not a
  regression.

Mutation check: forcing the gate closed fails four tests, three of them pre-existing
fail-open tests — `test_a_finished_agent_is_still_itself`,
`test_answering_in_the_pane_clears_the_block_and_releases_its_mail`,
`test_reviving_a_hookless_agent_does_not_manufacture_a_turn_it_cannot_close`. The no-hooks
case cannot silently close in future without the suite saying so.

### 4. The `done()` guard. Correct where it is reachable; cannot eat a first report.

Probe B: hooked, two `sb done` in one turn → one `[done]` message, one herdr prompt, one
`done` event plus one `done_repeated`, board keeps the first summary. Probe C: hooked, a
genuine second `done` after a real turn boundary → both reports delivered, `done_repeat`
false. That is the distinction the design asked for.

I traced every writer of `state='done'` looking for a state where the guard eats a genuine
first report:

- `done()` itself — by definition a repeat.
- `cleanup()` (`broker.py:3914`), including the `cleanup_forced_unconfirmed` path, which
  the code itself says may leave a live pane behind. Such an agent calling `sb done` for
  the first time has **no** `done` event to anchor on, so `_turn_passed_since` fails open,
  `_revive` restores it to `working`, and the report goes through. Read, not run.
- `restore()` writes `state='working', ended_at=NULL, turn=NULL`, so a restored agent is
  never in the guard's state.

The repeating agent is told clearly: `cli.py` replaces the note with "already reported …
Nothing to redo" on exit 0.

### 5. Are the 3 tests worth their weight? Two are; the third pins less than it looks.

Every one of them fails against a mutation of the thing it claims to pin — gate neutered
kills test 1, gate inverted kills test 2, guard removed kills test 3 — and tests 1 and 2
call the real `hooks.mark_turn` rather than imitating the edge, which is the right call.

Test 3 (`test_a_repeat_done_is_recorded_and_neither_mails_nor_rings_the_parent_again`)
passes `me="kid"` to both `done()` calls, so it never goes through `whoami`/`_revive`. It
therefore pins the guard's *body* but not the composition that decides whether the guard is
reachable at all — and that composition is where the behaviour actually varies (finding 1).
It survives the gate being neutered entirely.

I am not asking for more tests. What is unproven by tests, stated plainly: the `ended_at`
branch of the gate has no hooked-session test of its own (probe B covers it live), and no
test covers a session whose hooks stop firing (finding 2).

## Findings, worst first

### 1. (medium) The `done()` guard is not independent of the gate — bug 4 is unfixed wherever the gate fails open

Proven live, probe A: **no hooks**, two `sb done` in one turn, resolved through `whoami` the
way production does.

    orch mailbox : ['[done] counted 144, the parser is fine', '[done] as I said']
    kid events   : ['done', 'revived', 'done']
    herdr prompts: two child-done pokes

Both reports mailed, the parent rung twice, and the board takes the second summary — the
exact defect bug 4 describes. The guard triggers on `state == "done"` at entry, and that
state is only reachable because `_revive` declined to revive; when `_turn_passed_since`
fails open, `_revive` flips the row to `working` first and the guard never sees it. The
scout asked for a guard that stood on its own ("independent of §2", `revive-scout.md` §3),
and `8db0f30`'s message says "done() now guards on entry" without qualification.

This is *consistent* with the fail-open principle and every `sb`-spawned session is hooked
(`herdr.py:573` adds `--settings` on every spawn and restore), so the real-world exposure is
small. It is the claim, not the behaviour, that is wrong. Two ways to settle it: say the
limit out loud in `done()`'s docstring, or anchor the guard on "a `done` event exists with
no `turn_end` after it" — the same fact the gate already computes — instead of on the state
column.

### 2. (low) `hooked` is sticky: an agent that ever had a turn edge can never fail open again

`hooked = bool(edges) or turn IS NOT NULL`, where `edges` is every `turn_*` event that agent
ever produced. So the fail-open case is "never had hooks", not "has no hooks now". Probe D:
an agent with old turn edges whose session no longer fires hooks blocks, and then stays
`blocked` through three later turns — the human typing in the pane can never clear it. The
only way out is `sb tell`, which routes through `_unblock_if_needed` and is untouched by
this change.

Reachable when `hooks.stop_hook_args()` returns `[]` on a restore (it swallows a settings
file it cannot write), or when a human resumes the session by hand without `--settings`.
Narrow and recoverable, but `_turn_passed_since`'s docstring — "a session carrying no hooks
has no `turn_*` events for this agent EVER" — reads as if this case did not exist.

### 3. (nit) The docstring names a function that does not exist

`broker.py:707` cites `store._repair_turn_without_hooks`. The function is
`store._repair_unhooked_turn` (`store.py:711`). It is load-bearing prose — it is the reason
the query matches on `payload.target` rather than `events.agent` — so the wrong name costs
the next reader a grep.

### 4. (nit) The edges query is a full table scan, on every `sb` command from a done or blocked row

`SELECT kind, MAX(id) … WHERE kind IN ('turn_start','turn_end') AND
json_extract(payload,'$.target')=?` has no usable index (`events` is indexed on
`(agent, id)` only, and these rows have `agent IS NULL`). `EXPLAIN QUERY PLAN` says
`SCAN events`; measured against the live store (`.git/agentflow/state.db`, 28,387 events)
it costs **5.4 ms per call** and grows with the log. Adding `AND id > <anchor>` and asking
only whether a row exists would bound it, with the hooked test done separately.

### 5. (nit) A repeat `done` drops the live-children note

`cli.py` overwrites `note` wholesale, so an agent repeating `done` with children still
running is no longer told they are running. Harmless, and arguably right, but it is a
behaviour change that fell out of the edit rather than a decision.

## Not reported, per the task

The doorbell/`sb tell`-started turn clearing a block with nobody having answered; the
absence of an end-to-end run against a real spawned Claude agent; `sb cleanup` refusing a
revived child.

## What I did not check

Anything outside `_revive`, `_turn_passed_since`, `done()` and the `done` path in `cli.py` —
in particular the two other leads' ranges in `broker.py`, and `status.py`. I did not run a
real spawned agent; every live result above is `Broker` + `hooks` driven directly against a
temp store in a clone.
