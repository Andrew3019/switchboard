"""The clickable board — a human's live view of the tree. A RENDERER.

Three ways in, all the same screen: `sb start` opens one beside the orchestrator
it starts, `sb board` opens one here, and
`python3 -m switchboard.board` is the plumbing both go through.

This is a HUMAN-ONLY surface and must stay one. `sb board` is hidden from
`--help` and refuses any caller that `whoami()` resolves to an agent, and the
board appears nowhere in defaults/protocol.md, which is where an agent actually
learns what `sb` can do. Its only side effect is `herdr agent focus`, a human
jumping to a pane.

**This file does not import `store`, and must not start.** It once did, inside
`snapshot()`, and the claim that a two-second tick there was read-only was false
twice: `collect` marked an agent `failed` when herdr stopped listing it
(`reap=False` closed that), and `store.connect()` itself re-stamps `meta`,
CREATEs and ALTERs tables and backfills every agent row, and when something
missing can be given to no existing row it REBUILDS the store, dropping every
table `SCHEMA` declares (`readonly=True` closed that, in `1c10745`). Both fixes
are real and both are still in force — they moved, with the connect, into
`switchboard/collector.py`. What changed here is that they stopped being a claim
this file has to keep making. A panel now reads a file that one elected collector
publishes, so the board has no database handle and no import that could get it
one: read-only is a fact about `switchboard/panel.py`'s imports, checked by
`tests/test_panel.py::RendererImports`, rather than a docstring somebody has to
defend on every future edit. That is also what makes a panel per agent affordable
— forty of these cost one collector between them.

`refresh()` is the whole of the difference. Read `switchboard/panel.py` before
reaching for the store from here.

Proved out by `scripts/05-mouse.py` and `scripts/06-board.py`: herdr forwards
SGR mouse events to a pane, and a decoded row maps back to an agent. Those two
stay as the record of what was proven; this is the version that is maintained.

`open_beside()` below was once removed as dead code, because it was written a
turn before anything called it. It is now called from `broker._open_board`, which
every spawn reaches through `broker.delegate` — so every agent, not only a
top-level orchestrator, opens with a board beside it. There is no declining it:
every sb-made view is split with the board (DESIGN-TRUTH.md's "`--no-board`.").
"""

from __future__ import annotations

import json
import os
import re
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import unicodedata
from typing import Iterator, Optional

from . import config
from . import panel
from . import status as status_mod
from . import sweep as sweep_mod

# 1000h = press/release reporting. 1006h = SGR encoding, which is the only one
# that survives past column 223 and the only one 05-mouse saw herdr emit.
MOUSE_ON = "\033[?1000h\033[?1006h"
MOUSE_OFF = "\033[?1006l\033[?1000l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

SGR = re.compile(r"\033\[<(\d+);(\d+);(\d+)([Mm])")

# Both `[display]` in defaults/settings.toml.
REFRESH = config.setting("display.board_refresh")   # how often the collector re-collects,
                                                    # and so how often re-reading it can
                                                    # tell us anything new
CHROME = config.setting("display.board_chrome")      # header, STATS, two stats lines, a
                                                     # blank, AGENTS, tail, hints — the
                                                     # lines of this renderer that are
                                                     # not agent rows
_SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

# How much of the width the board takes when it opens beside an agent — THE ONLY
# board width there is. Every board pane is the same board showing the same fleet,
# so a human should not have to work out which spawn made the one in front of them
# from how wide it came out. The number is `sb start`'s: that board is the one a
# human sits in front of and reads, so it is the one that was tuned. Still under
# half — a roomier side panel, not the main event: the pane a human actually reads
# is the agent's own session. See `open_beside`, which inverts this into herdr's
# `--ratio`.
#
# It used to be two numbers (0.34 for a delegated child, 0.45 for the top
# orchestrator, picked by a `top=` flag on `broker._open_board`), which is exactly
# how the same view came out two sizes.
BOARD_SHARE = 0.45

# YOU ARE HERE — see `Locator`. How often a board re-asks herdr which panes share its own
# tab. The answer is a fact about a tmux tab that switchboard itself built and then leaves
# alone: `open_beside` splits an agent's pane once and neither half moves afterwards, so
# this changes at most when a human closes or opens a pane by hand. Ten seconds is a
# compromise entirely in one direction — the board redraws twice a second, and asking on
# every frame would put a subprocess on the hot path this file exists to keep clear.
HERE_REFRESH = 10.0

# The environment herdr puts in every pane it opens, read by `Locator` to answer "where am
# I". Already load-bearing elsewhere in switchboard — `broker.whoami()` reads the pane id
# to decide who is calling — so this is the same door, not a new one. Absent means the
# board is not running under herdr (a bare `python -m switchboard.board`), and the feature
# is then simply off.
TAB_ENV, PANE_ENV = "HERDR_TAB_ID", "HERDR_PANE_ID"

# Colour is a nicety, never load-bearing: every distinction below is also carried
# by a glyph or a word, so NO_COLOR loses nothing but polish.
_COLOR = os.environ.get("NO_COLOR") is None


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR and text else text


DIM, RED, YELLOW, GREEN, BLUE = "2", "31", "33", "32", "34"


# ---------------------------------------------------------------------------
# Pure: input decoding
# ---------------------------------------------------------------------------


def parse_sgr(buf: str) -> tuple[list[dict], str]:
    """Decode SGR mouse events. -> (events, leftover).

    Pure and total, so it can be tested without a terminal. Bytes that are not a
    complete escape sequence stay in `leftover` — a sequence split across two
    reads must not be reported as garbage. Anything that is not a mouse event
    comes back with `button=None` and its raw text, which is how keystrokes and
    any unexpected encoding both stay visible rather than being swallowed.
    """
    events: list[dict] = []
    pos = 0
    for m in SGR.finditer(buf):
        if m.start() != pos:
            events.append(_other(buf[pos:m.start()]))
        events.append({
            "button": int(m.group(1)),
            "col": int(m.group(2)),
            "row": int(m.group(3)),
            "press": m.group(4) == "M",
            "raw": m.group(0),
        })
        pos = m.end()

    tail = buf[pos:]
    cut = tail.rfind("\033")
    if cut == -1:
        return (events + [_other(tail)] if tail else events), ""
    if cut > 0:
        events.append(_other(tail[:cut]))
    return events, tail[cut:]


def _other(raw: str) -> dict:
    return {"button": None, "col": None, "row": None, "press": None, "raw": raw}


def is_left_click(ev: dict) -> bool:
    return ev["button"] == 0 and ev["press"] is True


def wheel(ev: dict) -> int:
    """-1 up, +1 down, 0 not a wheel event. Only meaningful on press."""
    if ev["button"] is None or not ev["press"]:
        return 0
    if ev["button"] == 64:
        return -1
    if ev["button"] == 65:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Pure: how an agent reads
# ---------------------------------------------------------------------------


def glyph(a) -> str:
    """One character for the only question worth asking at a glance: is this
    agent fine, does it want me, or is it broken?

    Order is priority, not taxonomy. `gone` outranks everything because a row
    that says `working` about a pane herdr cannot see is the one lie this view
    must never tell.
    """
    if a.gone:
        return "✗"
    if a.at_prompt or a.blocked:
        return "◐"
    if a.stalled or a.signal_drift:
        # One glyph for both, and no sixth one invented: the row is open, nothing is
        # running in it, and the note beside it says which of the two it is.
        return "◌"
    if a.finished:
        return "○"
    if a.alive is None:
        return "?"
    return "●"


_GLYPH_COLOR = {"✗": RED, "◐": YELLOW, "◌": YELLOW, "○": DIM, "?": DIM, "●": GREEN}


def wants_you(a) -> bool:
    """Whether this ROW is asking for something, as opposed to just reporting.

    Broader than `AgentStatus.needs_human` in one direction — a gone or stalled
    agent needs a person too, it just does not know it — and narrower in
    another: mail does not count here. Mail names itself where it is drawn, so
    an agent with two unread messages and a task is not dressed up as an agent
    in trouble.

    Narrower in one more way since the debounce: an inferred summons has to have
    HELD (`AgentStatus.settled`). Same set of rows, a settle window later — see
    that property, and `display.needs_settle` for what was measured.

    AWAITING KEYPRESS is in that set and not beside it: it is a narrower reading
    of a row that is already `stalled`, so `inferred_summons` covers it, and it
    is debounced exactly as the stall under it is. A human is the only thing that
    can move such an agent, which is a reason to draw the row clearly — not a
    reason to summon anybody on one frame of a screen classifier.
    """
    return bool(a.gone or a.blocked or (a.inferred_summons and a.settled))


def marker(a) -> str:
    """The trouble with this agent, or "". RANK ONE of the row's tail.

    Strictly ranked and only ever one: an agent that is both gone and blocked is
    gone, and the row says the thing a human would act on first.

    The two declared ones — GONE, BLOCKED — are drawn the instant they are seen.
    The inferred ones wait for `settled`, so a row that is between turns says
    what it is FOR rather than announcing a stall that outlives no frame; the
    state column beside it still reads `idle` the whole time.
    """
    if a.gone:
        return "GONE — herdr has no such agent"
    if a.at_prompt and a.settled:
        return "AT PROMPT — waiting on you"
    if a.blocked:
        return f"BLOCKED — {a.blocked_why or 'no reason recorded'}"
    if not a.settled:
        return ""
    if a.awaiting_keypress:
        # Above STALLED and not beside it: this is the same stall with one more thing
        # known about it, and the thing known is what the human has to DO. Below the two
        # above it because those are a person being asked an actual question; neither can
        # be true at the same time as this one anyway (both read a pane that is not idle).
        #
        # Deliberately does not name a dialog. What was observed is that herdr recognised
        # nothing on the screen — the reading a first-run picker or a login screen gives —
        # so the row says that, and says the one action that clears it whatever it turns
        # out to be. See `status.awaiting_keypress_screen`.
        return "AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane"
    if a.stalled:
        return f"STALLED — idle {status_mod.fmt_age(a.idle)}"
    if a.signal_drift:
        # Below STALLED because it is rarer. See `status.AgentStatus.signal_drift`.
        return "NO SESSION — died mid-turn, pane still open"
    return ""


def tail_note(a) -> str:
    """What this agent is FOR, or what came of it, or "". RANK THREE.

    Last because it is the least actionable thing on the line: a task head is
    context a reader can also get from the agent's own pane, where a stuck
    agent's marker and an unanswered message are things only this view will
    tell them.
    """
    if a.finished and a.summary:
        return f"done: {a.summary}"
    if a.idle_excuse:
        # THE OTHER HALF OF THE STALLED LINE, and the reason it is above the task.
        # Two rows can both say `idle` and mean opposite things: a lead waiting on
        # its children is doing exactly what the protocol asked of it, and an agent
        # that quietly died looks identical. `marker` above says "nothing explains
        # this"; this says what does. A reader never has to infer either.
        return a.idle_excuse
    return a.task or ""


def mail_note(a, *, short: bool = False) -> str:
    """The mail waiting here, or "". RANK TWO — see `detail_bits`.

    Undelivered first and named: unread means we rang and it has not looked, so
    the agent knows; undelivered means it was never told and never will be
    unless somebody notices. The remainder is counted the way `status._attention`
    counts it, by subtraction, so the two never double-count the same message.

    Words, no glyph. An envelope character is drawn one column wide by some
    terminals and two by others, and a row that is one column wider than it
    measured is the wrap this whole file is built to prevent.

    `short` is the same fact in the fewest columns it can be said in, for a
    renderer that reserves room for mail before it spends any on the name
    (`richboard.tail_forms`). Same pieces, same order, same rule about which of
    them is named and which is counted — only the wording gives.
    """
    bits = []
    if a.waiting_to_be_rung:
        bits.append(f"UNDEL {a.undelivered}" if short else
                    f"UNDELIVERED {a.undelivered}, "
                    f"{status_mod.fmt_age(a.undelivered_age)}")
    told = a.unread - a.undelivered
    if told > 0:
        bits.append(f"{told} unread")
    if not bits:
        return ""
    joined = " · ".join(bits)
    return joined if short else "mail: " + joined


def _note_color(a) -> str:
    if a.gone:
        return RED
    if a.at_prompt or a.blocked or a.stalled or a.signal_drift:
        return YELLOW
    return DIM


# What the row will not draw a piece of at all. Below this a clipped phrase is
# an ellipsis with a word in front of it, which says less than the space it
# costs — and on a single row, where the name, state and age have already taken
# their columns, this is what most often decides that only one piece is drawn.
_MIN_BIT = 10
# How much room a longer piece gives up so that MAIL can still be seen beside
# it. Bounded rather than "whatever mail needs": a marker clipped to nothing to
# make room for an unbounded count is the opposite trade.
_MAIL_RESERVE = 22


def detail_bits(a) -> list[tuple[str, str, str]]:
    """The row's tail as (text, colour, kind), HIGHEST PRIORITY FIRST.

    Everything that is detail rather than identity is here, and the order is the
    answer to the only hard question the row asks: at sixty columns they will not
    all fit, so what goes first and what goes at all?

        1. `marker`     — GONE, AT PROMPT, BLOCKED, STALLED, NO SESSION.
                          Something is wrong and a human is the only fix.
        2. `mail_note`  — undelivered or unread. Often the thing that would
                          unblock rank one, so it is never crowded out by it.
        3. `tail_note`  — the done summary, the idle excuse, or the task head.
                          Context. First to go.

    The idle excuse rides in rank three rather than getting room of its own: it
    is the calm half of the idle question ("waiting on children" against a bare
    `STALLED`), and an agent that has an excuse has no marker to compete with,
    so in practice it is what the row shows.

    Empty pieces are dropped, so an agent with nothing to say yields nothing and
    its row simply ends after the age.
    """
    bits = [(marker(a), _note_color(a), "marker"),
            (mail_note(a), YELLOW, "mail"),
            (tail_note(a), DIM, "tail")]
    return [b for b in bits if b[0]]


def _compose(bits, cols: int) -> str:
    """Draw as much of `bits` as fits in `cols` columns, priority first.

    Two rules beyond "fill until full". A piece is clipped rather than dropped
    only while it can still say something (`_MIN_BIT`); below that it is not
    drawn, because half a word is not worth a third of the line. And a piece
    gives up room ahead of MAIL specifically, up to `_MAIL_RESERVE`, so that a
    long BLOCKED reason cannot hide the answer that would end the block. Nothing
    reserves for the tail: context is what this line sheds first.
    """
    out: list[str] = []
    used = 0
    for i, (text, colour, _kind) in enumerate(bits):
        gap = 3 if out else 0                       # " · "
        room = cols - used - gap
        if i + 1 < len(bits) and bits[i + 1][2] == "mail":
            keep = min(_visible_len(bits[i + 1][0]), _MAIL_RESERVE) + 3
            if room - keep >= _MIN_BIT:
                room -= keep
        if room < _MIN_BIT:
            break
        piece = _clip(text, room)
        out.append(_c(piece, colour))
        used += gap + _visible_len(piece)
    return _c(" · ", DIM).join(out)


# ---------------------------------------------------------------------------
# Pure: the top section — the fleet's numbers, in two lines
# ---------------------------------------------------------------------------
#
# Shared by both renderers for `glyph`/`marker`/`mail_note`'s reason: what the section
# SAYS is decided once, so the panel and the plain board cannot come to report different
# numbers, and only the drawing of it differs. The dict comes from
# `panel.Reading.stats` — already computed by the collector — and NOTHING in here or
# below may import `switchboard/stats.py`, which reads the store and shells out to `git`,
# `lsof` and `ps`. See that module's note, and `tests/test_panel.py::RendererImports`.

# The label each line is read by. TIME FRAMES rather than a heading, because that is the
# half a reader cannot get from the numbers: `47 turns` says nothing about whether it is
# this hour or since Tuesday, and every figure in this section is one or the other. Both
# are nine columns, so the two lines' numbers start in the same one.
STATS_HOUR = "LAST HOUR"
STATS_NOW = "RIGHT NOW"
STATS_LABEL_W = 9
STATS_SEP = " · "                   # between pieces, as in the header line and the footer
# What a line says when it has nothing true to say — the first ~0.5 s of every board's
# life, when the collector has published a snapshot but no sample yet. A row of zeroes
# there would be a measurement nobody took; a blank line would read as a bug. This is the
# third thing, and it is the honest one.
STATS_NONE = "not measured"


def _num(stats: Optional[dict], key: str):
    """The number at `key`, or None for unknown. **None is never zero.**

    Everything in `stats.Stats` starts as None and goes back to None when its group ages
    out, so "we could not measure this" and "this measured zero" arrive as different
    values and must stay different on screen. Anything that is not a number is unknown
    too: this dict was read off a file a different process wrote.
    """
    v = (stats or {}).get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def fmt_count(n) -> str:
    """A count in as few columns as it can be said in: `47`, `4.4k`, `44k`, `1.2M`.

    Rounded, because this is a glance number in a pane that is spending a line on it.
    Nobody acts on the difference between 4,412 and 4,438 lines changed in an hour, and
    the columns the exact figure would cost are a row of the tree.
    """
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    if n < 1_000_000:
        return f"{n / 1000:.0f}k"
    return f"{n / 1_000_000:.1f}M"


def fmt_bytes(n) -> str:
    """Bytes as a glance figure: `640K`, `12M`, `1.2G`. Binary units, as `ps` reports."""
    n = float(n)
    if n < 1024 ** 2:
        return f"{max(0, int(n // 1024))}K"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.0f}M"
    return f"{n / 1024 ** 3:.1f}G"


def _plural(n, word: str) -> str:
    """`1 turn`, `2 turns`, `4.4k lines`. Plural off the raw count, not off the label."""
    return f"{fmt_count(n)} {word}" + ("" if n == 1 else "s")


def stats_rows(stats: Optional[dict]) -> list[tuple[str, list[str]]]:
    """The top section: `[(label, [piece, ...]), ...]`, pieces MOST IMPORTANT FIRST.

    Two lines, always both, so the tree below never moves under a number arriving. What
    varies is how much of each line a pane has room for — whole pieces, dropped from the
    right, the same way the header above drops its counts.

    AN UNKNOWN IS NOT DRAWN AT ALL. On the first tick every one of the fourteen fields is
    None by design (the numbers join a tick later), and a `0 turns` there would be a
    measurement this board never made. A line left with nothing to say draws `STATS_NONE`,
    which is that fact in the one place a reader would otherwise see a gap.

    The `*_age` fields are not drawn and not read. A group older than its `max_age` comes
    back None from `stats.collect` already, so an age here could only decorate a number
    that is already known to be current enough to show.

    The three ages are the only fields with no piece of their own; `cpu_cores` has none
    either, but it is read — as the denominator that turns summed CPU into a share. What is
    drawn is what a person glancing at a fleet acts on: whether it is moving, what came of
    it, and what it is costing the machine.
    """
    hour: list[str] = []
    turns = _num(stats, "turns_last_hour")
    added = _num(stats, "code_added")
    deleted = _num(stats, "code_deleted")
    commits = _num(stats, "commits_last_hour")
    spawns = _num(stats, "spawns_last_hour")
    messages = _num(stats, "messages_last_hour")
    if turns is not None:
        # FIRST, because it is the closest thing the store has to "is the fleet moving".
        hour.append(_plural(turns, "turn"))
    if added is not None and deleted is not None:
        # CODE ONLY, and COMMITTED only. Prose is filtered out upstream (`stats.is_docs`),
        # so a documentation hour does not read as a thousand lines of work; and this walks
        # commits, so uncommitted edits in a worktree are not in it. The `+/-` shape is
        # about which direction the code moved, not about a live working-tree diff.
        # Both halves or neither — a `+312` beside an unknown deletion count is a half
        # measurement wearing the punctuation of a whole one.
        hour.append(f"+{fmt_count(added)}/-{fmt_count(deleted)}")
    if commits is not None:
        hour.append(_plural(commits, "commit"))
    if spawns is not None:
        hour.append(_plural(spawns, "spawn"))
    if messages is not None:
        # MAIL, and never "calls". Andrew asked for sb calls; nothing logs one —
        # `store.log_event` is called from particular sites, so that number does not exist
        # to be reported. This is inter-agent mail, which is the honest near thing, and
        # labelling it as the thing he asked for would have the board claim a measurement
        # nobody takes. Not through `_plural`: mail is uncountable, so `3 mail` and never
        # `3 mails`.
        hour.append(f"{fmt_count(messages)} mail")

    now: list[str] = []
    cpu = _num(stats, "cpu_percent")
    cores = _num(stats, "cpu_cores")
    rss = _num(stats, "memory_bytes")
    avail = _num(stats, "memory_available_bytes")
    procs = _num(stats, "processes")
    if cpu is not None and cores:
        # A SHARE OF THE WHOLE MACHINE. `ps` sums %CPU across the fleet's process tree, so
        # on any multi-core machine the raw figure goes over 100 and reads as a broken
        # gauge; divided by the core count it is the one percentage a person can size at a
        # glance — half the machine is half the machine whatever the box has in it.
        # Unknown cores means no piece at all: a share has no meaning without its
        # denominator, and guessing one would be inventing the measurement.
        # Clamped, because a summed decaying average can momentarily overshoot the machine
        # and a `104% cpu` would read as a bug rather than as a busy fleet.
        share = min(100, max(0, round(cpu / cores)))
        now.append(f"{share}% cpu")
    if rss is not None:
        # `rss` and not "memory". This is summed resident set, so a page shared by ten
        # processes is counted ten times — an upper bound, ~6% high where it was measured.
        # The word names which number it is rather than dressing it up as the footprint.
        now.append(f"{fmt_bytes(rss)} rss")
    if avail is not None:
        # What is LEFT, straight from the OS — the fleet's number above says nothing about
        # whether the machine is near its limit, which is the thing a person watching forty
        # panes actually wants to know.
        now.append(f"{fmt_bytes(avail)} free")
    if rss is not None and avail is not None and (rss + avail) > 0:
        # The fleet's share of the memory it COULD use: its own plus what is free. Not a
        # share of physical RAM — that denominator includes everything other programs are
        # holding, which the fleet cannot have, and would report a busy machine as a light
        # one. Both halves come from the same proc sample, so this is one moment's ratio.
        now.append(f"{min(100, max(0, round(100 * rss / (rss + avail))))}% mem")
    if procs is not None:
        now.append(_plural(procs, "proc"))

    return [(STATS_HOUR, hour), (STATS_NOW, now)]


def stats_fit(pieces: list[str], cols: int) -> list[str]:
    """As many whole pieces as `cols` columns hold, in order. Whole ones or none.

    The header line drops its counts the same way and for the same reason: half a piece
    says nothing and a dangling separator says less. The list is ordered by how much each
    piece matters, so what a narrow pane keeps is the top of it — and a piece too long for
    the room left ENDS the line rather than being skipped over, because skipping would
    quietly reorder that list.
    """
    out: list[str] = []
    used = 0
    for p in pieces:
        gap = _visible_len(STATS_SEP) if out else 0
        if used + gap + _visible_len(p) > cols:
            break
        out.append(p)
        used += gap + _visible_len(p)
    return out


# ---------------------------------------------------------------------------
# Pure: layout
# ---------------------------------------------------------------------------


def _starts_group(rows, i: int) -> bool:
    """Does display row `i` begin a first-level group — so does a break go above it?

    A direct child of the top orchestrator usually bounds one task, and its whole
    subtree is that task's working-out; a root does the same at the level above.
    So a break goes above every row at depth 0 or 1, and above nothing else,
    which is what keeps a subtree contiguous: a depth-2 row can never open one.
    Never above the very first row — a screen that opens with a blank line has
    separated the tree from the header, which needs no separating.

    Reads `.depth`, which a `Collapsed` carries as well as an agent, so a
    collapsed group of first-level children is spaced off like the live ones.
    """
    return i > 0 and rows[i].depth <= 1


# The break itself. A blank line, not a rule of dashes: at sixty columns a
# full-width rule is the heaviest thing on the screen and it runs straight
# across the indentation, so the eye reads the horizontal band before it reads
# the tree — and depth is the thing this view is for. Whitespace separates
# without drawing anything, which is the whole requirement. Owned by nobody, so
# a click on it does nothing (see `layout`).
_BREAK = ""

# One rung of the tree, in columns. FOUR, not two: at two the ladder was there but did not
# read as one at a glance, which is the whole job of drawing depth at all. Named once and
# shared with `richboard` (rows, name-column widths and the workspace gutter's offset all
# have to agree, or the gutter lands outside the indentation it is drawn into) so the two
# renderers cannot come to indent by different amounts.
INDENT = "    "


def _is_group(row) -> bool:
    """Is this display row a collapsed group rather than an agent?

    One predicate, used by everything that reads a row, so there is exactly one
    place that knows how the two are told apart. Everything downstream of
    `layout` receives whatever the row carries, and reading `.name` off a group
    is the failure `layout`'s closing comment is about.
    """
    return isinstance(row, status_mod.Collapsed)


def _stats_line(label: str, pieces: list[str], width: int) -> str:
    """One line of the top section, in this renderer's own vocabulary.

    No filled bar and no colour: dim label, plain numbers, dim separators — the same trade
    the `AGENTS` label makes here, and the same one the footer makes. Polish is what this
    renderer does without; the numbers are identical to the panel's, because both ask
    `stats_rows`.
    """
    kept = stats_fit(pieces, width - 1 - STATS_LABEL_W - 2)
    body = (_c(STATS_SEP, DIM).join(kept) if kept
            else _c(_clip(STATS_NONE, max(0, width - 1 - STATS_LABEL_W - 2)), DIM))
    return _c(" " + _pad(label, STATS_LABEL_W) + "  ", DIM) + body


def layout(snap, *, top: int, height: int, width: int, msg: str,
           note_text: str = "", show_archived: Optional[bool] = None,
           here: Optional[str] = None, stats: Optional[dict] = None
           ) -> list[tuple[str, Optional[object]]]:
    """Build the whole screen as (text, agent) pairs — one per line, in order.

    The agent a row belongs to is carried BY the row rather than recomputed from
    an index, so a click can never resolve to a different agent than the one the
    human is looking at. Everything downstream just indexes this list.

    That is also how the shape of a row is allowed to change. An agent is ONE
    line — identity, then whatever of `detail_bits` fits after it — and the
    breaks between first-level groups are lines belonging to nobody. Neither
    fact is known outside this function. The row went one line → two → one
    again, and a blank line appeared between the groups, without a line changing
    anywhere else: no caller counts lines, and nothing computes which agent sits
    on screen row N.

    Every line is drawn by `emit`, which takes the owner alongside the text. A
    collapsed group carries itself; a group break carries `None`, which is what
    makes clicking it do nothing rather than focusing whatever is nearby.

    `here` — the agent sharing this board's own tab, from `Locator` — is ACCEPTED
    AND NOT DRAWN here, and the signature says so rather than the caller having to
    remember it: `_frame` calls this and `richboard.layout` with the same keywords,
    and one renderer quietly taking a keyword the other does not is how that seam
    rots. What is lost on this path is that a human on a machine without `rich`
    cannot see which agent is beside them; what would be lost by faking it is a
    working board, which is the whole reason this renderer exists. The mark is
    a background across a whole line (`richboard.HIGHLIGHT_STYLE`) and this
    renderer has no vocabulary for one — every colour it draws is a `_c` piece
    that ends in a reset, so a background would have to be re-opened after each of
    them and survive `_fit`, on the path that exists precisely so a machine without
    `rich` still has a working board. Polish is what this renderer does without.

    `stats` — the fleet's numbers, `panel.Reading.stats` as the collector computed
    them — IS drawn here, unlike `lit`: it is words, which this renderer has every
    vocabulary for, and the two boards showing different numbers would be a
    difference of fact rather than of appearance. `None` and `{}` are ordinary:
    the section draws its labels and says the numbers are not measured.

    `top` is the scroll offset in DISPLAY rows, not in agents. Those stopped
    being the same thing when collapse landed: `display_rows` replaces whole
    archived subtrees with one `Collapsed`, so a window taken over `snap.agents`
    would scroll past rows that are not drawn and the `+N more below` count would
    contradict the screen. Everything here — the slice, the clamp, the tail —
    counts what is actually on screen.

    Returns at most `height` lines.
    """
    rows: list[tuple[str, Optional[object]]] = []

    def emit(text: str, owner: Optional[object] = None) -> None:
        """Draw one line, and say in the same breath what a click on it means.

        THE ONLY WAY A LINE GETS ONTO THE SCREEN, and the reason adding or
        removing a line is safe. Nothing anywhere computes "which agent is on
        screen row N" — the answer is recorded here, as the line is built, and
        `agent_at` does nothing but index what was recorded. So dropping an
        agent's second line and inserting a blank between groups needed no
        change to the click path at all: pass the owner it belongs to, or None
        for chrome and for the breaks, and the mapping is right by construction
        rather than by a formula somebody has to remember to update.
        """
        rows.append((text, owner))

    if show_archived is None:                       # `display.show_archived`, via status,
        show_archived = status_mod.SHOW_ARCHIVED    # so both readouts share one default
    agents = status_mod.display_rows(snap.agents, show_archived=show_archived)
    # The top section is FOUR lines — its own label, two lines of numbers, and the blank
    # that holds it off `AGENTS` — and `display.board_chrome` counts them, so nothing
    # below has to learn about it. The one exception is a pane too short to hold the
    # numbers AND a single agent row, where the whole block gives its lines back: the
    # board is the tree, and a fleet's statistics over no fleet is what the last line must
    # not be spent on. `richboard.layout` makes the same trade one section later, on
    # `AGENTS`. Header and blank go back WITH the numbers — a label over nothing and a gap
    # holding nothing apart are the two things a pane this short has least use for.
    top_lines = ([_c(" STATS", DIM)]
                 + [_stats_line(label, pieces, width) for label, pieces in stats_rows(stats)]
                 + [""])
    capacity = height - CHROME
    if capacity < 1:
        capacity += len(top_lines)
        top_lines = []
    capacity = max(1, capacity)
    # How many SCREEN LINES each display row costs: its own, plus the break above it if
    # it opens a first-level group. Everything that windows or counts below reads this
    # rather than assuming one line each, the failure otherwise being a row pushed off
    # the bottom while the footer still claims it is on screen.
    breaks = [_starts_group(agents, i) for i in range(len(agents))]
    costs = [2 if b else 1 for b in breaks]
    top = max(0, min(top, _max_top(costs, capacity)))
    window: list[tuple[object, bool]] = []          # (row, draw a break above it)
    used = 0
    for i in range(top, len(agents)):
        # Never at the top of the window: a break says "a new group starts here", and
        # the top of the screen says that already. `_max_top` still charges for it,
        # which can leave one line spare at the very bottom of a scroll and never
        # overfills — the direction that is only cosmetic.
        brk = breaks[i] and used > 0
        cost = 2 if brk else 1
        if used + cost > capacity:
            break
        window.append((agents[i], brk))
        used += cost

    bits = status_mod.summary_bits(snap)
    # The headline undimmed and the rest dim — the emphasis Andrew asked for, drawn
    # rather than worded. `summary_bits` decides WHICH count leads; this only decides
    # that the leading one is the one you see first. Joined here with the same
    # separator `summary_line` uses, from the same list, so the board and `sb status`
    # cannot come to show different counts.
    # The product's own name is decoration and the headline count is not, so in a pane
    # too narrow for both, the name is what goes.
    brand = _visible_len("switchboard  ·  ") + _visible_len(bits[0]) <= width
    head = (_c("switchboard", BLUE) + _c("  ·  ", DIM) if brand else "") + bits[0]
    cols = _visible_len(("switchboard  ·  " if brand else "") + bits[0])
    for b in bits[1:]:
        # Whole counts or none, rather than letting `_fit` cut one in half. A 60-column
        # board cannot hold every count, and what it drops is the tail of a list that is
        # already ordered by how much it matters — so the totals go before the trouble
        # does, and the headline never does. `sb status` and a wider board still show
        # them all, and the archived total is on the screen anyway, in the tree's own
        # `+N archived` footer.
        if cols + 3 + _visible_len(b) > width:
            break
        head += _c(" · " + b, DIM)
        cols += 3 + _visible_len(b)
    emit(head)
    # The stats block — its own label, its numbers, and the blank line under them. See
    # `richboard._stats_block`, which makes the call about the header for both renderers;
    # here the label is dim text rather than a filled bar, exactly as `AGENTS` below is,
    # because filled bars are what this renderer does without. Owned by nobody: a click on
    # a number, on the label or on the blank focuses no agent.
    for line in top_lines:
        emit(line)
    # The tree is a SECTION here too, and for the panel's reason (`richboard.layout`): the
    # stats block above it means the tree would otherwise run straight on from a line of
    # numbers. This renderer has no filled bars, so the section reads as a dim label
    # rather than a coloured band — the same meaning in this renderer's own vocabulary.
    #
    # It REPLACED the blank line that separated the header from the tree rather than
    # being added above it — a label separates as well as a blank does, and the pane is
    # worth more than the air. The stats block above it is the one that did add lines, and
    # `display.board_chrome` went 4 → 6 → 8 for them: two for the numbers, then one each
    # for their own `STATS` label and the blank line under it. The number is what "rows
    # that are not agents" means here, and it is the one place that has to know.
    emit(_c(" AGENTS", DIM))

    if not agents:
        why = note_text or "nothing running — sb start"
        emit(_c(f"  ({why})", DIM))
    else:
        # Defaults, not `max(seq)`: a window can be nothing but collapsed rows —
        # which is the ORDINARY end-of-session state, every agent finished and
        # its pane closed — and there is then no agent to measure a name or a
        # state against. Empty-sequence `max` raises, and a panel that raises at
        # the end of every session is worse than one with a narrow column.
        # Columns, not characters, in both column widths and in every pad and clip
        # below — see `_visible_len`.
        w_name = max([0] + [_visible_len((INDENT * a.depth) + a.name)
                            for a, _ in window if not _is_group(a)])
        # `display_state`, not the store's raw word: `working` drawn next to this row's
        # own `STALLED — idle …` note is the row contradicting itself, and the one thing
        # a glanceable view must never do. See `AgentStatus.display_state`.
        w_state = max([0] + [_visible_len(a.display_state)
                             for a, _ in window if not _is_group(a)])
        for a, brk in window:
            if brk:
                emit(_BREAK)                # owned by nobody: a click here is a miss
            if _is_group(a):
                # No glyph, no state, no note. It is not an agent and must not
                # read as one — `agent_at` hands this very object to the click
                # handler, which has to be able to tell them apart.
                #
                # `INDENT`, the same rung every row above it uses: this row is the
                # footer of a block of siblings and has to start where their names
                # do. `sb status` draws the same tree two spaces at a time and
                # passes its own rung, which is why the unit is an argument.
                emit(_c("   " + status_mod.collapsed_label(a, INDENT), DIM), a)
                continue
            g = glyph(a)
            label = (INDENT * a.depth) + a.name
            # ONE LINE, and everything on it. Identity, state and age take fixed columns;
            # whatever is left goes to `detail_bits`, in priority order, and at sixty
            # columns that is usually room for one piece — which is the whole difference
            # between this and the two-line version, and why the priority matters more
            # here than it did there.
            left = (f" {g} {_pad(label, w_name)}  {_pad(a.display_state, w_state)}  "
                    f"{status_mod.fmt_age(a.idle):>5}  ")
            line = (f" {_c(g, _GLYPH_COLOR.get(g, ''))} {_pad(label, w_name)}  "
                    f"{_pad(a.display_state, w_state)}  "
                    f"{status_mod.fmt_age(a.idle):>5}  ")
            bits = detail_bits(a)
            if bits:
                # The arrow belongs to whatever leads the tail, and takes its colour, so
                # it points at a reason rather than floating: trouble, or mail, and
                # nothing at all when the tail is only saying what the agent is up to.
                lead = "← " if wants_you(a) or bits[0][2] == "mail" else "  "
                body = _compose(bits, width - _visible_len(left) - _visible_len(lead))
                if body:
                    line += _c(lead, bits[0][1]) + body
            emit(line, a)

    while len(rows) < height - 2:
        emit("")

    hidden = len(agents) - (top + len(window)) if agents else 0
    tail = f"+{hidden} more below" if hidden > 0 else ("scroll ↑" if top else "")
    if note_text and agents:
        tail = note_text
    emit(_c(tail, DIM))
    # Last on the line and dim, and only when it is true: this renderer is the FALLBACK
    # now, and a human looking at it has no other way to find out that the panelled board
    # exists and that one install away is all it is. Said here rather than in a warning
    # somewhere, because this screen is the only place the fact is relevant — and clipped
    # first, because it is the least useful thing on the line to somebody who already
    # knows. See `_frame`.
    from . import richboard
    line = (_c("click a row to focus it · scroll to pan · a archived · q quits", DIM)
            + ("   " + msg if msg else ""))
    if not richboard.available():
        # AFTER the message, so it is this note that a narrow pane clips and never the
        # answer to the click the human just made.
        line += _c("  ·  pip install rich", DIM)
    emit(line)

    # The one invariant this view rests on: no line may ever wrap. A wrapped line
    # pushes every row below it down by one, and the next click focuses the wrong
    # agent — silently, and looking exactly like a correct click. `_fit` measures
    # in columns, so this is now enforced rather than hoped for: it used to be
    # asserted in characters, which one emoji in a task was enough to break.
    return [(_fit(text, width), a) for text, a in rows[:height]]


def _max_top(costs: list[int], capacity: int) -> int:
    """The furthest a scroll may go: the first row of the last full screenful.

    In LINES, not in rows, which is the same number until a row is preceded by a
    group break and so costs two. Counts backwards from the end and stops when
    the next row up would not fit, so scrolling to the bottom lands on a full
    screen rather than on one row with blank space under it. Never past the last
    row: with a capacity too small for even that one, it is still the one to show.
    """
    total, t = 0, len(costs)
    while t > 0 and total + costs[t - 1] <= capacity:
        total += costs[t - 1]
        t -= 1
    return min(t, max(0, len(costs) - 1))


def agent_at(rows, row: int):
    """Screen row (1-based) -> whatever is drawn there, or None.

    May be a `Collapsed` as well as an agent, so every caller has to ask before
    it reads a `.name` — see `_is_group`. Not filtered to agents here on
    purpose: a click on a collapsed row is a real thing the human did, and the
    handler that decides what it means should be the one that sees it.
    """
    i = row - 1
    if i < 0 or i >= len(rows):
        return None
    return rows[i][1]


def tab_siblings(panes: list[dict], tab: Optional[str],
                 me: Optional[str]) -> list[str]:
    """Every pane id sharing `tab` that is not `me`. Pure, and the first half of the join.

    `panes` is `herdr pane list`'s `panes` array verbatim. A pane carries a `tab_id` and a
    `pane_id` and, if herdr has an agent bound to it, a generic `agent` kind — "claude",
    never the switchboard NAME, which is why this returns ids for `here_agent` to look up
    rather than a name of its own.

    NOT FILTERED TO PANES HERDR CALLS AGENTS. The board's sibling is an agent pane and
    herdr does bind those, but the filter would buy nothing — an id that belongs to no
    agent row matches no agent in `here_agent` and drops out there — and it would cost the
    one case this most has to survive: a pane herdr has momentarily lost track of is still
    the pane the human is sitting beside.

    A tab with no sibling at all is ordinary rather than exceptional: single-pane tabs
    exist, and a human may close the agent half of a pair and leave the board.
    """
    if not tab:
        return []
    return [p["pane_id"] for p in panes
            if isinstance(p, dict) and p.get("tab_id") == tab
            and p.get("pane_id") and p.get("pane_id") != me]


def here_agent(agents, pane_ids: list[str]) -> Optional[str]:
    """Which agent is sitting in one of `pane_ids`, by name. Pure, and the second half.

    TREE ORDER DECIDES A TIE, because something has to and nothing better is available: a
    tab with two agent panes in it is not a shape switchboard makes (`open_beside` splits
    once), so this is a human's hand-built tab and the first row is as good an answer as
    any. What must not happen is two rows lit — "you are here" has one answer.

    A stale `pane_id` on a row, or a sibling belonging to a fleet in another checkout,
    matches nothing and the board draws no highlight. That is the resting state of this
    feature and never an error.
    """
    if not pane_ids:
        return None
    want = set(pane_ids)
    for a in agents:
        if getattr(a, "pane_id", None) in want:
            return a.name
    return None


def pane_list() -> Optional[list[dict]]:
    """`herdr pane list` -> its `panes` array, or None if it could not be had.

    None and not `[]`, so a caller can tell "herdr said there are no panes" — which would
    mean the board's own pane does not exist — from "herdr did not answer", which is a
    hiccup to ride out on the last good answer. See `Locator._resolve`.

    Never raises: this runs on a worker thread whose exception would be lost anyway, and
    every failure it can have (herdr missing, slow, angry, or answering something that is
    not JSON) has the same meaning here — no new answer this time.
    """
    try:
        p = subprocess.run(["herdr", "pane", "list"], capture_output=True, text=True,
                           timeout=_SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    try:
        payload = json.loads(p.stdout or "")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    panes = (payload.get("result", payload) or {}).get("panes")
    return panes if isinstance(panes, list) else None


class Locator:
    """YOU ARE HERE: which agent shares this board's own tmux tab.

    Every sb-made view is one tab holding an agent pane and the board pane beside it
    (`open_beside`), so each board has exactly one agent it is sitting next to — and until
    now no board knew which. Whatever tab a human lands on, the highlighted row names the
    agent in front of them. That is the whole feature, and it REPLACED a highlight that
    marked whichever row you last clicked: one board, one meaning for a lit row.

    Three steps, and each is somewhere it can be tested: `HERDR_TAB_ID` from the
    environment (here), the tab's other pane ids from `herdr pane list` (`tab_siblings`),
    and those ids against the published rows (`here_agent`). The last hop is why
    `status.AgentStatus` carries `pane_id` at all — herdr knows panes and the store knows
    names, and a renderer may not open the store.

    OFF THE DRAWING THREAD, and that is the one thing about this class that is not
    obvious. `herdr pane list` is a subprocess costing tens of milliseconds and the board
    redraws twice a second; both blocking on it every tick and blocking on it every tenth
    tick are the same mistake, differently priced. So `tick` starts a daemon thread at most
    every `HERE_REFRESH` seconds and returns immediately, and `name` answers from the last
    result — which is a set of pane ids, joined against whatever rows the current frame has,
    so the highlight follows an agent that is renamed away or restored without waiting for
    the next subprocess.

    Every failure degrades to no highlight and none of them says anything on screen: this
    is polish, and a board that drew an error where a row's background should be would be
    reporting a fault a human can do nothing about.
    """

    def __init__(self, *, refresh: float = HERE_REFRESH,
                 env: Optional[dict] = None):
        env = os.environ if env is None else env
        self.tab = env.get(TAB_ENV) or None
        self.me = env.get(PANE_ENV) or None
        self.refresh = refresh
        self.panes: list[str] = []          # sibling pane ids, last successful answer
        self._last = 0.0
        self._busy = False

    @property
    def enabled(self) -> bool:
        """False outside herdr — a bare `python -m switchboard.board`. Not an error."""
        return self.tab is not None

    def tick(self, *, at: Optional[float] = None) -> bool:
        """Ask again if it is time to. -> whether a lookup was started. Never blocks."""
        if not self.enabled or self._busy:
            return False
        at = time.monotonic() if at is None else at
        if self._last and at - self._last < self.refresh:
            return False
        self._last = at
        self._busy = True
        threading.Thread(target=self._resolve, daemon=True).start()
        return True

    def _resolve(self) -> None:
        try:
            panes = pane_list()
            if panes is not None:
                self.panes = tab_siblings(panes, self.tab, self.me)
        finally:
            self._busy = False

    def name(self, agents) -> Optional[str]:
        """The agent to highlight on this frame, or None. Cheap: a set lookup per row."""
        return here_agent(agents, self.panes)


def _visible_len(s: str) -> int:
    """How many terminal COLUMNS `s` occupies once drawn.

    Not `len()`. A character is not a column: one CJK ideograph or emoji is two
    of them, a combining accent is none, and a family emoji is one glyph two
    columns wide however many codepoints it is made of. Measuring in characters
    is the bug this whole section exists to close — the row fits by `len()`, the
    terminal wraps it anyway, and every click below lands one agent low.
    """
    return sum(w for _, w in _clusters(_ANSI.sub("", s)))


def _pad(text: str, cols: int) -> str:
    """Left-align to `cols` COLUMNS. What `f"{text:<{cols}}"` only does for ASCII."""
    return text + " " * max(0, cols - _visible_len(text))


def _fit(text: str, width: int) -> str:
    """Guarantee a line occupies one terminal row.

    Slicing coloured text would cut an escape sequence in half, so an overlong
    line loses its colour rather than its correctness — this only happens in a
    pane too narrow to be pretty anyway. The slice is by column and on cluster
    boundaries: cutting a two-column glyph in half is how a "truncated" line
    still wraps, and cutting a combining mark off its base is how it lands on
    whatever character follows.
    """
    if _visible_len(text) <= width:
        return text
    return _clip_cols(_ANSI.sub("", text), width)


def _clip(text: str, cols: int) -> str:
    """`status.clip`, measured in columns — flatten whitespace, then fit with an ellipsis.

    A separate function rather than a change to `status.clip`, which every other
    readout shares and whose budget is a character count its own tests state.
    """
    flat = " ".join((text or "").split())
    if _visible_len(flat) <= cols:
        return flat
    return _clip_cols(flat, cols - 1) + "…"


_ANSI = re.compile(r"\033\[[0-9;]*m")
_ZWJ = "‍"
_VS16 = "️"        # emoji presentation
_VS15 = "︎"        # text presentation
_ZERO_CATEGORIES = frozenset({"Mn", "Me", "Cf", "Cc"})


def _is_zero(ch: str) -> bool:
    """Occupies no column of its own: combining marks, joiners, selectors, controls."""
    return unicodedata.combining(ch) != 0 or unicodedata.category(ch) in _ZERO_CATEGORIES


def _is_regional(ch: str) -> bool:
    return "\U0001f1e6" <= ch <= "\U0001f1ff"


def _is_modifier(ch: str) -> bool:
    """Skin tone. A wide symbol by `east_asian_width`, but it tints the glyph
    before it rather than drawing one of its own."""
    return "\U0001f3fb" <= ch <= "\U0001f3ff"


def _base_width(ch: str) -> int:
    if _is_zero(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _clusters(plain: str) -> Iterator[tuple[str, int]]:
    """Split ANSI-free text into (glyph, columns) pairs.

    A glyph, not a codepoint: everything a terminal draws in one place travels
    together, so a truncation can never land inside one. `east_asian_width` from
    the standard library carries the two-column cases — no `wcwidth` dependency —
    and the rules it does not cover are here: a variation selector chooses
    presentation and so chooses width, a regional-indicator pair is one flag, and
    a ZWJ swallows whatever it joins because the result is a single glyph.
    """
    i, n = 0, len(plain)
    while i < n:
        j = i + 1
        w = _base_width(plain[i])
        if _is_regional(plain[i]) and j < n and _is_regional(plain[j]):
            j += 1                                  # 🇯🇵 — two codepoints, one flag
            w = 2
        while j < n:
            ch = plain[j]
            if ch == _VS16:
                w = 2                               # ✈️ — drawn as emoji, so two wide
                j += 1
            elif ch == _VS15:
                w = 1                               # ✈︎ — drawn as text, so one
                j += 1
            elif ch == _ZWJ:
                j += 2 if j + 1 < n else 1          # 👩‍👩‍👧 — still one glyph, still two wide
                # and round the loop again: a longer chain is more of the same glyph.
            elif _is_zero(ch) or _is_modifier(ch):
                j += 1
            else:
                break
        yield plain[i:j], w
        i = j


def _clip_cols(plain: str, cols: int) -> str:
    """Longest prefix of ANSI-free `plain` that fits in `cols` columns.

    Comes up short by one column rather than over by one when the next glyph is
    two wide and only one column is left. Short is a cosmetic gap; over is a
    wrapped line and a misdirected click.
    """
    out, used = [], 0
    for glyph, w in _clusters(plain):
        if used + w > cols:
            break
        out.append(glyph)
        used += w
    return "".join(out)


# ---------------------------------------------------------------------------
# Impure: the snapshot file, herdr, the terminal. NOT the store — see the module note.
# ---------------------------------------------------------------------------


def refresh(sup: panel.Supervisor):
    """-> (snapshot, note, stats). One tick of a renderer. Never raises.

    Two things, and neither of them touches the store. Say a panel is still
    being looked at, starting a collector if none is up — which is how takeover
    works: the dead holder's flock is gone, so the next panel to tick replaces
    it. Then read the file.

    `note` is the panel's own condition, ranked in `panel.Reading.note`, and the
    staleness line is the reason it exists. A shared snapshot introduces exactly
    one new failure — a wedged collector leaving forty screens quietly agreeing
    on old data — so the age is printed the moment it is worth printing, and the
    board says "snapshot 40s old" instead of presenting it as now.

    `stats` is the fleet's numbers for the top section, `stats.Stats.as_dict()` as
    the collector computed them and `{}` when it published none. READ here, never
    computed: `stats.collect()` reads the store and shells out to `git`, `lsof`
    and `ps`, which is both halves of what a renderer must not do. It rides in the
    same file as everything else this function reads, so it costs no second look.
    """
    sup.tick()
    r = panel.read(sup.paths)
    return r.snap, r.note, r.stats


def focus(name: str) -> str:
    """The board's only side effect. Returns a line for the status bar."""
    try:
        p = subprocess.run(["herdr", "agent", "focus", name],
                           capture_output=True, text=True,
                           timeout=_SUBPROCESS_TIMEOUT)
    except FileNotFoundError:
        return "herdr not on PATH"
    except subprocess.TimeoutExpired:
        return f"{name}: focus timed out"
    if p.returncode != 0:
        return f"{name}: {status_mod.clip((p.stderr or p.stdout or 'focus failed'), 50)}"
    return f"→ {name}"


def open_beside(h, pane_id: str, *, cwd: str) -> Optional[str]:
    """Split `pane_id` and run the board in the new pane. -> new pane id, or None.

    Called by `broker._open_board`, so every agent lands with the tree up beside
    it — `sb start`'s orchestrator and every `sb delegate` child alike, at the same
    width: the share is `BOARD_SHARE` and there is no parameter to pass a different
    one, which is what makes "every board pane is the size `sb start` gives it" a
    property of the code rather than of the callers agreeing.

    `BOARD_SHARE` is the BOARD's share of the width, which is the number a reader
    wants to reason about; herdr's `--ratio` is the *other* number — what the pane
    being split keeps — so it is inverted on the way out. The board is the small
    pane: the agent's own session is the thing being read, and the tree beside it
    is a glance.

    Returns None rather than raising on any herdr failure, and callers ignore the
    result: a spawn failing because a *view* would not open is a far worse bug
    than spawning without one.

    Launches `sys.executable -m switchboard.board` rather than `sb board`, so it
    does not depend on `sb` being on PATH in that pane, and cannot trip the
    human-only gate on the way in.
    """
    from .herdr import HerdrError

    try:
        pane = h.split_pane(pane_id, direction="right", ratio=1 - BOARD_SHARE, cwd=cwd)
    except (HerdrError, OSError):
        return None
    try:
        h.prompt_pane(pane, f"exec {sys.executable} -m switchboard.board")
    except (HerdrError, OSError):
        try:
            h.close_pane(pane)          # a bare shell pane is worse than no pane
        except Exception:
            pass
        return None
    return pane


def _size() -> tuple[int, int]:
    try:
        c = os.get_terminal_size()
        return c.lines, c.columns
    except OSError:
        return 24, 80


def _frame(snap, *, top: int, height: int, width: int, msg: str, note_text: str,
           show_archived: bool, here: Optional[str] = None,
           stats: Optional[dict] = None
           ) -> list[tuple[str, Optional[object]]]:
    """One frame, from whichever renderer can draw it. THE SEAM, and all of it.

    `richboard` is the look Andrew approved and it needs `rich`, which is
    switchboard's first ever runtime dependency and an OPTIONAL one: there is no
    packaging file, `bin/sb` runs the checkout under whatever `python3` is on
    PATH, and on the same machine one interpreter has `rich` and the next does
    not. So the board must not become unrunnable because it is missing — it
    falls back to `layout` above, which is the board this repo has always drawn
    and is missing nothing but the polish.

    The fallback is per FRAME, not per process, because `richboard.layout`
    declines a pane too small to be a panel and declines a frame whose line
    count did not come back the way it was built. Both are conditions that clear
    on their own, and either way the caller gets the same `[(text, owner)]` list
    and indexes it the same way.
    """
    # Imported here rather than at the top of the file, and it is not laziness:
    # `richboard` imports THIS module for the rules a row is drawn by, so an
    # import at the top would run it against a half-built `board`. It pulls in
    # no `rich` of its own — every one of those imports is inside a function —
    # so this costs a dictionary lookup per frame.
    from . import richboard

    rows = richboard.layout(snap, top=top, height=height, width=width, msg=msg,
                            note_text=note_text, show_archived=show_archived, here=here,
                            stats=stats)
    if rows is not None:
        return rows
    return layout(snap, top=top, height=height, width=width, msg=msg,
                  note_text=note_text, show_archived=show_archived, here=here, stats=stats)


def draw(snap, top: int, msg: str, note_text: str, show_archived: bool,
         here: Optional[str] = None, stats: Optional[dict] = None) -> list:
    height, width = _size()
    rows = _frame(snap, top=top, height=height, width=width, msg=msg,
                  note_text=note_text, show_archived=show_archived, here=here, stats=stats)
    out = ["\033[H\033[2J"]
    out.append("\r\n".join(text for text, _ in rows))
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    return rows


def sweep_tick(armed: int, note: list) -> int:
    """Run the half-hourly worktree sweep if this board is the one that gets to. Returns
    the slot now armed, whether or not anything ran.

    The board is the trigger because there is nothing else: switchboard has no daemon, and
    the collector is elected per repo by an flock in a process that must never touch the
    store. So the sweep rides the one long-lived human-facing loop there is — and that
    means **no board running is no sweep**, which is accepted.

    `armed` is the slot this board has already seen, initialised at startup to the slot it
    started IN. A board opened at :17 therefore sweeps at :30 and not at :17: the trigger
    is a boundary being crossed while the board watches, never "it has been a while".

    Every agent's pane opens with a board beside it, so a fleet of twenty crosses :30
    twenty times at once. `sweep.claim` is what makes exactly one of them run — an flock
    around a marker file in the repo's shared `.git`, which is the only thing boards in
    different worktrees have in common.

    In a subprocess, and its output goes to a note rather than to the terminal: this pane
    is in raw mode with mouse reporting on, and anything written to it that the frame
    loop did not draw corrupts the screen.
    """
    slot = sweep_mod.slot_of(time.time())
    if slot == armed:
        return armed
    if not sweep_mod.ENABLED or not sweep_mod.claim(slot):
        return slot
    threading.Thread(target=_sweep, args=(note,), daemon=True).start()
    return slot


def _sweep(note: list) -> None:
    """The sweep itself, off the drawing thread. Never raises into it."""
    try:
        out = subprocess.run(sweep_mod.command(), capture_output=True, text=True,
                             env=sweep_mod.environ())
        line = (out.stdout or out.stderr or "").strip().splitlines()
        note.append(f"sweep: {line[0] if line else 'nothing to do'}")
    except (OSError, subprocess.SubprocessError) as e:
        note.append(f"sweep did not run: {e}")


def main() -> int:
    if not sys.stdin.isatty():
        print("board: stdin is not a tty — run this in a pane.", file=sys.stderr)
        return 2

    # Resolved before raw mode, because this is the one failure a panel cannot
    # draw its way out of: with no repo there is no snapshot to read and no
    # collector to elect. Cheap and subprocess-free — see panel.git_common_dir.
    try:
        sup = panel.Supervisor(panel.Paths.resolve())
    except (RuntimeError, OSError) as e:
        print(f"board: {e}", file=sys.stderr)
        return 2

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    restored = False

    def restore(*_):
        nonlocal restored
        if restored:
            return
        restored = True
        try:
            os.write(sys.stdout.fileno(), (MOUSE_OFF + SHOW_CURSOR).encode())
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    # try/finally is not enough on its own: SIGTERM and SIGHUP skip it entirely,
    # and a pane left in raw mode with mouse reporting on is unusable.
    def bail(_sig, _frame):
        restore()
        os._exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, bail)

    dirty = [True]

    def on_resize(_sig, _frame):
        dirty[0] = True

    signal.signal(signal.SIGWINCH, on_resize)

    # `a` toggles from wherever `display.show_archived` starts it. The KEY is not
    # persisted, deliberately: a panel is cheap, every pane has its own, and a
    # toggle that outlives the pane is a setting — which is exactly what the
    # setting it starts from is for. `layout` clamps `top` every call, so the row
    # count changing under the toggle needs nothing here.
    top, msg, buf = 0, "", ""
    show_archived = status_mod.SHOW_ARCHIVED
    # Which agent shares this pane's tab — the row this board highlights. Built here and
    # not at import, so the environment it reads is this process's own, and asked again per
    # frame because the answer is a NAME resolved against the rows being drawn.
    where = Locator()
    # The slot this board started in, so the first sweep is at the next boundary and never
    # at startup — see `sweep_tick`. `sweep_note` is the worker thread's one-slot mailbox.
    armed, sweep_note = sweep_mod.slot_of(time.time()), []
    try:
        tty.setraw(fd)
        sys.stdout.write(MOUSE_ON + HIDE_CURSOR)
        sys.stdout.flush()

        snap, note_text, stats = refresh(sup)
        where.tick()
        rows = draw(snap, top, msg, note_text, show_archived,
                    where.name(snap.agents), stats)
        last = time.time()

        while True:
            r, _, _ = select.select([fd], [], [], 0.25)
            if r:
                data = os.read(fd, 1024)
                if not data:                      # stdin closed
                    break
                buf += data.decode("utf-8", "replace")
                events, buf = parse_sgr(buf)
                for ev in events:
                    if ev["button"] is None:
                        if "q" in ev["raw"] or "\x03" in ev["raw"]:
                            raise KeyboardInterrupt
                        if "r" in ev["raw"]:
                            last = 0.0
                        if "a" in ev["raw"]:
                            show_archived = not show_archived
                            dirty[0] = True
                        continue
                    step = wheel(ev)
                    if step:
                        top = max(0, top + step * 3)
                        dirty[0] = True
                        continue
                    if is_left_click(ev):
                        a = agent_at(rows, ev["row"])
                        if _is_group(a):
                            # Focusing "the archived ones" is not a thing herdr can
                            # do, and reading `.name` here is the misclick this
                            # branch exists to prevent. Say what would work.
                            msg = "press a to show archived"
                        else:
                            # A click still focuses, and now that is ALL it does: the row
                            # background stopped meaning "the one you just touched" and
                            # started meaning "the one beside you", and one board cannot
                            # have two meanings for one mark. What a click did that was
                            # worth keeping — jumping to the pane — is here, and what it
                            # said on screen is said by the status line.
                            msg = focus(a.name) if a else ""
                        dirty[0] = True

            if time.time() - last >= REFRESH:
                snap, note_text, stats = refresh(sup)
                dirty[0] = True
                last = time.time()
                # On the refresh tick rather than every select timeout: a two-second
                # granularity is plenty for a boundary that comes twice an hour, and this
                # is the one place in the loop that already costs something.
                armed = sweep_tick(armed, sweep_note)
                # On the refresh tick, for `sweep_tick`'s reason and one of its own: this
                # only ever STARTS a lookup, and starting one twice a second to have it
                # declined by the throttle is work for nothing. `Locator` holds the real
                # cadence; this just gives it chances to fire.
                where.tick()
            if sweep_note:
                msg = sweep_note.pop()
                dirty[0] = True
            if dirty[0]:
                # Asked HERE, on the frame being drawn, rather than when the pane list came
                # back: the cached answer is a set of pane IDS, and turning those into the
                # name of a row is done against the rows this frame actually has. So an
                # agent that is restored, renamed away, or dropped from the snapshot stops
                # or starts being highlighted on the next frame, with no subprocess in it.
                rows = draw(snap, top, msg, note_text, show_archived,
                            where.name(snap.agents), stats)
                dirty[0] = False
    except KeyboardInterrupt:
        pass
    finally:
        restore()
    return 0


if __name__ == "__main__":
    sys.exit(main())
