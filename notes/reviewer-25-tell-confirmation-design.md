# Confirming a plain `sb tell` landed — mechanism review and design

Design only. No production code changed. Everything live was run in an isolated
`git clone` at `<scratchpad>/r25-clone` on `tell-enter`, driving its own
`switchboard/` and a throwaway herdr workspace `w1JC` (label `r25-tell`, one pane,
one agent `r25-target`). Torn down — §7.

---

## Verdict

**Do not route `next-turn`/`when-idle` through `Herdr.deliver`.** Its proof cannot
see a submission to a busy agent, so every correct delivery would look like a
failure; and its `_rescue` step presses Enter on box content nobody has identified.

**Recommended fix: confirm the doorbell OFF the sender's turn.** `_ring` sends
exactly as today and returns; `Broker.flush_pending` — which already runs at the head
of every `sb` command and is already spawned by the collector every ≥10 s — gains a
second pass that asks, of a ring made more than a few seconds ago, whether the
target's own transcript records the submission, and re-*sends* (never presses Enter)
if it does not.

The one reason that decides it: **the confirmation has to cover every doorbell, not
just `sb tell`'s.** Most rings come from `flush_pending` and from `done`'s poke to a
parent, and `flush_pending` is on the critical path of every `sb` command any agent
runs. A sender-side wait is affordable for a `tell` and not affordable there, so the
confirmer has to be something that is not on anyone's critical path — and the
codebase already has exactly one such thing.

**Cost if I am wrong:** a doorbell that our proof cannot see gets re-sent (capped).
A duplicate doorbell costs the recipient one wasted `sb inbox` — it carries no
payload — so the downside is noise, not a lost or doubled message. The upside is
that a dropped Enter, which today strands the message permanently, is repaired
within ~10–20 s.

---

## 1. `Herdr.deliver`'s proof does not work on a busy target — measured

`_deliver_interrupt` builds the proof as `output.task_arrived(cwd, text, since)`
(`broker.py:5504`), and `output._transcripts_with` (`output.py:213-220`) only reads
transcript records whose `type` is `"user"`.

Claude Code does not write a `user` record when it accepts a prompt mid-turn. It
writes a **`queue-operation` / `enqueue`** record at submit time, and only turns that
into a `user`-side record when the turn ends and the queue drains.

Measured, agent busy in a single 200 s `Bash` call, doorbell sent with
`herdr agent prompt`:

| moment | what was true |
|---|---|
| t+0.0 s | box showed the doorbell text |
| t+3.0 s | box showed `❯ Press up to edit queued messages` — Claude Code had taken it |
| t+0 → t+36.3 s | `output.task_arrived(...)` **False on every poll** |
| t+2.29 s (separate run) | the `queue-operation/enqueue` record was readable in the transcript |
| t+3 min 09 s | the `user`-side record carrying the text was written, at the turn boundary |

So on today's predicate, a perfectly delivered next-turn tell is unprovable until the
target's turn ends. `deliver` would therefore, for every such tell:

- burn attempt 1 (`deliver_ms` 20 s, plus the `deliver_working_ms` 60 s stretch,
  which a busy agent always qualifies for — `herdr.py:822-826`),
- then `_rescue` (Enter) + attempt 2, then `_rescue` + attempt 3,
- then raise `not_delivered` on a message that landed.

Order of the sender's wait: **~3–6 minutes**, ending in a false failure. That is the
five-and-a-half-minute regression DESIGN-TRUTH's "It waits for nothing and cancels
nothing" exists to prevent, reintroduced on the send side.

For an **idle** target the proof does work, but not quickly: `task_arrived` first
returned True at **14.59 s** after the send (one measurement; `deliver`'s own
docstring records 35 s under a six-way fan-out). No `queue-operation` record is
written in the idle case — the `user` record is the only evidence.

### This is also a live defect on the interrupt path

`sb tell --interrupt` sends `esc` first, so its target is usually idle by the time
`deliver` runs. When the `esc` does not land, or the agent is working anyway, the
interrupt is queued, the enqueue record is written, and `task_arrived` still says no
— so `deliver` retries with rescue Enters and finally raises `Undeliverable` for an
interrupt that arrived. Filed as a bug against `switchboard/output.py`.

---

## 2. `_rescue` is not safe on a plain tell

`_rescue` (`herdr.py:725-768`) presses Enter on **whatever is in the box**, without
looking. That trade is right for an interrupt — its text *is* the message, and a
second `prompt` would duplicate the payload — and wrong for a doorbell, which
carries nothing and can simply be sent again. Four ways it goes wrong here:

1. **A human's half-typed text gets submitted.** DESIGN-TRUTH (~line 130): "If
   Andrew is halfway through typing when a message is sent, the half-written text
   goes along with it". Today that costs one Enter per send. `deliver` adds up to two
   more Enters at ~20–80 s spacing — Enters at moments nothing was sent, so the
   half-typed text goes in on its own with no message attached to explain it.
2. **A modal gets answered.** Reproduced in this run: `herdr agent start` returned
   `interactive_ready: true` with Claude Code's *workspace trust* dialog on screen
   (`❯ 1. Yes, I trust this folder / 2. No, exit`). An Enter there picks the
   highlighted option. `herdr.py:648-655` already records this class; a rescue Enter
   on a plain tell is a new way to reach it, on live agents rather than only at spawn.
3. **Double delivery is reachable.** `_rescue` returns "rescued" only if the proof
   confirms within `timeout_ms // 4` (5 s). For a busy target the proof never
   confirms (§1), so a successful rescue reads as a failure and `deliver` sends the
   doorbell again — the box then holds two doorbells, submitted together or
   separately. Harmless in content (both say "you have mail"), but it is
   double-delivery of the ring, and on `apply_preset` (`broker.py:3786`), where the
   ring's text *is* the payload, it would paste the preset twice.
4. **An empty box is not empty on screen.** Claude Code renders the previous input as
   a ghost suggestion in an empty box, and a stripped pane capture cannot tell it from
   real text — see §4.

---

## 3. The recommended design

### Shape

- `_ring`, non-interrupt: unchanged send (`self.h.prompt`), unchanged
  `store.mark_delivered`, unchanged return. **The sender waits for nothing.**
  It additionally logs the ring — agent, the doorbell text, the send time — which
  the event log already supports (`store.log_event`).
- `Broker.flush_pending`: a second, cheap pass over rings that are older than a
  settle window (~5 s) and not yet confirmed, for messages still unread:
  - **proof** = the submission is in the target's own transcript, either as a
    `queue-operation`/`enqueue` record (busy target) or as a `user` record (idle
    target), timestamped since the send. Read from `store.transcript_path(agent)` —
    the agent's own session file, not the whole `cwd` directory (§5).
  - proof present → mark the ring confirmed; nothing else happens.
  - proof absent → **re-send the doorbell** (`h.prompt` again). Capped at two
    repairs, then log `ring_unconfirmed` and stop, which is exactly today's
    behaviour.
- **No Enter is ever pressed on a plain tell.** The repair for a doorbell is a
  re-send, because a doorbell has no payload to duplicate. That is the same reasoning
  `_rescue`'s docstring uses, applied to the case where it comes out the other way.

### Why not the alternatives

- **Sender-side blocking confirmation (`deliver`, or a bounded version of it).**
  A bounded version is actually achievable — ~2 s for a busy target (enqueue record),
  ~1–2 s for an idle one (herdr flips to `working`, which `_running_turn` already
  tests). But `_ring` is not only `sb tell`: `flush_pending` calls it at the head of
  **every `sb` command**, and `done` calls it for the parent poke. A 2–3 s tax there
  is paid by the whole fleet on every command whenever anyone has pending mail. Scope
  it to `tell` only and the majority of doorbells stay unconfirmed — the bug stays
  half-fixed.
- **A cheap pre-flight pane check.** Worth less than the post-hoc one: it cannot see
  a dropped Enter (that has not happened yet), only that the box was already dirty. It
  would catch the modal case, at one subprocess per ring. Not the fix.
- **A post-hoc pane check instead of the transcript.** Faster to write and the read is
  clean and structured (§4), but it is the weaker evidence: the box says what herdr
  last managed to capture, and an empty box is ambiguous with a ghost suggestion. Use
  the transcript to decide *whether* it landed. The pane read is still the right tool
  if a future repair wants to press Enter — but only ever after positively matching
  our own text in the box, never blind.

### What must change for this to work at all

`output.task_arrived` (or a sibling predicate) must accept the
`queue-operation`/`enqueue` record type. Without it a busy target can never be
proved and the repair fires on every correct delivery. This is the linchpin of the
design and it is ~3 lines.

---

## 4. What the prompt box can and cannot tell you

`herdr agent explain <name> --json` exposes the box as a structured region — the
rule `live_prompt_box`, `region: prompt_box_body`, `evidence.region_preview` — and it
is present in `evaluated_rules` even when a higher-priority rule wins, so it is
readable for a *working* agent too. Observed values:

| box | meaning |
|---|---|
| `❯\xa0<our text…>` (truncated at pane width) | pasted, **not submitted** — the bug |
| `❯\xa0Press up to edit queued messages` | submitted, queued behind the running turn |
| `❯\n` | genuinely empty |
| `❯\xa0<previous input>` | **empty, showing a ghost history suggestion** |

The last row is the trap: after a successful doorbell the ghost is the doorbell text,
so a naive "is my text in the box?" check says "stuck" for a box that is empty. In
this run the ghost was `! sb board`; typing a space cleared it, backspace brought it
back, and two Enters on it submitted nothing — so the cost of that false positive is
a wasted keystroke, not a wrong submission. I tested Enter-on-ghost only with the
agent idle; I did not test it mid-turn.

Also note the capture lags: 0.3 s after a paste the box still showed the previous
content; it was correct by 1.9 s.

---

## 5. Blast radius

**Callers of the path.** `Broker._ring`'s non-interrupt branch has four callers:

| call site | mode | effect of the change |
|---|---|---|
| `broker.py:3721` `tell` | next-turn | the target case |
| `broker.py:3786` `apply_preset` | next-turn | **the ring's text IS the payload here** — today a preset can be recorded applied when the paste never submitted. A confirmed ring fixes that too; a re-send repair would paste the preset twice, so this call site needs the Enter-conditioned repair or an opt-out |
| `broker.py:3895` `done` → parent poke | when-idle | target is idle by construction |
| `broker.py:5276` `flush_pending` | when-idle | the confirmer would be re-entrant with the ring — it must not confirm and re-ring in the same pass |

`Herdr.deliver` itself is untouched, so `_spawn` (`broker.py:3519`) and
`_deliver_interrupt` keep their current behaviour — except that fixing
`task_arrived` to see enqueue records makes both *more* likely to confirm, never
less.

**Store semantics.** Keep `delivered_at` meaning exactly what it means today
("we rang"). Do **not** repurpose it as "confirmed": at least fifteen tests assert
`store.undelivered(...) == []` immediately after a ring, and `sb tell`'s own report,
`status._undelivered_counts` and `collector.ringable` all read that pair. Confirmation
wants its own record — an event-log row is enough and needs no schema change.

**Tests.**
- `tests/test_broker.py:1297`
  `test_an_interrupt_is_delivered_confirmed_and_a_doorbell_is_not` asserts
  `self.h.proofs == []` for a plain tell. It stays TRUE under this design — the plain
  tell still calls `Herdr.prompt` with no proof; the confirmation is a later, separate
  pass. Its docstring ("Every other mode carries no payload and is re-rung from the
  store, so it stays a plain prompt") is the design being extended, not contradicted.
  It would need to change only under the rejected "route tell through `deliver`" fix.
- `tests/test_herdr.py` `DeliverTest`/`DeliverProofTest` are untouched.
- New tests worth pinning (two or three, per the standing rule): a ring whose proof
  never appears is re-sent once and then given up on; a ring whose enqueue record
  appears is not re-sent; `output` accepts a `queue-operation/enqueue` record and
  still rejects one older than `since`. The last one is a pure record-shape test on
  captured JSON — no fake herdr needed.
- **Unproven by any test that could exist here:** that a re-send actually submits when
  the first Enter was dropped. The dropped Enter happens inside the herdr binary; the
  fakes model `agent list` and nothing else and are not to be grown. That belongs in a
  live check, not the suite.

---

## 6. Evidence

Transcript record shapes, from `<transcript>/524ac058-….jsonl`:

```
{"type":"queue-operation","operation":"enqueue","timestamp":"2026-08-16T12:49:30.497Z",
 "content":"[sb: from tester] MAILALPHA - you have mail, run sb inbox"}
{"type":"queue-operation","operation":"remove","timestamp":"2026-08-16T12:52:39.389Z", …}
{"type":"attachment","attachment":{"type":"queued_command","prompt":"[sb: from tester] MAILALPHA …",
 "origin":{"kind":"human"}},"timestamp":"2026-08-16T12:49:30.496Z"}   ← written at the boundary
```

Per-probe record types (`enqueue` present only for the two sent to a busy agent):

```
DELTA   (busy)  queue-operation/enqueue 12:56:10  → user 12:58:24
ECHO    (busy)  queue-operation/enqueue 12:57:25  → user 12:58:24
FOXTROT (idle)  user 12:59:49
GOLF    (idle)  user 13:01:11
```

Runs, all against `r25-target` in `w1JC`:

- **A — busy, `herdr agent prompt`:** `task_arrived` False on every poll from 0.0 s to
  36.3 s; box `Press up to edit queued messages` from 3.0 s.
- **B — busy, `herdr pane run` (paste, no Enter — the bug):** box held the literal
  text for 11 s; `task_arrived` and the enqueue predicate both False for 21 s; one
  `herdr agent send-keys r25-target enter` moved the box to
  `Press up to edit queued messages` within 1.6 s and the enqueue record appeared
  ~4–6 s later.
- **C — busy, timing:** enqueue record readable at **2.29 s**; `task_arrived` still
  False at that moment.
- **D — idle:** no enqueue record at all; `task_arrived` True at **14.59 s**.
- **Spawn:** `herdr agent start` returned `interactive_ready: true` with the workspace
  trust modal on screen — the hazard `herdr.py:648-655` describes, reproduced.

Probe scripts: `<scratchpad>/probe.py`, `probe2.py`, `probe3.py`.

## 7. Teardown

`herdr pane close w1JC:p1` removed the only pane and herdr retired the workspace with
it (`workspace close w1JC` then answered `workspace_not_found`). Workspace count
17 → 16, and the sixteen are the fifteen that pre-dated my run plus the three other
agents' workspaces that appeared during it — nothing of the live fleet was touched.
`sb workspace close` was tried first and correctly refused (the clone is its repo's
primary working tree). No `pkill`, no `herdr workspace close` on a repo-bound
workspace. The clone itself is left in the session scratchpad as evidence.

## 8. What I did not check

- I did not test Enter-on-a-ghost-suggestion with the agent mid-turn (only idle).
- I did not measure any of this under real machine load — the condition Andrew hit.
  The 2.29 s and 14.59 s figures are single measurements on an idle machine.
- I did not test the `when-idle` path end-to-end through `Broker.flush_pending`; all
  live probes went through `herdr` directly plus the clone's `switchboard.output`.
- I did not check whether Claude Code writes the `queue-operation` record on older
  versions, or whether `codex`/other agent kinds write anything comparable. The
  design's proof is Claude-Code-specific, exactly as `task_arrived` already is.
- I did not verify the "several agents share one cwd" false-positive concretely; it
  is read off `output._transcripts_with` scanning the whole directory, and is why §3
  says to read the agent's own session file.
