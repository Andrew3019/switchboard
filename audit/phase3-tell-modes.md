# Phase 3 — the `tell` cluster (3.1, 3.3, 3.2, 3.6)

Branch `phase3-tell-modes`, based on `phase3.5a-needs-reply` (`c7f43fa`).

The pass/fail tests below were written **before any code was changed**, from
`BUILD-PLAN.md`'s pass lines, `audit/phase3-scope.md`, and `DESIGN-TRUTH.md:236-247`.
Results are recorded against them at the bottom, filled in as each item lands.

The open question that gated 3.1 is settled by `audit/phase3-delivery-primitive.md`
(branch `probe-delivery-primitive`): `agent prompt` **queues** — the message lands at the
recipient's next tool-call boundary with the in-flight call completing, and cancels
nothing. So *next turn* is built by calling the primitive the busy-gate currently refuses
to call, with no escape keypress and no cancel wrapper.

---

## Tests

### 3.1 — three delivery modes on `sb tell`

**T1.1 (live, primary) — next turn reaches a busy agent at its next boundary.**
Give an agent one long single tool call (a 90s `Bash` sleep loop writing timestamps).
Part-way through, `sb tell <agent> "..."` with no mode flag.
*Pass:* the tool call runs to completion (its own log shows every line), the agent reports
that the text arrived attached to that call's result, and delivery happened at send time
(`sb tell` reports no "will be rung when free", the store row has `delivered_at` set).
*Fail:* the call is cut short (interrupt without cancellation semantics), or delivery is
deferred until the whole turn ends (today's only behaviour).

**T1.2 (live) — when idle still defers.** Same setup, `sb tell --when-idle`.
*Pass:* `sb tell` reports the target mid-turn, the store row is undelivered while the tool
call runs, and the doorbell lands only after the agent's turn ends.
*Fail:* it lands mid-turn (mode not honoured).

**T1.3 (live) — interrupt still cancels.** Same setup, `sb tell --interrupt`.
*Pass:* the in-flight tool call is abandoned (its log stops short of 90 lines) and the
agent reads the cancel-worded body inline.
*Fail:* the loop runs to completion, i.e. the escape keypress was lost with the verb.

**T1.4 (automated) — `sb done`'s parent poke stays *when idle*.** DESIGN-TRUTH:220-224.
*Pass:* a `done` whose parent is busy does not ring; it is deferred and flushed later.

**T1.5 (automated) — a blocked agent's mail is still held (3.4 not regressed).**
*Pass:* a default-mode `tell` to a blocked agent does not ring and does not clear the
block; the human's own `tell` still does.

### 3.3 — every sb message carries `[sb: from <name>]`

**T3.1 (automated) — the doorbell names its sender.** A `tell` from `w1` to `w2` rings
text containing `[sb: from w1]`. The `done` poke to a parent names the child. A human's
`tell` names `human`.

**T3.2 (automated) — the inline interrupt body carries the same tag**, and so does
`sb inbox`'s own output line — the same `[sb: from <name>]` shape, not a second spelling.

**T3.3 (live) — an agent receiving mail sees the tag** in its pane and in `sb inbox`.

### 3.2 — delete the `sb interrupt` verb

**T2.1 (automated) — `sb interrupt w "stop"` no longer parses** (argparse error, exit 2).

**T2.2 (live) — the capability survives**: `sb tell --interrupt` still cancels a running
tool call (this is T1.3, re-run after the verb is gone).

### 3.6 — remove `sb ask`

**T6.1 (automated) — `sb ask w "q?"` no longer parses**, and `Broker.ask` no longer
exists.

**T6.2 (grep) — no shipped prompt mentions it**: `grep -rn "sb ask" defaults/` is empty.

---

## Results

*Not run yet — this section is filled in as each item lands, and its git history is the
record of the order it was written in versus when the code changed.*
