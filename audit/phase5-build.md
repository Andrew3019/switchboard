# Phase 5 build — structure

What was built, the pass/fail tests written down *before* the change, and what those tests
answered before and after. Branch `phase5-structure`, based on `phase4-removals` (PR #11,
itself on PR #10; neither merged). Scoped in `audit/phase5-scope.md`, diagnosed live in
`audit/phase5-spawn-placement.md` (branch `diagnose-spawn`). `DESIGN-TRUTH.md:34-64` and
`:173-185` govern; nothing here edits it.

**Headline.** 5.1 and 5.2 were one fix, not two. The fork rule keyed on worktree
POSSESSION (`has_worktree(me)`), which coincides with top-ness for every agent that
happens to exist and is not the same fact. Adding the column alone would have changed
nothing, because nothing read it. Both halves landed together, and the case where the two
facts come apart is proved live below.

---

## The pass/fail tests, and what they answered

Written against the code as it stood on `phase4-removals`, then re-run.

| # | Test | Before | After |
|---|---|---|---|
| 1 | `sb start`'s row carries a fact saying it was created by `sb start`, independent of `parent`/`branch` | FAIL — no such column exists | PASS — `agents.is_top = 1` |
| 2 | A delegated agent does not carry it | (n/a) | PASS |
| 3 | A pre-existing row is stamped by migration iff it is a top | FAIL — column absent | PASS — 1 of 6 live rows stamped, the right one |
| 4 | A **backfilled** top still forks its children | FAIL | PASS (live, §3) |
| 5 | A top's `delegate` gets a new space and worktree | PASS, but for the wrong reason | PASS, on the stamp |
| 6 | A non-top, worktree-less agent's `delegate` gets a **tab in its own space** | **FAIL — forked a whole new space** | PASS (live, §2) |
| 7 | A sub-orchestrator's child stays in the caller's space; so does its subtree | FAIL for a worktree-less caller | PASS (live, §2) |
| 8 | A bare agent's `delegate` is refused, and costs no row and no pane | FAIL — succeeded unconditionally | PASS |
| 9 | Bareness is decided by a role FIELD, not the role's name | FAIL — nothing decided it at all | PASS |
| 10 | `sb tell` across two tops is refused; a sibling inside one tree is not | FAIL — global | PASS (live, §4) |
| 11 | `sb status` with no flags shows an agent one tree; the human every tree | FAIL — global to everyone | PASS (live, §4) |
| 12 | `sb inspect` / `sb log` / `sb restore` are bounded the same way | FAIL — global | PASS (live, §4) |
| 13 | The board is NOT scoped | PASS | PASS — untouched |

Unit tests: `tests/test_structure.py`, 28 of them. Suite: **1130 passed** (base was 1102;
25 new in `test_structure.py`, 3 more added after the acceptance run, and no test deleted).
PR #10's 1122 is not this base — `phase4-removals` is 1102 and that is what this stacks on.

---

## What changed

**5.1 — the stamp.** `agents.is_top INTEGER NOT NULL DEFAULT 0`, declared after `branch`
(its backfill reads `branch`, and `_reconcile` ALTERs in schema order). Written by
`Broker._top` and by no other path: `delegate` grew an `is_top` kwarg that only `_top`
passes, so "only `sb start` creates a top" is a fact of the code rather than a convention.
Backfill `store._backfill_is_top`: `UPDATE agents SET is_top=1 WHERE parent IS NULL AND
branch IS NULL`. Andrew's decision, and the scoping pass verified it — re-verified here
against the live store on the day of the build: 252 rows, 7 roots, all 7 match that shape,
no non-root does. An unstamped row is **not** treated as ordinary; that would silently
demote every real top.

**5.2 — the fork rule.** `broker.py`'s `if inherited and not self.has_worktree(me)` became
`if inherited and self.mints_space(me)`. `mints_space` reads the stamp. The human answers
True and so still forks, and so does a caller we hold no row for: neither has a space to
lend, and the only alternative is spawning into whatever checkout `sb` was run in, which
DESIGN-TRUTH rules out in as many words.

**5.3 — the refusal.** `Role.delegate: bool = False`, set `true` by
`defaults/roles/orchestrator.md`'s front matter alone. A FIELD and not a check against the
literal role name, per Andrew's decision: vocabulary is data, and `role == "worker"` breaks
the moment a leaf role is renamed or added. Enforced in `Broker.delegate` rather than the
CLI, so `sb workspace new` — which spawns a lead through the same method — goes through it
too. The refusal names the roles that *can* spawn, generated from the role definitions.

**5.4 — the boundary.** Five verbs, not six: `sb ask` was deleted in phase 3.
`Broker.top_of` walks the parent chain to the root ancestor and answers the human unless
that root carries the stamp; `tree_of` returns the set of names in a caller's tree, or
`None` for the human. `tell` and `restore` refuse across it in the broker; `status`,
`inspect` and `log` are bounded in the CLI, where the caller's identity exists. `cleanup`
keeps its own tighter `_descendants(me)` rule, which is right for that one verb. **The
board is not scoped** and neither is the human — DESIGN-TRUTH:180-181.

The refusal names the boundary out loud ("in another top orchestrator's tree") rather than
saying "not found": a workflow that quietly stops crossing trees would otherwise look
exactly like one that mistyped a name.

### The one thing the acceptance run caught that the unit tests did not

`sb delegate` typed by a person makes a root that is parentless and **unstamped**. Rooting
each such agent in itself made two of them two trees, and a `sb tell` between them was
refused — which is not what the rule says: only *another top orchestrator's* tree is
invisible, and that is not what they are in. `top_of` now answers `human` for an unstamped
root, so the human's own direct spawns are one group, mutually visible, and still cannot
see into any top's tree. Three tests pin it. `status`'s scope had to become a *set* rather
than a root name as a result, because the human's group has no row to name it.

---

## Live proof — isolated clone

`git clone` of the repo into a scratch directory, `phase5-structure` checked out there,
driven only by **that clone's own `./bin/sb`** (`sb doctor` confirmed the store path
resolved inside the clone). Real agents, real herdr workspaces, real worktrees.

### 1. The stamp, and where a top's spawn lands

| agent | spawned by | caller | landed as | `is_top` |
|---|---|---|---|---|
| `top-a` | `sb start` | human | new bare space over the clone | **1** |
| `lead-1` | `top-a` | a top | **new space + worktree** `lead-1` | 0 |
| `sub-1` | `lead-1` | orchestrator, has worktree | **tab in `lead-1`** | 0 |
| `grand-1` | `sub-1` | sub-orchestrator | **tab in `lead-1`** | 0 |

Three deep, one fork. `sub-1`'s whole subtree stayed in the lead's space, which is
DESIGN-TRUTH's "its whole subtree stays in that one space".

### 2. The bug itself, fixed

`bare-sim`: `parent='top-a'`, `branch NULL`, `workspace='top-a'` — the exact shape the six
live production rows have. Planted directly into the clone's own store, as the diagnosis
did, because `sb delegate --workspace <bare space>` is refused on this branch and the shape
can no longer be minted organically. Everything downstream of it is a real `sb delegate`.

    bare-sim (non-root, no worktree) → child-of-bare
      branch NULL, workspace 'top-a'   ← a TAB in the caller's own space

Under the old rule this forked a brand-new space and worktree (`grandchild-1` in
`audit/phase5-spawn-placement.md`). After the fix the whole clone held exactly one forked
branch, `lead-1`. **This is the central finding, closed.**

`grand-1`, a `worker`, then ran `sb delegate`:

    sb: a worker does not spawn agents — only a role with delegate rights does (today:
    orchestrator). If this task is bigger than one agent, or needs a decision you were not
    given, say so to your parent with `sb done` rather than growing a tree under yourself.

No row and no pane were created for the refused name.

### 3. The migration, proved rather than assumed

`ALTER TABLE agents DROP COLUMN is_top` on the clone's live store, `schema_hash` reset —
i.e. the store as it was before this phase, with a real six-agent tree already in it. The
next `sb` command migrated it:

    top-a           is_top=1     ← the only real top, correctly stamped
    lead-1          is_top=0
    sub-1           is_top=0
    grand-1         is_top=0
    bare-sim        is_top=0     ← parentless-looking shape, correctly NOT stamped
    child-of-bare   is_top=0

Then the **backfilled** `top-a` delegated `after-backfill`, which forked its own space and
worktree — the behaviour the migration exists to preserve, not just the column value.

### 4. The tree boundary

Second top `top-b` started, with a child `b-kid`. From `after-backfill` (inside `top-a`'s
tree):

| command | result |
|---|---|
| `sb tell bare-sim` (sibling, same tree) | `sent to bare-sim` |
| `sb tell b-kid` (other tree) | refused, named as a boundary |
| `sb inspect b-kid` | refused |
| `sb restore b-kid` | refused |
| `sb log --agent b-kid` | refused |
| `sb status` (no flags) | 7 agents, **2 hidden** — `top-b` and `b-kid` |
| `sb log` (no agent) | every agent in `top-a`'s tree, none from `top-b`'s |

The same two commands as the human: `sb status` showed both trees, `sb log` showed both
trees' agents.

### Teardown

Every agent closed with `sb cleanup --force <name>` leaves-up, every workspace with
`sb workspace close <name> --yes`, the three worktrees herdr put under
`~/.herdr/worktrees/clone/` removed with them, that empty directory removed, the clone
deleted. `herdr agent list` confirmed nothing from the clone was left running. **No
`pkill`, scoped or otherwise.** Nothing outside the clone's own store and worktrees was
touched; the production store was only ever read, read-only.

---

## `./acceptance/accept.py phase5-structure` — three runs, verbatim

**Run 1**, before the two fixes it caught:

      1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [48s]
      2  a child's report wakes its parent        FAIL   the child never reported to its parent   [4m32s]
      3  a block holds until the human answers    FAIL   the sibling never sent its message   [4m48s]
      4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbyo18xs4-k: blocked, not finished — it has not reported an end'   [1m09s]

    2 of 4 FAILED — the fleet is not sound   (4m56s)

Neither was a flake, and both were worth having. Check 2's parent is a `worker` whose whole
job is to delegate — refused by 5.3, which reads from outside as "the child never
reported"; the fixture now asks for `--role orchestrator`. Check 3 is two agents the human
spawned directly, i.e. two parentless unstamped roots, and its `sb tell` was refused by a
boundary rule that should never have separated them; that is the `top_of` fix above.

**Run 2**, after both:

      1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [16m36s]
      2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 42s later; the parent woke and read it   [17m33s]
      3  a block holds until the human answers    FAIL   the agent could not be spawned   [15m51s]
      4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbk6njm74-k: blocked, not finished — it has not reported an end'   [50s]

    1 of 4 FAILED — the fleet is not sound   (17m39s)

Check 3's failure here is the known spawn-delivery flake, named as such in the brief:
`herdr [task_undelivered] sbk6njm73-b started, and its task could not be got into it`. The
run took 17m39s against 4m56s for run 1 — the machine was loaded, which is the condition
the flake is known to appear under. Re-run, as the brief instructs.

**Run 3**, unchanged code:

      1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [1m28s]
      2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 49s later; the parent woke and read it   [2m14s]
      3  a block holds until the human answers    PASS   held 52s against a sibling, released by the human's answer and read it   [1m45s]
      4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbn3ntk84-k: blocked, not finished — it has not reported an end'   [1m06s]

    all 4 pass — the fleet is sound   (2m20s)

---

## Live-fleet audit — who the 5.3 refusal would cut off

Read-only query against `/Users/andrew/Code/switchboard/.git/agentflow/state.db`, 252 rows,
run at build time as Andrew asked.

**Agents that have exploited the gap: 8, all finished, none with a live child.**
`prompt-work` (11 children), `worker-2` (16), `accept-phase1` (10, role `qa`),
`fix-spawn-2` (4), `verify-prompt-drop` (3, role `qa`), `split-fixer`, `board-teardown`,
`audit3-finish` (1 each). Every one of them has `ended_at` set, and every one has zero
children that are still live. **The refusal cuts nothing off mid-task.**

**Live agents at build time: 5.** `main-5` and `main-7` (roles `orchestrator`, both tops —
unaffected), and three `worker`-role agents: `tell-modes`, `phase4-removals` and
`phase5-structure` (this agent). None of the three has ever spawned a child. They *would*
be refused if they tried — but the live fleet runs whatever `sb` is on `PATH`, which is
`main`, so nothing here reaches them until this is integrated. Nothing to hold back.

**The six worktree-less non-root agents that prompted the diagnosis**, re-checked as the
brief asked: `sb-guard`, `workspace-debug`, `design-patch`, `phase1-split`, `verify-design`,
`wm-land` — all six still have `ended_at` set (`done` or `failed`). The fix strands no
running work.

---

## Fixtures that had to change, and why

Not incidental churn — each described a shape the code now refuses.

- `role="main"` in 26 test fixtures. `main` is not a role in this repo (`vocabulary
  .main_role` is `orchestrator`), so those rows fell through to the fallback role and could
  not delegate. Renamed to `orchestrator`, which is what they were always meant to be.
- Fixtures that built a "root orchestrator's space" now carry `is_top=True`. That is the
  fix restated: bareness was standing in for top-ness in the tests exactly as it was in the
  code.
- `ForkRuleTest`'s `test_a_child_of_a_bare_parent_is_forked_its_own_worktree` was renamed
  to `..._of_a_top_...`, and the class docstring rewritten. Its old premise was the bug.
- Messaging fixtures that made a sender and a recipient out of two parentless rows now
  build one tree. Two parentless rows are two trees in the general case, and the tests are
  about an orchestrator and its worker.
- `acceptance/accept.py` check 2 spawns a parent whose whole job is to delegate; it asks
  for `--role orchestrator` now.

---

## Not done, and stated rather than left silent

- **The role prompts say nothing about any of this.** None of the five role files mentions
  that it cannot spawn, or that a top's spawns land differently. Deliberate: phase 6 owns
  the prompt rewrite and BUILD-PLAN's own ordering rule is "the prompt should explain a
  rule the code already enforces". The refusal message carries the explanation meanwhile.
- **`sb workspace new` is still a separate command.** Phase 4's 4.4 deferred its deletion
  to "once phase 5 covers space creation". 5.2 fixed the fork rule but did not fold
  `workspace_new`'s creation logic into `delegate`, so that deletion is still outstanding
  and is not claimed here.
- **A worktree-less non-top agent's child now lands in the caller's bare space**, which for
  an agent in a top's space is the human's main checkout. That is what "its whole subtree
  stays there" means, and it is the shape §2 proves. It is only reachable for a row that
  already exists: the path that mints one (`sb delegate --workspace <bare space>`) is
  refused on this branch. Worth knowing about; not changed, because nobody asked for a
  fourth rule.
- **Not proved:** anything about several agents crossing the boundary concurrently, and
  anything about the migration running under a live fleet (the clone's fleet was small and
  quiet). The `_reconcile` path itself is unchanged and already carries its own concurrency
  tests; only a new column and its fill were added to it.
