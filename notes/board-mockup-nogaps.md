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
> nowhere else. Round 4 adds the workspace gutter and the gone-agent treatment, so the
> frames under "Verification (rounds 1–3)" no longer show what the board looks like — the
> round 4 frames do.

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
