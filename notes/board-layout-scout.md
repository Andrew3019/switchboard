# Scout: how `sb board` is shaped, for the five brief items

Reconnaissance only — no behaviour changed. Source: `notes/board-layout-brief.md` (items
1-4) plus item 5, added mid-task via `sb tell` (pane-focus highlight). Checked against
code, not against `learnings/board-*.md` or other docs, which are untrusted per the ground
rules — I did not read those files.

## 1. Where the rendering lives

Two renderers draw the same `status.display_rows()` output:

- **`switchboard/board.py`** — plain-text fallback, used when `rich` is absent or the pane
  is too small. `layout()` (~L424-581) draws the whole frame: header, tree, footer. It has
  **no bracket/gutter drawing at all** — `_starts_group`/`_is_group` only handle
  indentation and blank-line breaks between top-level workspace groups, not brackets.
- **`switchboard/richboard.py`** — the real one Andrew looks at (`rich`-based). `layout()`
  (~L456-561) is the equivalent frame-builder. This is the only file with the bracket
  logic: `group_runs()` (L395-406), `gutter_column()` (L409-448), and the per-row drawer
  `_row()` (L619-680).
- **`switchboard/status.py`** — not a renderer, but upstream of both: `display_rows()`
  (L1833+) builds the collapsed-archive rows both renderers consume, and `Collapsed`
  (L1804) / `collapsed_label()` (L1817) define what an archived-summary row *is*.

### File collisions across items 1, 2, 4, 5

| item | touches |
|---|---|
| 1 (archive collapse) | `richboard.py`: `_row()` (is_group branch), `group_runs()`. Maybe `status.py`: `Collapsed` needs a `workspace` field. |
| 2 (wrap tree in "Agents" section) | `board.py` `layout()` head area, `richboard.py` `layout()` head area (~L496-521) — both files, top-of-function only |
| 4 (bracket to the right) | `richboard.py`: `gutter_column()` only — one line changes |
| 5 (focus highlight) | `richboard.py`: `_row()` (new styling branch), `layout()` (to compute/pass "is this row focused") |

**Items 1 and 5 both land inside `_row()`** — real collision risk if split across two
agents; whoever does 1 will touch the `if board._is_group(row):` branch and the mark
handling, and 5 needs to touch the same function's styling for every row. Recommend one
agent owns `_row()` for both, or do them sequentially, not in parallel.

Item 4 only touches `gutter_column()`, a different function in the same file — a merge
conflict is possible (same file) but not a logic collision (different function).

Item 2 only touches the head section of `layout()` in both files, before the tree body —
separable from 1/4/5's row-level work, but shares files, so still sequence carefully or
have the same agent take 2+3 together (3 also needs a new top section).

`board.py` (plain fallback) is essentially untouched by 1, 4, 5 — those are rich-only.
Item 2 is the one change that must touch `board.py` too, since the plain renderer has its
own header code.

## 2. Items 1 and 4 in detail

### Item 1 — archived row: collapse level, indent, bracket

**What already works (in `status.display_rows`, L1833-1957):** the collapse-to-level logic
is already correct. It walks the tree, recurses into a live parent's children, and only
merges a **sealed subtree** (an archived node whose whole subtree is archived) into one
`Collapsed(depth, count, needs_human)` row, placed right after its visible siblings at
that level. So "collapse to the level where there are still active agents, last row of
that level" is already the behaviour — Andrew's brief text describes what's already true
here.

**What's actually broken is the drawing**, in `richboard.py`:

- `group_runs()` (L395-406) decides which consecutive rows share one workspace bracket. It
  reads `row.workspace`, but does `ws = None if board._is_group(row) else row.workspace` —
  a `Collapsed` row has no `.workspace` at all, so it's always treated as `ws=None`, which
  **ends whatever run it follows**. A collapsed-archive row inside a workspace grouping
  never joins that workspace's bracket.
- `_row()` (L619-631), when `board._is_group(row)` is true, returns immediately after
  drawing `"   " + status_mod.collapsed_label(row)` — it **ignores the `mark` parameter
  entirely**, so even if `group_runs`/`gutter_column` did produce a bracket char for that
  row, `_row` would never draw it.
- Indentation is separately hard-coded twice: `collapsed_label()` in `status.py` prefixes
  `"  " * c.depth` (2-space unit), while every other row's indent uses `board.INDENT` (4
  spaces, `_row()` L640: `board.INDENT * row.depth`). These disagree, so even the
  indentation that IS drawn for a collapsed row doesn't line up with its siblings' name
  column.

**Roughly what has to change:**
1. `status.Collapsed` needs enough to know its workspace — either add a `workspace` field
   (set to the group's shared workspace, `None` if the group spans none/mixed) or leave it
   to the renderer to look up from context.
2. `group_runs()` needs to treat a `Collapsed` row as belonging to the run it's the tail
   of, instead of always ending the run.
3. `_row()`'s `is_group` branch needs to build its indent from `board.INDENT * row.depth`
   (matching every other row) instead of `collapsed_label`'s own 2-space indent, and needs
   to apply `mark` the same way the ordinary-row branch does.
4. `gutter_column()` itself may not need to change for this item — it operates on rows by
   depth already, indifferent to Collapsed vs agent, once `group_runs` is fixed to include
   the Collapsed row in the run.

### Item 4 — bracket as far right as possible

Current logic, `gutter_column()` (L409-448):
```
depth = min(_row_depth(rows[i]) for i in range(first, last + 1))   # shallowest row in the run
off = len(board.INDENT) * (depth - 1)                              # leftmost column of that row's own indent block
```
`off` is a column index into the row's rendered indentation, where the bracket char
replaces a space. Every row in a bracketed run has *at least* `INDENT_width * depth`
columns of indent (by definition of `depth` being the run's minimum), so any column from
`0` to `INDENT_width * depth - 1` is safe to draw into for every row in the run — that's
the whole available range. The current code picks the **start** of the last 4-space
indent block (leftmost valid column). "As right as possible" is just picking the **end**
of that same block instead — i.e. `off = len(board.INDENT) * depth - 1` (the column
directly before the glyph/name for the shallowest row).

This is a one-line, single-function change, confined entirely to `gutter_column()`. The
`off = -1` branch (shared workspace at depth 0) is untouched — it's already the only
column available there (the single leading space), so left and right coincide.

## 3. Item 3 — new top stats section: what's actually available

Checked `switchboard/store.py` schema and how `switchboard/status.py` / `broker.py` /
`herdr.py` populate it.

**(a) Live CPU/memory for the sb process tree — available-expensively, not built.**
There's no PID/CPU/memory registry anywhere in the store. The closest existing machinery
is `switchboard/live.py`, which shells out to `lsof -a -d cwd -F pcn` to find processes
running under a given checkout directory (used by `broker._live_under` for the
close-workspace safety gate), plus `broker._parents()` / `_ancestry()` which read `ps` to
walk parent-pid chains for the *same* gate. Neither captures CPU or RSS today — that would
mean a **new** `ps -o pid,rss,%cpu` (or similar) subprocess call, filtered to the pid tree
rooted at every agent's pane. Cost matters: `herdr.py`'s own comments note the board
already re-reads status roughly **twice a second**, and "every status read is a
subprocess" is called out as a real cost concern there. Adding a `ps` scan on every
refresh is the same category of cost again, so this is real but not free — it'd want its
own cheaper cadence (e.g. once every few seconds, cached) rather than syncing to the
board's own refresh rate.

**(b) Session stats from the store — mixed.**
- **Turns**: `hooks.py` L267 logs a `turn_start`/`turn_end` event pair (`events` table,
  `kind`, `agent`, `created_at`) on every real turn boundary. Counting `turn_end` events
  with `created_at` in the last hour, per agent or fleet-wide, is a cheap indexed query —
  **available-cheaply**.
- **sb calls**: there is no generic "every `sb` invocation" log. `store.log_event` is
  called only from specific sites (`plugin` runs, `workspace_*`, `board_open/close`,
  `cleanup`, a handful of failure paths) — not from every CLI command. A true "N sb calls
  in the last hour" number isn't tracked anywhere. The nearest honest proxy is the
  `messages` table (`ask`/`tell`/`done`/`failed` rows, with `created_at`), which is a real,
  cheap count, but it's "inter-agent messages sent," not "sb commands run" — **available-
  cheaply as a proxy, not available as the literal thing Andrew described**.
- **Agent spawns**: `agents.created_at` is on every row — counting spawns in the last hour
  is a trivial cheap query. Also directly visible as a `kind="start"` event.
  **Available-cheaply.**
- **LOC / non-docs LOC**: nothing in the store tracks this at all — it isn't a switchboard
  concept, it's a fact about each workspace's git history. See (c).

**(c) PRs and LOC — available-cheaply, but from git, not the store.**
I found no code anywhere that shells to `gh` or tracks PR state — every mention of "pull
request" I found (`broker.py`, `cli.py`, `roles.py`, `models.py`) is prose in agent-facing
protocol text (the "how to land work" instructions baked into role prompts), not tracking
code. So: PRs opened/merged — **not available** without new instrumentation, and it'd need
either `gh` API calls (network + auth, per workspace) or watching the protocol's own
`sb done` messages for PR URLs (fragile, agents don't always mention it in a fixed
format).

For LOC, `workspaces.checkout` already gives a real filesystem path per workspace, so
`git diff --stat` / `git log --since=1h --numstat` per checkout is a plain, cheap, local
git subprocess — no new data model needed. Non-docs LOC would need a path filter (e.g.
exclude `*.md`, `notes/`, `learnings/`) layered on top of that diff, which is a policy
choice, not a data-availability problem.

**Summary table:**

| stat | cost |
|---|---|
| live CPU/mem per agent | available-expensively (new `ps` scan, no registry today) |
| turns in last hour | available-cheaply (`events`, `turn_end`) |
| sb calls in last hour | not available as literal count; `messages` count is a cheap proxy |
| agent spawns in last hour | available-cheaply (`agents.created_at` / `kind="start"` events) |
| LOC / non-docs LOC changed | available-cheaply (git subprocess per `workspaces.checkout`) |
| PRs opened/merged | not available (no tracking exists; would need `gh` calls or parsing `sb done` text) |

**What I'd actually put in 3 lines:** turns + spawns in the last hour (both free, both
already timestamped events), agent counts (already computed every refresh via
`status.summary_bits`, just currently only shown in the header line, not broken out), and
LOC changed via a cheap git diff per active workspace. I'd leave PRs and live CPU/mem out
of the first cut — PRs need new tracking, and CPU/mem needs a new subprocess cadence
decision — and flag them as later additions if Andrew still wants them once the cheap
stuff is up.

## Item 5 (added mid-task): pane-focus row highlight

**(a) Can the board tell which agent's pane the viewer is looking at?** Largely no, and
what's there is partial. Switchboard has **no direct tmux/terminal access anywhere** — I
grep'd for `tmux` outside `herdr.py` and found nothing; every terminal operation goes
through the `herdr` CLI, which abstracts the actual multiplexer away. `herdr.Agent` (the
parsed `agent list`/`agent get` record, `herdr.py` L172-207) carries a `state` field with
possible values `idle | working | blocked | unknown | done` — no `focused` field exists in
what's parsed, and I found no `"focused"` key anywhere in the codebase or test fixtures.

The one real signal: `herdr.py`'s own docstring (L1000-1003, around `report_state`) says
herdr derives **`done` = idle AND not yet viewed/focused**, and that focusing a done
pane's tab flips its reported state back to `idle`. So an agent reading `idle` (not
`done`) *may* mean "idle and currently being looked at" — but this is inferential, only
documented for the idle case, and I found no equivalent distinction for a `working` agent
(nothing suggests herdr reports a pane differently depending on focus while it's busy). So
today: **no reliable "which pane is focused" query exists for a working agent; a weak,
partial signal exists for idle ones via the done/idle distinction.** `board.focus()`
(`board.py` L779) is a one-way write (`herdr agent focus <name>`), not a read — clicking a
row in `sb board` sets focus, it doesn't observe it.

**(b) Where a whole-row background highlight would go.** `richboard._row()` (L619-680)
builds each row as a `rich.text.Text`, appended piece by piece with per-segment
foreground styles (glyph colour, state colour, etc.) — there's no existing whole-row
background. But the *pattern* already exists elsewhere: `_bar()` (L769-773) draws a
full-width filled bar (used for the header and the NEEDS YOU divider) by padding text to
the full column width and wrapping it in one `Text(..., style=...)`. `_row()`'s rows are
**not** padded to the pane's full inner width today — the tail is clipped to whatever room
is left, and short rows just stop, leaving unstyled trailing space. To highlight a whole
row you'd need to (1) add a "is this row focused" boolean threaded from `layout()` down to
`_row()` alongside the existing `mark` parameter, and (2) pad the finished line out to
`inner` width and apply a background style (e.g. `line.stylize("on <colour>")`) across the
whole thing, not just the printed characters — otherwise the highlight would visibly stop
partway across the row.

**(c) Collides with 1 and (less so) 4, not meaningfully with 2.** Same function,
`_row()`, as item 1's fix — see the table above. Recommend the same agent do 1 and 5
together, or do them one after another rather than two agents editing `_row()` at once.
