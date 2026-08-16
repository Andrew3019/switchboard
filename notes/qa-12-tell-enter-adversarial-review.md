# Adversarial review of the confirm-and-repair fix — `b49caa9`, `1aa67ea`, `19f9541`

Review only, no production code touched. All live work below ran against an isolated
`git clone` at `<scratchpad>/qa-clone` on `tell-enter`, driving that clone's own
`switchboard` package directly (in-process, not through `./bin/sb` — no herdr workspace
was created, so there is nothing to tear down). The clone and the repro script are left in
the session scratchpad as evidence:
`<scratchpad>/race_confirm_rings.py`, `<scratchpad>/race_confirm_rings_4x.py`.

`/Users/andrew/anaconda3/bin/python -m pytest tests` in the clone: **1336 passed**, same
count the worker's note reports. Ran it myself; did not just trust the note.

---

## Verdict: not safe to land as-is. One real defect (proven live), one parameter that
contradicts the codebase's own cited evidence.

---

## 1. CONFIRMED LIVE: `_confirm_rings` has no cross-process guard, and the cap does not
hold under concurrency

This is exactly the thing the worker's note lists as unproven ("Two `sb` processes
reaching `_confirm_rings` in the same instant could each repair once. Bounded by the cap,
not otherwise guarded.") — it is worse than that phrasing suggests.

**The read and the write are not atomic, and nothing serializes them across processes.**
`_confirm_rings` (`broker.py:5356-5401`) reads a ring's state with `_last_ring` (one
`SELECT`, no transaction held open), does a `get_agent` `SELECT`, tails a transcript file,
and only THEN writes `ring_repaired` — a separate, later, independently-committed
`INSERT` (`store.log_event` commits immediately, `store.py:1708`). Nothing holds a lock
across that gap. The codebase already has a working pattern for exactly this shape of
problem — `Broker._fork_lock` (`broker.py:2572`), an `fcntl.flock` on a file under the
shared `.git` — and `_confirm_rings` does not use it or anything like it.

**Reproduced live.** Script: `<scratchpad>/race_confirm_rings.py`. Built a real file-backed
sqlite store (WAL, `busy_timeout`, same as production — via `store.connect()`), one agent
with an aged, unconfirmed `ring_sent` row (repairable, `tries=0`), and a fake herdr whose
`.prompt` just records calls. Two threads, each with its own `sqlite3` connection to the
same file (mirrors two separate `sb` processes), released at the same instant by a
`threading.Barrier`. `output.submitted_since` was patched to sleep 0.4s and return
`False` — widening the natural read-decide-write gap to make the race deterministic
rather than relying on lucky timing. That gap is real without the sleep too (`get_agent`
+ file stat/open/tail/parse); I widened it because that is standard practice for
demonstrating a timing-dependent race reliably, and because I/O contention under a loaded
machine — the exact condition this whole fix targets — naturally widens the same gap.

Result: **both threads sent a repair.** Both logged `ring_repaired {"attempt": 1, ...}` —
both computed the same stale `tries=0` before either commit landed, so both believed they
were the first repair. Re-ran with 4 concurrent threads instead of 2: **all 4 sent a
repair**, all logged `attempt: 1`.

```
=== herdr.prompt calls ===
('target', 'you have mail', ...)
('target', 'you have mail', ...)
('target', 'you have mail', ...)
('target', 'you have mail', ...)
total repair sends: 4  (RING_REPAIRS cap = 2)
```

**What this means concretely:** the intended cap of 2 repairs per stalled doorbell is not
a hard cap — it is a hard cap only for a single serialized stream of `sb` commands. Any N
processes that reach `_confirm_rings` for the same stalled ring inside the same race
window each send one repair, for up to N repairs, not 2. `flush_pending` runs at the head
of every `sb` command every agent runs, so in a busy fleet — again, the exact condition
that causes the original dropped-Enter bug — many agents can plausibly run a command
within milliseconds of each other. This is a resonance: the load that causes Enters to
drop is the same load that defeats the fix's own cap.

**Bounded, not runaway, but not what the commit message promises.** After a race like
this, the next `_last_ring` read will count all the `ring_repaired`/`ring_repair_failed`
rows actually in the log (my repro's DB had 4 `ring_repaired` rows after the 4-way run),
so the NEXT pass sees `tries >= RING_REPAIRS` and stops — it does not loop forever, and it
does not amplify without bound on subsequent passes. But it can produce an N-way pile of
duplicate doorbells in a single instant, where N is fleet contention, not a compile-time
constant — worse than the "capped at two" the commit message and the settings.toml
comment both describe. For a doorbell (no payload) this is noise, not corruption; it is
not free noise, though — `agent prompt` into a dirty box appends (worker's note, §2), so a
target could see several concatenated doorbells arrive as one prompt, and each repair
still risks the mid-turn-arrival cost the design note itself worries about at length.

**Not proven:** that this actually happens between two genuinely independent OS processes
(`sb` invocations) rather than two threads sharing a Python process, and not proven under
real herdr/pane conditions rather than a faked `.prompt`. I judge the OS-process case to
behave identically — the mechanism is purely about SQLite read/write ordering across
independent connections, which two threads with two connections already model correctly —
but I did not run it as two separate `sb` command-line invocations.

## 2. `ring_settle = 30.0` is set below the codebase's own cited worst case for the exact
lag it exists to outlast

`defaults/settings.toml:304-307`, the comment justifying `30.0`, says in the same breath:

> `deliver_working_ms` records 35 s for the same lag under a six-way fan-out. Thirty
> seconds clears the ordinary case of both.

30 does not clear 35. That 35 s figure is not a stray number — it is the exact same
mechanism `_confirm_rings`'s proof depends on: `herdr.py:799-801`'s `_took_prompt`
docstring says outright "Claude Code does not flush its transcript when the text is
submitted — under a six-way fan-out one was measured 35 s late, against a 20 s window."
`_confirm_rings`'s proof (`output.submitted_since`) is exactly a read of that same
transcript file. So the codebase has independent, already-documented evidence — cited in
the very comment that sets the number — that the flush lag this window has to outlast can
run to 35 s, and set the window to 30.

**Concrete failure this causes:** an agent that is mid-fan-out (spawning or managing
several children at once — `delegate`'s own shape) receives a correctly-delivered
doorbell whose transcript flush lags past 30 s. `_confirm_rings` judges it unconfirmed,
sends a duplicate doorbell, and — per the design note's own accounting — "the first
doorbell already started its turn, so the second arrives mid-turn and buys the agent an
extra turn to find an empty inbox." Cost: one wasted turn for the busiest agents in the
fleet, at the worst time (they're already fanning out), and it repeats up to
`RING_REPAIRS` times if the lag persists.

**Not proven live** — I did not reproduce a 6-way fan-out and measure its actual flush lag
in this review; I am relying on the figure the codebase itself already measured and cites,
in the same file, to justify a number that contradicts it. Both the design note's 14.59 s
and the `deliver_working_ms` 35 s figure are flagged by their own authors as single
measurements on an idle machine, not load — so the true worst case could be worse than
35 s, not better.

**A number, not a shrug, since that's what was asked:** raise `ring_settle` to at least
40 s, with the margin over 35 s that 30 s currently has none of. Better: match the
reasoning `_took_prompt` already uses for the identical problem — it does not pick one
fixed timeout, it extends once by `deliver_working_ms` (60 s) when the target is
confirmed still working, precisely because a fan-out's flush lag is unpredictable. A
settle window that stretches the same way for an agent herdr reports as `working` would
track the actual cause instead of a flat guess.

## 3. Everything else attacked and holding

- **Re-entrancy (item 2).** `_confirm_rings`'s repair calls `self.h.prompt` directly, not
  `self._ring` — it cannot recurse into ring-writing, and cannot ring the calling agent
  (the "repairer"). `skip=rung` correctly excludes agents this same `flush_pending` pass
  already rang, closing the one re-entrancy path that exists. Read, not just trusted.
- **Cost on the critical path (item 3), outside the concurrency case above.** Bounded:
  the settle-window age check is the first thing tested per outstanding agent and is a
  cheap in-memory comparison; only rings actually past 30 s pay for `get_agent` + a
  transcript tail, and once a ring closes (`ring_confirmed`/`ring_unconfirmed`)
  `_last_ring` returns `None` on its very first row read for that agent on every
  subsequent command — so a permanently-stuck ring does not keep paying full cost forever,
  only the cheap "outstanding" scan does. `outstanding`'s own query
  (`SELECT DISTINCT to_agent FROM messages WHERE read_at IS NULL AND delivered_at IS NOT
  NULL`) has no `to_agent` predicate, so it can't seek either `idx_msgs_inbox` or
  `idx_msgs_undelivered` — it does a full index scan of `idx_msgs_inbox` rather than a
  table scan, which is cheap while unread-mail volume stays small, but is a per-command
  cost proportional to total unread backlog fleet-wide, not per-agent. Worth knowing, not
  severe enough to block.
- **Proof correctness (item 4).** `submitted_since` takes one exact `Path`
  (`store.transcript_path` returns `d / f"{session_id}.jsonl"`), so it structurally cannot
  read a sibling's transcript in a shared `delegate` cwd — this isn't just tested, it's
  true by construction. The ghost-suggestion trap doesn't apply here at all: the proof
  reads the on-disk transcript file, never the pane, so there is no box content to be
  confused by a ghost. `_record_time` parses ISO-8601 with `Z→+00:00` into a
  timezone-aware epoch float, compared against `store.now()` (`int(time.time())`) — both
  UTC epoch, no tz bug. Checked directly, not inferred from the docstring.
- **`apply_preset`'s opt-out (item 6).** Traced every `self._ring(` call site
  (`broker.py:3737, 3808, 3917, 5032, 5303`) — only `apply_preset` (3808) passes
  `repair=False`; every other doorbell defaults `repair=True`, correctly. The flag is
  written into the `ring_sent` payload and read back by `_last_ring` unchanged; the
  interrupt path (5032) never reaches this machinery at all — `_ring` skips the
  `ring_sent` log entirely for `mode==INTERRUPT`, by design. No path found where a preset
  ring could be silently re-sent.
- **Item 7, notes vs. code.** The three new `test_broker.py`/`test_output.py` tests the
  worker's note names actually exist, at the described names, and assert what the note
  claims (checked their bodies, not just their titles). Nothing else in the three notes
  was found to claim behavior the current code doesn't have — the one place a note's
  *original* number changed (the design note's proposed 5 s settle window → the shipped
  30 s) is itself explained and cited in the worker's note, not a silent contradiction.
  My finding #2 above is a problem with the 30 s figure's own justification, not a
  notes-vs-code mismatch.

## What I did not check

- Real OS-process concurrency (only threads-with-separate-connections, argued equivalent
  above but not run as two literal `sb` invocations).
- Whether `when-idle` rings (`done`'s parent poke, `flush_pending`'s own re-ring) hit the
  same race — the mechanism is identical for every non-interrupt ring since they all share
  `_confirm_rings`, but I only set up a `next-turn`-shaped row in the repro.
- Real machine load, or a real 6-way `delegate` fan-out's actual flush lag — finding #2
  reasons from figures the codebase already measured and cites, not a fresh measurement.
- Non-Claude agent kinds (already flagged unproven by the worker; out of scope here too).
