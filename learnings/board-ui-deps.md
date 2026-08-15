# Dependency options for a richer board UI — deep dive

Research task: `notes/task-board-ui-deps.md`. Scope was research only, no product code
touched. Covers rich, textual, blessed, urwid, prompt_toolkit, and a scan for anything
newer/missed. Written 2026-08-14.

**How this was produced**, so you know what to trust: I read `switchboard/board.py` myself
first (its docstrings on `_clusters`/`_visible_len`, the "line must never wrap" invariant,
and `main()`'s `select()`-based loop are quoted/paraphrased below from that reading, not
from memory of the library). I built a scratch venv and ran real width-comparison code
against all five candidates plus `wcwidth` (output below, in full). Health/footprint/API
claims for each library were gathered by three background research agents that fetched
real PyPI JSON metadata, GitHub repo pages, and doc pages — every fact below has a URL
next to it. I did not independently re-verify every URL those agents fetched; where I
ran code myself I say so explicitly ("verified: ran ...").

Everything below is dated **2026-08-14** — stars/versions/release dates are snapshots and
will drift.

---

## The key question first: width measurement

`board.py`'s `_clusters`/`_visible_len` (board.py:572-676) hand-roll column-accurate width
because **a wrapped line desyncs the screen-row-to-agent mapping and misdirects clicks**
(board.py:534-538, the "one invariant this view rests on"). It uses
`unicodedata.east_asian_width` for the base W/F-wide check, then its own rules for what
`east_asian_width` doesn't cover: zero-width combining marks/joiners/selectors/controls
(`Mn`, `Me`, `Cf`, `Cc` categories plus `unicodedata.combining()`), regional-indicator flag
pairs collapsed to one 2-wide glyph, ZWJ sequences collapsed to one glyph, and VS15/VS16
variation selectors flipping presentation width.

**Verified: I ran this.** Script and full output live in
`/private/tmp/claude-501/.../scratchpad/width_test.py` (session scratch dir, not in the
repo — copy it out if you want to keep it; I did not commit it per the task's "commit only
that file" instruction). It reimplements `_clusters`/`_visible_len` verbatim (no import —
board.py isn't importable standalone in that venv) and measures the same strings with each
library's own width function, in a venv with `rich 15.0.0`, `textual 8.2.8`,
`blessed 1.48.0`, `urwid 4.0.9`, `prompt_toolkit 3.0.53`, `wcwidth 0.8.2`.

Test strings (the exact cases `board.py`'s comments call out): plain ASCII, CJK ideographs,
a bare emoji, an emoji forced to text presentation via VS15, a heavy-checkmark forced to
*emoji* presentation via VS16, a two-codepoint regional-indicator flag (🇯🇵), a three-person
ZWJ family emoji, a skin-tone modifier, a combining accent, fullwidth punctuation, and a
mixed row resembling an actual board line (`● agent-中文 ✔️ working`).

Result table (columns as measured by each function):

```
case                     |   board | wcwidth.wcswidth | rich.cells.cell_len | blessed.Terminal.length | urwid.util.calc_width | prompt_toolkit.get_cwidth | textual._cells.cell_len
ascii                    |       5 |                 5 |                  5  |                       5 |                     5  |                        5  |                      5
cjk                      |      22 |                22 |                 22  |                      22 |                    22  |                       22  |                     22
emoji_simple              |      10 |                10 |                 10  |                      10 |                    10  |                       10  |                     10
emoji_vs16_text_default   |      12 |                12 |                 12  |                      12 |                    12  |                       11  |                     12
emoji_vs15_text           |      11 |                11 |                 11  |                      11 |                    11  |                       11  |                     11
flag_jp                  |      12 |                12 |                 12  |                      12 |                    12  |                       14  |                     12
family_zwj                |       7 |                 7 |                  7  |                       7 |                     7  |                       11  |                      7
skin_tone                 |      13 |                13 |                 13  |                      13 |                    13  |                       15  |                     13
combining_accent          |       9 |                 9 |                  9  |                       9 |                     9  |                        9  |                      9
fullwidth_punct           |       8 |                 8 |                  8  |                       8 |                     8  |                        8  |                      8
mixed_glyph_row           |      23 |                23 |                 23  |                      23 |                    23  |                       22  |                     23
```

**rich, blessed, urwid, textual, and bare `wcwidth` all match `board.py` exactly on every
case, including the hard ones (ZWJ family, flag pair, VS15/VS16).** That's because:

- `rich.cells.cell_len` and `textual._cells.cell_len` are the same function — textual
  depends on rich and re-exports it — and rich's cell-width table has its own Unicode
  grapheme-aware handling (confirmed by matching output, not read line-by-line).
- `blessed.Terminal.length` and `urwid.util.calc_width` both call through to the `wcwidth`
  package as their real width engine (`urwid`'s own PyPI metadata lists `wcwidth>=0.4` as a
  hard dependency — see the dependency section below — and blessed depends on
  `wcwidth>=0.8.1`).
- `wcwidth` itself (version 0.8.2, current) has apparently grown its own ZWJ/regional-
  indicator-aware sequence handling in recent releases, since `wcwidth.wcswidth()` called on
  the *whole string* matches board.py exactly — this wasn't obvious going in, and it's the
  most important single fact this test surfaced: **the plumbing under three of five
  candidates already agrees with switchboard's hand-rolled logic**, at least for these
  cases.

**prompt_toolkit's `get_cwidth` is the outlier, and it's a real, load-bearing difference.**
It's off on every case involving ZWJ, regional indicators, or variation selectors:
undercounts the VS16 case by 1 (12 vs 11 — the *dangerous* direction, since board.py's whole
invariant is "never let a line be one column too narrow and wrap"), overcounts the flag by
2 (12 vs 14), overcounts the ZWJ family by 4 (7 vs 11), overcounts the skin-tone case by 2
(13 vs 15), and undercounts the mixed row by 1 (23 vs 22).

**Verified: I read why, not just observed it.** `prompt_toolkit/utils.py`'s `get_cwidth` is
a thin wrapper around `wcwidth` (docstring: "Wrapper around `wcwidth`"), but — unlike my
`wcwidth.wcswidth(whole_string)` call above — prompt_toolkit's own internal call sites
invoke it **one character at a time**. I grepped the installed package and found the exact
site: `prompt_toolkit/layout/screen.py:124`, `self.width = get_cwidth(char)`, where `char`
is a single `Char` cell being written to the screen buffer — this is how prompt_toolkit
actually measures width when it renders, not an artifact of how I happened to call the
function in my test. Per-character measurement structurally cannot do ZWJ-joining or
regional-indicator-pairing, which are sequence-level rules — so this isn't a fixable
one-line integration bug, it's how the library's screen/layout model is built. **A board.py
rewritten on top of prompt_toolkit's own width measurement would mismeasure exactly the
row `board.py`'s own comments call out as the reason this code exists** (a task with a
family emoji, a "✔️" note, or a flag would be measured wrong).

So on the one question the task says "decides whether a library can be trusted with
drawing": rich, textual, blessed, and urwid all pass empirically; prompt_toolkit fails,
concretely and reproducibly, and the failure is architectural (per-character measurement),
not a version-pin gap that a future release would close on its own.

---

## rich

- **Links.** Docs: https://rich.readthedocs.io/en/stable/. Repo:
  https://github.com/Textualize/rich. Panels/boxes: https://rich.readthedocs.io/en/stable/panel.html
  and the box-style reference https://rich.readthedocs.io/en/stable/appendix/box.html.
- **Health.** ~57k GitHub stars. Latest release v15.0.0 (recent history: 14.3.4 Apr 2026,
  14.3.3 Feb 2026 — releases roughly every 2-6 weeks). ~4,460 commits on main, actively
  triaged. MIT. Python `>=3.9` (PyPI metadata).
- **Dependency footprint.** Verified: `./tuivenv` install shows exactly two runtime deps —
  `markdown-it-py` and `pygments` (both pure Python). `pip show`: `Requires: markdown-it-py,
  pygments`. Installed size of `rich/` in site-packages: 2.9M (plus its two deps: pygments
  9.3M — mostly lexer data — and markdown-it-py's small dependency chain, mdurl 72K).
- **What it gives.** `rich.panel.Panel` with any `rich.box` style including `ROUNDED`;
  `rich.table.Table` with `row_styles` for zebra/per-row highlighting; background fills via
  `Style(bgcolor=...)`; `rich.layout.Layout` for splitting the screen into regions;
  `Color.downgrade()` does truecolor→256→16 with saturation-aware nearest-color mapping.
  **Verified:** I rendered a `Panel("hello", box=ROUNDED, style="on grey15")` through
  `Console.render()` and got 11 segments back without error — rounded-box + background-fill
  both work as documented. **Verified:** NO_COLOR — with `NO_COLOR=1` set, a fresh
  `rich.console.Console()`'s `color_system` came back `None` (vs `truecolor` with it unset);
  rich disables color but keeps bold/dim/underline, per its docs.
- **Fit with a repaint-from-snapshot loop.** Excellent, close to a drop-in. `rich.live.Live`
  is a context manager where you call `live.update(new_renderable)` with a freshly-built
  object each tick — it does not want mutated state, it wants a new tree from your current
  data, which is exactly `board.py`'s `layout()` shape today. `main()` would still own the
  `select()` loop, input reading, and the ~2s refresh timer; it would just build a
  `rich.layout.Layout`/`Table`/`Panel` tree from `snap` instead of a list of strings, and
  call `live.update()` instead of the current `draw()`'s raw `sys.stdout.write`.
- **Mouse.** Rich has no input system at all — it's render-only. Nothing to conflict with;
  `board.py`'s `parse_sgr`/`MOUSE_ON` handling stays exactly as-is.
- **tmux behaviour.** No rich-specific tmux quirks found; it just emits ANSI/SGR and
  auto-detects color depth from `COLORTERM`/`TERM`, so it inherits the same general
  tmux-truecolor-passthrough config dependency every ANSI-emitting program has.

## textual

- **Links.** Docs: https://textual.textualize.io/. Repo:
  https://github.com/Textualize/textual. Borders/layout:
  https://textual.textualize.io/guide/styles/ (also `textual borders` CLI to preview).
- **Health.** ~37k stars. Latest v8.2.8 (Jun 2026), releases roughly every 2-4 weeks,
  ~13,100 commits on main — very actively developed. MIT. Python `>=3.9,<4.0`.
- **Dependency footprint.** Pulls rich wholesale, plus `markdown-it-py[linkify]`,
  `mdit-py-plugins`, `platformdirs`, `pygments`, `typing-extensions`. Installed size of
  `textual/` alone: 7.2M (on top of rich's footprint). An optional `syntax` extra adds 16
  `tree-sitter*` packages (per-language grammars) — sizeable, opt-in only, no reason to
  enable it for a board.
- **What it gives.** CSS-like styling with `border:` on any widget (many border types via
  `textual borders`), alpha-transparent backgrounds, a full box model (padding/margin/`fr`
  units), container widgets (`Horizontal`/`Vertical`/`Grid`), a `DataTable` widget, and (via
  its rich dependency) the same color-downgrade/NO_COLOR handling as rich.
- **Fit with a repaint-from-snapshot loop.** This is the real cost. Textual is a full
  asyncio application framework — `App.run()` takes over the terminal, alternate screen, and
  all input. Its idiomatic model is *reactive*: widgets hold `reactive` attributes and you
  mutate them; a `set_interval` timer drives periodic ticks. You *can* force a
  "rebuild-the-whole-widget-tree-from-JSON every 2s" pattern (wipe children, rebuild), and it
  will run, but it fights the framework's diffing and risks flicker/focus loss on identity
  churn — it's the wrong grain for this codebase's "one pure function draws the whole
  screen" design. `board.py`'s `main()` would essentially cease to exist as written and
  become a Textual `App` subclass.
- **Mouse.** Textual decodes SGR mouse itself (`textual/_xterm_parser.py`) into
  `MouseDown`/`Click`/`MouseScrollUp` etc. Adopting it means **deleting**
  `board.py`'s `parse_sgr`/`is_left_click`/`wheel` entirely and handing input to Textual's
  driver — no coexistence option.
- **tmux behaviour.** No official tmux doc page; a Textualize GitHub discussion
  (Textualize/textual#4003) shows users hitting the standard tmux truecolor-passthrough gap,
  fixed by the usual `tmux.conf` `default-terminal`/`terminal-overrides` knobs — general tmux
  behavior, not textual-specific.

## blessed

- **Links.** Docs: https://blessed.readthedocs.io/en/latest/. Repo:
  https://github.com/jquast/blessed. **There is no panels/boxes/borders page** — closest is
  cursor addressing at https://blessed.readthedocs.io/en/latest/location.html; color fills
  are on https://blessed.readthedocs.io/en/latest/colors.html. Blessed genuinely has no
  panel/box abstraction to link to.
- **Health.** ~1.5k stars, 0 open issues shown at check time. Latest 1.48.0 (2026-08-07);
  six point releases between 2026-05-19 and 2026-08-07, mostly terminal-capability-detection
  fixes (kitty DA1 handling, thread-safety). MIT. Python 3.8-3.14.
- **Dependency footprint.** Two hard deps: `wcwidth>=0.8.1`, `jinxed<3,>=2.1` (terminfo
  lookups on platforms without stdlib `curses`, i.e. Windows). Installed size of `blessed/`:
  1.0M, plus wcwidth (4.4M — mostly its Unicode data tables) and jinxed (848K).
- **What it gives.** Honestly, a terminal-capability wrapper, not a widget system: no
  bordered-panel primitive, no table, no "fill this rectangle" helper (you'd still loop and
  print characters), no rounded-corner concept. What it *does* give concretely: real
  background-color escape wrapping (`term.on_color_rgb()` etc.) with **documented
  truecolor→256→16 downgrade** ("even if the terminal only supports 256, or worse, 16
  colors, the nearest color supported is automatically mapped" — colors.html), based on
  `COLORTERM`/`term.number_of_colors` detection. No documented NO_COLOR env-var support was
  found — you'd still gate that in switchboard's own code, same as today.
- **Fit with a repaint-from-snapshot loop.** The best architectural fit of any candidate
  after rich. No event loop of its own — `term.inkey(timeout=...)` is a call you make inside
  whatever loop you already drive, and rendering is "print strings built with
  `term.color()`/`term.move_xy()`". `board.py`'s `main()` and `select()`-based loop could
  stay essentially as-is; blessed would replace the raw ANSI-escape plumbing (`MOUSE_ON`,
  `HIDE_CURSOR`, manual `\033[H\033[2J`) with capability-aware calls, not the loop structure.
- **Mouse.** Blessed decodes SGR mouse itself: `term.mouse_enabled()` context manager
  ("always enables SGR extended mouse mode (1006)"), events arrive through the same
  `inkey()` call as keyboard input as a `MouseEvent` with `.y`/`.x`/button/modifier
  predicates. This **would directly replace** `board.py`'s `parse_sgr`/`SGR` regex/`wheel`/
  `is_left_click` — same protocol, blessed just owns the decode step instead of hand-rolled
  regex on raw stdin bytes.
- **tmux behaviour.** Blessed explicitly emulates `hpa`/`vpa` "by proxy" under tmux/screen
  since those terminfo capabilities aren't natively reported inside multiplexers — a real,
  documented tmux-awareness point in blessed's favor. No blessed-specific truecolor bug
  found; general tmux truecolor config caveats apply same as everywhere else.

## urwid

- **Links.** Docs: https://urwid.org/ (mirror: https://urwid.readthedocs.io/). Repo:
  https://github.com/urwid/urwid. Panels/borders: widget reference
  https://urwid.org/reference/widget.html (`LineBox`, `SolidFill`, `AttrMap`); layout at
  https://urwid.org/manual/widgets.html (`Pile`, `Columns`, `GridFlow`, `Overlay`, `Frame`).
- **Health.** ~3,000 stars, 124 open issues. **License: LGPL-2.1-only** — copyleft, worth
  flagging explicitly since every other candidate here is MIT/BSD. Latest 4.0.9
  (2026-08-14); five point releases in the last ~3.5 weeks, 4 active maintainers listed —
  reads as healthy and actively maintained, not dormant. Python 3.9-3.14 + PyPy3.
- **Dependency footprint.** Verified: `pip show urwid` lists `Requires: typing-extensions,
  wcwidth` — two hard runtime deps (default install). Optional extras
  (`pygobject`/`tornado`/`trio`/`twisted`/`zmq`/`pyserial`) only pull in if you opt into a
  non-stdlib event-loop backend; default footprint stays light. Installed size of `urwid/`:
  2.7M.
- **What it gives.** The real contrast with blessed: a genuine widget+layout system.
  `LineBox` wraps any widget with a border and title, with named rounded-corner symbols
  (`LineBox.Symbols.LIGHT.TOP_LEFT_ROUNDED` etc.); `SolidFill` fills a rectangle; per-row
  highlight is idiomatic via `AttrMap` + `ListBox`/`Pile` (this is what urwid is *for* — a
  focus-highlighted list is close to switchboard's own row-per-agent model); `Pile`/
  `Columns`/`Overlay`/`Frame` cover layout/splitting. No dedicated `Table` widget, but
  trivially composed from `Columns`+`Pile`. Colour downgrading is documented and deliberate
  (truecolor hex, 256-color cube/grayscale, 16-color+attributes, with an explicit
  "design for graceful degradation" recommendation and a `palette_test.py` example). No
  documented NO_COLOR support found — same caveat as blessed.
- **Fit with a repaint-from-snapshot loop.** The important nuance the docs state
  explicitly: "Using MainLoop is highly recommended, but if it does not fit... you may
  choose to use your own code instead, and there are no dependencies on MainLoop in other
  parts of Urwid." So a DIY loop is a supported path, not a hack — but you're still adopting
  a **retained widget tree**: either cede the loop to `MainLoop.run()` and push snapshot
  data in via widget updates + `draw_screen()`, or rebuild widget contents each tick
  yourself and call `draw_screen()` manually, bypassing `run()`. Either way it's more
  invasive than blessed's "just print strings" model, because there's now a widget tree with
  identity that has to be kept in sync with `snap`, not a flat string buffer.
- **Mouse.** Native mouse support wired through the event loop and widget tree — container
  widgets route SGR/xterm events to a widget's own `mouse_event()` method when tracking is
  enabled on the loop. Same replace-not-coexist story as the others, but more entangled
  since events dispatch through the widget tree rather than coming back as a flat read from
  one input call.
- **tmux behaviour.** General truecolor-passthrough caveat, same as everywhere.
  **A concrete, documented tmux bug exists:** urwid/urwid#195 — a full-screen `LineBox` in a
  tmux pane failed to render its bottom-right corner correctly on Linux (fine on macOS);
  resizing the pane was the reported workaround. Directly relevant if `LineBox` would be used
  for the board's own border.

## prompt_toolkit

- **Links.** Docs: https://python-prompt-toolkit.readthedocs.io/. Repo:
  https://github.com/prompt-toolkit/python-prompt-toolkit. Layout:
  https://python-prompt-toolkit.readthedocs.io/en/master/pages/full_screen_apps.html.
- **Health.** ~10.6k stars. Latest 3.0.53, released **July 26, 2024** — over two years stale
  as of this check (2026-08-14), the largest gap of any candidate here, though the repo
  still shows commit/issue activity (2,822 commits, 611 open issues). Reads as "stable,
  low-churn" rather than actively developed. BSD-3-Clause. Python `>=3.10` (current
  release's floor).
- **Dependency footprint.** Verified: single hard dependency, `wcwidth>=0.1.4`. Installed
  size of `prompt_toolkit/`: 3.6M.
- **What it gives.** `Frame` widget for bordered panels (rounded corners possible but need
  explicit custom border characters, no one-flag "rounded=True"); `Window` background fill;
  no built-in table widget (composed manually); no declarative per-row highlight (DIY via
  custom `UIControl` styling); `HSplit`/`VSplit`/`FloatContainer` for layout — this part is
  genuinely prompt_toolkit's strength. Colour downgrading is built in (default 256-color,
  truecolor opt-in via `ColorDepth.TRUE_COLOR`, auto-downgrade for `TERM=linux`/
  `eterm-color`, controllable via `PROMPT_TOOLKIT_COLOR_DEPTH` env var). **No confirmed
  NO_COLOR support** — only its own `PROMPT_TOOLKIT_COLOR_DEPTH` convention was found.
- **Fit with a repaint-from-snapshot loop.** Owns the asyncio event loop via
  `Application.run()`/`run_async()`. A 2s tick would be a `call_later()` or background task
  calling `app.invalidate()`; internally it re-renders declaratively from your
  `Layout`/`UIControl` tree and diffs against the previous frame itself, so the "describe
  current state, let it figure out what changed" shape is reasonable. The real cost:
  `board.py`'s `select()`-based main loop would need to become an asyncio app under
  `run_async()`, or you'd run prompt_toolkit's `Screen`/`Renderer` standalone (possible, but
  under-documented and gives up most of the reason to adopt it).
- **Mouse.** Decodes SGR itself (`key_binding/bindings/mouse.py`, detects `ESC[<`, parses
  `button;x;y` plus terminator, handles scroll + modifier bits). Would conflict with
  hand-rolled parsing if prompt_toolkit also owns input reading, which it does by default
  once you adopt `Application`.
- **tmux behaviour.** No dedicated tmux doc page; scattered GitHub issues report rendering
  glitches on resize, but nothing reads as an accepted, documented limitation. Notable but
  weak data point: **pymux**, a tmux-like multiplexer built on prompt_toolkit, exists — shows
  the rendering model *can* work in multiplexer-adjacent contexts — but pymux itself is
  reported to need maintenance (pinned to old prompt_toolkit/ptterm versions), so it doesn't
  strongly support or refute anything about running *inside* tmux specifically.
- **And it's the one that fails the width test** — see the top section. This is the
  deciding factor against it independent of everything else above.

---

## Other candidates looked for and ruled out

Searched explicitly for anything newer than 2023 that might have been missed. Found nothing
credible beyond what's below (see the raw sweep — nothing else turned up, including one
unverifiable search snippet naming an "xnano" TUI framework with no confirmable GitHub/PyPI
presence, not included as a real finding).

- **PyTermGUI** — genuinely interesting on paper (window-manager-style widgets, mouse
  support, explicit NO_COLOR/degradation docs, MIT) but **archived by its owner on
  2026-08-10, four days before this research** — "no longer in development." Out purely on
  timing; not worth adopting a dead project on day one regardless of design quality.
- **asciimatics** — 1.15.0, last released Oct 2023 (~2.5 years stale), pulls in `Pillow`
  (a substantial, non-trivial dependency for a terminal renderer) plus `pyfiglet`. Its
  selling point is ASCII-art/animation effects, irrelevant here. Out.
- **py_cui** — last released Sept 2022 (~4 years stale), curses-based (inherits curses'
  portability/terminfo quirks — a step backward from what board.py's hand-rolled approach
  is already avoiding by not using curses). Out.
- **npyscreen** — confirmed effectively dead (homepage links rot to a defunct Google
  Code/Bitbucket chain; community explicitly questions if it's alive). Not evaluated
  further.

---

## Ranked recommendation

1. **rich**, specifically. Two pure-Python dependencies, MIT, actively released,
   `rich.live.Live` fits `board.py`'s "one pure function draws the whole screen from a
   snapshot" model almost exactly (verified: rendered a rounded `Panel` with a background
   fill through it directly), doesn't touch input or own the event loop at all — `board.py`'s
   existing `select()` loop, `parse_sgr` mouse decoding, and `main()` structure survive
   untouched, and it passed the width test byte-for-byte against every hard case board.py's
   own comments call out. This is the "just UI" option Andrew described: swap the string-
   building half of `layout()` for building `rich` renderables, keep everything else.

2. **blessed**, if the goal is specifically to stop hand-rolling escape codes and mouse
   decoding rather than to add panel/table primitives. Also passed the width test, also two
   small deps, MIT, has real documented tmux-awareness (`hpa`/`vpa` proxying), and its SGR
   mouse decoding is a clean, documented replacement for `board.py`'s own `parse_sgr`. It
   gives you nothing for borders/panels/tables though — you'd still be drawing those by hand,
   just with correct-by-construction color/cursor calls underneath. Reasonable to combine
   with rich (blessed for input/color plumbing, rich for panel rendering) rather than an
   either/or, though that's a design question beyond this research task's scope.

3. **urwid** — the only candidate with a first-class bordered-panel-with-rounded-corners
   *and* focus/highlight system that matches switchboard's row-per-agent shape closely
   (`AttrMap`+`ListBox` is close to "highlight the row under the cursor/click"), and it
   passed the width test. Held back from #1 by three real costs: LGPL-2.1 (copyleft, unlike
   every other MIT/BSD candidate here — a licensing question Andrew should weigh in on, not
   assumed away), wanting a retained widget tree even though a DIY loop is documented as
   supported, and a documented tmux-specific `LineBox` rendering bug (urwid#195) that would
   need to be tested against switchboard's actual tmux setup before trusting it for borders.

4. **textual** — ruled out for this specific use case, not for lack of quality: it's the
   most actively developed and richest-featured candidate, but it wants to own the whole
   application (event loop, alternate screen, input, its own SGR mouse parser) and its
   idiomatic model is reactive-widget, not full-repaint-from-JSON. Adopting it means
   `board.py`'s `main()` stops being a `select()` loop and becomes a Textual `App`
   subclass — a rewrite of the whole file's control flow, not a rendering swap. Worth
   revisiting only if switchboard ever wants the board to become a much larger interactive
   application rather than a glanceable side panel.

5. **prompt_toolkit** — ruled out. It fails the one test the task calls the deciding
   factor: its `get_cwidth` measures width one character at a time
   (`prompt_toolkit/layout/screen.py:124`), which structurally cannot do the ZWJ-joining or
   regional-indicator-pairing `board.py` depends on, and the failure is reproducible and in
   the dangerous direction on at least one case (undercounts a VS16 emoji by 1 column, which
   is exactly the "line wraps, next click lands on the wrong agent" failure `board.py`'s own
   docstring calls out as unacceptable). It's also the only candidate with no tagged release
   in over two years. Combined with wanting to own the event loop, there's no case for it
   here even though its `HSplit`/`VSplit` layout system is genuinely nice.

**What's unverified and should be checked with real code before committing**: I did not
build a working prototype of any candidate driving `board.py`'s actual `layout()`/`draw()`
inside a real tmux pane — the fit-with-the-loop and tmux-behavior sections above are read
from docs/source and, for urwid's LineBox bug, from an issue report, not from watching it
happen in switchboard's own pane. If rich is picked, the next real step is a small spike:
render one frame of `layout()`'s current output as a `rich.table.Table` inside `Live`, in an
actual tmux pane on this machine, and confirm resize/`SIGWINCH` handling and truecolor
passthrough behave as documented.
