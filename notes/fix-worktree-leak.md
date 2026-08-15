# #40 — cleanup now closes the space too

Branch `fix-worktree-leak`, commit `2d0def7`. Not pushed, no PR (not authorised).

## The change

Only the trigger was missing. `cleanup()` now calls `workspace_close` for each workspace
its candidate agents worked in, once nothing is left in it. Every gate, inventory and
deletion below it is `workspace_close`'s, unchanged — no second opinion about when a
directory is safe to delete.

- new: `Broker._close_empty_spaces` / `_space_ready` / `_my_spaces` (`switchboard/broker.py`)
- `CleanupResult` gains `.spaces` and `.spaces_refused`
- `sb cleanup` reports closed spaces in text, both lists in `--json`

Three skips this level keeps on its own: a bare space, one already retired, and **the
space the caller is standing in**. The gates below deliberately excuse the caller (its row,
its process tree) so an agent *can* close its own workspace when it asks by name; a sweep
inheriting that excusal would delete the directory it is running in.

## The policy decision the issue left open

**A clean but unmerged branch does not hold the space.** `DESIGN-TRUTH.md:437` accepts that
aggressive cleanup destroys `sb restore`, and `_finish` uses `git branch -d`, so the branch
and every commit on it stay behind. `confirm=False` throughout: work git can see, and
ignored content nobody has looked at, both still hold the space for
`sb workspace close <name> --yes`.

## Proof

Live, in an isolated clone (torn down afterwards), same scenario both ways:

- on `main`: nothing deleted, no `spaces` key in the JSON at all
- on the branch: the clean space's worktree gone from disk and from git's registry,
  `retired_at` set (`sb workspace list` reads `retired` — a state no workspace in this
  repo has ever reached), the `space-clean` branch surviving unmerged, and the dirty space
  kept with the gate's own reason plus a `cleanup_space_held` event

3 new tests in `tests/test_workspace_close.py`; full suite 1253 passed.

## Unproven

- No real herdr agent ran through it — the live proof used rows with no panes, so
  `workspace_close`'s pane-closing step is covered only by the existing unit tests.
- A human sweep will now close every one of the ~125 stale worktrees that is clean and
  finished, in one command. That scale is untested.
