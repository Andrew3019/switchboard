# Scout task — task delivery bug

SCOUT ONLY — read and report. Change no code, commit nothing.

## Context

I (your parent, `task-delivery-fix`) own a fix for a high-severity, verified-still-broken
bug in task delivery to a freshly spawned agent. The bug report evidence is committed on
branch `bug-triage`, not pushed. Read it first:

    git show bug-triage:notes/triage/group-2-task-delivery.md

The relevant section is the one headed `2026-08-14-172112`.

The bug has two halves.

**(1) False negative.** `sb delegate` confirms delivery by watching for the task text in the
child's own Claude Code transcript. When that proof lands just after the last poll, `deliver`
raises, and the safety net in `Broker._spawn`'s `_took_a_turn` (switchboard/broker.py, around
line 3287) consults only the store row and one instantaneous herdr probe — never the
transcript, which herdr lags behind. A live agent gets stamped GONE and `sb delegate` exits 1.
Measured in the incident: proof written `00:16:32.619Z`, give-up `00:16:33.475Z`.

**(2) No rescue on retry.** When the first prompt pastes into the box without submitting,
`deliver`'s retry is another `agent prompt` into a box that already holds the text — so either
both copies submit as one message, or neither submits and the agent never starts a session.
Nothing clears the box or sends an explicit enter, although `Herdr.send_keys` exists (its only
caller is the interrupt path at broker.py:4015).

## What I need back

Come back and tell me how this code is actually shaped, so I can split the implementation well.

**A. Map the delivery path end to end.**
- `switchboard/herdr.py`: `deliver`, `_took_prompt`, `_running_turn`, `send_keys`
- `switchboard/output.py`: `task_arrived` — give its exact signature. Does it already take a
  `since` argument, or would that need adding?
- `switchboard/broker.py`: `_spawn`'s delivery block, and `_took_a_turn`

Give real function signatures, what calls what, and where the timing deadlines and retry
counts come from (`deliver_ms`, `deliver_working_ms`, `retries.deliver_attempts`).

**B. For each half, the smallest honest change and what it touches.** Do NOT write the code —
describe it precisely enough that a worker can implement it without re-deriving your map.
Flag anything the bug report asserts that is NOT true of the code at HEAD. The report is
untrusted except where you have checked it against the code.

**C. Do the two halves touch overlapping functions or lines?** That decides whether I can run
two writers in parallel or must serialise them. Be concrete — name the functions each half
edits.

**D. How could a fix here be PROVEN live?** Read `sb presets house-rules` first. Tell me:
- the smallest run in an isolated `git clone` that can tell fixed from broken, for each half
- which existing tests under `tests/` already cover this path (name the files)
- whether the existing fake herdr can express a paste-that-does-not-submit. Do NOT propose
  growing the fake.

## Output

Write your findings to `notes/scout-task-delivery.md` in this worktree. That file is yours
alone — touch no other file, and do not commit. Then `sb done` with a plain two-line summary
pointing me at that file.
