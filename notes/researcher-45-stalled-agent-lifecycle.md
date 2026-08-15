# Stalled-agent lifecycle: full map

Scout only — nothing here was changed. All line numbers are against this worktree's
current HEAD of `switchboard/status.py`, `switchboard/broker.py`, `switchboard/store.py`,
`switchboard/hooks.py`, `switchboard/herdr.py`. Read `notes/triage/group-4-lifecycle.md`
(on branch `bug-triage`) first section for the filed incident this is scoped to.

## a. The state model

**`agents.state`** — a stored column, one of `working | blocked | done | failed`
(`defaults/settings.toml` `[states]` groups them: `running=["working"]`,
`finished=["done","failed"]`, `live=["working","blocked"]`, `reapable=["working","blocked"]`).
Writers, all in `store.py`/`broker.py`:
- `store.create_agent`/`claim_agent` — inserted as `working` (spawn default).
- `Broker.block` — writes `blocked`.
- `Broker.done` (broker.py:3470) — writes `done`.
- `Broker.cleanup` (broker.py:3806) — writes `done` at close time (`store.set_state(...,"done")`),
  regardless of what state the row was actually in when swept.
- `status._record_gone` (status.py:1057, writes via the `reapable` UPDATE at status.py:1136-1144)
  — writes `failed` for a row that is `REAPABLE` and confirmed absent from herdr
  (`_confirmed_gone`, `GONE_CONFIRM_GRACE` = 60s). **This is the only writer that can end a
  row nobody reported the end of, and it fires only when herdr stops listing the pane at
  all** — not when the pane is merely stuck.
- `Broker._revive` (broker.py:603, esp. 653-656) — reverts a finished row (`ended_at` not
  NULL) back to `state='working', ended_at=NULL` the moment the agent runs *any* further
  `sb` command, deliberately leaving `turn` untouched (comment at 632-652 explains why: a
  written `turn='working'` here is exactly the kind of edge nothing could ever close for a
  session with no Stop hook).

**`agents.turn`** — a separate stored column, `working | idle | NULL`
(`states.turn_working="working"`, `states.turn_idle="idle"`). This is switchboard's own
activity signal, not herdr's. Writers:
- `hooks.mark_turn` (hooks.py:241) — `UserPromptSubmit` writes `turn='working'`, `Stop`
  writes `turn='idle'`. Logged as `turn_start`/`turn_end`, target in payload (not `agent=`,
  so it doesn't reset `_last_activity`'s idle clock — see hooks.py:253-260).
- `status._forget_turn` (status.py:1017) — the ONLY thing that clears a stuck `turn='working'`
  edge. Writes `turn=NULL, turn_doubt_since=NULL`. NULL, not `idle` — deliberately falls
  back to "ask herdr" rather than asserting an end (status.py:1020-1029).

`turn` is NULL for a row no hook has ever fired for (pre-hook stores, or an agent that's
never taken a turn); every reader treats NULL as "no signal, ask herdr instead" — this is
load-bearing throughout.

**`stalled` and `turn_doubted` — where each is computed:**

- `AgentStatus.turn_doubted` — **a computed `@property`** (status.py:476-515). True iff
  `state in RUNNING and turn == TURN_WORKING and alive is True and herdr_state in
  IDLE_LIKE and idle >= TURN_STALE_GRACE`. This is a *doubt*, not a verdict — one bad
  herdr reading must not act alone.
- `AgentStatus.stalled` — **a stored field on the dataclass, but computed once per
  `collect()` call and written onto the object**, not a `@property` (status.py:334 field
  decl; computed at status.py:862/883: `idle = bool(running and turn_over and alive is not
  False)`, `stalled = idle and excuse is None`). `turn_over` (status.py:849-850) prefers
  the store's own `turn` column (`turn == TURN_IDLE`) and falls back to herdr
  (`hstate in IDLE_LIKE`) only when `turn is None`. So **as long as `agents.turn` is stuck
  at `'working'`, `stalled` reads False** — `turn_over` is False, so `idle` is False, so
  `stalled` is False. This is exactly the 45-minute suppression the task describes: the
  stale `turn` edge doesn't just delay STALLED, it hard-blocks the `stalled` predicate
  until something clears `turn` back to NULL.
- The repair: `status.collect()`, in its `reap=True` branch (status.py:927-931), asks
  `_sustained(db, "turn_doubt_since", [names where a.turn_doubted], ..., TURN_DOUBT_GRACE)`
  and feeds the confirmed names to `_forget_turn`. `_sustained` (status.py:972-1014) is the
  shared debounce also used for `gone` (`_confirmed_gone`/`absent_since`) — a name must be
  flagged on *every* reading across the whole grace window, with a single "not flagged"
  reading resetting the clock to nothing.
- Net effect: total time from a session dying mid-turn to `stalled` finally reading True is
  `TURN_STALE_GRACE (1800s) + TURN_DOUBT_GRACE (900s)` = **45 minutes**, both configurable
  via `config.setting("timeouts.turn_stale_grace"/"turn_doubt_grace")`
  (`defaults/settings.toml:279,290`; repo-level overrides work through the normal
  `config.setting` resolution, same file, `settings.toml` in a repo can override the
  package default — not verified per-repo here, but nothing in `config.py` scopes these
  two keys away from the general override mechanism used for every other `timeouts.*` key).

`signal_drift` (status.py:432-474) is the sibling predicate for the case herdr reads the
pane as `unknown` (no Claude recognized at all) rather than `idle`/`done` — genuinely no
agent in the pane. It is NOT the shape in the filed incident (herdr read `idle`, which is
what let `turn_doubted` fire), has no repair path at all, and is surfaced only via
`needs_human`, never reaped. Kept distinct in `needs_human`'s reasoning (status.py:589-592).

## b. The cleanup gate (`Broker.cleanup`, broker.py:3603-3821)

Order, per candidate, inside the `for a in candidates:` loop (broker.py:3705 on):

1. **Self** (3706-3709): `a["name"] == me` → refuse, no flag lifts it.
2. **Already closed** (3710-3713): `ended_at and not pane_id` → refuse (`expected=True`),
   nothing held back.
3. **Live descendants** (3714-3720, computed up front at 3673-3682 into `held`): refuse,
   **no flag — not even `--force` — lifts this one** (see `live_descendants`, b.5 below).
4. `if not force:` gate block (3721-3754) — **everything past this point is what `--force`
   skips entirely**:
   - **4a. Finished** (3722-3732): `a["state"] not in FINISHED` → refuse
     `"{state}, not finished — it has not reported an end"`. **This is the refusal named in
     the task.** It does not mention `--force` anywhere in the string. `expected=` is
     `a["state"] != "blocked"` — i.e. a sweep treats a `working` row hitting this gate as
     *expected* (still working, no note needed), a `blocked` one as worth calling out.
     **A `stalled`/`turn_doubted` row is indistinguishable from a genuinely busy one at
     this gate — it reads `state=="working"` either way.** This is the gate that needs the
     new exemption.
   - **4b. Gone-but-unconfirmed** (3733-3736): `state == GONE_STATE ("failed")` and
     `not self._end_still_holds(name)` → refuse. Re-asks herdr directly (broker.py:4071)
     rather than trusting the stored `failed` verdict, because `_record_gone` can fire off
     a herdr hiccup that has since resolved.
   - **4c. Unread mail** (3737-3747): `store.unread_for(mark=False)` non-empty and
     `not self._finished_and_unreachable(name)` → refuse `"unread mail it could still
     read"`. See (c) below — this is where a stalled row's mail gets stuck.
   - **4d. Legacy `cleanup != "close"`** (3748-3754): dead code path for pre-`--keep`-removal
     rows, irrelevant here.
5. **`--force` bypasses gates 4a-4d entirely** — `force=True` skips the whole `if not
   force:` block. It is legal only when the agent is **named explicitly**
   (`if not names: raise ValueError(...)` at 3666-3668) — never a sweep. Nothing in the CLI
   or this refusal string tells the caller `--force` is the way through; the task's
   complaint #1 is accurate, this is a UX gap not a logic bug.
6. If `force and a["state"] == WORKING"` (3757-3765): logs `cleanup_forced_live` — the one
   place the code admits force "cannot tell stuck from busy" and says so on the record.
7. Close proceeds: `release_agent`/`close_pane` via herdr, `_close_board`,
   `forget_prompt_file`, `store.set_state(db, name, "done")` (**always `"done"`, even for a
   force-closed `working` or `blocked` row** — there is no `"force-closed"` or similar
   state, so a swept stall becomes indistinguishable from a normal `done` afterwards),
   `store.update_agent(pane_id=None)`, **`self._clear_unreadable_mail(name)`** (3818, see c),
   `cleanup` event logged, name appended to result.

**`_finished_and_unreachable`** (broker.py:4093-4131), the precedent gate 4c leans on:
```
a = store.get_agent(db, who)
if a is None or a["state"] not in FINISHED: return False
if not a["pane_id"]: return True
return self._name_bound(who) is False
```
Two-part test: state must already be `done`/`failed` (**not** `working`/`blocked` — this
is exactly why it cannot help a stalled row, whose state is still `working`), and *then*
either it has no pane id at all, or herdr — asked directly by name via `_name_bound`, not
via the raw `agent list` membership, per the docstring's account of the bug the naive
version had (4118-4124) — no longer answers to that name. `_name_bound` returning `None`
("cannot tell") reads as *still bound*, so a herdr outage never trips this open. This is
the closest existing precedent for a state-independent "give up on this row" exemption,
but it is deliberately gated on `FINISHED` first — extending it (or adding a sibling) to
also admit a `stalled`/`turn_doubted` `working` row is a **new** exemption, not a widening
of this one.

## c. The mail path

"Unreadable" has two distinct meanings the code keeps apart, both in `store.py`:
- **`mark_unannounceable`** (store.py:1599-1616) — stamps `delivered_at` only, leaves
  `read_at` NULL. For a row whose **pane herdr still lists** (`_pane_still_listed`,
  broker.py:4218-4238, true whenever herdr answers *anything* for that name/pane, or
  cannot be asked at all). Message stays genuinely readable — `sb inspect`, `sb restore`+
  `sb inbox` — just stops being chased by the doorbell.
- **`mark_undeliverable`** (store.py:1619- ) — stamps `delivered_at` **and** is the
  branch for a pane herdr has confirmed gone. `read_at` still deliberately left NULL (so
  `sb inspect`/`sb restore` still show it), but this is the "nobody will ever read this"
  branch, logged `mail_cleared`.

**`Broker._clear_unreadable_mail`** (broker.py:4240-4306) picks the branch: if
`a["pane_id"] and self._pane_still_listed(who)` → gentle branch (`mark_unannounceable`,
event `mail_unannounced`), else → the undeliverable branch (`mark_undeliverable`, event
`mail_cleared`) over the full re-derived `unread_for` backlog for that name.

**When it runs:** two call sites only —
1. `Broker.flush_pending` (broker.py:4199-4201), inline in the per-`sb`-command doorbell
   sweep, guarded by `self._finished_and_unreachable(who)` — i.e. **only for rows already
   in a FINISHED state**. A `working` stalled row never reaches this call at all.
2. `Broker.cleanup`, unconditionally at the end of every successful close (3818) — **this
   runs regardless of force**, but a row only gets there once it has passed (or bypassed via
   `--force`) every earlier gate, including the `state not in FINISHED` one.

**What this means for a stalled agent's mail today:** `unread_for` still reports it
because `mark_unannounceable`/`mark_undeliverable` are never reached for a `state=working`
row — `flush_pending`'s guard requires FINISHED, and `cleanup` gate 4a refuses before mail
is ever touched. So mail sits fully unread, fully un-clearable, until either (a) the agent
somehow reports an end itself, or (b) a human runs `sb cleanup --force <name>`, at which
point gate 4a-4d are all skipped, the close proceeds, and `_clear_unreadable_mail` finally
clears it — this is exactly the `mail_cleared` event the triage note observed at 19:05,
6.5 hours after the crash. **Nothing today releases a stalled agent's mail back to its
sender** — there is no "return to sender" mechanism anywhere in this file; mail is only
ever marked unannounceable/undeliverable in place, never rerouted.

**What would have to be true for it to happen automatically:** either (1) `cleanup`'s gate
4a grows a stalled/turn_doubted exemption (matching (f) below) so a `--force`-free sweep
can reach `_clear_unreadable_mail` for these rows too, or (2) `flush_pending`'s
`_finished_and_unreachable` guard (or a new sibling predicate) is loosened to also cover a
confirmed-stalled `working` row directly, independent of `cleanup` ever running — the
latter would clear the mail (stop the doorbell chasing it) without closing the pane, which
is a smaller, non-destructive intervention than sweeping the whole row.

## d. The board

`AgentStatus.display_state` (status.py:376-430) is what actually draws the STATE column,
and it performs the same `turn`-then-herdr join as `stalled`/`turn_doubted`: `if
self.turn is not None: return self.state if self.turn == TURN_WORKING else "idle"` (427)
— so as long as `agents.turn` is wedged at `'working'`, `display_state` **also** reads
`working`, same as `stalled`. This is the mechanism behind consequence #3 in the task: the
row is drawn as an ordinary working agent for the same reason `stalled` reads False — one
stuck column gates both. `_flags`/board rendering (status.py:1676, 1709, 1773-1778) draw
`STALLED — idle Nm — its turn ended ...` only once `a.stalled` is True, i.e. only after
`_forget_turn` has cleared `turn` back to NULL, i.e. only after the full 45-minute
`TURN_STALE_GRACE + TURN_DOUBT_GRACE` window. `TURN_STALE_GRACE`/`TURN_DOUBT_GRACE` live at
status.py:270-271, sourced from `config.setting("timeouts.turn_stale_grace"/
"turn_doubt_grace")`, values in `defaults/settings.toml:279,290` (1800.0 / 900.0) — both
ordinary `config.setting` keys, so configurable the same way every other `timeouts.*`
value is (per-repo `settings.toml` override; not separately special-cased in `config.py`).

## e. Precedent and risk — who else reads `agents.state == 'working'`

Every place a stalled row (`state='working'`, but truly dead/stuck) is currently *treated
as alive* by something other than the cleanup gate, and would change behavior if that
row's state were ever swept out from under it (e.g. to `done`/`failed`) by a new mechanism:

- **`Broker.live_descendants`** (broker.py:3823-3861) — `a["state"] in store.LIVE_STATES
  and not a["ended_at"]`, `LIVE_STATES = ("working","blocked")`. This is what makes gate 3
  (live-descendant refusal) fire for a **parent** of a stalled child — the child's stuck
  `state='working'` keeps the parent's own `sb cleanup <parent>` refused too, and this is
  the ONE gate `--force` never lifts. **If a stalled row is auto-swept to `done`/`failed`,
  its parent's live-descendant refusal disappears with it** — probably desired, but worth
  naming: it changes what "still working underneath" means for every grandparent in the
  tree, not just the row itself.
- **`hooks._has_live_child`** (hooks.py:203) and **`Broker._has_live_child`**
  (broker.py:4634-4645) — both raw-SQL `state IN ('working','blocked') AND ended_at IS
  NULL` (hardcoded strings, not `LIVE_STATES`, but same set today). `hooks._has_live_child`
  is the **Stop-hook exemption** (hooks.py:308-312): a parent with a live child is allowed
  to end its own turn without reporting. If a stalled child's `state` changes out from
  under it (by anything other than the child's own `sb done`), a parent that is *itself*
  mid-turn and checking this on its own next Stop could lose the exemption mid-flight —
  low risk in practice since this hook fires once per turn end, but it is a caller that
  assumes `state='working'` means "genuinely still going," and any auto-sweep changes that.
  `Broker._has_live_child` backs `reconcile`'s `reconcile_waived` exemption at
  broker.py:4571-4574 — same assumption, lower stakes (reconcile just skips a ping).
- **`Broker.reconcile`** (broker.py:4524-4581) already pings every `a.stalled` row via
  `_nudge` → `self.h.prompt(who, text)` (4603). For the incident's actual shape (herdr
  reads the pane as idle, not unknown — that's what let `turn_doubted`/`_forget_turn` fire
  at all), this means **once the 45-minute repair does clear `turn`, the very next
  `collect(reap=...)` call also makes `stalled` True and the reconciler will try to prompt
  a pane that may not actually be running Claude any more** (if the session process itself
  is gone, only the shell remains, `h.prompt` writes into a dead shell — silent no-op from
  the fleet's point of view, `reconcile_ping` still logs as if it landed since `_nudge`
  only inspects the HerdrError path, not whether anything downstream reacted). Not a new
  bug this task creates, but worth the implementer knowing reconcile is already reaching
  these rows once `turn_doubted` resolves — any cleanup-side fix should use the **same**
  `stalled` (or a `stalled`-plus-something-more-confirmed) predicate reconcile already
  trusts, rather than inventing a second notion of "safe to sweep."
- **`_finished_and_unreachable`** and **`flush_pending`** (b, c above) both gate on
  `state in FINISHED` first — unaffected by a state change *to* `done`/`failed`, only
  currently blind to a row still at `working`.
- **herdr.py `WORKING`** (herdr.py:83, `_running_turn`/`_took_prompt`,
  herdr.py:730-782) is a **different constant with the same string value** — herdr's own
  pane-content classification, not the `agents.state` DB column, imported into `broker.py`
  (`from .herdr import WORKING`) and reused for two *different* comparisons: herdr-state
  reads (broker.py:3316, `live.state == WORKING`) and DB-state reads (broker.py:3757,
  `a["state"] == WORKING`) that happen to share the literal `"working"`. **This is exactly
  the pane-delivery surface `task-delivery-fix` (the parallel lead) owns** — `herdr.py`
  `deliver`/`_took_prompt`/`_running_turn` and `broker.py`'s `_spawn` delivery block/
  `_took_a_turn` are named in this task's constraints as theirs. Our recommended fix (f)
  does not need to touch any of those functions — it only touches `Broker.cleanup`'s state
  gate and possibly `status.py`'s `stalled`/`turn_doubted` predicates and
  `_clear_unreadable_mail`'s call sites — but **flagging per the task's instruction**: if
  their fix changes what `agents.turn`/`agents.state` look like for an agent whose prompt
  silently failed to land, it changes the input our fix reads, not the reverse. No file
  overlap either way as of this reading.

## f. Recommended fix shape, minimal-first

1. **(Mechanical, lowest risk) Name `--force` in the refusal.** Change the string at
   broker.py:3730 from `f"{a['state']}, not finished — it has not reported an end"` to
   also say `--force` is the way through for a named agent. Fixes consequence #1
   completely on its own, zero semantic change, no design call needed — a human should
   just approve the wording.

2. **(The real gate) Let gate 4a admit a confirmed-stalled row without `--force`.** Add an
   exemption at broker.py:3722, parallel to the existing `_finished_and_unreachable`
   pattern at 4c: something like
   `if a["state"] == WORKING and not status.AgentStatus(...).stalled: refuse(...)` — in
   practice this means `cleanup` needs a `status.collect()`-derived view of the candidate
   (or a narrower helper reusing `turn_doubted`/`stalled`'s own logic) rather than the raw
   `agents` row it works from today, since `stalled` needs `turn`, herdr's live read, and
   `idle` together. **Design decision for a human, not the implementer:** should the bar to
   sweep be `stalled` (idle, no live-child/awaiting-task excuse — reached only after the
   full 45-minute wait) or something that can fire sooner, e.g. `turn_doubted` alone
   (doubt registered, before `_sustained` even confirms it) or a fresh predicate that
   doesn't wait for `_forget_turn` to run first? Reusing `stalled` is the conservative,
   already-vetted answer (reconcile already trusts it) but inherits the full 45-minute
   wait before `--force`-free cleanup becomes possible — probably fine, since gate 3
   (live descendants) and the mail gate (4c) still apply on top, but it's the human's call
   whether 45 minutes is the right floor for *this* gate specifically, separate from the
   board-display question in (d).

3. **(Mail, can ride with #2 or land separately) Let the mail gate (4c) or
   `flush_pending` reach a stalled `working` row.** Either extend
   `_finished_and_unreachable` to also return True for a confirmed-stalled `working` row
   with an unreachable/gone-looking pane (changes its contract — currently strictly
   `FINISHED`-only, so this needs a new name or an explicit added clause with its own
   docstring paragraph, not a silent widening), or add a sibling predicate
   `_stalled_and_unreachable` used only by the mail path. **Design decision:** should
   stalled mail be cleared (stop the doorbell, as `mark_unannounceable` already does for
   finished-but-unreachable rows) *independently* of whether the row itself gets swept?
   Doing so via `flush_pending` would fix consequence #2 without needing #2/#1 to land
   first, and is the more surgical, non-destructive option — worth the human choosing
   between "mail clears when swept" (simpler, one code path) vs. "mail clears as soon as
   stalled, sweep is separate" (fixes #2 sooner, needs a second call site).

4. **(Board, arguably already adequate) Consequence #3 is already mitigated by the
   existing 45-minute repair** (`_forget_turn`) — the task frames it as a design tradeoff
   already made (erring long is deliberate, per status.py:246-248's comment on
   `GONE_CONFIRM_GRACE`'s sibling reasoning), not obviously a bug to fix further. If a
   human wants the STALLED flag to appear sooner than 45 minutes for a `turn_doubted`
   (not yet `_sustained`-confirmed) row specifically, that's a change to `turn_doubted`'s
   own grace constants or to `stalled`'s computation to notice `turn_doubted` directly —
   **explicitly a design call**, since the whole point of `TURN_DOUBT_GRACE` is not
   trusting one bad herdr reading (status.py:507-511), and shortening it anywhere
   reintroduces exactly the false-positive risk the two-stage debounce was built to avoid.

**Ranked:** #1 (trivial, do it regardless) → #2 (the actual bug from the task title) → #3
(closes the mail hole, can be sequenced independently of #2) → #4 (probably out of scope;
flag it to the human rather than build it).

**Design decisions a human must make, collected:**
- Which predicate gates the new cleanup exemption — `stalled` (conservative, 45-min floor,
  reuses reconcile's own trust) vs. something faster (e above already flags that
  `reconcile` itself pings on `stalled`, so whatever the new gate uses should probably be
  the same predicate reconcile already relies on, to keep "safe to sweep" and "safe to
  ping" in agreement).
- Whether mail-clearing for a stalled row is coupled to the cleanup sweep or independent.
- Whether `_finished_and_unreachable` gets widened (contract change, needs its own
  docstring rewrite) or gets a sibling predicate instead.
