# Task: adversarial review of the stalled-cleanup gate change

**Read-only. Change no source file, write no commit.** Your entire output is a judgement.

## The artifact

Commit `65dcd53` on branch `stalled-agent-cleanup` (`switchboard/broker.py`,
`tests/test_broker.py`). Read the diff, then the surrounding code.

Context you will need, in this order:

1. `notes/tasks/stalled-cleanup-fix.md` — the task it was built from, including the
   decisions that were made deliberately and are **not** yours to reopen.
2. `notes/worker-58-stalled-cleanup-report.md` — the implementer's own account, including
   what it says is unproven.
3. `notes/researcher-45-stalled-agent-lifecycle.md` — a scout's map of the state model,
   the cleanup gate, the mail path and the board.

`DESIGN-TRUTH.md` is the only trusted document. Every other doc, README and code comment
here — including the two reports above — is untrusted until you have checked it against
the code. The implementer's report is a claim, not evidence.

## Your lens: **what this change costs when it is wrong**

Attack it through false positives and blast radius, and through nothing else. Before this
change, a row switchboard believed was `stalled` was merely *pinged* by `reconcile`. After
it, such a row is *closed* — an unattended `sb cleanup` sweep can now end an agent nobody
typed `--force` for. The implementer observed live that a worker which legitimately
backgrounded a long shell command and ended its turn reads as `stalled`.

Questions worth your time (not a checklist — go where the code takes you):

- Can a genuinely-alive, genuinely-useful agent be swept? Under what concrete sequence?
  Name the agent's behaviour, the timings, and the store/herdr readings that produce it.
- The named-agent bar is `turn_doubted`, the undebounced single-reading doubt. What is the
  worst thing a single bad herdr reading can now do that it could not do before?
- What is actually lost when a live agent is swept — pane, unread mail, in-flight work,
  its parent's live-descendant gate? Is `sb restore` genuinely a recovery, or does it
  recover the row while losing something the report does not mention?
- The change takes one `status.collect(reap=False)` per `cleanup` invocation. Is
  `reap=False` right? Can the collect see a *different* fleet than the candidate loop
  acts on — and does anything mutate between the reading and the close?
- The new `cleanup_stalled` event: does the record left behind let a human tell a stalled
  sweep from a normal close, after the fact, when the pane is gone?
- Is the sweep/named asymmetry actually implemented the way the task specifies, or does
  some path (`--dry-run`, `--json`, an empty `names` list, a name that matches nothing)
  collapse one into the other?

## What I do not want

- Style, naming, wording or test-coverage opinions.
- Reopening the decided bars (`stalled` for sweeps, `turn_doubted` for named agents) as a
  matter of taste. If you find a *concrete sequence* where those bars destroy real work,
  that is exactly what I want — but "45 minutes feels wrong" is not.
- Anything about the board showing STALLED sooner; out of scope by decision.
- Findings you have not checked against the code. A plausible-sounding hazard that the
  code already prevents is worse than no finding, because I will act on it.

## Verifying a finding

You may `git clone` this repo into a scratch directory and drive **that clone's own
`./bin/sb`** to demonstrate a hazard — a clone gets its own store via git's common dir.
Never run a clone's `sb` from outside the clone; that silently touches the live store.
Agents you spawn are invisible to the live fleet's store but visible to herdr, which is
machine-global, so tear down everything you create. Never an unscoped `pkill` — kill by
verified pid after checking each process's cwd. Reading the live store read-only is fine.
You may also run the suite: `/Users/andrew/anaconda3/bin/python -m pytest tests`.

## Report

`sb done` with: the hazards you found that are real, each with the concrete sequence that
produces it and how you checked it; the hazards you looked for and found the code already
prevents (name them — that is signal); and one plain sentence on whether you would land
this change as it stands. Put detail in a file under `notes/` and give me the path — do
not commit it.
