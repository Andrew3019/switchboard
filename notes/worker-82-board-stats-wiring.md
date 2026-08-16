# Board stats: collector -> snapshot -> pane

What landed in `60d7503` on `board-layout`, written for whoever draws the top section next.

## The dict you draw from

`panel.read(paths).stats` — a plain dict, already computed, no store handle and no
subprocess anywhere near you. It is `stats.Stats.as_dict()`, thirteen keys:

| key | what it is |
| --- | --- |
| `turns_last_hour` | `turn_end` events in the last hour |
| `spawns_last_hour` | agent rows created in the last hour |
| `messages_last_hour` | inter-agent messages — NOT "sb calls", nothing logs those |
| `store_age` | seconds since those three were sampled |
| `lines_changed` | added+deleted, commits made in the last hour, any ref |
| `lines_changed_nondocs` | the same excluding `*.md` and the `notes/`, `learnings/` trees |
| `commits_last_hour` | how many commits that was |
| `git_age` | seconds since the git walk |
| `cpu_percent` | summed across the fleet's process tree; can exceed 100 |
| `memory_bytes` | summed RSS — an upper bound, shared pages counted per process |
| `processes` | how many processes that was |
| `cpu_cores` | so you can turn `cpu_percent` into a share |
| `proc_age` | seconds since the `lsof`/`ps` scan |

**Every value is `None` when unknown, and `None` is never zero.** `spawns_last_hour == 0`
means nobody spawned anything; `None` means nobody could say. Drawing a `None` as `0` is
the one way to make this data lie, and nothing on screen would look wrong. Use `.get()` and
treat `None` as "leave it out".

The `*_age` fields are there so you can dim or drop a number that is older than it looks
without knowing `stats.py`'s cadences. A group past its `max_age` already comes back
`None`, so an age is never the thing standing between you and a wrong reading — it is
there for the softer call.

`{}` is possible, and only in the cases where there is no board to draw anyway: the
snapshot file is missing, unreadable, or written by a collector whose `format` this pane
does not read.

## What you must not do

Do not `from . import stats` in a renderer. `stats.collect()` reads the store and shells
out to `git`, `lsof` and `ps` — both halves of what `panel.py`'s module note forbids —
and `tests/test_panel.py::RendererImports` now pins the import statically, the same way it
pins `store`.

## Where it comes from

- `collector.FleetStats` makes the call, on the collector's own read-only connection.
- `panel.envelope` carries it as a third top-level key, `"stats"`, beside `"snapshot"`
  (which stays `sb status --json` verbatim) and `"collector"` (the tick counters).
- `panel.FORMAT` is deliberately **not** bumped. A key an older pane ignores is not a
  shape it would misread, and bumping would blank forty panes for the length of a rollout.

The one expensive call — the three store counts are table scans of an un-indexed
`created_at`, ~370 ms on the first call in a process against a 17 MB store — is primed on
a daemon thread from `collector.run()` before the tick loop, so the first snapshot goes out
without waiting for it. Until it lands, every field is `None`.

## Measured, live, in a clone with two real agents

- First snapshot published **90 ms** after a renderer asked for a collector — process
  spawn, import and tick included.
- Store counts were already on tick 1; the git walk and the `ps` scan joined on tick 2 at
  605 ms, off the tick thread as designed.
- Numbers were plausible: 2 spawns, 2 turns, 0 messages (a real zero), 7 processes,
  4.9% CPU, 25 commits and 4421 lines (2516 non-docs) in the hour.
- `tick_ms` median 16 ms over 20 ticks — the same as before the change.

Not proven: the 370 ms figure itself. A first sweep in a fresh process against the live
17 MB store measured 15 ms, because the live collector reads that file twice a second and
the page cache is hot. The priming is insurance that could not be made to fire here; the
ordering it guarantees is pinned by
`tests/test_panel.py::TheFleetNumbersRideAlong::test_the_first_tick_does_not_wait_for_the_cold_scan`
instead.
