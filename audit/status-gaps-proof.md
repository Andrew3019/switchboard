# Three gaps in how activity and failure are noticed — before and after, live

One script, one isolated clone per branch, one real fleet each: `main` (bb515be) for the
"before" and `status-gaps` (4dc58b2) for the "after". Same script both times, so the
difference in the table below is the fix and nothing else. The script is not in the repo —
it is `accept.py`'s `Clone` (isolation, teardown, no unscoped `pkill`) with three
measurements bolted on; what it did is written out in full here.

## The fleet, both runs

| agent | what it does | what is done to it |
| --- | --- | --- |
| `p` | orchestrator; its whole turn is ONE shell command — three `sb delegate`s then `sleep 420` — so it is provably mid-turn throughout | told something `--when-idle` |
| `b1` | `sb block` immediately, then nothing | its PANE IS CLOSED (`herdr pane close`) |
| `b2` | `sb block` immediately, then nothing | **nothing at all** |
| `w`  | one shell command: `sb inbox ; sleep 400 ; sb done` | its PANE IS CLOSED |

Between closing the two panes and reading the result, the script runs **no `sb` command of
any kind** — the store is read straight from sqlite, read-only. That is the whole of check
B: whatever happens has to happen by itself.

## Results

| | before (`main` bb515be) | after (`status-gaps` 4dc58b2) |
| --- | --- | --- |
| **A** a doorbell held for a busy agent | `ring_deferred` logged, `p`'s idle clock **49s → 3s** | `ring_deferred` logged, idle **48s → 52s** — kept counting |
| **B** a death, with nobody looking | `w` still `working` after **421s**, parent never told | `w` `failed` + parent told after **65s** |
| **C** a blocked agent whose pane died | `b1` still `blocked`, no `ended_at`, parent never told — and a manual `sb status` did not change that either | `b1` `failed`, `ended_at` set, parent told; **`b2` still `blocked`, still alive to herdr, `gone=False`, no message about it ever written** |

The `b2` column is the one that mattered most: a fix that reaped living blocked agents
would be worse than the bug. Its pane was never touched, so herdr keeps listing it,
`alive is False` is never true for it, and nothing in the new path can reach it.

Timings worth keeping:

- `b1` (blocked, had claimed a session by running `sb block`) was recorded `failed`
  **~74s** after its pane closed in one run and ~65s in another — `GONE_CONFIRM_GRACE`
  (60s) plus the collector's trigger latency.
- `w` took longer in an earlier run and legitimately so: it had never run an `sb` command,
  so its row had no `session_id` and `SPAWN_GRACE` (287s) correctly held it as a *claim*
  rather than a death. Giving it an `sb inbox` to run first brought it to 65s.

## What the "before" run also shows

On `main`, `sb status` — the only caller of `collect(reap=True)` — was run at the end of
the before run and left `b1` `blocked` and `w` `working`. So defect 3 was invisible even to
somebody looking, and defect 2 was invisible to everybody who was not.

## Scenario traps hit on the way, for whoever writes the next one of these

Three runs failed on the harness rather than on the code, and each is a fact about the
system worth writing down:

- An agent asked to "sleep, and do nothing else" reports `done` within seconds often
  enough that a probe built on it measures the model. The reliable way to hold an agent
  mid-turn is `accept.check_doorbell`'s: one shell command, joined with `;`, with the Bash
  timeout raised.
- `sb tell` defaults to **next-turn**, which rings a busy agent rather than holding the
  doorbell. `--when-idle` is what produces a `ring_deferred` at all.
- A `tell` from a script with no agent row resolves as the **human**, and the human's word
  is the one thing that lifts a block. Telling the blocked control agent released it and
  destroyed the check it was the control for.

## Not proven

- The reconciler's per-death spawn cost inside the confirmation window is argued from the
  code (`GONE_CONFIRM_GRACE` bounds it, and the row leaves the work list once written
  `failed`) and from the observed 65s reap; it was not measured as a process count.
- Nothing here is an endurance run, by design.
