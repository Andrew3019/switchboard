## Symptom

Worktrees are never deleted. They accumulate for the life of the repo and nothing in the
tool has ever removed one.

As measured on 2026-08-14: **102 worktrees on disk** besides the primary checkout,
**536 MB** in `~/.herdr/worktrees/switchboard/`. **101 of the 102 are clean** (no
uncommitted changes) and **57 have branches already merged into `origin/main`** — so the
large majority are safe to delete and none of them are being deleted. A re-check a few
hours later showed 107 checkouts against 211 recorded workspaces, so the number grows
with use rather than settling.

## This contradicts DESIGN-TRUTH

`DESIGN-TRUTH.md:229` says, confirmed 2026-08-09:

> **Cleanup closes the agents, closes the tab, and closes the entire space and deletes the
> worktree if everything else is closed too.** Work is usually pushed before its worktree
> is deleted.

The code does the first two halves and stops. `sb cleanup` closes the agents and the tab;
nothing ever checks whether "everything else is closed too", and nothing ever deletes the
space or the worktree. This is exactly the kind of drift DESIGN-TRUTH exists to prevent —
a confirmed entry describing behaviour the code does not have.

## Where the gap is, in the code

- **`Broker.cleanup`** — `switchboard/broker.py:3599`. Closes finished agents' panes
  (`release_agent` / `close_pane`), closes the board and the prompt file, and marks the
  row `done`. Its own docstring says "Safe to be aggressive: closing costs only the pane."
  The whole function body (lines 3599–3818) contains **zero** occurrences of `worktree`,
  `git branch` or `workspace_close`.
- **`Broker.workspace_close`** — `switchboard/broker.py:1483`. This is the only place
  worktree and branch deletion lives. It routes to `_close_bare` / `_close_gone` /
  `_close_checkout`, and is the only path that reaches `git worktree remove`
  (`_deregister`, `broker.py:2218`) and `git branch -d` (`_finish`, `broker.py:1734`).
- **The two are wired together nowhere.** The only call site of `workspace_close(` in the
  whole package is `switchboard/cli.py:1088`, the `sb workspace close` CLI command. So the
  only way a worktree is ever removed is a human or agent typing
  `sb workspace close <name>` by hand.
- No background sweep does it either. `Broker.reconcile` / `run_reconciler`
  (`switchboard/collector.py:256` on) only pings stalled agents to get them to report
  `done` or `blocked`; it never closes a workspace.

## The evidence that it has never happened

`sb workspace list --json` reports **`retired_at: null` on every single row, with no
exceptions** — 207 workspaces at the time of the investigation, 211 on re-check. The close
path leaves a trace when it completes (`retired_at`, plus a `workspace_retired` event), and
not one workspace in this repo's entire history carries it. **`sb workspace close` has
never once completed successfully.**

The same listing shows 87 workspaces as `"absent"` — checkout already gone from disk. Since
none of them have `retired_at` set, whatever removed those did it outside `sb` (a
hand-run `git worktree remove`, most likely).

And of the checkouts still on disk, **only 7 have any unfinished agent row**. The other
~96 belong to spaces where every recorded agent already finished — they are sitting there
purely because nothing closes them.

## Impact

Not urgent, and worth being honest about: 536 MB is not a lot of disk, and worktree
creation costs 0.157 s, so this is not degrading performance or blocking anyone. The real
costs are:

1. **Unbounded growth** — clutter in `git worktree list`, in `sb workspace list`, and on
   disk, growing with every top-level delegate, forever.
2. **The DESIGN-TRUTH mismatch itself**, which is the part worth attention regardless of
   the disk numbers.

## Recommended fix

**Close a workspace automatically once every agent in it is finished and its worktree is
clean.** This is not a new design decision — it is closing the gap between the confirmed
DESIGN-TRUTH entry and the code, which currently implements only the "everything else"
half.

The destructive machinery already exists and already gates itself: `_close_checkout`'s
inventory check refuses to throw away dirty content or a space with live descendants. What
needs building is the trigger — a check in `cleanup()` (or a follow-up sweep) for "is this
space now fully empty, clean and finished?", and the call to `workspace_close` when it is.

One decision to make while building it: **how aggressive to be about a clean but unmerged
branch.** The existing dirty-check protects uncommitted work, but a clean, committed,
unmerged branch could still be work somebody parked deliberately. `sb restore` cannot bring
an agent back once its worktree is gone (`broker.py:3907`, and DESIGN-TRUTH: "`sb restore`
is gone if the worktree is gone", `DESIGN-TRUTH.md:277`), so deletion is final.

Size: small-to-medium. The gating logic exists; the missing call, the trigger condition and
the unmerged-branch policy are the work.

## Source

Investigation notes: `notes/researcher-37-why-so-many-worktrees.md` on branch
`researcher-37`, which has the full method and every measurement. Every code reference and
the DESIGN-TRUTH quote above were re-checked against the files directly for this issue.

Related: the separate question of whether one worktree per top-level delegate is the right
granularity at all.
