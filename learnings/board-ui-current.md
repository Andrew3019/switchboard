# The board UI, as it exists today

Research only, grounded in the code as of `main` @ `b3ec755` (worktree `researcher-24`).
Checked against the code directly; README/DESIGN-TRUTH claims are marked where used
without independent verification.

## 1. There are TWO renderers of one snapshot, not one

`switchboard/status.py`'s `AgentStatus`/`Snapshot` dataclasses are the one shared model.
Two separate functions draw them, with genuinely different visual vocabularies:

- **`switchboard/board.py`: `layout()`** — the interactive TUI (`sb board`, hidden from
  `--help`, human-only). ANSI colour, a glyph per row, one line per agent, tree-indented,
  mouse-clickable.
- **`switchboard/status.py`: `render()`** — the plain-text table (`sb status`, agent-facing,
  and whatever is piped/captured). No colour, no glyphs, fixed columns, two lines per agent
  (identity row + a `↳ task` / `✓ summary` line).

Both read `Snapshot`/`AgentStatus`; neither imports the other's drawing code.

### Data flow, end to end (the live/interactive path)

1. `switchboard/collector.py` is a single elected process (`flock` on `panel/collector.lock`,
   in `panel.py`) that calls `status.collect()` — one `herdr agent list` call plus one pass
   over the SQLite store — every `display.board_refresh` seconds (2.0s, `defaults/settings.toml`
   line 397), and `panel.publish()`s the resulting `Snapshot.as_dict()` (i.e. `sb status --json`
   verbatim) atomically to `panel/snapshot.json` under the repo's shared `.git`.
2. Every `sb board` pane is a separate OS process running `switchboard/board.py:main()`. It
   never imports `store` (a real invariant, statically and dynamically checked by
   `tests/test_panel.py::RendererImports` — the board file's own docstring stresses this at
   length, after two incidents where the board previously mutated the store it was supposed
   to be read-only over). Each tick: `panel.Supervisor.tick()` starts a collector if the lock
   is free (takeover), stamps `panel/demand` (mtime = "a renderer is still looking", the
   collector's only reason to keep running), then reads `panel/snapshot.json`
   (`panel.read()`), turning the JSON back into a `Snapshot`.
3. `board.layout()` turns that `Snapshot` into `(text, owning_agent_or_None)` pairs — one per
   screen line. `board.draw()` clears the screen (`\033[H\033[2J`) and writes them.
4. The loop (`board.main()`) is `select()` on stdin with a 0.25s timeout: it redraws whenever
   (a) that 0.25s poll saw input (a keypress or an SGR mouse event) or a resize signal
   (`SIGWINCH`) set a `dirty` flag, or (b) `REFRESH` (2.0s, same `display.board_refresh`
   setting) has elapsed since the last re-read of the snapshot file. So input is handled at
   up to 4Hz; the underlying data only actually changes at the collector's ~2s cadence.
5. `sb status` (`switchboard/status.py` via `cli.py`) is a one-shot: it calls `status.collect()`
   itself (not through the panel/collector — it talks to herdr and the store directly, and its
   own `reap=True` call is what performs the "agent went missing" / "turn edge went stale"
   write-backs described in `status.py`'s big docstring), then `status.render()`s the result to
   stdout and exits. It is not part of the panel mechanism at all.

## 2. Where the board is displayed

- **A tmux/herdr pane, always beside another pane, never standalone.** `board.open_beside()`
  is called from `broker._open_board`, reached by every `sb delegate` and by `sb start` — so
  every agent spawn splits a pane and runs `python3 -m switchboard.board` in the new one
  (launched by module path, not by `sb board`, specifically so it doesn't depend on `sb`
  being on PATH in that pane and can't trip the human-only gate). `BOARD_SHARE = 0.34` (a
  child's board takes 34% of the split); `TOP_BOARD_SHARE = 0.45` for the top orchestrator's
  own board (opened by `sb start`), which is meant to be the board a human actually reads.
  Herdr's own `--ratio` flag is inverted from this (`ratio=1-share`) since herdr's ratio is
  "what the pane being split keeps."
- It refuses to run outside a real terminal: `board.main()`'s first check is
  `sys.stdin.isatty()`; if not a tty, it prints an error to stderr and exits 2. It is a
  genuine raw-mode terminal program: `tty.setraw()`, SGR mouse tracking turned on
  (`\033[?1000h\033[?1006h`), cursor hidden, and it restores all of that (`termios`, mouse off,
  cursor shown) on exit, SIGINT, SIGTERM, SIGHUP.
- It is **not** driven by tmux capture-pane polling — it's a normal foreground TUI process
  sitting in its own pane, reading a file that a separate collector process writes, and
  writing directly to its own stdout. The "tmux" part is only that herdr is what opens/sizes
  the pane it runs in (`h.split_pane`, `h.prompt_pane`).
- `sb status` (the plain-text one) has no notion of a pane at all — it's a normal CLI command,
  writes to stdout, and is exactly what would be seen if piped or run non-interactively
  (confirmed: `status.render()` never calls `sys.stdin.isatty()` or checks `NO_COLOR`, and
  emits no ANSI codes anywhere — grepped, no color codes appear in `status.py`).

### Refresh mechanism and rate, precisely

- Redraw = full clear + full repaint (`"\033[H\033[2J"` then the whole frame), not a diff/patch
  — see `board.draw()`.
- Underlying data refresh: `display.board_refresh = 2.0` seconds (`defaults/settings.toml`
  line 397), which is *both* how often the one collector re-polls herdr+store *and* how often
  each panel re-reads the published file. `panel.STALE_AFTER = 5.0`s is when a panel starts
  saying "snapshot Ns old" instead of trusting it; `panel.collector_idle_exit = 60.0`s is how
  long the collector keeps running after the last panel stopped asking for it (`demand`
  mtime); `panel.spawn_cooldown = 5.0`s throttles how often a renderer will attempt to spawn a
  replacement collector.
- Input responsiveness: independent of the above, polled via `select(..., timeout=0.25)`, so
  clicks/keys/resizes feel instant even though the tree itself only updates every ~2s.
- On resize: `SIGWINCH` just sets `dirty=True`; the next loop iteration calls `os.get_terminal_size()`
  fresh (`board._size()`) and re-lays-out at the new width/height — no debounce, no special
  case beyond a full redraw at the new dimensions.

## 3. Current visual vocabulary

### Colour

- **ANSI 16-colour SGR codes only** (`\033[{code}m...\033[0m`), via `board._c()`. Codes used:
  `DIM="2"`, `RED="31"`, `YELLOW="33"`, `GREEN="32"`, `BLUE="34"`. No 256-colour, no
  truecolor, anywhere in `board.py` (grepped for `\033[38` / `48;5` / `48;2` — none found).
- Colour is explicitly "never load-bearing": `_COLOR = os.environ.get("NO_COLOR") is None`
  gates all of it, and every colour distinction is also carried by a glyph or a word (module
  docstring: "so NO_COLOR loses nothing but polish").
- `status.render()` (the plain-text `sb status` table) uses **no colour at all** — no `\033[`
  sequences anywhere in that file.

### Glyphs / box drawing / unicode

- One glyph per row, priority order (`board.glyph()`): `✗` gone (red) > `◐` at-prompt/blocked
  (yellow) > `◌` stalled/signal-drift (yellow) > `○` finished (dim) > `?` unknown-alive (dim)
  > `●` otherwise/working (green).
- `←` arrow prefixes the trailing "detail" text when the row wants attention or leads with
  mail; two spaces otherwise (keeps column alignment).
- Tree indentation: two spaces per depth level (`"  " * a.depth`), prepended to the name — no
  box-drawing characters (no `├─`, `└─`, `│`) anywhere; it's pure indentation, not a drawn
  tree.
- No box borders/frames around the whole board — it's a flat scrolling list of lines, a blank
  line (`_BREAK = ""`) between top-level groups (deliberately *not* a horizontal rule — the
  module comment explains a full-width rule at 60 columns would dominate the eye over the
  indentation, "and depth is the thing this view is for").
- `status.render()`'s plain table instead uses ASCII: fixed-width padded columns
  (`AGENT  ROLE  STATE  HERDR  MAIL  AGE  IDLE  WORKSPACE`), `↳` for the task line, `✓` for a
  finished agent's summary line, `<<` (not an arrow glyph) prefixing flags like `<< STALLED`,
  `<< GONE`, `<< AT PROMPT`, `<< UNDELIVERED n, age`. Collapsed/archived rows are `+ N archived`
  (optionally `· M need you`).

### Real example output, captured live from this repo (`./bin/sb status`, run 2026-08-14)

```
AGENT            ROLE          STATE     HERDR    MAIL     AGE    IDLE  WORKSPACE
board-fix        orchestrator  working   working     -     45m     36s  board-fix
    ↳ Await my instructions.
  researcher-22  researcher    done      blocked     1      2m      0s  researcher-22  << AT PROMPT
      ↳ Read notes/task-board-ui-current.md and do exactly what it says.
      ✓ Task said to read notes/task-board-ui-current.md and do exactly what it says, but that file doe…
  researcher-24  researcher    working   working     -      1m      1m  researcher-24
      ↳ Read the file at absolute path /Users/andrew/Code/switchboard/notes/task-board-ui-current.md (i…

5 alive · 1 at a prompt · 2 unread · 5 agents · 344 hidden

NEEDS YOU
  researcher-22  waiting at a prompt in its own TUI  →  sb inspect researcher-22
  researcher-23  1 unread, not picked up  →  sb inspect researcher-23
```

I could not capture a live `sb board` frame (it requires a real tty and refuses to run
without one — confirmed by reading `board.main()`'s `isatty()` check; I did not attempt a
pty harness). Constructed from `board.layout()`'s own logic and pinned by
`tests/test_board.py` instead, a board row for a stalled agent reads approximately (colour
stripped):

```
 ◌ researcher-22        idle       2m   ← STALLED — idle 2m · fix the parser
```

and for a healthy one:

```
 ● researcher-24        working    1m     Read the file at absolute path /Users/andrew...
```

(glyph, then `name` padded to the widest name column, then `display_state` padded to the
widest state column, then right-aligned idle age, then — if room remains — up to one
"detail" piece chosen by priority: marker > mail > task, see `board.detail_bits()` /
`board._compose()`.)

## 4. Hard constraints a redesign must respect

- **No line may ever wrap.** This is stated as "the one invariant this view rests on" in
  `board.layout()`'s own docstring: a wrapped line pushes every row below it down by one, and
  the next click focuses the wrong agent — silently, looking exactly like a correct click.
  This is not hypothetical: DESIGN-TRUTH.md records it as an actual bug Andrew hit ("the
  evidenced cause is that board rows are measured in characters rather than terminal columns,
  so one wide character — an emoji, CJK — wraps a row and every row below it is off by one").
  The current fix is `board._visible_len()`/`_clip_cols()`/`_fit()`, a hand-rolled
  East-Asian-width-aware, ANSI-aware, grapheme-cluster-aware column counter (handles ZWJ
  sequences, variation selectors, regional-indicator flag pairs, combining marks, skin-tone
  modifiers) with no `wcwidth` dependency. Any redesign that changes what's drawn must keep
  measuring in *terminal columns*, not characters or code points.
- **Width and height are read fresh every frame** via `os.get_terminal_size()`
  (`board._size()`), with a hardcoded fallback of `24, 80` if that raises `OSError`. There is
  no minimum-width guarantee beyond that fallback; `CHROME = 4` (header + 2 blanks + footer,
  per `defaults/settings.toml`) is reserved off the top, and DESIGN-TRUTH explicitly notes the
  board's default pane is narrow (34% width split) and past bugs were width-related.
- **One renderer must NOT serve both surfaces as-is** — they already don't: `board.layout()`
  (colour, glyph, single-line, mouse-click-mapped) and `status.render()` (plain, columnar,
  two-line, no color) are separately maintained today, both against the same `Snapshot`
  model. A redesign has to decide whether to keep that split or unify it; either way, the
  contract that both draw from is `status.Snapshot`/`AgentStatus`, and `status.display_rows()`
  is explicitly the single shared tree/collapse logic used by both today ("ONE function for
  every renderer... a tree rule written twice is a tree rule that ends up disagreeing with
  itself").
- **`sb status` output is genuinely piped/captured non-interactively.** It never checks
  `isatty()`, never emits ANSI, and is what agents themselves read (it's their view of the
  tree; `sb board` is explicitly human-only and refuses any caller `whoami()` resolves to an
  agent — DESIGN-TRUTH: "`sb status` is for agents; `sb board` is Andrew's view of the tree").
  So `sb status`'s output has to keep being plain-text-safe for logs, agent transcripts, and
  scripts — colour/glyphs there are optional decoration at most, never load-bearing.
- **`sb board` is human-only and hidden from `--help`.** It refuses any agent caller. Its
  contract is narrower — it's read by a human sitting at one terminal at a time, in a pane
  herdr sized, with mouse support.
- **tmux/herdr quirks:** the board's only side effect is `herdr agent focus <name>` (invoked
  from a left-click, via `board.focus()`), which shells out to the `herdr` binary and is
  itself defensive (missing binary, timeout, nonzero exit all degrade to a status-bar message
  rather than a crash). Splitting/creating the pane (`open_beside`) also degrades to `None`
  (no board opened) rather than failing the spawn it's attached to, on any herdr/OSError.
  `SIGWINCH`-driven resize (see above) is the only tmux-adjacent redraw trigger; there is no
  tmux `capture-pane` polling anywhere in this code path.
- **On resize:** handled (see §2) — full relayout at new dimensions, no known bug filed
  against it in the files I read, but also no test I found that specifically pins resize
  behavior (I did not exhaustively search the whole test suite for this — a targeted grep for
  "resize"/"WINCH" in tests would confirm one way or the other; I did not do that grep).
- **DESIGN-TRUTH.md is explicit that `sb board`'s current behavior is meant to be stable for
  now**: "`sb board` stays as it is right now. It shows the full tree with its nest
  structure; an archived agent shows collapsed... That is all it needs for now; the rest of
  what it has works fine and auditing it comes later." (confirmed 2026-08-09). Any redesign
  proposal should be read against that — it's the only trusted document per this task's own
  instructions, and it currently records the click-focus behavior and collapse-on-archive as
  settled, not as things to unsettle.

## 5. Dependencies

- **No `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements*.txt`, `Pipfile`, or
  `poetry.lock` exists anywhere in this repo** (checked with `find`). There is no Python
  packaging metadata at all — `bin/sb` runs by putting the checkout directly on `sys.path`
  (`sys.path.insert(0, ...)` then `from switchboard.cli import main`) rather than through an
  installed package.
- Grepping every `import`/`from` line across `switchboard/*.py` turns up **only the standard
  library**: `argparse, contextlib, dataclasses, datetime, difflib, fcntl, hashlib,
  importlib.util, inspect, json, os, pathlib, re, select, shlex, shutil, signal, sqlite3,
  subprocess, sys, termios, threading, time, tomllib, traceback, tty, typing, unicodedata,
  urllib.parse` (plus internal `switchboard.*` / `.` relative imports) — no third-party
  package anywhere.
- README.md states this is deliberate: "About sixteen thousand lines of Python, standard
  library only — no third-party runtime dependency. `tomllib` and `sqlite3` do the work a
  config parser and a database would otherwise be pulled in for." (README is not the trusted
  document per this task's instructions, but this claim matches what I independently found by
  grepping every import in the package, so I'm reporting it as verified against the code, not
  taken on the README's word alone.)
- Concretely for a redesign: the East-Asian-width/ANSI-aware column measurement in
  `board.py` (`_clusters`, `_visible_len`, `_clip_cols`) is hand-rolled specifically to avoid
  a `wcwidth` dependency (stated in its own docstring). That's the clearest existing signal of
  the project's bar for pulling in *any* third-party dependency — it did the harder thing
  instead. I'd treat "no third-party dependencies" as a real constraint unless told otherwise
  by whoever owns DESIGN-TRUTH.md (Andrew) — I did not find anything in DESIGN-TRUTH.md itself
  that states the stdlib-only rule explicitly; that constraint currently rests on the code and
  README only, not on the one trusted document.

## What I did not check

- Did not run `sb board` in an actual pty (no live frame capture) — description of its output
  is derived from reading `layout()`'s logic plus what `tests/test_board.py` pins, not from
  observing pixels.
- Did not grep the full test suite for resize-specific tests.
- Did not read `switchboard/collector.py` line-by-line (read `panel.py`'s account of it,
  which is the module that documents the collector/renderer split in most detail); the data-
  flow description above is accurate as far as `panel.py` and `board.py` describe it, but I
  did not independently verify collector.py's internals.
- `switchboard/status.py` is 2055 lines; I read roughly the first half plus the render/layout
  section in full (through `_attention`, ~line 1740) and did not read `Detail`/`inspect`/
  `render_detail` (the `sb inspect` single-agent view, lines ~1871–2055) — not needed for this
  task, which is about the board/status tree view, not the single-agent inspector.
