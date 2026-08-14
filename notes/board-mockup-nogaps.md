# Board mockup changes (worker-28)

`scripts/board_mockup.py`, on branch `worker-28` (based on `worker-25`, commit `0305804`).
Still a spike — nothing imports it, no product code touched.

## How to run it

```
~/.cache/sb-board-mockup/venv/bin/python \
  /Users/andrew/.herdr/worktrees/switchboard/worker-28/scripts/board_mockup.py
```

Add `--once` for a single frame, `--width N` to force a pane width, `--source sample`
for the built-in fixture. Round 4 adds `--gutter bracket|bar|tick|none` (the workspace
grouping variants, default `bracket`) and `--gutter-colour single|rotate` (default
`single`).

> **Read the rounds in order — later ones supersede earlier frames.** Blank lines: rounds
> 1 and 2 removed every one; round 3 put a single one back, above the NEEDS YOU bar and
> nowhere else. Round 4 added the workspace gutter and the gone-agent treatment; round 5
> fixed the grouping rule, moved the gutter into the indentation and recoloured it;
> round 6 marks one-row workspaces and moves `done` off yellow; round 7 takes tops out
> of the gutter and settles `done` on a muted blue.
> **Only the round 7 frames show what the board currently looks like.**

## Round 1 — no blank lines

Four blank lines removed, all of them. Nothing put in their place — no rule, no
separator, no extra padding:

1. **The group break between agents.** `render` used to emit a blank line above every
   row at depth ≤ 1, i.e. above each top-level agent and each of its direct children.
   With one-line rows that was an empty line between nearly every pair of agents. Gone;
   the loop is a plain `for row in rows` with no gap logic at all.
2. **Under the header bar.**
3. **Above the NEEDS YOU bar.**
4. **Above the footer line.**

Nothing was kept back. The filled header bar, the filled NEEDS YOU bar and the rounded
panel border carry all the separation, and the tree indentation carries the structure.

## Round 2 — plain state words, and a two-kind NEEDS YOU

**The state pill lost its fill.** `PILL` → `STATE`, `pill()` → `state_word()`. The state
is now plain coloured text with the same colour meanings as before: working green, done
yellow, idle grey/dim, blocked/failed/gone red. Colour is still never load-bearing —
the word says it.

Two knock-ons, both deliberate:

- The state column is now exactly as wide as the widest state word. It used to carry two
  columns of side padding, which is invisible without a background.
- The width-degrade ladder in `render` lost a rung. It used to give up, in order, the
  idle age, then the pill's padding, then the name; there is no padding left to give up,
  so it is now age, then name (floor of 6 columns), then the reserved tail.

**NEEDS YOU lists two kinds only** (`needs_kind`), blocked first, then idle:

| Kind      | Condition                     | Reason column                                     |
|-----------|-------------------------------|---------------------------------------------------|
| `BLOCKED` | `blocked` or `at_prompt`      | the `sb block` reason, or "at a prompt, waiting on you" |
| `IDLE`    | `stalled` or `signal_drift`   | "idle \<age\>, nothing running", or "died mid-turn, pane still open" |

Conditions taken from `notes/board-inventory.md` on branch `researcher-30`. The two are
told apart by the word in a fixed 7-column gutter, not by colour alone (colour is a
second signal: red for BLOCKED, yellow for IDLE).

Dropped from the list, and **worth confirming with Andrew**:

- **Unread mail no longer summons anybody.** This is what he asked for. The agent's own
  row still shows `mail: N unread` in its tail, and that tail is still reserved before
  the name, the age or anything else, so mail is not clipped first.
- **`gone` agents are no longer listed either.** He named two kinds and a pane herdr has
  no agent for is neither blocked nor idle. It is not invisible — its row still draws a
  red `✗` and `GONE — herdr has no such agent` — but it no longer appears under NEEDS
  YOU. Say the word and I will add it back as a third kind.
- **`+ N archived · M need you` uses the same predicate.** `needs_human` is now just
  `bool(needs_kind(a))`, and it ignores any `needs_human` key the collector publishes,
  because the collector counts unread mail in it. Without this the collapsed row would
  say "need you" about agents the NEEDS YOU bar deliberately omits. Visible effect on the
  live fleet: `+ 305 archived · 3 need you` is now just `+ 305 archived`.

Below ~14 columns of room the reason is dropped rather than shown as near-total
ellipsis — at 40 columns the section is `BLOCKED  worker-25` with no trailing text, which
says more than `closed yo…` does.

### On the filled bars, asked but not changed

The header bar and the NEEDS YOU bar are now the only filled elements on the board. They
do **not** look out of place to me, and I have left them alone. With every blank line
gone they are the only thing separating the three sections, and being the sole filled
elements makes them read unambiguously as section headers rather than as decoration
competing with the rows. When the pills were also filled, the bars were one of many
coloured blocks and read as weaker. This is a judgement call on a mockup, though — if
Andrew wants them plain too it is a two-line change to `HEADER_STYLE` and `NEEDS_STYLE`.

## Round 3 — one blank line back, above NEEDS YOU

Exactly one, and only that one: `render` emits a single empty line immediately above the
NEEDS YOU bar, because that is the section Andrew acts on and he wants it to breathe.
Nothing changed under the header, between agent rows, or above the footer — those stay
gone. The line lives inside the `if wanted:` branch, so a board with nobody to summon has
no blank line at all.

## Verification (rounds 1–3)

Real fleet data (the live collector snapshot), rendered at 67 columns. Note the single
empty line above `NEEDS YOU` and nowhere else. These frames predate round 4, so they show
no workspace gutter:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 17 alive · 2 blocked · 13 unread                 │
│  ○ main-3           failed   5d10h                              │
│  ○   split-fixer    failed   4d10h  mail: 4 unread              │
│  ○     worker-1     done     5d13h                              │
│      + 4 archived                                               │
│  ○ main-10          failed    1h57                              │
│  ◌   worker-9       working  1d04h  STALLED — idle 1d04h        │
│  ○   reviewer-14    done     15h18                              │
│      + 10 archived                                              │
│  ○ main-11          done      1h54                              │
│      + 10 archived                                              │
│  ◐ main-15          blocked     1m  BLOCKED — decision now thr… │
│  ◌   worker-24      working   1h04  STALLED —… · mail: 1 unread │
│  ◌   researcher-20  working   1h04  STALLED —… · mail: 1 unread │
│  ○   worker-26      done       24m                              │
│  ○   worker-27      done        6m                              │
│  ●   worker-29      working     5m                              │
│      + 7 archived                                               │
│  ◌ board-fix        working    58s  STALLED — idle 58s          │
│  ○   researcher-22  done      1h10  mail: 1 unread              │
│  ○   researcher-23  done       34m  mail: 1 unread              │
│  ◐   worker-25      blocked    20m  BLOCKED — closed… · UNDEL 1 │
│  ●   worker-28      working     1m                              │
│  ●   researcher-31  working     1m                              │
│  ●   researcher-32  working     1m                              │
│      + 5 archived                                               │
│    + 305 archived                                               │
│                                                                 │
│  NEEDS YOU · 6                                                  │
│   BLOCKED  main-15        decision now three ways on the dispa… │
│   BLOCKED  worker-25      closed your right pane by accident; … │
│   IDLE     worker-9       idle 1d04h, nothing running           │
│   IDLE     worker-24      idle 1h04, nothing running            │
│   IDLE     researcher-20  idle 1h04, nothing running            │
│   IDLE     board-fix      idle 58s, nothing running             │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

The built-in sample at 67 columns, which is the only fixture with an at-a-prompt agent, a
`GONE` agent and undelivered mail in it:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│  ● board-fix        working     2s                              │
│  ◐   researcher-22  done        3m  AT PROMPT — wai… · 1 unread │
│  ○   researcher-23  done        3m  mail: 1 unread              │
│  ●   researcher-26  working    15s                              │
│  ◐   worker-25      blocked     4m  BLOCKED — which pane shoul… │
│  ◌     qa-31        idle       12m  STALLED — idle 1… · UNDEL 2 │
│  ✗   worker-19      idle       31m  GONE — herdr has no such a… │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│ sample data — asked for · mockup, not the board                 │
╰─────────────────────────────────────────────────────────────────╯
```

The same fleet at 40 columns — one line per agent, no wrap, reason column dropped:

```
╭─ switchboard ────────────────────────╮
│  switchboard · 17 alive · 2 blocked… │
│  ○ main-3  failed                    │
│  ○   …xer  failed   mail: 4 unread   │
│  ○     w…  done                      │
│      + 4 archived                    │
│  ○ ma…-10  failed                    │
│  ◌   …r-9  working  STALLED — idle … │
│  ○   …-14  done                      │
│      + 10 archived                   │
│  ○ ma…-11  done                      │
│      + 10 archived                   │
│  ◐ ma…-15  blocked  BLOCKED — decis… │
│  ◌   …-24  working  STAL… · 1 unread │
│  ◌   …-20  working  STAL… · 1 unread │
│  ○   …-26  done                      │
│  ○   …-27  done                      │
│  ●   …-29  working                   │
│      + 7 archived                    │
│  ◌ bo…fix  working  STALLED — idle … │
│  ○   …-22  done     mail: 1 unread   │
│  ○   …-23  done     mail: 1 unread   │
│  ◐   …-25  blocked  BLOCK… · UNDEL 1 │
│  ●   …-28  working                   │
│  ●   …-31  working                   │
│  ●   …-32  working                   │
│      + 5 archived                    │
│    + 305 archived                    │
│                                      │
│  NEEDS YOU · 6                       │
│   BLOCKED  main-15                   │
│   BLOCKED  worker-25                 │
│   IDLE     worker-9                  │
│   IDLE     worker-24                 │
│   IDLE     researcher-20             │
│   IDLE     board-fix                 │
│ live snapshot · mockup, not the boa… │
╰──────────────────────────────────────╯
```

Checked programmatically at 40, 56, 67 and 100 columns over both the live snapshot and
the sample, measuring display columns the way the script's own `vlen` does: every line is
exactly the requested width (so nothing wraps at any of them), and each frame contains
exactly ONE empty line inside the panel — the one immediately above the NEEDS YOU bar.

The nobody-to-summon case, rendered from a two-agent snapshot in a scratch dir via
`SB_PANEL_DIR` (both agents healthy, both holding unread mail). No NEEDS YOU section, and
therefore no blank line anywhere — and mail alone does not summon:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 2 alive · 4 unread                               │
│  ● main-1      working     5s  mail: 3 unread                   │
│  ●   worker-2  working     2s  mail: 1 unread                   │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

Not proven: fleet shapes none of these three inputs contains — a very deep tree, a name
far longer than any here, more than six agents wanting a person at once (the `+ N more`
line) — were not exercised, and nothing here was checked in a real terminal; the frames
above are piped output with `NO_COLOR` set, so the colours themselves are unverified by
eye.

## Round 4 — workspace grouping in a left gutter, and gone agents

> **Superseded by round 5**, which fixes the grouping rule (it merged
> worktrees), moves the gutter into the indentation, and recolours it. The
> variant frames below still show the round 4 geometry.

Two things, neither of them wired into the real board. This is still only
`scripts/board_mockup.py`.

### Grouping: a rule in a left gutter, no blank line

A workspace boundary is exactly "a top-level agent and its whole subtree", and the row
order is already contiguous by workspace — researcher-32 established both from the store's
full 361-row history (`notes/board-worktree-grouping.md`, branch `researcher-32`). So the
gutter needs no workspace lookup at all: a group opens at every depth-0 agent and runs to
the row before the next one. `group_spans` is those six lines; `gutter_column` turns them
into one `(char, style)` per row.

**The cost is exactly one column.** The rule takes over the leading space the row already
had and adds one of its own, so `fixed` goes from 5 to 6. Everything upstream of it is
untouched: the reserved tail (`BLOCKED`/`MAIL`) is still charged to the budget first, and
the name column still has its floor of 6. At 40 columns the name and state columns are
already at their floors with or without the gutter, so **the whole column comes off the
tail** — the rightmost, lowest-priority text — and nothing else clips sooner. Measured, at
40 columns, `--gutter none` on the left and `--gutter bracket` on the right:

```
│  ● bo…fix  working                   │   │ ╭ ● bo…fix  working                  │
│  ◐   …-22  done     AT P… · 1 unread │   │ │ ◐   …-22  done     AT … · 1 unread │
│  ○   …-23  done     mail: 1 unread   │   │ │ ○   …-23  done     mail: 1 unread  │
│  ●   …-26  working                   │   │ │ ●   …-26  working                  │
│  ◐   …-25  blocked  BLOCKED — which… │   │ │ ◐   …-25  blocked  BLOCKED — whic… │
│  ◌     q…  idle     STALL… · UNDEL 2 │   │ │ ◌     q…  idle     STAL… · UNDEL 2 │
│  ✗   …-19  idle     GONE — herdr ha… │   │ │ ✗   …-19  idle     GONE — herdr h… │
│      + 1 archived                    │   │ ╰     + 1 archived                   │
```

Identical names, identical states, three characters fewer of tail. Selected with
`--gutter bracket|bar|tick|none` (default `bracket`) and `--gutter-colour single|rotate`
(default `single`).

#### (a) `--gutter bracket` — corner, rule, corner

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 14 alive · 12 unread                             │
│ ╭ ○ main-10          failed    2h09                             │
│ │ ◌   worker-9       working  1d04h  STALLED — idle 1d04h       │
│ │ ○   reviewer-14    done     15h31                             │
│ ╰     + 10 archived                                             │
│ ╭ ○ main-11          done      2h07                             │
│ ╰     + 10 archived                                             │
│ ╭ ◌ main-15          working     1m  STALLED — idle 1m          │
│ │ ◌   worker-24      working     9m  STALLED … · mail: 1 unread │
│ │ ◌   researcher-20  working     9m  STALLED … · mail: 1 unread │
│ │ ○   worker-26      done       37m                             │
│ │ ○   worker-27      done       19m                             │
│ │ ○   worker-29      done        8m                             │
│ │ ●   worker-30      working     1m                             │
│ ╰     + 8 archived                                              │
│ ╭ ◌ board-fix        working     1m  STALLED — idle 1m          │
│ │ ○   researcher-22  done      1h22  mail: 1 unread             │
│ │ ○   researcher-23  done        3m  mail: 1 unread             │
│ │ ●   worker-28      working     3m                             │
│ ╰     + 8 archived                                              │
│     + 312 archived                                              │
│                                                                 │
│  NEEDS YOU · 5                                                  │
│   IDLE     worker-9       idle 1d04h, nothing running           │
│   IDLE     main-15        idle 1m, nothing running              │
│   IDLE     worker-24      idle 9m, nothing running              │
│   IDLE     researcher-20  idle 9m, nothing running              │
│   IDLE     board-fix      idle 1m, nothing running              │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

#### (b) `--gutter bar` — a plain rule, full height, no corners

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 14 alive · 12 unread                             │
│ ▌ ○ main-10          failed    2h09                             │
│ ▌ ◌   worker-9       working  1d04h  STALLED — idle 1d04h       │
│ ▌ ○   reviewer-14    done     15h31                             │
│ ▌     + 10 archived                                             │
│ ▌ ○ main-11          done      2h07                             │
│ ▌     + 10 archived                                             │
│ ▌ ◌ main-15          working     1m  STALLED — idle 1m          │
│ ▌ ◌   worker-24      working     9m  STALLED … · mail: 1 unread │
│ ▌ ◌   researcher-20  working     9m  STALLED … · mail: 1 unread │
│ ▌ ○   worker-26      done       37m                             │
│ ▌ ○   worker-27      done       19m                             │
│ ▌ ○   worker-29      done        8m                             │
│ ▌ ●   worker-30      working     1m                             │
│ ▌     + 8 archived                                              │
│ ▌ ◌ board-fix        working     1m  STALLED — idle 1m          │
│ ▌ ○   researcher-22  done      1h22  mail: 1 unread             │
│ ▌ ○   researcher-23  done        3m  mail: 1 unread             │
│ ▌ ●   worker-28      working     3m                             │
│ ▌     + 8 archived                                              │
│     + 312 archived                                              │
│                                                                 │
│  NEEDS YOU · 5                                                  │
│   IDLE     worker-9       idle 1d04h, nothing running           │
│   IDLE     main-15        idle 1m, nothing running              │
│   IDLE     worker-24      idle 9m, nothing running              │
│   IDLE     researcher-20  idle 9m, nothing running              │
│   IDLE     board-fix      idle 1m, nothing running              │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

#### (c) `--gutter tick` — the cheapest: a mark on the group's first row only

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 14 alive · 12 unread                             │
│ ▌ ○ main-10          failed    2h09                             │
│   ◌   worker-9       working  1d04h  STALLED — idle 1d04h       │
│   ○   reviewer-14    done     15h31                             │
│       + 10 archived                                             │
│ ▌ ○ main-11          done      2h07                             │
│       + 10 archived                                             │
│ ▌ ◌ main-15          working     1m  STALLED — idle 1m          │
│   ◌   worker-24      working     9m  STALLED … · mail: 1 unread │
│   ◌   researcher-20  working     9m  STALLED … · mail: 1 unread │
│   ○   worker-26      done       37m                             │
│   ○   worker-27      done       19m                             │
│   ○   worker-29      done        8m                             │
│   ●   worker-30      working     1m                             │
│       + 8 archived                                              │
│ ▌ ◌ board-fix        working     1m  STALLED — idle 1m          │
│   ○   researcher-22  done      1h22  mail: 1 unread             │
│   ○   researcher-23  done        3m  mail: 1 unread             │
│   ●   worker-28      working     3m                             │
│       + 8 archived                                              │
│     + 312 archived                                              │
│                                                                 │
│  NEEDS YOU · 5                                                  │
│   IDLE     worker-9       idle 1d04h, nothing running           │
│   IDLE     main-15        idle 1m, nothing running              │
│   IDLE     worker-24      idle 9m, nothing running              │
│   IDLE     researcher-20  idle 9m, nothing running              │
│   IDLE     board-fix      idle 1m, nothing running              │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

#### Which one, and why

**Bracket, in a single colour.** Two findings decided it, both visible above:

1. **`bar` does not actually group.** In one colour it is an unbroken column of `▌` down
   the entire board with no boundary anywhere in it — look at variant (b): you cannot tell
   where `main-11` ends and `main-15` begins. It only separates groups if the colour
   changes at each boundary, which makes it depend on rotation, which is the thing that
   fails next.
2. **Rotating colours is the tempting answer and the wrong one.** A terminal has a handful
   of reliably distinct colours; this fleet has run ninety-odd workspaces and shows five or
   six groups on a screen. `--gutter-colour rotate` recycles inside a single screen, and
   two groups sharing a colour reads as *one group* — precisely the claim the gutter exists
   to make correctly. One of the rotation colours is also blue, which is the panel border's
   own colour, so that group's rule visually merges with the frame. Implemented so Andrew
   can see it, not recommended.

The bracket's corners carry the boundary on their own, so it needs no colour to work at
all — the colour is pure decoration, which is the rule everywhere else in this file.
`tick` is the honourable runner-up: it also works in one colour and reads cleanly, but it
marks only where a group *starts*, so the last group's end is implied rather than drawn,
and a group that scrolls off the top loses its only marker.

One detail worth confirming: a one-row group gets a plain `│` rather than a corner, since
two corners will not fit on one row and a lone corner claims an extent the group does not
have. The trailing `+ 312 archived` row gets no rule at all — it stands for archived
top-level agents, which are whole workspaces of their own that are not on screen to be
bracketed.

### Gone agents: visible, and an offer in the footer

**Only the visual half.** No input handling, no sweep — the mockup reads no keys and
clears nothing. What is here is how it would read.

A gone agent's row is now red the whole way across — glyph, name, state, age and the
`GONE — herdr has no such agent` tail — with the name struck through. The strike sits on
top of the glyph, the red and the word, so a terminal that ignores it loses no meaning.
Verified by reading the emitted SGR codes rather than by eye: the name carries `1;9;31`
(bold, strike, red), the state, age and tail carry `31`.

The footer carries the offer, on a filled red block, and it goes **first** on the line so a
narrow pane clips the provenance note rather than the one actionable thing:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│ ╭ ● board-fix        working     2s                             │
│ │ ◐   researcher-22  done        3m  AT PROMPT — wa… · 1 unread │
│ │ ○   researcher-23  done        3m  mail: 1 unread             │
│ │ ●   researcher-26  working    15s                             │
│ │ ◐   worker-25      blocked     4m  BLOCKED — which pane shou… │
│ │ ◌     qa-31        idle       12m  STALLED — idle … · UNDEL 2 │
│ │ ✗   worker-19      idle       31m  GONE — herdr has no such … │
│ ╰     + 1 archived                                              │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│  x  clear 1 gone   sample data — asked for · mockup, not the b… │
╰─────────────────────────────────────────────────────────────────╯
```

`x  clear 1 gone` is a sketch of a key, not a key. The count comes from the real agent
list, so it says how many rows would go.

### Verified

Every combination of `{bracket, bar, tick, none}` × `{40, 56, 67, 100}` columns ×
`{live snapshot, sample}`: every line exactly the requested width, so nothing wraps, and
exactly one blank line inside each panel — still the one above NEEDS YOU. `--archived`
checked too (groups still open at depth 0 when nothing collapses).

Not verified: the colours themselves, by eye, in a real terminal — the frames above are
piped `NO_COLOR` output and the colour claims come from reading escape codes. Whether the
struck-through name renders at all depends on the terminal. And no fleet shape beyond the
live snapshot and the sample: no very deep tree, no name longer than these, no `+ N more`
in NEEDS YOU, and no fleet with two or more gone agents at once (the footer count is
formatted from a real count, but only ever rendered as `1`).

## Round 5 — group on the workspace value, gutter into the indent, real colours

> **Partly superseded by round 6**: one-row workspaces now get a mark instead of
> nothing, and `done` is dim rather than bold yellow. The grouping rule, the
> zero-cost geometry and the rest of the colour inventory below still stand.

### The groups were wrong

Round 4 bracketed "a depth-0 agent and its whole subtree". That merges several worktrees
into one: a new workspace opens when a **top** delegates, so each direct child of a top
starts its own workspace and the top sits alone in its own. The gutter now reads the
`workspace` field and a group is simply **a run of consecutive rows sharing a workspace**
(`group_runs`). No fork rule is encoded here at all, so it stays right whichever way that
rule goes later.

The live store settles it with a case depth cannot see: `workspace-debug`, a depth-1 child
of `main`, has `workspace == "main"` — the same as its parent, unlike every one of its
siblings. Under the old rule it was swallowed into `main`'s bracket along with fifteen
other worktrees. Now it is correctly its own thing. Full archived history at 67 columns:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 11 alive · 14 unread                             │
│  ○ main                       failed                            │
│  ○ ╭ plugins-redesign-lead    done                              │
│  ○ │   plugin-redesign        done                              │
│  ○ │     plugins-investigate  done                              │
│  ○ │     design-a             done                              │
│  ○ │     design-b             done                              │
│  ○ │     design-synth         done                              │
│  ○ │     verify-design        done                              │
│  ○ │     design-patch         done                              │
│  ○ │     phase1-split         done                              │
│  ○ │     phase2-loader        done                              │
│  ○ │     phase3-prompts       done                              │
│  ○ │     phase4-plugins       done                              │
│  ○ │     land-redesign        done                              │
│  ○ │     land-redesign-2      done                              │
│  ○ │     land-rebase          done                              │
│  ○ │     doc-reconcile        done                              │
│  ○ ╰     doc-sweep            done                              │
│  ○   workspace-debug          failed                            │
│  ○ ╭ workspace-model-lead     done                              │
│  ○ │   wm-phase0              done                              │
│  ○ │   wm-spawn-claim         done                              │
│  ○ │   wm-board               done                              │
│  ○ │   wm-plugins             done                              │
│  ○ │   wm-claim-fix           done                              │
│  ○ │   wm-model               done                              │
│  ○ │     store-split          done                              │
│  ○ │     fork-rule            done                              │
│  ○ │     join-workspace       done                              │
│  ○ │     phase2-integrate     done                              │
│  ○ ╰   wm-land                done                              │
│  ○   sb-guard                 done                              │
│  … (the rest of 364 archived agents)                            │
```

`main` alone, unbracketed. `plugins-redesign-lead` and its whole subtree in one bracket —
one worktree, correctly. `workspace-debug` and `sb-guard` (both `workspace == "main"`)
standing apart, each a run of one.

**A one-row group draws no bracket, in general.** Enclosing a single row says "these rows
go together" about one row, which is not information — and the top orchestrator, always
alone in its own workspace, is exactly the case Andrew said he does not want enclosed.

**The consequence, which is worth a look before you accept it:** on the *current* live
fleet nothing is bracketed at all, because every visible agent happens to be alone in its
worktree — the multi-agent worktrees are all in the archived history.

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 11 alive · 14 unread                             │
│  ○ main-10          failed    2h37                              │
│  ◌   worker-9       working  1d04h  STALLED — idle 1d04h        │
│  ○   reviewer-14    done     15h58                              │
│      + 10 archived                                              │
│  ○ main-11          done      2h34                              │
│      + 10 archived                                              │
│  ● main-15          working     1m                              │
│  ◌   worker-24      working     2m  STALLED —… · mail: 2 unread │
│  ◌   researcher-20  working     2m  STALLED —… · mail: 2 unread │
│  ●   worker-30      working     5m                              │
│      + 12 archived                                              │
│  ◌ board-fix        working     4m  STALLED — idle 4m           │
│  ○   researcher-22  done      1h50  mail: 1 unread              │
│  ○   researcher-23  done       30m  mail: 1 unread              │
│  ●   worker-28      working     4m                              │
│      + 8 archived                                               │
│    + 312 archived                                               │
│                                                                 │
│  NEEDS YOU · 4                                                  │
│   IDLE     worker-9       idle 1d04h, nothing running           │
│   IDLE     worker-24      idle 2m, nothing running              │
│   IDLE     researcher-20  idle 2m, nothing running              │
│   IDLE     board-fix      idle 4m, nothing running              │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

That is the honest rendering of this fleet, not a bug. But if Andrew wants to *see* his
worktrees rather than only see where they run deep, the alternative is to bracket one-row
groups too, which puts a rule beside nearly every row on this board. Say which he prefers.

Two other rules I had to pick, both stated rather than hidden:

- A **collapsed** `+ N archived` row carries no workspace of its own — the agents behind
  it may be several — so it belongs to no run and ends whichever run it follows. In
  practice these sit at the end of a subtree, so nothing real is split; a collapsed row
  landing mid-run would cut that group's rule in two.
- A run whose shallowest row is at **depth 0** is skipped: there is no indentation to draw
  in, and shifting the whole board one column right to accommodate it is a worse trade.
  Not observed in any real data — every workspace with more than one agent is rooted at
  depth ≥ 1.

I also corrected the built-in sample fixture: `qa-31`, a child of `worker-25`, had
`workspace="qa-31"`. Only a top's delegate mints a workspace, so it is `worker-25`. The
fixture had been wrong since it was written; reading the field is what exposed it.

### The gutter moved into the indent — and now costs nothing

It was a rule in the leading space at the far left, costing one column. It now sits
**between the glyph and the name**, inside the indentation the row already carries, at the
column its group's shallowest row indents to. Every row in a run is at least that deep, so
the rule always lands on a space that was already there.

**Cost: zero columns.** `fixed` is back to 5, the same as with no gutter at all. Proved
rather than asserted: rendering the same data with `--gutter none` and `--gutter bracket`
at 40, 56, 67 and 100 columns, the frames differ **only** in the rule characters
themselves — every row is the same length and differs by at most one character, in place.
Names, states, ages and tails are byte-identical. At 40 columns:

```
│  ◐   …-25  blocked  BLOCKED — which… │      ← --gutter none
│  ◐ ╭ …-25  blocked  BLOCKED — which… │      ← --gutter bracket
│  ◌     q…  idle     STALL… · UNDEL 2 │      ← --gutter none
│  ◌ ╰   q…  idle     STALL… · UNDEL 2 │      ← --gutter bracket
```

All three variants, on the sample fixture at 67 columns:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│  ● board-fix        working     2s                              │
│  ◐   researcher-22  done        3m  AT PROMPT — wai… · 1 unread │
│  ○   researcher-23  done        3m  mail: 1 unread              │
│  ●   researcher-26  working    15s                              │
│  ◐ ╭ worker-25      blocked     4m  BLOCKED — which pane shoul… │
│  ◌ ╰   qa-31        idle       12m  STALLED — idle 1… · UNDEL 2 │
│  ✗   worker-19      idle       31m  GONE — herdr has no such a… │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│  x  clear 1 gone   sample data — asked for · mockup, not the b… │
╰─────────────────────────────────────────────────────────────────╯
```

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│  ● board-fix        working     2s                              │
│  ◐   researcher-22  done        3m  AT PROMPT — wai… · 1 unread │
│  ○   researcher-23  done        3m  mail: 1 unread              │
│  ●   researcher-26  working    15s                              │
│  ◐ ▌ worker-25      blocked     4m  BLOCKED — which pane shoul… │
│  ◌ ▌   qa-31        idle       12m  STALLED — idle 1… · UNDEL 2 │
│  ✗   worker-19      idle       31m  GONE — herdr has no such a… │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│  x  clear 1 gone   sample data — asked for · mockup, not the b… │
╰─────────────────────────────────────────────────────────────────╯
```

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│  ● board-fix        working     2s                              │
│  ◐   researcher-22  done        3m  AT PROMPT — wai… · 1 unread │
│  ○   researcher-23  done        3m  mail: 1 unread              │
│  ●   researcher-26  working    15s                              │
│  ◐ ▌ worker-25      blocked     4m  BLOCKED — which pane shoul… │
│  ◌     qa-31        idle       12m  STALLED — idle 1… · UNDEL 2 │
│  ✗   worker-19      idle       31m  GONE — herdr has no such a… │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│  x  clear 1 gone   sample data — asked for · mockup, not the b… │
╰─────────────────────────────────────────────────────────────────╯
```

My pick is unchanged: **`bracket`, single colour**. With one-row groups now drawing
nothing, `bar` and `bracket` differ only at the two ends of a run, and `bar`'s ambiguity
from round 4 is gone — but the corners still say where a group starts and stops without
asking colour to carry it, and `tick` still leaves a group's end implied.

### Colours

**The gutter was `grey42` — a mid grey, and effectively invisible. That is what Andrew was
seeing.** It is now `bold cyan` (SGR `1;36`), which is outside the board's status
vocabulary of green/yellow/red and distinct from the panel border's blue (`34`).

Full inventory below. Every entry was read off the emitted escape codes, not from the
style strings, so it is what the terminal is actually told.

| Element | Style | SGR | Reads as |
|---|---|---|---|
| Panel border and rule | `blue` | `34` | blue |
| Panel title `switchboard` | `bold blue` | `1;34` | bright blue |
| Header bar | `bold white on blue` | `1;37;44` | white on blue |
| **Workspace gutter rule** (single) | `bold cyan` | `1;36` | **bright cyan** |
| Workspace gutter rule (`rotate`) | cyan/magenta/green/blue/yellow/red | `1;36` `1;35` `1;32` `1;34` `1;33` `1;31` | cycles per group |
| Glyph `●` healthy | `bold green` | `1;32` | bright green |
| Glyph `◐` at prompt / blocked | `bold yellow` | `1;33` | bright yellow |
| Glyph `◌` stalled / no session | `bold yellow` | `1;33` | bright yellow |
| Glyph `○` finished | `dim` | `2` | dim default |
| Glyph `?` herdr unreachable | `dim` | `2` | dim default |
| Glyph `✗` gone | `bold red` | `1;31` | bright red |
| Agent name, ordinary | none | — | terminal default |
| Agent name, wants a person | `bold` | `1` | bold default |
| Agent name, **gone** | `bold red strike` | `1;9;31` | bright red, struck through |
| State `working` | `bold green` | `1;32` | bright green |
| State `done` | `bold yellow` | `1;33` | bright yellow |
| State `idle` | `dim` | `2` | dim default |
| State `blocked` / `failed` / `gone` | `bold red` | `1;31` | bright red |
| State on a gone row (override) | `red` | `31` | red |
| Idle age | `dim` | `2` | dim default |
| Idle age on a gone row | `red` | `31` | red |
| Row tail (`BLOCKED …`, `mail: …`) | `yellow` | `33` | yellow |
| Row tail on a gone row | `bold red` | `1;31` | bright red |
| `+ N archived` collapsed row | `dim` | `2` | dim default |
| NEEDS YOU bar | `bold black on yellow` | `1;30;43` | black on yellow |
| NEEDS YOU kind `BLOCKED` | `bold red` | `1;31` | bright red |
| NEEDS YOU kind `IDLE` | `bold yellow` | `1;33` | bright yellow |
| NEEDS YOU name | `bold` | `1` | bold default |
| NEEDS YOU reason | `dim` | `2` | dim default |
| NEEDS YOU `+ N more` | `dim` | `2` | dim default |
| Footer `x  clear N gone` | `bold white on red` | `1;37;41` | white on red |
| Footer provenance note | `dim` | `2` | dim default |

Two things that fall out of the list, reported and not changed:

- **`bold yellow` (`1;33`) is doing four jobs**: the `◐` and `◌` glyphs, the `done` state,
  and the `IDLE` kind in NEEDS YOU. So a finished agent's state word is the same colour as
  the glyph that means "this one wants you". Every one of those also carries a word or a
  distinct glyph, so nothing is lost — but if Andrew wants `done` to recede, moving it to
  plain (non-bold) yellow or to dim would separate them.
- **`dim` (`2`) is the other overloaded one**: `idle`, ages, collapsed rows, reasons and
  the footer. That one seems right — it is the "background information" tier throughout.

### Verified

128 combinations — `{live, sample}` × `{with, without `--archived`}` ×
`{bracket, bar, tick, none}` × `{40, 56, 67, 100}` columns: every line exactly the
requested width so nothing wraps, and exactly one blank line inside each panel (still the
one above NEEDS YOU). Plus the zero-cost diff above at all four widths.

Not verified: the colours by eye in a real terminal. The inventory is read from emitted
SGR codes, which is what the terminal is told, not what it draws — how `bold cyan` and
`strike` actually look is Andrew's to judge. And no fleet shape beyond the live snapshot
(both collapsed and `--archived`) and the sample: no `+ N more` in NEEDS YOU, and never
more than one gone agent at once.

## Round 6 — every workspace marked, and `done` off the wants-you yellow

> **Partly superseded by round 7**: top orchestrators are excluded from the gutter
> entirely (so the depth-0 blemish below is gone, by deletion), and `done` moved from
> dim to a muted blue.

### A mark for a workspace of one

A run of one gets a standalone **`·`** (middle dot) in the same cyan as the rule, so every
workspace is visible and not just the ones that run deep. The dot rather than a bullet
deliberately: `●` is already the healthy-agent glyph and `•` beside it would read as a
second status glyph, whereas `·` cannot be mistaken for one. Brackets are unchanged — a
run of two or more still gets `╭ │ ╰`.

The live fleet, where before this every workspace held one visible agent and nothing at
all was drawn:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 15 alive · 14 unread                             │
│ ·○ main-10          failed    2h50                              │
│  ◌ · worker-9       working  1d05h  STALLED — idle 1d05h        │
│  ○ · reviewer-14    done     16h11                              │
│      + 10 archived                                              │
│ ·○ main-11          done      2h48                              │
│      + 10 archived                                              │
│ ·◌ main-15          working     8m  STALLED — idle 8m           │
│  ◌ · worker-24      working    15m  STALLED —… · mail: 2 unread │
│  ◌ · researcher-20  working    15m  STALLED —… · mail: 2 unread │
│  ◌ · worker-30      working     9m  STALLED — idle 9m           │
│  ● · researcher-33  working    12m                              │
│  ● · reviewer-17    working     8m                              │
│      + 12 archived                                              │
│ ·◌ board-fix        working     3m  STALLED — idle 3m           │
│  ○ · researcher-22  done      2h03  mail: 1 unread              │
│  ○ · researcher-23  done       43m  mail: 1 unread              │
│  ● · worker-28      working     3m                              │
│      + 8 archived                                               │
│ ·● main-16          working     4m                              │
│  ● · researcher-34  working     1m                              │
│    + 312 archived                                               │
│                                                                 │
│  NEEDS YOU · 6                                                  │
│   IDLE     worker-9       idle 1d05h, nothing running           │
│   IDLE     main-15        idle 8m, nothing running              │
│   IDLE     worker-24      idle 15m, nothing running             │
│   IDLE     researcher-20  idle 15m, nothing running             │
│   IDLE     worker-30      idle 9m, nothing running              │
│   IDLE     board-fix      idle 3m, nothing running              │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

The sample fixture, which has the one multi-agent worktree (`worker-25` and its `qa-31`):

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│ ·● board-fix        working     2s                              │
│  ◐ · researcher-22  done        3m  AT PROMPT — wai… · 1 unread │
│  ○ · researcher-23  done        3m  mail: 1 unread              │
│  ● · researcher-26  working    15s                              │
│  ◐ ╭ worker-25      blocked     4m  BLOCKED — which pane shoul… │
│  ◌ ╰   qa-31        idle       12m  STALLED — idle 1… · UNDEL 2 │
│  ✗ · worker-19      idle       31m  GONE — herdr has no such a… │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│  x  clear 1 gone   sample data — asked for · mockup, not the b… │
╰─────────────────────────────────────────────────────────────────╯
```

The archived history, where the deep worktrees are, showing dots and brackets together:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 15 alive · 14 unread                             │
│ ·○ main                       failed                            │
│  ○ ╭ plugins-redesign-lead    done                              │
│  ○ │   plugin-redesign        done                              │
│  ○ │     plugins-investigate  done                              │
│  ○ │     design-a             done                              │
│  ○ │     design-b             done                              │
│  ○ │     design-synth         done                              │
│  ○ │     verify-design        done                              │
│  ○ │     design-patch         done                              │
│  ○ │     phase1-split         done                              │
│  ○ │     phase2-loader        done                              │
│  ○ │     phase3-prompts       done                              │
│  ○ │     phase4-plugins       done                              │
│  ○ │     land-redesign        done                              │
│  ○ │     land-redesign-2      done                              │
│  ○ │     land-rebase          done                              │
│  ○ │     doc-reconcile        done                              │
│  ○ ╰     doc-sweep            done                              │
│  ○ · workspace-debug          failed                            │
│  ○ ╭ workspace-model-lead     done                              │
│  … (the rest of 364 archived agents)                            │
```

At 40 columns, unchanged in cost:

```
╭─ switchboard ────────────────────────╮
│  switchboard · 15 alive · 14 unread  │
│ ·○ ma…-10  failed                    │
│  ◌ · …r-9  working  STALLED — idle … │
│  ○ · …-14  done                      │
│      + 10 archived                   │
│ ·○ ma…-11  done                      │
│      + 10 archived                   │
│ ·◌ ma…-15  working  STALLED — idle … │
│  ◌ · …-24  working  STAL… · 2 unread │
│  ◌ · …-20  working  STAL… · 2 unread │
│  ◌ · …-30  working  STALLED — idle … │
│  ● · …-33  working                   │
│  ● · …-17  working                   │
│      + 12 archived                   │
│ ·◌ bo…fix  working  STALLED — idle … │
│  ○ · …-22  done     mail: 1 unread   │
│  ○ · …-23  done     mail: 1 unread   │
│  ● · …-28  working                   │
│      + 8 archived                    │
│ ·● ma…-16  working                   │
│  ● · …-34  working                   │
│    + 312 archived                    │
│                                      │
│  NEEDS YOU · 6                       │
│   IDLE     worker-9                  │
│   IDLE     main-15                   │
│   IDLE     worker-24                 │
│   IDLE     researcher-20             │
│   IDLE     worker-30                 │
│   IDLE     board-fix                 │
│ live snapshot · mockup, not the boa… │
╰──────────────────────────────────────╯
```

### The depth-0 mark: it can be drawn, and it is tighter than the rest

The top orchestrator now gets a dot, as asked. It has no indentation of its own — its name
starts immediately after the glyph — so its dot goes in the row's **leading space**, the
only free column to the left of the glyph. Direction-wise that is right: the outermost
group's mark sits outermost, and the tops' dots line up in their own column.

**But it is the one mark with no space beside it**, so it reads tighter than every other:

```
│ ·○ main-10          failed    2h48       ← top: dot hard against the glyph
│  ◌ · worker-9       working  1d05h       ← depth 1: a space either side
```

It is legible — the dot is small and low, the glyphs are rings and discs, and I do not
think anyone misreads `·○` as one character — but it is a visible blemish and it is the
honest answer to "check it does not look wrong". Two ways out if Andrew dislikes it:

1. **Leave it.** Costs nothing, and the tops' dots form their own clean left column.
2. **Indent the whole board by two columns**, giving depth 0 an indent to draw in like
   every other level. That makes the top's dot identical to all the others and costs
   **two columns on every row**, which comes off the tail — the opposite of the
   zero-cost trade the gutter has made so far.

I left it as (1) and did not force anything further; say the word for (2).

### `done` is dim now

`done` was `bold yellow` — the board's "this one wants you" colour — so a finished agent
pulled the eye exactly like a stuck one. It is now `dim`, the same tier as ages, archived
rows and reasons. It shares that tier with `idle`, which is fine: the two are told apart
by the word, as everything here is.

Re-read the inventory afterwards from the emitted codes. **Bold yellow (`1;33`) is now
worn by exactly three things, all of which mean "wants you"**: the `◐` glyph (at a prompt
or blocked), the `◌` glyph (stalled or no session), and the `IDLE` kind in NEEDS YOU.
Nothing else lands on it. One caveat: `--gutter-colour rotate` includes bold yellow in its
cycle, so under `rotate` one group's mark wears the wants-you colour — one more reason
`single` is the default.

Changed rows in the inventory table above:

| Element | Was | Now | SGR |
|---|---|---|---|
| State `done` | `bold yellow` | `dim` | `2` |
| Lone-workspace mark `·` | — | `bold cyan` | `1;36` |

### Verified

64 combinations — `{live, sample}` × `{with, without `--archived`}` ×
`{bracket, bar, tick, none}` × `{40, 56, 67, 100}` columns: every line exactly the
requested width, exactly one blank line inside each panel. The gutter still costs **zero
columns**: diffing `--gutter none` against `--gutter bracket` at all four widths, every
differing row differs by **exactly one character, in place** — now 16 such rows on the live
fleet instead of 0, because every workspace is marked.

Not verified: the colours by eye. The inventory is read from emitted SGR codes — what the
terminal is told, not what it draws.

## Round 7 — tops out of the gutter, `done` in blue, and the worktree fact checked

### Tops are not marked at all

A depth-0 run is a top orchestrator's own workspace and now gets **nothing** — no dot, no
bracket. That also disposes of the round 6 blemish (a top's dot jammed against its glyph
for want of an indent) by deletion rather than by indenting the board, which stays at zero
cost. Everything else is unchanged: a dot for a workspace of one, a bracket for a run of
two or more.

The gutter now occupies one clean vertical column at depth 1, with the tops standing
outside it:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 13 alive · 14 unread                             │
│  ○ main-10          failed    3h04                              │
│  ◌ · worker-9       working  1d05h  STALLED — idle 1d05h        │
│  ○ · reviewer-14    done     16h25                              │
│      + 10 archived                                              │
│  ○ main-11          done      3h01                              │
│      + 10 archived                                              │
│  ● main-15          working     9s                              │
│  ◌ · worker-24      working    29m  STALLED —… · mail: 2 unread │
│  ◌ · researcher-20  working    29m  STALLED —… · mail: 2 unread │
│  ◌ · worker-30      working     6m  STALLED — idle 6m           │
│  ○ · worker-31      done        2s                              │
│  ● · reviewer-18    working     1m                              │
│      + 14 archived                                              │
│  ◌ board-fix        working     3m  STALLED — idle 3m           │
│  ○ · researcher-22  done      2h17  mail: 1 unread              │
│  ○ · researcher-23  done       57m  mail: 1 unread              │
│  ● · worker-28      working     3m                              │
│      + 8 archived                                               │
│  ○ main-16          done       11m                              │
│      + 1 archived                                               │
│    + 312 archived                                               │
│                                                                 │
│  NEEDS YOU · 5                                                  │
│   IDLE     worker-9       idle 1d05h, nothing running           │
│   IDLE     worker-24      idle 29m, nothing running             │
│   IDLE     researcher-20  idle 29m, nothing running             │
│   IDLE     worker-30      idle 6m, nothing running              │
│   IDLE     board-fix      idle 3m, nothing running              │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│  ● board-fix        working     2s                              │
│  ◐ · researcher-22  done        3m  AT PROMPT — wai… · 1 unread │
│  ○ · researcher-23  done        3m  mail: 1 unread              │
│  ● · researcher-26  working    15s                              │
│  ◐ ╭ worker-25      blocked     4m  BLOCKED — which pane shoul… │
│  ◌ ╰   qa-31        idle       12m  STALLED — idle 1… · UNDEL 2 │
│  ✗ · worker-19      idle       31m  GONE — herdr has no such a… │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 3                                                  │
│   BLOCKED  researcher-22  at a prompt, waiting on you           │
│   BLOCKED  worker-25      which pane should this render into?   │
│   IDLE     qa-31          idle 12m, nothing running             │
│  x  clear 1 gone   sample data — asked for · mockup, not the b… │
╰─────────────────────────────────────────────────────────────────╯
```

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 13 alive · 14 unread                             │
│  ○ main                       failed                            │
│  ○ ╭ plugins-redesign-lead    done                              │
│  ○ │   plugin-redesign        done                              │
│  ○ │     plugins-investigate  done                              │
│  ○ │     design-a             done                              │
│  ○ │     design-b             done                              │
│  ○ │     design-synth         done                              │
│  ○ │     verify-design        done                              │
│  ○ │     design-patch         done                              │
│  ○ │     phase1-split         done                              │
│  ○ │     phase2-loader        done                              │
│  ○ │     phase3-prompts       done                              │
│  ○ │     phase4-plugins       done                              │
│  ○ │     land-redesign        done                              │
│  ○ │     land-redesign-2      done                              │
│  ○ │     land-rebase          done                              │
│  ○ │     doc-reconcile        done                              │
│  ○ ╰     doc-sweep            done                              │
│  ○ · workspace-debug          failed                            │
│  ○ ╭ workspace-model-lead     done                              │
│  ○ │   wm-phase0              done                              │
│  ○ │   wm-spawn-claim         done                              │
│  … (the rest of 370 agents)                                     │
```

### `done` is `steel_blue`

Andrew asked for blue. Plain `blue` is **SGR `34` — byte-identical to the panel border**,
so a finished state word would render in exactly the colour of the frame around it.
`bold blue` (`1;34`) is the panel title. Anything toward `sky_blue3` (`38;5;74`) leans
into the gutter's `bold cyan` (`1;36`).

**Chosen: `steel_blue` (`38;5;67`)** — a desaturated mid blue, roughly `#5f87af`. It is
blue as asked, it collides with neither the border nor the gutter, and being desaturated
it recedes, which is what "finished, nothing to do" should do. Where the palette now
stands as a whole: green = running, bold yellow = wants you, red = trouble, dim =
background information, blue = chrome (border, header), cyan = structure (the gutter), and
`steel_blue` = finished.

One caveat: `38;5;67` is a 256-colour. On a terminal that can only do 16 it degrades to
the nearest standard colour, which is white — not blue. Every modern terminal does 256, so
this is a footnote rather than a risk.

If he dislikes it, one line in `STATE`:

```python
"done": "steel_blue",     # what it is now
"done": "blue",           # what he asked for — same colour as the panel border
"done": "cornflower_blue",# brighter, closer to the border's hue
"done": "magenta",        # maximum separation from everything else on the board
```

### The worktree fact, checked against the store

board-fix's reading was **correct**, and here is the count rather than the argument. Read
straight off the live snapshot (370 agents) through the mockup's own `display_rows`:

| | Visible (archived collapsed) | `--archived` (everything) |
|---|---|---|
| Rows drawn | 15 | 370 |
| Distinct workspaces | **15** | 203 |
| Workspaces holding more than one drawn row | **0** | 14 |
| Rows in such a shared workspace | **0** | 181 |
| Depth histogram | `{0: 5, 1: 10}` | `{0: 17, 1: 191, 2: 123, 3: 38, 4: 1}` |
| Rows at depth ≥ 2 | **0** | 162 |

So on the current board: **15 rows, 15 workspaces, no two rows sharing one.** Five of
those rows are tops (`main-10`, `main-11`, `main-15`, `main-16`, `board-fix`) and are now
unmarked; the other ten are direct children of a top, each genuinely in its own worktree,
and each gets a dot. Nothing is visible at depth 2 or below at all, which is why no bracket
appears — there is nothing on screen for a bracket to enclose.

The shared worktrees are real and are all archived. The largest under `--archived`:

```
worker-2          37 rows      teardown-fix      29 rows
status-board      22 rows      plugins-redesign  17 rows
workspace-model   12 rows      prompts           12 rows
accept-phase1     11 rows      fix-options-2     10 rows
```

One extra check worth having, over the whole 370-row history rather than the visible
fifteen: **the number of rows whose workspace differs from their parent's where the parent
is not a top is zero.** Every workspace fork in this store's entire history happens at a
"child of a top" edge — which is researcher-32's finding, reproduced independently here by
counting rather than by reading `broker.py`.

### Verified

64 combinations — `{live, sample}` × `{with, without `--archived`}` ×
`{bracket, bar, tick, none}` × `{40, 56, 67, 100}` columns: every line exactly the
requested width, exactly one blank line inside each panel. Gutter still costs **zero
columns**: `--gutter none` versus `--gutter bracket` differs on exactly 10 rows on the live
fleet — the ten depth-1 rows — each by exactly one character, in place. And a direct check
that no depth-0 row carries a mark under `--archived`: zero.

Not verified: the colours by eye. `steel_blue` in particular is a judgement I cannot make
from escape codes — I can prove it is not the border's blue and not the gutter's cyan, not
that it looks right.
