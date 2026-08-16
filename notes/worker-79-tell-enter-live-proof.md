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
| `apply_preset` | `repair=False`: recorded, never re-sent |
| `defaults/settings.toml` | `timeouts.ring_settle = 30.0`, `retries.ring_repairs = 2` |
| `status.DONE_TO_THE_AGENT` | the five new `ring_*` kinds, or every doorbell would reset the target's idle clock |

**The settle window is 30 s, not the ~5 s the design note proposed.** The note's own idle
measurement is the reason: a busy target's queue record was readable at 2.29 s, but an idle
target writes no queue record and its `user` record took 14.59 s (and `deliver_working_ms`
records 35 s for the same flush lag under a six-way fan-out). At 5 s the repair would fire
on most correct deliveries to an idle agent — and that duplicate is not free, because the
first doorbell has already started its turn, so the second arrives mid-turn and buys the
agent an extra turn to find an empty inbox. One number in `settings.toml` if that is wrong.

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
- **Concurrency.** Two `sb` processes reaching `_confirm_rings` in the same instant could
  each repair once. Bounded by the cap, not otherwise guarded.

## 5. Teardown

`herdr pane close w1JQ:p1` — the only pane, and herdr retired the workspace with it.
Workspace count 15 → 14, and the fourteen are the fourteen that pre-dated the run. No
`pkill`, no `herdr workspace close`. The live fleet's store has no `w79` row and no `ring_*`
event in it. The clone and the shim are left in the session scratchpad as evidence.
