# The doorbell on merged `main` — is the acceptance failure real?

Run 2026-08-11 13:53–14:02 by agent `prove-doorbell` (role qa), against merged `main`
(`9e7b917`, all six phases), in throwaway `git clone`s under this session's scratchpad,
driven only by each clone's own `./bin/sb`. Two agents spawned, both closed; both clones,
their herdr workspaces and their collectors torn down (see §6). No `pkill`. Nothing in
`switchboard/`, `tests/`, `DESIGN-TRUTH.md` or `BUILD-PLAN.md` was changed; nothing pushed
or merged.

## The answer

**The deferred-then-doorbell path is not healthy on merged `main`, and the acceptance
check's own explanation of its failure is wrong.** The check said the parent "happened to
be idle, so the doorbell was never tested". It was not idle. I forced a parent to be
provably inside a 150-second tool call at the moment its child reported, and the report was
*still* delivered on the spot — no `ring_deferred`, no hold.

The cause is not in `broker.done` or `_ring`, both of which do what
`DESIGN-TRUTH.md:220-224` says. It is one line upstream: `Broker._busy`
(`switchboard/broker.py:4003`) asks herdr `agent list` whether the target's
`agent_status == "working"`, and **herdr on this machine reports `idle`/`done` for panes
that are demonstrably mid-turn**. `_busy` is therefore always False, `_ring`'s `if mode ==
WHEN_IDLE and self._busy(who)` never fires, and *when idle* has silently collapsed into
*next turn* for every caller — `sb done`'s poke to a parent included.

Delivery itself is not broken: the ring goes out, `agent prompt` queues it, and the parent
reads it at its next turn boundary. What is lost is the design's hold, and two things that
hang off the same broken input (§4).

## 1. The acceptance failure, reproduced

`acceptance/accept.py main --only 2`, run from a clone of merged `main`
(evidence: `…/scratchpad/runs/accept-sbcqnj9r/run.log`):

```
  2  a child's report wakes its parent   FAIL   the report was delivered directly, so the
     doorbell was never the thing that woke the parent — this run did not test it   [1m30s]
      child reported at 1786481642, delivered_at=1786481642 (lag 0s)
      ring_deferred events for the parent: 0
      collector doorbells 0 -> 0, last at None, error=None
      parent summary: 'WOKEN [1] [sb: from sbcqnj9r2-c] [done] CHILD-sbcqnj9r2'
```

Same headline as the two runs before it. Note `doorbells 0 -> 0`: nothing was ever
deferred, so the collector's doorbell had no work — this run did not exercise it either.

## 2. The parent was busy, and the report was delivered anyway

The check holds its parent for 45 s, which leaves room to argue about timing. I re-ran the
same shape with a 150 s hold, in my own clone of `9e7b917`, driving `dbclone/bin/sb`
(script: `scratchpad/probe.py`, log: `scratchpad/probe-busy.log`). Parent task, verbatim in
shape with the check's: `sb delegate '<child: sb done "PROBE-pdb1">' --name pdb1-c && sleep
150` as ONE shell command, then end the turn.

| time | what, and where it is recorded |
|---|---|
| 13:57:0x | parent `pdb1-p` enters the single shell command (`sb delegate … && sleep 150`) |
| 13:57:17 | child `pdb1-c` runs `sb done "PROBE-pdb1"` — `events`: `pdb1-c done` |
| 13:57:17 | message row: `created_at 13:57:17`, **`delivered_at 13:57:17`** — rung on the spot |
| 13:57:17–13:59:44 | `read_at` NULL for **147 seconds**, sampled every 5 s from read-only sqlite |
| 13:59:45 | `read_at` set — the parent came out of `sleep 150`, read its inbox |
| 13:59:53 | `pdb1-p done`, summary `WOKEN [1] from pdb1-c: [done] PROBE-pdb1` |

`ring_deferred` events for `pdb1-p`: **0**. The 147 seconds between delivery and reading is
the proof the parent was mid-tool-call when the ring went out: a prompt sent to a busy pane
sits queued until the boundary, which is precisely what happened.

Herdr's own view of that parent, polled every 2 s across the whole window
(`herdr agent list` → `agent_status`): **`done` the entire time**, never `working`.

## 3. herdr is not reporting `working` for anything on this machine

Not specific to my clone. `herdr agent list` sampled 5 times over 20 s at 13:57:47–13:58:03,
while I — agent `prove-doorbell` — was inside one continuous `bash` tool call the whole
time:

```
[('claude','idle'), ('claude','idle'), ('accept-phase1-4b','idle'), ('main-7','idle'),
 ('tell-modes','idle'), ('phase4-removals','idle'), ('finalise-stack','idle'),
 ('prove-doorbell','idle'), ('features-doc','idle'), ('pdb1-p','done'), ('pdb1-c','idle')]
```

Every sample identical; no pane in the live fleet or my clone ever read `working`.
(`done` is not a fourth state we set — per `reference/herdr-state-authority.md` §5 it is
herdr's read-side rendering of `idle` for a pane no client has focused.)

This is environmental, not something phases 3–6 wrote: nothing in `switchboard/` sets
`working` — `Herdr.report_state` is called by nothing in the broker any more, deliberately
(`broker.py:4506`), and the value only ever comes from herdr's own detector. It also used
to work: `audit/acceptance-script.md` records check 2 passing on 2026-08-10 with
`ring_deferred` and a 43 s hold, on the same herdr 0.8.0. Something on the herdr /
Claude-Code side stopped flipping panes to `working` between then and now. A near-miss of
the same shape is already on file — `BUGS.md:220`, "busy-test is STALLED: herdr idle, store
'working'".

I did not find *why* herdr's detector stopped; that is outside this repo.

## 4. What else rides on the same broken input

Both observed, not inferred:

- **Busy agents are reported `stalled`.** `status.py:539` marks an agent stalled when the
  store says running and herdr says idle-like. The collector's snapshot for `pdb1-p`, taken
  while it was inside `sleep 150`, reads `"state":"working","herdr_state":"done",
  "stalled":true` and `"stalled":1` in the counts.
- **The reconciler pings healthy busy agents.** `collector.run_reconciler` fires on
  `a.stalled`. In the acceptance clone it fired against the parent one second after it
  started working — `events`: `reconcile_waived {"reason": "live_children", "target":
  "sbcqnj9r2-p"}` at 13:53:55. It was waived only because that parent had a live child; a
  busy agent without children has no such exemption.

## 5. The idle case, for contrast — correct

With `pdb1-p` genuinely idle (reported done, pane alive), I ran the child's report again at
the moment of my choosing, as the child (`HERDR_PANE_ID=wVM:p3 ./bin/sb done
"PROBE-IDLE-pdb1"`, run from inside the clone):

- 14:00:18 created, 14:00:18 delivered, **14:00:23 read**, 14:00:32 the parent reported.

Direct delivery to an idle parent is right and is not masking anything: `_ring` has nothing
to defer, the parent wakes in five seconds. The busy case above and this one take the
*same* code path today — that is the defect.

## 6. What the acceptance check should say

Check 2 is testing the right thing. `sb done` is specified to use *when idle*
(`DESIGN-TRUTH.md:220-224`), so demanding the deferred path is not a check that has drifted
from the design — a healthy fleet would defer here, and this one does not.

What is wrong is the check's **verdict when the ring is direct**. It cannot tell
"the parent was idle, so there was nothing to defer" (a coverage miss) from "the parent was
mid-turn and we rang anyway" (a defect), and it prints the first as if it were established.
That sentence is what sent the last two runs away with a benign explanation for a real
fault. Suggested change, ~20 lines in `check_doorbell`, no change to the criterion:

1. At the moment the child's message row appears, record herdr's `agent_status` for the
   parent (one `herdr agent list`, read-only — it runs no `sb` in the clone, so the
   measurement stays clean).
2. Also record how long `read_at` stays NULL after `delivered_at`. A delivered-but-unread
   gap of tens of seconds is independent proof the parent was inside a tool call.
3. Split the failure: parent `working` (or unread for ≫ a turn boundary) → **"the parent was
   mid-turn and the report was rung at it anyway — when-idle did not defer"**; parent
   genuinely idle → the existing "this run did not test it", which is then honestly a
   coverage miss and should arguably be an ERROR (inconclusive), not a FAIL.

Not changed here, as briefed.

## 7. Size of the fix

- The check: small, ~20 lines, in `acceptance/accept.py`.
- The behaviour: `broker.py` needs no logic change — it asks the right question. What is
  needed is a `_busy` that gets a true answer: either herdr's detector reporting `working`
  again (an environment/herdr fix, size unknown from here, and `DESIGN-TRUTH.md:236-247`
  says herdr's status is where this should come from), or a second source of truth for
  "mid-turn" in `_busy` — which is a design decision, not a QA call.

## 8. What I did not prove

- **The collector's doorbell itself.** Neither run reached it: nothing was ever deferred, so
  it had no work (`doorbells 0 -> 0`). Its build-and-cwd correctness was measured on
  2026-08-10 in `audit/doorbell-path-proof.md` and I did not re-measure it. I could not
  force the deferred path without making herdr lie about a pane, and the one call that
  would do it (`pane report-agent`) permanently evicts the agent's name.
- **Why herdr stopped reporting `working`.** Outside this repo; not diagnosed.
- **Checks 1, 3 and 4** — I ran only check 2.
- I did not test whether a blocked target still holds mail (`ring_held`); that guard is
  independent of `_busy` and check 3 covers it.

Suite on this branch, unchanged code: `python -m pytest tests` → **1128 passed**.

## Teardown

`sb cleanup pdb1-c pdb1-p --force` → `closed: pdb1-c, pdb1-p`; `herdr workspace close wVK`;
the clone's collector SIGTERMed by pid after `ps` confirmed it was
`python -m switchboard.collector` (pid 16924); `~/.herdr/worktrees/dbclone` and the clone
deleted. The acceptance run tore down its own clone. Afterwards `herdr agent list` and
`herdr workspace list` carry no `pdb1*`/`sbcqnj9r*` row, and `~/.herdr/worktrees` has no
`dbclone`. Only the logs under the session scratchpad remain.
