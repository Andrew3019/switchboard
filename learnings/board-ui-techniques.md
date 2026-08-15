# Terminal rendering techniques for a visually richer board

Researched at Andrew's request (task in `notes/task-board-ui-techniques.md`, written by
`board-fix`). Research only — no product code changed.

## 0. What the current board actually does (context for everything below)

Read `switchboard/board.py` before anything else, because it fixes several constraints that
any recommendation has to respect:

- **Zero external dependencies today.** There is no `pyproject.toml`, `setup.py`, or
  `requirements.txt` in the repo — the whole CLI, including the board, is stdlib only
  (`os`, `re`, `select`, `signal`, `subprocess`, `termios`, `tty`, `unicodedata`). Any
  library option below is *the first third-party dependency switchboard would ever take*,
  not an addition to an existing pile.
- **It's a redraw-in-place loop, not a widget tree.** `main()` sets raw mode, hides the
  cursor, and on every tick calls `draw()`, which clears the screen (`\033[H\033[2J`) and
  writes one big string. There's no persistent widget state to diff against — `layout()`
  is a pure function from a snapshot to a list of `(text, owner)` lines.
- **It already hand-rolls mouse input.** `parse_sgr` decodes SGR mouse sequences
  (`\033[?1000h\033[?1006h`) itself, including click-to-focus and wheel-to-scroll. Any
  library brought in either has to support this same interaction model (click a row, focus
  an agent) or this input layer stays hand-rolled underneath/alongside it.
- **It already hand-rolls column-accurate width.** `_clusters`/`_visible_len`/`_clip_cols`
  implement East-Asian width, ZWJ sequences, variation selectors, and regional-indicator
  (flag) pairs from `unicodedata` alone, specifically to avoid a `wcwidth` dependency and to
  guarantee no line ever wraps (the docstring on `layout` calls this "the one invariant this
  view rests on" — a wrapped line desyncs the click-to-agent mapping). Any adopted library's
  own width handling would need to match or beat this, and a mismatch is a correctness bug
  (misclicks), not a cosmetic one.
- **`NO_COLOR` is already respected**, and every color distinction is described as "never
  load-bearing" — always backed by a glyph or word too. That's a design invariant worth
  preserving regardless of technique.
- **The screen is a *human-only* side panel** opened by `herdr` next to an agent's own pane,
  usually well under half the terminal width (`BOARD_SHARE = 0.34`, `TOP_BOARD_SHARE =
  0.45`). It is read continuously by a human sitting next to their own shell, not launched as
  a standalone full-screen app the way `k9s` or `lazygit` is. This matters for the
  "how much room do you actually have" question in every layout decision below.

## 1. Library options

### `rich` (Textualize)

- Gives you: `Panel` (bordered box with title, several built-in box-drawing styles including
  `ROUNDED`, `HEAVY`, `DOUBLE`), `Table` (borders, per-cell/row background via `Style`),
  `Layout` (splits a screen into regions), truecolor/256/16-color styling with automatic
  downgrading, and `Live` for redraw-in-place rendering (renders a renderable repeatedly,
  diffing at the terminal level, without needing an event loop).
- Suits switchboard's model well on paper: `Live` is exactly "repeatedly render a snapshot
  to the same screen region," which is what `draw()` already does by hand. You could build
  a `Panel`/`Table` from `layout()`'s output and hand it to `Live` instead of writing raw
  ANSI + `\r\n`.
- Terminal/TTY behavior: Rich auto-detects `isatty()` on the output file and strips control
  codes when not writing to a terminal (so piping the board's stdout degrades to plain
  text automatically); this can be overridden via `force_terminal` or the `TTY_COMPATIBLE`
  / `TTY_INTERACTIVE` env vars. That auto-degrade is a feature the board would want anyway.
- Dependency weight: two required deps, `pygments` (syntax highlighting) and `markdown-it-py`
  (Markdown rendering) — both unused by anything board-shaped, but pulled in regardless.
  There's an open, unresolved GitHub issue (Textualize/rich#2277) asking for a "minimal"
  Rich without them, which tells you this is a known complaint, not a solved problem.
- Mouse input: Rich has no first-party SGR mouse decoding of its own; `board.py`'s
  `parse_sgr`/click-to-focus logic would stay exactly as hand-rolled as it is today, with
  Rich only replacing how the frame is drawn.
- I did not verify Rich's own column-width handling (`Segment`/`cell_len`) against
  switchboard's `_clusters` for the exact edge cases here (ZWJ family emoji, regional-
  indicator flags) — that would need to be checked line-by-line before trusting it over the
  existing implementation, not assumed compatible.

### `textual` (Textualize)

- Gives you: a full component model (App + Widgets), CSS-like stylesheets, an async event
  loop, reactive state, built-in mouse support (including click and scroll), and widgets
  like `DataTable` and `Tree` that are close in shape to a scrollable agent list.
- It is explicitly the "I want an interactive app," not "I want to print prettier text"
  tool — Textualize's own framing is that Rich is for formatted output and Textual is for
  apps with structure, events, and an async runtime. That's a much bigger shift than the
  redraw-in-place loop the board uses now: adopting Textual means rewriting `main()`'s
  select-loop-and-redraw as a Textual `App` with its own event loop, replacing the hand-
  rolled SGR parsing with Textual's mouse events, and probably replacing the pure
  `layout()` function with widget state that has to be *updated* rather than *rebuilt from
  a snapshot* each tick (or reconciled with Textual's own diffing).
- Depends on Rich, so it inherits Rich's dependency set plus its own (`typing-extensions`,
  `platformdirs`, etc.) — heavier than Rich alone.
- Piped/non-tty behavior: Textual apps generally assume a real terminal to attach to (they
  take over the whole screen via the alternate buffer); running one with stdout redirected
  is not really the failure mode the board hits today (`main()` already checks
  `sys.stdin.isatty()` and exits with an error), so this is less of a concern than for a
  library meant to also work non-interactively — but it does mean Textual is aimed
  squarely at "the whole pane is this app," which matches the board's real usage
  (`open_beside` launches it as `python3 -m switchboard.board` filling its own tmux pane) more
  than it might first appear despite being heavier machinery than needed.

### `blessed`

- A thin, elegant wrapper over `curses`/terminfo: styling as chainable attributes
  (`term.bold_red('x')`), cursor positioning (`term.location()`), terminal capability
  queries (`term.number_of_colors`), and a `term.fullscreen()` context manager for
  alternate-screen apps — but it is explicitly positioned (including by its own
  maintainers, per community discussion) as best for **non-fullscreen** terminal output,
  not a widget/layout system. No panels, no tables, no background-fill boxes built in — you
  would still hand-build every box character and background span, just with less manual
  ANSI-code bookkeeping than today (`term.on_color_rgb(r,g,b)` instead of writing
  `\033[48;2;r;g;bm` by hand) and with terminfo-driven fallback for missing capabilities.
- Very light dependency footprint (`wcwidth`, `six`-era holdovers depending on version) —
  much lighter than Rich or Textual.
- Not a redraw-in-place framework by itself; it gives primitives, and the existing
  clear-and-redraw loop in `draw()` would stay almost exactly as structured.
- No built-in SGR mouse decoding matching this project's click-to-focus needs, as far as I
  found — `parse_sgr` would stay hand-rolled either way.

### `urwid`

- A real widget library (`ListBox`, `Frame`, `LineBox`, `AttrMap` for per-widget
  background/foreground) with its own screen/event loop, built specifically for Python
  (unlike `curses`, which wraps a C library). It supports mouse events, palettes with
  16/256/truecolor-ish handling, and box-drawing borders out of the box.
- Like Textual, it wants to own the event loop and redraw cycle — adopting it is a
  structural rewrite of `main()`, not a drop-in replacement for the ANSI string `draw()`
  currently emits. It's older and less actively developed than Textual, with a smaller
  community pushing it forward now that Textual exists as the modern alternative covering
  similar ground.

### `prompt_toolkit`
- Built for building CLI/REPL input experiences (readline replacement, autocompletion,
  Emacs/Vi keybindings) with only `pygments` and `wcwidth` as dependencies, and it does have
  a full-screen `Application`/layout system (`HSplit`/`VSplit`, `Window`, styled text) capable
  of building a boxed, colored screen. But its center of gravity is text input and editing,
  not read-only dashboards — using it for the board would mean adopting an input-focused
  framework for a view that has no text entry at all. I'd rank it below Rich/Textual/blessed
  for this specific job; noting it mainly because the task asked for it explicitly.

### Hand-rolled ANSI (status quo)
- What `board.py` already does. Zero dependencies, exact control over every byte written,
  already has working mouse decoding and width-safe clipping tuned to this exact use case.
  The cost is that every visual improvement (a bordered panel, a background-highlighted row)
  has to be written and tested by hand against the same edge cases (`NO_COLOR`, narrow
  panes, emoji width) the current code already carefully handles for the plain-text case.

## 2. Raw ANSI techniques (usable with zero library, i.e. what's actually available to
   extend the current hand-rolled approach)

- **Background colours.**
  - 16-color: `\033[4{0-7}m` (standard) / `\033[10{0-7}m` (bright). Universally supported,
    including on genuinely old terminals.
  - 256-color: `\033[48;5;{0-255}m`. Widely supported (most terminals since the mid-2000s,
    including default `xterm-256color`).
  - Truecolor (24-bit): `\033[48;2;{r};{g};{b}m`. Supported by most modern terminal
    emulators (iTerm2, Konsole, VTE-based terminals like GNOME Terminal/Terminator/Alacritty,
    Windows Terminal), but not universally, and detection is heuristic: check
    `COLORTERM` for `truecolor`/`24bit` as the positive signal, and fall back to the
    `*-256color` suffix on `$TERM` as a floor when `COLORTERM` is unset. There's no single
    universal terminfo capability that guarantees this — `tmux` itself needs its
    `terminal-overrides`/`Tc`/`RGB` terminfo entry set correctly to pass truecolor through
    from the terminal it's running in, which is a real, common failure mode (truecolor
    working in a bare terminal but degrading inside tmux until configured).
  - Given board.py's existing philosophy (colour is decoration, never load-bearing, and
    respects `NO_COLOR`), 256-color backgrounds are probably the safe ceiling to design
    against, with truecolor as a nice-to-have behind a capability check, not a requirement.
- **Box-drawing / rounded corners.** Unicode's Box Drawing block (U+2500–U+257F) has
  single/double/heavy line variants and dedicated rounded-corner glyphs (`╭ ╮ ╰ ╯`,
  U+256D–U+2570) distinct from the sharp-corner set (`┌ ┐ └ ┘`). These are extremely widely
  supported in monospace terminal fonts today (they're what Rich's own `ROUNDED` box style
  draws), so a hand-rolled "panel" border is a small, self-contained addition — a handful of
  constant strings plus corner/edge logic, not a new subsystem.
- **Half-block / eighth-block characters.** The Block Elements range (U+2580–U+259F)
  includes half blocks (▀ ▄ ▌ ▐) and finer eighth-step blocks, useful for sub-cell-resolution
  bars (e.g., a denser progress/sparkline than one full glyph per cell) by pairing a
  background colour on one half of a cell with a foreground block character. Not obviously
  needed for a status board of rows and columns of text, but relevant if "richer" ever means
  a small utilization graph or progress bar rather than borders/panels.
- **Dim/bold/reverse video.** Already in use (`DIM`, and `_c` for bold/etc. via SGR codes);
  reverse video (`\033[7m`) is a cheap way to render a "selected/highlighted row" without
  needing to know the terminal's actual background colour at all — it just swaps whatever
  foreground/background the terminal already has, so it degrades gracefully on any terminal
  including 16-color-only ones and doesn't fight light vs. dark themes.
- **Degradation on poor terminals.** A terminal with no colour support at all (rare today,
  but `TERM=dumb` exists) or a `NO_COLOR`-respecting run should fall back to what board.py
  already guarantees: every colour is decorative, glyphs and words carry the actual meaning.
  The same principle extends cleanly to borders/backgrounds — a panel border can be omitted
  entirely without changing what any row says, so a "no truecolor / no box-drawing" fallback
  is "draw what you draw today," which is a genuinely free win of the current design.

## 3. Constraints that bite in practice

- **No truecolor support.** Real, not hypothetical — plenty of remote/serial/older
  terminals and some default configs only advertise 256 or 16 colors. Detection has to be
  a heuristic (`COLORTERM` then `TERM` suffix), never assumed.
- **tmux colour passthrough.** Since `open_beside()` launches the board inside a `herdr`-
  managed pane (almost certainly tmux under the hood, given the split/pane vocabulary),
  truecolor specifically needs tmux's own terminfo/`Tc` capability wired up correctly, or
  24-bit backgrounds silently degrade even though the outer terminal supports them. This is
  the single most likely real-world "why doesn't my nice background colour show up" bug
  report for this project specifically, given how the board is actually launched.
- **Light vs. dark terminal themes.** A background colour picked to look good on a dark
  theme (e.g., a muted dark blue panel fill) can be low-contrast or ugly on a light theme,
  and vice versa. board.py currently sidesteps this entirely by never setting a
  background — only foreground colour and reverse video are used. Any move to
  background-filled panels/rows reopens this problem and needs either a small conservative
  palette (a few colours that read acceptably on both), reverse video instead of a fixed
  background (inherits the user's own contrast), or a config knob, rather than one hardcoded
  RGB panel colour.
- **Double-width / emoji glyph width.** board.py already treats this as a correctness
  issue, not a cosmetic one — the whole `_clusters`/`_visible_len` apparatus exists because
  a mis-measured line wraps, which then desyncs `agent_at`'s screen-row → agent mapping,
  silently misdirecting clicks. Any richer rendering (box borders spanning exact widths,
  right-aligned panel edges) inherits this same requirement: every border and fill has to be
  computed in the same column-accurate units, not `len()`.
- **Resizing.** Already handled today via `SIGWINCH` → `dirty[0] = True` → full re-`draw()`
  from `_size()`. A panel/box approach needs the same property: borders recomputed from
  current width every draw, not cached, which is naturally true of the existing pure-
  function `layout()` design and would need to stay true.
- **Screen-reader / plain-text fallback.** Nothing in the current design specifically talks
  to screen readers, but the `NO_COLOR` respect and "every distinction has a word or glyph"
  rule already produce something close to a reasonable plain-text degrade path. True
  box-drawing panels are harder to make screen-reader-friendly than plain lines are (a
  border character read aloud is noise), which is another argument for keeping any visual
  richness strictly decorative and skippable, matching the existing colour philosophy.

## 4. What good examples look like

- **lazygit / gh-dash** (and most of the modern "lazy-\*"/dashboard tools): built in Go on
  `bubbletea` (an Elm-architecture TUI framework) with `lipgloss` for styling — lipgloss is
  explicitly "CSS for your terminal," giving declarative borders, padding, and colour
  without hand-written ANSI. This is the Go-ecosystem analogue of "Textual + a styling
  layer" — a real component/event-loop framework, not a redraw-a-string-in-place script.
- **k9s**: also Go-based, similarly built on a full TUI framework rather than raw ANSI,
  giving it the same kind of bordered-panel, colour-coded-table look.
- **btop**: a C++ system monitor known for its dense, richly coloured panels and graphs;
  it hand-rolls its rendering rather than using a component framework, but it targets a
  full-screen dedicated view, not a side panel next to other work — a different problem
  shape than switchboard's board.
- **Claude Code itself** (this CLI): renders mostly through disciplined plain-text
  formatting, colour, and spacing rather than heavy box-drawing — closer in spirit to what
  a hand-rolled, decoration-optional approach like board.py's current one can achieve than
  to a k9s/lazygit-style bordered dashboard. I have not inspected its rendering source, so
  this is an observation from using it, not a verified claim about its implementation.
- The throughline: the tools with the richest look (lazygit, k9s) all commit to owning
  a real full-screen application framework with a styling layer built for it. Tools that
  stay closer to "print nicer text into an existing shell" (which is closer to what the
  board is — a side panel, not the whole show) tend to stay lighter-weight in their
  rendering technique.

## 5. My read: candidate directions, ranked

**A. Extend the hand-rolled ANSI approach — add box-drawing panels, reverse-video row
highlighting, and a capability-checked 256-color background, still zero dependencies.**
- Cost: moderate, incremental. A border-drawing helper (top/bottom rules with rounded
  corners, side rules) and a "highlight this row" helper (reverse video or a very small
  background palette) can be added next to the existing `_c`/`_pad`/`_clip` helpers without
  touching the pure `layout()`/`_compose` structure or the mouse-click machinery at all.
- Risk: it's more hand-written ANSI to get right (colour-code interaction with `_fit`'s
  width truncation, `NO_COLOR`, light/dark contrast) — but the project already has working,
  tested infrastructure for exactly these problems (`_visible_len`, `_clip_cols`, `_c`), so
  the new code extends a pattern that's already proven rather than starting cold.
- **Ranked #1.** It's the only option that doesn't touch the zero-dependency status, doesn't
  risk the click-to-agent mapping invariant, and doesn't require re-deriving mouse/width
  handling this project has already gotten right once.

**B. Adopt `rich`'s `Panel`/`Table`/`Live` for rendering, keep the hand-rolled SGR mouse
input and snapshot/layout logic underneath.**
- Cost: moderate-to-large. `layout()` would need reshaping from "one big pre-rendered
  string" into data Rich renders (a `Table` or manually laid-out `Panel` content), and the
  existing width-safe clipping would need to be reconciled with (or replaced by) Rich's own,
  which I have not verified matches switchboard's emoji/ZWJ/flag handling.
- Risk: first-ever third-party dependency, dragging in `pygments`+`markdown-it-py` for
  features the board never uses; a real chance of subtle width/wrap regressions in exactly
  the invariant `layout()`'s docstring calls out as the one thing that must never break,
  unless carefully verified line-by-line against the current `_clusters` test coverage.
- **Ranked #2.** Gets real panels/tables for less hand-written code than option A, but at
  dependency and correctness-risk cost that has to be paid deliberately, not accidentally.

**C. Rewrite the board as a `textual` app (or `urwid`).**
- Cost: large. This is a structural rewrite: replace the `select()`-loop-and-redraw `main()`
  with an event-driven `App`, replace hand-rolled SGR parsing with the framework's mouse
  events, and likely replace the pure `layout()` function with stateful widgets updated
  per-tick rather than rebuilt from a snapshot — a real architecture change to a file whose
  own docstring stresses how deliberately narrow and read-only its responsibilities are kept.
- Risk: highest of the three — heaviest dependency footprint, biggest surface for regressions
  in click-to-focus and width handling, and the least alignment with the board's actual
  usage pattern (a lightweight side panel next to a human's real work, refreshed every couple
  seconds) versus what Textual is built for (an app that owns the whole screen).
- **Ranked #3.** Would deliver the most "modern TUI framework" look, but the cost doesn't
  seem to match "the board looks kind of plain" as a problem — this is the option to reach
  for only if the ambition grows into something Textual is actually suited for (real
  interactivity beyond click-to-focus and scroll), not for backgrounds and panel borders.

Overall: unless there's an appetite for switchboard's first external dependency and a
willingness to re-verify the width/mouse invariants against it, **A** gets most of the
visual win ("real borders, panels, highlighted backgrounds") for the least risk to the two
things `board.py` is most careful about today — never mis-measuring a line, and never
losing meaning when colour is off.
