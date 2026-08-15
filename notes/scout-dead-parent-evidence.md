# Dead parent with live children — how often, and why

Task: `task-evidence.md` (scout, read-only). No code touched, nothing spawned that writes.

`notes/dead-parent-live-children-brief.md` does not exist anywhere — not in this
worktree, not on any local or remote branch (`git log --all -- '**/dead-parent-live-children-brief.md'`
returns nothing), not as an uncommitted file in any sibling worktree under
`/Users/andrew/.herdr/worktrees/switchboard`. I did not block on this: the task
description plus the two files that do exist on `board-ghost-sessions`
(`qa-ghost-repro-isolated.md`, `researcher-ghost-fix-shape.md`) were enough to work from.
Worth flagging to whoever wrote the task in case the brief was meant to be committed and
wasn't.

## 0. Store and method

Live store: `/Users/andrew/Code/switchboard/.git/agentflow/state.db` (shared across every
worktree of this repo — `store.repo_root()`). Opened only via
`switchboard.store.connect(readonly=True)` (the dedicated read-only path,
`store.py:402`, which never reconciles or writes the schema) or a raw
`sqlite3.connect('file:...?mode=ro', uri=True)`. `Herdr.list_agents()` was called once,
read-only (it is a query, not a mutation), to get the CURRENT global live-agent list.
No `sb` command was run. No file outside `notes/scout-dead-parent-evidence.md` was
written.

Covers **463 agent rows**, spanning **created_at 1786148869 → 1786830937 (≈7.9 days)** of
real fleet activity — this is the entire recorded history in this store, not a sample.

## 1. Right now: zero cases

Cross-referencing the store against `Herdr.list_agents()` live right now (9 agents alive,
globally, across every fleet on the machine), with the session_id-disagreement guard from
`researcher-ghost-fix-shape.md` applied by hand (so a name-collision with an unrelated
fleet's agent doesn't get counted as "alive"): **0 dead/archived parent rows have a live
descendant at this moment.**

I also checked the invariant the code itself claims (`Broker.live_descendants`,
`broker.py:4031`: *"an agent whose pane is closed has no descendant whose pane is still
working"*) directly against store state alone — dead-state (`done`/`failed`) parent with
any descendant still `working`/`blocked` in the store: also **0**, for the whole store,
not just now. This matches the code: `cleanup` computes `live_descendants` from store
state and explicitly refuses to close a parent while a descendant is `working`/`blocked`
(`broker.py:3876-3884`), and — importantly — that refusal fires **even under `--force`**,
because the `held` check runs before the `if not force` branch. Force-closing a parent
while a descendant is genuinely mid-task, through `sb cleanup`, is not possible in this
codebase as it stands. (`cleanup_forced_live`, 11 events, is a different thing — forcing
closed an agent that is itself still `working`, not one with live descendants; none of
those 11 agents have any children.)

So the store-level invariant holds by construction, always. The board bug this task is
downstream of is real (proven live in `qa-ghost-repro-isolated.md`), but it needs a
name-collision with an unrelated fleet — it is not evidence of the store's own parent/child
bookkeeping going wrong.

## 2. Historical evidence — did it ever actually happen here?

The store doesn't keep a history of herdr's live/dead readings, so "was agent X's pane
open at time T" can't be reconstructed directly. What it does keep, durably: each row's
own `ended_at`, and the full `events` log (`gone`, `revived`, `done`,
`done_with_live_children`, `cleanup_forced_live`, `cleanup_refused`, …).

**Best proxy: for every dead-state parent that has children, does any descendant's
`ended_at` fall after (or is still NULL relative to) the parent's own `ended_at`?** That's
the literal condition for "this parent finished before this descendant did" — the
necessary condition for the parent to have shown archived on a board while the child was
still drawn live, at some point.

- Rows that are parents (≥1 child): **55**
- Of those, dead-state (`done`/`failed`): **53**
- Of those, with a descendant whose `ended_at` came after the parent's own: **3**

That's **3 / 53 ≈ 5.7%** of dead parents-with-children, over the whole recorded history.
Genuinely rare, matching what Andrew expected.

### The 3 cases, individually

**`plugin-redesign`** (gap ≈ 9 seconds) — noise, not a real incident. `gone` fired 5
seconds into its own spawn (`events` id 50, `created_at=1786150896`, `delegate` for it
logged 5s later at id 52) and `revived` 17 seconds after that. This is the exact
spawn-window gap `researcher-ghost-fix-shape.md` §1 names as the one case its proposed
`session_id` fix can't close — a row reaped before it has a stored `session_id` yet,
self-correcting in seconds. Its own final `ended_at` lands essentially simultaneously with
its last child (`land-rebase`, 9s later) — a completion race in a landing sequence, not an
hours-long dead-board-row.

**`main-10`** (gap ≈ 20.4 hours) — real, and matches
`qa-ghost-evidence-live.md §5`'s live-reproduced case exactly (top-level orchestrator,
child `worker-9`). Only one event on `main-10` ever: `gone` at `1786734258`
(`{"state": "failed", "told": null}`) — no `done` event, ever. This parent was **confirmed
absent by the reap/debounce path**, not self-reported: it stopped appearing in `agent
list` and was never seen again. Its child `worker-9` kept working until `1786807713` —
over 20 hours of genuine further work by a live agent, underneath a parent already marked
`failed`.
→ **Cause: parent crashed / was reaped / confirmed gone**, child had genuinely
unfinished work.

**`suggestions-plugin`** (gap ≈ 3.5 hours) — real, different mechanism. Both ends here are
ordinary: `suggestions-plugin` self-reported `done` three times (revived twice by
follow-ups in between, finally settling `done` at `1786814862`); its child `worker-46` had
*already* self-reported `done` earlier, at `1786814629` — 233 seconds before its parent's
final `done`. So by the store's own "live" definition (state, not pane), nothing was
live-with-a-live-parent-dead at that moment, and no `done_with_live_children` event fired
for this pair (checked directly). What actually happened: `worker-46`'s **pane sat open
for another 3.5 hours** after it reported done, until a `cleanup --forced` closed it at
`1786827627`. Herdr would have kept listing `worker-46` as alive that whole window, purely
because nobody had run cleanup on it yet — while `suggestions-plugin` (the parent) had
already been fully closed and archived.
→ **Cause: pending-cleanup lag on an already-finished child**, not a bug and not ongoing
work — a `done` agent's pane stays open until someone runs `sb cleanup`, and if the
parent's cleanup happens first, the child looks "alive" on herdr for however long the gap
is.

### The one `done_with_live_children` event

`done_with_live_children` (the code's own explicit log line for "parent called `sb done`
while children were genuinely still `working` in the store", `broker.py:3727`) fired
exactly **once** in the whole history: `main-7`, at `1786457901`, naming
`tell-modes,phase4-removals,finalise-stack` — all three finished roughly 8.9 hours later
(`1786489926-27`). This is a real instance of cause 1 from the task ("parent called `sb
done` with children still running"). But it does **not** show up as a board incident:
`main-7` was `revived` 16 seconds later (a follow-up turn started), and `sb done` never
closes the caller's own pane (`broker.py:3712-3661` — the whole point of not reporting
`idle` to herdr is to keep the name addressable). So `main-7`'s pane stayed open
throughout; herdr never saw it as gone, so it was never `archived` on a board in that
window. `main-7` was eventually reaped for real, hours after its children had long since
finished (`gone` at `1786734177`, vs. children's `ended_at` at `1786489927`) — outside the
window this section is about.

## 3. Counts per cause

Of the dead-parent-with-live-descendant instances the schema can actually evidence:

| Cause | Count | Notes |
|---|---|---|
| Parent crashed / reaped / confirmed gone, child had real ongoing work | **1** (`main-10`) | The only mechanism that produced a multi-hour, board-visible incident from real unfinished work |
| Child self-reported done but its pane wasn't cleaned up yet | **1** (`suggestions-plugin`) | Both sides already "done" in the store's own sense; purely a cleanup-ordering lag |
| Spawn-race false reap, self-corrected in seconds | **1** (`plugin-redesign`) | Not a real incident — same mechanism `researcher-ghost-fix-shape.md` already names as the fix's known residual gap |
| Parent called `sb done` with children still running | **1 logged, 0 board-visible** (`main-7`) | Legal per the code's own design; doesn't produce an archived row because `sb done` never closes the caller's pane |
| Parent force-closed via `cleanup --force` while a descendant was live | **0** | Structurally prevented — the `live_descendants` gate in `Broker.cleanup` fires before the `force` branch, for named closes and sweeps alike |
| Name-collision with an unrelated fleet's agent (the ghost bug) | **0 in this data** | Real and separately reproduced (`qa-ghost-repro-isolated.md`), but it needs a same-named live agent in an *unrelated* store — nothing in this store's own parent/child pairs shows it, because it isn't a parent/child relationship at all |

## 4. What dominates

Two genuine multi-hour incidents in 7.9 days across 53 dead parents-with-children (~5.7%
of them, and a much smaller fraction of all 463 rows). Both are **legitimate timing**, not
malfunction: either the parent is confirmed gone (crash/reap) while a child is doing real
further work (`main-10`), or the child finished first but its pane just hasn't been
cleaned up yet (`suggestions-plugin`). Neither involves `cleanup` violating its own
invariant — that gate holds, always, even under `--force`. The `sb done`-with-live-children
path is legal and does get exercised, but it doesn't reach the board because `sb done`
never closes the reporting agent's own pane.

So: **it is rare, exactly as expected, and the two real cases found are both "the child
legitimately outlived it"** — one from real unfinished work under a reaped/crashed
parent, one from an ordinary cleanup-ordering lag on an already-finished child. Nothing
here points to force-closes or a cleanup-gate bug as a cause.
