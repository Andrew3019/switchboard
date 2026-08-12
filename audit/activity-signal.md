# Switchboard's own activity signal — what was built, and what it was proved to do

Built 2026-08-11 on branch `activity-signal`. The measurements it is built on are
`audit/hook-signal-cost.md` (what each design costs) and `audit/status-ground-truth.md`
(why the old one broke). This is the build and its live proof.

## The one-paragraph version

Switchboard had no signal of its own for "is this agent working?". It asked herdr, which
infers it by matching Claude's spinner glyphs in the terminal title — and Claude Code
2.1.228 changed those glyphs, so herdr reported **idle** for every pane on the machine,
including agents provably mid-tool-call. Hold-until-free delivery stopped holding, the
reconciler pinged working agents, and the board said `idle` about agents that were running
tool calls. Now switchboard records the fact itself, from Claude Code's own hooks:

    UserPromptSubmit  ->  agents.turn = 'working'      a turn began
    Stop              ->  agents.turn = 'idle'         a turn ended

`status.py` and `Broker._busy` read that first and herdr second. A row with no signal of
ours behaves exactly as it did before.

## Why the edges, and not the two designs that were briefed

From `audit/hook-signal-cost.md`, and cost is **not** the reason:

| design | per tool call | per turn | why not |
|---|---|---|---|
| `PreToolUse`+`PostToolUse` writing events | +148 ms | +74 ms | affordable, but 2 rows per tool call — 31,000 for this repo's history |
| `PostToolUse` touching a timestamp | +19 ms | 0 | **wrong**: cannot tell a long tool call from a finished turn |
| **the edges** (built) | **0** | +74 ms | 2 rows per turn; no timeout at all |

The timestamp design loses on correctness. It forces you to pick an N, and no N exists:
2.18 % of 15,000 real tool calls in this repo ran longer than the existing 72-second
grace and the longest ran 18 minutes, so an N safe against false "idle" is an N that
reports a finished turn up to 18 minutes late. The edges need no N — a long tool call is
inside a turn that began and has not ended, however long it runs. The live proof below
includes a 100-second tool call reading `working` throughout.

The `Stop` half is nearly free: `bin/sb-stop-hook` already ran on every turn end of every
agent we spawn, so the idle edge is one extra `UPDATE` inside a process already paid for.

## What changed

| file | change |
|---|---|
| `store.py` | `agents.turn` (TEXT, NULL-able), `store.set_turn`, `TURN_WORKING`/`TURN_IDLE` from `[states]` |
| `hooks.py` | `UserPromptSubmit` added to the same per-spawn settings file; `mark_turn`; `run()` writes idle **after** the gate decides |
| `bin/sb-activity-hook` | new entry point, prints nothing on stdout, ever |
| `status.py` | `turn` on `AgentStatus`; `display_state` and `stalled` read ours first; `signal_drift`; readouts |
| `broker.py` | `_busy` reads ours first; `restore` clears the signal; `_revive` sets it |
| `board.py` | one note and one glyph branch for `signal_drift` |
| `defaults/settings.toml` | `states.turn_working` / `states.turn_idle` |

Coverage is exactly the Stop gate's, because it is the same settings file:
`herdr.start_agent` hands `--settings` to every spawn and every restore, and to nothing
else. **No file of Andrew's is written or read**, and an ordinary `claude` session never
sees either hook.

### The five states are unchanged

`idle, working, blocked, done, failed`. `agents.turn` is **not** a sixth state and not a
second state column: `state` is the agent's self-report about its TASK, `turn` is an
observation about its TURN, and a blocked agent is `blocked` in one and `idle` in the
other — both true, proved live below. `stalled` stays what it was, a qualifier meaning
idle with no excuse. `signal_drift` is a flag on the same footing, not a word in the STATE
column.

### Composing with the Stop gate — the requirement most likely to be got wrong

`hooks.run` decides first and marks second:

```python
reason = stop_gate(payload, db)
if reason is None:                  # the turn really is ending
    mark_turn(payload, db, store.TURN_IDLE)
```

A blocked stop is **not** the end of a turn. The agent is handed `BLOCK_REASON` and keeps
going in the same turn, and `UserPromptSubmit` does not fire again for it, so marking idle
there would hand its held mail over mid-turn and have the reconciler ask a working agent
why its turn ended. Pinned by a test, and reproduced live below.

### Herdr is kept, and where

Not ripped out — it sees things we cannot, and each use is named in the code:

- **Fallback.** A row with `turn IS NULL` — predating the column, not spawned by us, or
  freshly restored — is read exactly as before (`status.collect`'s `turn_over`,
  `Broker._busy`).
- **Overrides us in one direction only.** `alive is False` (herdr answered and does not
  list the agent) means no turn can be running whatever our last edge said. That is the
  `gone` machinery, untouched, and it is what catches a crash in practice — see below.
- **The cross-check for the failure this introduces** — `AgentStatus.signal_drift`.
- **Still the only source for `at_prompt`**, a permission prompt sitting on screen.

### The hook that never fires

If a session dies mid-turn, no `Stop` runs, `turn` says `working` forever, and nothing in
the fleet would ever move that row. Two things catch it:

1. **`gone`, and in practice this is the one that fires.** herdr's pane exits with the
   process, so a dead session is an agent herdr stops listing; after
   `GONE_CONFIRM_GRACE` the row is recorded `failed`. Proved live below by `kill -9`.
2. **`signal_drift`** for the arrangement where the pane outlives the session: our signal
   says `working`, herdr answers, and it reports `unknown` — "plain shell or unrecognised
   program", produced by the *absence* of any Claude rule matching, which is why it
   survives the broken spinner regex that took herdr's `working` rule out. Debounced by
   `STALL_GRACE` so a flicker is not a death; no new constant. It is surfaced (`<< NO
   SESSION`, the DRIFT block, `needs_human`, `sb board`) and never repaired — inventing an
   end here would be the same lie as fabricating a summary.

Deliberately NOT drift: our `working` against herdr's *idle*. That is what a live agent
mid-tool-call reads as today, so it would fire on every working agent in the fleet. When
herdr's detector is fixed it becomes the stronger cross-check; it is a one-line change and
it should not be made until then.

## Live proof

Isolated `git clone` of this repo into the session scratchpad, branch `activity-signal`,
driven entirely through **that clone's own `./bin/sb`**. Three real agents, real herdr,
real Claude Code 2.1.228. Times are seconds from the first event of each agent's trace.

### 1. Working through a 100-second tool call, and idle the moment the turn ends

`sb start --name sigproof` with a task of one `sleep 100`, then `sb done`.

```
  4s  turn_start           {"target": "sigproof"}
 23s  stop_gate_blocked    sigproof            <- tried to end silently; refused
 39s  ring_deferred        sigproof            <- a --when-idle tell, HELD
127s  done                 sigproof {"summary": "slept"}
129s  turn_end             {"target": "sigproof"}
132s  agent prompt sigproof [sb: from human] You have mail
132s  turn_start           {"target": "sigproof"}
148s  done                 sigproof
151s  turn_end
```

Read from the board at t+18s, mid-tool-call:

```
sigproof  orchestrator  working   idle   ...        <- STATE from us, HERDR column from herdr
  state      working   turn: working   herdr: idle
```

**herdr said `idle` for the whole 100 seconds.** Before this change that row read `idle`
and, once the grace passed, `STALLED`. It now reads `working` because we know its turn
began and has not ended.

### 2. The gate blocks, and the agent is NOT recorded idle

t+23s above: `stop_gate_blocked`, and **no `turn_end`**. Checked in the store at that
moment: `state=working, turn=working`. The mark was written only at t+129s, when the turn
actually ended. This is requirement 1, live.

### 3. Hold-until-free actually holds, and delivers

The `--when-idle` tell at t+39s was **deferred** (`ring_deferred`) on our signal alone —
herdr was reporting `idle` and would have delivered it into the running turn. It was rung
at t+132s, three seconds after `turn_end`, and read by the agent four seconds later.

### 4. An agent that just stops, never reports (Andrew's "not driven at a state" case)

`sb start --name silentfin`, told to write a file and to run no `sb` command at all.

```
   0s  turn_start        {"target": "silentfin"}
   5s  stop_gate_blocked silentfin        <- the gate's one nudge
  13s  turn_end          {"target": "silentfin"}     <- it stopped anyway
  78s  reconcile_ping    {"target": "silentfin"}     <- STALLED, once the grace passed
  78s  turn_start        {"target": "silentfin"}     <- the ping IS a prompt
  83s  stop_gate_capped  {"target": "silentfin"}     <- one nudge per silence, kept
  83s  turn_end
```

The board went `working` -> `idle` -> `<< STALLED`, and the stall came from **our** signal:
this row never ran an `sb` command and never got a session id. Note also that the ping did
not start a nag loop — the turn edges are logged against no agent, with the target in the
payload (`Broker._nudge`'s rule), so `_last_activity` does not read the reconciler's own
footprint as the agent having done something.

### 5. `blocked` is a report, and it ends the turn

`crashy` hit a harness refusal and called `sb block` of its own accord:

```
  state      blocked   turn: idle   herdr: idle  << BLOCKED
  blocked    foreground sleep 300 refused by harness
```

Two columns, two questions, both true: it has stopped for a person (`state`), and its turn
is over (`turn`).

### 6. `failed` — the crash, inferred, never self-reported

`crashy` was put into a genuine long tool call (this repo's own suite as one `Bash` call),
confirmed `state=working, turn=working`, and then its Claude process was killed:

```
kill -9 27519          # found by pgrep -f on the CLONE's hooks path — never an unscoped pkill
+8s   crashy  idle  -  << GONE      herdr agent get crashy -> agent_not_found
+70s  state=failed, ended_at set
```

herdr's pane exits with the process, so the crash showed up as an absence and the existing
`gone` machinery recorded `failed` after `GONE_CONFIRM_GRACE`. The stale `turn='working'`
left on that row is inert: every reader gates on `state in RUNNING` first, and
`flush_pending` checks `_finished_and_unreachable` before it asks `_busy` anything.

## What is NOT proved

- **`signal_drift` has no live proof.** Every way I could kill a session in this setup took
  the pane with it, which is `gone`'s case, not this one. It is unit-tested and reasoned
  from herdr's own `unknown` semantics, and it is a belt over an existing brace — if it is
  ever wrong it costs one line on the board, since nothing is written back. If you want it
  proved, the arrangement to build is a pane running a shell that runs `claude`, so the
  pane survives the process; that is not how `herdr agent start` sets one up today.
- **The `Stop` hook failing to write** (store unreachable at that moment) leaves `working`
  behind exactly like a crash, and reaches the same two cross-checks. Not exercised.
- **No fleet-scale test.** One store, three agents, one machine. The per-firing cost was
  measured elsewhere (`audit/hook-signal-cost.md` §4 for contention) and nothing here adds
  a per-tool-call cost to contend with.
- **`SessionStart`/`SessionEnd` are not used.** A restored session clears the signal to
  NULL and waits for its first real prompt; whether `--resume` fires `UserPromptSubmit` on
  its replayed turn was not measured, and the NULL fallback is what makes that safe either
  way.
- **Compaction.** `PreCompact` never fired in the cost audit's runs and is not handled. If
  a compaction ends a turn without `Stop`, this signal would hold `working` — same shape as
  the crash case, same cross-checks, unmeasured.

## Tests

`/Users/andrew/anaconda3/bin/python -m pytest tests` — **1142 passed** (1131 on `main`,
11 new). The new ones pin the decision and the write, never the CLI's behaviour:

- `test_hooks.py::ActivitySignalTest` — the two edges in order; **a turn the gate refuses
  is not recorded idle**; `blocked` ends a turn; a session that is not ours writes nothing;
  the edges do not reset the idle clock.
- `test_status.py` — ours outranks herdr in both directions; a long tool call never reads
  idle; a row with no signal still reads herdr; a dead session is surfaced and not
  repaired; a momentary `unknown` is not a dead session.
- `test_broker.py` — hold-until-free runs on our signal while herdr reads idle.

The fake herdr was not grown for any of this.

## Acceptance — `./acceptance/accept.py activity-signal`

Verbatim, first run (all four checks, in parallel, on a machine that was also running this
build's own three proof agents):

```
  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [7m54s]
  2  a child's report wakes its parent        FAIL   the child never reported to its parent   [7m49s]
  3  a block holds until the human answers    PASS   held 170s against a sibling, released by the human's answer and read it   [11m31s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbri0r384-k: blocked, not finished — it has not reported an end'   [7m05s]

  check 2 — a child's report wakes its parent
      agents: [{'name': 'sbri0r382-p', 'state': 'working'}, {'name': 'sbri0r382-c', 'state': 'working'}]

1 of 4 FAILED — the fleet is not sound   (11m39s)
```

**Check 2's failure is not this change, and the evidence is in its own message.** It fails
before it reaches anything this branch touches: the child agent never wrote a message row
at all — it never ran its `sb done` inside the window — so the doorbell was never asked to
do anything. Re-run alone, verbatim:

```
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 51s later; the parent woke and read it   [2m05s]

all 1 pass — the fleet is sound   (2m09s)
```

Watched live in that clone's store as it ran, which is the part worth keeping — this is
the deferred path the check exists to force, running on the new signal:

```
t+0    turn_start   {"target": "…-p"}          parent begins `sb delegate … && sleep 45`
t+10   turn_start   {"target": "…-c"}
t+15   done         …-c
t+15   ring_deferred …-p                       held: OUR signal says the parent is mid-turn
t+58   stop_gate_blocked …-p
t+64   turn_end     {"target": "…-p"}
t+66   delivered_at set                        the collector's doorbell, 2s after the edge
t+67   turn_start   {"target": "…-p"}          the parent wakes and reads it
```

Note what herdr was saying about that parent throughout: `idle`. Before this change the
ring would not have been deferred at all — it would have been delivered into the running
turn, and the check would have passed by the wrong route.
