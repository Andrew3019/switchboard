# What a delegated child forks from, and how that was proved

## The bug

`Broker.delegate` forks a child a worktree when the parent has none — `_fork_for` →
`_attach_workspace(name)`, whose `base` defaulted to `BASE_BRANCH`, i.e. `origin/main`
(`defaults/settings.toml`). Nothing in that path ever looked at the branch the parent was
working on. So every child of a top orchestrator started at `origin/main`, and a branch
could not be acceptance-tested by the agents its own orchestrator spawned: they all ran
the code from main. Reproduced on this very worktree, which was created at `origin/main`
and was missing all 17 commits on `fix-sb-path`.

It compounds the `sb`-path pin (`audit/sb-path-pin.md`): with that fix each agent
faithfully runs *its own checkout's* `sb` — a checkout of old code.

## The rule now

`Broker._inherited_base()` reads the branch out of the parent's checkout (`_here`) and
that is what the fork starts from. Two cases fall back to `origin/main`, and neither is an
exception:

- **the checkout is on `main`.** Inheriting `main` means the *remote* one, freshly
  fetched, rather than however stale the local copy is — so a top orchestrator starting
  fresh work forks from today's main exactly as before.
- **a detached HEAD**, which has no branch to inherit.

Nothing is passed and nothing is remembered (PRINCIPLES C6): the branch is a fact read
from the checkout at the moment of the fork. `sb start --base` and `sb workspace new
--base` are untouched — a caller who says which base they want still gets it.

## Uncommitted work

Inheriting a branch is not inheriting a working tree: `git worktree add` starts at a
commit, so anything merely saved in the parent's checkout stays there. The spawn still
happens — a dirty checkout is the normal state of one, and refusing would refuse almost
every real spawn — and the parent is told on stderr, the same channel a skipped fragment
uses, with the count also written into the `fork` event.

Tracked files only. Untracked ones do not travel either, but a checkout with stray scratch
files is the normal case, and a warning that fires on every spawn is one nobody reads.

## A branch with a slash in it

`_fork_base` split its argument on `/` to find `remote/ref`, so an inherited branch called
`fix/thing` was read as `thing` in a remote called `fix` — the wrong branch when that ref
existed, and a silent `no_remote` fallback when it did not. Local heads are now resolved
first. This was harmless while every base was `origin/main`; inheritance makes it the
ordinary case.

## Proved in an isolated clone

Method from `audit/isolated-instance.md`: a separate `git clone` gets its own
`state.db` via `git rev-parse --git-common-dir`, so nothing touches the live fleet.

1. Cloned the repo to a scratch dir, checked out `fix-fork-branch` (tip `be539d4`).
   `./bin/sb doctor` reported the clone's own store; `sb status` was empty.
2. From that checkout, on that branch, spawned a real throwaway child:
   `./bin/sb delegate '...' --name forkproof-child`.
   stderr said: `sb: forkproof-child forked from 'fix-fork-branch' — your branch, not
   origin/main`.
3. The `fork` event recorded `"base": "fix-fork-branch", "inherited": true, "dirty": 0`.
4. The child's worktree was on branch `forkproof-child` at commit `be539d4` — the
   parent's tip, containing the fix itself. Under the old code it would have been at
   `origin/main`, three commits and one whole phase behind.
5. The `sb_pinned` event showed the child's PATH pointing at its own checkout's `bin` —
   so the child is not merely *on* the parent's branch, it *runs* that branch's code.
6. Cleaned up: `sb cleanup forkproof-child --force`, the leftover worktree removed with
   `git worktree remove`, the clone deleted. `herdr workspace list` and the live
   `sb status` show no residue.

Tests: `tests/test_broker.py::ForkBaseTest` (8 cases, over a real git repo with a real
local `origin`, since the answer is read out of a checkout). Full suite: 1756 tests, OK.

## Noticed, not fixed

`sb cleanup forkproof-child --force` closed the agent and its herdr workspace but left
the git worktree on disk at `~/.herdr/worktrees/fork-proof-clone/forkproof-child`,
registered in `git worktree list`. DESIGN-TRUTH says cleanup deletes the worktree once
everything else is closed. Not investigated — it was outside this task.
