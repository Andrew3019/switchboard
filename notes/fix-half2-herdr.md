# Fix half 2 — a retry submits the stuck box before it types the task again

Commit `d2323c8` on `task-delivery-fix`. Two files only: `switchboard/herdr.py`,
`tests/test_herdr.py`.

## What changed

`Herdr.deliver`'s loop, on every attempt after the first, now calls a new
`Herdr._rescue(name, timeout_ms, proof=..., working_ms=...)` before it considers sending
the prompt again:

1. peek the agent for a fresh baseline, stamp `sent`,
2. `self.send_keys(name, "enter")` — submit whatever is already sitting in the box,
3. `self._took_prompt(...)` with a window of `timeout_ms // 4` (min 1ms) and `working_ms`
   passed through unchanged,
4. truthy → `deliver` returns; falsy → fall through to the `prompt` re-send exactly as
   before.

A herdr that refuses the keys reads as "not rescued" and falls through too. The first
attempt sends no keys at all: nothing is stuck yet, and an enter into a pane that may
still be showing the workspace-trust dialog is precisely how a prompt gets eaten.

`deliver`'s docstring paragraph claiming the re-send "types and presses enter, carrying
the stuck text in with it" is replaced with what the code now does, and says outright
that the old sentence was never true of any code here.

## Which rescue design, and why not clear-then-resend

Clear-then-resend would be cleaner. Herdr has no key for it, as far as anything
observable says:

- `herdr agent send-keys --help` / `herdr pane send-keys --help` document only
  "Use esc as the canonical Escape key name; escape is also accepted." No enumeration.
- `herdr api schema --json`: `AgentSendKeysParams` is `{target: string, keys: [string]}`,
  unconstrained — the schema names no key at all.
- Key names are not validated up front (`herdr agent send-keys <unknown-agent> C-u`
  answers `agent_not_found`, not a key error), so a guessed name cannot be probed safely
  without firing a real keystroke into a real pane. The binary does carry an
  "unsupported key " message, so a bad name would be rejected at send time — but nothing
  attests which names are good, and a select-all/kill-line is not documented anywhere.

So: submit what is there, re-send only if nothing came of it. That is the ordering the
task specified and it is what keeps the common case from duplicating.

The rescue window is a quarter of a send's because the text is already pasted — Claude
Code appends a submitted prompt to its transcript about a second later, not after a cold
start. `working_ms` still passes through: an agent visibly running a turn has taken
something, and re-sending on top of that is the duplicate this exists to prevent.

No new setting, so nothing outside my two files changed.

## Proof

**Automated** — `tests/test_herdr.py`, two tests in `DeliverTest`:

- `test_the_first_send_presses_nothing` — a delivery that lands is one `agent prompt` and
  zero `agent send-keys`.
- `test_a_retry_presses_enter_before_it_types_anything_again` — the `takes_on=2` fake,
  asserting the **call sequence** is `prompt → send-keys(w1, enter) → prompt`.

Whole suite: `1237 passed` (`/Users/andrew/anaconda3/bin/python -m pytest tests`). No
failures, mine or anyone's.

**Live** — three cold spawns, each in its own fresh `git clone` of the repo in a scratch
dir, checked out on this branch, driven by that clone's own `./bin/sb` (`sb delegate`;
`sb start` refuses an agent caller by design, and `delegate` from a clone store whose
`whoami` is HUMAN spawns a top-level child through the same `_spawn`/`deliver` path).

All three lost their first prompt — the real cold-checkout race, no starving needed — and
all three logged exactly:

```
agent prompt probeN <task>
agent send-keys probeN enter        <-- the rescue, firing in production code
agent prompt probeN <task>
```

Each transcript then held the task text **exactly once** (`type: "user"` records,
markers `MARKER-SIGMA-7719`, `MARKER-TAU-2244`, `MARKER-RHO-8811`).

Two hand-driven checks on those live panes, to test the two halves the spawn race did not
happen to produce:

- *Rescue works.* `herdr pane send-text w1ER:p1 'MARKER-OMEGA-3355 …'` left the text
  sitting unsubmitted in probe1's box (verified by reading the pane), then
  `herdr agent send-keys probe1 enter` submitted it — transcript holds it **once**.
- *Old behaviour is the filed bug.* Same setup on probe2, then the old recovery
  (`herdr agent prompt probe2 '<same text>'`) — one single user record holding the text
  **twice**, which is exactly the incident's "submitted the task twice as one message".

## What is not proven

- The three live spawns exercised "the paste never landed" (empty box → rescue is a
  no-op → re-send delivers). The "box held the text" branch was never produced by the
  spawn race itself; it was reproduced by hand, one step removed from `deliver` driving
  it.
- Neither fake herdr models pane or box *content*. The automated tests prove "a retry
  sends a rescue key before any second `agent prompt`"; they cannot prove "and that stops
  a real terminal double-submitting". That half rests on the two hand-driven live checks
  above, not on the suite.
- The rescue can still duplicate in one narrow case: the enter submits the stuck text,
  the proof does not turn up inside the rescue window (and herdr never reports `working`,
  so no stretch), and the re-send fires anyway. That is the pre-existing "duplicate is
  recoverable, silence is not" trade, now reached less often rather than eliminated.
- Non-`enter` key names are unprobed — see above; I never sent one.

## Noticed, not fixed

- The module comment at `herdr.py:57-59` still describes delivery as "re-sent if it was
  not taken", which is now a half of what happens. Left alone: not asked for, and comment
  churn in a file two agents are near is not free.
