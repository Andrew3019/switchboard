# Message delivery, measured — `interrupt` vs `tell` (busy) vs `tell` (idle)

Run 2026-08-10, 21:13–21:26 local, by `delivery-experiment` (qa). Nothing was changed;
this is measurement only.

**Where.** An isolated `git clone` of the repo at `b2a3e47` (current `main`, phases 1 and
2 merged), driven by that clone's own `./bin/sb`, its own store
(`<clone>/.git/agentflow/state.db`), its own collector (`sb doctor`: `panel pid 16680`).
The live fleet was never touched.

**Subjects.** `sb start expt-top` (top orchestrator) delegated three workers —
`subject-one`, `subject-two`, `subject-three` — each with the identical task in
`audit/delivery-modes/subject-task.md`: read twenty named files one at a time, `date
+%H:%M:%S` before each, append one summary line per file to its own log with `>>`, `sleep
5` between files, and — the measurement — the moment it becomes aware of any message,
append a line giving the time, the file number, mid-step or between steps, how it became
aware, and the exact text. ~18–21 s per file, so ~20 turn boundaries per subject over ~7
minutes. The top then blocked and did nothing else.

**Evidence.** The three subject logs and the store dumps are in `audit/delivery-modes/`.
Log timestamps come from `date` inside each agent; delivery timestamps come from the
store (`messages.created_at` / `delivered_at` / `read_at`), which is the authority.

## The three measurements

| | subject-one — `sb interrupt` | subject-two — `sb tell` while busy | subject-three — `sb tell` while idle |
|---|---|---|---|
| sent | 21:16:57 | 21:16:58 | 21:25:02 |
| command printed | `interrupted subject-one` | `sent to subject-two (subject-two mid-turn or blocked — will be rung when free)` | `sent to subject-three` |
| store `delivered_at` (ring) | 21:16:58 | **21:22:24** | 21:25:02 |
| store `read_at` | 21:16:58 | 21:22:35 | 21:25:19 |
| agent logged awareness | 21:17:10 | 21:22:35 | 21:25:08 (doorbell), 21:25:22 (body) |
| latency, sent → aware | **13 s** | **5 min 37 s** | **6 s** |
| what it was doing | between steps: file 8/20 logged, five-second sleep done, file 9 not started | nothing left — all 20 files done at 21:21:59 and `sb done` already called at 21:22:15 | nothing left — finished 21:22:43, idle 2m19s |
| how it became aware | "text appeared in my prompt" — the instruction itself, inline | "text appeared in my prompt" (`You have mail. Run: sb inbox`), then read the body with `sb inbox` | same two-step: doorbell in the prompt, body via `sb inbox` |
| store events | `interrupt {"stopped": true}` at 21:16:58 | `ring_deferred` at 21:16:58, and nothing else until the ring | none — rung on the spot |

### What each one actually did

**`sb interrupt` lands immediately and cancels the work.** One `ring_deferred`-free path:
`esc` to herdr, a settle pause, then a forced ring carrying the instruction itself
(`broker.interrupt` → `_ring(force=True)`, `broker.py:3840`). Store shows created =
delivered = read at 21:16:58, one second after I pressed return. The agent's own account
puts awareness 13 s later at 21:17:10 — that gap is the cancelled turn restarting and the
model writing its log line, not queueing. It landed *between* steps by luck of timing (it
had just finished a `sleep 5`); nothing waited for that boundary. The wrapper text is
`prompts.toml` `notify.interrupt` — "[INTERRUPT — stop now] The instruction you were
following is cancelled; do not resume it." — so subject-one stopped at file 8 of 20 and
reported done. That is the verb working as designed, but worth saying plainly: **an
interrupt is not a message, it is a cancellation with a message attached.** There is no
way today to put text into a busy agent's turn without also telling it to abandon its
task.

**`sb tell` to a busy agent waits for idle, and here that was 5 min 37 s.** The message
was durable in the store at 21:16:58 with `ring_deferred` logged, and it was *not*
delivered at any of the roughly nineteen turn boundaries subject-two crossed in the next
five and a half minutes — it read fourteen more files, wrote fourteen more log lines, and
logged at 21:21:59 "no message of any kind arrived at any point during the run". The ring
fired at 21:22:24, nine seconds after subject-two called `sb done` at 21:22:15 — i.e. the
collector's doorbell tick (`collector.DOORBELL_GAP = 10.0`), not anything I ran. The
subject noticed at 21:22:35 and had to correct the "done" it had already filed. Note the
idle threshold in practice: `_busy` is herdr's `working` state, which stayed true right up
to `sb done`. Mail to a working agent does not land at a step boundary, a tool boundary,
or a lull — only when the whole turn ends.

**`sb tell` to an idle agent lands immediately.** Delivered in the same second it was
sent, no `ring_deferred`, visible to the agent 6 s later.

**Phase 2's "a finished agent is reachable again" is confirmed.** Subject-three had
already reported done before *both* tells. Both were delivered in the same second they
were sent (`messages` rows 7 and 9), both produced a `revived` event, and the agent read
and logged both bodies (21:25:22 and 21:25:56). Nothing was lost and nothing needed
`sb restore`.

## Answers to the questions asked

- **Does `sb interrupt` land immediately, mid-step, or at the next step boundary?**
  Immediately — same second, mid-turn, cancelling. Not at a boundary.
- **Does `sb tell` to a busy agent wait for idle, and how long?** Yes. 5 min 37 s here,
  and the number is entirely "how long until that agent's turn ends", plus up to 10 s of
  collector tick. It is unbounded in principle: a subject that ran for an hour would hold
  the message for an hour.
- **Does `sb tell` to an idle agent land immediately?** Yes, same second, twice out of
  twice.
- **Is there a real difference today between "next turn" and "interrupt"?** No — there is
  no "next turn" path in the product at all. `interrupt` is the only thing that puts text
  into a live turn, and it always sends `esc` first (`stop=True` default; the `stop=False`
  argument exists on `Broker.interrupt` but no CLI flag reaches it) and always wraps the
  text in the cancel-your-work template. So the two are the *same code path* only in the
  sense that "next turn" does not exist to differ from it. **This corrects BUILD-PLAN.md
  §3.1**, which says *next turn* "is the herdr path that only `sb interrupt` uses
  (`force=True`)": the forced ring is necessary but not sufficient — as shipped it is
  bundled with an escape keypress and a cancellation prompt, so lifting it into a
  non-cancelling mode is more than exposing an existing path. The rest of §3.1 holds:
  *when idle* is what `tell` does today, and the line reference has moved (the hold is
  `broker.py:4207` in `_ring`, via `_busy`, not `broker.py:3348`).
- **Did anything arrive that the agent never noticed, or get noticed without arriving?**
  No. Every one of the four messages sent shows `read_at` set, and every one appears in the
  right subject's log with its exact text. No phantom awareness, no silent loss.

## Two things I was not asked about, found while measuring

Reported, not fixed.

1. **A blocked orchestrator is deaf to its children.** `expt-top` blocked at 21:15:5x.
   All six `done` reports its children filed (store rows 3–6, 8, 10, from 21:17:19
   onward) logged `ring_held {"reason": "blocked"}` and were still undelivered when I tore
   the fleet down eleven minutes later. That is exactly what DESIGN-TRUTH says should
   happen ("when-idle mail is held until its block is answered"), so it is not a defect —
   but it means an orchestrator that blocks while children run learns nothing until a
   human answers it, and `sb status` shows it as `UNDELIVERED 1` the whole time.
2. **A `tell` that lands after `sb done` makes the agent re-report.** Subject-two filed
   `done` at 21:22:15, got the held message nine seconds later, and filed a second `done`
   at 21:22:56 correcting the first. Its parent, when it reads its mail, will see two
   contradictory summaries from the same child. A consequence of when-idle delivery, worth
   knowing before 3.1.

## What I did not test

- Only one message per agent (plus a second to subject-three); no queueing of several
  messages behind one busy agent, and no ordering check.
- No agent-to-agent `tell` — every message here was sent as the human (which reaches the
  same `_ring` and hits the same `_busy` defer; `answer=True` only skips the *blocked*
  check, not the busy one). An agent sender was not exercised live.
- `sb interrupt` was tested once, on an agent that happened to be between steps. I did not
  catch one mid-file-read, so "cancels a tool call in flight" is inferred from
  `stopped: true` and the code, not observed.
- No test of `interrupt` against a blocked or a finished agent (the finished case is
  refused in code before the escape, `broker.py:3857`).
- Nothing about latency under load, or with no collector running.

## Reproducing

`audit/delivery-modes/subject-task.md` is the verbatim subject task.
`audit/delivery-modes/subject-{one,two,three}.log` are the raw logs.
`audit/delivery-modes/store-messages.txt` and `store-events.txt` are the store dumps the
table above is built from.
