# Can switchboard automatically create/attach a herdr space per top orchestrator?

Read-only investigation. herdr source checked at `/Users/andrew/Code/herdr` (git HEAD at
investigation time). switchboard source checked at this checkout. The prior notes file
this task's background cites (`notes/herdr-grouping-capability.md`) does not exist in
this worktree, so its claims are re-derived from code here rather than trusted.

## 1. What herdr actually keys "space" on

herdr has no persisted "Space" record at all. A **space is a runtime grouping of
workspaces that share the same `GitSpaceMetadata.key`**, computed fresh each time a
workspace's git identity is (re)discovered.

- `git_space_metadata_from_info` — `src/workspace/git/discovery.rs:71-100` — builds
  `GitSpaceMetadata { key, checkout_key, repo_name, repo_root, is_linked_worktree }`.
  - `key` (line 72-74) = the **canonicalized absolute filesystem path of the git common
    dir** (`git_common_dir`, i.e. the shared `.git` directory a worktree points at),
    stringified. **Not** a remote URL, not a repo name, not a commit hash.
  - `checkout_key` (75-77) = canonicalized path of the individual checkout's repo root
    (per-worktree, not shared).
  - `repo_name` (88-92) = derived from the common-dir's parent folder name — used for
    the auto label, not the identity.
- `git_worktree_info` (`discovery.rs:42-56`) is what produces `git_common_dir`: it walks
  up from `cwd` via `git_repo_root` (line 244) to find a `.git`, then resolves it to the
  common dir a linked worktree shares with its main checkout (`git_dir_for_repo_root`,
  `git_common_dir_for_git_dir`).
- This is set on a `Workspace` only via `cached_git_space = cwd.and_then(git_space_metadata)`
  — `src/workspace.rs:1175` (also `src/app/actions.rs:2711` on refresh). There is **no
  setter that assigns a workspace to an arbitrary/chosen space** — grep for
  `reparent|move_workspace|change_space|set_space|adopt` across `src/` turns up nothing;
  the only `move_workspace` (`src/app/actions.rs:1365`) reorders *display position*
  within a workspace list, confirmed by its own test name
  (`move_workspace_reorders_without_changing_logical_selection`, line 4550) — it does not
  touch `cached_git_space`. So: **confirmed, there is truly no reparent/move-into-space
  API.** Grouping is 100% a side effect of where a workspace's `cwd` happens to sit on
  disk relative to other workspaces' `cwd`s.

Grouping/UI side: `src/ui/sidebar.rs` groups workspaces whose `cached_git_space.key`
matches (tests around line 2863-2990, e.g.
`workspace_list_entries_group_multiple_workspaces_in_same_git_space`). A workspace with
**no** git identity (cwd not inside any repo) is never grouped with anything — test
`workspace_list_entries_leave_single_git_and_non_git_workspaces_flat` (line 2965) — it
sits alone. This matches the task background's claim that a free-standing labeled space
can exist but nothing can be placed inside it: a non-git workspace has no key for
anything else to match.

**No explicit "create space" call exists.** There's `herdr workspace create --cwd <dir>
--label <name>` (`src/cli/workspace.rs:41-102`, `src/cli/runtime.rs:23`) and `herdr
worktree create --workspace <id> --branch <name> [--base ...] [--path ...] --label
<name>` (`src/cli/worktree.rs:66-140`, the latter runs `git worktree add` under an
existing workspace's repo). Neither takes a "space" argument. A space is created purely
as the **implicit consequence** of the first workspace whose `git_common_dir` key hasn't
been seen before; it is looked up by no ID — herdr just recomputes the key from `cwd`
every time and groups matches. So "does a space already exist" isn't a question herdr
answers directly: switchboard would have to infer it from whether some other known
workspace's `git_common_dir` already equals the candidate's.

## Question 1 — does using a separate repo per task give this for free?

**Yes, mechanically it does, and it is a real option, not a dead end** — but it only
solves the *task-repo* half of the ask, not the *top-sits-above-repos* half.

- Any `cwd` whose `git_repo_root` walk lands on a `.git` directory with a common-dir path
  herdr hasn't seen before becomes a brand-new key → brand-new space, automatically, the
  moment a workspace or worktree is created there. A `git clone` of a repo into a new
  directory has its own `.git` (own common dir) → **new space, no herdr change needed.**
  A `git init` obviously too. This is confirmed directly from `discovery.rs:71-100`
  above, not inferred from behavior.
- What does **not** get you a new space: a `git worktree add` off an existing checkout
  (what `herdr worktree create` and switchboard's `broker.py` `worktree create --branch`
  both do — `broker.py:84,2244,2296,2641`). A linked worktree's `git_common_dir` is the
  *same* shared `.git` as its main checkout and every sibling worktree, so it lands in
  the exact same `key` and therefore the exact same space. This is exactly why, today,
  switchboard's own worktrees of one repo (e.g. all the `researcher-*`, `main-*`
  worktrees under this checkout) share one herdr space — verified by reading
  `broker.py:1001` (`self.h.create_workspace(name, cwd=str(self.repo))` — `self.repo` is
  literally "THIS worktree", per the comment at `broker.py:613-614`) alongside the
  `worktree create` call path, both of which point at the same repo's common dir.

So: **per-task-repo work (clone/init a fresh repo per task instead of a worktree of one
shared repo) does give automatic per-repo spaces for free**, purely from herdr's existing
identity logic — no herdr change required for that half.

**But it does not, by itself, give "top-level agents sit above repos."** A top
orchestrator today is created with `cwd=self.repo` (`broker.py:1001`), i.e. inside
*some* repo — currently the switchboard repo itself. If tops are meant to sit "above" any
one task-repo, a top's workspace `cwd` would need to point somewhere with **no** git
identity at all (or a different neutral repo). From the sidebar tests above, that makes
the top a flat, ungrouped, singleton entry — not "above" its children's spaces in any
structural sense herdr models; herdr has no parent/child relationship between spaces,
only "same key = same group" or "no key = alone." So top-above-repos is achievable
visually (a flat, un-grouped top workspace, distinct from any task-repo's space) but not
because herdr models hierarchy — it's just the absence of a shared key, which is already
true today for a non-git cwd.

### Cost of the per-repo-clone route
- **Disk:** a full `git clone` duplicates the whole object database per task (no
  `--shared`/`--reference` used anywhere in switchboard's worktree code today — that
  would need adding, and `--shared` has its own known git footguns around
  cross-repo object pruning). Worktrees currently share one object store; clones would
  not, unless switchboard explicitly passes `--reference`/`--shared` or
  `--dissociate` semantics are worked out.
- **Sync between clones:** nothing keeps sibling clones' branches/refs in sync
  automatically — `git worktree add` gets that for free (shared refs), a clone doesn't.
  Any cross-task branch sharing switchboard currently gets from worktrees-of-one-repo
  (e.g. `git worktree list` unifying all task branches, `broker.py:1415-1417`) would need
  reimplementing as explicit fetch/push between clones or a fetch from a shared remote.
- **Branch/PR flow:** unaffected in principle — each clone can still push a branch and
  open a PR against the same GitHub remote — but switchboard's current worktree-registry
  bookkeeping (`workspaces` table, `git worktree list` reconciliation in
  `broker.py:1303-1332,1415`) assumes one shared repo and would need a second code path
  for "per-task clone" bookkeeping.
- **Cleanup:** deleting a clone is simpler than `git worktree remove` in one sense (just
  `rm -rf`, no shared-repo bookkeeping to corrupt) but loses the safety switchboard
  currently leans on where a worktree can't be half-detached from its repo's ref
  database.
- This is a **structural change to how switchboard allocates a task's checkout**, not a
  herdr change, and it only applies when the *task itself* is "a repo" — it does nothing
  for spaces that aren't 1:1 with a single repo (e.g. today's model where multiple task
  workspaces share one repo on purpose, via worktrees, specifically so they can share
  refs/branches cheaply).

## 2. Fallback — smallest herdr change (sized only, not designed)

What's missing for "create a *named* space and land specific worktrees inside it" is a
way to assign a workspace's `cached_git_space.key` independent of its `cwd`'s actual git
identity — i.e. a manual override rather than the automatic discovery in
`discovery.rs:58-100`.

- The natural seam: `Workspace` already carries `cached_git_space: Option<GitSpaceMetadata>`
  (`src/workspace.rs:189`) and it's only ever populated by
  `discover_workspace_git_identity`/`git_space_metadata` (`workspace.rs:63-76`,
  `1175`). A minimal change would add an optional explicit override — e.g. a
  `--space-key <key>` (or `--space-label <name>`, hashed to a synthetic key) flag on
  `herdr workspace create` / `herdr worktree create`, which sets `cached_git_space.key`
  directly instead of deriving it from `cwd`, while still deriving `repo_root`/
  `checkout_key` normally for functionality that needs real paths.
- Rough size: touches `WorkspaceCreateParams`/`WorktreeCreateParams` (CLI arg parsing in
  `src/cli/workspace.rs`, `src/cli/worktree.rs`), the constructor path in
  `src/workspace.rs` (`Workspace::new`, `discover_workspace_git_identity`), and probably
  the API request/response schema in `src/api/*` if switchboard drives herdr over the
  API rather than CLI. That's a handful of files, roughly one new optional parameter
  threaded through 3-4 call sites plus a struct field default — **small, not a
  refactor**, but it is still a herdr source change, and the task explicitly says not to
  make one — sizing only, per the task.
- I did not check whether switchboard talks to herdr via CLI subprocess or the HTTP API
  in the hot path (both exist — `src/api/server.rs` etc.) — that would decide exactly
  which files carry the new parameter; either way the size class doesn't change.

## 3. What switchboard would then have to do (sketch only)

Whichever route: switchboard needs to decide, at `sb start` (top creation) and at
worktree/repo creation for a task, **when** to create vs. attach, and **what name** to
use — a herdr space has no name of its own to query, so "does a space already exist" has
to be answered by switchboard's own bookkeeping (its `workspaces` table already tracks
per-name `checkout`/branch state, `broker.py:1071-1100`), not by asking herdr.

- Route 1 (clone-per-task-repo): switchboard would, at the point it currently does
  `worktree create --branch <name>` (`broker.py:2244` area), instead check "have I
  already cloned this repo for this task-repo identity" (its own record, not herdr's) —
  if not, `git clone`, if so, reuse the existing clone dir, then `herdr workspace
  create --cwd <clone-dir>`. The top orchestrator would be created with `cwd` pointing
  outside any repo (or a dedicated neutral non-git directory) so it never picks up a
  `cached_git_space` and stays visually separate from every task-repo's space, per the
  sidebar's "flat, ungrouped" behavior for non-git workspaces confirmed above.
- Route 2 (herdr override flag, if built): switchboard would compute a stable key per
  task-repo identity itself (e.g. hash of the task's canonical repo path or its own
  workspace name) and pass `--space-key <that>` on every `worktree create` call for that
  task's worktrees, and skip it (or use a distinct constant) for the top. "Does one
  exist already" is still switchboard's own bookkeeping question — herdr doesn't persist
  space records to query against — so this route doesn't remove that need either.

## 4. Comparison and recommendation

| | Route 1: per-task clone | Route 2: herdr override flag |
|---|---|---|
| herdr changes | none | small (sized above) |
| Gets top-above-repos | yes, via non-git cwd (already possible today, no change needed) | yes, same mechanism |
| Gets task-repo isolation | yes, for free, from existing key derivation | yes, but requires switchboard to invent and track its own key per task-repo anyway |
| New cost | disk duplication, ref sync, cleanup semantics (all switchboard-side) | dependency on a herdr change Andrew explicitly wants to avoid needing, plus still needs switchboard-side key bookkeeping |
| Breaks existing worktree-sharing model | yes — task workspaces that intentionally share one repo (today's default) would need a different code path | no — additive, existing worktree flow untouched |

**Recommendation: neither route is clearly "the" answer, and the honest finding is that
Andrew's stated shape does not fully hold against the code without picking one of two
different trade-offs, both real costs, not one:**

- **Top-above-repos costs nothing today** — it is already achievable with zero code
  change, by giving a top orchestrator a `cwd` outside any git repo (confirmed via the
  sidebar's non-git-workspace grouping test). If that alone is what's wanted, it needs no
  herdr change and no per-task-clone restructuring.
- **Create-or-attach *per task-repo* is only "free" (route 1) if switchboard is willing
  to make each task's checkout an independent clone instead of a worktree** — which
  changes disk usage and removes the cheap shared-ref worktree model switchboard
  currently relies on for anything that intentionally shares a repo across task
  workspaces. If per-task-repo work is genuinely meant to be "its own repo" in the first
  place (a distinct GitHub repo, not a branch of this one), route 1 is nearly free and
  is what I'd pick. If "per-task work" is meant to stay branches of the *same* repos
  switchboard already manages (worktrees of switchboard's own repo, or of a target repo
  it's making changes to), route 1 does not apply — those worktrees will always share one
  key/space under herdr's current identity model, and only route 2 (a herdr change)
  reaches Andrew's stated shape.
- **If I'm wrong about which of those two situations is the real one** (single vs.
  per-task distinct repos), the cost is: recommending route 1 when the real need is
  branch-per-task-of-one-repo wastes the disk/sync cost above for nothing, since the
  worktrees still land together regardless; recommending route 2 when clones would have
  worked for free means asking for an unnecessary herdr change. I did not find anything
  in `DESIGN-TRUTH.md` or the task file settling which of those two is meant — worth
  confirming with Andrew before building either.

## What I did not check

- Did not check whether switchboard talks to herdr via CLI or its HTTP API in the
  spawn hot path (both exist in herdr's source) — relevant only to exactly which files a
  route-2 change would touch, not to the size class or the conclusion.
- Did not test any of this live against the running fleet — this is a static-code
  reading only, per the read-only/no-mutation rule in the task.
- Did not re-derive whether `git worktree add --reference`/shared-object-store options
  would reduce route 1's disk cost — flagged as a cost, not measured.
