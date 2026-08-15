# Can herdr group agents under something other than the repo?

**Answer: No.** A worktree's parent workspace ("space") is always resolved by git repo
identity (`repo_key`), never by an arbitrary chosen/labeled workspace. There is no
create-time or after-the-fact way to place a worktree into a workspace that isn't tied
to its own repo.

## Where I looked

- The real herdr binary: `/Users/andrew/.local/bin/herdr` (Mach-O arm64, `herdr 0.8.0`).
  CLI help (`herdr --help`, `herdr workspace --help`, `herdr worktree --help`) is the
  live interface.
- The full socket API schema: `herdr api schema --json` (protocol 19), specifically the
  `WorkspaceCreateParams` and `WorktreeCreateParams` request schemas.
- herdr's own source, checked out at `/Users/andrew/Code/herdr` (git HEAD
  `69a07fdf061a35276295189d52d591893c429806`, 2026-08-06). Implementation read, not just
  CLI/schema surface:
  - `src/app/api/worktrees.rs` — `resolve_worktree_source`, `worktree_source_from_workspace`,
    `ensure_source_parent_membership`, `find_parent_workspace_for_space`,
    `find_parent_workspace_by_key`, and the `worktree_membership()` constructor
    (lines ~174–435 and ~705–717).

This supersedes `notes/recruiting-space-followup.md`, which was untrusted per the task
and is confirmed correct by the source read below.

## The evidence that decides it

`herdr worktree create` does accept `--workspace <ID>` (`WorktreeCreateParams.workspace_id`
in the schema), which at first glance looks like "attach this worktree to a chosen
workspace." Reading the implementation shows it is not that:

- `workspace_id` on worktree-create is used only to pick the **source** checkout to base
  the new worktree off. `worktree_source_from_workspace()` (worktrees.rs:282) requires
  the referenced workspace to *already* be a git-repo-backed space (`ws.worktree_space()`
  or `ws.git_space()`); if it isn't, it fails with `not_git_worktree` /
  "Herdr worktree actions require a workspace inside a Git work tree". A plain
  label-only workspace with no git identity cannot be passed here.
- The **destination** parent workspace for the new worktree is never taken from that
  parameter. It's computed independently by `ensure_source_parent_membership()` →
  `find_parent_workspace_by_key(&source.repo_key)` (worktrees.rs:386, 427-435), which
  scans existing workspaces for one whose git space `key` (the repo identity) matches.
  If none is found, it creates a brand-new parent workspace itself
  (`create_workspace_with_options(source.source_checkout_path, ...)`, worktrees.rs:390-395)
  — again seeded from the checkout path, not from any label the caller supplied.
- The membership record written for the new worktree (`worktree_membership()`,
  worktrees.rs:705-717) always sets `key: source.repo_key` and
  `label: source.repo_name` — both derived from the repo, not overridable.

So the `--workspace`/`workspace_id` argument is not a "put this agent under my chosen
orchestrator space" knob; it's "start this new worktree from the checkout that's open in
this existing repo-workspace." Grouping is still 1:1 with repo identity, full stop.

`herdr workspace create --label <TEXT>` does let you make a workspace with an arbitrary
name and no `cwd`/repo at all — so free-standing, non-repo-tied workspaces can exist.
But nothing lets you *move a worktree into one* afterward either: the `workspace`
subcommand set is `list, create, get, focus, rename, report-metadata, close` — no
"move"/"reparent". The only move-like schema I found, `WorkspaceMoveParams`
(`workspace_id` + `insert_index`), is for reordering a workspace's position in the
sidebar list, not changing what it's parented under or merging worktrees into it.

## What would have to change for this to become possible

herdr itself would need a new capability — it doesn't exist today, not even
unimplemented-behind-a-flag. Specifically it would need either:
- `WorktreeCreateParams.workspace_id` to be honored as a true destination parent
  (skip `find_parent_workspace_by_key` when a target is explicitly given), or
- A new "reparent worktree into workspace" API distinct from the existing
  create/open/remove trio.

Nothing in switchboard would need to change until herdr grows that; switchboard doesn't
currently pass anything that herdr would use for this even if it existed.

## Conditionality / caveats

- Checked against herdr 0.8.0 (installed binary) and the matching-looking source tree
  at `/Users/andrew/Code/herdr` HEAD `69a07fd` (2026-08-06). I did not verify the
  installed binary was built from exactly that commit — I'm relying on version number
  and directory naming, not a build-hash match. If a newer/older herdr build behaves
  differently, this answer could be stale.
- I did not exercise `herdr workspace create --label` or `herdr worktree create
  --workspace` live (task is read-only) — this is a source-and-schema read, not an
  observed runtime test. The control flow in worktrees.rs is unambiguous enough that I'm
  confident in the "no" without running it, but flagging that I didn't execute it.
- The grouping-is-repo-identity behavior is consistent with, and independently confirms,
  DESIGN-TRUTH.md's own model ("A worktree belongs to a space, not to an agent" /
  "only the top ever creates a space") — switchboard was already built assuming this
  constraint, it isn't a new discovery that contradicts anything trusted.
