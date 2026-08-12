# Switchboard's own activity signal — what was built, and what it was proved to do

Built 2026-08-11 on branch `activity-signal`. The measurements it is built on are
`audit/hook-signal-cost.md` (what each design costs) and `audit/status-ground-truth.md`
(why the old one broke). This is the build and its live proof.

## The one-paragraph version

Switchboard had no signal of its own for "is this agent working?". It asked herdr, which
infers it by matching Claude's spinner glyphs in the terminal title — and Claude Code
2.1.228 changed those glyphs, so herdr began reporting **idle** for panes that were
provably mid-tool-call. Hold-until-free delivery stopped holding, the reconciler pinged
working agents, and the board said `idle` about agents that were running tool calls. Now
switchboard records the fact itself, from Claude Code's own hooks:

    UserPromptSubmit  ->  agents.turn = 'working'      a turn began
    Stop              ->  agents.turn = 'idle'         a turn ended

`status.py` and `Broker._busy` read that first and herdr second. A row with no signal of
ours behaves exactly as it did before.

**Correction, and it changes how this whole document should be read.** An independent
verifier (`audit/activity-signal-verification.md`) found that herdr's detector is
**intermittent, not dead**: on the same machine minutes apart it called one agent
mid-foreground-call `idle` and another one `working`. The sentence this document originally
opened with — "herdr reported idle for every pane on the machine" — is too strong as a
present-tense statement and has been struck above. The conclusion is unchanged, and if
anything it is firmer: a busy detector that is right *sometimes* is a worse thing to gate
mail delivery and the reconciler on than one that is never right, because its failures are
invisible. Where the intermittency does earn its keep is as a cross-check, and the stale-edge
repair below is built on exactly it.

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
| `store.py` | `agents.turn` (TEXT, NULL-able), `agents.turn_doubt_since`, `store.set_turn`, `TURN_WORKING`/`TURN_IDLE` from `[states]` |
| `hooks.py` | `UserPromptSubmit` added to the same per-spawn settings file; `mark_turn`; `run()` writes idle **after** the gate decides |
| `bin/sb-activity-hook` | new entry point, prints nothing on stdout, ever |
| `status.py` | `turn` on `AgentStatus`; `display_state` and `stalled` read ours first; `signal_drift`; `turn_doubted` and `_forget_turn`, on `_confirmed_gone`'s debounce factored out as `_sustained`; readouts |
| `broker.py` | `_busy` reads ours first; `restore` clears the signal; `_revive` sets it |
| `board.py` | one note and one glyph branch for `signal_drift` |
| `defaults/settings.toml` | `states.turn_working` / `states.turn_idle`; `timeouts.turn_stale_grace` / `timeouts.turn_doubt_grace` |

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
mid-tool-call reads as today, so it would fire on every working agent in the fleet.

**Neither of those two catches the case that actually matters, and that is the correction
this document most needed.** A dead *session* is what they cover. The far more ordinary
failure is a live session whose `Stop` hook simply never wrote — and there the pane is a
perfectly healthy Claude sitting at its prompt, so `gone` is false (herdr lists it) and
`signal_drift` is false (herdr says `idle`, not `unknown`). The verifier built that case
live and confirmed both cross-checks miss it (`audit/activity-signal-verification.md` §7).
What it costs is not one line on a board: the row says `working` for good, so the reconciler
never pings it, `sb cleanup` refuses it, and its held mail is never rung. Three ordinary
paths reach it and all three are silent — `store.set_turn` swallows `sqlite3
.OperationalError`, which includes *database is locked* once the busy timeout is exhausted;
`hooks.run` catches every exception and returns `{}`; and the `Stop` hook entry carries
`"timeout": 10`, and a hook that times out fails open.

That is what "our `working` against herdr's idle" is for after all — not as a drift flag,
which would light up the whole fleet, but as a slow, corroborated **doubt**. See the next
section.

### The repair: a stale `working` edge is doubted, then dropped

An edge is a fact with an age, and past a point it stops being evidence. Two windows, and
the split between them is the design:

| | what it asks | shipped |
|---|---|---|
| `turn_stale_grace` | has this row had NO event of its own for this long? | 30 min |
| `turn_doubt_grace` | and has herdr said "no turn in that pane" at EVERY reading since? | 15 min |

Past both, `status._forget_turn` sets `agents.turn` back to **NULL** — and NULL, not `idle`,
is the whole of why this is safe. NULL is the value a row with no signal has always held;
every reader in the package already treats it as "we have no signal here, ask herdr", which
is exactly how the row behaved before the activity signal existed. So being wrong about a
live agent costs that one row a week-old behaviour for one turn, and it self-corrects at the
agent's very next turn edge or `sb` command, both of which write the column again. Nothing
is lost, no summary is fabricated, no end is recorded: `state` is untouched and the row is
still its agent's to finish.

**The bound is not the rejected timeout.** The timestamp design was rejected because it
forces you to pick an N that tells a long tool call from a finished turn, and no such N
exists. This N decides nothing on its own; it only says when a row is worth asking herdr
about. It is still set clear of the numbers that killed the other design: 2.18 % of this
repo's tool calls run past 72 s and the longest ran 18 min, and measured across 406 real
agent sessions here, the longest a live agent goes *inside one turn* without running an `sb`
command is **20.6 min at the 99th percentile** (median 14 s, p90 3.4 min). 30 min clears
both. The tail goes to 139 min at the 99.9th, which is precisely why the first window is not
allowed to decide.

**What decides is the second window, and it works because herdr is intermittent rather than
dead.** A genuinely working agent reads `working` to herdr sooner or later — the verifier saw
it do so — and ONE such reading anywhere in the 15 minutes clears the doubt and starts the
clock from nothing. So does one `sb` command from the agent, which resets the staleness half.
An agent that is quiet because its turn really ended produces neither, ever. A single
disagreement can never move a row: the memory is a column (`agents.turn_doubt_since`) and the
debounce is `_confirmed_gone`'s, factored out rather than written twice.

Deliberately narrow, and each exclusion is load-bearing:

- `alive is True` — a herdr outage observed nothing, and an agent herdr answered about and
  did not list is `gone`'s case.
- `herdr_state in IDLE_LIKE` and not `!= working` — `unknown` is `signal_drift`'s reading
  (a pane with no agent in it has nothing to be pinged back to life), and `blocked` is a
  person being asked something in the TUI, which is mid-turn and produces the longest
  silences there are.
- Only on the reap path, so a read-only reader — the board, the collector — never repairs.
  Same property `gone` already has: with nothing looking, the row sits. Any `sb status` or
  `sb inspect` is enough to move it.

The wedge becomes a delay of at most 45 minutes, and everything that was unreachable is
reachable again with no new machinery: the row is STALLED, so the reconciler pings it; the
doorbell reads herdr again, so held mail is rung; and an agent that answers reports and is
swept like any other.

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

## The stale edge, live — the wedge, and the same case repairing

Two isolated `git clone`s of this repo, each driven only through **its own** `./bin/sb`,
real herdr 0.8.0 and real Claude Code. `clone2` on `activity-signal` (the code as it stood),
`clone` on this branch. Both agents were given one task — a single 150-second foreground
`sleep`, then stop, and **run no `sb` command at all** — and in both the store was made
unopenable (`chmod 000 state.db*`) across the moment their turn ended, which is the
verifier's construction (`audit/activity-signal-verification.md` §7). Unix seconds are out of
the store and `date +%s`. Everything was torn down; no unscoped `pkill`, and no process was
killed at all.

### The wedge, unfixed (`clone2`, branch `activity-signal`)

`turn_start` at 1786496557, sealed 1786496617, unsealed 1786496787. The `Stop` hook fired
inside that window and failed open in both halves: no `turn_end`, no `stop_gate_blocked`.

```
AGENT   ROLE          STATE     HERDR    MAIL     AGE    IDLE  WORKSPACE
vstuck  orchestrator  working   idle        -      4m      3m  vstuck

{'state':'working','turn':'working','herdr_state':'idle','stalled':False,
 'gone':False,'signal_drift':False,'display_state':'working','idle':239}

sent to vstuck (vstuck mid-turn or blocked — will be rung when free)
closed: (nothing)
  refused vstuck: working, not finished — it has not reported an end
```

Every flag that could move this row is False. 783 seconds after the lost edge, unchanged:
`stalled False, gone False, signal_drift False`, and `mail: [{'body':'held forever?',
'delivered_at': None, 'read_at': None}]`.

### The same case, repairing (`clone`, this branch)

`rstuck`, wedged identically — `turn_start` 1786496862, sealed 1786496916, unsealed
1786497056, no `turn_end` — then the held mail and a refused sweep, exactly as above:

```
rstuck  orchestrator  working   done        -      3m      3m  rstuck
sent to rstuck (rstuck mid-turn or blocked — will be rung when free)
  refused rstuck: working, not finished — it has not reported an end
```

**The shipped bound is real**, and this is the reading that shows it — the same row, quiet
for 87 s, is not even doubted at 30 minutes:

```
shipped (1800/900):  {'turn':'working','turn_doubted':False,'idle':87}
```

The rest of the run used `SWITCHBOARD_DEFAULTS` pointing at a copy of `defaults/` with
`turn_stale_grace = 60` and `turn_doubt_grace = 30` and **nothing else changed**, so a
45-minute mechanism could be watched in 90 seconds. What that shortens is the two windows;
the path below is the shipped one.

```
1786497162  {'turn':'working','turn_doubted':True, 'stalled':False,'idle':87, 'undelivered':1}
            stored: turn='working', turn_doubt_since=1786497162      <- doubted, still believed
1786497198  {'turn':'working','turn_doubted':True, 'stalled':False,'idle':123,'undelivered':1}
            stored: turn=None, turn_doubt_since=None                 <- past the window: dropped
            event  turn_forgotten {"target":"rstuck","held":90}
1786497198  {'turn':None,     'turn_doubted':False,'stalled':True,  'display_state':'idle',
                                                                     'undelivered':0}
```

One reading doubts and writes nothing. The next, past the window, drops the edge. The
reading after that is a normal stalled row — and `undelivered` went 1 → 0 in the same
command, because `flush_pending` reads herdr again the moment the edge is gone. What
followed, from the store:

```
1786497198  turn_forgotten   {"target": "rstuck"}
1786497198  delivered_at set                     the doorbell — held mail, finally rung
1786497198  turn_start       {"target": "rstuck"}   the agent woke
1786497204  read_at set                          it read the message
1786497219  done             {"summary": "Ran the 150-second sleep command you asked for…"}
1786497222  turn_end         {"target": "rstuck"}
```

`state=done, turn=idle, ended_at=1786497219` — and then `sb cleanup rstuck` → `closed:
rstuck`. Pingable, cleanable, mail delivered.

**And the reconciler's ping, with no mail in play.** A second agent, `rping`, wedged the same
way and never sent anything, so the doorbell had nothing to ring:

```
1786497455  {'turn':'working','turn_doubted':True, 'stalled':False,'idle':173,'undelivered':0}
1786497490  {'turn':'working','turn_doubted':True, 'stalled':False,'idle':208,'undelivered':0}
            stored: turn=None
1786497490  {'turn':None,     'turn_doubted':False,'stalled':True,  'display_state':'idle'}

1786497490  turn_forgotten    {"target": "rping"}
1786497490  reconcile_ping    {"target": "rping"}     <- the same second
1786497491  turn_start        {"target": "rping"}     <- it woke
1786497497  stop_gate_blocked
1786497505  turn_end          {"target": "rping"}
```

### What this run does NOT prove

- **The size of the bounds.** The mechanism ran on 60/30; 1800/900 is argued from measurement
  (the section above) and from the rejected timeout's own numbers, not watched end to end.
  A 45-minute wedge was not sat through.
- **A live agent being spared by a herdr `working` reading.** The clearing path is unit-tested
  and it is the same `_sustained` the `gone` debounce has used since it shipped, but no live
  run drove a genuinely working agent past the staleness bound and watched herdr rescue it.
  **This is the residual risk to know about**: if herdr's detector were dark for a whole
  doubt window rather than intermittent, a live agent that runs no `sb` command for 45
  minutes would have its edge dropped. What that costs is the row reading the way it did on
  `main` for one turn — held mail delivered into a running turn, one reconciler nudge — and
  it self-corrects at that agent's next edge. Nothing is written that a later edge cannot
  overwrite.
- **Lock contention as the cause**, rather than `chmod`. Consequence proved, frequency not —
  same limit the verifier recorded.

## What is NOT proved

- **`signal_drift` has no live proof.** Every way I could kill a session in this setup took
  the pane with it, which is `gone`'s case, not this one. It is unit-tested and reasoned
  from herdr's own `unknown` semantics, and it is a belt over an existing brace — if it is
  ever wrong it costs one line on the board, since nothing is written back. If you want it
  proved, the arrangement to build is a pane running a shell that runs `claude`, so the
  pane survives the process; that is not how `herdr agent start` sets one up today.
- ~~**The `Stop` hook failing to write** (store unreachable at that moment) leaves `working`
  behind exactly like a crash, and reaches the same two cross-checks. Not exercised.~~
  **Exercised, and both halves of that sentence were wrong.** It does not reach either
  cross-check, and it is not like a crash — a crash takes the pane and `gone` catches it,
  while this leaves a live pane nothing will ever touch again. Reproduced live twice, once
  unfixed and once repairing, in "The stale edge, live" below.
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

`/Users/andrew/anaconda3/bin/python -m pytest tests` — **1145 passed** (1131 on `main`,
14 new). The new ones pin the decision and the write, never the CLI's behaviour:

- `test_hooks.py::ActivitySignalTest` — the two edges in order; **a turn the gate refuses
  is not recorded idle**; `blocked` ends a turn; a session that is not ours writes nothing;
  the edges do not reset the idle clock.
- `test_status.py` — ours outranks herdr in both directions; a long tool call never reads
  idle; a row with no signal still reads herdr; a dead session is surfaced and not
  repaired; a momentary `unknown` is not a dead session.
- `test_broker.py` — hold-until-free runs on our signal while herdr reads idle.
- `test_status.py`, the repair — an edge nothing stands behind is dropped once the doubt has
  held, and the row moves again; ONE disagreeing reading starts the clock over; a long tool
  call is never doubted and neither is a pane with nobody in it.

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

Note what herdr was saying about that parent throughout: `idle`.

### The before/after this section used to claim — STRUCK

A "before and after" ran here: the same check against **`main`** immediately afterwards,
FAILing with `ring_deferred events for the parent: 0` and `lag 0s`, and the conclusion
**"this branch is what makes acceptance check 2 pass again"**.

**It does not reproduce, and it should not be relied on.** The verifier ran
`./acceptance/accept.py main --only 2` twice in a row from a clean clone and `main` PASSED
both times, by exactly the deferred-then-doorbell path the check exists to force — 48 s and
46 s of hold (`audit/activity-signal-verification.md` §10). They also passed all four checks
on this branch **in parallel** in 2m19s, against the 11m39s run above in which check 2
failed; so check 2 is flaky under heavy load rather than reliably failing under parallel
load, and that run shared the machine with this build's own three proof agents.

Both sentences the claim rested on are withdrawn. What is left is the mechanism, which
stands on its own and is watched live in the trace above: when herdr's detector is wrong
about a parent, `main` delivers the child's report into the parent's running turn and this
branch holds it. herdr's detector is wrong about a parent *sometimes* — that is the whole
finding — so the before/after was a snapshot of one moment's intermittency, presented as if
it were the difference between the two branches. It is not.

Later runs of the full four checks on this branch, for the record — `./acceptance/accept.py
repair-stuck`, all four in parallel:

```
  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [37s]
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 47s later; the parent woke and read it   [2m07s]
  3  a block holds until the human answers    PASS   held 26s against a sibling, released by the human's answer and read it   [1m36s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbwlxwdp4-k: blocked, not finished — it has not reported an end'   [42s]

all 4 pass — the fleet is sound   (2m14s)
```
