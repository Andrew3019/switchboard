# All six phases together — the first time they have all run at once

**2026-08-11.** Phases 1–2 are on `main`; 3, 4, 5 and 6 are a stack of four branches that
until now had only ever been tested separately, and phase 6 had never been tested with
phase 5 at all — it was built beside it, from `phase4-removals`. This is the run that puts
them in one tree.

Stack at the time of writing, bottom to top:

| branch | PR | contents |
|---|---|---|
| `phase3-messaging` | #10 | phase 3, all 8 items, plus two defect fixes |
| `phase4-removals` | #11 | phase 4's removals |
| `phase5-structure` | #12 | phase 5, the `is_top` stamp and the fork rule |
| `phase4-workspace-new` | #13 | phase 4's deferred item: `sb workspace new` deleted |
| `phase6-prompts` | #14 | phase 6, rebased onto the tip (`e02370e`) |

Nothing here is merged, and nothing here touched `main`.

## 1. The suite, reconciled

`/Users/andrew/anaconda3/bin/python -m pytest tests` on each branch of the stack:

| branch | tests | delta |
|---|---|---|
| `phase5-structure` (`c6d5945`) | **1130** pass | — |
| `phase4-workspace-new` (`860b620`) | **1111** pass | −19, deleted with `sb workspace new` |
| `phase6-prompts` (`e02370e`) | **1124** pass | +13, phase 6's own |

**1124 is the real merged number**, and the two figures the phases reported are both
explained rather than explained away. Phase 5's 1130 was correct for its own tip. Phase 6's
1115 was correct for the base it was built on (`phase4-removals`, 1102 + 13) and was never
a number for the stack. The 19 that went are the tests of a verb that no longer exists —
the ones worth keeping were rewritten onto the paths that replaced it rather than deleted
(see `phase4-workspace-new`'s commit).

Everything passes. No test needed a re-run, and nothing is skipped.

## 2. Acceptance on the stack tip

`./acceptance/accept.py phase6-prompts`, run from the tip. **First run passed; there was no
second or third run**, so this is every verdict there is:

    1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [1m29s]
    2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 68s later; the parent woke and read it   [2m34s]
    3  a block holds until the human answers    PASS   held 27s against a sibling, released by the human's answer and read it   [1m20s]
    4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sb1ly95d4-k: blocked, not finished — it has not reported an end'   [1m41s]

    all 4 pass — the fleet is sound   (2m40s)

Evidence: `/var/folders/5r/8xg52c651zxg199r33s0fsy00000gn/T/accept-sb1ly95d/run.log`.

## 3. One live run, all six phases in one tree

An isolated `git clone` of the tip at `/private/tmp/claude-501/live-stack/fstsog6q`, driven
through **that clone's own `./bin/sb`**, its own store proved by `sb doctor` before
anything was spawned. Five real agents in one tree:

    fstsog6q-top      top orchestrator, bare space over the clone's own checkout
      fstsog6q-lead   spawned by the top
        fstsog6q-kid    ┐
        fstsog6q-quiet  ├ spawned by the lead
        fstsog6q-slow   ┘

A role that exists nowhere in the code — `.switchboard/roles/archaeologist.md` — was
dropped into the clone before the first spawn, so a hardcoded role list could not pass.

**A. A top's spawn gets its own space.** The top's row is `is_top=1`, `branch NULL`,
`cwd` = the clone itself. The lead's row is `workspace=fstsog6q-lead`,
`branch=fstsog6q-lead`, `cwd=/Users/andrew/.herdr/worktrees/fstsog6q/fstsog6q-lead`. The
store holds **exactly one `fork` event** for the whole run:

    {"parent": "fstsog6q-top", "workspace": "fstsog6q-lead", "branch": "fstsog6q-lead",
     "path": ".../fstsog6q/fstsog6q-lead", "base": "phase6-prompts", "inherited": true, "dirty": 0}

The base is the clone's own branch, not `origin/main` — the inherited-base rule, which is
also the whole of what `--base` used to be for.

**B. A lead's child is a tab in that lead's space.** All three of the lead's children carry
`workspace=fstsog6q-lead`, `workspace_id=wS4`, and the lead's own cwd, in distinct panes
(`wS4:p5`, …). One fork for four agents below the top: the subtree stayed in one space.

**C. A spawned agent's prompt carries the generated role list.** Read off the recorded
`herdr agent start` argv — the actual `--append-system-prompt` — for **all five** spawns:

    The roles that exist are: archaeologist, orchestrator, qa, researcher, reviewer, worker.
    That is the list `--role` takes; a name that is not on it still works and inherits the
    default role.

`archaeologist` is there because the file was there. Still generated, and phase 5's new
`Role.delegate` field changed nothing about it — the fragment reads role NAMES.

**D. A message to a busy agent arrives tagged with its sender.** The lead delegated
`fstsog6q-slow` a long read task and, with no pause, ran `sb tell fstsog6q-slow 'note from
your lead: report the largest file too'` while it was mid-turn. The recorded delivery:

    agent prompt fstsog6q-slow [sb: from fstsog6q-lead] You have mail. Run: sb inbox

`slow` read it (`read_at` set 11s later) and its report ends `…largest is
switchboard/broker.py` — the note changed what it reported, so it arrived, was attributed,
and was acted on.

**E. An agent that ends its turn without reporting is stopped once.** `fstsog6q-quiet` was
told to say one word and not report. It stalled, and got exactly one
`reconcile_ping` (`{"target": "fstsog6q-quiet"}`), then nothing for the remaining ~3
minutes it stayed stalled. Once per stall, as designed.

**Teardown.** Every agent closed leaves-up through `sb cleanup --force`, the clone's own
collector stopped by the pid it published (checked with `ps` first), herdr's workspaces
gone from `herdr workspace list`, the clone and its worktrees deleted. Never an unscoped
`pkill`. The live fleet's own collector is the one process still running.

## What broke only when the phases were combined

**Nothing.** The five checks above hold together, the rebase of phase 6 onto phases 4-5
produced no conflict, and no test or acceptance check fails on the stack that passes on a
branch alone. On this evidence **the stack is sound.**

## One defect found on the way — reported, NOT fixed

It is not a phase interaction and it does not belong to this task. It belongs to phase
3.5's reconciler, and it reproduces anywhere that reconciler runs; it took a six-phase live
run to make it visible.

**Every newly spawned agent is told its turn ended without a report — before its task
arrives.** From the run's herdr call log, in order (`agent prompt` only):

    1786454672  agent prompt fstsog6q-kid  [sb] Your turn ended 2s ago without a report, …
    1786454673  agent prompt fstsog6q-kid  Read switchboard/broker.py in full, …

The same one-to-three-second inversion happened for **all five** agents, plus four
`reconcile_failed [agent_not_ready]` events for pings aimed at agents still mid-spawn.

**Why.** `status.collect` computes `spawning = session_id IS NULL and age < SPAWN_GRACE`
and uses it to suppress `gone` — but **not** `stalled`
(`switchboard/status.py:468-497`). Between `herdr agent start` returning and the task
prompt landing, a fresh row is `working`, herdr lists it, and herdr calls it idle: that is
the exact shape of a stall, so `Broker.reconcile` nudges it. `awaiting_task` does not
save it — that exemption is for an agent spawned with NO task, and this is the agent
spawned WITH one.

**It is not cosmetic.** In this run `fstsog6q-lead` acted on the nudge before reading its
mail and reported `sb done "No task was ever given to me — my only instruction was to
wait"`, a premature and false report caused entirely by being told, at birth, that its turn
had ended. The whole first attempt at this live run was derailed by it.

**The likely fix is one clause** — `stalled=… and not spawning`, the same guard `gone`
already gets — but this is phase 3.5's code and nobody asked for it to be changed here, so
it has been left alone. It needs its own scope, its own tests, and someone who owns that
file.

## Left unproven

- **Merge order.** Each branch was tested at its own tip and phase 6 was tested rebased on
  the rest. Nobody has merged the five into `main` and run anything afterwards; that is
  Andrew's step, and a merge is not a rebase.
- **One acceptance run, not three.** It passed first time, so the flake the brief warned
  about was not exercised. Nothing here says it has gone.
- **`FEATURES.md` is stale and was left stale.** It still documents `sb workspace new`,
  `--keep` and `--ephemeral`, all removed in phases 4 and 4-deferred. Phase 4 did not
  update it either, so this is a document that has fallen behind the last three phases
  rather than one section going out of date. Correcting it is a job, not a footnote.
- **Behaviour, as ever, rather than presence.** Phase 6's prompt rules were checked for
  presence in the prompts and, for the role list, in a live system prompt. Whether agents
  obey them is a judgement from watching real runs.
