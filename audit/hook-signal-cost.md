# What a hook-based activity signal costs

Measured 2026-08-11 in an isolated clone, driving real Claude Code sessions. Nothing here
was built; this is a measurement. Method and raw numbers: `notes/measure-hook-cost-method.md`.

## The answer

| design | added latency per tool call | per turn | store writes |
|---|---|---|---|
| **Full** — `PreToolUse` + `PostToolUse` + `Stop`, each writing an event | **+148 ms** | +74 ms | 2 rows/call |
| **Cheap** — `PostToolUse` only, touching a timestamp file | **+19 ms** | 0 | none |
| **Edges** (third design, below) — `UserPromptSubmit` + `Stop` | **0 ms** | +74 ms | 2 rows/turn |

The median real tool-call cycle in this repo's history is 6.72 s (14,193 consecutive
tool calls across 259 sessions). So the full design costs **2.2 % of a tool call**, the
cheap one 0.3 %.

**Verdict: none of these is expensive.** The full design, applied to the single busiest
agent session in this repo's history (320 tool calls over 27.9 hours), would have added
**54 seconds — spread over 28 hours**. Across all 259 sessions and 15,000 tool calls ever
recorded here it would have added 38.5 minutes of wall clock in total.

Cost is not what should decide this. Correctness should, and it decides against the cheap
design — see "what the cheap design loses".

**Recommendation: the edge design.** It costs nothing per tool call, needs no idle
timeout at all, and is a drop-in for the exact field `status.py` is currently getting
wrong. The one reason that decides it: an activity *timestamp* forces you to pick an N,
and no N exists that works — 2.18 % of this repo's real tool calls run longer than the
72-second grace, and the longest ran 18 minutes.

## Where the 148 ms goes

Per hook firing, measured 60 times each (`/bin/sh -c <command>`, JSON payload on stdin,
exactly as Claude Code invokes a `type: command` hook):

| what runs | median | p90 |
|---|---|---|
| `/usr/bin/true` (process-spawn floor) | 5.4 ms | 6.0 ms |
| `/usr/bin/touch <file>` (the cheap design's whole body) | 8.7 ms | 9.2 ms |
| `python3 -c pass` (interpreter floor) | 25.0 ms | 25.7 ms |
| a python script that stamps an mtime, no switchboard import | 35.9 ms | 37.7 ms |
| `sb-activity-hook`: import switchboard + connect + write one event | 59.3 ms | 61.9 ms |
| `bin/sb-stop-hook`, the gate that already runs today | 58.4 ms | 61.5 ms |

**The store is not the cost. The interpreter is.** Inside the process, `store.connect()`
takes 0.46 ms and `connect + log_event` 0.67 ms — about **1 %** of the firing. `import
switchboard.store` costs 21–31 ms, and Python itself costs 25 ms before that. Store size
is irrelevant: the same benchmark against an empty store and against a 12.5 MB copy of the
live fleet's store (22,125 events, 263 agents) produced identical numbers.

In situ, one firing costs about 74 ms rather than 59 — Claude Code adds roughly 15 ms of
its own per hook (matcher evaluation, process management, recording it in the transcript).
Two firings per tool call is the 148 ms.

## How the in-situ number was got

The A/B is real Claude Code sessions in the clone (`claude -p`, sonnet, a task of twelve
`Read` calls), three runs per arm. Total session wall clock is useless for this — model
round trips swamp it (nohook runs came in at 19.1/21.5/23.4 s, full at 20.2/27.4/22.5 s).

So the metric is taken from the transcripts instead: the gap between the assistant message
carrying a `tool_use` and the user message carrying its `tool_result`. That interval
contains the tool and its hooks and **not** the model, which is what makes it clean:

| arm | tool calls | median gap | mean | p90 |
|---|---|---|---|---|
| no hooks | 36 | 6.0 ms | 9.3 | 19 |
| full (Pre + Post) | 48 | 154.0 ms | 150.5 | 173 |
| cheap (Post, `touch`) | 36 | 25.0 ms | 26.3 | 41 |

Both hooks are serial: the tool does not start until `PreToolUse` returns, and the result
does not land until `PostToolUse` returns. That is the whole cost — there is no hidden
asynchronous part.

One thing that makes it cheaper than the table suggests: **hooks fire in parallel across a
parallel tool batch**. In a run where the model issued Reads in pairs, both `PreToolUse`
firings started in the same millisecond. A batch of N tool calls costs one hook duration,
not N.

## Process cost and contention

Every firing is a fresh `/bin/sh` and, for the store-writing designs, a fresh Python
interpreter. At the fleet's measured rate (3,503 tool calls/day over the last four days),
the full design launches ~7,000 extra Python processes per day — an average of 0.08/s.

Concurrency, the full hook fired repeatedly by N simultaneous "agents" (8-core machine,
already at load ~5):

| concurrent agents | full hook median | `touch` hook median |
|---|---|---|
| 1 | 57.6 ms | 7.5 ms |
| 4 | 66.7 ms | 8.4 ms |
| 8 | 97.2 ms (p90 120) | 12.5 ms |
| 16 | 187.0 ms | 22.6 ms |

At the 5–8 agents that are commonly alive, a firing costs ~1.7× its solo cost, so the full
design is ~194 ms per tool call rather than 148. **This is CPU contention, not store
contention** — the `touch` hook, which never opens the database, degrades by the same
factor.

Store contention is not plausible. Eight processes writing events flat out (1,600 writes
in about a second, ~1000× the realistic rate) saw a median write of 0.05 ms and p90 of
0.07 ms; only the tail showed WAL-checkpoint stalls (max 205 ms on one write in 1,600). The
store is in WAL mode and `_DB_TIMEOUT` already covers this class of wait.

## Write volume

Measured by inserting 10,000 activity events into the 12.5 MB copy of the live store:
**77 bytes per event**, including indexes.

- A median session (45 tool calls): 90 rows, 7 KB.
- The busiest session in this repo's history (320 calls): 640 rows, 49 KB.
- The fleet, at 3,503 tool calls/day: **7,006 rows/day, 0.54 MB/day**.

The live store currently grows at about 5,600 rows/day (22,126 events over the last 3.9
days), so the full design roughly **doubles the store's write volume and growth rate**.
0.54 MB/day is nothing in itself; the thing to notice is that `events` becomes mostly
activity noise, and anything that scans it — `_last_activity`, `sb inspect`, the
reconciler — is reading a table with 7× more rows per agent than it has today (84
events/agent now, ~600 with the full design). None of those queries were measured under
that load. The edge design adds 2 rows per turn instead: 1,231 rows for the entire
259-session history.

## What it would have cost today

Real sessions from this repo's history, priced at the measured rates:

| session | worktree | tool calls | turns | span | full | cheap | edges |
|---|---|---|---|---|---|---|---|
| 57ceca58 | Code/switchboard | 320 | 95 | 27.9 h | 54.4 s | 6.1 s | 7.0 s |
| 73ea3449 | finalise-stack | 235 | 4 | 3.8 h | 35.1 s | 4.5 s | 0.3 s |
| 86e2dfa3 | prompts | 234 | 46 | 3.3 h | 38.0 s | 4.4 s | 3.4 s |
| b33424bc | Code/switchboard | 185 | 83 | 13.9 h | 33.5 s | 3.5 s | 6.1 s |
| all 259 sessions | — | 15,000 | 1,231 | — | 38.5 min | 4.8 min | 1.5 min |

## What the cheap design loses

**It cannot tell a long tool call from a finished turn.** That is the distinction the
signal exists for, so the cheap design is not a cheaper version of the signal — it is a
different, worse signal.

`PostToolUse` fires when a tool *finishes*. While one is running, nothing fires, so the
timestamp ages at exactly the rate an idle agent's does. Measured on a real agent in the
clone running this repo's own test suite as a single Bash call:

```
  0.0s  SessionStart
  1.2s  UserPromptSubmit
  3.2s  PreToolUse  Bash
 75.6s  PostToolUse Bash      <- 72.4 seconds with no signal, agent working the whole time
 76.5s  Stop
```

That is not a corner case. Over 15,148 real tool calls with a measurable duration in this
repo's transcripts:

| duration | share |
|---|---|
| p50 | 0.2 s |
| p90 | 5.5 s |
| p99 | 102.5 s |
| longer than 30 s | 586 calls (3.87 %) |
| longer than 60 s | 390 calls (2.57 %) |
| **longer than 72 s** | **330 calls (2.18 %)** |
| longer than 300 s | 23 calls (0.15 %) |
| max | **1,095 s** (18 min, a `Bash` call) |

### What N would have to be

- To never call a working agent idle, **N must exceed the longest tool call: >1,100 s (18
  minutes)** on this evidence. At that N the signal reports a finished turn up to 18
  minutes late, which is far worse than what exists now.
- At **N = 72 s**, matching `status.STALL_GRACE`, **330 tool calls in this repo's history
  (2.18 %) would each have produced a false "idle" reading on an agent that was working** —
  and since the reconciler nudges what reads stalled, those are false nudges landing
  mid-tool-call. That is the same class of bug `STALL_GRACE` was sized to prevent.
- Any N large enough to be safe is too large to be useful. There is no good value.

The fix inside the cheap family is to add `PreToolUse`, so that "a Pre with no matching
Post" means "inside a tool call" and never goes stale. But that is the full design's cost.
**Cheap-and-correct is the full design.**

### How this interacts with the 72-second grace

`STALL_GRACE` (72.0 s, computed from `DELIVER_ATTEMPTS`/`DELIVER_TIMEOUT_MS`/`SPAWN_BACKOFF`)
is not an idle clock and should not be confused with one. Read `status.collect`: `stalled`
is `running and alive and hstate in IDLE_LIKE and not awaiting and not starting`. The
truth of "is a turn running" comes entirely from **herdr's** state — the thing that is
broken — and `STALL_GRACE` only suppresses the label for an agent that has never run an
`sb` command, so "idle" cannot be read as "never started".

That matters for the choice of design: **`status.py` wants a state, not a timestamp.** The
edge design produces a state and drops straight into that expression in place of `hstate in
IDLE_LIKE`, with no new constant. The cheap design produces a timestamp, which would force
that expression to become clock-based and introduce the N that has no good value. The
72-second grace stays untouched under the edge design and keeps doing its actual job.

## The third design: record the edges, not the activity

Neither of the two briefed designs is the cheapest correct one. The question "is this
agent working?" is a state with exactly two transitions, and Claude Code fires a hook on
both. Verified by installing every hook event and running real sessions:

```
SessionStart      fires
UserPromptSubmit  fires — once per turn, on every poke
PreToolUse        fires — per tool call
PostToolUse       fires — per tool call
Stop              fires — once per turn end
SessionEnd        fires
```

So: **`UserPromptSubmit` → write `working`. `Stop` → write `idle`.**

- **Per tool call: nothing.** No hook in the tool path at all.
- **Per turn: ~74 ms**, and only the `UserPromptSubmit` half is new — `Stop` already runs
  `bin/sb-stop-hook` on every turn end of every agent we spawn, so the idle edge is one
  extra `INSERT` (0.2 ms measured) inside a process that is already being paid for.
- **No N, no clock, no grace.** A long tool call is inside a turn that began with a
  `UserPromptSubmit` and has not yet hit `Stop`, so it reads `working` for its entire
  duration however long that is. This is the distinction the cheap design cannot make and
  the full design makes only by accident.
- **Two rows per turn**: 1,231 rows for this repo's entire history, versus 31,000 for the
  full design.
- Coverage is identical to today's Stop gate: it reaches exactly the sessions switchboard
  spawns with `--settings` (`herdr.start_agent` hands it to every spawn and every restore),
  and no session of the human's.

Verified against a real interactive session, not just `-p`: a `claude` started in an
isolated tmux server, then poked twice by sending keystrokes into its pane, fired
`UserPromptSubmit` then `Stop` for each poke. That is the shape of the doorbell —
`Herdr.prompt` is `herdr agent prompt`, and its own docstring records that literal
keystrokes into the pane behave identically.

**Its one weakness:** a session that is killed, crashes, or has its pane destroyed never
fires `Stop`, so the store would hold `working` forever. That is the same failure the
existing `gone` machinery already handles — herdr presence plus `GONE_CONFIRM_GRACE` (60 s)
— and the row would show as `gone`, not as a live working agent. If a belt-and-braces
heartbeat is wanted, adding `PostToolUse` on top costs the measured 19 ms per tool call and
gives a liveness ping without any of the interpretation problems, because the *state*
still comes from the edges.

## What I did not measure

- Everything is one machine (8-core Apple silicon, already at load ~5) with the local
  filesystem and a warm page cache. Absolute milliseconds will differ elsewhere; the
  breakdown (interpreter dominates, store is ~1 %) should not.
- The concurrency numbers are N processes firing the hook in a tight loop, not 8 real
  agents in a real fleet. They bound CPU contention; they are not a fleet test.
- I did not drive `herdr` itself. The doorbell test used `tmux send-keys` into an
  interactive `claude`, on the strength of `Herdr.prompt`'s own recorded finding that the
  two paths behave identically. If the edge design is built, fire one real `sb tell`
  at a real agent and confirm `UserPromptSubmit` before relying on it.
- I did not measure what a 7×-larger `events` table does to `_last_activity`, `sb inspect`,
  or the collector's two-second tick. That is the full design's real hidden cost, and it is
  the one number in this report I am guessing at rather than reporting.
- All sessions in the A/B ran `sonnet` on a twelve-`Read` task. The per-firing cost does
  not depend on the model or the tool, but the arms were not run against every tool type.
- `SubagentStop` fired once, incidentally, in the interactive test; `Notification` and
  `PreCompact` never fired in any run. I did not characterise any of the three.
