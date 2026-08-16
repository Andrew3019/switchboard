# Upstream bug report (drafted, NOT filed): `herdr workspace close` closes a whole worktree group

**Status: not filed.** This is a draft for Andrew to decide whether, where and how to file.
Nothing was committed to, opened against, or modified in the herdr repo.

**Version this is written against:** herdr `0.8.0`, source at `/Users/andrew/Code/herdr`,
git `69a07fdf0` — the same version as the installed binary (`herdr --version`), so every
line cited is code that was actually running during the incident.

## Summary

`herdr workspace close <id>` is documented and named as a single-workspace operation, and
its API response reports only the one workspace it was asked about. In fact, when the named
workspace is a git repository's **primary** checkout and any other open workspace sits in a
`git worktree` of that same repository, herdr closes **every workspace in that group** in
the same call — every tab, every pane, every agent process in all of them — and tells the
caller nothing about it.

There is one herdr daemon per machine with no isolation between workspaces, so "the group"
is not scoped to the caller's project, session or terminal. On 2026-08-16 a single such call
against a scratch workspace tore down ~20 panes across an unrelated live agent fleet and the
server process itself went away for ~4 seconds and respawned from persisted state.

## Mechanism

1. `handle_workspace_close` (`src/app/api/workspaces.rs:298`) resolves the id, then does:

   ```rust
   self.state.selected = index;            // point the GLOBAL selection at it
   self.state.close_selected_workspace();  // then "close the selected workspace"
   ```

   It performs **no** group check of its own.

2. `close_selected_workspace` (`src/app/actions.rs:1670`) is not "close one workspace". It
   expands to a set of indices first:

   ```rust
   let close_indices = self.workspaces.get(self.selected)
       .and_then(|ws| ws.worktree_space())
       .filter(|space| !space.is_linked_worktree)      // only from a PRIMARY checkout
       .map(|space| /* every workspace whose membership.key == space.key */)
       .filter(|indices| indices.len() >= 2)           // ...if there are 2+ of them
       .unwrap_or_else(|| vec![self.selected]);
   ```

   Then it removes every index in `close_indices`, collecting their terminals and panes.

3. The grouping key is `WorktreeSpaceMembership.key`, built in
   `src/workspace/git/discovery.rs:71-99` as `canonicalize(git_common_dir)` — **the `.git`
   directory a repository's primary checkout shares with every `git worktree add` worktree of
   it.** `is_linked_worktree` is `git_dir != git_common_dir`: false for the primary checkout,
   true for a linked worktree.

So: **closing the workspace whose cwd is the primary checkout closes every open workspace
anywhere on the machine whose cwd is any worktree of that repository.** Closing a linked
worktree's workspace is safe (the `!is_linked_worktree` filter stops the expansion), which is
why the behaviour goes unnoticed for a long time and then fires all at once.

Membership comes from the `worktree_space` cache on each workspace, which is also what the
API publishes as each workspace's `worktree` object (`src/app/creation.rs:507-514`). It is
not populated for every workspace at all times, so the same command is destructive or benign
depending on cache state the caller cannot see.

## The part that makes it a bug rather than a design choice

herdr **already treats this expansion as dangerous everywhere else.** Two helpers exist for
exactly it:

- `workspace_close_would_close_worktree_group` (`src/app/actions.rs:1984`)
- `confirm_implicit_worktree_group_close` (`src/app/actions.rs:2001`) — sets
  `Mode::ConfirmClose` and makes the caller confirm.

They are used on the interactive and implicit paths:

- the TUI close-workspace action opens a confirmation modal when `confirm_close` is set
  (`src/app/input/navigate.rs:224-232`, and the second handler at `:1618-1628`;
  `confirm_close` defaults to **true**, `src/config/model.rs:1051`);
- closing the *last pane* over the API refuses outright rather than doing it silently —
  `close_pane` returns `confirmation_required`, `"closing this pane would close a worktree
  group"` (`src/app/api/panes.rs:1532-1540`).

The one path with no check at all is the explicit API/CLI verb `workspace close`, which is
the only path a script or an agent ever uses. The guard exists; the scripted entry point
skips it.

Reporting is missing too. `handle_workspace_close` emits one `WorkspaceClosed` event naming
the one requested `workspace_id` and returns bare `Ok{}` (`workspaces.rs:322-330`), while
`close_selected_workspace` logs a `workspace_closed` line per index it actually closed. A
caller reading only the API response cannot tell whether it closed one workspace or nine.

## Reproducing it (in principle)

Not run here — the only machine with a herdr daemon is the one running the live fleet, and
this repo's rules forbid issuing the command. From the code the reproduction is:

1. `git clone <repo> /tmp/r` and `git -C /tmp/r worktree add /tmp/r-wt`.
2. Open a herdr workspace with cwd `/tmp/r` (the primary checkout) and another with cwd
   `/tmp/r-wt`, with a pane running in each.
3. `herdr workspace list` — both should show a `worktree` object with the same `repo_key`,
   one with `is_linked_worktree: false` (the primary) and one `true`. This is the
   precondition; if either `worktree` is null the cache has not populated and the bug will
   not fire.
4. `herdr workspace close <id of the /tmp/r workspace>`.

Expected: the `/tmp/r` workspace closes. Actual (per the code): both close, both panes die,
and the response says `ok` and names only the id you passed.

Everything except step 4's outcome was confirmed against the **live** daemon read-only on
2026-08-16: five open workspaces shared one `repo_key` (`…/switchboard/.git`), exactly one
of them non-linked. The precondition is not exotic — it is what any "primary checkout plus
per-task worktrees" workflow looks like all day.

## Why it is severe

- **Blast radius is unbounded by anything the caller controls.** One machine-global daemon,
  one socket, no per-project or per-session scope. A workspace created for a throwaway
  experiment is in the same process and the same grouping as production work.
- **It is silent.** No warning before, nothing in the response after. The caller — a script,
  a CI step, an agent — has no way to learn what it did.
- **It is unrecoverable in the way that matters.** The panes are agent processes; killing
  them loses whatever they were mid-way through. herdr's own persisted-state restore brings
  back the workspaces, not the work.
- **The safe-looking case teaches the wrong lesson.** Run it on a linked worktree a hundred
  times and it does exactly what it says; run it once on a primary checkout and it takes the
  fleet.
- Observed once already: ~20 panes across unrelated workspaces destroyed, and the server
  process itself gone for ~4.1s before respawning — with no panic, signal or crash report
  anywhere. *(Why the server process exited is not explained by this bug and remains
  unproven; the group close fully explains which panes died and why they died together.)*

## Suggested fixes, in preference order

1. **Do not group-expand on the API path at all.** `handle_workspace_close` should close the
   workspace it was given. The expansion reads as a TUI convenience — closing the tab group
   you are looking at — and has no business firing for a scripted single-id call from a
   caller that never selected anything.
2. **Failing that, refuse and make the caller opt in**, the way `close_pane` already does:
   return `confirmation_required` naming the other workspaces, and require an explicit
   `--close-group` / `close_group: true` to proceed.
3. **Whatever it does, say what it did.** The response (and the `WorkspaceClosed` event)
   should list every workspace actually closed, not just the requested one. This alone would
   have turned the outage into an immediately legible mistake instead of a morning of log
   archaeology.
4. **Document the grouping** wherever `workspace close` is documented, including that
   membership depends on a cache whose state the caller cannot observe.

## Switchboard-side notes (context for whoever files this)

Switchboard never calls this verb on the live path: `switchboard/herdr.py` speaks only
`workspace create` / `workspace rename` and closes panes one at a time. The single caller in
the repo is the acceptance harness's throwaway-clone teardown, and it now refuses to close
any workspace whose reported paths are not under the clone it created
(`acceptance/accept.py`, `workspace_is_ours`). The trigger in the real incident was an agent
running the raw command by hand because its task told it to; the rule against that now lives
in `.switchboard-shared/presets/house-rules.md`. Full mechanism and evidence:
`notes/herdr-close-mechanism.md`, `notes/herdr-outage-cause.md`.
