# Board inventory — every UI element, every row field

Research only, no design opinions. Sources read directly (not docs): `switchboard/board.py`,
`switchboard/status.py`, `switchboard/panel.py`, `switchboard/collector.py`,
`switchboard/models.py` (checked, irrelevant — model-tier config, not board data), and
`scripts/board_mockup.py` on branch `worker-25` (commit `1bb7541`, not merged). `DESIGN-TRUTH.md`
lines 193–235 confirm current scope for `sb board` / `sb status`.

All three renderers (`board.layout`, `status.render`, `board_mockup.render`) are draws over one
join: `status.collect()` builds an `AgentStatus` per agent from the store + herdr + the activity
signal; `status.Snapshot` holds the list; `panel.py` is the transport (one collector process
publishes `Snapshot.as_dict()` as JSON, every panel reads the file — no new fields, no new logic).

---

## 1. Page-level elements

In draw order, interactive board (`board.layout`, `board.py:377`) unless noted.

| # | Element | Shows | Appears when | Driven by |
|---|---|---|---|---|
| 1 | Head line | `switchboard  ·  ` (brand, dropped first if width is tight) + `summary_bits` joined by ` · `: `N alive`, then any of `stalled/gone/blocked/at a prompt` counts that are non-zero, then `unread`/`undelivered` if non-zero, then `N agents`, then `N hidden` if any | Always, one line. Counts drop from the tail (not the alive headline) if the pane is too narrow to show them all | `status.summary_bits(snap)` — same function `sb status`'s `summary_line` uses, so the two cannot disagree |
| 2 | Blank line | separator | Always | `board.py:471` |
| 3 | "(nothing running — sb start)" note | placeholder | Only when there are zero agents at all (not "zero visible") | `board.layout`, `note_text` param or hard-coded fallback |
| 4 | Group break | one blank line | Above every row at tree depth 0 or 1 (a root or a direct child), except never above the very first row on screen | `board._starts_group`; costs 2 "lines" for scroll-math purposes |
| 5 | Agent row | see §2 | One row per agent in `display_rows` (not per row in the raw tree — archived subtrees may be collapsed away) | `status.display_rows`, iterated in `board.layout`'s window loop |
| 5a | ↳ task line | secondary line | See §3 | n/a — board.py does NOT draw a second line at all (see §4) |
| 6 | Collapsed-archive line | `"+ N archived"`, plus `" · M need you"` if any of the hidden agents individually `needs_human` | One row per *collapse root* (a maximal sealed sub-tree) instead of drawing its whole hidden subtree, when `show_archived` is off | `status.display_rows` → `status.Collapsed` → `status.collapsed_label`; `board.layout` draws it dim, un-clickable (`emit(..., a)` where `a` is the `Collapsed` object; `agent_at` returns it but `board.main`'s click handler special-cases it to the message "press a to show archived") |
| 7 | Padding blank lines | fill to `height - 2` | Whenever the drawn content is shorter than the screen | `board.layout:523` |
| 8 | Scroll/footer tail line | `"+N more below"` if rows are hidden below the window, else `"scroll ↑"` if scrolled down from the top, else empty — but overridden entirely by `note_text` (the panel's own staleness/error note, e.g. `"snapshot 6s old"`) whenever one is set and there are agents to show | Always one line | `board.layout:526-530`, `panel.Reading.note` |
| 9 | Help/status-bar line | `"click a row to focus it · scroll to pan · a archived · q quits"` + `"   " + msg` if a message is pending (from a click's focus result, or "press a to show archived") | Always | `board.layout:531-532` |

Never-wrap invariant: every line is finally passed through `_fit` (column-measured clip), so no
line can push the ones below it down — that's what makes the click→row mapping trustworthy.

`sb status` (`status.render`, `status.py:1601`) has a different top-level shape entirely — see §4.

`board_mockup.py`'s top-level shape (`render`, line 433) is a single bordered `rich.Panel`:
header bar (styled, filled background) → blank → rows (with group breaks, collapsed markers, and
a genuine second dim line per agent) → blank → a styled `NEEDS YOU` bar (up to 6 named agents +
"+N more") → blank → a footer note (`"live snapshot · mockup, not the board"` or similar,
plus data-source note). No scroll, no click, no mouse — explicitly out of scope per its docstring.

---

## 2. The agent row — every field

Interactive board draws one row per agent as (`board.layout:507-521`):

```
 <glyph> <name, indented>  <state>  <idle age>  <lead><detail bits…>
```

### Field-by-field

| Field | What it is | Source | Possible values | Shown vs. omitted | Width |
|---|---|---|---|---|---|
| **glyph** | 1-char at-a-glance status | `board.glyph(a)` | `✗` gone · `◐` at_prompt/blocked · `◌` stalled/signal_drift · `○` finished · `?` alive unknown · `●` else (see table below) | Always drawn, colour-coded via `_GLYPH_COLOR` | 1 col fixed |
| **name** | agent name, indented `"  " * depth` | `a.name`, `a.depth` | free text | Always | Measured: `w_name = max` visible length of `"  "*depth+name` across all rows in the current window (padded to that) |
| **display_state** | one state word | `AgentStatus.display_state` property (see §"states" below) | see states table | Always | Measured: `w_state = max` across window |
| **idle age** | time since last activity, right-aligned to 5 cols | `status.fmt_age(a.idle)` | `Ns` / `Nm` / `NhMM` / `NdHHh` | Always | Fixed 5 cols (`>5`) |
| **lead arrow** | `"← "` or `"  "` | `wants_you(a) or bits[0][2]=="mail"` | arrow coloured by the first detail bit's colour, or two spaces | Drawn only if `detail_bits` is non-empty | 2 cols |
| **detail bits (tail)** | up to 3 ranked pieces, see below | `board.detail_bits(a)` composed by `_compose` | — | Whatever fits; see priority rules below | Whatever's left of the line width |

### Glyph — exhaustive

| Glyph | Meaning | Condition (first match wins, in this order) |
|---|---|---|
| `✗` | GONE — herdr has no such agent | `a.gone` |
| `◐` | waiting on a human, either in-TUI or via `sb block` | `a.at_prompt or a.blocked` |
| `◌` | idle with nothing running and no explanation (STALLED), or session died mid-turn (NO SESSION) — one glyph for both, the tail note says which | `a.stalled or a.signal_drift` |
| `○` | finished | `a.finished` |
| `?` | herdr couldn't be reached at all | `a.alive is None` |
| `●` | healthy / working | everything else |

### `display_state` — the state word

Computed by `AgentStatus.display_state` (`status.py:376`), NOT the raw store `state` column
verbatim, specifically to avoid a row saying `working` in its state column while its tail says
`STALLED`. Rule:

- if `state` isn't one of the "running" states (`working`/`blocked` by config), show the store's
  word as-is — that covers `done`/`failed`/whatever a terminal word an agent wrote for itself
- else if herdr says the agent isn't listed at all (`alive is False`) → `idle`
- else if switchboard's own turn signal (`agents.turn`) has a value → `working` or `idle`
  depending on whether it says `working`/`idle`
- else if herdr is unreachable (`alive is None`) → fall back to the store's word
- else (herdr is the only signal) → `idle` if herdr's own state is idle-like, else the store's word

So the finite word-set actually observed in this column is: whatever the store's `state` column
can hold (config-defined closed vocabulary — `working | blocked | done | failed`, per
`status.py:159` comment) union `idle` (a derived, not-stored word this property can produce).

### Marker — the row's #1-priority trouble note (`board.marker`, exhaustive, ranked, only one shown)

| Marker text | Condition |
|---|---|
| `GONE — herdr has no such agent` | `a.gone` |
| `AT PROMPT — waiting on you` | `a.at_prompt` |
| `BLOCKED — <reason, or "no reason recorded">` | `a.blocked` |
| `STALLED — idle <age>` | `a.stalled` |
| `NO SESSION — died mid-turn, pane still open` | `a.signal_drift` |
| *(none)* | none of the above |

### Mail note (`board.mail_note`, rank 2)

`"mail: UNDELIVERED <n>, <age>"`, `"mail: <n> unread"`, or both joined by ` · ` — or empty. Built
from `a.waiting_to_be_rung`/`a.undelivered`/`a.undelivered_age` and `a.unread - a.undelivered`
("told" — mail that was rung but not yet read).

### Tail note (`board.tail_note`, rank 3, least priority)

- `"done: <summary>"` if `a.finished and a.summary`
- else `a.idle_excuse` if set — one of the three phrases computed in `status.collect`:
  `"awaiting first task"`, `"waiting on children"`, `"starting up"` (only ever set on a row
  that is idle at all)
- else `a.task or ""`

### Priority order when space is short (`board.detail_bits`, board.py:281-306)

Exactly three ranked bits, marker first:

1. **marker** — something is wrong, only a human fixes it
2. **mail_note** — undelivered/unread mail, kept visible even beside a marker because it's
   often what would *resolve* rank 1
3. **tail_note** — done-summary / idle-excuse / task head; dropped first, since it's available
   elsewhere (the agent's own pane)

`_compose` (board.py:309) fills columns left to right in that order; a piece below `_MIN_BIT`
(10 cols) is dropped entirely rather than shown as a bare ellipsis; a non-mail piece gives up up
to `_MAIL_RESERVE` (22 cols) of its own room specifically so MAIL isn't crowded out by a long
marker text; nothing is ever reserved for tail (rank 3) — it's what gets cut first.

### Width

- **name column**: measured across every agent row currently in the scroll window
  (`w_name = max(...)`), not fixed globally — so it can change as you scroll or as agents finish
  and shrink the window's longest name.
- **state column**: same, measured (`w_state`).
- **age column**: fixed at 5 characters, right-aligned.
- **glyph**: fixed 1 column, spaces around it fixed.
- **detail-bit region**: whatever's left of terminal width after the fixed/measured columns —
  the entire priority/clipping machinery above exists because this remainder is often only
  enough for one bit at 60 columns.

---

## 3. The secondary line(s)

**The interactive board draws NO second line per agent at all.** Task and summary are folded
into the tail's rank-3 `tail_note` bit, competing for the same single remainder of the line as
the marker and mail. This is explicitly called out as a difference in the mockup's own docstring
(`scripts/board_mockup.py:24-29`): a real second line would need `layout()` to charge 2 screen
rows for that agent and `emit()` to record the owner on both — a layout change, not implemented.

`sb status` and the mockup DO draw a second (and sometimes third) line:

- **`sb status`** (`status._what`, status.py:1646): under each row,
  - `↳ <task, clipped to TASK_CLIP chars>` if `a.task` is set
  - `✓ <summary, clipped>` **in addition**, if `a.finished and a.summary` — so a finished agent
    with both a task and a summary gets *two* extra lines, not a choice between them. No
    `idle_excuse` line exists in `sb status` at all — that field is board/mockup-only.
- **`board_mockup.py`** (`secondary`, line 320): exactly ONE extra dim line, priority-ordered:
  `✓ <summary>` if finished-with-summary, else `· <idle_excuse>` if set, else `↳ <task>` if set,
  else nothing — i.e. the same three-way priority the interactive board's rank-3 tail_note uses,
  just given its own line instead of competing with marker/mail.

Truncation: `sb status`'s `clip()` (status.py:1663) is a plain character-count clip
(`TASK_CLIP`, a config setting) with `…` appended, flattening whitespace first — NOT
column-aware like the board's `_clip`/`_clip_cols`. The mockup's `clip()` (mockup line 97) is
column-aware like the board's. So `sb status`'s task/summary lines could in principle mis-measure
against a wide character, where the board and the mockup would not.

---

## 4. What differs between the three renderers

| Aspect | Interactive board (`board.py`) | `sb status` (`status.py`) | Mockup (`board_mockup.py`, branch `worker-25`) |
|---|---|---|---|
| Second line per agent | None — task/summary compete with marker/mail on one line | Two possible extra lines: `↳ task` and, separately, `✓ summary` | One extra line, one of `✓ summary` / `· idle_excuse` / `↳ task` |
| `idle_excuse` shown at all | Yes, folded into tail_note rank 3 | **No** — `_what()` has no idle_excuse branch | Yes, on its own line |
| Columns shown | glyph, name, state, idle age, tail bits | AGENT / ROLE / STATE / HERDR / MAIL / AGE / IDLE / WORKSPACE, plus `_flags()` suffix | glyph, name, state pill, idle age, tail (marker/mail) |
| `ROLE` column | not shown | shown | not shown |
| `HERDR` column (raw herdr state, distinct from `display_state`) | not shown | shown, via `_herdr_cell`: `?` if alive unknown, else herdr's own state or `-` | not shown |
| `WORKSPACE` | not shown | shown | not shown |
| `AGE` (since created, not idle) | not shown | shown | not shown |
| Trouble notation | inline tail bits, ranked/clipped, one glyph | `_flags()` suffix: `<< STALLED`, `<< GONE`, `<< NO SESSION`, `<< UNDELIVERED n, age`, `<< AT PROMPT`/`<< BLOCKED` — ALL applicable flags shown, not just the top-ranked one | same rank-1/2 idea as the board (`marker`/`mail_note`), reimplemented over dicts |
| Word for "died mid-turn, pane still open" | `NO SESSION` (glyph note) | `<< NO SESSION` (same word, in `_flags`) | same |
| Mail wording | `"mail: UNDELIVERED n, age"` / `"n unread"` | different phrasing in `_flags` (`<< UNDELIVERED n, age`) and a completely different, longer explanation block under `DRIFT`/`UNDELIVERED` sections | same short board wording (reused verbatim) |
| Group-break rule | blank line above every depth ≤1 row (`_starts_group`) | none — plain nested tree, indentation only | same as the board (blank line at depth ≤1) |
| Archived collapse | one `+N archived[· M need you]` row, un-clickable | same collapsing logic (`display_rows`, shared function) — same label text | same collapsing logic reimplemented over dicts, same label text |
| `NEEDS YOU` section | **absent** — the board has no such block; a stalled/blocked/etc. agent is only findable by scanning tail markers | present, full detail with per-reason phrasing and suggested commands (`sb tell`, `sb inspect`) | present, compact styled bar, up to 6 names + reason, "+N more" |
| `UNDELIVERED` / `DRIFT` explanatory sections | absent | present, multi-line explanatory prose plus a per-agent list | absent |
| Summary/count line | in the header, `summary_bits` joined, brand-name competing for space | `summary_line` — same `summary_bits`, always shown in full width (no brand/name competing) | header bar version of `summary_bits`, fewer fields (`alive`/`at_prompt`/`blocked`/`unread` only — drops `stalled`/`gone`/`undelivered`/`hidden`) |
| Click / scroll / focus | yes — the whole point of this renderer | n/a (plain text) | explicitly NOT implemented (no mouse, no click, no scroll) — noted as a scope difference in its own docstring |
| Width measurement | column-aware throughout (`_visible_len`, handles CJK/emoji/ZWJ) | **character-count** in `clip()` for task/summary lines — the rest of the table columns use plain `len()` padding too | column-aware (`vlen`, a smaller reimplementation) |
| Colour | ANSI codes, disabled by `NO_COLOR` | none — plain text only | `rich` styles (filled-background "pills"), disabled by `NO_COLOR`, dark-terminal-only per its own docstring |
| Data source | live: reads panel's published snapshot every `REFRESH` interval via a Supervisor that starts a collector if needed | live: calls `status.collect()` directly (own herdr call + store read) — not through the panel/collector | reads the same published snapshot file the board reads, **falls back to nine lines of hard-coded `SAMPLE` data** if none exists |

Confirmed scope statement (`DESIGN-TRUTH.md:195-199`, 2026-08-09): "`sb board` stays as it is
right now… That is all it needs for now; the rest of what it has works fine and auditing it
comes later" — i.e. the interactive board's current shape (no NEEDS YOU block, one line per
agent, no ROLE/WORKSPACE/AGE columns) was a deliberate stopping point, not an oversight, as of
that date.

---

## 5. Worked example

Live `sb status` output, captured 2026-08-14, annotated. (Full raw output is longer; three rows below.)

```
board-fix        orchestrator  idle      done        -    1h22     36s  board-fix
    ↳ Await my instructions.
```

| Field | Value | Meaning |
|---|---|---|
| AGENT | `board-fix` | `a.name`, depth 0 |
| ROLE | `orchestrator` | `a.role` |
| STATE (`display_state`) | `idle` | store `state` is `working` (a root, no ended_at) but `agents.turn` (or herdr) says no turn is running → falls to `idle` |
| HERDR | `done` | herdr's own raw state for the pane — herdr's *display* state for "idle and not yet looked at" (per status.py:112-114) |
| MAIL | `-` | `a.unread == 0` |
| AGE | `1h22` | `fmt_age(now - created_at)` |
| IDLE | `36s` | `fmt_age(now - last_activity)` |
| WORKSPACE | `board-fix` | `a.workspace` |
| flags suffix | *(none shown)* | not stalled/gone/etc — this is the "awaiting first task" idle_excuse case (a fresh orchestrator waiting to be told something), which `sb status` does not render at all (§3/§4) |
| `↳` line | `Await my instructions.` | `a.task`, clipped |

```
  researcher-22  researcher    done      idle        1     39m     33m  researcher-22
      ↳ Read notes/task-board-ui-current.md and do exactly what it says.
      ✓ Task said to read notes/task-board-ui-current.md and do exactly what it says, but that file doe…
```

| Field | Value | Meaning |
|---|---|---|
| STATE | `done` | store state itself is a FINISHED word, not RUNNING, so `display_state` returns it verbatim — no herdr/turn join involved |
| HERDR | `idle` | herdr's raw state — differs from STATE, both legitimately, because STATE is the terminal self-report and HERDR is what the pane currently looks like |
| MAIL | `1` | one unread message (its parent hasn't been read? — actually this is mail waiting *for* researcher-22, i.e. `a.unread`) |
| AGE / IDLE | `39m` / `33m` | created 39 min ago, quiet for the last 33 |
| `↳` and `✓` lines | both present | this agent is `finished` (`a.finished`) with both a task and a summary, so `sb status` prints both extra lines — on the interactive board these two would be competing for one tail slot, and the summary (rank 3, `tail_note`'s `finished+summary` branch) would win outright over the raw task text |
| On the board's own row this agent would show | glyph `○` (finished), tail: no marker (not gone/blocked/stalled), mail_note `"mail: 1 unread"` (rank 2), and rank 3 (`done: <summary>`) only if columns remain after the mail bit | the `NEEDS YOU` list on `sb status` (not present on the board at all) separately lists `researcher-22  1 unread, not picked up` |

```
  worker-25      worker        done      done        -     11m      3m  worker-25
      ↳ Read the file at absolute path /Users/andrew/Code/switchboard/notes/task-board-mockup.md (it is…
      ✓ Built scripts/board_mockup.py + notes/board-mockup.md, committed on worker-25 (1bb7541, not pus…
```

| Field | Value | Meaning |
|---|---|---|
| MAIL | `-` | no unread — despite being `finished`, nothing is owed to it, so it does NOT appear in `NEEDS YOU` |
| STATE / HERDR | `done` / `done` | agree this time — both say the same terminal word |
| `✓` line | truncated with `…` at `TASK_CLIP` characters — this is the worker whose mockup work this inventory cross-references | confirms `sb status`'s clip is a plain character count, not column-aware |

Footer of the live capture: `5 alive · 2 unread · 9 agents · 347 hidden` and a `NEEDS YOU` block
listing exactly the two agents above with unread mail (`researcher-22`, `researcher-23`) — the
347 hidden figure shows how large the archived tail of this particular fleet already is, all of
it collapsed to the single `+ 4 archived` row seen in the live tree (only 4 *direct* collapse
roots hide 347 agents total — collapse counts whole subtrees, not top-level children).

---

## Surprises worth flagging

- The interactive board — the one thing Andrew actually looks at day to day per
  `DESIGN-TRUTH.md:233` — has no `NEEDS YOU` section, no ROLE/WORKSPACE/AGE columns, and no
  second line. Everything about *why* an agent needs attention has to fit into one shared,
  ranked, space-competing tail region with the mail note and the task text. `sb status`, which
  DESIGN-TRUTH says is "for agents" not Andrew, is actually the richer, more explanatory of
  the two views.
- `idle_excuse` (the three-phrase "why is this idle-but-fine" note) is rendered by the board and
  by the mockup, but is completely absent from `sb status`'s output — a genuine three-way
  inconsistency, not just wording.
- `sb status`'s task/summary-line truncation (`status.clip`) is a plain character count while
  every other clip in the codebase (board, mockup) is column-aware; a wide character in a task
  or summary could measure differently there than anywhere else.
- The mockup's header/count line drops four of the eight `summary_bits` fields (`stalled`,
  `gone`, `undelivered`, `hidden`) that both real renderers show — it re-derives its own smaller
  `summary_bits` from scratch rather than reading the shared one.
