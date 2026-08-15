# The board's visual half: what could it actually look like?

Task: `notes/task-board-ui-looks.md` (from board-fix). Research only, no product
code touched. Scope is *look*, not libraries — a sibling (researcher-26,
`task-board-ui-deps.md`) is covering the library question separately.

I read `switchboard/board.py` in full and ran `sb status` in this checkout to see
real data before sketching anything (output below is genuine, from this fleet,
not invented for the mockups).

## 0. The constraints the design has to fit (from board.py + a live `sb status`)

- **Width**: the board pane is 34% of the terminal for a child agent's board,
  45% for the top orchestrator's (`BOARD_SHARE`, `TOP_BOARD_SHARE`,
  board.py:81-87). The task brief's 40-60 column budget is the right range to
  design for; nothing here should assume more.
- **One line per agent, hard.** board.py:534-538: "no line may ever wrap. A
  wrapped line pushes every row below it down by one, and the next click
  focuses the wrong agent." Any redesign that lets a row grow to two lines
  needs a redesign of the click-mapping in `layout`/`agent_at`, not just a
  paint job. This is the single biggest constraint on all three mockups below.
- **Per-row fields, in order**: glyph (●○◐◌✗?), indent (`"  " * depth`), name,
  state, idle age, then up to one "detail bit" (marker / mail / tail note)
  chosen by priority and clipped to fit (`detail_bits`, `_compose`,
  board.py:281-333).
- **Grouping, not boxes**: first-level groups (an orchestrator and its direct
  children) get a blank line above them, not a rule — board.py:357-362
  explicitly rejected a horizontal rule as "the heaviest thing on the screen,"
  since it would visually cut across the tree's own indentation.
- **Color is decoration only.** `_COLOR = os.environ.get("NO_COLOR") is None`
  (board.py:91) and every distinction is also carried by a glyph or word. Five
  colors total today: DIM(2), RED(31), YELLOW(33), GREEN(32), BLUE(34) — all
  *foreground* SGR codes, no backgrounds, no 256/truecolor.
- **Mouse + click mapping**: rows carry their owning agent object
  (`layout`'s `emit`), so a background-filled "selected row" affordance is
  free to add visually — nothing currently marks a row as selected/hovered,
  there's no cursor concept yet, only click-to-focus.

Real sample, this fleet, right now (`sb status`, plain text, no color captured
here since it's piped):

```
AGENT            ROLE          STATE     HERDR    MAIL     AGE    IDLE  WORKSPACE
board-fix        orchestrator  idle      done        -     52m      2s  board-fix
    ↳ Await my instructions.
  researcher-22  researcher    done      blocked     1      9m      3m  researcher-22  << AT PROMPT
      ↳ Read notes/task-board-ui-current.md and do exactly what it says.
      ✓ Task said to read notes/task-board-ui-current.md and do exactly what it says, but that file doe…
  researcher-23  researcher    done      done        1      8m      3m  researcher-23
      ↳ Read notes/task-board-ui-techniques.md and do exactly what it says.
      ✓ Task was to read notes/task-board-ui-techniques.md and do exactly what it says — that file does…
  researcher-26  researcher    working   working     -     18s     15s  researcher-26
      ↳ Read the file at absolute path /Users/andrew/Code/switchboard/notes/task-board-ui-deps.md (it i…

NEEDS YOU
  researcher-22  waiting at a prompt in its own TUI  →  sb inspect researcher-22
  researcher-23  1 unread, not picked up  →  sb inspect researcher-23
```

That's the shape everything below has to actually carry: a tree, states,
mail counts, ages, task/summary lines, a NEEDS YOU section.

## 1. Survey — terminal UIs worth stealing from

For each: the *one or two specific techniques*, not a general description.

### [lazygit](https://lazygit.dev/) ([repo](https://github.com/jesseduffield/lazygit))
- Multiple bordered panels (files / branches / commits / stash) tiled on
  screen at once, each with a titled border.
- Border style is a first-class config option: `rounded` (default), `single`,
  `double`, `hidden`, `bold` — see
  [`docs/Config.md`](https://github.com/jesseduffield/lazygit/blob/master/docs/Config.md).
  The *focused* panel gets a distinct border color from unfocused ones — that,
  not fill color, is how lazygit shows "where you are."
- Known weak spot, worth noting as a warning: default colors clash badly on
  light-background terminals ([issue #508](https://github.com/jesseduffield/lazygit/issues/508))
  and low-contrast panel borders were reported separately
  ([issue #38](https://github.com/jesseduffield/lazygit/issues/38)). Lazygit's
  answer was "make it themeable," not "pick colors that work on both" — it
  never solved the light/dark problem generically, it pushed the decision to
  the user's config file.

### [k9s](https://k9scli.io/) ([repo](https://github.com/derailed/k9s))
- Full "skin" system: YAML files under `~/.config/k9s/skins/` remap every UI
  element's color, loaded live without restart
  ([DeepWiki: Themes and Styling](https://deepwiki.com/derailed/k9s/6.3-themes-and-styling)).
- The **selected row is a solid background fill with contrasting foreground**,
  not just bold or reverse — that's the technique worth stealing specifically:
  it reads instantly as "cursor is here" versus a merely-bold row, which per
  lazydocker below is genuinely harder to see.
- A `transparent.yaml` skin exists specifically to preserve the user's own
  terminal background rather than paint one
  ([skins/transparent.yaml](https://github.com/derailed/k9s/blob/master/skins/transparent.yaml))
  — i.e. k9s itself ships the "don't assume a background" escape hatch as an
  explicit, named option, which is a useful precedent.
- Catppuccin ships an official k9s theme
  ([catppuccin/k9s](https://github.com/catppuccin/k9s)) that's designed to
  read on both light (Latte) and dark (Mocha/Macchiato/Frappé) variants of one
  consistent palette — the palette-not-per-tool approach, see §3.

### [btop](https://github.com/aristocratos/btop)
- Built-in theme picker (Default, TTY, gruvbox_dark, nord, onedark, dracula,
  …), switched live, no restart.
- Rounded-corner box drawing is a literal on/off *option*, independent of
  theme — the box-drawing character set is swappable from the sharp default to
  a rounded one purely for aesthetics.
- Graphs render as dense braille-character sparklines inside bordered panels —
  the technique worth stealing isn't the graph itself (the board has no
  numeric series to plot) but the *density*: a lot of information in a
  fixed-height bordered box without the box growing.

### [gh-dash](https://www.gh-dash.dev/) ([repo](https://github.com/dlvhdr/gh-dash))
- Built on Charm's stack — bubbletea (TUI loop), lipgloss (styling), glamour
  (markdown) — confirmed by
  [Hacker News discussion of the release](https://news.ycombinator.com/item?id=40496150)
  and the [project's own examples page](https://www.gh-dash.dev/configuration/examples/).
- Sectioned single-column list (PRs "assigned to me", "review requested",
  etc.), each section a titled group, each row a single line with colored
  status pills (open/draft/merged) as short colored words, not icons.
- This is the closest existing tool to switchboard's board in *shape*: a
  narrow-ish single-column list of items with state, not a multi-pane
  dashboard like lazygit/k9s. Its section-header-plus-flat-rows structure maps
  almost directly onto "orchestrator, then indented children."

### [lazydocker](https://lazydocker.com/) ([repo](https://github.com/jesseduffield/lazydocker))
- Same gocui-based panel layout as lazygit (its sibling project), themeable
  the same way.
- A genuine documented weakness, useful as a cautionary data point: the
  selected-row highlight is bold-only in some configs and was reported as
  hard to distinguish from normal text
  ([issue #214](https://github.com/jesseduffield/lazydocker/issues/214), white-on-white
  in dialogs). This is the concrete case for "bold alone is not enough
  contrast for a selected/active row" — background fill or reverse video reads
  more reliably.

### [gitui](https://github.com/gitui-org/gitui)
- Rust, near-instant redraw, same panelled-with-borders shape as lazygit but
  written for raw speed. Themeable via a TOML/RON config; didn't find
  documented specifics on its selected-row treatment beyond "customizable,"
  so I'm not claiming a specific technique here beyond the general panel
  layout.

### zellij, atuin, dust, bottom
- **[zellij](https://zellij.dev/)**: persistent status bar at the bottom
  showing live keybindings for the current mode, and a tab bar at the top
  showing session/tab names — i.e. chrome that tells you *what your keys do
  right now* rather than a static help text. Relevant to the board's own
  footer line (`click a row to focus it · scroll to pan · a archived · q
  quits`, board.py:531) — zellij's version of that line changes based on mode,
  which the board's doesn't need since it only has one mode.
- **[atuin](https://atuin.sh)**: search-as-you-type shell history UI; didn't
  turn up specific styling detail beyond "themeable," and it's a full-screen
  overlay, not a side panel, so I'm treating it as low-relevance to this task
  and not asserting techniques I didn't verify.
- **dust**, **bottom**: my searches did not surface specific styling
  documentation for either (search results for "dust bottom terminal UI
  design" returned zellij/atuin results instead, not these tools) — I'm
  flagging this as unverified rather than inventing detail. What's true from
  general knowledge and worth naming anyway: `bottom` (btm) uses the same
  bordered-panel-plus-live-graph shape as btop, so it doesn't add a
  new technique to the list above.

## 2. What suits a 40-60 column side panel, and what doesn't

The width budget matters more than any other factor here. A lazygit/k9s/btop
panel border costs **2 columns of pure structure** (`│ content │`) per nested
level, plus at least 1 column of padding inside it typically — call it 3-4
columns per level of "real box." The board's own name column already flexes
with the deepest agent name plus its indent (board.py:484), and depth in this
tree can go 3+ levels (orchestrator → delegate → sub-delegate). Boxing that
tree the way lazygit boxes its panels would eat the width budget on structure
before a single field is drawn.

**Fits a narrow panel:**
- Background-fill on a single row (k9s's selected-row technique) — costs zero
  extra columns, since it's paint, not glyphs.
- A colored short status word or single glyph per row (gh-dash's pills, the
  board's own ● ○ ◐ ◌ ✗ glyphs) — this is already exactly what the board does.
- Section headers as a styled text line with no box around it (gh-dash's
  "PRs assigned to me" style) — this is what "NEEDS YOU" already is, just
  undecorated.
- Dim/secondary color for the tail note vs. bright for identity — pure
  foreground-color technique, zero width cost, already implemented via DIM.
- A single top-level rule or filled header bar (one row, full width) — this
  is the one "bold" idea from btop/k9s's chrome that costs only 1 row, not
  columns, so it's cheap even at 40 columns.

**Wasted or actively harmful at 40-60 columns:**
- Multi-panel side-by-side layout (lazygit's six-panel screen, k9s's
  resource-list-plus-detail split) — there is no width left to tile two
  panels side by side under 60 columns; this needs a full-screen app.
- Per-item bordered boxes (a box drawn around *each row*, rather than around
  the whole list) — at depth 3 with a box per agent, the box-drawing
  characters alone would consume more width than the agent name.
- Dense sparkline/graph rendering (btop's braille graphs) — the board has no
  numeric time-series to plot per row, so this technique has no data to carry
  even ignoring width.
- Full theme-file customization systems (k9s skins, lazygit config.yml) — not
  a "too wide" problem, but a "wrong tool" one: switchboard ships one binary
  to many users' terminals; a per-user skin file is exactly the kind of
  optional-feature surface DESIGN-TRUTH would push back on unless Andrew
  wants it. Noting it here as "possible, but a scope question," not
  recommending against it outright.

## 3. Light vs. dark: what's safe blind, what needs a chosen palette

The board cannot know the user's terminal background — board.py has no such
detection code today, and the existing `NO_COLOR`-respecting design
(board.py:91-95) implies the author already treats color as optional
decoration rather than something to detect and adapt.

**Safe without knowing the background (foreground-relative techniques):**
- **Reverse video** (swap fg/bg) — this is the one technique that is
  *guaranteed* readable regardless of terminal background, because it uses
  the terminal's own two colors against each other rather than asserting a
  third one. It's the correct choice for "selected row" if the board wants to
  stay palette-agnostic. This is effectively what k9s's `transparent.yaml`
  skin (cited above) is doing in spirit — deferring to the terminal instead
  of asserting a color.
- **Dim (SGR 2)** — every terminal renders this as "darker than normal text"
  relative to whatever the normal text color already is; it degrades safely
  on both light and dark because it's relative, not absolute. This is what
  the board already uses for secondary text and is the correct existing
  choice.
- **Bold** — same relative-safety property as dim, but weaker as a signal
  (lazydocker's issue #214 above is the concrete evidence it isn't enough
  alone for "selected").
- **The 8 standard ANSI foreground colors (30-37)**, used *without* also
  setting a background — a well-configured terminal remaps these to fit its
  own theme, which is exactly the mechanism that currently keeps GREEN/RED/
  YELLOW/BLUE safe in board.py's `_c()` (SGR codes "32", "31", "33", "34" —
  board.py:98). This is the reason the current board hasn't had a light/dark
  bug report: it never asserts an RGB value.

**Unsafe without a chosen palette:**
- **Any fixed background color fill** (e.g. a literal "blue header bar") —
  this needs a palette decision because a background color is an assertion
  about what contrasts with the terminal's *default* background, which the
  board cannot see. A background chosen against a dark terminal can be
  unreadable-close to a light terminal's own default. This is lazygit's
  actual, documented failure mode (issue #508 above): its defaults were
  tuned for dark terminals and broke on light ones.
- **True-color / 256-color exact hex fills** (k9s skins, btop themes) — same
  problem, worse, because a specific hex assumes nothing about the
  surrounding terminal at all.

**A small palette that's evidenced to work on both**, if the board does want
one fixed set of colors rather than staying purely relative: the pattern
[Catppuccin](https://github.com/catppuccin/k9s) uses across its whole
ecosystem (k9s included) is to ship **paired light/dark variants of one
consistent palette** (Latte for light, Mocha for dark) rather than one
palette assumed to work on both — i.e. the evidence points toward "detect or
ask, then pick one of two prepared palettes," not "one palette that's
claimed to be universally safe." I did not find a single fixed palette
anywhere in this research that's documented as reading well on both
backgrounds without switching — that claim doesn't hold up, and the honest
recommendation is: either stay fully relative (reverse video + dim + the 8
ANSI colors, as today), or detect background and switch between two curated
sets. There is background-detection prior art worth a pointer for whoever
picks this up:
[termstandard/colors](https://github.com/termstandard/colors) and
[terminal-colorsaurus](https://github.com/bash/terminal-colorsaurus) (queries
the terminal for its actual background color via OSC escape codes) — I did
not test either against switchboard's target terminals, so this is a
pointer, not a verified recommendation.

## 4. Sketches

Using real agent names and data from this fleet (`sb status` above), at 56
columns — inside the 40-60 budget. Each keeps the one-line-per-agent
constraint from board.py:534.

### (a) Restrained — section rules, highlighted selected row, dim secondary text

Only additions over today: a filled bar for the header, reverse-video on one
row to show "this is where a click landed," and a plain blank-line rule
between groups (already true today, kept). No new box-drawing.

```
 switchboard · 6 alive · 1 at prompt · 2 unread

 ●  board-fix        orchestrator  idle       2s
      Await my instructions.

 ◐  researcher-22    researcher    done       3m  << AT PROMPT
      ✓ file doesn't exist, said so and stopped
[7m ○  researcher-23    researcher    done       3m  ·1 unread    [0m
      ✓ task file doesn't exist — reported, stopped
 ●  researcher-26    researcher    working   15s
      Read task-board-ui-deps.md and do what it says

 NEEDS YOU
   researcher-22  waiting at a prompt  → sb inspect researcher-22
   researcher-23  1 unread, not picked up

 click a row to focus · scroll to pan · a archived · q quits
```
(`[7m…[0m` = reverse video on the selected/hovered row; renders as
light-on-dark or dark-on-light automatically, whichever the terminal is.)

### (b) Panelled — real bordered box with a title

Costs 2 columns of border on every line plus the group-break rule becomes a
row-spanning divider instead of blank space — a real departure from
board.py:357-362's explicit rejection of a full-width rule, so this is the
most invasive of the three relative to the current code, not just the paint.

```
┌─ switchboard ── 6 alive · 1 at prompt · 2 unread ──┐
│ ●  board-fix       orchestrator  idle        2s    │
│      Await my instructions.                        │
├──────────────────────────────────────────────────── │
│ ◐  researcher-22   researcher    done   3m<<PROMPT  │
│      ✓ file doesn't exist, said so and stopped      │
│ ○  researcher-23   researcher    done    3m ·1 unrd │
│      ✓ task file doesn't exist — reported, stopped  │
│ ●  researcher-26   researcher    working    15s     │
│      Read task-board-ui-deps.md, do what it says    │
├──────────────────────────────────────────────────── │
│ NEEDS YOU                                            │
│  researcher-22  at a prompt → sb inspect researcher-…│
│  researcher-23  1 unread, not picked up              │
└──────────────────────────────────────────────────────┘
```

### (c) Bold — filled headers, colour-blocked state column

Background fills on the header and on the state word itself (state becomes a
colored "pill" rather than plain text) — the gh-dash-pill idea plus a k9s-style
filled header. This is the one that most needs the palette answer from §3,
since it's the only sketch asserting real background colors rather than
staying relative.

```
[44;97m switchboard  ·  6 alive  ·  1 at prompt  ·  2 unread        [0m
 ●  board-fix        [100;97m idle    [0m   2s
      Await my instructions.

 ◐  researcher-22     [43;30m done    [0m   3m  << AT PROMPT
      ✓ file doesn't exist, said so and stopped
 ○  researcher-23     [43;30m done    [0m   3m  · 1 unread
      ✓ task file doesn't exist — reported, stopped
 ●  researcher-26     [42;97m working [0m  15s
      Read task-board-ui-deps.md, do what it says

[43;30m NEEDS YOU                                            [0m
   researcher-22  at a prompt  → sb inspect researcher-22
   researcher-23  1 unread, not picked up

 click a row to focus · scroll to pan · a archived · q quits
```
(`44;97`=blue bg/white fg header, `43;30`=yellow bg/black fg "needs
attention" pill, `42;97`=green bg/white fg "working" pill, `100;97`=grey
bg/white fg "idle" pill — these are the exact assertions §3 flags as needing
a palette decision, since a yellow-on-black pill that's legible on a dark
terminal can wash out on a light one without testing.)

## 5. Recommendation

**(a), restrained — reverse video for the one thing that needs emphasis
(a selected row), dim for everything secondary, no fixed background
colors — is the one I'd pick.** The reason that decides it: it's the only one
of the three that doesn't need the light/dark palette question in §3 answered
first. (a) uses only relative techniques (reverse video, dim, the 8 remapped
ANSI colors) that are already proven safe by the current code's total absence
of light/dark bug reports. (b) and (c) both assert things that need real
testing against light and unusual-background terminals before they can ship,
and (c) specifically needs a two-palette (or detect-and-switch) system that
nothing in this research found already built and evidenced — that's new
design work, not a paint job. (a) is also the smallest actual change to
`layout()`: it adds a fill to one line-composition path and changes zero
column budgeting, versus (b)'s row-spanning-divider and per-row padding
change to every row, or (c)'s new "state as colored pill" concept that
`display_state`'s current column-width logic doesn't have a slot for.

If Andrew wants more visual ambition than (a) *and* is willing to accept
"detect the terminal background, choose one of two prepared palettes" as
real scope, (c)'s pill idea is the one worth revisiting — but that's a
follow-up decision, not this one.
