# Phase 1 scope — pass/fail tests and a file-conflict map

Read-only pass over BUILD-PLAN.md items 1.1, 1.3–1.9 (1.2 is being verified separately —
left alone here). Checked against the actual code, not the plan's evidence, which was
true when written. `DESIGN-TRUTH.md` is the only trusted source of intent; everything
else (comments, `audit/2026-08-09/*.md`) was cross-checked, never taken on faith.

**Code state**: `switchboard/`, `bin/`, `defaults/` are byte-identical between this branch
and the commit the `2026-08-09` audit ran against (`git diff caa6d20 HEAD -- switchboard/
bin/ defaults/` is empty). So that audit's file:line citations are still accurate today,
and I've used them as a head start, verifying each one against the current file rather
than trusting the write-up.

**Verdict on all eight: all real.** Nothing here is already fixed on main, and nothing
turned out to be working as designed. One (1.5) is narrower than the plan's evidence
suggests, and two (1.3, 1.6) are bigger than "fix a function" — see sizing below.

---

## 1.1 — Spawn delivery must arrive and be submitted, or fail loudly

**What happens today.** `Broker.delegate` starts the agent through
`Herdr.start_agent` (`switchboard/herdr.py:382-455`), which *does* retry with backoff and
raises loudly on failure — that half is solid. But the agent's actual first task is sent
separately, one line before `delegate` returns:

```
switchboard/broker.py:2646   self.h.prompt(name, task)
```

`Herdr.prompt` (`switchboard/herdr.py:457-471`) is a single `agent prompt` call with **no
retry, no verification, and an explicit warning in its own docstring**: "Its return value
reflects state BEFORE the prompt lands, so never infer 'it started' from it." Nothing
reads the return value anyway. If this call silently no-ops, pastes without submitting,
or never reaches the pane, `delegate` still returns the agent's name as success. This is
exactly hazard #1's two failure modes.

**Pass/fail test.** Spawn an agent, then within a couple seconds check its transcript (or
`sb inspect <name>`) for the task text having actually landed as a submitted turn. Today:
this can silently fail with `sb delegate` printing success. Fixed: either the call
verifies delivery (e.g. polls for a state change or a session id appearing) and retries,
or it raises and the agent is left in a state that says "spawned, task not delivered"
rather than a bare success.

**Files/functions:** `switchboard/broker.py` `Broker.delegate` (~2479-2647, specifically
the final `self.h.prompt(name, task)` at 2646); `switchboard/herdr.py` `Herdr.prompt`
(457-471), possibly `Herdr.start_agent` (382-455) if the fix folds task delivery into the
same retry loop instead of a bare `agent prompt` call.

**Size:** small-to-medium. The shape of the fix (verify-then-retry) is well understood;
the work is deciding what "verified" means against herdr's API and wiring it in.

---

## 1.3 — Doorbell: mail to an idle agent must be announced; parent woken on child report

**What happens today.** Confirmed exactly as evidenced: `flush_pending`
(`switchboard/broker.py:3304-3352`) has exactly two callers —
`switchboard/cli.py:585` (start of every `sb` command) and `switchboard/broker.py:2791`
(inside `ask`'s poll loop, which is itself slated for removal in phase 3). Its own
docstring says so: "This is the stand-in for an events daemon."

`Broker.done` (`broker.py:2830-2869`) does ring the parent immediately, at line 2868 —
*if* the parent is idle at that exact moment. If the parent is mid-turn, `_ring`
(`broker.py:3386-3438`) defers via the `_busy` check at 3426-3428, and the deferred
message only gets re-rung by `flush_pending` — which nothing calls unless some other `sb`
command happens to run. A top orchestrator that goes idle after its last child reports
is never woken; it has to poll, which is the exact failure hazard #2 describes and which
the plan's own workaround (`sb status` every 20s) is a heartbeat standing in for.

**Pass/fail test.** Have agent A go idle. Have agent B message A (or complete `sb done`
to a parent A) while A is mid-turn, then let A finish its turn with no other `sb` command
running anywhere in the fleet. Fixed: A gets rung within a bounded time of going idle,
with nothing else touching `sb`. Today: A sits rung-less indefinitely.

**Files/functions:** `switchboard/broker.py` `Broker.flush_pending` (3304-3352),
`Broker._ring` (3386-3438), `Broker.done` (2830-2869, the ring at 2868). The actual fix
needs a new trigger — something that calls `flush_pending` on a timer or on a herdr state
transition, independent of another `sb` invocation. Candidate homes: `board.py`'s own
loop (already polls), or a small daemon. No current file owns this.

**Size:** needs its own breakdown. This isn't a function-level fix — it's "build the
autonomous trigger that doesn't exist yet," and it overlaps hard with phase 3's
reconciler (3.5, which needs the same kind of loop) and delivery modes (3.1, which
changes what `_ring`/`flush_pending` even mean). Recommend scoping phase 1's slice as:
land a *minimal* trigger (even a dumb poll loop calling `flush_pending`) so `done`/`tell`
reach an idle target without a heartbeat, and leave the richer reconciler behavior to
phase 3.

---

## 1.4 — `sb cleanup` must never silently do nothing

**What happens today.** Reproducible exactly as the plan states. `Broker.cleanup`
(`switchboard/broker.py:2914-3070ish`) has several silent `continue`s when a *named*
agent is refused and not force-closed:

- `broker.py:3002-3003` — state not in `FINISHED` (e.g. blocked, or still working):
  silent `continue`, no log line, no reason surfaced.
- `broker.py:3006-3015` — unread mail still holds the row: silent `continue`.
- `broker.py:3018-3019` — role's `cleanup != "close"` and not `include_kept`/named:
  silent `continue`.

Only the live-descendants gate (`held`, ~2978-3000) logs a `cleanup_held` event; none of
the others do. `cli.py:866-871` then prints `closed: (nothing)` with zero indication of
which gate fired.

**Pass/fail test.** `sb cleanup <name>` against a blocked agent (or one with unread mail,
or a `cleanup!=close` role) with no `--force`. Today: `closed: (nothing)`. Fixed: the
output names the reason — e.g. `refused <name>: blocked` / `refused <name>: unread mail`
— for every gate, not just the live-children one.

**Files/functions:** `switchboard/broker.py` `Broker.cleanup` (2914-3070ish, specifically
each `continue` in the per-candidate loop ~2990-3021); `switchboard/cli.py` the `cleanup`
dispatch branch (866-871) to print the reasons `cleanup` now returns.

**Size:** small. Same shape as the existing `cleanup_held` handling — extend it to the
other three gates and thread the reason through to the CLI's output.

---

## 1.5 — An interrupted turn leaves an agent recorded working forever

**What happens today.** `status.py` already computes exactly this condition —
`stalled = running and alive and herdr-idle and not awaiting_task`
(`switchboard/status.py:466`, `IDLE_LIKE` check) — meaning: the store still says
`working`, but herdr says the pane is actually idle (the turn ended, one way or another,
without the agent calling `sb done`/`sb block`). Nothing ever *writes* a correction for
this case: `collector.py` runs the only continuous loop and is deliberately read-only
(`reap=False`, `collector.py:13,112`), so detection exists but nothing acts on it. The
row stays `working` until the agent itself runs another `sb` command — which an
externally-interrupted agent may never do again.

**Note on scope, flagged rather than assumed:** this is the *same* underlying gap as
phase 3.5's reconciler (an idle-but-not-done/blocked agent needs a nudge), just entered
from a different bug report. I'm not duplicating it as a second full build — see grouping
below.

**Pass/fail test.** Interrupt an agent's turn externally (kill its process, or otherwise
end the turn without `sb done`/`sb block`). Run `sb status` repeatedly with no other `sb`
traffic. Today: the row stays `working` forever, `stalled: true` in the JSON but nothing
downstream acts on it or even makes it visually distinct from a genuinely busy agent in
`sb status`'s default view. Fixed (minimum bar for phase 1, short of the full
reconciler): the row is at least corrected to a state that lets `sb cleanup` or a human
act on it, or is surfaced clearly enough that "stalled 16 hours" isn't buried in `sb
status --json` only.

**Files/functions:** `switchboard/status.py` (stalled detection, ~426-466, already
correct — likely just needs its result surfaced more prominently) and whichever module
ends up owning the write-back (`collector.py`, or the same trigger built for 1.3).

**Size:** small if scoped to "surface `stalled` more visibly and let cleanup/humans act
on it"; folds into 1.3's "needs its own breakdown" if scoped to "auto-correct the state."
Recommend the narrow scope for phase 1, and let phase 3.5 do the auto-nudge.

---

## 1.6 — Agent name binding lost while alive, permanently unreachable

**What happens today.** This is a herdr-level limitation, documented in switchboard's
own code as a known dead end:

```
switchboard/herdr.py:476-480 (Herdr.prompt_pane docstring)
  "herdr can lose an agent's name binding permanently (once it has seen the agent
   leave the foreground, ... agent prompt and even a pane-targeted agent prompt
   answer agent_not_found / agent_not_ready, and no later report re-registers it)"
```

The one workaround that used to exist (`pane run` typing directly into the pane) was
removed as a genuine shell-injection vulnerability (backtick/`$(` in agent-authored text
executing in the pane) — see the same docstring. So today, once this happens, there is
**no recovery path at all**: `Broker._ring` (`broker.py:3386-3438`) just fails via
`ring_failed`/`Undeliverable`, and nothing distinguishes "lost binding, pane still alive
with real work in it" from "agent is actually gone" in `_finished_and_unreachable`
(`broker.py:3269-3294`) or `_agent_states` (~3230-3245).

**Pass/fail test.** Trigger the binding loss (cause the agent to leave herdr's tracked
foreground — e.g. running a nested shell command in its pane, per the docstring's
trigger condition), then `sb tell` it. Today: silent/logged failure, agent effectively
orphaned with live work in its pane and no path back in except a human manually
intervening in the pane. Fixed: at minimum, this state is detected and surfaced
distinctly (not conflated with "gone"), so a human or the reconciler knows to go look at
the pane directly rather than the doorbell silently failing forever.

**Files/functions:** `switchboard/broker.py` `Broker._ring` (3386-3438),
`Broker._finished_and_unreachable` (3269-3294), `Broker._agent_states` (~3230-3245);
`switchboard/herdr.py` `Herdr.prompt`/`Herdr.prompt_pane` (457-489).

**Size:** needs its own breakdown. The root cause lives in herdr (a separate binary, not
in this repo) — switchboard can only detect-and-surface, not truly fix the binding loss.
Scoping this to "detect the distinct failure mode and expose it" (not "prevent it") is
the realistic phase-1 slice; anything more needs to go through herdr itself, which is out
of this repo's control.

---

## 1.7 — Failed worktree fork swallowed; `sb start` inside a worktree doesn't refuse

**What happens today — two distinct sub-bugs, confirmed live in current code:**

1. **Fork failure swallowed.** `Broker._fork_for` (`broker.py:2433-2463`) catches
   `HerdrError`, logs `fork_failed`, and returns `None` (2455-2458). `Broker.delegate`
   (2479-2647) only checks `if forked:` (2533) — when it's `None`, `where` falls through
   to the parent's own cwd (2541-2546), which for a top orchestrator is the human's main
   checkout. The parent is never told; only an event-log row exists.
2. **`sb start` doesn't refuse inside a worktree.** `Broker._top` (`broker.py:514-596`)
   calls `self.h.create_workspace(name, cwd=str(self.repo))` at line 571, where
   `self.repo` is `store.worktree_root()` (set in `cli.py:576`, explicitly "THIS
   worktree, not the main checkout"). Nothing compares this against
   `store.main_checkout()` (`store.py:122-129`) and refuses. `sb start` typed inside any
   worktree silently lays a new top orchestrator's bare space over that worktree's
   checkout.

**Pass/fail test (fork swallow):** Force a fork failure (e.g. a branch-name collision via
`BranchTaken`, or simulate a herdr `worktree create` failure) during `sb delegate`. Today:
the child spawns anyway, silently sharing the parent's checkout, with only a `fork_failed`
event row. Fixed: the parent is told (a message, not just a log line) and/or the spawn is
refused outright rather than silently degrading.

**Pass/fail test (start in worktree):** Run `sb start` from inside any worktree checkout.
Today: succeeds, using that worktree's directory as the new top's cwd. Fixed: refuses,
naming the main checkout to run it from instead (per DESIGN-TRUTH:49-51).

**Files/functions:** `switchboard/broker.py` `Broker._fork_for` (2433-2463),
`Broker.delegate` (2479-2647, specifically 2530-2539 where `forked` is handled),
`Broker._top`/`Broker.start` (475-596); `switchboard/cli.py` `start` dispatch (342, 705).

**Size:** small-to-medium each; two independent sub-fixes in the same function
neighborhood (`delegate`/`_top`), so worth doing together rather than as two separate
PRs that would conflict with each other anyway.

---

## 1.8 — `sb restore` after worktree deletion reports success, opens in `$HOME`

**What happens today.** `Broker.restore` (`broker.py:3122-3182`) resolves the pane's cwd
at line 3156: `ws.get("path") or a["cwd"] or str(self.repo)`, with **no check that this
path still exists on disk**, then calls `_tab_for` (`broker.py:2340`) with it. Herdr
silently substitutes `$HOME` for a missing `--cwd` (confirmed live in the prior audit:
`herdr tab create --cwd /nonexistent/...` → `"cwd":"/Users/andrew"`). `restore` then sets
`state='working'` (3178-3180) and returns success (`cli.py:894` prints `restored
<name>`) — with the agent now sitting in the human's home directory with none of its
context, silently.

**Pass/fail test.** Delete a worktree out from under a closed agent, then `sb restore
<name>`. Today: prints `restored <name>`, agent lands in `$HOME`. Fixed: refuses with a
message naming the branch the work is still on (per DESIGN-TRUTH:272-274, "the push is
the recovery path for the work, not restore").

**Files/functions:** `switchboard/broker.py` `Broker.restore` (3122-3182, specifically
the cwd resolution at 3156, before the `_tab_for` call). Scoped narrowly — add an
existence check in `restore` itself — this does **not** need to touch `_tab_for`
(2340), which is also called from `delegate` (2569) and another spawn path (2109); a
broader fix that hardens `_tab_for` itself against herdr's `$HOME` substitution would
create overlap with 1.1/1.7's work in `delegate`, so it's better left out of phase 1.

**Size:** small, if scoped to `restore` only as above.

---

## 1.9 — Blocking pushes IDLE; a sibling's ordinary mail clears the block

**What happens today.** Confirmed exactly, and already independently verified twice in
the prior audit (`audit/2026-08-09/CONSOLIDATED.md`). `Broker.block`
(`broker.py:2871-2904`) pushes herdr state `IDLE` at line 2902 (deliberately, per its own
comment — herdr un-targets a `blocked` agent otherwise). But `Broker._ring`
(`broker.py:3386-3438`) calls `self._unblock_if_needed(who)` **unconditionally** at line
3429, before *every* delivery — mail, `done` notifications, anything. `_unblock_if_needed`
(3440-3462) then flips the agent from `blocked` back to `working` in both herdr and the
store. So any sibling's unrelated `tell`, or a child's `done`, silently cancels a block
and drops the agent out of `sb status --needs-me` — burying Andrew's eventual answer
under it.

**Pass/fail test.** Block agent A. Have unrelated agent B send A ordinary mail (not
Andrew answering the block). Today: A's state flips to `working`, drops off `sb status
--needs-me`, and receives B's message as if nothing happened. Fixed: A stays `blocked`
and B's mail is held until the block is answered (per DESIGN-TRUTH ~244-245); only
Andrew's actual reply through the pane clears it.

**Files/functions:** `switchboard/broker.py` `Broker._ring` (3386-3438, specifically the
unconditional `_unblock_if_needed` call at 3429), `Broker._unblock_if_needed`
(3440-3462), `Broker.block` (2871-2904), `Broker._busy` (3296-3302, since `block`'s
`IDLE` push is what makes `_busy` treat a blocked agent as available in the first place).

**Size:** small-to-medium — the fix has to distinguish "this ring is Andrew's actual
reply to the block" from "this ring is unrelated mail," which likely needs a real
`blocked` herdr state (if herdr's targeting restriction can be worked around) or a
same-conversation/session check rather than a blanket unblock-on-any-ring.

---

## Grouping — what can run in parallel, what must be sequenced

**Shared-region map** (the actual overlap, by function):

| Function/region | Touched by |
|---|---|
| `Broker.delegate` (broker.py 2479-2647) | 1.1 (line 2646), 1.7 (lines 2530-2539) |
| `Broker._fork_for` / `Broker._top` (2433-2463, 514-596) | 1.7 only |
| `Broker._ring` (3386-3438) | 1.3, 1.6, 1.9 |
| `Broker._unblock_if_needed` / `Broker._busy` | 1.9 only |
| `Broker.flush_pending` / `Broker.done` | 1.3 only |
| `Broker.cleanup` (2914-3070ish) | 1.4 only |
| `Broker.restore` (3122-3182) | 1.8 only |
| `status.py` stalled detection | 1.5 only (read-mostly; low collision risk) |
| `Herdr.prompt` / `Herdr.start_agent` (herdr.py) | 1.1, 1.6 (read/detection only for 1.6) |

**Sequencing forced by overlap:**

- **1.1 and 1.7 must be serialized** — both edit `Broker.delegate`, in nearby but
  distinct regions (2646 vs. 2530-2539). Low conflict risk if done as sequential small
  diffs, but running them as simultaneous agents on the same function is asking for a
  merge fight.
- **1.3, 1.6, and 1.9 all touch `Broker._ring`** — 1.9's fix in particular (stop
  unconditional unblock) sits right next to where 1.3 would add richer delivery-mode
  logic and where 1.6 would add failure-mode detection. Do **1.9 first, alone** (it's the
  most urgent — Andrew's answers being buried — and the smallest, most surgical change to
  `_ring`). Then 1.3 and 1.6 can either be sequenced after it or, if scoped so one only
  reads `_ring`'s surroundings (1.6's detection) while the other adds the external
  trigger (1.3's daemon, which barely touches `_ring` itself), they can proceed in
  parallel with careful review — but if both end up editing `_ring`'s body, serialize
  them too.

**Safe to build fully in parallel** (no shared file region with anything else in this
list):

- **1.4** (`Broker.cleanup` + `cli.py` cleanup branch) — isolated.
- **1.5**, scoped narrowly to surfacing `stalled` (status.py, mostly read/display) —
  isolated, *unless* it's scoped to auto-correction, in which case it likely needs
  whatever trigger 1.3 builds and should wait on that.
- **1.8** (`Broker.restore`, scoped to the cwd-existence check only, not `_tab_for`) —
  isolated, as long as nobody "improves" `_tab_for` itself in the same pass.

**Recommended parallel sets:**

- **Set A (fully parallel, start immediately):** 1.4, 1.8, and 1.5-narrow.
- **Set B (sequenced pair):** 1.7 → 1.1 (or 1.1 → 1.7; either order, just not
  simultaneous) — both in `delegate`.
- **Set C (sequenced, start with the smallest/most urgent):** 1.9 alone first, then 1.6
  (detection-only scope) and 1.3 (external trigger, "needs its own breakdown") — treat
  1.3 as a mini-project of its own rather than a same-size peer of the others; it's the
  one item here big enough to warrant a dedicated lead rather than a single agent.

Sets A, B, and C have no file overlap with each other and can run concurrently.

---

## Nothing here is already fixed on main or a non-problem

All eight items reproduce against current code (`switchboard/`, `bin/`, `defaults/`
byte-identical to the commit the underlying audit ran against). None are stale claims —
the plan's evidence lines still point at real, current bugs. The one place I'd push back
on scope, not correctness: **1.3 and 1.5 overlap substantially with phase 3's reconciler
(3.5) and delivery modes (3.1/3.4)**, and building the "right" version of either inside
phase 1 risks re-doing the same work in phase 3. I scoped both narrowly above (a minimal
trigger, and surfacing rather than auto-correcting) specifically so phase 1 doesn't have
to solve phase 3's problem to close its own gap.
