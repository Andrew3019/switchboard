# STALLED vs idle on `sb board` — findings

Scope: read-only, no edits. Files read: `switchboard/status.py`, `switchboard/board.py`,
`switchboard/richboard.py`, `DESIGN-TRUTH.md`, plus `git branch -a` to check the collision
heads-up.

## 1. Where each state is computed

Both come from `switchboard/status.py`, inside `collect()` (the per-tick join of store +
herdr), and are read by `board.py`/`richboard.py` for display. Nothing is computed twice —
`board.marker` and `richboard.needs_kind` both read the same `AgentStatus.stalled` field.

**`idle`** — `status.py:912`:
```python
idle = bool(running and turn_over and alive is not False)
```
- `running` = `row["state"] in RUNNING and row["ended_at"] is None` (`status.py:841`)
- `turn_over` (`status.py:899`) = our own `agents.turn` signal if we have one
  (`turn == TURN_IDLE`), else fallback to herdr: `bool(alive) and hstate in IDLE_LIKE`.
- `alive is not False` — herdr hasn't positively said the pane is gone (that's GONE's case).

**`stalled`** — `status.py:908-933`:
```python
excuse = ("awaiting first task" if awaiting
          else "waiting on children" if name in live_parent
          else "starting up" if starting
          else None)
...
stalled = idle and excuse is None
```
Three exemptions only:
- `awaiting` — `agents.awaiting_task` still set (never given a first task yet — a fresh
  lead/orchestrator).
- `name in live_parent` — has a direct child still `working`/`blocked` and not ended
  (`live_parent` built at `status.py:796-798`).
- `starting` — no `session_id` yet and still inside `STALL_GRACE` of creation
  (`status.py:885`).

So **`stalled` is not an independent signal** — it's the exact same `idle` boolean, with
three narrow carve-outs subtracted.

## 2. Timing: idle and stalled fire at the same instant

There is **no separate stall timeout** layered on top of `idle`. The moment `turn_over`
flips true (our `Stop` hook fires, or herdr's fallback reading says the pane is idle),
`idle` is true — and in the same expression, on the same tick, `stalled` is true too,
*unless* one of the three named excuses applies. `STALL_GRACE` and `TURN_STALE_GRACE`
exist elsewhere in the file, but they gate different things (the `starting` excuse's
window, and `signal_drift`/`turn_doubted`'s "how long do we trust a `working` edge with no
corroboration" — a completely different question). Nothing delays STALLED behind idle.

**So `stalled` is not a superset of `idle` reached later — it's idle itself, minus three
specific shapes.** For any ordinary agent that (a) has already been given a task, (b) has
no live children, and (c) has already started — which is most workers, reviewers, and any
lead once its first child is done — going idle and going STALLED are the same event.

## 3. What drives NEEDS YOU, and its relation to STALLED

There are actually **two different "needs a human" predicates** in this codebase, used by
different views:

- `AgentStatus.needs_human` (`status.py:589-607`), used by `sb status --needs-me` /
  `--json` / the DRIFT block:
  ```python
  return (self.blocked or self.at_prompt or self.unread > 0
          or self.waiting_to_be_rung or self.stalled or self.signal_drift)
  ```
  `stalled` is one of six OR'd conditions — a strict subset of this, not identical to it.
  An agent can need-you without being stalled (unread mail, blocked, at a prompt).

- `richboard.needs_kind` / `needs_list` (`richboard.py:214-231, 278-299`), which is what
  actually populates the **NEEDS YOU section on the interactive board**:
  ```python
  if a.blocked or a.at_prompt: return "blocked"
  if a.stalled or a.signal_drift: return "idle"
  ```
  then `needs_list` further drops any "idle"-kind row whose subtree still has live work
  beneath it (`busy_below`, so a lead isn't summoned just because a *grandchild* is still
  going — narrower than the one-generation `live_parent` excuse in `stalled` itself).

**So on the board specifically: STALLED and "idle" NEEDS YOU membership are, by
construction, almost the same condition already.** `stalled` implies `needs_kind == "idle"`
implies membership in NEEDS YOU (modulo the subtree check, which only *removes* rows, never
adds ones that aren't stalled). The only way to be in NEEDS YOU without being STALLED is via
`blocked`/`at_prompt` — a different section of the same list, drawn with a different marker
("BLOCKED", "AT PROMPT"), not "STALLED".

`board.marker()` (`board.py:203-220`) is the function that actually prints the word
"STALLED" on a row: it fires whenever `a.stalled` is true, full stop — it does not check
NEEDS YOU membership, but as shown above, everything with `a.stalled` true already qualifies
for NEEDS YOU's "idle" kind, so there's no daylight between "shown as STALLED" and "would be
summoned by NEEDS YOU" for that agent (again modulo the busy_below subtree veto, which just
hides some stalled leads/roots from the summons list without changing their row's marker —
see §6).

## 4. Verdict on Andrew's reading

**Partly right, partly not, and it's worth separating the two claims in his message:**

- *"seems like all idle are stalled"* — **essentially true in practice**, but not because
  the code conflates the two. It's because the only agents excused from STALLED are three
  specific structural shapes (never-tasked lead, parent with a live child, still starting
  up) — and a typical worker/reviewer/leaf agent that finishes an ordinary turn matches none
  of them. For that common shape, `idle` and `stalled` are computed as literally the same
  boolean at the same instant (§2). So yes: for most agents, in practice, idle ⟹ STALLED,
  immediately, with no separate threshold.

- *"only idle that goes to NEEDS YOU should be actually stalled"* — **this is already how
  it works**, on the board specifically (§3). `stalled` is already scoped to be
  NEEDS-YOU-worthy: it's one of the two `needs_kind` branches that populate the section, and
  no idle agent is marked STALLED without also qualifying for NEEDS YOU's "idle" kind. There
  is no case today where a row says STALLED but is absent from NEEDS YOU.

So the apparent contradiction Andrew is naming — "everything idle is stalled, but shouldn't
only NEEDS YOU-idle be stalled" — dissolves once you see that "stalled" was deliberately
*designed* to mean "idle with nothing excusing it, i.e. the human should look" (see the
module docstring at `status.py:1-33`, and the `AgentStatus.stalled`/`idle_excuse` field
comments at `status.py:370-380`). The three excuses are the whole mechanism that keeps
STALLED from being "just idle" — and they're deliberately narrow, tuned to specific known
shapes (a lead waiting on its own children, a fresh unstarted agent), not to "idle in
general." If most agents don't hit them, that's the exemption list being narrow, not the
STALLED/NEEDS-YOU relationship being wrong.

**What might actually be bothering Andrew**, if the board still *feels* like it's crying
STALLED too often: the exemption list may be too narrow for shapes that exist in practice
but aren't covered — e.g. a dispatcher genuinely between tasks, or a lead whose child is
itself idle-with-a-live-grandchild (richboard's `busy_below` handles that for the NEEDS YOU
*list*, at `richboard.py:285-291`, but that fix is NOT applied to `stalled` itself, only to
who's *summoned* — the row still shows the STALLED marker even when richboard hides it from
the NEEDS YOU section). That's a real, narrow gap: **the "waiting on children" excuse in
`status.py` is one generation deep (`live_parent`, direct children only); richboard's
`busy_below` is the whole subtree.** A lead with an idle child that itself has a working
grandchild is STALLED on its own row (`status.stalled` says so) but silently excluded from
richboard's NEEDS YOU list (`needs_list` drops it via `busy_below`) — so that row now
reads STALLED on the board while NOT being in NEEDS YOU. That is a real, if narrow,
counterexample to "STALLED implies NEEDS YOU" worth flagging (see §6).

## 5. Anything suggesting STALLED means something other than "needs a human"

No — the documentation is unambiguous that STALLED was built specifically to name "this
agent's turn ended and it never called `sb done`/`sb block`, so nothing in the fleet will
ever act on it again unless a human notices" (`status.py:21-26`, `:592-599`). It is not an
overloaded or repurposed word. `richboard.needs_kind`'s docstring (`richboard.py:214-225`)
explicitly groups `stalled`/`signal_drift` under the "idle" kind of NEEDS YOU, in contrast
to `blocked`/`at_prompt`'s "blocked" kind — so the design intent is that STALLED already
*is* one of the two flavors of "needs a human," not an unrelated diagnostic word.

## 6. Minimal-fix sketch, IF the fix is "only call it stalled when it reaches NEEDS YOU"

Given §3/§4, there is really only one concrete gap to close, not a redesign:

- **The subtree check.** `status.py`'s `stalled` excuse only looks at direct children
  (`live_parent`, `status.py:796-798`, one generation). `richboard.busy_below`
  (`richboard.py:252-275`) already computes the correct whole-subtree "is anything under me
  still going" answer, but only `richboard.needs_list` uses it — `status.stalled` and
  `board.marker` do not. Fix would be: either (a) have `status.collect` also exclude
  subtree-busy leads from `stalled` (needs the full agent list built first, so `stalled`
  can no longer be computed row-by-row in the same loop — a bigger change), or (b) leave
  `status.stalled` as the raw one-generation signal and have `board.marker`/`glyph` (not
  just richboard's NEEDS YOU list) apply the same `busy_below` veto before printing
  "STALLED" on a row. (b) is the smaller change: touch `board.py` (`marker`, `glyph`,
  `wants_you` at `board.py:165-220`) to accept and check subtree-busy state the way
  `richboard.needs_list` already does, so a row never shows STALLED while richboard would
  simultaneously exclude it from NEEDS YOU.
- Everything else — the `stalled` boolean itself, `needs_human`, `needs_kind`, `needs_list`
  — already implements "STALLED ⟹ NEEDS YOU" by construction; no reclassification is needed
  there.

## Collision heads-up

Confirmed via `git branch -a`: `board-refresh-flicker` and `board-awaiting-keypress`
branches both exist, matching the brief's two other in-flight agents.
- **board-refresh-flicker**: touches board render/refresh timing, likely inside `board.py`
  or `richboard.py`'s draw/layout path (`board.layout`, `board._frame`, `board.draw`). If
  this scout's §6 fix changes `board.marker`/`glyph`, it edits the same functions that
  refresh-flicker work would be touching — coordinate before editing `board.py`'s marker/
  glyph functions.
- **board-awaiting-keypress**: a new "waiting on a human keypress" state, "on the board and
  in NEEDS YOU" per the brief — that's a third value alongside `blocked`/`at_prompt` in
  exactly the same rank-ordered spots this scout read: `board.marker` (`board.py:203-220`,
  strictly ranked: gone > at_prompt > blocked > stalled > signal_drift), `board.glyph`
  (`board.py:165-185`), `board.wants_you` (`board.py:191-200`), and richboard's
  `needs_kind`/`needs_list`/`needs_reason` (`richboard.py:214-314`). Any STALLED-related
  fix here and any keypress-state work there will both be editing the same handful of
  ranked if/elif chains in the same four functions — high collision risk, worth explicitly
  sequencing rather than parallelizing.

I did not read `hooks.py`, `broker.py`, or `reconciler`-related code beyond what's quoted
in `status.py`'s comments — those weren't asked for and I didn't verify their behavior
independently.
