# What the board looked like, before and after items 1, 2 and 4

Captures of the real `sb board`, not a mockup and not a unit test: a `git clone` of this
repo in a scratch directory, its own `bin/sb board` driven in a pty at 96×26, reading a
snapshot published into that clone's own `panel/` directory. The clone and the process
holding its collector lock are torn down; nothing here touched the live store.

The fleet is synthetic but real-shaped, and shaped for the bug: a top alone in its own
workspace, two delegated workspaces one of which holds a nested sealed archive, a
workspace of exactly one visible agent, and a blocked agent so NEEDS YOU is in frame.
Nothing about a layout depends on where the rows came from; what it depends on is depth,
workspace and archived-ness, and those are what this fixture varies.

## Before

```
╭─ switchboard ────────────────────────────────────────────────────────────────────────────────╮
│  switchboard · 7 alive · 1 blocked · 3 unread · 10 agents                                    │
│  ● dispatcher-1       working     5s                                                         │
│  ● ╭   board-layout   working    12s                                                         │
│  ● │       worker-74  working     3s                                                         │
│  ◐ ╰       qa-9       blocked     7m  BLOCKED — which bracket column? · mail: 1 unread       │
│ + 2 archived                                                                                 │
│  ● ╭   model-pins     idle        3m                                                         │
│  ● ╰       worker-51  working     8s  mail: 2 unread                                         │
│ + 1 archived                                                                                 │
│  ● ·   docs-pass      working    40s                                                         │
```

Three things to see in it:

- the bracket sits at the LEFT end of the indent block, four columns clear of the names it
  is meant to be grouping, so it reads as a column of its own rather than as a brace;
- `+ 2 archived` has no indentation at all — `collapsed_label` indented it two spaces per
  level and `board._clip`, which flattens runs of whitespace, then ate even those — so the
  row that stands for board-layout's archived children sits at the left margin, level with
  nothing;
- and it carries no bracket, so the run it is the tail of closes one row early, on `qa-9`.

## After

```
╭─ switchboard ────────────────────────────────────────────────────────────────────────────────╮
│  switchboard · 7 alive · 1 blocked · 3 unread · 10 agents                                    │
│  AGENTS                                                                                      │
│  ● dispatcher-1       working     5s                                                         │
│  ●    ╭board-layout   working    12s                                                         │
│  ●    │    worker-74  working     3s                                                         │
│  ◐    │    qa-9       blocked     7m  BLOCKED — which bracket column? · mail: 1 unread       │
│       ╰    + 2 archived                                                                      │
│  ●    ╭model-pins     idle        3m                                                         │
│  ●    │    worker-51  working     8s  mail: 2 unread                                         │
│       ╰    + 1 archived                                                                      │
│  ●    ·docs-pass      working    40s                                                         │
```

`AGENTS` is a filled grey bar in the terminal, the same `_bar` the blue title and the
yellow NEEDS YOU are drawn with, and quieter than either on purpose.

## The end-of-session state, which is the ordinary one

Every agent archived collapses to a single row, and it now indents and reads as the footer
of the tree rather than as a stray line:

```
╭─ switchboard ────────────────────────────────────────────────────────────────╮
│  switchboard · 0 alive · 1 blocked · 3 unread · 10 agents                    │
│  AGENTS                                                                      │
│    + 10 archived · 2 need you                                                │
```

## What else was checked live

- Every frame from height 6 to 39, at six widths and three scroll positions, came back
  with the height it was built with — `richboard.layout` returns `None` rather than a
  frame it cannot account for, and a wrong line count is how a click focuses the wrong
  agent.
- At the very shortest pane the section header gives its line back rather than stand over
  no agents at all: at height 6 there is one agent row and no `AGENTS` bar, at 7 there are
  both.
- `a` (show every archived row) still draws the whole tree with the brackets closing on
  the real last row of each workspace.
- The plain fallback, with `rich` made unimportable, indents its collapsed rows by
  `board.INDENT` like every other row and says `AGENTS` in place of the blank line it
  already spent — so its line count, and `display.board_chrome`, are unchanged.
