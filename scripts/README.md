# Pre-PoC smoke scripts

Before building the PoC, prove the herdr flow by hand. Basic bash, no abstractions —
the point is to find out where it actually breaks.

Run in order. Each prints what it's doing and what it expects.

| Script | Proves |
|---|---|
| `00-preflight.sh` | herdr is present, right version, server up, integrations installed. Read-only, free. |
| `01-spawn.sh` | We can build a run's scaffolding **from a script**: worktree → workspace → pane → agent. Costs nothing until the agent is prompted. |
| `02-state.sh` | **The load-bearing one.** Our reported state beats herdr's detector and sticks. |
| `03-talk.sh` | Doorbell + mailbox: agent A pokes agent B, B responds. Two live agents — **this one costs tokens.** |
| `05-mouse.py` | Does a herdr pane forward **mouse clicks** to a TUI at all? Prints every event decoded and raw. Nothing on click = the clickable board dies here. |
| `06-board.py` | Clickable agent tree: real agents from the store, redrawn every 2s, click a row → `herdr agent focus`. Human-only surface — no agent runs this, and it never becomes an `sb` verb. |
| `wf-shim.sh` | The throwaway `wf` used to validate the verb surface before any of it existed: files instead of SQLite, four rounds against real agents. Findings 14–19 in `POC.md` came out of it. Superseded by `sb`; kept as the record. |

## Notes

- `02` is the one that decides whether M2 is trustworthy. If our `blocked` gets flipped
  back to `working` by the detector, the design needs rethinking.
- `03` is the actual PoC in miniature — if it works with files as the mailbox, the real
  version is the same thing with SQLite.
- `05` is the only question `06` depends on. Run it first — if clicks never arrive, `06`
  is a pretty list you can only quit.
- **Both answered yes**, so `06` is superseded by `switchboard/board.py` — the real one,
  run with `python3 -m switchboard.board` in a pane. Nothing opens it for you; an earlier
  version of this line said `sb start` did, and that was never true. These two stay only
  as the record of what was actually proven about herdr and the mouse.
- `05`/`06` are Python because raw mode and mouse decoding in bash is not basic, it's a
  stunt. Stdlib only, and the terminal machinery is **duplicated** between them on purpose.
- There is no `04-cleanup.sh`; it was never written. Close leftover panes from `01`/`03`
  with `sb cleanup <name> --force`, which is the verb that grew out of needing it.
- **Nothing here is the product.** It's a probe. Delete it once M2 exists.
