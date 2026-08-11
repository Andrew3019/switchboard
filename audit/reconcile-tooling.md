# Reconciling `tooling` with main

Merge commit **9cfb78e**, on branch `reconcile-tooling`. Branch `tooling` itself is checked
out in worktree `integrate-tooling`, so I could not move that ref — **fast-forward `tooling`
to 9cfb78e** to land it. No rebase; tooling's commits are untouched.

## The conflicts

Two files, both in `tests/`, both where main added or deleted a test inside a block tooling
had trimmed. Four cases needed judgment; all four resolved toward main.

1. **`tests/test_broker.py` — DROPPED** `test_done_pushes_idle_because_herdr_has_no_done_state`
   and `test_a_state_write_checks_for_a_conflicting_integration_once`. tooling kept them, main
   deleted them: phase 2 stopped `done` reporting herdr state, so both assert a path that no
   longer exists and would now fail.
2. **`tests/test_broker.py` — KEPT** main's new
   `test_a_finished_agent_can_still_be_reached_on_an_evicting_herdr`.
3. **`tests/test_broker.py` — RESTORED** `test_a_childs_summary_still_reaches_its_parent_as_mail`,
   which tooling deleted as worthless. It is not: phase 2's mail routing rests on it — only the
   human lost a mailbox, agent-to-agent handoff had to survive.
4. **`tests/test_inspect.py` — KEPT** main's new
   `test_a_blocked_agent_is_told_its_mail_waits_on_the_human_not_on_idle`, and **RESTORED**
   `test_no_undelivered_section_when_everything_was_announced`, which tooling deleted. Phase 2
   rewrote the undelivered rendering, so "no section when there is nothing" is a live guard
   again rather than an obvious one.

Everything else merged clean: main's four additions to `tests/test_status.py`, main's deletion
of the two other herdr-check tests tooling had kept, and `defaults/settings.toml` (tooling's
shared preset layer and main's `fork_lock` both present).

## Evidence

Full suite, `/Users/andrew/anaconda3/bin/python -m pytest tests`: **1115 passed, 0 failed** (81s).

`./acceptance/accept.py`, run against `reconcile-tooling` because that is where the merge is:

```
  1  a cold fan-out of six starts six       PASS  6/6 took their task and reported into 6 new checkouts, 0 spawns misreported  [1m46s]
  2  a child's report wakes its parent      PASS  deferred while the parent worked, then delivered by the doorbell 43s later   [1m37s]
  3  a block holds until the human answers  PASS  held 31s against a sibling, released by the human's answer and read it       [1m18s]
  4  a sweep names what it refused          PASS  closed 1, refused 1 and said why                                             [1m12s]
all 4 pass — the fleet is sound   (1m50s)
```

Run log: `/var/folders/5r/8xg52c651zxg199r33s0fsy00000gn/T/accept-sb481k1p/run.log`

Not pushed, not merged, main untouched. Unproven: nothing about the merge itself, but the
acceptance run exercised the ref `reconcile-tooling`, not one named `tooling` — same tree.
