# Why does switchboard create so many worktrees?

Investigation only — no code, no worktree, nothing touched. All checks below are
read-only (`git status`, `git worktree list`, `sqlite3` SELECTs, `sb workspace list
--json`, one throwaway `git worktree add`/`remove` in `/tmp` for timing, cleaned up
immediately after).

## 1. The rule, exactly — confirmed from code

`Broker.delegate` (`switchboard/broker.py:3033`), the comment block at
`broker.py:3069-3104` ("THE FORK RULE"):

- A new worktree+space is minted **only** when `self.mints_space(me)` is true on the
  **inherited** path (caller passed no explicit `workspace=`). `mints_space` reads the
  `is_top` stamp written by `sb start` (`_top`) and nothing else — not role, not whether
  the caller already holds a worktree.
- Anyone else's `delegate` (an orchestrator, a lead, a bare agent) puts the child in a
  **tab in the caller's own space** — same worktree, same checkout.
- This exactly matches the prior investigation's conclusion (`board-worktree-grouping.md`
  on `researcher-32`) and DESIGN-TRUTH's confirmed entries ("Only `sb start` ever creates
  a top orchestrator", "A worktree belongs to a space, not to an agent").

**Naming.** `_fork_for` (`broker.py:2904`): branch name = worktree name = **the agent's
own name**, verbatim, no prefix/suffix — "the name is already unique (`agents.name` is
the primary key)". Forked from the parent's own branch if the parent is on one
(`_inherited_base`, `broker.py:2974`), otherwise from freshly-fetched `origin/main`.

**`sb cleanup`** (`Broker.cleanup`, `broker.py:3599`) — I read this fully. It closes
finished agents' **panes** (`release_agent`/`close_pane`), the board, the prompt file,
and marks the row `done`. It does **not** touch the worktree or the branch anywhere in
that function. The docstring says exactly this: "Safe to be aggressive: closing costs
only the pane." Worktree/branch deletion lives entirely in a separate function,
`Broker.workspace_close` (`broker.py:1483`), which routes to `_close_bare` / `_close_gone`
/ `_close_checkout` and is the only place `git worktree remove` (`broker.py:2218`,
`_deregister`) and `git branch -d` (`_finish`, `broker.py:1734`) get called.

**The two are wired together nowhere.** I grepped every call site of `workspace_close(`
in `broker.py` and `cli.py` — the only caller is the CLI's `sb workspace close`
(`cli.py:1088`). `sb cleanup` never calls it, directly or indirectly. So on the current
code, **`sb cleanup` cannot delete a worktree, no matter how idle or finished the space
is.** The only way a worktree goes away is a human or agent typing `sb workspace close
<name>` by hand.

**This contradicts a DESIGN-TRUTH entry.** DESIGN-TRUTH.md says (confirmed 2026-08-09,
under "Commands"):

> "Cleanup closes the agents, closes the tab, and closes the entire space and deletes
> the worktree if everything else is closed too."

That is Andrew's confirmed *intent*. The code does the first two (agents, tab) and stops
— it never checks whether "everything else is closed" and never deletes the space or
worktree. I did not find any other mechanism (reconciler, background sweep, hook) that
does this either — `run_reconciler`/`Broker.reconcile` (`collector.py:256` on) only pings
stalled agents to get them to report done/blocked; it never closes a workspace.

**`sb restore`**: `Broker.restore` (`broker.py:3867`) explicitly cannot bring an agent
back once its worktree is gone ("A worktree that has been deleted is the end of this
agent" — `broker.py:3907`), matching DESIGN-TRUTH's "`sb restore` is gone if the worktree
is gone."

## 2. Why it exists — what's actually recorded

DESIGN-TRUTH.md does **not** record "isolation between concurrently-writing agents" as
the stated reason anywhere — I grepped for "isolat", "concurrent", "conflict": zero
hits. What it does confirm is the *rule* and its *consequence*, not a rationale:

> "A worktree belongs to a space, not to an agent." / "A lead's children share its
> worktree, so the lead assigns disjoint files and serialises anything that overlaps."

So: concurrent-write safety is the obvious motive and it is consistent with everything
else in the file, but it is my inference, not something Andrew stated as the reason. If
that matters, it's worth getting him to confirm it explicitly so it can go in
DESIGN-TRUTH rather than staying assumed.

## 3. What it actually costs — measured, not estimated

- `git worktree list` in `/Users/andrew/Code/switchboard`: **102 entries** besides the
  primary checkout (confirms the "101" in the task — I ran it fresh and it's currently
  102; one more agent forked between when the task was written and now).
- **Disk**: `du -sh ~/.herdr/worktrees/switchboard/` = **536M** total. `.git/worktrees`
  (the git admin metadata for all of them) = **3.9M**. So working-tree checkout content
  is ~99.3% of the cost, git bookkeeping is negligible (~0.7%). One sample worktree
  (`adv-r1-harm`) is 2.7M; the primary checkout is 65M (has extra build/dev artifacts the
  bare worktrees don't). Average per worktree ≈ 5.2M. In absolute terms 536M is not a
  large amount of disk on a modern machine — this is not a space emergency.
- **Creation time**: one throwaway `git worktree add -b <branch> <path> origin/main`,
  timed: **0.157s total** (`0.03s user 0.08s system`). Worktree creation itself is not a
  meaningful cost; `switchboard/herdr.py`'s `create_worktree` even gives it the same
  generous timeout as other slow spawn steps purely because "how long `worktree create`
  takes is a property of the repo," not because it's normally slow.
- **Uncommitted changes**: looped `git -C <path> status --porcelain` over all 102
  non-primary worktrees. **1 dirty, 101 clean.** (The one dirty one, `split-scout`, has
  uncommitted tracked changes sitting in it — that's the one genuinely irreplaceable
  worktree in the set; deleting it would lose real work.)
- **Merged into `origin/main`**: checked each worktree's checked-out branch with
  `git merge-base --is-ancestor <branch> origin/main` after `git fetch origin main`.
  **57 of 102 are already merged**, 45 are not.
- **Agent/row state**, via `sb workspace list --json` (the tool's own accounting, which
  merges the agents table with git's live worktree registry — I did not hand-roll this
  from the DB, since a direct sqlite3 read against the live store risked reading a stale
  replica mid-checkpoint; the `sb` CLI call is read-only and canonical):
  - 207 workspace names ever recorded. 103 still have a checkout on disk (`verdict:
    "ok"`, roughly matching the 102 from `git worktree list` — off by one likely because
    the primary checkout also gets a row). 87 are `"absent"` (checkout already gone from
    disk — someone deleted them without going through `sb workspace close`, since that
    matters for the next point). 17 are `"bare"` (top orchestrators, no checkout, as
    expected — they were never worktrees).
  - Of the 103 still on disk, only **7 have any unfinished agent row** — the other
    **96 are worktrees for spaces where every recorded agent already finished**, sitting
    there because nothing closes them.
  - **`retired_at` is `null` on all 207 rows, with no exceptions.** That is the
    strongest single piece of evidence here: as far as the store's own bookkeeping is
    concerned, `sb workspace close` has never successfully completed against a single one
    of these 207 workspaces, ever, in this repo's history. Whatever removed the 87
    "absent" ones did it outside `sb` (`git worktree remove` run by hand, most likely, or
    some other process) — the tool's own close path leaves a trace (`retired_at`,
    `workspace_retired` event) and none of the 207 rows carry it.

**Bottom line on cost**: disk (536M) and creation time (0.16s) are both small and not
worth optimizing on their own. The real cost is clutter and untracked risk: 101 of 102
are clean and 57 are already merged, so a large majority are safe to delete right now,
but nothing in the tool currently does, or ever has.

## 4. Is anything cleaning them up?

**No.** Confirmed from three independent angles: (a) reading `cleanup()` — it doesn't
call `workspace_close`; (b) grepping every call site of `workspace_close(` — only the CLI
command; (c) `sb workspace list --json` — `retired_at` null across all 207 rows in this
repo's whole history. `sb cleanup`, run "aggressively" per DESIGN-TRUTH's stated intent
for orchestrators, closes panes and marks agents done — it never frees the worktree it
was told to free. There's no scheduled prune, no reconciler-driven sweep, nothing. The
101-102 worktrees are not a sign of the fork rule being too eager on its own; they are
what *any* volume of forking looks like after enough time with the intended cleanup step
unimplemented.

## 5. Is the granularity right?

Every one of the "does the checkout survive?" facts above (57 merged, 101/102 clean)
comes from spaces where the top-orchestrator-forks / children-share rule is already the
one in DESIGN-TRUTH and is explicitly reasoned about there (leads "assign disjoint files
and serialise anything that overlaps" for children sharing one worktree). That already
puts a second, softer defence (file-ownership discipline) alongside the worktree
boundary for everything *below* a top. So the actual per-top granularity looks
reasonable given what's confirmed: it isolates the one case (sibling tops, e.g. two
unrelated `sb start` trees, or two independent things Andrew is doing at once) where nothing
else defends against a collision, and relies on softer discipline everywhere collisions
are already coordinated by a single lead. I did not find any evidence in the code or
DESIGN-TRUTH of concurrent-write incidents that this granularity was tuned in response to
— DESIGN-TRUTH records the rule, not a war story that justified it — so I can't confirm
whether a coarser or finer cut was ever seriously compared against this one.

## Options

**A. Keep as is.** Nothing changes. Cost: worktrees keep accumulating at whatever rate
tops fork; disk cost stays small per-worktree but grows unbounded; clutter (episode
count, `git worktree list` noise, `sb workspace list` noise) grows with it. Risk: none new
— it's the status quo. Size: none.

**B. Wire up what DESIGN-TRUTH already says should happen — auto-close a space (agents +
tab + worktree) once every agent in it is finished, clean, and (optionally) merged.**
This isn't a new design decision, it's closing the gap between the confirmed entry
("deletes the worktree if everything else is closed too") and the code, which currently
only does the "everything else" half. Cost: implementation work in `cleanup()` or a
follow-up sweep to check "is this space now fully empty, clean, and finished" and call
`workspace_close` for it. Risk: `workspace_close`'s destructive path already gates on
dirty content and live descendants (`_close_checkout`'s inventory/gate), so the same
protection applies — the risk is scoping the trigger correctly (e.g. don't auto-close a
space with an unmerged-but-intentionally-parked branch someone plans to return to; the
existing dirty-check protects against losing uncommitted work, but a *clean, committed,
unmerged* branch could still be work someone wanted to keep). Size: small-to-medium — the
gating logic already exists, it's the missing call and the "auto" trigger condition that
need building, plus a decision on how aggressive to be about unmerged-but-clean branches.

**C. Fork less eagerly** (e.g. only fork on some stronger evidence of concurrent-write
risk, not automatically for every top-level delegate). This directly contradicts a
DESIGN-TRUTH-confirmed rule ("Only `sb start` ever creates a top orchestrator... a top's
spawn gets a new space and worktree" — confirmed 2026-08-09), so it isn't something to
just build; it would need Andrew to explicitly revisit that entry. Size: large — touches
a core, explicitly-confirmed mechanism, and DESIGN-TRUTH says contradicting a confirmed
entry means stop and ask rather than proceed.

**D. Share one worktree more broadly and rely on file-ownership discipline instead of a
directory boundary.** Same problem as C, deeper: it doesn't just relax the fork
threshold, it removes the isolation DESIGN-TRUTH's whole worktree-per-top model rests
on. Larger change than C, same "ask Andrew first" gate.

## Recommendation

**B.** The one reason that decides it: **the current state isn't "the fork rule is too
eager," it's "the cleanup half of the confirmed design was never built."** 96 of the 103
worktrees still on disk belong to spaces where every agent already finished, 101 of 102
are clean, and 57 of 102 are already merged — those numbers say the *volume* of forking
isn't the problem, the missing close step is. B fixes the actual gap without touching the
fork rule at all, which is the one piece of this DESIGN-TRUTH explicitly guards
("contradicting a confirmed entry" needs Andrew's sign-off) — C and D both require
reopening that rule for a problem that doesn't need it reopened.

**Is 101/102 a problem to fix now, or just untidy?** Just untidy. Disk cost is 536M
(small) and creation time is 0.16s (negligible); nothing here is degrading performance
or blocking work. The one thing worth Andrew's attention sooner rather than later is the
DESIGN-TRUTH/code mismatch itself (§1) — not because the worktrees are costly, but
because a confirmed entry currently describes behavior the code doesn't have, and that's
exactly the kind of drift DESIGN-TRUTH is supposed to prevent silently happening.
