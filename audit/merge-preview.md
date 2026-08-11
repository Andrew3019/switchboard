# What main actually becomes when the five PRs merge

Run 2026-08-11 by `merge-preview` (QA). Nothing was pushed; no PR was merged; `main` was
not touched. The preview branch itself was built in a throwaway clone under the scratch
directory and is gone — this document is the deliverable.

**Verdict: the merged result is sound.** Two conflicts, both one-line and both obvious.
Suite 1128 pass. Acceptance 4/4 pass, first run. The two defects the whole-stack run
reported against the tip of #14 are **not** in the merged result, and I proved that live
rather than by grep.

A note on the brief's arithmetic: it says six PRs. `gh pr list` shows **five** open —
#10 `phase3-messaging`, #11 `phase4-removals`, #12 `phase5-structure`,
#13 `phase4-workspace-new`, #14 `phase6-prompts`. Five is what I merged.

## 1. The preview, and how it was built

A `git clone` of this repo into the scratch directory, a branch cut from `origin/main`
(`5998a43`), and each PR branch merged into it with `--no-ff` in the brief's order:

    7bbf517 Merge phase3-messaging      (#10)   clean
    ede4421 Merge phase4-removals       (#11)   CONFLICT: switchboard/status.py
    bf1c64a Merge phase5-structure      (#12)   CONFLICT: tests/test_status.py
    a9da1d0 Merge phase4-workspace-new  (#13)   clean
    c01e86e Merge phase6-prompts        (#14)   clean

Those hashes are local to the throwaway clone; Andrew's will differ. The conflicts will
not.

## 2. The two conflicts, and how to resolve each

Both come from the same root the brief names: #11, #12, #13 and #14 fork from `8f69642`,
the commit *before* phase 3's fix commit `233b14e`, so `233b14e` arrives only through #10
and lands on top of code the other branches have since rewritten.

### Conflict 1 — `switchboard/status.py`, merging #11 after #10

One hunk, the `from .herdr import` block near line 81:

    <<<<<<< HEAD                       (main + #10)
        BLOCKED, DELIVER_ATTEMPTS, DELIVER_TIMEOUT_MS, IDLE, SPAWN_ATTEMPTS, SPAWN_BACKOFF,
        SPAWN_TIMEOUT_MS, WORKING, Herdr, HerdrError,
    =======                            (#11)
        BLOCKED, SPAWN_ATTEMPTS, SPAWN_BACKOFF, SPAWN_TIMEOUT_MS, Herdr, HerdrError,
    >>>>>>> up/phase4-removals

Both sides changed the same line for unrelated reasons: #10 added `DELIVER_ATTEMPTS` and
`DELIVER_TIMEOUT_MS` because `STALL_GRACE` is derived from them; #11 dropped `IDLE` and
`WORKING` because it deleted `sb wait`, their only user.

**Resolution — take the union minus `IDLE` and `WORKING`:**

    BLOCKED, DELIVER_ATTEMPTS, DELIVER_TIMEOUT_MS, SPAWN_ATTEMPTS, SPAWN_BACKOFF,
    SPAWN_TIMEOUT_MS, Herdr, HerdrError,

Checked rather than assumed: after the merge, `DELIVER_ATTEMPTS`/`DELIVER_TIMEOUT_MS` are
used only by `STALL_GRACE` (status.py:181-183), `BLOCKED` by `is_blocked` and the render,
and `WORKING` nowhere. The one remaining hit for `IDLE` is the string literal in the board
header (`f"{'IDLE':>6}"`), not the symbol.

### Conflict 2 — `tests/test_status.py`, merging #12

One hunk, in `test_json_carries_the_same_facts` (near line 883). With `--conflict=diff3`:

    ours   (main+#10+#11)  role="main",         kid gets session_id="s1"
    base                   role="main",         kid has no session_id
    theirs (#12)           role="orchestrator", kid has no session_id

`233b14e` added `session_id="s1"` so the kid reads as stalled (without a session id
`STALL_GRACE` suppresses the flag, which is the whole fix); #12 renamed the root's role.
Disjoint edits on adjacent lines.

**Resolution — take both:**

    store.create_agent(self.db, name="root", role="orchestrator", workspace="main")
    store.create_agent(self.db, name="kid", role="worker", parent="root",
                       session_id="s1")

### Merge order

The brief's order is right, and it is also the only order that keeps #13 and #14 clean —
`phase4-workspace-new` is built on `phase5-structure` and `phase6-prompts` on that, so
those two must land last and in that order.

The order does **not** change the conflicts, only which PR shows red. I built a second
preview merging #11, #12, #13, #14 first and #10 last: the same two files conflict, with
the same content, all on #10's merge. So Andrew hits two one-line conflicts either way.

Worth knowing: all five PRs currently read `MERGEABLE` on GitHub, because each is measured
against today's `main`. The moment #10 lands, #11 will turn conflicted in the UI. That is
expected, not a new problem.

## 3. The two "defects" are absent

Present, and coherent, in the merged tree — not just present as symbols:

- `status.STALL_GRACE` is defined (status.py:181) and read where it matters:
  `starting = row["session_id"] is None and (now - last) < STALL_GRACE`, feeding the
  `stalled` predicate. Resolves to **72.0 s** against the merged `defaults/settings.toml`
  (`deliver_ms` 20000 x `deliver_attempts` 3, plus the spawn backoff), so #11's trim of
  that file did not remove the keys it derives from.
- `hooks._already_nudged` is defined (hooks.py:168) and called last in `stop_gate`
  (hooks.py:239). Its query reads events `stop_gate_blocked` / `done` / `blocked`; all
  three are still written in the merged tree (`hooks.py:246`, `broker.py:3399`,
  `broker.py:3475`), so the cap has the history it needs after #13's broker rewrite.

## 4. The suite

    /Users/andrew/anaconda3/bin/python -m pytest tests
    1128 passed in 68.89s

`audit/full-stack-verification.md` recorded **1124** at the tip of #14. The +4 are exactly
the four tests `233b14e` added, which is the arithmetic the brief predicts.

## 5. Acceptance

`./acceptance/accept.py merge-preview-local`, run from the preview clone. Exit code 0.
Verbatim:

      1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [42s]
      2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 49s later; the parent woke and read it   [1m49s]
      3  a block holds until the human answers    PASS   held 26s against a sibling, released by the human's answer and read it   [1m38s]
      4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbrmje094-k: blocked, not finished — it has not reported an end'   [47s]

    all 4 pass — the fleet is sound   (1m55s)

First run passed, so no re-run was needed. Evidence:
`/var/folders/5r/8xg52c651zxg199r33s0fsy00000gn/T/accept-sbrmje09/run.log`.

## 6. The live run

A second `git clone` of this repo into the scratch directory, checked out at the preview
and driven only through **that clone's own `./bin/sb`**. `sb doctor` before anything:
store `…/scratchpad/live/.git/agentflow/state.db`, 0 agents. Run id `mpq7k`.

**No agent is nudged before its task arrives.** `./bin/sb reconcile` was driven once a
second from outside for the whole run — strictly more aggressive than the collector, and
the same probe that reproduced the defect on the tip. **96 invocations, every one printed
`pinged nobody`**, across two spawns. Zero reconciler nudges in the event log.

**An agent that ends its turn unreported is stopped once, not twice.** `mpq7k-silent` was
delegated a task that told it to run no commands at all. Events, from that clone's store:

    368  1786457345  mpq7k-silent  stop_gate_blocked
    373  1786457420  (none)        stop_gate_capped  {"target": "mpq7k-silent"}
    376  1786457433  (none)        stop_gate_capped  {"target": "mpq7k-silent"}

It was poked with an `sb tell` between the block and the caps — a fresh stop-chain, with
`stop_hook_active` false, which is exactly the case `stop_hook_active` never capped. One
block, then the store-backed cap held. `mpq7k-l2` shows the same shape independently
(blocked at 1786457142, capped at 1786457219).

**A lead's child is a tab in the lead's space.** `mpq7k-lead` (top, `is_top=1`, workspace
`wTC`) delegated `mpq7k-l2`, which opened its own workspace `wTE` as its lead. `mpq7k-l2`
then delegated `mpq7k-gk`:

    mpq7k-l2   workspace mpq7k-l2  workspace_id wTE  pane wTE:p1  is_top 0
    mpq7k-gk   workspace mpq7k-l2  workspace_id wTE  pane wTE:p3  is_top 0

Same workspace, a new pane in it, and **no `fork` event** for `mpq7k-gk` — a tab, not a
checkout of its own. The top's own children do fork (`mpq7k-kid`, `mpq7k-l2` both have
`fork` events and their own worktrees), which is the phase 5 rule doing what it says.

**A message carries its sender's tag.** From the store and the herdr call log:

    agent prompt mpq7k-lead [sb: from mpq7k-kid] You have mail. Run: sb inbox
    body: '[done] kid done'           from mpq7k-kid  to mpq7k-lead
    body: 'HELLO-mpq7k'               from mpq7k-lead to mpq7k-kid
    body: 'HELLO-mpq7k received'      from mpq7k-kid  to mpq7k-lead

Acceptance check 3 shows the same thing from the reader's side, in the agent's own words:
`READ [1] [sb: from sbrmje093-s] SIBLING-sbrmje093 [2] [sb: from human] HUMAN-ANSWER-sbrmje093`.

**Teardown.** All four agents closed with `sb cleanup --force` (`alive left: []`); the
clone's herdr workspace closed by checkout path; the child worktrees under
`~/.herdr/worktrees/live/` removed; the clone's own collector (pid 60371, cwd the clone,
verified `switchboard.collector`) exited by itself once the last pane closed — I could not
signal it, see §7. No `pkill` of any kind was run.

## 7. What I could not test, and one thing I did not

- **I could not SIGTERM the clone's collector.** The sandbox refused both `kill` and
  `os.kill`. It retired on its own after the last pane closed, and I confirmed the process
  is gone, so nothing leaked — but the scripted teardown path in `accept.py`
  (`_stop_collector`) is one I did not exercise by hand.
- **I did not test #13 or #14 in isolation.** They merged clean and are covered by the
  suite and the acceptance run against the merged result, which is what Andrew gets.
- **No endurance or load testing**, per the brief.
- **One observed behaviour, reported and not fixed** (it is by design, phase 5): a `worker`
  that runs `sb delegate` is refused — *"a worker does not spawn agents — only a role with
  delegate rights does (today: orchestrator)"*. My first probe hit this and the agent
  correctly `sb block`ed rather than guessing. Noted because it is a live-fleet-visible
  behaviour change, not because it is wrong.

## 8. `fix-spawn-nudge`

**Discard it.** The branch cherry-picks `233b14e`'s `status.py` half onto the tip of #14.
That same change arrives through #10, and I confirmed the merged `status.py` already
carries it, byte for byte, in the preview. Landing the branch as well would duplicate the
commit and manufacture a conflict where there is currently a one-line one. Its
`audit/spawn-nudge-fix.md` is the useful part — the diagnosis is right and it is what this
run was built on — but nothing in the branch needs to reach `main`.

## 9. So: is the stack sound as it will merge?

Yes. Merge in the order #10, #11, #12, #13, #14; resolve the two one-line conflicts in §2;
what comes out passes 1128 tests, passes all four acceptance criteria first time, and does
not reproduce either defect the whole-stack run found against the tip.
