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
- One line per agent: glyph, indented name, the state as a small filled **pill**
  (green `working`, yellow `done`, grey `idle`, red `blocked`/`failed`/`gone`), the
  idle age, and then the trouble marker / mail note in the tail.
- A second, **dim** line per agent: the done summary (`✓ …`), the idle excuse, or the
  task head (`↳ …`).
- Group breaks as whitespace, and archived subtrees collapsed to `+ N archived ·
  N need you` — the same rule as `status.display_rows`.
- A `NEEDS YOU` bar (black on yellow) with the agents asking for a person.
- A dim footer saying which data source the frame came from.

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
│       ↳ Await my instructions.                                  │
│                                                                 │
│  ◐   researcher-22   done         3m  AT PROMPT — waiting on y… │
│       ✓ that file does not exist on any branch — said so and s… │
│                                                                 │
│  ○   researcher-23   done         3m  mail: 1 unread            │
│       ✓ task file missing — reported it and stopped, nothing c… │
│                                                                 │
│  ●   researcher-26   working     15s                            │
│       ↳ Read notes/task-board-ui-deps.md and do exactly what i… │
│                                                                 │
│  ◐   worker-25       blocked      4m  BLOCKED — which pane sho… │
│       ↳ Build a runnable mockup of a richer board.              │
│  ◌     qa-31         idle        12m  STALLED — idle 12m        │
│       ↳ Verify the mockup at 40/56/100 columns.                 │
│                                                                 │
│  ✗   worker-19       idle        31m  GONE — herdr has no such… │
│       ↳ Old pane, herdr has no such agent.                      │
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

The same frame with colour on, first rows through `cat -v`, as evidence the fills are
real ANSI and not drawn characters — `1;37;44` header bar, `1;30;42` green `working`
pill, `1;30;43` yellow `done` pill:

```
^[[34m│^[[0m ^[[1;37;44m switchboard · 6 alive · 1 at prompt · 1 blocked · …^[[0m ^[[34m│^[[0m
^[[34m│^[[0m  ^[[1;32m●^[[0m board-fix        ^[[1;30;42m working ^[[0m^[[2m     2s^[[0m   ^[[34m│^[[0m
^[[34m│^[[0m  ^[[1;33m◐^[[0m ^[[1m  researcher-22^[[0m  ^[[1;30;43m done    ^[[0m^[[2m     3m^[[0m^[[33m  AT PROMPT …^[[0m
```

And on real live data at 56 columns (trimmed):

```
╭─ switchboard ────────────────────────────────────────╮
│  switchboard · 13 alive · 12 unread                  │
│                                                      │
│  ◌ main-15           working      1m  STALLED — idl… │
│       ↳ Await my instructions.                       │
│                                                      │
│  ◌   worker-24       working     20m  STALLED — idl… │
│       ↳ Read .switchboard/tasks/top-orchestrator-en… │
│  ●   worker-26       working      1m                 │
│       ↳ Read .switchboard/tasks/dispatcher-lead-spl… │
│                                                      │
│      + 6 archived                                    │
```

## Verification

- **No line ever wraps, at any width.** Every output line was measured, in display
  columns with the east-asian-width rule `board._visible_len` uses, for **widths 24
  through 120**, on both sample and live data, with colour forced on: all 97 × 2 frames
  had every line exactly the requested width. Narrowest-first the layout gives up the
  pill's padding, then the name column, then the tail; the age column goes last.
- **The loop and resize work.** Run under a pty at 56 columns, resized to 100 columns
  mid-run with a `SIGWINCH`: it re-rendered at the new width immediately (the signal
  only cuts the 2-second sleep short; the width itself comes from `console.width`,
  re-read every render). `Ctrl-C` exits cleanly and restores the screen.
- Read at 40, 56, 67 and 100 columns by eye. At 40 the trouble markers drop off the
  row tail — they are still in NEEDS YOU, which is the point of that section.

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

1. **The second dim line per agent.** `board.layout` charges one screen line per agent
   and `_starts_group`/`_max_top` count in those lines, so a two-line row means
   `costs` becomes 2 (or 3 with a break) per agent and the scroll maths follows. The
   click mapping itself is fine: `emit` records the owner per *line*, so both lines
   would just carry the same agent.
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
