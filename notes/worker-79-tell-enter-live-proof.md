# Confirm-and-repair for a dropped Enter — what was built, and what the live runs proved

Implementation of `notes/reviewer-25-tell-confirmation-design.md` §3. All live work ran in
an isolated `git clone` at `<scratchpad>/w79-clone`, driving its own `./bin/sb` against a
throwaway herdr workspace `w1JQ` (label `w79-tell`, one pane, one agent `w79-target`).
Torn down — §5.

---

## 1. The change

| where | what |
|---|---|
| `output._submitted_text` | a `queue-operation`/`enqueue` record counts as an arrival, not only a `user` record. `remove` does not |
| `output.submitted_since` | the same proof narrowed to ONE session file, for a target whose session id is already known |
| `Broker._ring` | a successful non-interrupt ring logs `ring_sent` (agent, text, time, `repair` flag). `delivered_at` unchanged |
| `Broker._confirm_rings` | the second pass in `flush_pending`: confirm, or re-send, or give up |
| `Broker._last_ring` | reconstructs one ring's state from the event log — no schema change |
| `Broker._claim_repair` | takes an attempt slot inside `BEGIN IMMEDIATE`, before the send — §6 |
| `apply_preset` | `repair=False`: recorded, never re-sent |
| `defaults/settings.toml` | `timeouts.ring_settle = 45.0`, `retries.ring_repairs = 2` |
| `status.DONE_TO_THE_AGENT` | the five new `ring_*` kinds, or every doorbell would reset the target's idle clock |

**The settle window is 45 s, not the ~5 s the design note proposed.** A busy target's queue
record was readable at 2.29 s, but an idle target writes no queue record and its `user`
record took 14.59 s — and `deliver_working_ms` and `Herdr._took_prompt` both put that same
flush at **35 s** under a six-way fan-out. At 5 s the repair would fire on most correct
deliveries to an idle agent, and the duplicate is not free: the first doorbell has already
started its turn, so the second arrives mid-turn and buys the agent an extra turn to find an
empty inbox. 45 is the cited worst case plus about one collector tick.

It shipped at 30 s first, which was below the 35 s its own comment cited — qa-12 caught it
(§6). Flat rather than the conditional stretch `_took_prompt` uses for the identical lag,
because nobody waits on this window: `deliver`'s is a blocked sender, so it must be short by
default; this one is staleness, so a longer flat number costs nothing, while the stretch
would hang on `_busy`, whose detector has gone dark for every Claude pane on the machine
before — and wrong there means the short window, which is the repair the stretch was for.

## 2. What the live runs proved

The reproduction is a `herdr` shim first on `PATH` that turns `agent prompt` into
`pane send-text` — the literal text into the box, no Enter, rc=0 and the ordinary success
envelope. That is the bug exactly as switchboard sees it. Everything else is the real
binary and the clone's real `sb`.

| run | setup | result |
|---|---|---|
| **A** | ordinary `sb tell` to an idle target | `ring_confirmed {"after": 55, "repairs": 0}`. **Not** re-sent — the false-positive case |
| **B** | Enter dropped (`pane run`, which lost its own Enter here) | box held the unsubmitted doorbell; repaired; agent took it; `ring_confirmed {"repairs": 2}` |
| **C** | same shim, `pane run` submitted this time | `pane run` sends text *and* Enter, so it is not a reliable repro. Confirmed at 101 s, 0 repairs |
| **D** | Enter dropped (`pane send-text` — deterministic) | box: `❯\xa0[sb: from human] You have mail…`, `sb tell` said "sent". **Four back-to-back `sb` commands produced exactly one repair.** The repair submitted it; `ring_confirmed {"after": 103, "repairs": 1}` |
| **E** | every send's Enter dropped, shim left on `PATH` | `ring_sent` → `ring_repaired 1` (+35 s) → `ring_repaired 2` (+35 s) → `ring_unconfirmed {"reason": "exhausted", "repairs": 2}`. Two further passes did nothing |

**Run B found a real defect, and it is fixed.** The settle window was measured from the
original send, so once a ring was older than it, it was older than it *continuously* —
`flush_pending` runs at the head of every `sb` command, so the `sb flush` and the `sb log`
after it repaired inside the same second, the second send going out before the first could
possibly have been taken. The window is now measured from the last attempt (`_last_ring`'s
`last`), which run D re-proved.

Also observed: `agent prompt` into a dirty box **appends**. After run B's two repairs the
box held three concatenated doorbells and they went in as one prompt. Harmless for a
doorbell — the agent saw one message — but it is why the repair for `apply_preset` would be
worse than the failure.

And the workspace-trust modal reproduced again at spawn: `agent start` returned with
`❯ 1. Yes, I trust this folder` on screen and the start prompt swallowed whole. That is the
hazard `herdr.py:648-655` names and the reason the repair never presses Enter.

## 3. Tests

Three, per the standing rule. `python -m pytest tests`: **1336 passed**.

- `test_output.py::test_a_prompt_queued_behind_a_running_turn_has_arrived` — the record
  shape, on captured JSON. Fresh `enqueue` counts; one older than `since` does not; `remove`
  does not. No fake herdr involved.
- `test_broker.py::test_a_doorbell_the_busy_target_queued_is_confirmed_not_sent_again`
- `test_broker.py::test_a_doorbell_nothing_recorded_is_re_sent_and_then_given_up_on` — also
  pins the per-attempt window run B found.

`test_an_interrupt_is_delivered_confirmed_and_a_doorbell_is_not` (`:1297`) passes unchanged;
nothing was removed from `tests/test_broker.py`.

## 4. Not proven

- **`when-idle` end to end.** Every live run went through `next-turn` (`sb tell`'s default).
  `done`'s parent poke and `flush_pending`'s own re-ring are when-idle and take the same
  path, but were not driven live.
- **`apply_preset`.** Excluded from the repair by design, so a preset whose Enter is dropped
  is still stranded — unchanged from today, and now at least logged.
- **Under real machine load**, the condition Andrew hit. The shim drops the Enter
  deterministically on an idle machine; it does not reproduce the timing that causes it.
- **Non-Claude agent kinds.** The proof is Claude-Code-specific, exactly as `task_arrived`
  already was. A `codex` agent writes no such records, so its rings would log
  `ring_unconfirmed` or be repaired twice for nothing. Not checked.
- **`ring_settle` against a genuinely slow flush.** 30 s clears the two measurements there
  are; both are single readings on an idle machine.
- ~~**Concurrency.**~~ Closed in §6 — it was a real defect, not a caveat.

## 5. Teardown

`herdr pane close w1JQ:p1` — the only pane, and herdr retired the workspace with it.
(§6's runs create no pane at all — a `herdr` shim intercepts `agent prompt` — so there is
nothing to tear down for them.)
Workspace count 15 → 14, and the fourteen are the fourteen that pre-dated the run. No
`pkill`, no `herdr workspace close`. The live fleet's store has no `w79` row and no `ring_*`
event in it. The clone and the shim are left in the session scratchpad as evidence.

---

## 6. The two defects qa-12 found, and what closing them proved

`notes/qa-12-tell-enter-adversarial-review.md`. Both closed in `d22d6b5`.

### 6a. The repair cap did not hold across processes — fixed and proved both ways

`_confirm_rings` read the attempt count, tailed a transcript, and only then logged
`ring_repaired`, with nothing held across the gap. `flush_pending` runs at the head of every
`sb` command, so concurrent commands all read the same stale count and all sent.

The attempt is now claimed by the row, written inside `BEGIN IMMEDIATE` before the send
(`_claim_repair`), and that row is what `RING_REPAIRS` counts. `BEGIN IMMEDIATE` rather than
`_fork_lock`'s `fcntl` file because the contended thing IS the store and SQLite already
serializes writers; two statements inside, no herdr call and no file read.
`ring_repair_failed` stopped being counted — it annotates the `ring_repaired` that claimed
the slot rather than spending a second one.

| run | before (`19f9541`) | after (`d22d6b5`) |
|---|---|---|
| qa-12's script, 2 threads | 2 sends, both `attempt: 1` | 2 sends, `attempt: 1` then `2` |
| qa-12's script, 4 threads | **4 sends**, all `attempt: 1` | **2 sends**, `attempt: 1` then `2` |
| 6 real `sb` processes | **4 sends**, all `attempt: 1` | 1 send |
| 6 real `sb` processes (repeat) | — | 1 send |
| 8 real `sb` processes | — | 2 sends, `attempt: 1` then `2` |

**The OS-process rows close qa-12's own "not proven".** `<scratchpad>/race_procs.sh`: one
agent with an aged unconfirmed ring and a transcript that exists and proves nothing, `HOME`
pointed at a scratch dir so nothing touches the real `~/.claude`, a `herdr` shim first on
`PATH` that records each `agent prompt` and returns the ordinary success envelope. Then N
`./bin/sb log` launched at once. No threads, no injected sleep, no shared interpreter — and
the pre-fix code blew the cap of 2 with four sends anyway.

Where the post-fix runs land 1 rather than 2 it is the per-attempt settle window winning
before the claim is reached: the first process's `ring_repaired` row is already committed by
the time the others read. Both guards are doing their job, and only the threaded runs — with
qa-12's injected sleep holding every reader inside the gap together — isolate the claim on
its own. That is why both are reported.

### 6b. `ring_settle` 30 s → 45 s

30 sat below the 35 s flush lag its own comment cited. See §1 for the reasoning and for why
it is a flat number rather than `_took_prompt`'s conditional stretch. **Not measured here** —
this is a parameter set from figures the codebase already measured, and both of those are
single readings on an idle machine, so the true worst case could still be past 45 s.
