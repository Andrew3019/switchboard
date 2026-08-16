### Current behavior

`herdr workspace close <id>` closed more workspaces than the one it was given. The workspace I closed had its cwd in a repository's primary checkout. Other open workspaces had cwds in `git worktree` worktrees of that same repository. All of them closed at once — their tabs, panes, and the processes running in those panes. Around 20 panes went away.

The command reported success for the single workspace id I passed and said nothing about the others.

### Expected behavior

`workspace close <id>` closes that workspace, or tells me it is about to close more than one.

### Reproduction

1. A repository at `~/Code/myrepo`, with worktrees added under `~/.herdr/worktrees/myrepo/*`.
2. Workspace A open with cwd `~/Code/myrepo` (the primary checkout). Workspaces B–E open with cwds in those worktrees. Panes running in all of them.
3. `herdr workspace close <id of workspace A>`.

Workspaces B–E close as well.

Closing one of B–E instead closes only that one, which is what I expected throughout.

### Effect on my work

The panes were long-running agent processes. Restarting brought the workspaces back from persisted state, but not the processes or the work they were part-way through. Two of them could not be resumed at all.

### Version and environment

- herdr 0.8.0, stable channel
- macOS 26.5.2 (build 25F84), Apple Silicon
- Apple Terminal, `TERM=xterm-256color`

### Log excerpt

```
10:14:48.284774Z  INFO api request received  request_id="cli:workspace:close" method="workspace.close"
10:14:48.284774Z  INFO workspace closed  outcome="ok" workspace_id="w1H6"
10:14:48.297918Z … 10:14:52.829706Z   ~20 × pane exited (Hangup / Terminate / Kill), across workspaces I did not name
10:14:48.3…       WARN herdr::app::actions: PaneDied for unknown pane
```

The server log then goes quiet for about 4 seconds and a new server process starts and restores from `session.json`. I do not know whether that part is related.
