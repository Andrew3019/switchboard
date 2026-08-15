# Why does clearing a dead pane have to be manual, and could switchboard do it itself?

Scope: investigation only, per `notes/task-gone-agents.md`. No product code touched.

## TL;DR

Most of what Andrew imagines as "the manual clear" is **already automatic**. The moment
herdr stops listing an agent's pane, switchboard already (a) confirms the absence over a
debounce window, (b) writes `state=failed` into the store, and (c) pings the parent with a
message — no human action required, and it happens on the very next `sb` command anyone
runs, or automatically via `sb reconcile` on the collector's own timer if a board is open.
The board/status text views also already **collapse** an absent agent's row into a `+N
archived` footer by default, seconds after it goes.

The one genuinely manual step left is **`sb cleanup`** — releasing the pane reference,
closing the tab, clearing stuck mail, and (at the top of a workspace) deleting the
worktree. That step is manual not because anyone forgot to wire it up, but because
`cleanup()` is explicitly, by the code's own words, *"the one caller that acts on the row
irreversibly"* — and the inference that a pane is gone is exactly the kind of fact this
codebase's design refuses to act on without a human or an explicit call naming the agent
(`broker.py:4075-4084`, and the module-wide principle in `status.py:24-26`: "we
deliberately do NOT repair it... surfacing beats guessing (C9)").

## 1. The current mechanics

**Where `gone` comes from.** `status.collect()` (`status.py:689-936`) does one `herdr agent
list` call and one pass over the `agents` table per invocation. For each row:

- `unended` = the store's `state` is `working` or `blocked` (`REAPABLE`, `settings.toml:142`)
  and `ended_at` is NULL — i.e. nothing has ever reported an end for this row.
- `gone` = `unended AND alive is False AND not spawning` (`status.py:895`), where
  `alive is False` means herdr answered the `agent list` call and simply did not include
  this name (as opposed to `alive is None`, which means herdr could not be reached at all —
  see below).

**The debounce.** A single absent reading is not trusted — `_confirmed_gone`
(`status.py:939-969`) stamps `agents.absent_since` on the first sighting and only hands the
name back to be recorded once it has been *continuously* absent for
`timeouts.gone_confirm_grace` = **60 seconds** (`defaults/settings.toml:252`). One agent
seen present again at any point during that window clears the stamp entirely — this is the
literal fix for a bug the code remembers by name: "the store's own history has three
agents marked failed during one night's startups" from trusting a single herdr hiccup
(`status.py:238-240`).

**The write.** `_record_gone` (`status.py:1057-1162`) then, in one commit:
- `UPDATE agents SET state='failed', ended_at=COALESCE(ended_at, now)` — but only if the
  row is *still* in `REAPABLE` at that instant (a race guard: an agent that reports `done`
  in the gap between the herdr read and this write is not overwritten).
- Writes a `messages` row to the parent, `kind="failed"`, with a one-line note ("stopped
  without reporting and its pane is gone") — delivered exactly like a `done`, through the
  same `flush_pending`/doorbell machinery, respecting the same when-idle/blocked holds.
- Logs a `gone` event.

This is guarded by `if consulted and reap` (`status.py:918`) — `consulted` means herdr was
actually reachable this time, and `reap` is a flag most readers pass as `False`
(`board.py`, `collector.py:197` for the always-running board/collector loop) so a
long-running process never acts on stale code. The only paths that pass `reap=True` are
**`sb status`** (a short-lived, current-code process, `cli.py:977`) and **`sb reconcile`**
(`cli.py:661`), which is the one command the collector's own background timer runs
unattended, specifically so a child's death reaches its parent "as mail" rather than
"archaeology" someone has to notice on the board (`cli.py:640-645`, `collector.py:256-314`).

**So: recording the death and notifying the parent are already automatic**, gated only on
(a) something invoking any `sb` command, or a board/collector process being alive to run
`sb reconcile` on its own, and (b) the 60s confirm window. Andrew doesn't have to do
anything for this part.

**Board display.** Separately, `AgentStatus.archived` (`status.py:597-626`) is true once
`alive is False` and the row's age has passed `SPAWN_GRACE` (~4-5 minutes, derived from
herdr's own worst-case spawn retry budget) — this is a pure rendering fact, recomputed
every tick, never stored. `display_rows` (`status.py:1482-...`) collapses a fully-archived
subtree into one `+ N archived` line, and `display.show_archived` defaults to **false**
(`defaults/settings.toml:415`). So both `sb board` and `sb status`'s text render already
hide a gone row behind a fold within a few minutes, well before the human would otherwise
notice it sitting there in full.

**What "the manual clear" actually is.** `Broker.cleanup()` (`broker.py:3599-3817`), called
by `sb cleanup`. With no names given, it sweeps every *finished* agent in the caller's
scope (state in `["done","failed"]`) that has no unread mail it could still read and no
live descendants, and for each one: releases the pane in herdr, closes the tab, closes the
board if this was the last agent in it, deletes the system-prompt file, sets
`pane_id=NULL`, clears any now-unreadable mail, and logs `kind="cleanup"`. Per
DESIGN-TRUTH.md:229-231, at the top of a workspace this cascades further — "closes the
entire space and deletes the worktree if everything else is closed too."

**Nothing calls `cleanup()` automatically.** Not the collector, not `reconcile`, not
`status.collect()`. It is only ever invoked by a human typing `sb cleanup`, or by an agent
(an orchestrator is *expected* to call it on its own subtree — DESIGN-TRUTH.md:219-221:
"The orchestrator handles cleanup itself, and it should do this aggressively — probably
literally every agent that is done"). For a **root** agent — one Andrew spawned directly,
with no orchestrator above it — there is no agent whose job this is, so it stays until he
runs it himself. That is consistent with `_record_gone`'s own comment: "A ROOT agent has
no parent and the human has no mailbox, so its failure stays a row and an event... and is
the one case a person still has to see on the board" (`status.py:1122-1127`).

## 2. Why it is manual today — is there a recorded reason?

I found **no passage in DESIGN-TRUTH.md or in code comments that argues against**
auto-clearing a gone/failed row. There is no line saying "and this step must stay manual
because X." What I did find is a strong, repeated design stance that explains why nobody
reached for it by default, without ever naming this exact case:

- `status.py`'s module docstring states the house rule generally: for the sibling case of
  a stalled agent, "We deliberately do NOT repair it... Surfacing beats guessing (C9)."
  Recording the failure (writing `state=failed`, telling the parent) is exactly the kind of
  "surfacing" this codebase is comfortable doing on an inference. *Acting further* on that
  same inference — closing panes, deleting a worktree — is a different category of act.
- `Broker._end_still_holds` (`broker.py:4067-4087`) exists **specifically** because
  `cleanup()` is "the one caller that acts on the row irreversibly," and a `failed` state
  is "a cached observation of a single `agent list`" that could be stale, mid-spawn, or a
  race — so cleanup re-verifies with herdr before touching a `GONE_STATE` row rather than
  trusting the stored inference. That is the clearest signal in the codebase of *why*
  turning "recorded gone" into "closed and possibly worktree-deleted" is treated as a step
  that wants a deliberate trigger, even though nobody wrote that rule down for this
  specific question.
- DESIGN-TRUTH.md never discusses auto-cleanup of gone/failed agents at all — the only
  cleanup-related confirmed decisions are about *orchestrators* being aggressive about
  their own subtrees (219-221) and about restore being unavailable once a worktree is gone
  (277-279). Root-level, human-owned agents are simply outside that decision's scope.

**Plain answer: this looks like an absence, not a decision.** The recording/notifying half
was clearly and deliberately automated (with real engineering care — the debounce, the
race guard, the reap-only-from-current-code rule). The closing half was left to
`sb cleanup`, which is a pre-existing, general-purpose, human/orchestrator-invoked
command — and nothing in the history suggests anyone weighed "should a *gone* row
specifically auto-trigger it" and said no.

## 3. What would be lost by auto-clearing

Confirmed from `cleanup()`'s own docstring and behavior (`broker.py:3604-3606`): closing an
agent's pane is cheap. `session_id`, the stored `summary` (from its last `sb done`, if any),
`messages`, and the on-disk transcript are untouched by `cleanup()` — none of the SQL in
`cleanup()` touches those columns/tables. `sb restore` (`broker.py:3867-3966`) works from a
`session_id` alone and does not check `state` at all — it works on a `failed`/GONE row
exactly as it would on a `done` one, **as long as the checkout directory still exists**.

So the pane being gone is cheap and recoverable (`sb restore`) right up until the point
something deletes the worktree. That is the one real loss, and it is not caused by
`cleanup()` releasing a pane — it is caused by the workspace-level teardown that `cleanup()`
can cascade into when it closes the *last* agent in a space (DESIGN-TRUTH.md:229-231,
:277-279: "`sb restore` is gone if the worktree is gone... the push is the recovery path
for the work, not restore"). Auto-clearing a single dead pane does not, by itself, delete
anything; auto-triggering the *cascading* workspace close on an inferred death is the part
that would need to be irreversible on a guess, and is exactly the part `_end_still_holds`
was written to double-check before `cleanup()` itself will touch it.

One smaller, real nuance: `cleanup()` unconditionally sets `state="done"` on close, even
for a row that was `failed` (`broker.py:3802`). The event log still has `kind="gone"` /
`kind="cleanup"` and `sb log`/`sb inspect` still tell the true story, but the live `state`
column stops distinguishing "closed because it finished" from "closed because it died
un-reported" the moment cleanup runs. That's pre-existing behavior, not something
auto-clearing would introduce, but it means auto-clearing would compound with an existing
quirk — a fast, invisible flip from a visible `failed` row to an indistinguishable `done`
one, sooner than a human currently notices it.

## 4. The dangerous cases

Going through "herdr has no such agent" ≠ "the human closed a finished pane":

| Case | Is it GONE, or something else? | Would auto-clearing lose anything? |
|---|---|---|
| Human closed the pane/space by hand, work already reported (`sb done`) | GONE only briefly — state is already `done`/finished before the pane closes, so this case barely touches `_record_gone` at all | No — nothing left to record |
| Human closed the pane/space by hand *before* the agent reported | GONE, correctly | No new loss — same as today's manual `sb cleanup`, just earlier |
| Crash mid-turn (process killed, `/exit`ed) leaving no pane at all | GONE, correctly — herdr genuinely no longer lists it | No — same as above; the transcript up to the crash is preserved regardless |
| Crash/kill that leaves a *dead shell* in the pane (herdr still sees a pane, reads `unknown`) | **NOT gone** — this is `signal_drift` (`status.py:432-474`), a different, disjoint flag. `gone` requires `alive is False`; here `alive is True` with `herdr_state==UNKNOWN`. Nothing here proposes touching this case, and it wouldn't be — `_confirmed_gone`/`_record_gone` never see it | N/A — out of scope, correctly untouched |
| herdr unreachable / restarted mid-poll | `consulted=False` → `alive=None` for every row → `gone` cannot be computed True (`status.py:790`, `918`) → nothing recorded, nothing cleared | No — this is already fail-closed |
| Machine reboot (all panes really gone) | GONE, correctly, once herdr comes back and answers | No — genuinely dead, same as the mundane case |
| Agent died with **unread mail** | GONE gets recorded (state→failed, parent pinged) regardless — that's already automatic today. But `cleanup()`'s own gate refuses to close a row with unread mail it could still read, *unless* the agent is also finished-and-unreachable (no reachable pane to ring, `broker.py:3733-3743`) | No new risk from auto-clearing *cleanup* specifically, because this existing gate would still apply to an automated caller exactly as it does to a human's `sb cleanup` — the mail is not lost, just not clearable while it's still theoretically readable |
| Agent died with **children still running** | `cleanup()`'s live-descendants gate refuses this unconditionally — "nothing lifts this one... not even `--force`" (`broker.py:3624-3630`) | No — same gate would block an automated cleanup exactly as it blocks a human's |
| A `failed` row that was a stale/racy read (herdr hiccup, mid-spawn) | `cleanup()` re-checks with `_end_still_holds` before ever closing a `GONE_STATE` row, specifically to guard against acting on this | No — this existing recheck is exactly the safety net an automated trigger would still go through |

The upshot: every one of the genuinely dangerous shapes (still has children, still has
unread mail, might be a stale inference, is a live-but-unrecognized pane rather than a gone
one) is **already gated inside `cleanup()` itself**, independent of who or what calls it.
Nothing about calling `cleanup()` automatically instead of by hand would need to re-derive
those safety checks — they exist regardless of the caller.

## 5. Options

**(a) Auto-clear once GONE is confirmed and nothing is owed to it.**
Have the collector (or `sb reconcile`, which already reaps) call `cleanup([name])` for any
row that just transitioned to `failed` via `_record_gone` *and* passes `cleanup()`'s own
existing gates (no unread mail, no live descendants) — i.e. let `_record_gone` hand its
output straight to the existing, already-safe `cleanup()` path instead of stopping at the
write.
- Changes: a few lines wiring `_record_gone`'s confirmed names into a `cleanup()` call,
  gated the same way `reconcile` already gates its own reaping (current code, short-lived
  or collector-owned process).
- Costs: closing panes silently, a bit more surprising the first time — a row a human was
  about to go double-check on the board is now just... not there, replaced by whatever
  the parent's inbox says.
- Risks: this is the one path that can cascade into deleting a worktree
  (DESIGN-TRUTH.md:229-231) — the same irreversible step the code already treats with
  extra care (`_end_still_holds`). Auto-triggering that off an *inferred* absence, even a
  well-debounced one, is a bigger step than auto-recording the inference was.
- Size: small in code, but the largest behavior change of the three real options — it's the
  one that touches the irreversible path.

**(b) Auto-clear after a grace period, separate from `GONE_CONFIRM_GRACE`.**
Same as (a), but don't fire on the same tick `_record_gone` confirms — wait some further
window (minutes to hours) so a human has a chance to see the row as `failed` before it
disappears, and so a herdr blip that briefly stops listing a genuinely-alive-but-confused
pane (not currently possible per the fail-closed design above, but as a belt-and-suspenders
measure) has more time to self-correct.
- Changes: a new timestamp/column (mirroring `absent_since`) plus the same `cleanup()` call
  as (a), on a longer clock.
- Costs: one more grace-window constant to size and justify, in a file that already visibly
  agonizes over getting these right (see `status.py`'s multi-paragraph justifications for
  every existing one).
- Risks: same worktree-deletion risk as (a), just deferred rather than removed.
- Size: small-to-medium — mostly the discipline of sizing and testing the new window.

**(c) Leave the store alone; only make the *board* stop showing it, harder than today.**
`archived` + `show_archived=false` already does most of this. If the complaint is really
"I still see it," the smallest change is making the fold happen even earlier/more
aggressively, or defaulting `sb status` (not just `sb board`) to fully drop archived rows
rather than footnoting them — a pure display change, no state or pane touched.
- Changes: tune `SPAWN_GRACE`/the archive threshold, or change a default flag.
- Costs: essentially none.
- Risks: essentially none — nothing is deleted, `sb cleanup` is still needed eventually to
  actually free the pane/tab, so this only defers the manual step, doesn't remove it.
- Size: smallest of the four.

**(d) Leave clearing manual, but make it one keystroke on the board.**
Add a key binding in the `sb board` TUI (alongside the existing `a` toggle) that runs
`cleanup()` on the row under the cursor (or on all currently-visible GONE/failed rows).
- Changes: one new key handler in `board.py`, calling the existing `Broker.cleanup()` —
  no new logic, reuses every gate as-is.
- Costs: none beyond the UI surface.
- Risks: same as manual `sb cleanup` today, i.e. none beyond what already exists — a human
  is still the one deciding to press the key, so the worktree-deletion risk in (a)/(b)
  stays exactly as deliberate as it is now.
- Size: smallest of the options that actually addresses "why do I have to type a command
  for this" — it removes the *keystrokes*, not the *human-in-the-loop*.

## 6. Recommendation

**(d)**, possibly combined with tightening **(c)**'s display defaults.

The one reason that decides it: **the thing standing between "gone" and "cleaned up" is not
missing automation, it's an irreversible action** (worktree deletion) sitting behind a step
the code has already gone out of its way to make re-verify itself before firing
(`_end_still_holds`). Everywhere else in this file, the design's answer to "should we act on
an inference automatically" is "no — surface it, let something with judgment decide" (C9).
Automating past that for *this specific* inference (options a/b) is the one place that
principle would be broken, for a convenience whose entire cost is "Andrew has to type six
characters." A keystroke on the board removes the friction Andrew is actually describing
without asking the system to make an irreversible call on a guess.
