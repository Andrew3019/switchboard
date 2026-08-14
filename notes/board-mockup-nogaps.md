# Board mockup: no blank lines

`scripts/board_mockup.py`, on branch `worker-28` (based on `worker-25`, commit `0305804`).
Still a spike — nothing imports it, no product code touched.

## What changed

Four blank lines removed, all of them. Nothing put in their place — no rule, no
separator, no extra padding:

1. **The group break between agents.** `render` used to emit a blank line above every
   row at depth ≤ 1, i.e. above each top-level agent and each of its direct children.
   With one-line rows that was an empty line between nearly every pair of agents. Gone;
   the loop is now a plain `for row in rows` with no gap logic at all.
2. **Under the header bar.**
3. **Above the NEEDS YOU bar.**
4. **Above the footer line.**

Nothing was kept back. The filled header bar, the filled NEEDS YOU bar and the rounded
panel border carry all the separation, and the tree indentation carries the structure.

Everything else is untouched: one line per agent, rounded panel, filled header, state
pills, dark terminal only, and the tail budget that keeps BLOCKED and MAIL from being
what gets clipped.

## How to run it

```
~/.cache/sb-board-mockup/venv/bin/python \
  /Users/andrew/.herdr/worktrees/switchboard/worker-28/scripts/board_mockup.py
```

Add `--once` for a single frame, `--width N` to force a pane width, `--source sample`
for the built-in fixture.

## Verification

Real fleet data (the live collector snapshot), rendered at 67 columns. No blank line
between any two agent rows, and none anywhere else inside the panel:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 14 alive · 1 blocked · 13 unread                 │
│  ○ main-3            failed    5d10h                            │
│  ○   split-fixer     failed    4d09h  mail: 4 unread            │
│  ○     worker-1      done      5d13h                            │
│      + 4 archived · 1 need you                                  │
│  ○ main-10           failed     1h40                            │
│  ◌   worker-9        working   1d03h  STALLED — idle 1d03h      │
│  ○   reviewer-14     done      15h01                            │
│      + 10 archived                                              │
│  ○ main-11           done       1h38                            │
│      + 10 archived                                              │
│  ◌ main-15           working      2m  STALLED — idle 2m         │
│  ◌   worker-24       working     47m  STALLED — idl… · 1 unread │
│  ◌   researcher-20   working     47m  STALLED — idl… · 1 unread │
│  ○   worker-26       done         7m                            │
│  ●   worker-27       working      2m                            │
│      + 7 archived                                               │
│  ◌ board-fix         working      1m  STALLED — idle 1m         │
│  ○   researcher-22   done        53m  mail: 1 unread            │
│  ○   researcher-23   done        18m  mail: 1 unread            │
│  ◐   worker-25       blocked      3m  BLOCKED — clos… · UNDEL 1 │
│  ●   worker-28       working      1m                            │
│      + 5 archived                                               │
│    + 305 archived · 3 need you                                  │
│  NEEDS YOU · 13                                                 │
│   fix-options-2   1 unread, not picked up                       │
│   split-fixer     4 unread, not picked up                       │
│   board-teardown  1 unread, not picked up                       │
│   repo-rules      1 unread, not picked up                       │
│   main-6          1 unread, not picked up                       │
│   worker-9        stalled                                       │
│   + 7 more                                                      │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

The same fleet at 40 columns — still one line per agent, still no wrap:

```
╭─ switchboard ────────────────────────╮
│  switchboard · 14 alive · 1 blocked… │
│  ○ main-3  failed                    │
│  ○   …xer  failed   mail: 4 unread   │
│  ○     w…  done                      │
│      + 4 archived · 1 need you       │
│  ○ ma…-10  failed                    │
│  ◌   …r-9  working  STALLED — idle … │
│  ○   …-14  done                      │
│      + 10 archived                   │
│  ○ ma…-11  done                      │
│      + 10 archived                   │
│  ◌ ma…-15  working  STALLED — idle … │
│  ◌   …-24  working  STAL… · 1 unread │
│  ◌   …-20  working  STAL… · 1 unread │
│  ○   …-26  done                      │
│  ●   …-27  working                   │
│      + 7 archived                    │
│  ◌ bo…fix  working  STALLED — idle … │
│  ○   …-22  done     mail: 1 unread   │
│  ○   …-23  done     mail: 1 unread   │
│  ◐   …-25  blocked  BLOCK… · UNDEL 1 │
│  ●   …-28  working                   │
│      + 5 archived                    │
│    + 305 archived · 3 need you       │
│  NEEDS YOU · 13                      │
│   fix-options-2   1 unread, not pic… │
│   split-fixer     4 unread, not pic… │
│   board-teardown  1 unread, not pic… │
│   repo-rules      1 unread, not pic… │
│   main-6          1 unread, not pic… │
│   worker-9        stalled            │
│   + 7 more                           │
│ live snapshot · mockup, not the boa… │
╰──────────────────────────────────────╯
```

Checked programmatically at 40, 56, 67 and 100 columns over the live snapshot, measuring
display columns the way the script's own `vlen` does: every line is exactly the requested
width (so nothing wraps at any of them), and no line inside the panel is empty.

Not proven: only the live snapshot and the built-in sample were rendered. Fleet shapes
those two do not contain — a very deep tree, a name far longer than any here — were not
exercised, and nothing here was checked in a real terminal; the frames above are piped
output with `NO_COLOR` set.
