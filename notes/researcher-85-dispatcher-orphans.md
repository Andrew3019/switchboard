# Why closing a dispatcher orphans its children's herdr spaces

## 1. Workspace model: a dispatcher is bare, its children fork their own spaces

Only `sb start` stamps `is_top=True` (`broker.py:1291-1299`, in `_top`). A top's own
workspace is **bare** — no worktree, created with `create_workspace(name, cwd=str(self.repo))`
(`broker.py:1280`), living over the main checkout.

`delegate()`'s "FORK RULE" comment (`broker.py:3400-3428`): a child is forked into its
**own new worktree workspace** (named after the child's own agent name) exactly when the
caller `mints_space()`, i.e. is a top (`broker.py:3428-3435`, via `_fork_for`,
`broker.py:3228`). Any non-top spawning a child just adds a tab inside its own existing
workspace.

Net effect for a dispatcher (a top, so bare): every **direct** child it delegates to gets
its own separate herdr worktree workspace, named for that child (`_fork_for`,
`broker.py:3229`: "The branch is the agent's NAME"). Grandchildren (children of that child)
share the child's workspace, since the child is not a top and doesn't re-fork.

So a dispatcher's subtree is NOT one workspace — it's the dispatcher's bare space, plus one
separate worktree-workspace per direct child.

## 2. `sb workspace close <dispatcher>` never looks past the dispatcher's own workspace

`workspace_close()` (`broker.py:1782`) resolves the named workspace's row and routes to one
of three cases. A dispatcher (bare, no checkout) goes through `_close_bare`
(`broker.py:1869`).

`_close_bare`'s only gate is `_unfinished_in(name, exclude=me)` (`broker.py:1891`,
`2219-2230`):

```python
def _unfinished_in(self, name, *, exclude=None):
    """This workspace's OWN rows, by name [...]
    Deliberately not `_unfinished_under` — see `_close_bare` for why [...]"""
    return [r for r in self.db.execute(
        "SELECT * FROM agents WHERE workspace=? AND state NOT IN (...)", (name,)
    ).fetchall() if r["name"] != exclude]
```

This is a `WHERE workspace=?` query keyed on the dispatcher's own bare-workspace name. A
forked child's rows have `workspace=<child's own name>`, a **different** value — so they
are structurally invisible to this gate. The docstring says this is deliberate (not
`_unfinished_under`), for a real reason: `_close_bare` reuses this same predicate as its
gate, and it's scoped this way on purpose so a fleet of bare orchestrators sharing the main
checkout doesn't refuse each other forever (see `_close_bare`'s own docstring,
`broker.py:1872-1886`).

Consequence: `sb workspace close <dispatcher>` will happily retire the dispatcher's bare
space **even while its forked children are still fully alive and working** — no warning,
no refusal, nothing. It only stops panes and drops rows that literally have
`workspace=<dispatcher-name>` (`_stop_panes`, `broker.py:2443-2510`, same `WHERE
workspace=?` scoping). The children's forked worktree workspaces are never touched, never
even inspected — they just sit there in `workspaces` table, fully registered, forever,
until something else notices them.

## 3. What "later reports as `kept space X: holds N ignored file(s)`" means

That message comes from `sb cleanup`, a **different** command
(`cli.py:1127-1167`, reading `CleanupResult.spaces_refused`).

`cleanup()` (`broker.py:4062`) picks candidates from the caller's own subtree
(`self._descendants(me)`) or, run by a human with no names, **every** agent in the DB
(`broker.py:4128-4134`). It closes finished agents' panes, then calls
`_close_empty_spaces(candidates, ...)` (`broker.py:4552`), which — for each **distinct**
workspace those candidates worked in — tries `workspace_close()` on it
(`broker.py:4599-4608`).

So `sb cleanup` (unlike `sb workspace close <dispatcher>`) **does** reach a dispatcher's
orphaned child spaces, because its candidate scope is the whole subtree/DB, not one named
workspace. But `workspace_close` on a forked child goes through the checkout-owning path
(`_close_checkout`, `broker.py:1938`, via `_space_ready`, `broker.py:4636`), which inspects
`_ignored_weight(checkout)` (`broker.py:1744`) — `git status --porcelain --ignored`. Any
git-ignored, untracked file that isn't one of switchboard's own `LINKED_CONFIG` symlinks
counts as "unknown" (typical culprits: a real `.env`, `.claude/settings.local.json`,
scratch/notes files an agent wrote, build artifacts — anything gitignored that a worktree
delete would silently destroy). With `confirm=False` (always true for a sweep/cleanup —
`broker.py:4647-4649`, "a sweep never answers a question that was put to a person"), any
nonzero "unknown" count refuses the close and it's reported as `spaces_refused`, rendered
as `kept space <name>: holds N ignored file(s)` (`cli.py:1157-1159`).

So "kept space" is `sb cleanup` working as designed on a space it only reached long after
the fact — it is the FIRST time anything even tried to close these children's spaces, and
it refuses because untouched worktrees accumulate ignored content (agent scratch files,
local settings) that only a human-confirmed `sb workspace close <name> --yes` may destroy.

**Root cause, one sentence:** `sb workspace close <dispatcher>` closes exactly the one
named (bare) workspace row and nothing else; a dispatcher's real children live in entirely
separate, self-forked worktree workspaces that this command has no path to discover, so
closing a dispatcher leaves them registered and unclosed until an unrelated, later,
DB-wide `sb cleanup` stumbles onto them — usually finding them already too dirty
(ignored files) to auto-delete.

## 4. PR #116 — does it touch this? No.

PR #116 (`herdr-cleanup-gaps` branch, https://github.com/Andrew3019/switchboard/pull/116)
is "cleanup: a board pane herdr could not close is retried, not forgotten." It's entirely
about `_close_board` (`broker.py:1459`) — the small terminal split-pane opened *beside*
each agent for readability — and fixes a narrow bug where a *transient herdr failure*
closing that board pane dropped the `meta:board_pane:<name>` row anyway, permanently
orphaning a pane. Its fix threads a `settled: bool` return through `_close_board` and holds
the agent row open (`refuse` + `continue`) instead of forgetting on defer.

It never touches `workspace_close`, `_close_bare`, `_unfinished_in`, `_close_empty_spaces`,
`_fork_for`, or anything about herdr **worktree/worker spaces**. It's a different bug in a
different subsystem (board panes vs. worktree workspaces) that happens to share the word
"close."

**Verdict: no overlap, no conflict.** #116 does not fix, partially fix, or touch the
dispatcher-orphan case at all. Our fix (if pursued) would land in
`workspace_close`/`_close_bare`/`_close_empty_spaces`, none of which #116 changes.

## 5. Is there a clean fix? Options

**A — Cascade `_close_bare` through the dispatcher's own subtree.**
Reuse, don't reimplement (matches the codebase's own stated principle at
`broker.py:4560-4565`: "every gate [...] is `workspace_close`'s, unchanged, because a
second implementation [...] is the one thing this change must not add"). Concretely:
  1. Before retiring, refuse if `live_descendants(name)` is non-empty (that helper already
     exists and is exactly what `cleanup`'s gate uses, `broker.py:4841`, `4099-4111`) — this
     closes the "dispatcher closed while children still working" hole from §2.
  2. After the dispatcher's own bare-space retirement, call the same
     `_close_empty_spaces` machinery `cleanup` already uses, but scoped to
     `_descendants(name)` (`broker.py:4951`) instead of the caller's own scope — so
     `sb workspace close <dispatcher>` actually attempts to close every forked child space,
     with the same gates, same inventory, same `spaces`/`spaces_refused` reporting `sb
     cleanup` already gives.

  This makes "closing a dispatcher" and "cleaning up a dispatcher's subtree" the same
  operation for the one case that matters (all descendants finished), while still refusing
  loudly rather than silently for the other case (live descendants). No new deletion
  path — every primitive (`live_descendants`, `_descendants`, `_close_empty_spaces`,
  `_space_ready`) already exists and is unit-tested for `cleanup`.

**B — Refuse-only (no cascade).** Just add the `live_descendants` gate from A.1, and leave
finished-but-unclosed child spaces exactly as today (silent, discovered later by `sb
cleanup`). Smaller, safer diff, but doesn't actually fix "closing a dispatcher orphans
children's spaces" — it only prevents the worse live-children case. Leaves the brief's
literal bug (finished children, never-closed spaces) unaddressed.

**C — Workflow-only, no code change.** Tell dispatchers/humans to always `sb cleanup
<dispatcher>` (which already correctly cascades) before or instead of `sb workspace close
<dispatcher>`. Cheapest, but relies on discipline `sb` itself does nothing to enforce, and
the dangerous case from §2 (children still live) stays a silent trap either way.

**Recommendation: A.** It's the only option that actually stops spaces from being orphaned
by this command, it costs no new "is it safe to delete" logic (pure reuse), and it matches
the doc-cited design principle for this exact function family. B is a reasonable
first/cheaper increment of A if the team wants to land the safety half first. C fixes
nothing, only documents a trap that still exists.

## What's unverified

- I did not find or run a live repro (no clone/worktree spin-up was done — investigate-only
  task). Everything above is read from the code paths and PR #116's description/diff
  metadata via `gh pr view`, not executed.
- I did not check whether any *other* command (besides `sb workspace close` and `sb
  cleanup`) can retire a bare dispatcher workspace — only `cli.py:1200` calls
  `workspace_close` directly, and `cleanup`/`sweep` are the only other callers I found
  (`broker.py:4602`, `4749`). I did not read `sweep()` (`broker.py:4684`) in detail beyond
  confirming it also just calls `workspace_close` under the same gates.
