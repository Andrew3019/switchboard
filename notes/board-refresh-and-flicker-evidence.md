# board-refresh-and-flicker — what was measured, and what was proved

Task in `notes/board-refresh-and-flicker-brief.md`. Two questions were asked before
anything was changed: what does 4x the refresh actually cost, and which transitions cause
the flash. Both were answered with numbers rather than reasoning.

## 1. What a faster board costs

The collector is the only process that pays for the interval — 39 of 40 panes read a file
(`switchboard/panel.py`). One tick is `herdr agent list` plus four queries.

| where | tick | at 2 s | at 0.5 s |
|---|---|---|---|
| the fleet's own store, uncontended (507 agents, 30 602 events) | 57 ms median (herdr 11 ms) | 2.8% of a core | 11% |
| the live collector, under a working fleet | 146 ms median, p90 983 ms, max 1110 ms | 7% | 29%, and up to 66% in the tail |

The uncontended number is affordable and the loaded one is not, so `collector._gap` caps
the loop's share of a core at `MAX_DUTY` (25%) and stretches the sleep when a tick is
slow. On a healthy machine the guard never fires; when it does, the board updates less
often exactly while the machine is busy. `panel.stale_after` stays at 5 s, which is above
the worst tick plus its backoff (1.11 + 3.33 = 4.44 s) — a slow board never becomes forty
panes announcing a stale snapshot.

Profile of the 57 ms, for whoever wants it cheaper later: `_last_summaries` 22 ms,
`_last_activity` 21 ms, `_block_reasons` 10 ms — three full scans of `events`, which has
no index on `kind`. Left alone deliberately: an index would only reach stores created
after it, since `store._deficit` reconciles columns and tables and not indexes.

## 2. Which transitions cause the flash

`blocked` and `gone` cannot flash — one is a word the agent wrote, the other an absence
herdr held for `GONE_CONFIRM_GRACE`. Everything that flashes is inferred fresh each tick.

- **A turn gap.** 523 resumed turns in this store (`turn_end` → the next `turn_start`):
  2.1% under 2 s, 4.0% under 5 s, 9.8% under 15 s. Each is a row that said STALLED and
  then went back to work.
- **The cascade off it.** `richboard.busy_below` reads a descendant's reconciled state, so
  one child's two-second gap withdraws the excuse from every idle ancestor in the same
  frame — which is why this reads as a column blinking rather than a row.
- **A wake in progress.** Delivery → the next `turn_start`: 93% of 346 within 2 s. Spawn →
  first `turn_start`: 86% of 235 within 5 s, 99% within 30 s. That tail is the case Andrew
  reported separately, an agent sitting in NEEDS YOU for several frames while its pane
  comes up.

Caught live while watching the fleet read-only for 15 minutes: `agent-handoff-wording`
entered NEEDS YOU for **2.7 s** and `codex-support` for **8.4 s**, both then working
again. The two blocked agents in the same window held for 139 s and 247 s — a real block,
which is why blocks are exempt from the debounce.

30 s is sized off the spawn tail, the only one of the three worth sizing against.

## 3. Live proof, in an isolated clone

A `git clone` in a scratch directory, its own store, a stand-in `herdr` on PATH so pane
readings can be driven, and the clone's REAL collector started as its own process. The
renderer side reads the published file through `panel.read` and asks
`richboard.needs_list` the same question a board pane asks. The control is the same script
with `needs_settle = 0`, which turns the debounce off.

| | debounce on | control (off) |
|---|---|---|
| a 6 s turn gap | **nobody summoned** | `kid` summoned |
| a real stall | `kid` at **30.7 s** | `kid` at 0.5 s |

Separately, the real board run in a pty: **24 frames in 12.0 s = 1.99/s**. The collector
published at 1.6–1.8 polls/s in the same clone with a Python stand-in for herdr costing
30–120 ms a tick — and at 0.4/s in one run where the tick cost 607 ms, which is `_gap`
doing its job under load rather than a fault.

`python -m pytest tests`: 1281 passed before the change, and the suite plus the five new
tests after it.

## What is not proved

- No endurance run. A collector that drifts only after hours is not covered here.
- The `at_prompt` half of the debounce is reasoned, not observed: no herdr screen-scrape
  flicker was caught in the 15-minute window, so its inclusion rests on it being the same
  shape of reading as the rest, not on a measurement.
- Nothing was run against the live fleet's own board; the installed build was left alone.
