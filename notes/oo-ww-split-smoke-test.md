# `oo`/`ww` split — the manual smoke test

Everything here needs a real Cursor and a real keystroke, which is why none of it is
in `tests/test_board.py`. Branch: `oo-ww-split`.

Start a board (`sb board`, or the pane one beside any agent) and highlight an agent
that has written files.

1. **`oo` with the worktree window already open.** Open the agent's worktree in
   Cursor first, then press `oo`. The files should land as tabs in THAT window —
   containment beats recency, so it should hold even if some other Cursor window was
   the last one you touched.
2. **`oo` with no Cursor running at all.** Expect a ROOTLESS window: the files as
   tabs, no file tree, no SCM panel. Working as designed, and the reason `ww` exists —
   worth seeing once so it does not read as broken later.
3. **`ww` on the same agent.** A window on the worktree folder. Press `ww` again: it
   should FOCUS that window, not open a second one.
4. **`ww` then `oo`, one after the other.** With Cursor cold there is a residual gap —
   `cursor <cwd>` returns when the CLI hands off, not when the window is up — so the
   files can still arrive before the window exists. Wait to see the window, then `oo`.
   Worth checking how bad the gap actually is.
5. **`oo` on an agent that has written nothing.** Status line says "no files found in
   recent messages" and NO editor window appears. If a window appears, the guard is
   not doing its job.
6. **`ww` on an agent with no worktree** ("no worktree to open"), and on one whose
   worktree has been deleted ("worktree no longer exists").
7. **The hint, above the footer.** Files → two yellow lines, the second naming both
   keys. No files but a worktree → one line for `ww`. Neither → nothing. Check both
   renderers if you can (uninstall-free: a pane narrow enough falls back to plain).
8. **Both keys at once.** `wwoo` typed as one burst: both fire, one runs and the other
   is refused with a line naming what each was opening, and `oo`'s line is the one left
   on screen.

Known and not fixable from here: the macOS dock-icon bounce (vscode#139634), and `ww`
opening a second window when the worktree is a folder of a MULTI-ROOT workspace or the
`cwd` reaches it through a symlink.
