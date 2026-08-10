# Audit B — worktrees and spaces (reviewer-2, read-only)

Scope: two DESIGN-TRUTH entries — "a worktree belongs to a space, not to an agent" and
"a workspace forks from `origin/main` by default" — on the storage/creation side.
Nothing was changed. All paths below are in the `worker-2` checkout
(`/Users/andrew/.herdr/worktrees/switchboard/worker-2`).

## Verdicts

| # | Entry | Verdict |
|---|-------|---------|
| 1 | A worktree belongs to a space, not to an agent | **PARTIAL** |
| 2 | A workspace forks from `origin/main` by default | **SATISFIED** (one latent defect, listed) |

---

## Entry 1 — "A worktree belongs to a space, not to an agent" — PARTIAL

### What is satisfied

**The sharing rule exists and is the one rule.** `Broker.delegate` (`switchboard/broker.py:1294-1312`):
a child inherits its parent's workspace unless a workspace was named
(`inherited = workspace is None`, line 1284), inherits the parent's branch with it
(lines 1291-1292), and forks a worktree **only** when the parent has none
(`if inherited and not self.has_worktree(me)`, line 1311). So a lead's spawns are tabs in
the lead's space, and a child of a bare parent (the top orchestrator, or the human) gets
its own. That is exactly the entry's first two sentences.

**`has_worktree` is a stored fact, not a guess.** `broker.py:1026-1040` reads
`agents.branch` for that agent; `HUMAN` answers None and therefore forks. The column exists
for this purpose (`switchboard/store.py:151-157`).

**A forked space is named after the child and refuses collisions.** `_fork_for`
(`broker.py:1215-1245`) uses the agent name verbatim as the branch and raises `BranchTaken`
if a local head of that name exists (`_branch_exists`, `broker.py:1247-1259`).

**The top orchestrator's space is genuinely bare.** `_top` (`broker.py:434-494`) calls
`h.create_workspace` over `self.repo` — no `create_worktree` — and delegates with
`workspace=name` explicitly, which takes the non-inherited path so no fork happens and no
branch is recorded.

**Live confirmation** — the store at `/Users/andrew/Code/switchboard/.git/agentflow/state.db`:
`audit-1`, `reviewer-1`, `reviewer-2`, `reviewer-3` all carry
`workspace='worker-2', branch='worker-2', workspace_id='w1E'`, cwd
`/Users/andrew/.herdr/worktrees/switchboard/worker-2` — one space, four agents, one
checkout. The four `main*` roots carry `branch=NULL` with cwd = the primary checkout.
`python3 -m unittest tests.test_workspace` → 376 tests, OK.

### Gaps (each one line, buildable)

1. **The read-only exception does not exist anywhere.** `broker.py:1294-1299` states the
   opposite in so many words ("Role-agnostic: a researcher that only reads gets its own
   tree too"), and `sb delegate --help` offers no flag to decline a worktree — so the
   entry's third sentence ("the only time we do not use a worktree is a read-only task…")
   is unimplementable today.
2. **A failed fork silently drops a would-be-writer into the human's main checkout.**
   `_fork_for` returns `None` on any `HerdrError` (`broker.py:1235-1240`); `delegate` then
   falls through to `where = self.repo` (`broker.py:1321-1326`), so the child works in the
   top's bare space over `/Users/andrew/Code/switchboard`. Only an event log row
   (`fork_failed`) records it; the caller and the agent are told nothing.
3. **The worktree is stored per agent row, never per space.** There is no `workspaces`
   table; `agents.branch`/`workspace`/`cwd` are repeated on every row
   (`store.py:148-161`), and the space-level answer is *derived* from the oldest row that
   happens to have a branch (`store.workspace_branch`, `store.py:698-709`;
   `_recorded_path`, `broker.py:1008-1024`). Nothing constrains the rows in one workspace
   to agree.
4. **That divergence has actually happened.** In the live store, workspaces
   `plugins-redesign` and `workspace-model` each hold both branch-set rows and
   `branch=NULL` rows (`verify-design`, `wm-land`, `design-patch`, `phase1-split`), all
   with cwd inside the worktree. Any such row makes `has_worktree` answer False, so that
   agent's children fork a *new* worktree instead of staying in the space. I did **not**
   find a current code path that produces this — the NULL rows sit in one contiguous
   ~15-minute window, consistent with an older build — so treat the divergence as
   unexplained rather than as a live regression.
5. **Nothing ever tears a worktree down.** `grep -rn "worktree remove\|prune\|close_workspace\|delete_workspace" switchboard/ bin/sb`
   returns nothing; `Broker.cleanup` (`broker.py:1638-1750`) closes panes and sets state
   only. `git worktree list` in this repo shows 14 leftover worktrees and their branches
   from earlier runs. (This also contradicts the separate cleanup entry — "closes the
   entire space and deletes the worktree" — and is what makes `sb restore` never actually
   lose its worktree.)

---

## Entry 2 — "A workspace forks from `origin/main` by default" — SATISFIED

**The default is literally `origin/main`.** `defaults/settings.toml:111`
(`base_branch = "origin/main"`) → `broker.BASE_BRANCH` (`broker.py:80`) and
`herdr.BASE_BRANCH` (`herdr.py:41`). It is the default of `_attach_workspace`
(`broker.py:700`), of `workspace_new` (`broker.py:587`), of `herdr.create_worktree`
(`herdr.py:329`), and of the `sb workspace new --base` flag (`cli.py:253-254`).
`_fork_for` passes no base, so an inherited-path fork uses the same default
(`broker.py:1236`).

**It is fetched at fork time, not read stale.** `_attach_workspace` calls `_fork_base`
inside the create step (`broker.py:724-733`), which runs `git fetch origin main` before
forking (`_fork_base`, `broker.py:748-786`), then passes the resolved ref to
`worktree create --branch <name> --base <ref> --cwd <repo>` (`herdr.py:340-343`).

**Fork-vs-open is deliberate, not an accident.** `_attach_workspace` opens an existing
checkout of that branch instead of forking (`broker.py:715-719`, `_checkout_of`
`broker.py:1042-1061`), and `create=False` lookups never fork (`_workspace_id`
`broker.py:1074-1098`, `join_workspace` `broker.py:649-684`).

**What happens when `origin` / `origin/main` is missing** (`_fork_base`, `broker.py:769-786`):
no `origin` remote → fork from local `main`, flagged `no_remote`; fetch failed but
`origin/main` exists locally → fork from that, flagged `fetch_failed`; fetch failed and no
`origin/main` ever → fork from local `main`, flagged `no_remote_base`. The flag is carried
out in the result as `base_fallback` (`_result`, `broker.py:686-698`) and into the event
log (`fork` / `base_fallback` events).

### One defect, listed but not verdict-changing

6. **The local fallback ref is never checked to exist, so a `master`-based repo cannot
   fork at all.** I ran `Broker._fork_base("origin/main")` against three throwaway repos:
   `master`-only, no remote → `('main', 'no_remote')`; `master`-only with an `origin` →
   `('main', 'no_remote_base')`; `main`, no remote → `('main', 'no_remote')`. In the first
   two the returned `main` does not exist, so `worktree create --base main` fails, and by
   gap 2 above the child then lands silently in the parent's space. Config
   (`vocabulary.base_branch`) is the only workaround, and nothing prompts for it.

---

## Out of my slice (one line each, not investigated)

- `sb delegate --help` still advertises `--keep` and `--ephemeral`, which DESIGN-TRUTH
  lists under "Explicitly rejected"; `cleanup()` still takes `include_kept` and
  `leave_children` (`broker.py:1638-1640`). Belongs to whoever audits the command surface.
- `sb workspace new --no-board` exists (`cli.py:256-257`) against the rejected `--no-board`
  entry. Same owner.

## What I did not check

Spawn routing beyond the fork rule, the pane/board UI, mail/doorbell delivery, and whether
a bare agent can spawn — all reviewer-1/reviewer-3 territory per the brief. I did not test
a live spawn: every claim above comes from reading the source, querying the on-disk store,
running the existing test suite, and running `_fork_base` against throwaway repos.
