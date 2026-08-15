# Live proof — issue #38(b): an interrupt is delivered confirmed

The change is in `Broker._ring` / `Broker._deliver_interrupt` (`switchboard/broker.py`):
INTERRUPT mode now sends through `Herdr.deliver` with `output.task_arrived` against the
target's recorded cwd as the proof, instead of the bare `h.prompt` every other mode uses.

Everything below ran in a throwaway `git clone` of this repo under this session's
scratchpad, driving that clone's own `./bin/sb` and its own store
(`<clone>/.git/agentflow/state.db`). No agent, message or row touched the live fleet's
store. Every probe agent was closed afterwards (`sb cleanup --force`), verified absent
from `herdr agent list`, and the clone's probe files removed.

## The pane state that reproduces the bug

Issue #38's failure is a Claude Code pane sitting on a modal that eats typed text and
answers itself with the submitted Enter, while herdr reports the send as fine. The
first-run auto-mode dialog is one such modal; it cannot be reproduced without editing
Andrew's global `~/.claude.json` (part (a) of the issue, out of scope). The `/model`
picker is the same shape and was used instead: text typed into it is discarded and the
Enter selects an entry. Each probe was interrupted with `stop=False`, i.e. without the
`esc` that would have dismissed the picker — the point being a dialog that `esc` does not
clear, which is the first-run case.

## Before — `main` (474b23c), the code this replaces

worker-4, idle on the `/model` picker:

| what | observed |
|---|---|
| `_interrupt` returned | **success**, in 0.0 s |
| store row | `delivered_at` and `read_at` both set |
| the pane | `Set model to Opus 5 and saved as your default` — the dialog answered |
| the instruction | nowhere in the pane, nowhere in the transcript |
| the agent's action | none; the file the interrupt asked for was never written |

That is the bug exactly: a message recorded as read by an agent that never saw it.

## After — this branch

Same modal, two agents:

- **worker-3** — `_interrupt` took 28.2 s, retried through the modal (`deliver`'s rescue
  presses enter on what is stuck before re-sending), the instruction appears in the pane,
  and the agent obeyed it and reported `done` with "Interrupt received and obeyed".
- **worker-2** — same, 88.2 s, delivered and obeyed.

And the ordinary case, unchanged in spirit but now proved rather than assumed:

- **worker-1** — mid `sleep 300`, `sb tell worker-1 "..." --interrupt` returned in 1.7 s;
  the send was confirmed by the agent's own transcript (with a proof present that is the
  only thing `Herdr._took_prompt` can return true on), the row was marked delivered and
  read, the agent abandoned the sleep and did what the interrupt said.

## Tests

Three in `tests/test_broker.py`, each verified to fail against `main` and pass here:

- `test_an_interrupt_is_delivered_confirmed_and_a_doorbell_is_not`
- `test_the_interrupts_proof_is_the_targets_own_transcript`
- `test_an_interrupt_no_send_could_confirm_stays_queued_and_unread`

Full suite: 1253 passed.

## What is not proved

- The first-run auto-mode dialog itself, as opposed to a modal of the same shape. Doing so
  means changing Andrew's global Claude config, which is issue #38(a) and his call.
- Behaviour under load — an interrupt whose proof is flushed late, like the 35 s transcript
  lag `deliver` was widened for. `deliver`'s own window handling is unchanged by this fix.
