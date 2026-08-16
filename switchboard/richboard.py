"""The board's LOOK, drawn with `rich`. A renderer, and a drop-in for `board.layout`.

`layout()` here has exactly the signature and exactly the contract `board.layout` has:
snapshot in, `[(text, owner)]` out, one entry per screen line, at most `height` of them.
That is the whole of the seam. `board.draw` asks `available()` which renderer to use and
indexes the result the same way either way, so `agent_at` — and every click — is unchanged.

WHY A SEPARATE MODULE AND NOT AN EDIT TO `board.py`. `rich` is switchboard's first ever
runtime dependency, and it is an OPTIONAL one (see `available`). Keeping the two renderers
in two files is what makes "fall back to the plain one" a real, tested path rather than a
promise: `board.py` imports nothing from `rich` at any depth, so a machine without it runs
the board it has always run. Nothing else in switchboard imports this.

The look is `scripts/board_mockup.py` on branch `worker-28`, which Andrew approved — a
rounded panel, a filled header bar, one line per agent, state as a plain coloured word, a
zero-width workspace gutter, a NEEDS YOU section, and the whole thing filling the pane.
The rules for what a row SAYS are not re-decided here: `board.glyph`, `board.marker`,
`board.mail_note` and `board.wants_you` are imported, so the two renderers cannot come to
disagree about which agent is in trouble.

Four things the mockup did not have to do, and this does:

- **Scrolling.** `top` is an offset into display rows, as in `board.layout`. The window
  spends a line on `↑ N above` and on `+ N more below` when there is something either way.
- **A gutter across a scroll boundary.** Runs are computed over the WHOLE row list and
  drawn by absolute index, so a group whose top is scrolled off shows `│` where its `╭`
  would have been. A corner means "this is where the group ends"; the absence of one at
  the edge of the screen means "it carries on past here", which is the truth.
- **Owners.** Every line records who it belongs to, including the NEEDS YOU rows (which
  focus the agent they name), the collapsed-archive rows (which carry their `Collapsed`,
  as before) and the padding (nobody).
- **The no-wrap invariant.** See `_lines`.

This file must not import `store` — see `board.py`'s module note and
`tests/test_panel.py::RendererImports`, which covers this module too.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from . import board
from . import status as status_mod

# ---------------------------------------------------------------------------
# The optional dependency
# ---------------------------------------------------------------------------

# Tri-state cache: None = not asked yet. Asked once per process, not once per frame —
# a failed import is slow and the answer cannot change while the board is running.
_HAVE: Optional[bool] = None

# Below either of these the panel has no room to be a panel: two columns of border and
# two of padding, and two lines of border before a single row of anything. The plain
# renderer copes with a pane this size and this one would only lie about fitting, so
# `available` is not the only gate — `layout` returns None and `board.draw` falls back
# for that frame. A pane grown back gets the panel back.
MIN_WIDTH = 24
MIN_HEIGHT = 6


def available() -> bool:
    """Is `rich` importable here?

    THE ONLY THING THAT DECIDES WHICH RENDERER RUNS, and the reason a missing dependency
    is a cosmetic difference rather than a broken board. switchboard has no packaging file
    and is run straight out of the checkout by `bin/sb`, so `rich` is whatever the ambient
    interpreter happens to have — on one machine that is a yes and on the next it is a no,
    with no install step in between to notice. So it is asked, not assumed.
    """
    global _HAVE
    if _HAVE is None:
        try:
            import rich.box            # noqa: F401
            import rich.console        # noqa: F401
            import rich.panel          # noqa: F401
            import rich.text           # noqa: F401
            _HAVE = True
        except Exception:              # ImportError, and anything a broken install raises
            _HAVE = False
    return _HAVE


# ---------------------------------------------------------------------------
# The palette — `scripts/board_mockup.py`, unchanged. Dark terminals only.
# ---------------------------------------------------------------------------

STATE_STYLE = {
    "working": "bold green",
    # A muted blue, and every other blue on the screen is taken: plain `blue` is the panel
    # border, `bold blue` is its title, and anything bluer leans into the gutter's cyan.
    "done": "steel_blue",
    "idle": "dim",
    "blocked": "bold red",
    "failed": "bold red",
    "gone": "bold red",
}
STATE_DEFAULT = "dim"

GLYPH_STYLE = {"✗": "bold red", "◐": "bold yellow", "◌": "bold yellow",
               "○": "dim", "?": "dim", "●": "bold green"}

HEADER_STYLE = "bold white on blue"
# A section divider inside the head, quieter than either of the two bars above: the blue
# one is the board's own title and the yellow one is an alarm, and a divider that shouts
# as loudly as an alarm teaches the eye to ignore the alarm. Same `_bar` shape, so it
# reads as one of the family rather than as a new kind of line.
SECTION_STYLE = "bold white on grey23"
NEEDS_STYLE = "bold black on yellow"
BORDER_STYLE = "blue"
GUTTER_STYLE = "bold cyan"
DIM = "dim"

# The wash on the row a human just clicked — see `_wash` and `board.lit_row`.
#
# NEUTRAL, because every colour on this board already means something: green is working,
# red is trouble, yellow is a summons, cyan is a workspace. A highlight that borrowed any
# of them would say the agent had changed, when the only thing that changed is which row
# the human last touched.
#
# DARK, because the row underneath has to stay readable and everything it is drawn in was
# picked against a black pane. Lighter greys were tried on paper and lose the muted words
# first — `done`'s steel blue, then the age — which is the wrong half to lose.
#
# `not dim` is the other half of readable. Dim grey on a grey wash is the one combination
# that disappears, and it is the state word of every idle row plus the age of every row on
# the board. Lifting it for the ten seconds the row is lit changes nothing the row SAYS.
HIGHLIGHT_STYLE = "not dim on grey30"

# A workspace holding one visible agent. A middle dot, not a bullet: `●` is already the
# healthy-agent glyph and `•` beside it would read as a second status glyph.
LONE_MARK = "·"

# How many agents NEEDS YOU names before it starts counting instead.
NEEDS_MAX = 6

_COLOR = os.environ.get("NO_COLOR") is None


# ---------------------------------------------------------------------------
# Pure: what a row says. The ranking rules live in `board`; only the SHORT forms
# a narrow pane falls back to are new.
# ---------------------------------------------------------------------------


def marker_short(a) -> str:
    """`board.marker` cut to its WORD — `BLOCKED`, `AT PROMPT`, `GONE`, `STALLED`.

    The half that must never be what a narrow pane drops: the reason after the dash is
    recoverable from the agent's own pane, the word is not. Derived from `board.marker`
    rather than re-ranked here, so there is still exactly one place that decides which
    trouble a row reports.
    """
    m = board.marker(a)
    m = m.split(" — ")[0] if " — " in m else m
    # The one word that is too long to be a last rung. `AWAITING KEYPRESS` is twice the
    # width of anything else in this vocabulary, and this form is what a narrow pane keeps
    # when it has given up everything else — so it gives up the half that is grammar and
    # keeps the half that is the instruction. The ranking is still `board.marker`'s alone;
    # only the wording is shortened here, which is what this function is for.
    return "KEYPRESS" if m == "AWAITING KEYPRESS" else m


def tail_forms(a) -> list[str]:
    """Everything the row's tail could say, WIDEST FIRST, narrowest last.

    Andrew watches for two things — BLOCKED and MAIL — so those are what the row gives up
    last. The ladder degrades the WORDING before it gives up either piece, and the last
    rung is what `_row_budget` reserves columns for before it spends any on the name or
    the age.

    The task head and the done summary are not here: Andrew asked for one line per agent
    and does not read either on a board (`sb status` still shows both). `idle_excuse` is
    not here either, and is not gone — see `_excuse`.
    """
    full_m, short_m = board.marker(a), marker_short(a)
    full_x, short_x = board.mail_note(a), board.mail_note(a, short=True)
    if full_m and full_x:
        forms = [f"{full_m} · {full_x}", f"{full_m} · {short_x}", f"{short_m} · {short_x}"]
    elif full_m:
        forms = [full_m, short_m]
    elif full_x:
        forms = [full_x, short_x]
    else:
        return []
    out: list[str] = []
    for f in forms:                             # the ladder, without repeated rungs
        if f not in out:
            out.append(f)
    return out


def _excuse(a) -> str:
    """What explains an idle row, when the row has nothing else to say.

    THE ONE PIECE OF THE PLAIN BOARD'S TAIL THAT SURVIVES THE MOCKUP'S CUT, and it is not
    an oversight in either direction. Two rows can both read `idle` and mean opposite
    things — a lead waiting on its children is doing exactly what the protocol asked of
    it, and an agent that quietly died looks identical — and `stalled` is precisely "idle
    and nothing explains it", so an agent with an excuse has no marker to say it. Without
    this the calm half of the idle question is drawn as a blank tail.

    It is NOT in `tail_forms`, so it reserves nothing and is drawn only into room the two
    pieces Andrew watches for did not want. Context is what this line sheds first.
    """
    return (a.idle_excuse or "") if not board.marker(a) and not board.mail_note(a) else ""


def squeeze(a, room: int) -> str:
    """The tail when no whole rung of the ladder fits: fill `room`, mail first.

    Two jobs. It uses the room a rung would have left empty — a 25-column tail says
    `BLOCKED — which pane s…`, not a bare `BLOCKED` with fifteen columns of nothing after
    it — and it decides what goes when the pane is narrower than even the bottom rung: the
    marker's REASON first, then its word, and the mail kept whole to the last. Mail is the
    shorter of the two and the only one with no other representation on the screen — the
    state word beside it already says `blocked`, and NEEDS YOU below names the agent again
    — so an unanswered message is what a clip here would really lose.
    `board._MAIL_RESERVE` makes the same trade for the same reason.
    """
    full, word = board.marker(a), marker_short(a)
    if not full:
        long_x = board.mail_note(a)
        return _clip(long_x if _vlen(long_x) <= room else board.mail_note(a, short=True),
                     room)
    for x in (board.mail_note(a), board.mail_note(a, short=True)):
        if not x:
            continue
        gap = _vlen(x) + 3
        if room - gap >= _vlen(word) + 2:        # the word survives, plus a hint of the why
            return _clip(full, room - gap) + " · " + x
    x = board.mail_note(a, short=True)
    if x:
        if room - _vlen(x) - 3 >= 1:
            return _clip(word, room - _vlen(x) - 3) + " · " + x
        return _clip(x, room)                    # the last thing standing
    return _clip(full if room >= _vlen(word) + 2 else word, room)


def needs_kind(a) -> str:
    """Which of NEEDS YOU's TWO kinds this agent is, or `""` for neither.

    `blocked` — waiting on a human, whether it called `sb block`, is sitting at its
    prompt, or is parked on a screen herdr cannot read. `idle` — nothing running: stalled,
    or a session that died mid-turn with the pane still open.

    STILL TWO WORDS AND NOT THREE. `awaiting_keypress` is counted as `blocked` rather than
    given a kind of its own, for two reasons that point the same way: it IS the blocked
    shape — the agent cannot move until a person touches its pane, and no child of its own
    can free it, which is exactly what this bucket means and exactly why `needs_list`
    exempts the bucket from the busy-below suppression — and a third kind word would widen
    the section's fixed kind column for every row on the board. The distinction it loses
    here is drawn where there is room for it, in `needs_reason` and in `board.marker`.

    Nothing else qualifies. Mail does not: Andrew does not treat a message as something
    the board should summon him for, and the row still says `mail:` in its tail. `gone` is
    out too — a pane herdr has no agent for is neither blocked nor idle, and its row
    already shouts GONE in red. Both stay visible ON the rows; they are only out of the
    summons list. Narrower than `board.wants_you`, deliberately.

    An INFERRED summons also has to have held (`AgentStatus.settled`), which is what stops
    a row that is between two turns being listed for the frame it takes to start the next
    one. `blocked` is exempt and immediate — the agent wrote that word itself; the keypress
    reading is emphatically NOT exempt, being the most inferred thing on the row.
    """
    if a.blocked or ((a.at_prompt or a.awaiting_keypress) and a.settled):
        return "blocked"
    if (a.stalled or a.signal_drift) and a.settled:
        return "idle"
    return ""


def still_going(a) -> bool:
    """Whether this agent is work in flight — the thing an ancestor is waiting ON.

    Working, blocked, or sitting at a prompt: all three are a live subtree with something
    still to come out of it. A finished agent is not, and neither is a GONE one — its pane
    is not there, nothing is coming, and letting it stand in for live work is what would
    keep a whole branch's idle ancestors out of the summons list forever.

    Deliberately NOT the store's raw `state`, which says `working` about every open row
    including the idle ones. `display_state` is the reconciled word — the same one drawn
    on the agent's own row — so a subtree that has quietly gone idle stops holding its
    ancestors back, and the board cannot say `idle` on a row and treat it as working here.

    An agent whose idleness has NOT SETTLED counts as still going, and that is the half of
    the debounce this section needs. A descendant's two-second turn gap takes it out of
    RUNNING for one tick, and without this line that single gap withdraws the excuse from
    every idle ancestor at the same instant — which is the flicker as Andrew actually sees
    it, a column blinking rather than one row. Too soon to call it a stop is not a stop.
    """
    if a.finished or a.gone:
        return False
    if a.inferred_summons and not a.settled:
        return True
    return bool(a.blocked or a.at_prompt or a.display_state in status_mod.RUNNING)


def busy_below(agents: list[Any]) -> set[str]:
    """Every agent with at least one `still_going` agent somewhere BENEATH it.

    Walks up from each live agent rather than down from each candidate: one pass over the
    fleet, and no recursion to blow up on a deep tree.

    Two shapes of broken data have to be survivable, because this runs on a snapshot the
    board took of a live store and not on a tree anyone validated. A parent naming an agent
    that is not in the snapshot (archived, swept, never collected) simply ends the walk —
    `by_name.get` returns None. A cycle, including a row that is its own parent, is stopped
    by `seen`, which starts holding the agent itself: nothing is ever its own descendant.
    """
    by_name = {a.name: a for a in agents}
    out: set[str] = set()
    for a in agents:
        if not still_going(a):
            continue
        seen = {a.name}
        up = by_name.get(a.parent) if a.parent else None
        while up is not None and up.name not in seen:
            seen.add(up.name)
            out.add(up.name)
            up = by_name.get(up.parent) if up.parent else None
    return out


def needs_list(agents: list[Any]) -> list[Any]:
    """The NEEDS YOU section's membership, in the order it is drawn: blocked, then idle.

    Blocked first because a blocked agent asked a question and is holding until a person
    answers it, and it is listed whatever is happening under it — its own children cannot
    unblock it.

    AN IDLE AGENT WITH LIVE WORK BENEATH IT IS NOT THE HUMAN'S PROBLEM. `stalled` already
    excuses a parent whose own direct children are open, but "open" is the store's word and
    the excuse stops at one generation: a lead whose child is itself idle-with-a-working-
    grandchild came back into the list, and every one of those rows summoned Andrew to an
    agent he could only wait for. The rule is now the whole subtree and the reconciled
    state: listed only when NOTHING under it is still going, recursively. Children that
    finished or whose panes are gone hold nobody back.

    Rows only, so the section is not the place this is decided twice — `_needs_block` draws
    whatever this returns.
    """
    busy = busy_below(agents)
    out = [a for a in agents if needs_kind(a) == "blocked"]
    out += [a for a in agents if needs_kind(a) == "idle" and a.name not in busy]
    return out


def needs_reason(a) -> str:
    """Why this agent is in the list — the half after the kind word."""
    if a.at_prompt:
        return "at a prompt, waiting on you"
    if a.blocked:
        return a.blocked_why or "no reason recorded"
    if a.awaiting_keypress:
        # The action first, for the same reason the stalled line puts the age first: it is
        # the half worth reading and the half a clip would eat. Says what was observed —
        # herdr recognised nothing on the screen — and not which dialog it is, which
        # nothing here knows. See `status.awaiting_keypress_screen`.
        return "press a key in its pane — screen herdr cannot read"
    if a.signal_drift:
        return "died mid-turn, pane still open"
    if a.stalled:
        # Age first: it is the half worth reading, and the half a clip would eat if the
        # words came first.
        return f"idle {status_mod.fmt_age(a.idle)}, nothing running"
    return ""


# ---------------------------------------------------------------------------
# Pure: width. Measured by `board`, never re-implemented — see `_lines`.
# ---------------------------------------------------------------------------

_vlen = board._visible_len
_clip = board._clip
_pad = board._pad

SEP = " · "                                  # between footer pieces, as inside the hints


def _clipw(s: str, cols: int) -> str:
    """`_clip` for text whose SPACES ARE THE POINT — a filled bar's left inset.
    `board._clip` flattens runs of whitespace, which is right for a task
    head or a blocked reason and wrong for a string whose leading space is a column of
    colour.
    """
    if _vlen(s) <= cols:
        return s
    return board._clip_cols(s, max(0, cols - 1)) + "…"


def clip_name(s: str, cols: int) -> str:
    """A name cut to `cols`, KEEPING ITS TAIL — `researcher-22` → `re…-22`.

    Not `_clip`, which keeps the head. Switchboard names are a role and a number, and at
    the width the tail reserve leaves for this column the head is the half every sibling
    shares: three rows reading `res…` are three rows a human cannot tell apart, where
    `re…-22` and `re…-23` still name somebody.

    The tail is kept in COLUMNS and by GLYPH, not in characters — three characters of a
    CJK name are six columns, and a name that overruns its column by three is the wrap
    this whole renderer is built to prevent. `board._clusters` is what decides where a
    glyph ends, the same measurement every other clip on the row goes through.
    """
    if _vlen(s) <= cols or cols < 4:
        return _clip(s, cols)
    tail, tw = [], 0                             # the last three glyphs — the number
    for g, w in reversed(list(board._clusters(s))[-3:]):
        if tw + w > cols - 4:                    # never so much that the head cannot speak
            break
        tail.insert(0, g)
        tw += w
    return _clip(s, cols - tw) + "".join(tail)


# ---------------------------------------------------------------------------
# Pure: the workspace gutter — grouping that costs zero columns
# ---------------------------------------------------------------------------


def _row_depth(row) -> int:
    return int(getattr(row, "depth", 0) or 0)


def group_runs(rows: list[Any]) -> list[tuple[int, int]]:
    """`(first, last)` row index for each run of consecutive rows sharing a workspace.

    A GROUP IS READ FROM THE DATA, not inferred from depth. An earlier draft bracketed "a
    depth-0 agent and its whole subtree", which merges several worktrees into one: a new
    workspace opens when a TOP delegates, so each direct child of a top starts its own and
    the top sits alone in its. The live store has the case that settles it — a depth-1
    child whose `workspace` is its parent's, unlike every one of its siblings. Depth
    cannot tell that row from the ones around it; the workspace value can.

    A collapsed-archive marker is read the same way, off the same field. It carries the
    workspace of the agents it stands for when they shared one (`status.Collapsed`), and
    None when they did not — so a group whose last member has been archived keeps its
    closing corner, and a marker standing for several workspaces still belongs to none of
    them and ends the run it follows, which is what it did before it had the field.
    """
    runs: list[list[int]] = []
    current: Optional[str] = None
    for i, row in enumerate(rows):
        ws = row.workspace
        if ws is not None and ws == current:
            runs[-1][1] = i
        elif ws is not None:
            runs.append([i, i])
        current = ws
    return [(a, b) for a, b in runs]


def gutter_column(rows: list[Any]) -> list[Optional[tuple[str, int]]]:
    """Per row: `(char, offset)`, or `None` for a row with no mark.

    The mark lives INSIDE the indentation the row already has, at the LAST column the
    run's shallowest row indents to — the space directly in front of that row's name.
    Every row in a run is at least that deep, so the mark always lands on a space and the
    name column never moves: the gutter costs zero columns. `offset` indexes the row's
    rendered label, with `-1` meaning the space in front of the glyph — see below.

    AS FAR RIGHT AS THE RUN ALLOWS, which is Andrew's call and not an arbitrary one: the
    whole block from column 0 to `INDENT_width * depth - 1` is free for every row in the
    run, and drawing at the left end of it left the bracket floating in open space with
    the names it groups four columns away. Against the name it reads as a brace around
    them. The shallowest row still decides the column, so the bracket never lands on a
    glyph or a letter of a deeper row.

    `╭ │ ╰` around a run of two or more. A run of one gets a standalone `·`, because a
    bracket needs two rows to read as one.

    A TOP ORCHESTRATOR ALONE IN ITS WORKSPACE GETS NOTHING — no dot, no bracket. Andrew
    ruled that out, and it also disposes of the one place the gutter has no room, since a
    top's name starts immediately after its glyph with no indentation to draw in.

    A SHARED workspace at depth 0 is the case qa-2 found on Andrew's own board and it is
    NOT that case: two agents the human delegated directly into one checkout, or a top and
    a child sharing one, have a real grouping to show and the mockup drew nothing for it,
    because it skipped any run whose shallowest row is depth 0. Here such a run — two rows
    or more, never one — draws its bracket at `-1`, the leading space every row already
    spends before its glyph. That still costs zero columns and does not indent the board,
    which Andrew ruled out as well. The rule stays "a mark for every workspace holding
    more than a top on its own", and the offset is wherever that run's rows have a space.
    """
    out: list[Optional[tuple[str, int]]] = [None for _ in rows]
    for first, last in group_runs(rows):
        depth = min(_row_depth(rows[i]) for i in range(first, last + 1))
        if depth < 1:
            if first == last:
                continue                         # a top alone in its own workspace
            off = -1                             # the space before the glyph
        else:
            off = len(board.INDENT) * depth - 1  # the space before the name
        if first == last:                        # a workspace of one: a mark, not a bracket
            out[first] = (LONE_MARK, off)
            continue
        for i in range(first, last + 1):
            out[i] = ("╭" if i == first else "╰" if i == last else "│", off)
    return out


# ---------------------------------------------------------------------------
# The frame
# ---------------------------------------------------------------------------


def layout(snap, *, top: int, height: int, width: int, msg: str,
           note_text: str = "", show_archived: Optional[bool] = None,
           lit: Optional[str] = None, stats: Optional[dict] = None
           ) -> Optional[list[tuple[str, Optional[object]]]]:
    """The whole screen as (text, owner) pairs — `board.layout`'s contract, drawn richly.

    Returns None when it cannot honour that contract: `rich` is absent, the pane is too
    small to be a panel, or — the one that matters — the rendered frame did not come back
    with the line count it was built with. `board.draw` falls back to the plain renderer
    for that frame, which is a change of appearance and never a change of meaning.

    That last check is the whole safety story for clicks. Owners are recorded per CONTENT
    line as the frame is built, exactly as `board.layout`'s `emit` records them; the panel
    then adds one border line above and one below, and if the arithmetic ever stops being
    that — a wrapped row, a rich version that pads differently — the mismatch is caught
    here rather than showing up as a click that focuses the wrong agent.

    `lit` is the name of the agent whose row was clicked recently enough to still be
    marked, or None. A NAME and not a click time: WHEN is `board.lit_row`'s question and it
    is asked once per frame, before this is called, so nothing in this renderer has to know
    what time it is. The row it names is drawn washed (`_wash`); every other row, and a
    name matching nothing on screen, draws exactly as it did before.

    `stats` is the fleet's numbers as the collector computed them — `panel.Reading.stats`,
    a plain dict, `{}` or None when there are none yet. Drawn as the head's middle section
    (`_stats_block`); what it SAYS is `board.stats_rows`, shared with the plain renderer so
    the two boards cannot come to report different numbers.
    """
    if not available() or width < MIN_WIDTH or height < MIN_HEIGHT:
        return None

    from rich.text import Text

    if show_archived is None:
        show_archived = status_mod.SHOW_ARCHIVED
    rows = status_mod.display_rows(snap.agents, show_archived=show_archived)

    inner = width - 4                            # 2 columns of border, 2 of padding
    capacity = height - 2                        # 2 lines of border
    marks = gutter_column(rows)

    content: list[tuple[Any, Optional[object]]] = []

    def emit(line, owner: Optional[object] = None) -> None:
        """Draw one content line, and say in the same breath what a click on it means.

        THE ONLY WAY A LINE GETS INTO THE FRAME, for `board.layout.emit`'s reason: nothing
        anywhere computes "which agent is on screen row N". The answer is recorded here,
        as the line is built.
        """
        content.append((line, owner))

    # --- NEEDS YOU and the footer, sized before the body gets what is left ---
    # Read from `snap.agents` and not from `rows`: a blocked agent inside a collapsed
    # archive is still a person's problem, and the collapse must not be able to bury it.
    wanted = needs_list(snap.agents)
    needs = _needs_block(wanted, inner)
    foot = _footer(inner, msg, note_text)

    # The head is FOUR lines: the board's own bar, the two lines of fleet numbers, and the
    # section bar that says the tree below it is the tree. Counted as ONE number because
    # everything downstream — the body's room, the fill, and the frame's own height check
    # — is counted off it; which pieces that number is made of is only decided where the
    # head is drawn, and only ever by the two give-backs below.
    stats_block = _stats_block(stats, inner)
    bar = True                                   # is the AGENTS section header drawn?
    head_lines = 2 + len(stats_block)
    gap_min = 1 if needs else 0
    room = capacity - head_lines - 1 - len(needs) - gap_min          # head, footer
    if room < 1 and stats_block:
        # THE NUMBERS GO BEFORE THE SUMMONS DOES. A pane this short has room for the
        # board's real work and nothing else, and NEEDS YOU is the section a human is
        # looking for — so the stats block gives its lines back here, above the line that
        # would otherwise start shortening that list.
        head_lines -= len(stats_block)
        room += len(stats_block)
        stats_block = []
    if room < 1 and needs:
        # Too short even for one agent row: give the NEEDS YOU list back a line at a time,
        # its bar last — a count with no names still says somebody is waiting.
        keep = max(1, len(needs) + room - 1)
        needs = needs[:keep]
        room = capacity - head_lines - 1 - len(needs) - gap_min
        if room < 1:                                        # still none: the section goes
            needs, gap_min = [], 0
            room = capacity - head_lines - 1

    # WHICH ROWS ARE ON SCREEN, decided before the head is drawn because on the shortest
    # pane the head is what decides it. A section header over no agents at all is the one
    # thing this board must not spend its last line on, and a fleet's statistics over no
    # fleet is the same trade one line earlier — so when that is what it comes to, the head
    # gives its lines back and the tree keeps them. Pure, so asking twice is free.
    #
    # IN ORDER: the numbers first, the tree's own header last, the board's title never. And
    # only if a row actually comes of it — `_window` charges for its own `↑ N above` and
    # `+ N more below` lines, so a line given back does not always buy one.
    first, last = _window(len(rows), max(0, top), max(0, room))
    if rows and first == last:
        n = len(stats_block)
        for give_stats, give_bar in (((n, 0), (n, 1)) if n else ((0, 1),)):
            give = give_stats + give_bar
            grown = _window(len(rows), max(0, top), max(0, room + give))
            if grown[0] == grown[1]:
                continue
            head_lines, room = head_lines - give, room + give
            if give_stats:
                stats_block = []
            if give_bar:
                bar = False
            first, last = grown
            break

    # --- the head -----------------------------------------------------------
    # Counts from `status.summary_bits`, the same list `sb status` joins, so the two
    # readouts of one snapshot cannot come to show different numbers.
    emit(_bar(" " + " · ".join(["switchboard"] + status_mod.summary_bits(snap)),
              inner, HEADER_STYLE))
    for line in stats_block:
        # Owned by nobody, like the bars around it: a click on a number focuses no agent.
        emit(line)
    if bar:
        # The tree is a SECTION rather than the whole body, because it is no longer the
        # whole body: without a header of its own it would run straight on from the last
        # line of numbers above. One line and no blank around it — this is a pane, and a
        # row of agents is worth more than air.
        emit(_bar(" AGENTS", inner, SECTION_STYLE))

    # --- the body -----------------------------------------------------------
    if not rows:
        why = note_text or "nothing running — sb start"
        emit(Text(_clip("  (" + why + ")", inner), style=DIM, no_wrap=True,
                  overflow="crop"))
        drawn = 1
    else:
        drawn = 0
        if first > 0:
            emit(Text(_clip(f"  ↑ {first} above", inner), style=DIM, no_wrap=True,
                      overflow="crop"))
            drawn += 1
        w_name, w_state, show_age, left = _row_budget(rows[first:last], inner)
        for i in range(first, last):
            # A collapsed row is never lit: it is not an agent, `lit` is a name, and a
            # click on one focuses nobody — `board.main` says so rather than lighting it.
            on = (lit is not None and not board._is_group(rows[i])
                  and rows[i].name == lit)
            emit(_row(rows[i], marks[i], inner, w_name, w_state, show_age, left, lit=on),
                 rows[i])
            drawn += 1
        if last < len(rows):
            emit(Text(_clip(f"  + {len(rows) - last} more below", inner), style=DIM,
                      no_wrap=True, overflow="crop"))
            drawn += 1

    # --- fill the pane ------------------------------------------------------
    # The agent rows sit at the top, NEEDS YOU and the footer are pinned to the bottom,
    # and all the slack goes in ONE run between them. The blank line above NEEDS YOU is
    # that run's last line rather than a line added on top of it, so it is exactly one
    # when the board is full and the slack when it is not, and never multiplies.
    gap = max(gap_min, capacity - head_lines - drawn - len(needs) - 1)
    for _ in range(gap):
        emit(Text(""))
    for line, owner in needs:
        emit(line, owner)
    emit(foot)

    del content[capacity:]                       # a frame is never taller than the pane
    out = _lines([c for c, _ in content], width, height, inner)
    if out is None or len(out) != len(content) + 2:
        return None                              # see the docstring: fall back, silently
    owners: list[Optional[object]] = [None] + [o for _, o in content] + [None]
    return list(zip(out, owners))


def _window(n: int, top: int, room: int) -> tuple[int, int]:
    """Which display rows are on screen: `[first, last)`.

    In ROWS, which is also in lines — this renderer draws no blank line between agents, so
    a display row costs exactly one. What is not free is saying so: a window with anything
    above it spends a line on `↑ N above`, and one with anything below it a line on
    `+ N more below`, and both are charged here rather than discovered afterwards.

    `top` is clamped to the first row of the last full screenful, so scrolling to the
    bottom lands on a full screen rather than on one row with blank space under it.
    """
    if room <= 0 or n == 0:
        return 0, 0
    max_top = 0 if n <= room else max(0, n - (room - 1))
    top = min(max(0, top), max(0, min(max_top, n - 1)))
    avail = room - (1 if top else 0)
    take = min(max(0, avail), n - top)
    if top + take < n:                           # room for the `+ N more below` line
        take = max(0, take - 1)
    return top, top + take


def _row_budget(window: list[Any], inner: int) -> tuple[int, int, bool, int]:
    """The row's columns: `(name, state, draw the age, columns used before the tail)`.

    THE TAIL IS RESERVED FIRST and everything else on the row bids for what is left.
    BLOCKED and MAIL are what Andrew watches for, so the narrowest rung of every row's
    ladder is charged to the budget before the name or the age get any of it — the reverse
    of the usual "fill until full".

    Given up in this order as the pane narrows: the age first (the state word already says
    whether anything is running), then the name, down to six columns, below which a name
    is not a name. Only after both is the reserve itself cut, which a pane too narrow for
    `BLOCKED · 2 unread` forces and nothing here can prevent.

    The gutter is NOT in here. Its rule is drawn inside the indentation the name column
    already carries, so the budget is the same with it or without it.
    """
    live = [a for a in window if not board._is_group(a)]
    reserve = max([0] + [_vlen(f[-1]) for f in (tail_forms(a) for a in live) if f])
    reserve += 2 if reserve else 0               # the two spaces before it
    w_state = max([0] + [_vlen(a.display_state) for a in live])
    w_name_full = max([0] + [_vlen((board.INDENT * a.depth) + a.name) for a in live])

    fixed = 3 + 2                                # " ● " and the gap before the state
    show_age = True
    for show_age in (True, False):
        w_name = w_name_full
        if fixed + w_name + w_state + (7 if show_age else 0) + reserve <= inner:
            break
    else:
        w_name = max(6, inner - fixed - w_state - reserve)
    return w_name, w_state, show_age, fixed + w_name + w_state + (7 if show_age else 0)


def _gutter(line, label: str, mark: Optional[tuple[str, int]], indent_cols: int,
            style: str) -> None:
    """Append `label`, with the run's mark drawn INTO the indentation it already has.

    `off` is always inside this row's indentation, so the character it replaces is a space
    and the name column stays exactly where it was.

    ONE FUNCTION FOR BOTH KINDS OF ROW, and that is the point rather than tidiness: an
    agent row and the collapsed row that closes its workspace have to put the mark in the
    same screen column, or the bracket closes on nothing. Bounded by the INDENT and not by
    the label, so a mark that somehow came out too far right is dropped rather than drawn
    over a letter of the name.
    """
    if mark is not None and 0 <= mark[1] < indent_cols:
        ch, off = mark
        line.append(label[:off], style=style)
        line.append(ch, style=GUTTER_STYLE)
        line.append(label[off + 1:], style=style)
    else:
        line.append(label, style=style)


def _wash(line, inner: int) -> None:
    """Mark this line as the one just clicked: a background across the WHOLE row.

    PADDED FIRST, and that is the whole of why this is not one call. A row is drawn to
    whatever it has to say and then stops — nothing pads it, because until now nothing
    needed the columns after the last word. A background applied to the printed characters
    alone ends wherever that row's tail happened to end, so a fleet of rows lights up with
    a ragged right edge, which reads as a rendering fault and not as a mark. `_bar` fills a
    line to `inner` for the same reason; this is that idiom applied to a line that already
    has content.

    Measured by `board._visible_len`, like every other width in this file, so the wash ends
    in the same column the bars do — see `_lines` on why the two measurements must agree.

    Applied LAST, over the finished row, so it can be one span rather than a rule every
    `append` above has to remember. `rich` combines a later span over the earlier ones, so
    the foregrounds carry meaning as before and only the background and the dimming change.
    """
    line.pad_right(max(0, inner - _vlen(line.plain)))
    line.stylize(HIGHLIGHT_STYLE)


def _row(row, mark: Optional[tuple[str, int]], inner: int, w_name: int, w_state: int,
         show_age: bool, left_used: int, lit: bool = False):
    """One agent's line — the whole of it, because an agent is one line."""
    from rich.text import Text

    line = Text(no_wrap=True, overflow="crop")

    if board._is_group(row):
        # No glyph, no state, no tail. It is not an agent and must not read as one:
        # `board.agent_at` hands this very object to the click handler, which has to be
        # able to tell the two apart.
        #
        # Two things it DOES share with an agent row, because it stands among agent rows:
        # it indents by `board.INDENT` to the depth of the rows it replaced, so it lines
        # up with the siblings it is the footer of; and it carries the workspace mark,
        # because it is the last row of that workspace's run and the bracket has to close
        # on something. `_clip` is given the WORDS only — it flattens runs of whitespace,
        # and an indent handed to it arrives with the indent gone.
        indent = board.INDENT * row.depth
        head = " " if mark is None or mark[1] >= 0 else mark[0]
        line.append(head, style="" if head == " " else GUTTER_STYLE)
        line.append("  ")                        # where an agent row draws its glyph
        text = _clip(status_mod.collapsed_text(row), max(1, inner - 3 - _vlen(indent)))
        _gutter(line, indent + text, mark, _vlen(indent), DIM)
        return line

    # A gone agent is one whose pane herdr no longer has. It is the row a future "clear
    # them all" key would sweep, so it is drawn to be picked out without reading: red the
    # whole way across, the name struck through. The strike is decoration on top of the
    # glyph, the red and the word GONE in the tail — a terminal that ignores it loses
    # nothing that carries meaning.
    doomed = bool(row.gone)
    g = board.glyph(row)
    indent = board.INDENT * row.depth
    label = _pad(indent + clip_name(row.name, max(1, w_name - _vlen(indent))), w_name)
    name_style = "bold red strike" if doomed else "bold" if board.wants_you(row) else ""

    if mark is not None and mark[1] < 0:
        line.append(mark[0], style=GUTTER_STYLE)     # a shared workspace at depth 0
    else:
        line.append(" ")
    line.append(g, style=GLYPH_STYLE.get(g, ""))
    line.append(" ")
    # The workspace mark, drawn INTO the indent rather than in front of it — see `_gutter`,
    # which the collapsed row above goes through as well.
    _gutter(line, label, mark, _vlen(indent), name_style)
    line.append("  ")
    if doomed:
        line.append(_pad(_clip(row.display_state, w_state), w_state), style="red")
    else:
        line.append(_pad(_clip(row.display_state, w_state), w_state),
                    style=STATE_STYLE.get(row.display_state, STATE_DEFAULT))
    if show_age:
        line.append("  " + f"{status_mod.fmt_age(row.idle):>5}",
                    style="red" if doomed else DIM)

    # The widest rung of this row's ladder that fits in the room the budget kept for it.
    # Never dropped: a row with a tail always draws one, clipped only when even the
    # narrowest rung is wider than the pane.
    room = max(1, inner - left_used - 2)
    forms = tail_forms(row)
    if forms:
        text = forms[0] if _vlen(forms[0]) <= room else squeeze(row, room)
        line.append("  " + _clip(text, room), style="bold red" if doomed else "yellow")
    elif _excuse(row):
        line.append("  " + _clip(_excuse(row), room), style=DIM)
    if lit:
        _wash(line, inner)
    return line


def _stats_block(stats: Optional[dict], inner: int):
    """The head's middle section: the fleet's numbers, two lines, above the tree.

    NO BAR OF ITS OWN, which is the one visual call in here and the only place this
    section departs from `AGENTS` and `NEEDS YOU`. It does not need one: it is already
    delimited, by a filled bar directly above it and a filled bar directly below, and a
    third bar between two bars would spend a third of a small section on the word STATS.
    What a bar would have said, the two labels say better — they name the TIME FRAME each
    line is counted over, which is the half a reader cannot infer from the numbers, where
    a heading would only repeat what a line of counts already looks like.

    ALWAYS TWO LINES, whatever is known. A section that grew a line as the first sample
    landed would push the whole tree down half a second into every board's life, and the
    rows a human is reading would move under the cursor. `board.stats_rows` says what goes
    on them; the width ladder is the header's — whole pieces, dropped from the right.
    """
    from rich.text import Text

    out = []
    room = max(0, inner - 2 - board.STATS_LABEL_W - 2)
    for label, pieces in board.stats_rows(stats):
        line = Text(no_wrap=True, overflow="crop")
        line.append("  " + _pad(label, board.STATS_LABEL_W) + "  ", style=DIM)
        kept = board.stats_fit(pieces, room)
        for i, piece in enumerate(kept):
            if i:
                line.append(board.STATS_SEP, style=DIM)
            # The numbers themselves undimmed, and everything around them dim: the labels
            # and separators are scaffolding, and the figures are the only thing on these
            # two lines anybody came to read.
            line.append(piece)
        if not kept:
            line.append(_clip(board.STATS_NONE, room), style=DIM)
        out.append(line)
    return out


def _needs_block(wanted: list[Any], inner: int) -> list[tuple[Any, Optional[object]]]:
    """The NEEDS YOU section as (line, owner) pairs, or []."""
    from rich.text import Text

    if not wanted:
        return []
    out: list[tuple[Any, Optional[object]]] = [
        (_bar(f" NEEDS YOU · {len(wanted)}", inner, NEEDS_STYLE), None)]
    shown = wanted[:NEEDS_MAX]
    w_kind = 7                                   # "BLOCKED", the longer of the two words
    w_want = min(max(_vlen(a.name) for a in shown), max(1, inner - 12))
    for a in shown:
        kind = needs_kind(a)
        line = Text(no_wrap=True, overflow="crop")
        line.append("  " + _pad(kind.upper(), w_kind),
                    style="bold red" if kind == "blocked" else "bold yellow")
        line.append("  " + _pad(_clip(a.name, w_want), w_want), style="bold")
        room = inner - 2 - w_kind - 2 - w_want - 2
        # Below this the reason is all ellipsis and says less than the kind word already
        # does, so a narrow pane gets KIND + name and nothing else.
        if room >= 14:
            line.append("  " + _clip(needs_reason(a), room), style=DIM)
        # OWNED BY THE AGENT IT NAMES. This is a row about somebody, drawn where a human
        # is looking when they decide to go and deal with them, so clicking it focuses
        # them — the same thing clicking their row above does.
        out.append((line, a))
    if len(wanted) > NEEDS_MAX:
        out.append((Text(_clip(f"  + {len(wanted) - NEEDS_MAX} more", inner), style=DIM,
                         no_wrap=True, overflow="crop"), None))
    return out


def _footer(inner: int, msg: str, note_text: str):
    """The last line: whatever fits, in the order a narrow pane keeps them.

    A stale snapshot first (the board saying its own data is old outranks everything,
    because every other line on the screen is that data), then the answer to whatever the
    human last clicked, then the hints.

    The separator is drawn as its own append and never handed to `_clip`, which flattens
    whitespace and so ate a separator built into the piece: the note and the hints ran
    together into one string. Same shape as `board._compose`, which reserves the gap out
    of the room and clips only the piece — and the same separator, so the seam between
    two footer pieces reads like the seams inside the hint line itself.
    """
    from rich.text import Text

    foot = Text(no_wrap=True, overflow="crop")
    used = 0
    bits = [b for b in (note_text, msg,
                        "click a row to focus it · scroll to pan · a archived · q quits")
            if b]
    for b in bits:
        gap = _vlen(SEP) if used else 0
        room = inner - used - gap
        if room < 6:
            break
        piece = _clip(b, room)
        if gap:
            foot.append(SEP, style=DIM)
        foot.append(piece, style=DIM)
        used += gap + _vlen(piece)
    return foot


def _bar(text: str, cols: int, style: str):
    """A filled full-width bar. Padded, never wrapped: exactly `cols` wide."""
    from rich.text import Text
    return Text(_pad(_clipw(text, cols), cols), style=style, no_wrap=True,
                overflow="crop")


def _lines(renderables: list[Any], width: int, height: int, inner: int
           ) -> Optional[list[str]]:
    """Render the panel and hand back one string per screen line, or None if it failed.

    THE NO-WRAP INVARIANT LIVES HERE, and it is the one thing this file cannot get wrong
    quietly. No line may ever wrap, because a wrapped line pushes every row below it down
    by one and the next click focuses the wrong agent — silently, and looking exactly like
    a correct click. Three things hold it:

    - every content `Text` is built `no_wrap=True, overflow="crop"`, so `rich` crops to
      the panel's inner width rather than folding;
    - `rich` measures in cells and so does `board._visible_len`, and every clip and pad
      above went through `board`'s measurement, so the two agree on where a CJK ideograph,
      a ZWJ sequence, a variation selector or a flag pair ends;
    - and then it is CHECKED rather than trusted: the caller compares the line count it
      built against the line count it got back, and a frame that grew a line is refused
      whole and drawn by the plain renderer instead.

    `board._fit` is applied on the way out as the last of those. If `rich` and `board`
    ever did disagree about a width, the line loses its colour rather than its
    correctness — which is `board._fit`'s own trade, made in the one place a disagreement
    could reach the screen.
    """
    from rich.box import ROUNDED
    from rich.console import Console, Group
    from rich.panel import Panel

    console = Console(width=width, force_terminal=True, no_color=not _COLOR,
                      highlight=False, soft_wrap=False, legacy_windows=False)
    panel = Panel(Group(*renderables), box=ROUNDED, border_style=BORDER_STYLE,
                  height=height, title="[bold]switchboard[/bold]", title_align="left",
                  padding=(0, 1), width=width, expand=False)
    try:
        with console.capture() as cap:
            console.print(panel)
    except Exception:
        return None                              # a rich we do not understand: fall back
    text = cap.get()
    if text.endswith("\n"):
        text = text[:-1]
    return [board._fit(line, width) for line in text.split("\n")]
