# Scout report — telling the human apart from the agent in `Broker._revive`

Read-only investigation. No source file changed, nothing run live (this is a design
question, not a reproduction — the reproduction already exists in the evidence cited
below). Method: read `switchboard/broker.py`, `switchboard/hooks.py`, `switchboard/store.py`
(schema), `switchboard/cli.py` (`whoami` call site), and the three triage documents named
in the task.

## 1. What signals actually exist

The `agents` table (`store.py:140-`) has, relevant here: `state` (`working|blocked|done|
failed`), `ended_at`, `turn` (`store.py:71-72`, values `'working'`/`'idle'`/`NULL`), and no
per-agent turn-start/turn-end *timestamp* column — only the current value.

The two hooks (`hooks.py`) write the only two edges switchboard has of its own:

- `UserPromptSubmit` → `mark_turn(..., TURN_WORKING)`, logs event `turn_start`. Fires
  before the agent can run any tool call — i.e. **before** it can run any `sb` command —
  so by the time an `sb` command runs, `turn` already reads `'working'` whether this is a
  turn that just began or one already in progress. **The bare current value of `turn`
  cannot distinguish the two cases** — this is the trap both candidate mechanisms below
  have to avoid.
- `Stop` → only fires `mark_turn(..., TURN_IDLE)` (event `turn_end`) if `stop_gate`
  decided to let the turn end — i.e. only once the agent is in `REPORTED`
  (`done`/`blocked`/`failed`) or one of the other exemptions. Crucially: **`sb block`
  itself puts the agent in `REPORTED`**, so the very turn that called `sb block` is
  allowed to end normally, and `turn` flips to `idle` for it — *unless* the agent's own
  next command runs inside that same turn (same tool call / same message), in which case
  `Stop` never fires between them and `turn` never touches `idle`.

That is the reliable signal: **whether a `turn_end` event for this agent exists between
the `blocked` event and now.** If a genuine turn boundary passed (Stop hook fired, `turn`
went to `idle`, then a new `UserPromptSubmit` — from a human typing, a doorbell delivery,
or `sb tell` — set it back to `working`), a `turn_end` row for this agent sits in the
`events` table with an id/timestamp after the `blocked` event's. If the agent's own next
`sb` call runs in the same turn (e.g. `sb block "x" && sb plugin report-bug file ...` as
one shell line — the exact shape of the wild reproduction in
`bug-triage:notes/triage/group-5-block-status-misc.md`), no `turn_end` exists between them,
because Claude Code's `Stop` hasn't fired yet.

**Reliable:** the presence/absence of a `turn_end` event for this agent, timestamped after
the `blocked` event, whenever the hooks are installed and firing.

**Not reliable, and must not be used alone:**
- the bare `turn` column value at the moment `_revive` runs (always `'working'` in both
  the genuine and the self-revive case, per above);
- `state` alone (identical in both cases: `'blocked'` until `_revive` acts);
- session id / pane id (`whoami`'s own routing) — these identify *which* agent, not
  *when*, and are already used for that and only that;
- presence of hooks at all. A session started before the settings file existed, or one
  we did not spawn (a bare `claude` session with no `--settings`), carries **no** `turn_*`
  events ever — `_revive`'s docstring already names this case for the existing design, and
  it holds equally for anything built on `turn_end`. For such a session `turn` stays
  `NULL` forever and the `events` table has no `turn_start`/`turn_end` rows for it at all.
  This is detectable (`turn IS NULL` and no `turn_end` event ever logged for the agent) and
  must fail open to the current behaviour — immediate revive — exactly as today, per the
  file's own "fails open" principle (`hooks.py`'s closing paragraph, `_revive`'s own
  docstring).

## 2. Recommended mechanism for BUG 3

**Recommended: a variant of (b), keyed on the `turn_end` event rather than a new bespoke
stamp.** Concretely: in `_revive`'s `blocked` branch, before flipping `state` back to
`working` and logging `unblocked`, check whether a `turn_end` event for this agent exists
with an id greater than the `blocked` event's id.

- If yes (or if the agent has no `turn_start`/`turn_end` history at all — the no-hooks
  case) → today's behaviour: revive, log `unblocked reason=answered_in_pane`.
- If no, and the agent *does* have turn-event history (hooks are live for this session) →
  this is the agent's own next command inside the same turn that called `sb block`. Do not
  revive. The row stays `blocked`; the command the agent is trying to run still executes
  (whoami still needs to resolve a name) but the block is not cleared by it.

This needs no new column: it is one more `SELECT 1 FROM events WHERE agent=? AND
kind='turn_end' AND id > ? LIMIT 1` in `_revive`, keyed off the id of the `blocked` event
already being logged. It requires `whoami`'s two `SELECT`s (`broker.py:581-593`) to fetch
enough to locate the agent's `blocked` event, or an event-log lookup keyed on `agent`
+`kind='blocked'` (already indexed via `idx_events_agent`).

**Why this over (a) — revive only on ACT verbs, not read-only ones.** The partition is not
stable, and the wild reproduction proves it: the agent's next command after `sb block` was
`sb plugin report-bug file ...` — filing a bug report. That is squarely a *write*/act verb
by any reasonable partition (it creates a durable row), yet it plainly is not an answer to
the block either. `sb delegate`, `sb tell <other-agent>`, `sb plugin todo add` are all
similarly "acting" without addressing this agent's own block. The failure mode this bug
exists to fix is exactly "the agent takes SOME other action, not necessarily a read," so a
verb-side partition would have to enumerate, verb by verb, "does calling this ever
legitimately follow an unanswered block," and the honest answer for most of them is "yes,
plausibly" (tidying up, filing what it found, telling a sibling) — the same actions every
shipped prompt already tells a stopped agent's *own* turn to do before it stops, which is
precisely the case this bug is about. I could not find a stable line to draw here; I'd
enumerate on request but expect it to keep needing exceptions.

**Why (b)-as-turn-gap over a bespoke stamp-and-clear.** The original (b) framing — "`sb
block` stamps a marker; a same-turn call by the agent itself doesn't count" — is right in
spirit, and what I'm recommending is a specific, minimal instance of it: the marker is
simply "the id of the `blocked` event," already written for free, and "cleared" means "a
`turn_end` event with a later id exists" — a fact the existing activity-signal hooks
already produce for free. No new column, no new write path, and it reuses machinery
`hooks.py` already justifies at length (measured cost, fails open). A hand-rolled marker
(e.g. a boolean flag set at block time, cleared at some other point) would need its own
answer to "cleared by what, exactly" — and the honest answer is "by the same `turn_end`
event," so it collapses to the same mechanism with one extra column.

## 3. BUG 4 — where to dedupe, and whether fixing bug 3 covers it

**Two distinct defects, one shared root cause, and fixing bug 3's mechanism does not by
itself close bug 4.**

`_revive` has **two** branches (`broker.py:603-664`): the `ended_at IS NOT NULL` branch
(631-651, the one that matters for `done`) and the `blocked` branch (652-663, the one bug
3 targets). Bug 4's root cause per the live reproduction in
`bug-triage:notes/triage/group-4-lifecycle.md` is the **first** branch: a child that calls
`sb done`, then runs any further `sb` command in the same turn, gets `ended_at` cleared and
`state` flipped back to `working` — same shape as bug 3, different branch.

The turn-gap check in §2 generalizes cleanly to this branch too (same query, same
"no-hooks falls open to today's behaviour" caveat), and doing so removes the half of bug 4
that shows up as `sb cleanup` refusing a genuinely-finished child and the board briefly
reading `working` between the child's own follow-up commands. **But it does not stop the
duplicate mail.** `done()` (`broker.py:3470-3542`) has no guard at all on entry — it reads
`a = store.get_agent(...)` and then unconditionally calls `store.put_message(...)`,
`store.set_state(..., "done")`, and (for a non-root) `self._ring(parent, ...)`. Even with
`_revive` refusing to flip a same-turn row back to `working`, a second `sb done` call in
that same turn still reaches this code with `a["state"] == "done"` already, and will still
send a second `[done]` message and (for a root) call `_surface` again.

**Recommended fix, independent of §2: guard `done()` itself.** Right after `a =
store.get_agent(self.db, me)` (broker.py:3470-3506 region), branch on `a["state"] ==
"done"`:

- If the row is **already** `done` at entry — meaning `_revive` (with §2's fix) declined
  to revive it, i.e. this is the same turn as a prior `sb done` — this call is a repeat,
  not a follow-up. Recommended behaviour: **update in place, don't re-deliver.** Log a
  distinct event (e.g. `kind="done_repeated"`, carrying the new summary text) so nothing
  written is silently lost and `sb log`/`sb inspect` can still show it, but skip
  `put_message`/`_ring`/`_surface` — the parent already has the one real notification.
  Do not overwrite the event log's `done` row itself, so the *first* summary — the one the
  parent's mailbox actually saw — stays what `sb status` renders, rather than the second,
  usually content-free rewrite silently replacing it (exactly the defect QA reproduced:
  "the second, content-free report replaces the real one on the board").
- If the row is `working` at entry (the ordinary case, including a *genuine* second `done`
  after a real intervening turn — a parent's follow-up question, answered, then `done`
  again — because §2's fix would have let `_revive` restore it to `working` for that case)
  — today's full path runs unchanged: mail sent, ring fired.

**Refuse loudly vs. silent no-op vs. update-in-place:** I recommend update-in-place over
either extreme. Refusing loudly risks the same failure mode `hooks.BLOCK_REASON`'s own
comment already worries about — "an agent that believes it will be nagged forever starts
inventing reports to escape" — now applied to `done` instead of the stop gate. Silent
no-op risks losing real content: nothing guarantees the second summary is junk, only that
QA's one observed case was. Recording it under a different event kind costs nothing and
keeps the option open for a human to go look.

**Answer to "does fixing bug 3 alone fix bug 4?" No — related, not the same fix.** Both
bugs share the same defective idea (any `sb` call from the agent revives a `REPORTED` row
unconditionally), and the turn-gap check in §2 is the right fix for *both* branches of
`_revive`. But bug 4's second symptom — duplicate mail — lives in `done()`, not in
`_revive`, and needs its own guard regardless of what `_revive` does, because nothing stops
two `sb done` calls arriving in the same turn (see the shell-one-liner shape above)
independent of whether the row was ever flipped back to `working` in between.

## 4. Collisions with the two parallel leads

Checked by line number against `broker.py` at the HEAD this scout worked from.

- **`task-delivery-fix`** (owns `_spawn`'s delivery block and `_took_a_turn`): `_spawn`'s
  delivery block runs roughly `broker.py:3200-3282`, `_took_a_turn` is `3288-3311`. No
  overlap with anything recommended here — `_revive` (603-664), `whoami` (563-599),
  `done()` (3470-3542) and `block()` (3543-3600) are all outside that range and are
  different methods entirely. No line collision expected.
- **`stalled-agent-cleanup`** (owns the cleanup gate and board status): `cleanup()` starts
  at `broker.py:3603` and runs past 3760; `done()` (3470-3542) and `block()` (3543-3600)
  sit immediately *before* it with no shared lines. No line collision expected either.
  **Behavioural coupling worth flagging even without a line collision:** the turn-gap fix
  in §2/§3 removes a path that currently feeds `stalled-agent-cleanup`'s territory —
  today, a self-revived `blocked`/`done` row is exactly what later shows up as STALLED
  (via the stop gate firing on the wrongly-`working` row) or as `cleanup` refusing a
  genuinely-finished child ("working, not finished — it has not reported an end", the
  exact refusal QA reproduced). If that lead is independently changing what `cleanup`'s
  refusal says or how STALLED is computed, whoever lands second should re-check the other's
  work against a live repro of bug 3/4 rather than assume the two are additive — the
  symptom each is separately staring at (a misleading refusal message; a wrongly-STALLED
  row) may partly *be* this bug, not a separate defect layered on top of it.

## What I did not verify

This was a read-only design scout; nothing here was run. In particular I did not confirm
by execution that:
- an `events` query filtered `kind='turn_end'` and `id > <blocked event id>` is empty in
  the self-revive shell-one-liner case and non-empty in the human-answers-in-pane case —
  this is inferred from reading `hooks.py`'s `stop_gate`/`mark_turn`/`run` control flow,
  not reproduced live. I'm confident in it because `hooks.py`'s own docstring is explicit
  about the order (`stop_gate` decides before `mark_turn` runs, and `REPORTED` is checked
  first), but it is inference from source, not a run.
- the exact current end line of `done()`/`block()`/`cleanup()` may drift by a few lines by
  the time any of these three leads lands; the ranges above are current-HEAD line numbers,
  not stable anchors.
