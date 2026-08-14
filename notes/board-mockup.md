# A runnable mockup of a richer board

`scripts/board_mockup.py` — a spike, not the board. It touches no product code and
nothing imports it. Built from the task in `notes/task-board-mockup.md` (board-fix),
the look chosen there ("bold + panelled" — sketches (b)+(c) of
`notes/board-ui-looks.md` on `researcher-27`), rendered through `rich` (the library
decision from `researcher-26`'s `notes/board-ui-deps.md`).

## Run it

```
~/.cache/sb-board-mockup/venv/bin/python \
  /Users/andrew/.herdr/worktrees/switchboard/worker-25/scripts/board_mockup.py
```

`q`/`Ctrl-C` quits. The venv was made outside the repo, once:

```
python3 -m venv ~/.cache/sb-board-mockup/venv
~/.cache/sb-board-mockup/venv/bin/pip install rich      # rich 15.0.0
```

Flags: `--once` (one frame, exits — for capture), `--width N` (force a pane width),
`--source auto|live|sample`, `--archived` (don't collapse archived subtrees),
`--refresh SECS` (default 2.0, the real board's cadence).

Nothing is wired into `sb` and `rich` is in no packaging file. That is a later step.

## What it draws

- A rounded bordered panel with a `switchboard` title.
- A filled header bar (white on blue) carrying the counts.
- **One line per agent, like the real board**: glyph, indented name, the state as a
  small filled **pill** (green `working`, yellow `done`, grey `idle`, red
  `blocked`/`failed`/`gone`), the idle age, then the trouble marker and the mail note.
- **No second line.** It drew a dim `↳ task` / `✓ summary` line per agent until Andrew
  said he does not read those on a board. They are gone rather than demoted; `sb
  status` still prints both.
- Group breaks as whitespace, and archived subtrees collapsed to `+ N archived ·
  N need you` — the same rule as `status.display_rows`.
- A `NEEDS YOU` bar (black on yellow) with the agents asking for a person.
- A dim footer saying which data source the frame came from.

## BLOCKED and MAIL are what the row protects

Andrew watches a board for two things — an agent that is BLOCKED, and mail nobody has
picked up — so those two are the last thing the row gives up, not the first.

- **The tail is budgeted first.** `render` reserves columns for the narrowest form of
  every row's marker+mail *before* it spends any width on the name, the age or the
  pill's padding. That is the reverse of `board._compose`, which fills left to right
  and lets the tail have the remainder.
- **The wording degrades before either piece is dropped** (`tail_forms`, widest rung
  first): `BLOCKED — which pane should this render into? · mail: 1 unread` →
  `BLOCKED — … · 1 unread` → `BLOCKED · 1 unread`. `mail: UNDELIVERED 2, 5m` shortens
  to `UNDEL 2`.
- **Below the ladder** (`squeeze`) the marker's word is clipped and the mail is kept
  whole — the pill beside it already says `blocked` and NEEDS YOU names the agent
  again, so an unanswered message is the thing a clip there would really lose. This is
  the same trade `board._MAIL_RESERVE` makes.
- **The name gives way first, and keeps its tail**: `researcher-22` clips to
  `rese…-22`, not `res…`, because the head is the half every sibling shares
  (`clip_name`).
- Measured on the sample fleet: the marker word and the mail count both survive intact
  down to **32 columns**; between 24 and 31 the pane is narrower than
  `AT PROMPT · 1 unread` and something must be cut. Below 40 the name column is doing
  most of the giving-up, which is the visible cost of this rule.

The NEEDS YOU section is untouched — Andrew wants that revisited separately.

Colour is decoration only: every distinction is also a word or a glyph, so `NO_COLOR`
loses polish and no information. Tuned for a **dark terminal only** — no palette
switch, no background detection, out of scope by the task.

## Data

Reads the live snapshot the collector publishes — `<shared .git>/agentflow/panel/
snapshot.json`, the file `switchboard/panel.py` reads — resolving the git common dir
in Python the way `panel.git_common_dir` does, and honouring `SB_PANEL_DIR`. It reads
the JSON as **plain dicts** and imports no `switchboard` module, so it runs from a
venv with no repo on `sys.path`. It never writes anything, including the `demand`
file a real renderer stamps.

With no snapshot (or an unreadable/foreign-format one) it falls back to built-in
sample data — a trimmed real `sb status` from this fleet. The footer says which was
used, e.g. `live snapshot`, `live snapshot — STALE, 12s old`, or
`sample data — no collector has published a snapshot`.

The live collector currently publishes no `display_state` key (it is running older
code than this branch's `status.py`), so the script recomputes that rule itself rather
than leaving the column blank.

## Captured frame

`--once --source sample --width 67` (67 columns is the real width of the right-hand
pane in Andrew's focused tab), `NO_COLOR=1` so it pastes as text:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 6 alive · 1 at prompt · 1 blocked · 4 unread     │
│                                                                 │
│  ● board-fix         working      2s                            │
│                                                                 │
│  ◐   researcher-22   done         3m  AT PROMPT — w… · 1 unread │
│                                                                 │
│  ○   researcher-23   done         3m  mail: 1 unread            │
│                                                                 │
│  ●   researcher-26   working     15s                            │
│                                                                 │
│  ◐   worker-25       blocked      4m  BLOCKED — which pane sho… │
│  ◌     qa-31         idle        12m  STALLED — idle… · UNDEL 2 │
│                                                                 │
│  ✗   worker-19       idle        31m  GONE — herdr has no such… │
│                                                                 │
│      + 1 archived                                               │
│                                                                 │
│  NEEDS YOU · 5                                                  │
│   researcher-22  at prompt                                      │
│   researcher-23  1 unread, not picked up                        │
│   worker-25      blocked                                        │
│   qa-31          stalled                                        │
│   worker-19      gone                                           │
│                                                                 │
│ sample data — asked for · mockup, not the board                 │
╰─────────────────────────────────────────────────────────────────╯
```

The same fleet at **40 columns** — the name column is what pays for the tail, and it
keeps its numbers rather than its shared prefix:

```
│  ● bo…fix  working                   │
│                                      │
│  ◐   …-22  done     AT P… · 1 unread │
│                                      │
│  ○   …-23  done     mail: 1 unread   │
│                                      │
│  ●   …-26  working                   │
│                                      │
│  ◐   …-25  blocked  BLOCKED — which… │
│  ◌     q…  idle     STALL… · UNDEL 2 │
│                                      │
│  ✗   …-19  idle     GONE — herdr ha… │
```

The same frame with colour on, first rows through `cat -v`, as evidence the fills are
real ANSI and not drawn characters — `1;37;44` header bar, `1;30;42` green `working`
pill, `1;30;43` yellow `done` pill:

```
^[[34m│^[[0m ^[[1;37;44m switchboard · 6 alive · 1 at prompt · 1 blocked · …^[[0m ^[[34m│^[[0m
^[[34m│^[[0m  ^[[1;32m●^[[0m board-fix        ^[[1;30;42m working ^[[0m        ^[[34m│^[[0m
```

And on real live data at 56 columns (trimmed). Note the age column is gone: a live
agent's `BLOCKED — …` reserve did not leave room for it, and the age is what this
layout gives up first:

```
╭─ switchboard ────────────────────────────────────────╮
│  switchboard · 12 alive · 1 blocked · 12 unread      │
│                                                      │
│  ○ main-3            failed                          │
│                                                      │
│  ○   split-fixer     failed    mail: 4 unread        │
│  ○     worker-1      done                            │
│                                                      │
│      + 4 archived · 1 need you                       │
│                                                      │
│  ○ main-10           failed                          │
│                                                      │
│  ◌   worker-9        working   STALLED — idle 1d03h  │
```

## Verification

- **No line ever wraps, at any width.** Every output line was measured, in display
  columns with the east-asian-width rule `board._visible_len` uses, for **widths 24
  through 120**, on both sample and live data, with colour forced on: all 97 × 2 frames
  had every line exactly the requested width. Narrowest-first the layout gives up the
  age column, then the pill's padding, then the name (to six columns), and only then
  starts cutting the marker/mail tail.
- **BLOCKED and mail survive down to 32 columns.** Checked frame by frame over the same
  24–120 sweep on the sample fleet: the `BLOCKED`/`GONE`/`AT PROMPT`/`STALLED` word and
  the mail count are both present on their rows at every width ≥ 32 (`GONE` alone holds
  to 28). Below that the pane is narrower than `AT PROMPT · 1 unread` and one of them
  has to be cut — the marker's, by `squeeze`.
- **The loop and resize work.** Run under a pty at 56 columns, resized to 100 columns
  mid-run with a `SIGWINCH`: it re-rendered at the new width immediately (the signal
  only cuts the 2-second sleep short; the width itself comes from `console.width`,
  re-read every render). `Ctrl-C` exits cleanly and restores the screen.
- Read at 40, 48, 56, 67 and 100 columns by eye, on both sample and live data.

Unproven / not done:

- Never run for a long time; no endurance testing (the bug is not endurance).
- No automated tests — it is a mockup, and pinning a mockup's pixels is the wrong
  decision to pin.
- Not tried on a light terminal, deliberately: out of scope by the task.
- Not tried under a terminal without 256-colour support (`grey35` is a 256-colour
  name; rich downgrades it, but I did not check what it looks like on a 16-colour
  TERM).

## What this would cost the real board

Reported, not fixed — I changed no product code.

1. **Reserving for the tail first inverts `_compose`.** `board._compose` fills the row
   left to right and gives the tail the remainder, with `_MAIL_RESERVE` as its one
   concession; this mockup budgets the marker+mail first and lets the name, the age and
   the pill's padding bid for what is left. That is a change to how the columns are
   measured in `layout`, not a paint job — and it means a single agent with a long
   `BLOCKED — …` costs every other row its age column.
2. **Panel borders cost 4 columns** of the width budget (2 border, 2 padding) on every
   row, which at 40 columns is most of a name.
3. **A background fill is an assertion about the terminal's background.** This mockup
   asserts one. `researcher-27`'s §3 is the argument that shipping it means either a
   two-palette switch or a decision to support dark terminals only.
4. `rich` would become a runtime dependency of a tool that currently has none.

## Rendering it into a pane

How `switchboard` itself does it: `board.open_beside` splits a pane
(`herdr.split_pane` → `herdr pane split <id> --direction right --ratio <1-share>`)
and then `herdr.prompt_pane` runs the command in the new pane — which is
`herdr pane run <pane-id> "<command>"` followed by `herdr pane send-keys <pane-id>
enter`, because `pane run` types but does not reliably submit.

Andrew's focused tab at the time of writing is `w1BM:t1` (workspace `w1BM`, cwd
`/Users/andrew/Code/switchboard`). It has two panes, from `herdr pane layout --pane
w1BM:p3`:

- `w1BM:p1` — the focused Claude session, `x=22, width=68`.
- `w1BM:p3` — `x=90, width=67, height=42`: the **right-hand** pane. `revision: 0`,
  no agent bound, `pane read` returns nothing — i.e. empty, nothing running in it.

So the command to render the mockup there is:

```
herdr pane run w1BM:p3 "exec ~/.cache/sb-board-mockup/venv/bin/python /Users/andrew/.herdr/worktrees/switchboard/worker-25/scripts/board_mockup.py"
herdr pane send-keys w1BM:p3 enter
```

That is what is running in `w1BM:p3` now — the pane was verified empty first
(`revision: 0`, no agent bound, `pane read` returned nothing), and `pane read` after
the run shows the panel drawing live fleet data at its 67-column width. No other pane
was touched.

Pane ids are not stable across a close/reopen. To re-derive the right-hand pane of
whatever tab is focused: `herdr pane layout --current` and take the pane with the
larger `rect.x`.
