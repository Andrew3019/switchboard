# AUDIT 4c — the board and its click

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch `worker-2`).
Checked against main (`/Users/andrew/Code/switchboard`, `caa6d20`): `switchboard/board.py`,
`switchboard/panel.py` and `switchboard/cli.py` are **byte-identical** in both trees
(`diff <(git show HEAD:switchboard/board.py) …` → no output). So nothing below is fixed on
main, and evidence from either tree applies to both.

---

## Entry 1 — "`sb board` stays as it is right now." (DESIGN-TRUTH.md:174-179)

**Verdict: PARTIAL.** Three of the four claims are SATISFIED; the fourth (click focuses)
is satisfied in mechanism but defeated intermittently by the wrap bug in Entry 2. The two
"related" checks each turn up a violation.

### 1a. Shows the full tree — SATISFIED (with a scroll caveat)
- `board.layout` builds its rows from `status_mod.display_rows(snap.agents, …)` —
  `board.py:258` — i.e. the whole agent list of the snapshot, not a filtered subset.
- The snapshot is `sb status --json` verbatim, published by one collector and read by every
  pane (`panel.py:1-6`, `collector.py:91` `snapshot()`, `board.refresh` → `panel.read`,
  `board.py:352-368`). No per-board filtering anywhere.
- Caveat, not a violation: only a window of `height - CHROME` rows is drawn
  (`board.py:259-261`, `CHROME = display.board_chrome = 4`, `defaults/settings.toml:321`);
  the rest is reachable by scrolling and counted as `+N more below` (`board.py:303-304`).
  This matters for Entry 3.

### 1b. Nest structure — SATISFIED
- Indentation by depth: `label = ("  " * a.depth) + a.name` — `board.py:287`; the same
  depth padding is used for the collapsed row (`status.collapsed_label`, `status.py:831`).
- Ordering/depth is computed once in `status.display_rows` (`status.py:837-905`) and shared
  with `sb status`, so the two cannot disagree (`status.py:840-843`).

### 1c. Archived shows collapsed — SATISFIED
- `status.display_rows` replaces each *sealed* (fully archived) subtree with one
  `Collapsed` row (`status.py:808-818`, rule at `status.py:845`), rendered as
  `+ N archived · N need you` (`status.collapsed_label`, `status.py:821-834`) and drawn
  dimmed with no glyph/state/note (`board.py:280-285`).
- Default is collapsed: `display.show_archived = false`, read once in `status.py:192` and
  taken by the board at `board.py:256-258`; `a` toggles it per pane (`board.py:516-518`).

### 1d. Clicking a name focuses that agent — SATISFIED in mechanism, PARTIAL in practice
- Mouse reporting is turned on: `MOUSE_ON = "\033[?1000h\033[?1006h"` (`board.py:63`),
  written in raw mode at `board.py:494-496`.
- Decode → hit-test → focus: `parse_sgr` (`board.py:100-129`) → `is_left_click`
  (`board.py:136-137`) → `agent_at(rows, ev["row"])` (`board.py:317-328`, called at
  `board.py:525-526`) → `focus(a.name)` → `herdr agent focus <name>` (`board.py:371-383`).
- The row carries its own agent object (`layout` returns `(text, agent)` pairs,
  `board.py:237-244`), so an index can never resolve to a *different list entry* — but see
  Entry 2: it can resolve to a different *screen* line.
- Clicking a collapsed group is correctly refused rather than misdirected
  (`board.py:527-531`).

### Related — DESIGN-TRUTH.md:184-186 (only `sb start` focuses on spawn)
**SATISFIED for spawn paths, BROKEN for the flag.**
- Focus-on-spawn exists only in `Broker.start`/`_top` (`focus: bool = True`,
  `broker.py:477`; `self._focus(name, focus)` at `broker.py:566` and `:594`). `delegate`
  (`broker.py:2479`) never calls `_focus`; herdr calls made by spawn pass `--no-focus`
  (`herdr.py:267`, `:290`, `:313`, `:345`, `:364` — all default `focus=False`).
- BUT `sb workspace new --focus` exists — `cli.py:255`, threaded through at `cli.py:888`
  into `broker.new_workspace(focus=…)` (`broker.py:824`, `:881`, `:899`). DESIGN-TRUTH's
  rejected list says **"Focus as a flag … nothing can ask for it."** This is a live flag
  that asks for it.

### Related — DESIGN-TRUTH.md:172, :293 (every sb view is split with the board; no `--no-board`)
**BROKEN.** `--no-board` exists twice on the CLI:
- `cli.py:113-114` (`sb start --no-board`), `cli.py:256-257` (`sb workspace new --no-board`);
  threaded at `cli.py:711` and `cli.py:888` into `board=` (`broker.py:477`, `:825`,
  `:843`), which skips `_open_board` entirely. `board.py:4` and `board.py:40-41` still
  document it as a deliberate feature.

---

## Entry 2 — "The click is not working sometimes." (DESIGN-TRUTH.md:181-182)

**Verdict on Andrew's theory: the side panel is a CONTRIBUTING cause, not the cause.**
There is no side-panel *widget* anywhere — `switchboard/panel.py` draws nothing; it is the
collector/renderer snapshot mechanism (`panel.py:1-6`, `panel.py:212-247`) and contains no
layout code. What is real is that the board is opened as a NARROW SIDE PANE — 34 % of the
width, `BOARD_SHARE = 0.34` (`board.py:81`), inverted into herdr's ratio at
`board.py:409`. Narrow width is what makes the truncation path load-bearing, and the
truncation path is where the bug is.

### Root cause — `_fit` measures code points, not terminal columns
`board.layout` closes with the invariant the whole click rests on:

> "no line may ever wrap. A wrapped line pushes every row below it down by one, and the
> next click focuses the wrong agent — silently, and looking exactly like a correct click."
> — `board.py:311-313`

That invariant is enforced by `_fit` (`board.py:335-344`) using `_visible_len`
(`board.py:331-332`), which is `len()` of the escape-stripped string — **one unit per code
point**. Note text is pre-clipped by `status.clip` (`status.py:1018-1020`), which is also
`len()`-based. Neither accounts for display width, so any East-Asian wide character, emoji,
or (worse) any zero-width/combining character in a row makes the drawn line wider or
narrower in columns than the code believes.

Reproduced against this tree (`python3 -c` driving `board.layout` directly, width 44):

```
 3 codepoints= 25 termcols= 25   lead
 4 codepoints= 44 termcols= 45 << WRAPS  w1     ← task text contains an emoji
 5 codepoints= 43 termcols= 43   w2
```

Row 4 passes `_fit` (44 ≤ 44) and still occupies 45 columns, so the terminal wraps it.
Everything below shifts down one screen row while `rows` does not, and
`agent_at(rows, ev["row"])` (`board.py:317-328`) then returns the entry ABOVE what the human
clicked — or `None` for a padding line, in which case `msg = focus(a.name) if a else ""`
(`board.py:533`) sets an empty message and **the click silently does nothing**. That is
exactly the reported symptom: not an error, just nothing.

Why it is intermittent, and why it looks like the panel's fault:
- The text that overflows is agent-authored — `a.task`, `a.summary`, `a.blocked_why` via
  `note()` (`board.py:189-210`) — so whether any row is at the width limit depends on what
  agents happened to write.
- Column budget is `room = width - len(left) - len(lead)` (`board.py:295`), i.e. it shrinks
  with the pane. In a full-width pane nothing ever reaches the limit and the click always
  works; in the 34 % side pane most rows sit exactly at the limit, so one wide glyph tips a
  row over. **That is the side panel's real contribution — it is the amplifier, not the
  defect.**

### Ranked candidates, and what distinguishes them

| # | Candidate | Evidence | Distinguishing test |
|---|---|---|---|
| 1 | **Column-vs-codepoint width → wrapped row → off-by-N row mapping** (root cause) | `board.py:331-344`, `board.py:295-297`, `status.py:1018-1020`, reproduction above | Clicks are wrong/dead only for rows BELOW a row containing an emoji/CJK/combining char, and only in a narrow pane. Widen the pane and the same click starts working. |
| 2 | Multiplexer swallows the first click to focus the pane | Not evidenced in this repo — the board turns on 1000h/1006h and reads whatever arrives (`board.py:494-509`); nothing here can see whether herdr forwards a pane-inactive click. Also assumes pane-LOCAL coordinates, which `agent_at` requires and this repo never verifies (`scripts/06-board.py:29` merely assumed row 1 = first board row). | Click twice: if the second click always works while the board pane is unfocused, it is this, not #1. |
| 3 | `is_left_click` requires `button == 0` exactly | `board.py:136-137`. The probe that proved mouse forwarding masks the modifier/drag bits instead (`scripts/05-mouse.py:66-80`: `base = b & 0b11`, `b & 4/8/16/32`). So a click with shift/alt/ctrl held, or one the terminal tags with the motion bit, is dropped. | Reproducible on demand: a plain click works, the same click with a modifier held does nothing, anywhere on the board. |
| 4 | Click landed on a real agent but `herdr agent focus` failed (gone/archived pane) | `board.py:371-383` | Distinguishable by eye: this path always prints a reason into the status bar (`board.py:381-383`); #1 and #3 print nothing. |
| 5 | Stale `rows` after a resize | `rows` is rebuilt on every draw and SIGWINCH sets `dirty` (`board.py:481-484`, `:540-542`), so the window is ≤ one 0.25 s tick. Real but very narrow. | Only right after dragging the pane divider. |

Ruled out while looking: newlines in agent text cannot break the layout — `status.clip`
flattens all whitespace (`status.py:1019`). `CHROME` and the padding loop agree
(`board.py:259`, `:300`, `board_chrome = 4` at `defaults/settings.toml:321`), so the row
list is exactly `height` lines and is top-anchored.

Adjacent defect found in the same handler (reported, not fixed): the wheel handler updates
`top` without the clamp `layout` applies to its own copy — `top = max(0, top + step * 3)`
(`board.py:521`) vs `top = max(0, min(top, …))` (`board.py:260`). Scrolling past the end
inflates `top` unboundedly, so scrolling back up does nothing for as many events as were
over-scrolled.

---

## Entry 3 — "When something needs me, the board shows it, and `sb block`." (DESIGN-TRUTH.md:187-188)

**Verdict: PARTIAL.** A blocked agent is marked in three redundant ways, but it is never
pinned, sorted or counted where it cannot be missed, and it can be scrolled off the screen
entirely — which is a lot of weight for the only channel to carry (DESIGN-TRUTH.md:239-240:
a parent is NOT told its child blocked).

What is there, all evidenced:
- **Glyph** `◐`, ranked above every non-fatal state — `board.glyph`, `board.py:156-174`;
  coloured yellow via `_GLYPH_COLOR` (`board.py:177`).
- **Word + reason** in the note column: `BLOCKED — <why>`, ranked second only to `GONE` —
  `board.note`, `board.py:196-201`; yellow via `_note_color` (`board.py:213-218`).
- **A `←` lead marker** on any row that wants a person — `wants_you` (`board.py:180-186`,
  broader than `AgentStatus.needs_human` at `status.py:256-258`), drawn at `board.py:294`.
- **Header count**: `summary_line` includes `N blocked` (`status.py:1043-1050`), drawn into
  the board header at `board.py:263`.
- Colour is explicitly non-load-bearing — every distinction is also a glyph or a word
  (`board.py:83-85`), so `NO_COLOR` does not lose the signal.
- Collapse cannot silently bury one: a collapsed archived row carries
  `· N need you` (`status.py:815`, `:821-834`).

Where it falls short of "the board shows it":
- **No sort, no pin.** `layout` draws `display_rows` in tree order (`board.py:258-298`);
  nothing hoists a blocked agent. A blocked leaf sits wherever the tree puts it.
- **It can be off-screen.** Only `height - CHROME` rows are drawn (`board.py:259-261`); the
  rest collapses to a dim `+N more below` (`board.py:303-307`) that does **not** say how
  many of the hidden rows need a human — unlike the collapsed-archived row, which does.
  In the 34 %-wide, ordinary-height pane every agent lands in, a tree of any size hides
  rows, and the only channel for "something needs you" is then a dim `+7 more below`.
- **The richer readout is the one Andrew is not supposed to use.** `sb status` has a
  dedicated `NEEDS YOU` section listing them by name (`status.py:1079`); the board has no
  equivalent, and DESIGN-TRUTH.md:210 says `sb status` is not for Andrew.
- **Nothing is louder than anything else.** `BLOCKED` renders in the same column, same
  colour and same weight as `N unread` and `STALLED` (`board.py:213-218`). As a
  notification channel it is a status word among status words — no bell, no persistent
  banner, no unmissable state.

---

## Gaps

1. `_fit`/`_visible_len` (`board.py:331-344`) measure code points, not terminal columns —
   wide/zero-width characters in agent text wrap a row and silently break the click
   mapping. Needs a display-width measure (`east_asian_width`, combining marks, emoji) used
   by both `_fit` and `status.clip`.
2. Nothing sanitises agent-authored text of characters whose display width is ambiguous
   before it reaches a fixed-width row; `status.clip` (`status.py:1018-1020`) flattens
   whitespace only.
3. `is_left_click` (`board.py:136-137`) matches `button == 0` exactly and so drops
   modifier-held and motion-tagged clicks; it should mask like `scripts/05-mouse.py:66-80`.
4. Nothing verifies that the SGR row the board receives is pane-local; `agent_at`
   (`board.py:317`) assumes it. If herdr ever forwards window-absolute coordinates, every
   click in a non-top pane is off by the pane's origin.
5. Wheel scrolling does not clamp `top` (`board.py:521`) against the clamp `layout` applies
   (`board.py:260`), so over-scrolling makes the board feel dead on the way back up.
6. `--no-board` exists (`cli.py:113`, `cli.py:256`) though DESIGN-TRUTH.md:293 rejects it;
   `board.py:4` and `:40-41` still document it as intentional.
7. `sb workspace new --focus` (`cli.py:255` → `cli.py:888` → `broker.py:824`) is focus as a
   flag, which DESIGN-TRUTH.md:295 rejects.
8. The board never hoists, pins or sorts an agent that needs a human (`board.py:258-298`) —
   as the sole notification channel it should.
9. The `+N more below` tail (`board.py:303-307`) does not report how many hidden rows need
   a human, though the collapsed-archived row already sets that precedent
   (`status.py:821-834`).
10. The board has no `NEEDS YOU` list; only `sb status` does (`status.py:1079`), and that
    readout is explicitly not Andrew's (DESIGN-TRUTH.md:210).
