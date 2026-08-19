# QA-16: re-proof of dispatcher cascade-close against HEAD 01b423e

Re-verifies p-11 step s-56 (brief `.switchboard/briefs/qa-reverify/brief.md`) against the
code as it stands after the 6 review-driven fixes on top of qa-15's original proof
(`6f5c14d`), which predates all of them. All four items from the brief proved live.

## Method

Isolated clone: `git clone /Users/andrew/Code/switchboard` into a scratch dir outside any
worktree, checked out `fix-orphaned-dispatcher-children` at `01b423e`. `sb doctor`
confirmed the clone's own store (`<clone>/.git/agentflow/state.db`), never the live one.
Every store-touching command — `sb`, python fixture scripts — was run with the clone as
`cwd`, verified with `pwd` before each; the fixture scripts themselves assert
`Path.cwd() == CLONE` and that the connected store path is under the clone before writing
anything, and refuse to run otherwise.

Fixtures were built with real herdr (`Broker.start`/`delegate`/`_fork_for` called
directly — same convention qa-15 used), producing real git worktrees, real herdr
workspaces and panes, and real sqlite store rows — the same calls `sb start`/`sb
delegate` make. Only `Herdr.start_agent` (spawning an actual Claude process) and
`Herdr.deliver` (confirming a task landed in one) were stubbed; `sb workspace close`
itself, the command under test, ran for real through the CLI (`./bin/sb workspace
close ...`) every time.

**Incidental finding, not part of this fix:** `_fork_for`/`delegate` opens a REAL herdr
pane running a real `python -m switchboard.board` + shell in every forked worktree, even
with `start_agent` stubbed. That process (a) imports the `switchboard` package from
inside the new worktree, leaving a `__pycache__` there before any agent does anything,
and (b) has to be killed before the worktree can close (`_gate`'s process check correctly
refuses to delete out from under a live process). Neither is a bug in the change under
test; it just meant a "clean, finished child" fixture needed those processes killed and
the resulting `__pycache__` scrubbed first, same as a real agent's pane closing would
leave its worktree.

## What was proved

**Item 1 — clean finished child's forked space is deleted with the dispatcher.**
`qa16-a2` (bare, done) → `qa16-a2-clean` (done, real fork, scrubbed clean — `git status
--porcelain --ignored` empty).
```
$ ./bin/sb workspace close qa16-a2
closed 2 pane(s): qa16-a2, qa16-a2-clean
retired qa16-a2 — no checkout of its own, and 1 forked space(s) below it DELETED
  deleted space(s): qa16-a2-clean
```
Confirmed: directory gone, dropped from `git worktree list`, `workspaces.retired_at` set
for both rows.

**Item 2 — dirty child's space is kept and reported, never destroyed.**
`qa16-a` (bare, done) → `qa16-a-dirty` (done, real fork, `qa16-scratch.tmp` dropped in —
matches the repo's `*.tmp` gitignore pattern).
```
$ ./bin/sb workspace close qa16-a
...
  kept space qa16-a-dirty: .../qa16-a-dirty holds 3 ignored file(s) that git will not
  miss and the removal WILL delete: defaults/plugins/plans/__pycache__/,
  qa16-scratch.tmp, switchboard/__pycache__/. Nothing has been touched.
```
Confirmed: directory intact, `qa16-scratch.tmp` still there, workspace row not retired,
dispatcher itself still retired (a kept space does not block the close that owns it).

**Item 3 (R2) — a done parent's space is HELD while a live grandchild works.**
`qa16-b` (bare, done) → `qa16-b-lead` (done, real fork) → `qa16-b-worker` (real fork,
`parent=qa16-b-lead`, `state=working`).
```
$ ./bin/sb workspace close qa16-b
closed 1 pane(s): qa16-b
retired qa16-b — no checkout of its own, so nothing was deleted
  kept space qa16-b-lead: qa16-b-worker is still working underneath qa16-b-lead, whose
  space this is
  kept space qa16-b-worker: cannot close 'qa16-b-worker': ... still recorded as working ...
```
Confirmed: both `qa16-b-lead` and `qa16-b-worker` directories intact, neither
`workspaces.retired_at` set. This is the R2 fix's exact claim, proved live rather than
only in the unit harness.

**Item 4 (R1) — a second live top's forked child, joined by a descendant of the first, is
never touched by closing the first.**
`qa16-c1` (bare, done) → `qa16-c1-lead` (done, real fork). Separately, `qa16-c2` (bare,
done) → `qa16-c2-child` (done, real fork). `qa16-c1-joiner`, a descendant of `qa16-c1`
(`parent=qa16-c1-lead`), **joined** `qa16-c2-child`'s existing space (`workspace=
qa16-c2-child`, what `sb delegate --workspace qa16-c2-child` does) rather than forking
its own.
```
$ ./bin/sb workspace close qa16-c1
closed 1 pane(s): qa16-c1
retired qa16-c1 — no checkout of its own, so nothing was deleted
  kept space qa16-c1-lead: Python (...), zsh (...) are still running in .../qa16-c1-lead
  — close them first ...
```
`qa16-c2-child` is not mentioned at all — not deleted, not reported, not even looked at.
Confirmed on disk: `qa16-c2-child`'s directory intact, its workspace row `retired_at`
still `NULL`, throughout. (`qa16-c1-lead`'s own live board process was incidental noise
from fixture-building, not a fixture design choice — killed it and closed
`qa16-c1-lead` directly afterward to also confirm the delete side works once idle:
`retired qa16-c1-lead: worktree removed`, directory gone. `qa16-c2-child` remained
untouched through that too.)

## Not (re-)proven live

- **Crash-mid-cascade retryability (R2's other half, `5e060f3`)** — not exercised live.
  Not one of the brief's four numbered items; covered by the review's own repro (F1 in
  `reviewer-29-cascade-recursion.md`) against the unit harness and by
  `test_a_crash_mid_cascade_leaves_the_whole_close_retryable`, not independently proved
  here against real herdr.
- Reporting-surface fixes (R3, `bae8691`/`65d9c00`) were exercised incidentally — every
  transcript above shows the corrected headline/kept-space wording — but not probed
  adversarially for the specific edge cases reviewer-30 found (e.g. standing inside the
  space being closed).

## Teardown — confirmed complete

- All twelve `qa16-*` workspace rows in the clone's own store: `retired`.
- `git worktree list` in the clone: only the clone's own primary checkout.
- Two herdr panes that outlived their `sb workspace close` (a board-split second pane in
  each case — pre-existing herdr behavior, not part of this fix) closed directly via
  `herdr pane close`; `herdr workspace list` shows no `qa16-*` label left.
- Scratch clone directory and fixture scripts: deleted (`rm -rf`).
- Live production store: `./bin/sb workspace list` from my own checkout shows no `qa16-*`
  rows — confirmed no leak, unlike the prior QA's incident.
- My own checkout (`fix-orphaned-dispatcher-children`): `git status --porcelain` clean
  throughout, never touched.
