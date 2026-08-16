# `sb tell` → pane keystroke delivery path

Investigation only, no code changed. Bug: "when my computer was lagging, `tell`
pasted the message but the Enter didn't go through."

## 1. The path, `sb tell` down to the keystroke call

- `Broker.tell` — `switchboard/broker.py:3667`. Writes a `messages` row
  (`store.put_message`), then calls `self._ring(t, ..., mode=mode, ...)` at
  `broker.py:3721`.
- `Broker._ring` — `broker.py:5370`. This is the actual dispatcher. For the two
  non-interrupt modes (`next-turn`, the default, and `when-idle`) it does, at
  `broker.py:5459`:
  ```python
  self.h.prompt(who, text)
  ```
  For `mode=INTERRUPT` it instead calls `self._deliver_interrupt(who, text)`
  (`broker.py:5470`), which calls `self.h.deliver(who, text, proof=...)`
  (`broker.py:5504`).
- `Herdr.prompt` — `switchboard/herdr.py:600`. One shell-out:
  `self._call("agent", "prompt", name, text)`. That's it — no confirmation, no
  retry, no verification.
- `Herdr.deliver` — `herdr.py:628`. Wraps `Herdr.prompt` with retries and a
  confirmation ("proof") loop. Only reachable from `_ring`'s `INTERRUPT`
  branch and from `Broker._spawn` (spawn-time prompting, `broker.py:3519`).
- `Herdr._call` — `herdr.py:268` — shells out to the external `herdr` binary
  (`self.binary`, e.g. `herdr agent prompt <name> <text>`). **Everything past
  this point — how text is typed into the pane, and how/when Enter is sent —
  happens inside the herdr binary, which is outside this repo.** There is no
  tmux `send-keys` call anywhere in this codebase for the text+Enter combo;
  the one literal `send-keys`-ish thing here is `Herdr.send_keys`
  (`herdr.py:880`), which shells to `herdr agent send-keys <name> <keys...>`,
  used only for `esc` (interrupt cancel) and for `_rescue`'s bare `enter`
  press (see below).

## 2. How is Enter submitted — same call, separate, delay, retry, verification?

For a **plain `sb tell`** (the default `next-turn` mode, and `when-idle` too)
— which is what the bug report describes — the answer is stark:

- Text and Enter are **one opaque call**, `herdr agent prompt <name> <text>`.
  Whatever herdr does internally (type text, then send Enter) is not visible
  or controllable from this codebase.
- **No delay/sleep** between text and Enter is coded here — there can't be,
  since this repo doesn't issue them as separate steps for this mode.
- **No retry.** `Herdr.prompt` is called exactly once. If herdr's own
  internal Enter is dropped, `_call` still returns success (rc=0, no `error`
  key in the JSON envelope) because from herdr's point of view the command it
  ran (its own `prompt`) succeeded — HerdrError is not raised. So `_ring`
  reports the doorbell delivered (`store.mark_delivered`, `broker.py:5467`)
  and `Broker.tell` returns normally.
- **No verification that the text was accepted.** `Herdr.prompt`'s own
  docstring (`herdr.py:600-625`) says this explicitly: its return value
  "reflects state BEFORE the prompt lands, so never infer 'it started' from
  it." Nothing after the call checks pane content, agent state, or the
  target's own transcript.

Contrast with **`mode=INTERRUPT`** (`sb tell --interrupt`), which is the
*only* tell mode that gets confirmation: `_deliver_interrupt` →
`Herdr.deliver` (`herdr.py:628`) does retry (up to `DELIVER_ATTEMPTS=3`,
`defaults/settings.toml:383`), does a `_rescue` step that presses `enter` on
whatever is already sitting in the box before re-sending
(`herdr.py:725-768`), and does poll for proof — the target's own transcript
having absorbed the text (`output.task_arrived`) or, without a cwd/proof, a
weaker "did a new working turn start" check (`_took_prompt`,
`herdr.py:781-826`). This confirmed path is documented at length in
`Herdr.deliver`'s docstring as existing *specifically* because "the text is
pasted into the prompt box and never submitted" is an **observed, named
failure mode** of `agent prompt` — i.e. this exact bug is already understood
and already has a fix mechanism, just not one wired up to ordinary `tell`.

`tests/test_broker.py:1297` (`test_an_interrupt_is_delivered_confirmed_and_a_doorbell_is_not`)
asserts precisely this split: a plain `tell` calls `Herdr.prompt` with no
proof at all (`self.h.proofs == []`), only an `--interrupt` tell goes through
the confirmed path.

## 3. Concrete race(s) that could drop or mistime Enter

- **The one the docstrings name directly, at `herdr.py:642-655`:** "the text
  is pasted into the prompt box and never submitted, or it never arrives at
  all." Both are silent successes from `agent prompt`'s point of view. A
  system under load — the very condition Andrew hit — is exactly where a
  paste can land but the terminal/pty is too backed up to also register the
  Enter keystroke that (presumably) herdr fires right after it internally.
  This repo has zero visibility into that internal timing and zero retry for
  the plain-`tell` path, so a dropped Enter here is unrecoverable and
  unreported: `sb tell` returns success, the message row is marked
  delivered, and the text sits unsubmitted in the recipient's box.
- **Startup-dialog race**, named explicitly at `herdr.py:648-655`: "`agent
  start` returns with the pane already `interactive_ready` while Claude Code
  is still showing its workspace trust dialog. The prompt then types into a
  modal — the text is thrown away and the Enter answers the dialog." Not the
  bug reported here (that's spawn-time, not an ordinary `tell` to a running
  agent), but it's the same underlying failure class: herdr's `interactive_ready`
  signal doesn't mean "ready to receive this specific prompt."
- **No pane readiness/busy check before typing**, for the plain-`tell` path —
  see item 4.
- Nothing in this codebase enforces ordering or timing between the text paste
  and the Enter keystroke inside a single `agent prompt` call; that entire
  sub-path is opaque (inside the herdr binary), so I cannot name the specific
  internal race there — only that this repo has no way to detect or recover
  from it for `next-turn`/`when-idle` `tell`.

## 4. Is there a pane-readiness / "awaiting keypress" check?

There is prior work on detecting a modal / "awaiting keypress" state
(recent commits, `notes/` — e.g. `2619ffd`, `notes/` modal-capture entries),
but **it is not wired into the `sb tell` delivery path at all**:

- `_ring` (`broker.py:5370`) checks agent-level bookkeeping only:
  `_finished_and_unreachable`, `_is_blocked` (waiting on a human), and, for
  `when-idle` mode only, `_busy` (mid-turn). None of these inspect actual
  pane/terminal content or detect a modal/dialog state.
- The modal-detection work is used by `Herdr.deliver`'s `proof` mechanism
  (reading the target's own transcript file to confirm the text truly
  landed, as opposed to being eaten by a dialog) — but again, that's the
  confirmed path, reachable only via spawn (`_spawn`) and `--interrupt`
  tells, not ordinary `tell`.
- So: no, there is no pre-flight "is the pane ready / not on a modal" check
  before a plain `tell` types into it, and no post-hoc verification either.
  The mechanism exists in the codebase (`Herdr.deliver` + `output.task_arrived`
  proof) but is deliberately scoped to interrupts and spawns, not to the
  ordinary mailbox `tell` this bug report is about.

## 5. Existing tests

- `tests/test_herdr.py` — `DeliverTest` (`herdr.py:243` region) and
  `DeliverProofTest` (`herdr.py:393` region) test `Herdr.deliver`'s retry/
  rescue/proof logic thoroughly (e.g. `test_a_prompt_the_agent_took_is_sent_once`,
  `test_a_refused_prompt_is_retried_and_then_confirmed`,
  `test_a_re_send_is_what_makes_a_swallowed_first_prompt_land`). These all
  exercise the **confirmed** path only.
- `tests/test_broker.py`:
  - `test_tell_rings_the_doorbell_without_the_payload` (`:627`) and
    `test_the_default_mode_rings_a_busy_agent_and_cancels_nothing` (`:1020`)
    cover ordinary `tell`/`_ring` behavior, but only around queuing/blocking
    semantics, not delivery confirmation.
  - `test_an_interrupt_is_delivered_confirmed_and_a_doorbell_is_not` (`:1297`)
    is the one test that directly names the asymmetry: plain `tell` uses
    `Herdr.prompt` with `proofs == []`; only `--interrupt` is confirmed.
  - `test_the_interrupts_proof_is_the_targets_own_transcript` (`:1311`) and
    `test_an_interrupt_no_send_could_confirm_stays_queued_and_unread` (`:1334`)
    test the confirmation mechanism itself, again only for interrupt.
- **No test anywhere exercises "Enter dropped on a plain `next-turn`/
  `when-idle` tell"** — because there is no code path there that could catch
  or retry it; a test would just assert "returns success" trivially. This
  matches the bug: the failure mode is real and reachable, and it is
  entirely unguarded outside of `--interrupt`.

## Bottom line for splitting fix work

The confirmation/retry machinery Andrew's bug needs already exists —
`Herdr.deliver` (`herdr.py:628`) plus its `_rescue` enter-press
(`herdr.py:725`) and transcript-based proof (`output.task_arrived`) — and is
already proven correct by the `DeliverTest`/`DeliverProofTest` suites. It is
simply not used by `_ring`'s `next-turn`/`when-idle` branch
(`broker.py:5455-5459`), which still calls the bare, unconfirmed
`Herdr.prompt`. The fix is almost certainly in `Broker._ring`: route
`next-turn`/`when-idle` through `Herdr.deliver` (or something built on it)
instead of `Herdr.prompt`, rather than inventing new keystroke-timing logic —
that part is already opaque, inside the external herdr binary, and outside
this repo's control regardless.
