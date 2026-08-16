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

# Item 5: the clicked row, lit for ten seconds

Same method, one clone further on: a `git clone` of this branch in a scratch directory, its
own `python -m switchboard.board` in a tmux pane on a socket of its own at 96×22, reading a
snapshot published into that clone's `panel/` directory by a process holding that clone's
collector lock. Clicks are real SGR mouse bytes fed to the pane's stdin, which is exactly
what herdr forwards from a mouse. Torn down after: tmux server killed, publisher killed,
nothing spawned in herdr and nothing in the live store.

The wash is a colour, so a text capture cannot show it. What the captures were measured for
instead is which line carries the background and how wide it runs, read out of
`capture-pane -e`'s escape codes — which is the half that can be wrong while looking right.

## The frame, and the row that was clicked

`sbhl8529-w1` — screen line 5 — was clicked at t=0.

```
╭─ switchboard ────────────────────────────────────────────────────────────────────────────────╮
│  switchboard · 5 alive · 1 stalled · 1 blocked · 2 unread · 5 agents                         │
│  AGENTS                                                                                      │
│  ● sbhl8529-lead    working     5s                                                           │
│  ●    ╭sbhl8529-w1  working     5s                                                           │
│  ◐    ╰sbhl8529-w2  blocked     5s  BLOCKED — which colour?                                  │
│  ◌    ·sbhl8529-w3  idle       13m  STALLED — idle 13m                                       │
│  ○    ·sbhl8529-w4  done        5s  mail: 2 unread                                           │
```

| capture | what carries the wash |
|---|---|
| before the click | nothing |
| t + 1.0s | line 5, 92 columns, screen columns 3–94 |
| t + 9.5s | line 5, 92 columns, screen columns 3–94 |
| t + 10.8s | nothing |
| t + 12.3s | nothing |

92 columns is `width - 4` — two of border and two of padding, the same span the header and
`NEEDS YOU` bars fill. So the highlight ends where the bars end and the panel stays
rectangular; a wash on the printed characters alone would have stopped at column 40, in the
middle of the row, and stopped somewhere different on every other row. At 40 columns the
same click lights 36, which is that pane's `width - 4`.

Nothing expires it. The board redraws twice a second whatever the human does, and the frame
that stops drawing the mark is an ordinary refresh — which is why "gone by t+10.8s" is the
measurement rather than "gone at exactly t+10.0s".

The dim is lifted for the ten seconds, and the live codes show it: unlit, the age is
`\033[0;2m     5s`; lit, it is `\033[48;5;239m     5s`. Everything that carries meaning
still carries it — the glyph's green, the cyan bracket, the yellow tail.

## A second click while the first is still lit

One mark, and it moves. Clicking line 4 lit line 4; clicking line 7 two seconds later left
line 7 lit and line 4 dark in the same frame. Two lit rows would say two agents had just
been clicked, and the older one is a row the human has already looked away from.

`sbhl8529-w3` is drawn twice — its own row and the `NEEDS YOU` line naming it — and only
the row in the tree lights. The click was on the tree.

## A lit row that leaves the board

`sbhl8529-w3` was clicked and then dropped from the published fleet two seconds later. The
next frame drew four agents, no wash anywhere, and the board carried on: the mark is a name
and the renderer simply finds nothing to put it on. Nothing to clean up, because there is
nothing holding a row.

## What else was checked live

- At 40×14 the frame is intact and the mark still fills the row; at 20 columns the panel
  declines and the plain renderer takes the frame, where a click is still a focus and draws
  no mark at all — accepted and not drawn, see `board.layout`'s docstring.
- Every frame in the run came back 22 lines in a 22-line pane, so nothing the wash added
  wrapped a line — which is the failure that would move every click below it.
- The clicked row is marked whether or not the focus lands: herdr had no such agent in this
  isolated run and said so on the footer, and the row lit anyway. The mark answers "this is
  the row you touched"; the footer answers what came of it.
