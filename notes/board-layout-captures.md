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

# The stats section: why it said "not measured" live, and the STATS header

Same method again, one clone further on: a `git clone` of this repo at `stats-fix` in a
scratch directory, a real `python -m switchboard.collector` holding THAT clone's collector
lock, and the clone's own `bin/sb board` in tmux panes on sockets of its own. The store is
the clone's, seeded with three agent rows, one workspace whose checkout is the clone, seven
`turn_end` events and four messages, so every group of numbers has something real to count.
Nothing here touched the live store, and no agent was spawned: `sb start` refuses a Claude
Code session (`cli._agent_caller`), which is the guard that stops a verification clone
minting top agents.

## Why the live board said `not measured`, which was never a bug in this chain

`stats.collect()` against the live store returns all thirteen fields populated (measured
here: 9 turns, 41 lines, 2 commits, 3 spawns, 5 messages, 0.3 of 8 cores, 33 procs), and
`board.stats_rows` turns them into pieces. The break was one link earlier and outside this
code entirely: the process holding the live fleet's collector lock — pid 40401, started
2026-08-11 01:04 with `PYTHONPATH=.../worktrees/switchboard/accept-concurrent` — predates
`switchboard/stats.py`, so the envelope it publishes has no `stats` key at all:

```
$ python -c "import json; print(list(json.load(open('.../panel/snapshot.json')).keys()))"
['format', 'snapshot', 'collector']
```

`panel.read` finds nothing at `stats` and hands the renderer `{}`, which is exactly what
`STATS_NONE` is for — so every pane on the machine drew `not measured` correctly, about a
collector that cannot measure. Two things kept it there rather than it being the momentary
state `panel.envelope` describes ("an old pane ignores this, a new one finds `{}` in an old
collector's file"): that collector predates `collector.source_signature` too, so it has no
self-retirement at all, and its checkout has since been deleted, so there is nothing left
on disk for a signature to differ from. It is retired by `kill`, and the next pane's tick
elects a replacement from a current checkout.

## The section, live, at 96 columns

```
╭─ switchboard ────────────────────────────────────────────────────────────────────────────────╮
│  switchboard · 0 alive · 3 gone · 3 agents                                                   │
│  STATS                                                                                       │
│   LAST HOUR  7 turns · 888 lines · 127 code · 6 commits · 3 spawns · 4 messages              │
│   RIGHT NOW  0.1 of 8 cores · 59M rss · 6 procs                                              │
│                                                                                              │
│  AGENTS                                                                                      │
│    + 3 archived                                                                              │
```

Real numbers, published by a real collector and read off the file by a real board. `STATS`
is the same `_bar` as `AGENTS` — `capture-pane -e` shows both opening
`ESC[1m ESC[37m ESC[48;5;237m`, so same weight, same colour, same full-width fill — and the
blank line between the block and `AGENTS` is line 6.

## At 40 columns, and in the plain renderer

```
╭─ switchboard ────────────────────────╮        switchboard  ·  0 alive · 3 agents
│  switchboard · 0 alive · 3 gone · 3… │         STATS
│  STATS                               │         LAST HOUR  7 turns · 888 lines · …
│   LAST HOUR  7 turns · 888 lines     │         RIGHT NOW  0.1 of 8 cores · 152M rss · …
│   RIGHT NOW  0.0 of 8 cores          │
│                                      │         AGENTS
│  AGENTS                              │           + 3 archived
│    + 3 archived                      │
```

Nothing wraps at 40; whole pieces are dropped from the right as before. The plain fallback
(captured with `rich` made unimportable) says the same things in its own vocabulary — a dim
` STATS` label where the panel fills a bar, and the same blank line under the numbers.

## The short pane still gives the lines back, and in the right order

At 96×8 the whole stats block — header, both lines and the blank — goes together and the
tree keeps its rows; `AGENTS` survives one line longer, and goes at 96×7 and below. Half a
section is not a smaller section, so the header and the blank are given back with the
numbers rather than left standing over nothing.

```
96×8                                              96×7
│  switchboard · 0 alive · 3 gone · 3 agents  │   │  switchboard · 0 alive · 3 gone · …  │
│  AGENTS                                     │   │  AGENTS                              │
│    + 3 archived                             │   │    + 3 archived                      │
```

`display.board_chrome` went 6 → 8 for the plain renderer's two new lines; the panel counts
its own head (`richboard.layout`, `head_lines = 2 + len(stats_block)`, now six lines).

# The stat-line tweaks: `+added/-deleted`, `mail`, and CPU/memory as machine shares

Same method again, one clone further on: a `git clone` of this repo at `statline-tweaks`
into a scratch directory, a real `python -m switchboard.collector` holding THAT clone's
collector lock, the clone's own `bin/sb board` in tmux panes on a socket of its own. The
store is the clone's, seeded with three agent rows, one workspace whose checkout is the
clone, nine `turn_end` events and five messages. Two real commits were made IN the clone —
one adding 120 lines of code and 400 lines of prose, one trimming both — so the `+/-` has
something of each to tell apart, and three real CPU-burning processes were started with
their cwd inside the clone, so `cpu`, `rss` and `procs` are measurements of something.

No agent was spawned: `sb start` refuses a Claude Code session (`cli._agent_caller`), which
is the guard that stops a verification clone minting top agents. Real processes in a real
checkout are what the machine group actually measures, and those it had.

## The line, live, at 96 columns

```
╭─ switchboard ────────────────────────────────────────────────────────────────────────────────╮
│  switchboard · 0 alive · 5 unread · 5 undelivered · 3 agents                                 │
│  STATS                                                                                       │
│   LAST HOUR  9 turns · +388/-109 · 11 commits · 3 spawns · 5 mail                            │
│   RIGHT NOW  10% cpu · 53M rss · 1.4G free · 4% mem · 6 procs                                │
│                                                                                              │
│  AGENTS                                                                                      │
│ ╭● verify-lead   idle     1m  mail: UNDELIVERED 5, 1m                                        │
```

## The `+388/-109` is what git says, checked two ways

The board's figure was compared against the same walk done by hand, once through
`stats.is_docs` and once through an `awk` that knows nothing about this code:

```
$ awk 'NF==3 && $3 !~ /\.md$/ && $3 !~ /^notes\// && $3 !~ /^learnings\// && $1 ~ /^[0-9]+$/ \
       {a+=$1; d+=$2} END {print a, d}' \
      <(git log --all --no-merges --numstat --format=%H --since=@$(( $(date +%s) - 3600 )))
388 109
```

Both agree with the published snapshot (`code_added: 388, code_deleted: 109`) and with the
board. The prose commits are the check that matters: 400 lines added and 399 deleted in
`notes/verify-prose.md` appear in NEITHER half, which is the whole point of the change.

## The two shares, against what the machine says

`cpu_percent: 79.1` over `cpu_cores: 8` is 9.9% — drawn `10% cpu`, and it moved between 9%
and 13% across captures as the three burners came and went. The clamp is unit-pinned rather
than provoked live: a fleet that momentarily sums past `100 × cores` was not something worth
manufacturing.

Available memory is `vm_stat`'s free + inactive + speculative pages × page size, and it
tracks the command it reads:

```
$ vm_stat | egrep 'page size|Pages (free|inactive|speculative)'
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     3644.
Pages inactive:                                83424.
Pages speculative:                               435.
$ python -c "from switchboard import stats; print(stats._available_memory())"
1428406272          # (3644 + 83424 + 435) × 16384 = 1433649152, sampled a moment apart
```

Worth a reader knowing: `memory_pressure` on the same machine said "System-wide memory free
percentage: 34%" against this figure's 1.33G of 8G (17%). They are different questions —
that one counts compressed and purgeable memory this one does not — and the conservative
reading is the right one under a number labelled `free`.

The share itself is `rss / (rss + free)`, deliberately not a share of physical RAM: memory
another program is holding is not memory this fleet could have. 53M against 1.4G free is
`4% mem`.

## At 40 columns, and in the plain renderer

```
╭─ switchboard ────────────────────────╮   switchboard  ·  0 alive · 5 unread · …
│  switchboard · 0 alive · 5 unread ·… │    STATS
│  STATS                               │    LAST HOUR  9 turns · +388/-109 · 11 commits · …
│   LAST HOUR  9 turns · +388/-109     │    RIGHT NOW  9% cpu · 64M rss · 1.3G free · 5% mem · …
│   RIGHT NOW  9% cpu · 69M rss        │
│                                      │    AGENTS
│  AGENTS                              │    ● verify-lead   idle     2m  ← mail: UNDELIVERED 5
```

Nothing wraps at 40; whole pieces are dropped from the right, so the narrow pane keeps
`+388/-109` and loses the memory pieces before the CPU one. The plain fallback (captured
with `rich` made unimportable) draws the same pieces in its own chrome, which is what
sharing `board.stats_rows` between the two renderers is for.

## The first tick still says `not measured`

With every one of the fourteen fields None — the state of every board for its first half
second — the section says the honest thing and never `+0/-0` or `0% cpu`:

```
 STATS
 LAST HOUR  not measured
 RIGHT NOW  not measured
```

Rendered through `panel.read` on the clone's own published envelope with the stats blanked,
rather than in a tmux pane: a pane whose collector is stopped elects a new one within two
seconds and fills the line back in, so the blank state cannot be held on screen long enough
to capture. The renderer and the file are real; the pty is not.
