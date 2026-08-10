# A spawn that could not prove delivery called a working agent failed — the cause, the fix, and what the live run did and did not show

Work by agent `fix-spawn-falsefail` on branch `fix-spawn-falsefail`, forked from `phase-1`
(`5111d89`). Nothing was installed, pushed or merged; `main`, `DESIGN-TRUTH.md` and
`BUILD-PLAN.md` are untouched. Every live command was a throwaway `git clone`'s own
`./bin/sb`, run from inside that clone (`audit/isolated-instance.md`); the live fleet's
store was never written to.

## 1. Why a taken task was reported as lost

`audit/phase1-acceptance-4.md` §3 measured it and named the shape of the answer. Both
halves are real and only the second one is a bug in the confirmation itself:

1. **The proof is a file the agent flushes on its own schedule.** `output.task_arrived`
   answers "did the task arrive" by looking for the text in the child's Claude Code
   transcript. Claude Code does not write that file when the text is submitted. Under a
   six-way fan-out, `a4f5` took its task at 05:01:59.7 and the transcript's mtime was
   05:02:34 — a **35-second lag against a 20-second window**.
2. **Nothing else was consulted.** `Herdr._took_prompt` was `if proof is not None: … else:
   …`, so with a proof in hand the herdr status read was never made at all. "The
   transcript does not show it yet" and "the agent never got it" were therefore the same
   answer, even while herdr was plainly reporting the agent `working`.

So it is not a timeout that is merely too short — widening it alone would trade one
arbitrary number for another. What was missing is that the window had no way to tell
"nothing is happening" from "something is happening and the evidence is late".

The damage came after: on that verdict `Broker._spawn` stamped `failed` over the row —
in one case one second after the agent itself had written `done` and its summary into it —
and `TaskUndelivered` told the caller to respawn the work and `sb cleanup <name> --force`
the pane. Both instructions destroy exactly what the spawn had just created.

## 2. What changed

Nothing in what *confirms* a delivery. The child's own transcript is still the only thing
that ever answers yes, and a spawn that truly lost its task still fails loudly.

- **`Herdr._took_prompt` extends its window once, by `timeouts.deliver_working_ms`
  (60 s), when the window runs out on an agent herdr reports is running a turn.** A turn
  is not proof the text arrived — a startup dialog can move an agent without it — so it
  confirms nothing; it only buys the proof time to appear, which is exactly what was
  missing. An agent that never starts a turn is never granted it, so a genuinely lost task
  still fails in `deliver_ms` per send, as before. herdr is asked only when the window
  expires, never on the twice-a-second poll: every status read is a subprocess.
- **`Broker._spawn` decides what "could not confirm" means, and it asks the agent's own
  actions** (`_took_a_turn`): has the row been set to `done` or `blocked` — which only the
  agent itself can do, through `sb`, and which it cannot do without having run — or does
  herdr have it in a turn. Either way **the row is left exactly as it is** and the name is
  returned with a caveat. `failed` is written only for an agent that is doing neither.
  `failed` is deliberately not read as "it reported": `status._record_gone` writes that for
  an agent that vanished, so it is a verdict about the agent rather than a report from it.
- **`sb delegate` prints the caveat with the name** and exits 0:

  ```
  delegated to w3 — w3's delivery was not confirmed — w3: the text was sent 3 times and
  none of them could be confirmed to have arrived … But herdr reports it is running a
  turn, so it most likely took the task and nothing has been closed or respawned. Check
  with `sb inspect w3` before you act as though it did or did not: a second agent on the
  same work costs as much as none
  ```

  `--json` carries it as `unconfirmed`. The event is `task_unconfirmed`, distinct from
  `task_undelivered`.
- **The loud failure now says what is known and asks the caller to look before it closes
  anything**, rather than asserting a verdict and prescribing a `--force`:

  ```
  sb: herdr [task_undelivered] w3 started, and its task could not be got into it — … .
  herdr reports it is not running a turn and it has reported nothing, so as far as
  anything here can tell nobody is doing that work. Look before you act on that:
  `sb inspect w3` shows what is in its pane and `sb status` whether it has moved since.
  If it is idle with the task nowhere in it, delegate the work again — and close this one
  with `sb cleanup w3 --force` only once you have seen that it is idle
  ```

`Herdr.deliver`'s own exception was reworded too: it now says only that no send could be
**confirmed**, because that is all herdr knows. Claiming "the agent never took it" from
this layer is what let a caller believe a verdict nobody had established.

Three tests pin the decisions (`tests/test_herdr.py`,
`tests/test_broker.py`): a running turn buys a late proof time to arrive; an agent that is
not running gets no extra time and still fails; an unconfirmed delivery to a working agent
is not a failed spawn; and an agent that has reported `done` is never recorded `failed`.
Suite: `/Users/andrew/anaconda3/bin/python -m pytest tests` → **1797 passed**.

The only change to the test fake is `FakeHerdrAPI.get_agent`, which is `list_agents`
narrowed to one name — literally what the real `Herdr.get_agent` is. No new capability was
taught to it.

## 3. The live run

**60 counted spawns, 30 on `phase-1` and 30 on this branch**, in ten throwaway clones,
plus one warm-up agent per clone (uncounted) and a two-agent calibration clone: 72 agents
in all. The two arms always ran **at the same moment on the same machine**, so both saw
the same load — that is the whole variable, since the defect only exists when things are
busy enough for a transcript flush to lag.

| wave | clones | live panes at the peak | counted spawns | before: reported failed | after: reported failed |
|---|---|---|---|---|---|
| 1 | 4 (2 `phase-1`, 2 branch), no warm-up | ~28 | 24 | 12 | 12 |
| 2 | 4 (2/2), warm-up agent per clone | ~28 | 24 | 12 | 12 |
| 3 | 2 (1/1), warm-up agent per clone | ~14 | 12 | **1** | **0** |

Counted as **misreported**: `sb delegate` exited 1 for an agent that took its task and did
the work.

| | before (`phase-1`) | after (this branch) |
|---|---|---|
| spawns | 30 | 30 |
| misreported — agent had **already reported** when the spawn called it failed | **1** | **0** |
| misreported — agent took the task **after** the verdict (§3.3, a different cause) | 2 | 1 |
| false successes (a name returned for an agent that never ran) | 0 | 0 |

All 60 lines are in `audit/raw/spawn-false-failure-all.tsv` — clone, name, exit code,
seconds, wall time, and the exact output. Names beginning `b` are `phase-1`, `a` are this
branch.

### 3.1 The defect, reproduced exactly, on `phase-1`

Wave 3, clone `b3`, agent `b33` — the same shape as run 4's `a4f5`, from that clone's own
store:

```
15:30:35  delegate          b33
15:31:31  done              b33  {"summary": "PROBE OK b33"}
15:31:41  task_undelivered  b33  → row set to `failed`
```

The agent reported a successful end **ten seconds before** the spawn path overwrote its row
with `failed`, and `sb delegate` exited 1 with `b33 started but never took its task, so
nothing was delegated … Nothing is running that work; respawn it … then
`sb cleanup b33 --force``. Every word of that is false about `b33`, and both instructions
are destructive.

In the same wave, at the same moment, on the same machine, the six spawns on this branch
all returned 0, all six agents ran and reported, and the clone's store holds **no
`task_undelivered` and no `task_unconfirmed` event at all** — the extended window
confirmed them properly, from the transcript, as it is supposed to. Delegate durations
were the same in both arms (6–55 s), so the fix costs nothing when nothing is wrong.

### 3.2 Waves 1 and 2: a load at which nothing works, and both arms agree about it

At ~28 live panes this machine saturates and the agents genuinely do not run, so every
failure both arms reported was **true** at the moment it was reported:

- Wave 1 (no warm-up): every pane was still sitting on Claude Code's **workspace-trust
  dialog** (`Quick safety check: Is this a project you created…`), which eats the prompt.
- Wave 2 (a warm-up agent per clone answers that dialog first): the panes instead held
  **the task pasted into the prompt box, twice, unsubmitted**, at `0% 1M │ $0.00` — no turn
  ever started.

That is the regime the *first* phase-1 fix was written for, and both branches handle it
identically. **No false success appeared anywhere in 60 spawns on either branch**, which
is the guarantee this fix had to keep.

### 3.3 A third mechanism, on both branches, which this fix does not address

Three agents (`b2a1`, `b2b1` on `phase-1`; `a2a1` on this branch) **took the task minutes
after the spawn had given up**, and reported `done` — event trail `task_undelivered` →
`revived` → `done`. At the instant of the verdict they were idle with the text sitting
unsubmitted in the prompt box, so neither the transcript nor herdr had anything to say
about them and neither branch could have known. This is the pane submitting queued input
long after the last send, and it misreported at the same rate on both (2 of 30 before, 1 of
30 after — nowhere near enough to be a difference). See §4 for the one thing that would
help.

### 3.4 What is therefore unproven

- **The rate.** One reproduction of the exact defect in 30 spawns on `phase-1` and none in
  30 on the branch is a reproduction, not a rate. Run 4 got two in forty-two.
- **The unconfirmed path in the wild.** No spawn on this branch ever reached
  `task_unconfirmed` — every one of the 30 was either confirmed outright or was a true
  loss — so the caveat message and its exit-0 were exercised only by their unit tests.
- Any agent kind but `claude`, and `--workspace` delegation: not touched, as before.

## 4. Noticed, not fixed (reported, per the brief)

- **A pane that holds the task unsubmitted is not the same as a pane that holds nothing**,
  and the failure message says "may hold the text unsubmitted, be sitting on a dialog that
  ate it, or hold nothing at all" because we do not look. We could: `output.read_output`
  can already read the pane, and finding the task text sitting in the prompt box would let
  the message say which of the three it is — and would name the case in §3.2 exactly.
- **Six concurrent `sb delegate`s against a brand-new store raced and one died with
  `sb: database is locked`** (wave 0, calibration). Warming the store with a `./bin/sb
  status` first avoided it every time afterwards. Concurrent first-touch of a fresh store
  is unguarded.
- **A fan-out of six into a brand-new checkout parent loses every agent to the trust
  dialog** unless something has been started under that parent before. `agent start`
  returns while the dialog is still up. Run 4 saw one re-send survive this; at 24-wide,
  three sends did not.
- The `--force` advice still exists in the loud-failure message, now gated behind
  "once you have seen that it is idle". Removing it entirely would leave a caller with no
  way to close that pane at all, because `cleanup` refuses a `failed` row that still has
  one — and `cleanup` belongs to another agent this week.

## 5. Teardown

72 throwaway agents in eleven clones (`b1a` `b1b` `a1a` `a1b`, `b2a` `b2b` `a2a` `a2b`,
`b3` `a3`, and a two-agent calibration clone). All closed with the clone's own
`sb cleanup <name> --force`; the clone workspaces were closed with `herdr workspace close`
and the clones and their `~/.herdr/worktrees/<clone>` parents deleted. `herdr workspace
list` afterwards matches the pre-run baseline exactly. **No `pkill` of any kind was used
and no process was killed by pid.** One mistake worth recording: my first teardown script
deleted a clone before its agents were closed, which leaves twenty-four agents that no
`sb` can reach by name; the recovery is `herdr workspace close <id>` on the clone's
workspace, which takes its children's with it. The script now refuses to delete a clone
before its agents are closed.
