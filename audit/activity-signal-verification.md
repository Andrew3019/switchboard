# Independent verification of the activity signal (branch `activity-signal`, PR #17)

Verified 2026-08-11 by `verify-activity` (QA). I did not write this code. Everything below
was run live in two throwaway `git clone`s of this repo, each driven only through **its own**
`./bin/sb`, with real herdr 0.8.0 and real Claude Code (Opus 5). Timestamps are unix seconds
straight out of the store's `events` table and `date +%s`, not reconstructed.

Clones:

* `…/scratchpad/clone`  — branch `activity-signal`, 8 agents (`vlong`, `vsilent`, `vpoke`,
  `vhold`, `vcrash`, `vblock`, `vparent`, `worker-1`)
* `…/scratchpad/clone2` — branch `activity-signal`, 3 agents (`vstuck`, `vgate`)

All of them torn down (`sb workspace close`, and `herdr workspace close` for the four rows
`sb cleanup` correctly refused). No unscoped `pkill`; the one `kill -9` was pid 62900,
identified as the `claude` process whose `--settings` was the clone's own hooks file and whose
child was the clone agent's own `python -c 'time.sleep(400)'`.

---

## Verdict

**Merge — but not for the reason the audit doc gives, and only with its two overstated
claims struck.** The mechanism is sound on every path I drove it down: 1142 tests pass, all
four acceptance checks pass in parallel, and every one of the five states plus the natural
"nobody drove it there" cases behaved as designed. What does not survive verification is the
*justification*: the author's before/after evidence does not reproduce (§10).

The one thing that decides it: **herdr's busy detector is intermittent, not dead.** On the
same machine within minutes I saw herdr call one agent mid-foreground-tool-call `idle`
(§2) and another one `working` (§2), and `main` passed acceptance check 2 by the
hold-until-free path twice in a row (§10) — the check the author reports as failing on `main`.
A detector that is right sometimes is a worse thing to gate mail delivery and the reconciler
on than one that is never right, because its failures are invisible. Owning the fact is still
the correct call. "herdr reports idle for every pane" is not.

The cost of merging is a failure mode that did not exist before: a turn edge that fails to be
written leaves the row saying `working` for good, and **nothing in the fleet ever repairs
it**. I constructed that case live (§7) — the author could not — and found that *neither* of
the two cross-checks they name reaches it, contrary to the write-up. Before this branch a lost
`Stop` hook cost one gate nudge and the readout self-corrected from herdr on the next look;
now it costs the row permanently. Three ordinary paths reach it, all silent (§7). That is the
thing to weigh, and it is why I would not merge the audit doc unedited alongside the code.

---

## 1. The five states by their normal path

| state | agent | evidence |
|---|---|---|
| working | `vlong` | `turn_start` t=1786493649; `turn=working` continuously 1786493662 → 1786493809 (147 s) inside ONE foreground `Bash` call; `done` 1786493812 |
| idle | `vsilent` | `turn_end` 1786493624, `turn=idle`, board `STATE idle … << STALLED` |
| done | `vpoke`, `vhold`, `vparent`, `worker-1` | `done` then `turn_end` 1–2 s later, `state=done turn=idle` |
| blocked | `vblock` | `blocked` 1786493943, `turn_end` 1786493945 → `state=blocked turn=idle`, board `<< BLOCKED` |
| failed | `vcrash` | `kill -9` 1786494160 → board `GONE` by 1786494232 → `state=failed, ended_at=1786494318` |

`blocked` + `turn=idle` at the same time is exactly what the author claims and it is right:
two columns, two questions.

## 2. The long tool call — the headline claim, confirmed

`vlong` ran `/Users/andrew/anaconda3/bin/python -c 'import time; time.sleep(150)'` in the
FOREGROUND as a single `Bash` call. Sampled every 12 s from 1786493748 to 1786493809, the row
read `state=working turn=working` at every sample, and the board at 1786493670 read:

```
vlong    orchestrator  working   idle        -      1m     17s  vlong
```

`STATE working` from our signal; `HERDR idle` from herdr, at a moment the agent was provably
inside a tool call. That is the change, in one line.

**But a correction to the write-up's premise.** herdr is not uniformly blind. At 1786494117,
`herdr agent get vcrash` returned `"agent_status":"working"` for an agent in the same kind of
foreground call, and `sb status` showed `HERDR working` for it. So herdr's detector is
*intermittent*, not dead. That does not weaken the case for owning the signal — an
intermittently-correct busy detector is a worse thing to gate delivery on than a consistently
wrong one — but the audit doc's "herdr reported idle for every pane" is too strong as a
present-tense statement, and anyone reading it as a stable fact will be surprised.

## 3. Agents behaving naturally, not driven at a state

**Stops mid-task without reporting** (`vsilent`, told to write a file and to run no `sb`
command ever). Verbatim trace:

```
1786493610  turn_start        {"target": "vsilent"}
1786493619  stop_gate_blocked vsilent          <- the gate's one nudge
1786493624  turn_end          {"target": "vsilent"}
1786493692  reconcile_ping    {"target": "vsilent"}   <- 68s later, once STALL_GRACE passed
1786493693  turn_start        {"target": "vsilent"}
1786493698  stop_gate_capped  {"target": "vsilent"}   <- one nudge per silence, held
1786493698  turn_end          {"target": "vsilent"}
```

Board went `working` → `idle` → `<< STALLED`, and the DRIFT block attributed it correctly:
`STALLED  its turn-end hook fired — turn ended, 'sb done' never called`. No nag loop: the
reconciler's own prompt logged `turn_start` against no agent, so the idle clock was not reset
by its own footprint. This is the author's case 4, reproduced.

**Told to edit a file and never reports** — same agent, same result; the file task completed
and the row stayed open and STALLED until a human touched it.

**Poked while working** (`vpoke`, mid a 150 s foreground call, plain `sb tell` at 1786494070).
The message was **queued** by the CLI ("Press up to edit queued messages") and then consumed
*inside the running turn* — the pane shows it as a user line mid-turn and no `turn_start` was
logged for it. `turn` stayed `working` across the whole thing and went `idle` only at the real
`turn_end` (1786493793). No gap, no false idle.

This was my main suspicion going in — that a queued poke would end one turn and start another
without a `UserPromptSubmit` — and on Claude Code 2.1.228 it does not happen: the CLI folds the
queued message into the running turn. It is worth knowing that the correctness of the signal
here rests on that CLI behaviour, which is not ours and is exactly the kind of thing that
changed under herdr.

**Poked while idle** (`vsilent`, 1786494079): `turn_start` fired the same second. ✓
**Poked after `done`, still open** (`vpoke`, 1786494079): `turn_start` 1786494080, `revived`
1786494083 (state back to `working`, `turn=working`), then a normal `done`/`turn_end`. ✓

**A case the write-up does not cover, and it is the most common one there is.** `vlong`'s first
attempt was `sleep 120`, which the harness blocks in the foreground; the agent backgrounded it
and used `Monitor`, then ended its turn to wait. The signal correctly said `idle` — the turn
genuinely ended — so the board called it idle and it was on course to be STALLED and pinged
while its own background work ran. That is not a defect of this change (herdr read the same),
but "agent waiting on a background task" is a real, frequent shape that neither signal
describes, and this branch makes the wrong answer arrive faster and more confidently.

## 4. The Stop gate composed with the signal — requirement 1, confirmed directly

The author says a blocked stop must not be recorded idle. I watched the column at 2-second
resolution across one (`vgate`, clone2):

```
1786494531  {'state':'working','turn':'working'}   last event: turn_start        1786494530
1786494533  {'state':'working','turn':'working'}   last event: stop_gate_blocked 1786494532
1786494535  {'state':'working','turn':'working'}   last event: stop_gate_blocked 1786494532
1786494537  {'state':'working','turn':'idle'}      last event: turn_end          1786494535
```

Two samples with the gate's refusal already logged and `turn` still `working`. Confirmed
independently of the author's test.

## 5. Hold-until-free — confirmed end to end

`vhold` was mid a 150 s foreground call. `sb tell vhold "…" --when-idle` at 1786494079 printed
`(vhold mid-turn or blocked — will be rung when free)` and logged `ring_deferred` — while
`sb status` was showing `HERDR done` for that row, i.e. the defer ran on **our** signal alone.

```
1786494079  ring_deferred  vhold
1786494087  done           vhold
1786494088  ring_deferred  vhold     <- still mid-turn, held again
1786494089  turn_end       vhold
1786494091  turn_start     vhold     <- doorbell rang 2s after the edge; agent woke and read it
1786494103  done           vhold     summary: "held; inbox read, both messages were 'held message, ignore it'"
```

The parent/child form of the same path also ran clean: `vparent` delegated `worker-1`, ended
its turn (`stop_gate_waived reason=live_children`, `turn_end` 1786494271), was not pinged, and
both rows finished `done` at 1786494494.

## 6. The reconciler — pings the quiet, spares the rest

* **Pings a genuinely quiet agent:** `vsilent`, 68 s after its turn ended. ✓
* **Does not ping a working one:** `vlong`, `vhold`, `vcrash` each held `turn=working` for
  150 s+; zero `reconcile_ping` events for any of them. ✓
* **Does not ping a waiting orchestrator with live children:** `vparent` ended its turn at
  1786494271 with `worker-1` running and was never pinged; `stop_gate_waived` records why. ✓
* **Does not ping a freshly spawned one:** the `session_id IS NULL` + `STALL_GRACE` guard still
  holds — `vsilent` ended its first turn at 1786493624 and was not pinged until 1786493692. ✓

**One thing to be aware of, not a defect.** `stalled` has no idle threshold of its own, so an
agent whose turn ends without a report is `<< STALLED` on the board within a second, and the
reconciler can ping it on the next tick. `vpoke` was `stop_gate_blocked` at 1786494088 and
`reconcile_ping`ed at 1786494091 — two nudges, three seconds apart, for one silence. The rule
is unchanged by this branch, but the branch makes the trigger instant and reliable where it
used to be a lagging screen-scrape, so this will be seen much more often than it was.

## 7. The declared-unproven gap — CONSTRUCTED, and it behaves as feared

The author could not build "a hook that fails to write while the pane survives". I built it, in
clone2, without touching production code:

1. `vstuck` started a 90 s foreground call; confirmed `state=working turn=working`.
2. At 1786494271, while it was mid-call, I made the store unopenable: `chmod 000 state.db`.
3. Its turn ended around 1786494400 (herdr `agent_status` went `working` → `done`).
4. At 1786494435 I restored `chmod 644`.

Result, verbatim:

```
{'name':'vstuck','state':'working','turn':'working','session_id':None,'ended_at':None}

AGENT   ROLE          STATE     HERDR    MAIL   AGE   IDLE  WORKSPACE
vstuck  orchestrator  working   done        -    2m     2m  vstuck
1 agents · 1 alive
```

No `turn_end`, no `stop_gate_blocked` — the hook failed open in both halves. The row now says
`working` for an agent that is quiet, and:

* it is **not** `stalled`, so the reconciler will never ping it;
* it is **not** `signal_drift` — herdr says `done`, not `unknown`, so `<< NO SESSION` never
  fires. The author's second cross-check does not reach this case;
* it is **not** `gone` — the pane is alive. The first cross-check does not reach it either;
* `sb cleanup vstuck` → `refused vstuck: working, not finished — it has not reported an end`;
* `--when-idle` mail is held **forever**: `sb tell vstuck "held forever?" --when-idle` →
  `ring_deferred` at 1786494454, still undelivered 30 s later and permanently thereafter.

**Both cross-checks the write-up names are the wrong shape for this failure.** What actually
surfaces it is a third thing the write-up does not claim: the UNDELIVERED flag.

```
vstuck  orchestrator  working   done        1     3m    30s  vstuck   << UNDELIVERED 1, 30s
NEEDS YOU
  vstuck  1 never announced to it, oldest 30s  →  sb inspect vstuck
```

So the row is loud *if and only if* somebody sends it mail. With no mail it reads `working`,
quiet, unflagged, indefinitely. Any prompt to the agent repairs it (the next
`UserPromptSubmit` writes `working`, the next `Stop` writes `idle`) — but nothing in the fleet
will ever send that prompt, because the two mechanisms that would (the reconciler and the
doorbell) are the two that gate on the stuck value.

**How plausible is this outside my `chmod`?** More plausible than "exotic". Three real paths:
`store.set_turn` swallows `sqlite3.OperationalError` silently, which includes *database is
locked* once the busy timeout is exhausted; `hooks.run` catches every exception and returns
`{}`; and the `Stop` hook entry has `"timeout": 10` in the settings file, and a hook that
times out fails open. Under fleet-scale contention any of the three produces this state, and
none of them logs anything. **This is the merge's real cost and it should be written down as
such** — before this branch, a lost `Stop` hook cost one gate nudge and the status still
self-corrected from herdr; now it costs the row permanently.

I did not attempt to reproduce it via lock contention rather than `chmod` — that is
endurance-shaped and out of scope. What is proved is the consequence, not the frequency.

## 8. `signal_drift` — still unproven, and I could not prove it either

Same reason as the author: to get herdr's `unknown` you need a pane that outlives its `claude`
process, and `herdr agent start` does not set one up that way. My `chmod` construction (§7)
produced the *state* `signal_drift` exists for and did **not** trigger it, which is a useful
negative result: the predicate is narrower than the failure it is named after. Unit tests are
all it has. Time-boxed and stopped, as the brief allowed.

## 9. Tests and acceptance

`/Users/andrew/anaconda3/bin/python -m pytest tests`, in the clone, on `activity-signal`:

```
1142 passed in 69.80s (0:01:09)
```

Matches the author's number exactly.

## 10. Acceptance verdicts, verbatim

`./acceptance/accept.py activity-signal`, run from the clone, all four checks in parallel,
started 1786494676:

```
switchboard fleet acceptance — branch activity-signal, cloned from …/scratchpad/clone
run sbp9nikh — logs and evidence: /var/folders/5r/8xg52c651zxg199r33s0fsy00000gn/T/accept-sbp9nikh

  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [43s]
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 52s later; the parent woke and read it   [2m13s]
  3  a block holds until the human answers    PASS   held 26s against a sibling, released by the human's answer and read it   [1m35s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbp9nikh4-k: blocked, not finished — it has not reported an end'   [48s]

all 4 pass — the fleet is sound   (2m19s)
```

**This contradicts the author on check 2.** They report check 2 FAILing in parallel and
passing only when run alone, and the brief repeats it as a known property. In my run all four
passed *in parallel*, in 2m19s against their 11m39s — and check 2 passed by exactly the path it
exists to force ("deferred … delivered by the doorbell 52s later"). The likeliest explanation
is load: their run shared the machine with their own three proof agents. So check 2 is not
reliably-failing-under-parallel-load; it is flaky under heavy load, and this branch's own
acceptance is clean.

`./acceptance/accept.py main --only 2`, run afterwards from the same clone, started
1786494827:

```
switchboard fleet acceptance — branch main, cloned from …/scratchpad/clone
run sb0h4ltd — logs and evidence: /var/folders/5r/8xg52c651zxg199r33s0fsy00000gn/T/accept-sb0h4ltd

  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 48s later; the parent woke and read it   [1m39s]

all 1 pass — the fleet is sound   (1m43s)
```

Run again, alone, started 1786494945:

```
switchboard fleet acceptance — branch main, cloned from …/scratchpad/clone
run sbecxegm — logs and evidence: /var/folders/5r/8xg52c651zxg199r33s0fsy00000gn/T/accept-sbecxegm

  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 46s later; the parent woke and read it   [1m36s]

all 1 pass — the fleet is sound   (1m40s)
```

**This contradicts the author's "before and after" outright, twice.** They report check 2
FAILing on `main` with `ring_deferred events for the parent: 0` and `lag 0s`, and conclude
"this branch is what makes acceptance check 2 pass again". On this machine, today, `main`
passes check 2 **by the deferred-then-doorbell path the check exists to force** — twice in a
row, 48 s and 46 s of hold. That means herdr's busy detector was working for those parents at
that moment, which is the same intermittency §2 records.

The branch is not therefore pointless — depending on a detector that works sometimes is worse
than depending on one that never does, because you cannot see the failures. But the audit
doc's strongest piece of evidence does not reproduce and the sentence built on it should be
struck before merge.

---

## Everything that behaved differently from what the author claims

1. **"herdr reported idle for every pane"** is not true as a present-tense statement. herdr
   reported `working` for `vcrash` at 1786494117 and `idle` for `vlong` at 1786493670, both
   mid-foreground-call, minutes apart on the same machine. The detector is intermittent. The
   conclusion stands; the sentence overstates.
2. **The `failed` timing.** The author reports `+70s state=failed`. Mine was +158 s
   (`kill -9` 1786494160 → `ended_at 1786494318`), because the debounce needs two separate
   readings and reaping only happens when something runs a reaping `collect`. With a board or
   collector up it will be nearer the author's figure; with nothing looking, the row sits.
3. **The two cross-checks named for the crash case do not cover the hook-failure case.**
   Confirmed live in §7. The author says the two failures are "the same shape and reach the
   same cross-checks"; they are the same shape and reach *neither*.
4. **Acceptance check 2 passes on `main`.** Twice, by the deferred-then-doorbell path,
   1786494827 and 1786494945 (§10). The author's "this branch is what makes acceptance check
   2 pass again" does not reproduce.
5. **Acceptance check 2 does not fail under parallel load here.** All four checks passed
   together in 2m19s (§10), against the author's 11m39s with check 2 FAILing. The brief
   states the parallel failure as known; I contradict it.

## What I did not test

* Fleet scale / lock contention as the cause of a lost edge (§7) — consequence proved,
  frequency not.
* `signal_drift` live (§8).
* Compaction (`PreCompact`), `--resume` firing `UserPromptSubmit`, and `SessionStart`/
  `SessionEnd` — untouched, as the author says.
* The `sb inspect` `state … turn: … herdr: …` line I read in `status.render_detail` but did not
  capture from a live run.
* Hook latency. I did not re-measure the 74 ms figure.
