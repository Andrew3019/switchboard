# Group 2 — task delivery into the pane (typed but not sent)

Triaged against HEAD `fb04859`. One underlying fault runs through all four reports; the
*silence* the three older ones complain about is genuinely fixed, the *mechanism* is not.

No live run was needed and none was done. The 2026-08-14 incident left its own durable
artifacts on this machine (the failed agents' Claude Code transcripts, and the reporting
agent's session with exact clock times), and the delivery path has not been touched since:
`switchboard/output.py` last changed functionally on 2026-08-10 (`d1f73db`),
`switchboard/herdr.py` last changed on 2026-08-13 and only in docstrings (`264ea08`), and
no commit after 2026-08-12 touches `Broker._spawn`'s delivery block. So the code that
produced that failure is the code at HEAD. Everything below is `by reading`, with the
incident's artifacts read as evidence — it is not a repro.

---

## 2026-08-14-172112-sb-delegate-exits-1-with-task

**Verdict:** STILL BROKEN
**Severity:** high
**Evidence:** By reading, plus the incident's own transcripts. Reconstructed timeline for
`qa2ws2` from `~/.claude/projects/...-sbclone-qa2ws2/0a12aeb3-….jsonl` and the parent's
session `…-qa-2-…-scratchpad-sbclone/a02545ca-….jsonl`:
`sb delegate` started `00:15:09.264Z`; the task was submitted into the child and written to
its transcript at `00:16:32.619Z`; `sb delegate` exited 1 with `task_undelivered` at
`00:16:33.475Z` — **it gave up 0.9 s after the proof it was waiting for hit disk.** The
transcript record holds the task text *twice*, `"Read notes/qa2-mid2-task.md and do exactly
what it says.\nRead notes/…"`, which is retry #1 pasted-not-submitted and a later retry
submitting both at once. Elapsed 84 s = 3 × `deliver_ms` (20 s) + backoffs with no
`deliver_working_ms` stretch, so `Herdr._running_turn` said "not working" at every deadline
(herdr's state lags a just-submitted prompt). `Broker._spawn` then asked `_took_a_turn`
(broker.py:3287), which consults only the store row and one instantaneous herdr probe —
never the transcript — so it also said no, and broker.py:3281-3285 stamped `GONE_STATE`
over a live agent and raised. Second half of the report is the same bug's other tail:
`qa2solo` never got a transcript directory at all, i.e. both pastes sat unsubmitted in its
prompt box; `deliver`'s recovery is only another `agent prompt`, and nothing in HEAD ever
sends an `enter` or clears a stuck box (`Herdr.send_keys` exists but no delivery path uses
it — the only caller is the interrupt at broker.py:4015).

**Issue title:** A spawn whose task arrived seconds before the delivery deadline is stamped
failed, and a task left unsubmitted in the prompt box is duplicated rather than rescued

**Issue body:**
`sb delegate` confirms delivery by watching for the task text in the child's own Claude Code
transcript (`output.task_arrived`). Two failures follow from how the giving-up is done.

1. **False negative.** `Herdr._took_prompt` polls for the proof only until its deadline. When
   the proof lands after the last poll, `deliver` raises, and `Broker._spawn._took_a_turn`
   (broker.py:3287) — the safety net meant to catch exactly this — asks only the store row
   and one live herdr probe, never the transcript. herdr has not caught up to a
   prompt submitted a second ago, so a working agent is recorded `GONE`/failed and
   `sb delegate` exits 1. Measured in the filed incident: proof written `00:16:32.619Z`,
   give-up `00:16:33.475Z`. The parent is then told to treat a running agent as lost, which
   costs either a duplicate agent on the same work or a force-closed pane.
   Fix shape: have `_took_a_turn` call `output.task_arrived(cwd, task, since=<first send>)`
   before it concludes anything — cheap, decisive, and the same evidence `deliver` trusts.
2. **Retry duplication, no rescue.** When the first prompt pastes without submitting,
   `deliver`'s retry is another `agent prompt` into a box that already holds the text. Either
   both copies are submitted as one message (seen on `qa2ws2`) or nothing is (seen on
   `qa2solo`, which never started a session at all and was left holding two pasted copies).
   `deliver`'s docstring claims the re-send "types and presses enter, carrying the stuck text
   in with it"; the incident shows that is not reliable. Nothing clears the box or sends an
   explicit `enter`, though `Herdr.send_keys` could.

Lives in `switchboard/herdr.py` (`deliver`, `_took_prompt`, `_running_turn`) and
`switchboard/broker.py` (`_spawn`'s delivery block, `_took_a_turn`).

**Same-as:** 2026-08-09-151916, 2026-08-08-023237 (same paste-without-submit mechanism),
2026-08-09-161323 (same family, other tail).

---

## 2026-08-09-161323-second-spawn-failure-mode-agent-starts

**Verdict:** PARTLY FIXED
**Severity:** medium
**Evidence:** By reading. Filed against `caa6d20`, before the delivery work landed.
*Fixed half — the silence:* the spawn no longer returns a name on an unverified single
`agent prompt`. `c7e648d` (2026-08-09) made delivery part of the spawn, `f0fa70c`
(2026-08-10) made the confirmation the child's own transcript rather than herdr moving, and
`1f81ebb` (2026-08-10) split "unconfirmed" from "failed". An empty-prompt agent is now
re-sent up to `retries.deliver_attempts` = 3 times and, failing that, surfaced as
`task_undelivered` instead of reported as a success.
*Not fixed — the cause:* two commits attack the likeliest mechanism of a paste that never
lands (`4972bfc`, 2026-08-11, proves the pane's shell answers before anything is typed into
it; `1120221`, 2026-08-12, sends the 12KB system prompt as a path instead of a typed line,
removing the canonical-mode truncation), but the send itself is still an unacknowledged
`agent prompt` and a race there is still possible. Nothing proves it gone.

**Issue title:** covered by the 2026-08-14 issue above — no separate issue; the residue here
is "a prompt can still be lost on the way in", whose detection and reporting is the same
code the 08-14 issue names.

**Issue body:** n/a — folded into 2026-08-14-172112.

**Same-as:** 2026-08-14-172112, 2026-08-09-151916, 2026-08-08-023237.

---

## 2026-08-09-151916-sb-delegate-reports-success-but-the

**Verdict:** PARTLY FIXED
**Severity:** high
**Evidence:** By reading. Filed against `713a1f4`, before the delivery work.
*Fixed half:* the exact complaint — "`sb delegate` printed success, 2 of 3 agents sat for
10 h at a prompt holding `[Pasted text #1]`, store said `working`" — cannot happen silently
now. `c7e648d` + `f0fa70c` + `1f81ebb` mean an unsubmitted paste is retried and then reported
(`task_undelivered`, exit 1, row moved off `working`).
*Not fixed half:* the paste-without-submit itself is unchanged, and the retry can make it
worse rather than better — the 2026-08-14 incident's `qa2solo` was left with the same text
pasted **twice** and unsubmitted, born idle holding its own instructions exactly as described
here. So the agent still wedges; the difference is that the parent is now told.

**Issue title:** covered by the 2026-08-14 issue above (point 2 — retry duplication, no
rescue of a stuck prompt box).

**Issue body:** n/a — folded into 2026-08-14-172112.

**Same-as:** 2026-08-08-023237 (near-identical report, one day apart, same mechanism),
2026-08-14-172112, 2026-08-09-161323.

---

## 2026-08-08-023237-sb-delegate-types-the-prompt-into-the

**Verdict:** PARTLY FIXED
**Severity:** high
**Evidence:** By reading. Filed against `ac3ba9a-dirty`, the oldest of the four and the
original statement of the mechanism ("herdr wrote the prompt text into all three panes and
never pressed enter; the store says `working`; nothing in `sb status` distinguishes this from
a real working agent"). The status half and the silence half are closed by the same three
commits (`c7e648d`, `f0fa70c`, `1f81ebb`): a spawn is not a success until the task is
confirmed in the child's transcript, and a row that could not be confirmed is no longer left
sitting on `working`. The typing-without-submitting half is unchanged and still observed
2026-08-14. Effectively a duplicate of 2026-08-09-151916.

**Issue title:** covered by the 2026-08-14 issue above.

**Issue body:** n/a — folded into 2026-08-14-172112.

**Same-as:** 2026-08-09-151916 (same bug, same words, one day apart), 2026-08-14-172112,
2026-08-09-161323.

---

## What I could not prove

- Whether the underlying `agent prompt` paste-without-submit is a herdr bug or a Claude Code
  TUI timing window. Settling it needs an instrumented run against herdr directly, not `sb`.
- The *rate* today. The 08-14 incident is 2 failures in 3 spawns, but that is one cold
  fan-out in a fresh clone, which the code notes call the worst case.
