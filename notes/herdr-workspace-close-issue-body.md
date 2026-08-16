Hit this on 0.8.0; line references below are against master at 51b7064, where the behaviour is unchanged.

This is the same class of bug as #369, on the one path that fix did not cover. #369 closed the gap for closing a workspace via its last pane or tab; the explicit `workspace close` API verb still cascades to the whole worktree group with no confirmation.

## What happens

`herdr workspace close <id>` closes more than the workspace it is given. If the target workspace's cwd is a git repository's primary checkout, and other open workspaces have cwds in linked worktrees of that same repository, all of them are closed in the same call — their tabs, panes, and the processes running in those panes. The API response names only the workspace id that was passed and returns `Ok{}`, so the caller has no way to see that anything else closed.

Closing a linked worktree's workspace closes only that workspace, which is correct. The expansion only fires from the primary checkout.

## Where it comes from

`handle_workspace_close` (`src/app/api/workspaces.rs:298`) points the global selection at the requested workspace and delegates:

```rust
self.state.selected = index;
self.state.close_selected_workspace();
```

`close_selected_workspace` (`src/app/actions.rs:1673`) is not single-workspace. It builds a set of indices first:

```rust
let close_indices = self.workspaces
    .get(self.selected)
    .and_then(|ws| ws.worktree_space())
    .filter(|space| !space.is_linked_worktree)
    .map(|space| /* every workspace whose membership.key == space.key */)
    .filter(|indices| indices.len() >= 2)
    .unwrap_or_else(|| vec![self.selected]);
```

and then closes each one. The grouping key is the canonicalized `git_common_dir` (`src/workspace/git/discovery.rs:72`) — the `.git` directory that a primary checkout shares with every `git worktree add` worktree of it. `is_linked_worktree` is false for the primary checkout (`discovery.rs:46`), which is what lets the expansion through.

Afterwards, `handle_workspace_close` emits one `WorkspaceClosed` event for the single requested id, while `close_selected_workspace` logs a `workspace_closed` line for each index it actually closed. The log and the API response disagree.

## Why this looks like an oversight

The guard for exactly this case already exists and is used everywhere else:

- `workspace_close_would_close_worktree_group` and `confirm_implicit_worktree_group_close` (`src/app/actions.rs:1987`, `:2004`), reached from the TUI close action when `confirm_close` is set, which is the default (`src/config/model.rs:1112`).
- `close_pane` refuses rather than doing it silently — it returns `confirmation_required` with "closing this pane would close a worktree group" (`src/app/api/panes.rs:1568`). That is the #369 fix.

`handle_workspace_close` calls neither helper, and it is the path scripts and automation use.

There is also a visibility problem underneath it. Membership comes from each workspace's `worktree_space` cache, which is not populated for every workspace at all times, so the same command is destructive or benign depending on cache state the caller cannot observe.

## Impact

A primary checkout plus per-task worktrees is a common layout, and the daemon is machine-wide, so the group can span workspaces belonging to unrelated work. In our case one `herdr workspace close` against a scratch workspace closed roughly 20 panes across other workspaces. Restarting restores the workspaces from persisted state, but the processes that were running in those panes are gone along with whatever they were part-way through.

## Reproducing

I have not run this — the only machine here with a herdr daemon is one I did not want to take down a second time, so what follows is derived from reading the source. Everything except the final step was confirmed read-only against the live daemon: five open workspaces shared one `repo_key`, exactly one of them non-linked.

1. `git clone <repo> /tmp/r` and `git -C /tmp/r worktree add /tmp/r-wt`
2. Open a workspace with cwd `/tmp/r` and another with cwd `/tmp/r-wt`, each with a running pane
3. `herdr workspace list` — both should report a `worktree` object with the same `repo_key`, one with `is_linked_worktree: false`. If either is null the cache has not populated and the expansion will not fire.
4. `herdr workspace close <id of the /tmp/r workspace>`

Expected: the `/tmp/r` workspace closes. Per the code: both close, and the response names only the id that was passed.

## Suggested fix

Have `handle_workspace_close` close the workspace it was given, without the group expansion. The expansion makes sense as a TUI convenience — closing the tab group you are looking at — but the API call passes an explicit id from a caller that never selected anything, and routing it through `selected` plus `close_selected_workspace` looks like how it inherited the behaviour.

If the grouping is wanted on the API too, the alternative is to mirror `close_pane`: return `confirmation_required` listing the other workspaces, and require an explicit `close_group: true` to proceed. Either way it would help if the response and the `WorkspaceClosed` event reported every workspace that was actually closed.
