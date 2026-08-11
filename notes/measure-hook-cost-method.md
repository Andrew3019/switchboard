# measure-hook-cost — method, raw numbers, and how to re-run

The report is `audit/hook-signal-cost.md`. This is how every number in it was got, so it
can be checked without asking me. Scripts and settings files are in
`notes/measure-hook-cost/`; they were run from a scratch clone, not from this checkout, so
paths inside them are absolute to that clone and must be edited to re-run.

**Nothing under `switchboard/` was touched.** The two hook scripts (`sb-activity-hook`,
`sb-touch-hook`) existed only in the scratch clone's `bin/`; they are kept here as evidence
of what was measured, not as anything to install.

## Setup

- `git clone` of this repo into the session scratchpad; branch `measure-hook-cost`; all
  `sb`/hook invocations drove **that clone's own** `bin/`.
- The clone's store was seeded with a byte copy of the live fleet's
  `.git/agentflow/state.db` (12.5 MB, 22,125 events, 263 agents) so benchmarks ran against
  a realistic store. Copying the file only — the clone's tools were never pointed at the
  live store.
- Machine: 8-core Apple silicon, `load average 5.03` at the start of the run. Python for
  the hooks: `/opt/homebrew/bin/python3` 3.11.5, which is what `#!/usr/bin/env python3`
  resolves to on PATH here.
- Teardown: the tmux server used for the interactive test was killed by name
  (`tmux -L hookbench kill-server`); no `pkill`. The clone and scratchpad remain under
  `/private/tmp/claude-501/...` and can be deleted wholesale.

## 1. Per-firing micro-benchmark — `bench.py`

60 runs per variant, each `subprocess.run(["/bin/sh","-c",cmd], input=<json payload>)`,
which is how Claude Code invokes a `type: command` hook. Warm-up of 3 discarded.

```
variant                                                          median     mean      p90     min
shell floor: /usr/bin/true                                          5.3      5.4      6.0     4.9
cheap, no interpreter: touch a file                                 8.6      8.4      9.0     6.9
python floor: python3 -c pass                                      25.0     25.1     25.7    24.4
cheap, python: stamp mtime (no switchboard import)                 35.9     35.9     37.7    32.6
full: sb-activity-hook (import switchboard + store write)          59.5     58.9     61.9    53.2
existing Stop gate: sb-stop-hook (import switchboard + store reads) 59.2     59.3     62.4    54.6
```

Identical numbers were produced against an empty store before the 12.5 MB store was copied
in (59.3 / 58.4 median), which is the evidence that store size does not matter.

In-process breakdown, 50 iterations each:

```
connect+write ms median 0.67  p90 0.82
connect only  ms median 0.46  p90 0.53
python3 -X importtime -c 'import switchboard.store'  →  21.1 / 22.0 / 30.8 ms cumulative
```

## 2. In-situ A/B against real Claude Code sessions — `run.sh`, `gaps.py`

Task: read twelve small files with twelve `Read` calls. `claude -p ... --allowedTools Read
--model sonnet`, three runs per arm, arms differing only in `--settings`
(`settings-full.json`, `settings-cheap.json`, or none).

Session wall clock, kept only to show why it is not the metric:

```
nohook 19.07 / 21.48 / 23.35 s      full 20.19 / 27.42 / 22.49 s      cheap 19.55 / 17.7 / 19.68 s
```

The metric is the `tool_use` → `tool_result` gap read out of the transcripts in
`~/.claude/projects/<escaped clone path>/`, which excludes the model round trip. Sessions
were matched to arms by mtime order (and confirmed by file size — the four full-arm
transcripts are 111–115 KB because hook records go in the transcript, the others 83–85 KB).

```
full     n=48   median= 154.0ms mean= 150.5 p90= 173.0 min= 117.0
nohook   n=36   median=   6.0ms mean=   9.3 p90=  19.0 min=   1.0
cheap    n=36   median=  25.0ms mean=  26.3 p90=  41.0 min=  10.0
```

Per-run hook firing counts came from `SB_HOOK_LOG` (see `sb-activity-hook`): 25 firings for
12 tool calls = 12 Pre + 12 Post + 1 Stop, every full run.

`hooklog-par.txt` is the parallel-batch run: the paired `PreToolUse` firings share a
timestamp to the millisecond, which is the evidence that hooks run concurrently across a
parallel tool batch.

## 3. Which hook events fire — `settings-allevents.json`, `logger.sh`

All nine of `SessionStart UserPromptSubmit PreToolUse PostToolUse Notification Stop
SubagentStop PreCompact SessionEnd` were installed at once, pointed at a shell logger.

A two-`Read` headless run fired, in order: `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionEnd`.

The long-tool-call run (`eventlog-long.txt`), a real agent running this repo's own suite
as one `Bash` call — the suite takes 70.7 s and passes 1,128 tests on this branch:

```
     0.0s  SessionStart
     1.2s  UserPromptSubmit
     3.2s  PreToolUse Bash
    75.6s  PostToolUse Bash
    76.5s  Stop
    76.6s  SessionEnd
```

Interactive poke test: `tmux -L hookbench` (its own server, invisible to the live fleet)
running `claude --settings settings-allevents.json`, poked twice with `send-keys` + Enter.
Each poke produced one `UserPromptSubmit` and one `Stop`. `Notification` and `PreCompact`
never fired; one `SubagentStop` appeared after the second turn.

## 4. Contention — `contend.py`

N threads each firing the hook 15 times, against the 12.5 MB store.

```
concurrent  full hook: median / p90 / max      touch hook: median / p90 / max
     1          57.6 /  66.6 /  81.2               7.5 /  8.1 / 10.8
     2          59.8 /  64.1 /  65.5               7.4 /  8.3 /  8.8
     4          66.7 /  76.9 /  84.5               8.4 / 10.1 / 13.9
     8          97.2 / 120.5 / 172.8              12.5 / 15.9 / 19.2
    16         187.0 / 276.2 / 440.9              22.6 / 42.9 / 68.4
```

Both degrade by the same factor, which is why the report attributes it to CPU rather than
to the store. Isolated write contention, 8 processes × 200 `log_event` calls sharing one
connection each: median 0.05 ms, p90 0.07 ms, worst single write 205 ms (WAL checkpoint) at
~1,600 writes/s.

## 5. Row size and volume

10,000 activity events inserted into the 12.5 MB store, then
`pragma wal_checkpoint(TRUNCATE)`: 12,652,544 → 13,422,592 bytes = **77.0 bytes/event**.

Live store rate: 22,126 events spanning epoch 1786148869→1786487424 (3.9 days) ≈ 5,600
rows/day.

## 6. Real session history — `realsessions.py`

Every transcript under `~/.claude/projects/*switchboard*` excluding the scratch clone:
259 sessions with ≥5 tool calls, 15,000 tool calls, 1,231 turn-ends (an assistant message
with no `tool_use` and `stop_reason` in `{None, end_turn}`). Median 45 calls/session, max
320. Last four days alone: 292 sessions, 14,011 tool calls ≈ 3,503/day.

Tool-call duration distribution over the 15,148 calls with both a `tool_use` and a matching
`tool_result` timestamp: p50 0.2 s, p90 5.5 s, p99 102.5 s, p99.9 354 s, max 1,095.5 s.
Over 30 s: 586 (3.87 %). Over 60 s: 390 (2.57 %). Over 72 s: 330 (2.18 %). Over 300 s: 23.

Consecutive tool-call intervals under 120 s (n=14,193): median 6.72 s, mean 12.26 s. That
median is the denominator behind "2.2 % of a tool call".

## Caveats

Repeated from the report because they matter more than the numbers: one machine under real
load; the concurrency test is synthetic firings rather than a real fleet; the doorbell test
used `tmux send-keys` rather than `herdr agent prompt`; and I did not measure what a 7×
larger `events` table does to `_last_activity`, `sb inspect`, or the collector tick.
