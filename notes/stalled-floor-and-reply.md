# The floor under STALLED, and the excuse for an agent waiting on a reply

The fix for what `notes/stalled-vs-idle-finding.md` found. Andrew chose two of the three
options that note left open — the idle-duration floor (2) and a fourth excuse (3) — and
explicitly not reconciler-first (1). **The reconciler is untouched**: it still pings exactly
the stalled set, and the only thing that changed is which rows are in it.

## What was wrong

`stalled` was the idle flag, computed on the same tick, minus three excuses, with no
duration term in it anywhere. The `Stop` hook writes `turn='idle'` at the end of every
turn, so an ordinary worker was STALLED at **zero seconds** — pinged by the reconciler and
put in front of Andrew in the instant it stopped speaking. The sharpest case is the agent
that runs `sb tell --needs-reply` and ends its turn to wait, which is exactly what the
protocol tells it to do.

## What shipped

Both halves are `idle_excuse` values, not new terms, so `stalled` stays exactly "idle and
no excuse" and the row still says which:

- **`timeouts.stalled_floor` = 3 s.** Idle for less than that is `just finished a turn`.
- **`waiting on a reply`.** A `needs_reply` message from this agent with nothing back from
  its recipient since. Bounded by the recipient still being open (`ended_at IS NULL`) and
  the question still being deliverable (`undeliverable_at IS NULL`), and by nothing else —
  an unanswered question is an open item on the RECIPIENT's row, where unread mail is its
  own NEEDS YOU condition, so the fleet still surfaces it at the row that can act on it.

## The number that matters: end-to-end latency to a real stall

PR #66's debounce (`display.needs_settle`, 30 s) and this floor are **consecutive on a
board and nowhere else**, because the debounce times a summons from the tick the row first
becomes an inferred summons:

| reader | before | now |
|---|---|---|
| the board (collector behind it) | ~30 s | **~33 s** |
| the reconciler's ping | 0 s | 3 s |
| `sb status --needs-me`, `--json`, DRIFT | 0 s | 3 s |

Measured, not reasoned: driving the real `collect` + `stamp_needs_for` + `board.wants_you`
over a live clone row printed `stalled at t+3s; board summons at t+33s`.

They are not two debounces stacked. `defaults/settings.toml` says of `needs_settle` that
"nothing that ACTS on a stall — the reconciler, `--needs-me`, DRIFT — is debounced by
this"; those paths had **no** floor under them at all, and three seconds is what they now
have. Seeding the debounce from when the silence began, so the two overlapped at 30 s, was
considered and not done: `stamp_needs_for` times what the collector CONTINUOUSLY OBSERVED,
and three seconds is cheaper than giving that clock a second, inferred way to start.

**AWAITING KEYPRESS (PR #72) is not regressed.** Its probe gate is
`stalled and alive is True and idle >= NEEDS_SETTLE` — 30 s, which subsumes a 3 s floor
entirely, so no row reaches that code any later than it did.

## What the floor does NOT cover, and why that is right

`idle` is time since the agent last *did* something (`_last_activity`: its own `sb` calls
and the mail it sent or read), not time since its turn ended — the turn edges are logged
with `target=` rather than `agent=`, so they deliberately do not touch that clock. So an
agent that works silently for three minutes and then ends its turn is stalled at once: it
really has been quiet for three minutes, and the row says so. The floor bites exactly where
the eager stall was wrong — the agent whose LAST act was an `sb` call and whose turn ended
straight after, which is the `--needs-reply` case and every turn gap around mail.

One shape left as it is: an agent that asks the HUMAN with `--needs-reply` gets no excuse,
because the excuse joins to an agent row. A question aimed at a person should reach that
person, and `sb block` is the verb for it (a blocked row is not stalled either way).

## Live proof — isolated clone, real agents

`git clone` of this repo at `<scratchpad>/floorclone`, driven only by its own `./bin/sb`,
its own store, its own herdr workspace. Three real Claude agents: `floorlead` (dispatcher),
`worker-1`, and `asker` (a worker under `floorlead`). All closed, both worktrees retired,
`herdr agent list` and `herdr workspace list` show nothing of it, `~/.herdr/worktrees/`
is clean. The one poller process was killed by pid.

1. **A `--needs-reply` agent is not called stalled.** `asker` ran
   `sb tell parent "which branch should I use?" --needs-reply` and ended its turn as
   instructed. Sampled twice a second for the next four minutes through the clone's own
   `sb status --json`:

   ```
   asker turn=idle idle=8   stalled=False excuse=waiting on a reply
   asker turn=idle idle=130 stalled=False excuse=waiting on a reply needs_human=False
   asker turn=idle idle=901 stalled=False excuse=waiting on a reply
   ```

   On `main` that row is STALLED at `idle=0` and in NEEDS YOU.

2. **A real stall still arrives.** `floorlead` answered with `sb tell asker "main"`
   (message id 5 in the clone's store). The excuse ended with the answer and the row was
   stalled from `idle=3` onward, `needs_human=True`, drawn as `STALLED — idle 40s`.

3. **A short turn gap does not summon.** The floor's boundary, on that same live row with
   a real herdr, varying only `now`:

   ```
   idle= 0s  stalled=False needs_human=False excuse=just finished a turn
   idle= 1s  stalled=False needs_human=False excuse=just finished a turn
   idle= 2s  stalled=False needs_human=False excuse=just finished a turn
   idle= 3s  stalled=True  needs_human=True  excuse=None
   ```

   The sub-3 s window is too short for a 2.5 s `sb status` subprocess to land in reliably,
   which is why it is measured this way rather than by luck; everything in it — store,
   herdr, `collect` — is real.

## Tests

Full suite green with `/Users/andrew/anaconda3/bin/python -m pytest tests`. Four new tests
in `tests/test_status.py`, and each of the two new clauses was deleted in the clone to
confirm the tests fail without it (`test_a_turn_that_just_ended_is_not_a_stall_yet` without
the floor, `test_an_agent_waiting_on_a_reply_it_asked_for_is_not_stalled` without the
excuse).

Existing tests that built a fleet in the current second and expected a stall now say so
with `now` moved past the floor (`StatusTest.past_the_floor`, and the same in
`test_broker.py` / `test_inspect.py`) — the assertions are unchanged, only the clock.

## The fixture that lied

`tests/test_richboard.py`'s idle-with-a-working-descendant case built `lead` stalled above
a still-running `mid`, which `collect` cannot produce: `live_parent` excuses any parent
whose direct child is open. It now uses the shape that really produces it — `mid` reported
`done` while a grandchild of its own kept going, the legal case the finding names.

**Two more fixtures in that same class are unproducible for the same reason** and were left
alone rather than rewritten inside another PR's tests:
`test_a_blocked_grandchild_hides_the_idle_top_and_is_itself_listed` and
`test_a_descendants_turn_gap_does_not_summon_its_ancestors` both mark an intermediate row
`stalled=True` while its own child is running. Reported, not fixed.
