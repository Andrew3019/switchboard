# Why the top orchestrator's mail was held for a day

Diagnosed and fixed 2026-08-12 on branch `held-mail`. The symptom was `main-7` — this
session's top orchestrator — showing `<< UNDELIVERED 1` for hours while sitting at its
prompt, its children's reports arriving only when it happened to run `sb inbox` itself.
`DESIGN-TRUTH.md:66-67` and 220-224 make that the one case the design rules out: the top is
idle and should be *woken* rather than monitoring.

## The cause, in one sentence

`Broker._revive` stamped `agents.turn = 'working'` on `main-7` — a session with no activity
hooks, so nothing in the fleet could ever write the matching `idle` — and `Broker._busy`
believed it forever.

## The trace, from the live store

`main-7` was created `2026-08-11 01:59`, before the activity signal existed (PR merged
`18:47` the same day). Its session therefore carries neither hook, and the store says so
directly: **zero `turn_start` and zero `turn_end` events for it, ever**, across 44 hours and
hundreds of turns. Every other row in the store that holds a `turn` has them.

```
08-11 18:47:34  message 500  delivered_at set        the last message that ever reached it
08-11 18:49:44  event  done        agent=main-7      it reported
08-11 18:58:31  event  revived     agent=main-7      it ran another `sb` command
08-11 19:08:42  event  ring_deferred agent=main-7    message 502, delivered_at NULL
08-11 19:11:39  ... 19:13:04 ... 19:35:29 ... 19:46:59 ... 20:11:58 ... 20:52:02
08-12 21:11:44  event  ring_deferred agent=main-7    message 516, delivered_at NULL
```

Nine messages, none announced. `read_at` is set on some of them at `08-12 19:51` and
`21:24` — all in one batch, and only because the agent ran `sb inbox` of its own accord.

The `revived` event at `18:58:31` is the whole of it. `_revive`'s write was:

```sql
UPDATE agents SET ended_at=NULL, state='working', turn='working' WHERE name=?
```

and its comment named the case it was for: *"corroboration for the one case
[`UserPromptSubmit`] cannot cover, a row revived by an `sb` call in a session that started
before this settings file carried the hook."* That session is exactly the one with no `Stop`
hook either. The write is unclosable by construction.

At the moment of diagnosis, of 21 rows in the live store holding a non-NULL `turn`,
**exactly one had no hook edge behind it: `main-7`.**

## Why nothing repaired it

The three things that could have moved the row all read False, and each for its own reason:

- `stalled` — `status.display_state` reads our signal first, so the row displays `working`
  and is never stalled. No reconciler ping.
- `signal_drift` — needs `herdr_state == UNKNOWN`; herdr sees a healthy Claude and answers
  `idle` or `working`.
- `turn_doubted` → `_forget_turn` — the designed repair for a stale `working` edge, and the
  right mechanism, but its clock never matured here. It needs `idle >= 30 min` *and* herdr
  reading idle-like continuously for 15 min after that. Two things defeat it on a top
  orchestrator: herdr's detector is intermittent and does report that pane `working` (it
  did during this diagnosis), and — the sharper one — `_ring` logs `ring_deferred` with
  `agent=<recipient>`, which `status._last_activity` counts as the recipient's own
  activity. So **every held message resets the staleness clock of the agent it is held
  for**. On a busy fleet mail arrives more often than every 30 minutes and the window never
  opens. `_last_activity`'s own docstring states the rule this breaks: "Mail *arriving* is
  pointedly not activity — that is somebody else acting, and counting it would reset the
  idle clock on exactly the silent agent you are trying to spot."

That last point is reported, not fixed: it is a separate defect in a separate mechanism,
and with the cause below removed nothing depends on the repair for this case.

## The fix, and why it is in the signal

**The rule: only the hooks write `agents.turn`.** A non-NULL value now means "a hook
belonging to this session recorded an edge"; NULL means "no signal, ask herdr", which is
what every consumer already does with it (`status.collect`'s `turn_over`, `display_state`,
`Broker._busy`).

1. `Broker._revive` no longer writes `turn`. An `sb` command proves a turn *started*;
   nothing in that process can promise the *end* will be recorded, because the end is the
   `Stop` hook's to write and the hook belongs to the agent's session. For a session that
   carries the hooks there was nothing to corroborate anyway — `UserPromptSubmit` fires
   when the prompt is submitted, before the agent can run any command, so `turn` already
   says `working` by the time `_revive` runs.
2. `store._repair_unhooked_turn` restores that invariant once, for the rows the old writer
   wedged. A wedged `working` and a live one are the same string, so they are told apart by
   history: `hooks.mark_turn` logs a `turn_start`/`turn_end` event beside every write it
   makes, and a row with a `turn` and no such event is a row no hook ever wrote. It writes
   NULL, recorded in `meta` the way a backfill is so it runs once per store.

**Not the fallback.** The fallback was never reached: `_busy` falls back to herdr only when
`turn` is NULL, and the bug is that `turn` was not NULL. Widening the fallback would mean
distrusting a signal that is correct everywhere else.

**Not the delivery path.** Making `_busy` discount a `working` edge would re-break
hold-until-free for genuinely working agents, which is the whole thing the activity signal
was built to fix (`audit/activity-signal.md` §3).

**And not a restart of `main-7`.** The class — a long-lived agent alive across a change that
adds a hook — recurs on every future hook. What makes that class safe is that a hookless
row's `turn` stays NULL and the row behaves exactly as the whole fleet did before the signal
existed. That is what removing the write buys; the repair only cleans up after the writer
that already ran.

## Live proof

One isolated `git clone` of this repo in the session scratchpad, driven only through **that
clone's own `./bin/sb`**, real herdr and real Claude Code. The construction is a session
whose hooks write nothing — `bin/sb-activity-hook` and `bin/sb-stop-hook` replaced by stubs
that read stdin and exit 0 — which is behaviourally what a session spawned before the hooks
existed has: no turn edge is ever recorded for it. Nothing in `broker.py`, `store.py` or
`status.py` was touched for the proof.

Both agents were given one task: `sb done "reported"`, then `sb status`, then stop. That is
the wedging sequence — report, then run one more command — and nothing more.

### The wedge, on `main`

`wedged`'s events: `fork, sb_pinned, delegate, board_open, done, revived`. No turn edge of
any kind. After `revived`, the store reads `state=working, turn='working', ended_at=None`.

```
$ ./bin/sb tell wedged "held mail: does this ever arrive?" --when-idle
sent to wedged (wedged mid-turn or blocked — will be rung when free)

wedged  worker  working   done        1      1m     21s  wedged     << UNDELIVERED 1, 21s
wedged  worker  working   done        1      2m     41s  wedged     << UNDELIVERED 1, 41s
wedged  worker  working   done        1      2m      1m  wedged     << UNDELIVERED 1, 1m
wedged  worker  working   done        1      2m      1m  wedged     << UNDELIVERED 1, 1m
wedged  worker  working   done        1      3m      1m  wedged     << UNDELIVERED 1, 1m
wedged  worker  working   done        1      3m      2m  wedged     << UNDELIVERED 1, 2m
```

Six flushes over two minutes, the agent sitting at its prompt the whole time (herdr's own
column says so), the row saying `working` because of one write nothing can undo.

### The same row, repairing

`git checkout held-mail` in that clone, hooks re-stubbed, and **one** `sb status`:

```
before:  {'name': 'wedged', 'state': 'working', 'turn': 'working'}
         message: delivered_at None, read_at None

$ ./bin/sb status
wedged  worker  idle      done        1      3m      2m  wedged     << STALLED

after:   {'name': 'wedged', 'state': 'working', 'turn': None}
         message: delivered_at 1786596373, read_at 1786596378
         herdr: agent prompt wedged [sb: from human] You have mail. Run: sb inbox
```

The edge dropped, the doorbell rang in the same command, and the agent read the message five
seconds later. The row is `STALLED` afterwards, which is correct and is the point: with the
edge gone it is reachable by the reconciler and by `sb cleanup` again too.

### The wedge never forming

A second agent, `fresh`, spawned on the fixed branch and given the identical task:

```
events: fork, sb_pinned, delegate, board_open, done, revived
store:  {'name': 'fresh', 'state': 'working', 'turn': None, 'ended_at': None}

$ ./bin/sb tell fresh "held mail: does this ever arrive?" --when-idle
sent to fresh                      <- not "will be rung when free"
        message: delivered_at 1786596414, read_at 1786596418
```

`revived` with `turn` still NULL, and the when-idle mail delivered on the spot rather than
held.

Both agents were closed with `sb cleanup --force`, both herdr workspaces closed, and the
clone's own collector was closed by pid after checking its cwd was inside the clone. No
unscoped `pkill`.

## What this does NOT prove

- **`main-7` itself is not fixed by this branch until the branch is on `main`.** The repair
  runs the first time any command touches the live store from a checkout carrying it. It was
  deliberately not run against the live store from this worktree.
- **The `ring_deferred` idle-clock reset is reported, not fixed** (see above). It is why the
  designed repair could not rescue this row, and it will still weaken `turn_doubted` for any
  agent with a queue.
- **The proof's hookless session is constructed by stubbing the hook entry points**, not by
  finding a session older than the settings file. The observable that matters is identical —
  no turn edge is ever recorded — but it is a construction.
- **Compaction and `--resume`** are untouched by this and remain as
  `audit/activity-signal.md` left them.
