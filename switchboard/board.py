"""The clickable board — a human's live view of the tree. A RENDERER.

Three ways in, all the same screen: `sb start` opens one beside the orchestrator
it starts, `sb board` opens one here, and
`python3 -m switchboard.board` is the plumbing both go through.

This is a HUMAN-ONLY surface and must stay one. `sb board` is hidden from
`--help` and refuses any caller that `whoami()` resolves to an agent, and the
board appears nowhere in defaults/protocol.md, which is where an agent actually
learns what `sb` can do. Its side effects are two, and both are a human's own
hand: `herdr agent focus`, jumping to a pane, and four presses of `c`, which
runs `sb cleanup` on the highlighted agent (`cleanup_agent`). The second one
destroys things, and it reaches them exactly as the first does — a separate
process, off the drawing thread, never the store.

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

import importlib
import importlib.util
import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import unicodedata
from collections import deque
from pathlib import Path
from typing import Callable, Iterator, Optional

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
# What a TRAILING escape sequence has to look like to be worth waiting for: the start of
# an `SGR` above and nothing else. `os.read` gives no guarantee of landing on a sequence
# boundary, so a partial mouse report is held for the next read — but an ARROW KEY is
# `ESC [ A`, which is complete the moment it arrives and would otherwise sit in the buffer
# until the human happened to press something else. The `<` is what tells them apart: an
# SGR mouse report always has one, and no cursor key does.
_PARTIAL = re.compile(r"\033(\[(<[\d;]*)?)?$")

# Both `[display]` in defaults/settings.toml.
REFRESH = config.setting("display.board_refresh")   # how often the collector re-collects,
                                                    # and so how often re-reading it can
                                                    # tell us anything new
CHROME = config.setting("display.board_chrome")      # header, STATS, two stats lines, a
                                                     # blank, AGENTS, tail, hints — the
                                                     # lines of this renderer that are
                                                     # not agent rows
MIN_AGENTS = config.setting("display.board_min_agents")   # the AGENTS panel's floor, in
                                                          # lines — see `split_panels`
CURSOR_HOLD = config.setting("display.board_cursor_hold")   # seconds the arrow-key
                                                            # cursor stands — see `main`
PAN_STEP = config.setting("display.board_pan_step")         # columns per ← or →
# The keys this board answers to, said once and drawn by both renderers — the same reason
# `stats_rows` is shared. A footer that offered a key the board does not read, or stayed
# quiet about one it does, is worse than no footer: nobody presses what they were not told
# about, and nobody trusts a line that was wrong once.
KEYS = "click a row · ↑↓ pick · ⏎ focus · ←→ pan plans · a archived · q quits"
# The fewest lines a plugin section is worth drawing in: its own blank, its heading, one
# line of what it has to say, and the `+ N more below` that admits to the rest. Below this
# a section is a heading over nothing, so it gives its lines back instead — which is what
# `split_panels` spends it on, and the only place it is read.
SECTION_MIN = 4
_SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")
_EDITOR = config.setting("editor.command")   # `[editor]`, and see `open_report_files`

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
# The `oo` hint. Yellow like every other line on this board that is asking for a hand,
# and bold because it is the one piece of chrome that appears and disappears — a human
# who has not noticed it yet has to be able to.
HINT = "1;33"


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

    Only a PARTIAL MOUSE REPORT is held back (`_PARTIAL`). It used to be everything
    from the last `ESC` onwards, which is the same thing right up until a key that IS
    an escape sequence: an arrow key arrives complete and would have been held until
    the human pressed something else, so `↑` did nothing and then did two things at
    once.
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
    if cut == -1 or not _PARTIAL.match(tail, cut):
        return (events + [_other(tail)] if tail else events), ""
    if cut > 0:
        events.append(_other(tail[:cut]))
    return events, tail[cut:]


def _other(raw: str) -> dict:
    return {"button": None, "col": None, "row": None, "press": None, "raw": raw}


def is_left_click(ev: dict) -> bool:
    return ev["button"] == 0 and ev["press"] is True


# The cursor keys, in both encodings a terminal sends them in: `ESC [ A` in normal mode
# and `ESC O A` in application mode. The board never asks for either, so it takes what it
# is given rather than betting on which mode the terminal it was opened in happens to be
# in.
_ARROW = re.compile(r"\033[\[O]([ABCD])")
_ARROW_NAME = {"A": "up", "B": "down", "C": "right", "D": "left"}


def arrows(ev: dict) -> list[str]:
    """Every cursor key in one read, in the order they were pressed.

    A LIST, because one `os.read` can carry a held-down key several times over and a
    board that acted on one of them would crawl behind the human's finger. Same reason
    `double_press_run` counts characters rather than asking whether one arrived.
    """
    if ev["button"] is not None:
        return []
    return [_ARROW_NAME[m.group(1)] for m in _ARROW.finditer(ev["raw"])]


def entered(ev: dict) -> bool:
    """Was Return pressed? Both encodings, for `arrows`' reason."""
    return ev["button"] is None and ("\r" in ev["raw"] or "\n" in ev["raw"])


def step_cursor(names: list[str], name: Optional[str], delta: int) -> Optional[str]:
    """The agent one row up or down from `name`, in a list of display rows.

    THE CURSOR WALKS THE TREE AND THE WINDOW FOLLOWS IT, which is why this takes the whole
    tree's names (`status.board_rows`) rather than the frame's: an arrow held down at the
    bottom of a window would otherwise stop at whatever the last drawn row happened to be,
    and the board would scroll under a cursor that had stopped moving. `main` scrolls when
    the answer is a row this frame did not draw.

    A tree with no rows at all — nothing running — has nowhere to put a cursor and says
    so. A cursor already at either end stays there: a walk that wrapped round would move
    the pane the whole way across the fleet on one keypress.

    A `name` that is no longer in the tree — archived, renamed, finished — starts over
    from the end the key came from, which is where a human expects the FIRST press to land.
    """
    if not names:
        return None
    if name not in names:
        return names[0] if delta > 0 else names[-1]
    return names[max(0, min(len(names) - 1, names.index(name) + delta))]


def drawn_names(rows) -> set:
    """Every agent this frame actually drew a row for. See `step_cursor`."""
    return {o.name for _, o in rows if o and o is not SECTION_ZONE}


def pan_columns(text: str, cols: int) -> str:
    """`text` with its first `cols` visible columns dropped, and its colour kept.

    WHAT LEFT AND RIGHT DO, and the reason they are not a slice: a plugin's line carries
    SGR (`_colour_only`), and cutting a string at a character offset would either cut a
    colour sequence in half or drop the one that opened the colour still in force. So the
    sequences in the dropped part are kept and only the printable columns go — the line
    comes back the colour it was, starting `cols` columns further along.

    Columns, not characters, measured by `_visible_len` like every other width here. A
    wide character straddling the cut is dropped whole rather than half-drawn, which can
    shift such a line by one column against its neighbours; that is the honest end of the
    trade, and the alternative is a broken glyph.
    """
    if cols <= 0 or not text:
        return text
    out: list[str] = []
    dropped, i = 0, 0
    while i < len(text):
        m = _ANSI.match(text, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        if dropped >= cols:
            break
        dropped += _visible_len(text[i])
        i += 1
    return "".join(out) + text[i:]


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

    Reads `.depth`: every row here is an agent, and the board draws no
    stand-in rows at all (`status.board_rows`).
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


# ---------------------------------------------------------------------------
# The plugin seam — extra lines under a worktree group
# ---------------------------------------------------------------------------

# WHAT A PLUGIN SHIPS TO DRAW HERE, and the whole of the contract:
#
#     <plugin>/board.py        defining
#     board_lines(state_dir: Path, workspace: str, rows: list) -> Sequence[str]
#
# `rows` is the display rows of ONE worktree group, in the order they are drawn, and it is
# how a plugin learns anything about who is alive: an `AgentStatus` already carries
# `alive`, `state`, `gone` and `display_state`, computed once per snapshot by the
# collector. A plugin that wants an owner's status reads it off the row it was handed. It
# must not go and ask — the board redraws every couple of seconds, and a subprocess per
# frame per group is the one cost this seam exists to not have.
#
# A SEPARATE FILE, and not a function in the plugin's `__init__.py`, for one reason worth
# the extra convention: the question this file asks on a repo with nothing to draw is
# `<plugin>/board.py`.is_file(), which imports NOTHING. A plugin that draws nothing costs
# nothing at all, which is what makes "the board with no drawing plugin renders exactly as
# it did before" a property of the code rather than a promise about it.
BOARD_FILE = "board.py"
_STEM = "board"                                 # `BOARD_FILE` without its extension
BOARD_HOOK = "board_lines"

# WHERE a plugin's lines go, and the whole of that half of the contract: a `board.py` that
# also sets a module-level `SECTION = "PLANS"` is drawn as its own SECTION UNDER THE TREE,
# in the same place and the same vocabulary as `STATS` and `AGENTS`, instead of hanging
# under the worktree group its lines came from. Both renderers put it directly after the
# agents, with one blank line above it.
#
# ONE HOOK AND NOT TWO. `board_lines` is still called exactly as before — once per
# worktree, handed that worktree's rows — and a section is that same answer collected and
# labelled rather than a second thing a plugin has to implement. So a plugin moves between
# the two placements by adding or deleting one line, and the seam has one contract to be
# right about instead of two that must not drift.
#
# Why a plugin would want it: a block under a group reads as a FOOTNOTE to those agents,
# which is right for a line or two about them and wrong for something with a shape of its
# own. The plans plugin draws a flowchart per plan; a picture wants a section and a
# heading, not a hanging indent under the last row of a tree.
BOARD_SECTION = "SECTION"

# What a section title may be, once a plugin has been asked for one: short, printable, and
# drawn in the same voice as the board's own labels. A plugin that sets something else
# gets no section — its lines fall back to hanging under their group, which is what the
# seam did before sections existed and is never worse than a wrecked heading.
SECTION_MAX = 24

# The name a plugin package is imported under — `plugins._MODULE_PREFIX`, the same string
# deliberately, so a plugin already imported by an `sb plugin` call in this process is
# found rather than executed a second time under a second name.
_MODULE_PREFIX = "sb_plugin_"

# The most lines one plugin may contribute to one group. Not a layout limit — the window
# math below cuts a block to whatever the pane has left anyway — but a backstop against a
# plugin whose state grew unbounded turning every frame into a thousand-line list to slice.
HOOK_LINES = 40

# What a line a plugin hands over may not contain: C0, DEL, C1, and the two separators that
# end a line in some readers and not others. The same class the plans plugin escapes on the
# way IN (`_CONTROL` there) — one rule for "this is not part of a line", stated twice
# because the board has to hold it for plugins that never thought about it.
#
# `ESC` is in that range and is NO LONGER stripped wholesale: `_colour_only` lifts the SGR
# sequences out first and runs this over what is left, so a plugin may colour a word and
# still may not move the cursor. See that function for why the two were worth separating.
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")

# Closed after any line a plugin coloured, so an unbalanced sequence cannot leak into the
# rows below it. See `_colour_only`.
_SGR_RESET = "\033[0m"

# The subdirectory a plugin's state lives in under the store — `plugins._STATE_SUBDIR`.
# Named again here because `_state_dir` below resolves the path the renderer-safe way and
# so cannot go through the function that owns the constant; `tests/test_board.py` pins the
# whole path against `plugins.state_root`, which is what keeps the two from drifting.
PLUGIN_STATE_SUBDIR = "plugins"

# `{worktree: [(name, board_lines, state_dir, section)]}`. Discovered ONCE per process,
# because
# importing is the expensive half and a board redraws every couple of seconds. The price
# is that enabling a plugin reaches an already-open board only when it is reopened, and
# that is the right way round: a directory that changes almost never must not be re-globbed
# and re-imported sixty times a minute.
#
# WHAT IS CACHED IS THE PLUGIN, NEVER ITS STATE. The path is fixed for a worktree and is
# resolved once with it; whether anything is IN it is asked at draw time and never here.
# A state directory is made by a plugin's first COMMAND, so the ordinary first use of this
# whole feature — open the board, then create the first plan — is exactly the case where
# it does not exist yet, and a cache that wrote "nothing to draw" then would keep saying so
# until the pane was closed. Nothing on screen would have said why.
_HOOKS: dict[str, list[tuple[str, Callable, Path, Optional[str]]]] = {}


def board_hooks(worktree: Optional[Path] = None
                ) -> list[tuple[str, Callable, Path, Optional[str]]]:
    """Every enabled plugin that draws on the board, resolved and cached.

    Nothing here can fail loudly. A board is what a human looks at to find out that
    something has gone wrong, so a plugin that will not import, or a repo that is not a
    repo, costs its own lines and nothing else — never the frame.
    """
    key = str(worktree) if worktree is not None else str(Path.cwd())
    if key not in _HOOKS:
        try:
            _HOOKS[key] = _discover(Path(key))
        except Exception:                       # noqa: BLE001 — see the docstring
            _HOOKS[key] = []
    return _HOOKS[key]


def _discover(worktree: Path) -> list[tuple[str, Callable, Path, Optional[str]]]:
    """Import the `board.py` of every enabled plugin that has one.

    `switchboard.plugins` IS NOT IMPORTED HERE, and that is why this globs two directories
    itself rather than calling `plugins.available`. `report-bug` and `suggestions` ship
    enabled, so this runs on every board in every repo, and the import graph a renderer is
    allowed is the load-bearing property `tests/test_panel.py::RendererImports` exists to
    keep — one this file should not be spending on a directory listing. (`plugins` is
    reachable without a store since its `store` import moved inside `state_root`, which is
    a change PR8 made for the plugin packages this seam imports; it is still not a module
    a renderer should be pulling in for a glob.) The path is not borrowable either way:
    `plugins.state_root` goes through `store.repo_root()`, which spawns `git`. See
    `_state_dir`. `tests/test_board.py` pins both copies against the originals.
    """
    enabled = config.plugin_enablement(worktree)
    if not enabled:
        return []
    # Shipped first, then the repo's own, which replaces a shipped one of that name
    # wholesale. `plugins.available`'s rule, including the `__init__.py` test that tells a
    # plugin from a pre-rename preset sitting in the same directory.
    found: dict[str, Path] = {}
    for root in (config.defaults_dir() / "plugins", config.path_for("plugins_dir",
                                                                    worktree)):
        if root is None or not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "__init__.py").is_file():
                found[d.name] = d

    out: list[tuple[str, Callable, Path, Optional[str]]] = []
    for name in enabled:
        d = found.get(name)
        # THE WHOLE COST OF A PLUGIN THAT DRAWS NOTHING: one `is_file`. Nothing is
        # imported, so a board in a repo whose plugins all draw nothing is byte for byte
        # the board this file drew before the seam existed.
        if d is None or not (d / BOARD_FILE).is_file():
            continue
        try:
            mod, hook, section = _load_drawer(name, d)
        except KeyboardInterrupt:
            raise
        except BaseException:                   # noqa: BLE001 — a broken plugin costs the
            continue                            # board nothing; `sb plugin list` reports it
        if not callable(hook):
            continue
        state = _state_dir(worktree, name, str(getattr(mod, "SCOPE", "repo")))
        if state is None:
            continue
        out.append((name, hook, state, section))
    return out


def _load_drawer(name: str, d: Path) -> tuple[object, object, Optional[str]]:
    """The plugin package, then its `board.py`, then the hook and the section title on it.

    The PACKAGE first and under the same module name `plugins._import` gives it
    (`sb_plugin_<name>`), so that `board.py`'s own `from . import …` reaches the plugin it
    is part of and so that a plugin already imported by an `sb plugin` call in this process
    is not imported a second time under a second name.
    """
    modname = _MODULE_PREFIX + name
    mod = sys.modules.get(modname)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            modname, d / "__init__.py", submodule_search_locations=[str(d)])
        if spec is None or spec.loader is None:
            raise ImportError(f"{d}/__init__.py is not importable")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod              # before exec: a package imports itself
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(modname, None)
            raise
    drawer = importlib.import_module(f"{modname}.{_STEM}")
    return (mod, getattr(drawer, BOARD_HOOK, None),
            _section_title(getattr(drawer, BOARD_SECTION, None)))


def _section_title(given: object) -> Optional[str]:
    """A plugin's `SECTION`, vetted, or None — which means "hang under the group".

    Vetted HERE, once at discovery, rather than where the heading is drawn: a title is
    read from a plugin at import time and never changes, and a renderer asking the same
    question sixty times a minute is the cost this whole seam is arranged to avoid.

    Upper-cased because the two headings it stands beside are `STATS` and `AGENTS` and a
    section that shouted differently would read as a different KIND of thing. Flattened
    and length-capped for `_hook_lines`' reason, one register up: a heading is drawn into
    a filled bar in one renderer, and a control character or a title wider than the pane
    breaks the bar rather than merely looking wrong.
    """
    if not isinstance(given, str):
        return None
    text = " ".join(_CONTROL.sub(" ", given).split()).upper()
    return text[:SECTION_MAX] or None


def _state_dir(worktree: Path, name: str, scope: str) -> Optional[Path]:
    """Where this plugin keeps its state — resolved the way a RENDERER is allowed to.

    `plugins.state_root` is the same answer and is NOT used, for the reason
    `panel.git_common_dir` exists at all: it goes through `store.repo_root()`, which spawns
    `git rev-parse` on every call, and a renderer spawns no subprocess. `git_common_dir` is
    the board's own resolver for exactly this and is pinned against `store.repo_root()` by
    `tests/test_panel.py`; `tests/test_board.py` pins this against `plugins.state_root`, so
    the two spellings of one path cannot come apart.

    THE DIRECTORY IS NOT REQUIRED TO EXIST, and this is the one place that could quietly
    make the feature not work. sb makes a plugin's state directory when the plugin's first
    COMMAND runs, so a board opened before the first `sb plugin plans create` is looking at
    a path that is not there yet — and refusing the hook on that basis, once, into a cache
    that lives as long as the pane, is a plan that never appears. The path is what is
    fixed; its contents are what change, and reading them is the drawer's job on every
    frame. Nothing here creates it either — a board draws, it does not initialise.

    None only when there is no path to name: not a repo, or a setting that will not
    resolve.
    """
    try:
        if scope == "user":
            root = Path(config.setting("paths.user_state", repo=worktree)).expanduser()
        else:
            root = panel.git_common_dir(worktree) / config.setting("paths.store_dirname")
    except (RuntimeError, OSError, KeyError):
        return None
    return root / PLUGIN_STATE_SUBDIR / name


def group_extras(rows: list) -> list[list[str]]:
    """Per display row: the lines plugins draw under it. Aligned with `rows`, one entry each.

    THE BOARD'S ONE EXTENSION POINT, and it knows nothing about what the lines say. Every
    plugin that draws is asked about each WORKSPACE on screen, and the answer is hung on
    the last row of that workspace's last run, which is where a block reads as belonging to
    the rows above it.

    ONCE PER WORKSPACE AND NOT ONCE PER RUN, which is the distinction that matters.
    `richboard.group_runs` brackets runs of CONSECUTIVE rows sharing a workspace, and one
    workspace can hold two of them — a lead that delegated one child elsewhere and kept
    another at home puts its own workspace on both sides of the other one. Asking per run
    drew that workspace's block twice, said the same plan twice, and paid the drawer twice
    for it. So the runs are collected first: the rows handed over are every row of the
    workspace, in screen order, and the block is drawn under the last of them.

    Per ROW rather than per group so the window arithmetic has one number for each thing it
    windows: a row costs its own line plus whatever hangs off it, and `_max_top` never has
    to learn what a group is. A run cut in half by the window keeps its block off screen
    with the row it hangs on, which is right — a block under a group whose tail is not
    drawn would be a block under nothing.

    A plugin that declared a `SECTION` is skipped here entirely: its lines are drawn once,
    below the tree, by `section_extras`. Skipped rather than drawn in both places, which
    would be the same plan said twice on one screen.
    """
    out: list[list[str]] = [[] for _ in rows]
    hooks = [h for h in board_hooks() if not h[3]]
    if not hooks or not rows:
        return out                              # today's board, and nothing imported
    for ws, idx in _by_workspace(rows).items():
        group = [rows[i] for i in idx]
        lines: list[str] = []
        for _name, hook, state, _section in hooks:
            lines.extend(_hook_lines(hook, state, ws, group))
        out[idx[-1]] = lines
    return out


def section_extras(rows: list) -> list[tuple[str, list[str]]]:
    """The sections plugins draw BELOW the tree: `[(title, lines), ...]`, in plugin order.

    The same hook and the same per-workspace questions `group_extras` asks — see
    `BOARD_SECTION` for why one hook serves both placements. What differs is only where
    the answers go: collected across every workspace on screen into one titled block,
    instead of hung on the last row of each group.

    IN SCREEN ORDER, and the workspaces are still asked one at a time, so a section reads
    top to bottom in the order the tree above it does. Nothing is inserted between one
    workspace's lines and the next: what a section says about which worktree a line came
    from is the PLUGIN'S editorial problem, not the board's, and a board that started
    captioning a plugin's output would be deciding what the plugin meant.

    A section with no lines is not returned at all, so a plugin with nothing to say costs
    no heading and no blank — the same rule the group block has always followed.

    Not windowed here. `HOOK_LINES` still caps each plugin per workspace, and the two
    renderers cut the block to what their pane has left; this only says what there is.
    """
    hooks = [h for h in board_hooks() if h[3]]
    if not hooks or not rows:
        return []
    groups = _by_workspace(rows)
    out: list[tuple[str, list[str]]] = []
    for _name, hook, state, section in hooks:
        lines: list[str] = []
        for ws, idx in groups.items():
            lines.extend(_hook_lines(hook, state, ws, [rows[i] for i in idx]))
        if lines:
            out.append((str(section), lines))
    return out


def _by_workspace(rows: list) -> dict:
    """`{workspace: [row index, ...]}` in screen order — every row of it, runs merged.

    ONCE PER WORKSPACE AND NOT ONCE PER RUN, which is the distinction that matters and the
    reason this is a function rather than two loops. `richboard.group_runs` brackets runs
    of CONSECUTIVE rows sharing a workspace, and one workspace can hold two of them — a
    lead that delegated one child elsewhere and kept another at home puts its own
    workspace on both sides of the other one. Asking per run drew that workspace's block
    twice, said the same plan twice, and paid the drawer twice for it.
    """
    from . import richboard

    out: dict[str, list[int]] = {}
    for first, last in richboard.group_runs(rows):
        out.setdefault(rows[first].workspace, []).extend(range(first, last + 1))
    return out


def _hook_lines(hook: Callable, state: Path, workspace: str, group: list) -> list[str]:
    """One plugin's answer for one group: text, flattened to lines, or nothing at all.

    Every failure is nothing at all. A plugin that raises, returns the wrong type, or hands
    back a newline in a string it called a line is drawing on a HUMAN'S ONLY LIVE VIEW of
    the fleet, and the board losing a row to it — or wrapping, which moves every row below
    and misaims the next click — is a worse outcome than a plan going unshown.

    That guarantee is kept HERE and not asked of the plugin, because the seam is a generic
    extension point and the manners of code nobody in this repo wrote are not a guarantee.
    A control character is the sharp end of it: `ESC [ 2J` clears the pane and `ESC [ H`
    moves the cursor, and neither is SGR, so `_ANSI` does not see them and `_fit` carries
    them to the terminal intact. A raw TAB is the same class — `_visible_len` scores it 0, the
    terminal expands it to the next multiple of eight, and the line that "fits" wraps.

    Not a timeout, though, and the omission is deliberate rather than missed: a drawer that
    HANGS holds the render thread and the board with it, and there is no way to bound a
    synchronous in-process call without a thread per frame. The contract is that a drawer
    is cheap, and it is a contract rather than an enforcement.
    """
    try:
        given = hook(state, workspace, group)
    except KeyboardInterrupt:
        raise
    except BaseException:                       # noqa: BLE001 — see the docstring
        return []
    if not isinstance(given, (list, tuple)):
        return []
    out: list[str] = []
    for item in given[:HOOK_LINES]:
        if not isinstance(item, str):
            continue
        # Split rather than refused: one line is one row here, and a plugin that put a
        # newline in a string is describing two rows however it meant it. Then everything
        # left with no glyph becomes ONE SPACE — one rule, and the only one that keeps the
        # count of columns honest: a dropped character would shift a plugin's own alignment
        # and a kept one is a character this board cannot measure.
        out.extend(_colour_only(part) for part in item.splitlines() or [""])
    return out[:HOOK_LINES]


def _colour_only(line: str) -> str:
    """A plugin's line with its COLOUR kept and every other escape flattened to a space.

    The seam used to strip `\\x1b` with the rest of C0, which made "a plugin may not move
    the cursor or clear the pane" and "a plugin may not use colour" the same rule. They
    are not the same rule. `ESC [ 2J` is a plugin reaching past its own lines and into the
    human's only live view of the fleet; `ESC [ 32m` is a plugin saying which of its words
    matter, on a board whose every other line is already coloured, and where a plugin's
    alternative is spending a COLUMN on what a colour says for free.

    So the split is by sequence rather than by character: `_ANSI` matches select-graphic-
    rendition and nothing else — no cursor motion, no erase, no mode set, no OSC — and
    what falls between the matches goes through `_CONTROL` exactly as the whole line did
    before. Everything the old rule protected is still protected, and the board's own
    `_visible_len`, `_pad` and `_fit` already measure and cut around SGR, so a coloured
    line costs the layout nothing.

    A RESET IS APPENDED to any line that coloured anything, and this is the part that is
    not optional: a plugin that opens green and forgets to close it would otherwise paint
    the footer, the next agent's row, and everything else the terminal draws after it.
    The board is not entitled to trust that a plugin balanced its own sequences.
    """
    parts: list[str] = []
    painted = False
    at = 0
    for m in _ANSI.finditer(line):
        parts.append(_CONTROL.sub(" ", line[at:m.start()]))
        parts.append(m.group())
        painted = True
        at = m.end()
    parts.append(_CONTROL.sub(" ", line[at:]))
    return "".join(parts) + (_SGR_RESET if painted else "")



def _block_line(text: str) -> str:
    """A plugin's line, indented to where it reads as hanging under the group above it.

    ONE RUNG IN, and a fixed one. A group's rows are at whatever depths they are at, so
    indenting to the group would put two blocks on two screens at two different columns
    for no reason a reader could name; a block one rung inside the leftmost name column is
    in the same place every time and is plainly not a row of the tree.
    """
    return "   " + INDENT + text


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


class _SectionZone:
    """The owner every plugin-section line carries, so a scroll knows which panel it is in.

    FALSY ON PURPOSE, and that is the whole trick. Owners are recorded line by line as a
    frame is built (`layout.emit`) and read back by `agent_at`, whose callers ask `if a`
    before touching `a.name` — so a sentinel that is false answers "no agent here" to every
    one of them without a single caller learning that sections exist. What DOES ask is the
    wheel, which compares against this object by identity and scrolls the section instead
    of the tree (`board.main`).

    One object for every plugin's section, not one per plugin: what a wheel over PLANS and
    a wheel over some future section mean is the same thing, which is "not the tree".
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:                   # only ever seen in a test failure
        return "<section>"


SECTION_ZONE = _SectionZone()


def split_panels(avail: int, want_agents: int, n_section: int) -> tuple[int, int]:
    """How many lines the tree gets and how many the plugin sections do: `(agents, section)`.

    THE ONE PLACE THE PANE IS DIVIDED, shared by both renderers so they cannot come to
    give the same fleet two different shapes. `avail` is what is left once the head, the
    footer and NEEDS YOU have been paid for; `want_agents` is what the whole tree would
    cost in lines; `n_section` is how many lines the sections would take in full.

    What it is for. A section used to be sized FIRST and the tree given the remainder, so a
    worktree carrying a dozen plans took the tree down to one row — and the section was cut
    off at the bottom of the pane anyway, so the squeeze bought nobody anything. Each panel
    now gets a share and scrolls inside it (`section_window`, and `top` for the tree).

    The rules, in order:

    - Everything that fits is drawn. Only a pane too small for both divides anything, and
      the tree's claim on it includes the floor: ten lines for three agents, so that the
      section under them sits still while agents come and go.
    - Contended, they split it: each panel takes what it wants up to half the pane, and
      whatever the other did not need goes back to the one still short. So thirty agents
      and three lines of plans is 30/3 and not 15/3, and thirty agents against forty lines
      of plans is an even half each.
    - THE TREE'S BLANK PADDING IS NOT WORTH MORE THAN A SECTION'S LINES, and is given up
      when — and only when — that is what makes the section whole. Half a flowchart is not
      a smaller picture, it is a wrong one, so it is that trade or no trade: padding is
      never spent to make a section merely longer. The rows themselves are never touched,
      which is the whole difference from the arrangement this replaced.
    - A SECTION BEING CUT MUST STILL BE WORTH THE LINES (`SECTION_MIN`): a heading over
      nothing and a `+ 40 more below` is not a section, it is the memory of one, and a
      pane that short has better uses for four lines. It hands them all back and the tree
      takes the pane — which is what this board did with every section before any of this,
      and is still the right answer at the bottom of the range. A section that fits WHOLE
      is never held to this: two lines that say everything they have to say are a section.

    Pure, so it is asked wherever it is needed rather than threaded through anything.
    """
    if n_section <= 0 or avail <= 0:
        return avail, 0
    want = max(MIN_AGENTS, want_agents)
    if want + n_section <= avail:
        return want, n_section
    room = min(want, max(MIN_AGENTS, avail // 2), avail)
    section = min(n_section, avail - room)
    short = n_section - section
    if 0 < short <= room - want_agents:
        room, section = room - short, section + short
    if section < min(n_section, SECTION_MIN):
        return avail, 0
    return min(want, avail - section), section


def section_window(n: int, top: int, room: int) -> tuple[int, int]:
    """Which plugin-section lines are on screen: `[first, last)`, `first` the clamped top.

    `room` is every line the section panel has, the two scroll lines included: one for
    `↑ N above` when there is something above and one for `+ N more below` when there is
    something below, charged here rather than discovered afterwards — `richboard._window`
    charges for the tree's the same way, and for the same reason.

    Section lines are lines and not rows: a section is a blank, a heading and whatever the
    plugin drew, and nothing here knows which is which. So a window can open in the middle
    of a flowchart, exactly as a scrolled terminal does, rather than being snapped to a
    section boundary the caller would then have to define.

    `top` is clamped to the first line of the last full screenful, so scrolling to the
    bottom lands on a full panel rather than on one line with blank space under it.
    """
    if room <= 0 or n <= 0:
        return 0, 0
    if n <= room:
        return 0, n
    first = max(0, min(top, n - (room - 1)))     # the last screenful still spends a line
    last = first + room - (1 if first else 0)    # on `↑ N above`, and this one does not
    if last < n:
        last -= 1                                # and this one spends one on the rest
    return first, min(last, n)


def layout(snap, *, top: int, height: int, width: int, msg: str,
           note_text: str = "", show_archived: Optional[bool] = None,
           here: Optional[str] = None, stats: Optional[dict] = None,
           openable=None, section_top: int = 0, cursor: Optional[str] = None,
           pan: int = 0) -> list[tuple[str, Optional[object]]]:
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

    Every line is drawn by `emit`, which takes the owner alongside the text. An
    agent row carries its agent; a group break carries `None`, which is what
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

    `top` is the scroll offset in DISPLAY rows, not in agents. Those are not the
    same thing: `board_rows` drops finished subtrees and the breaks between groups
    are lines belonging to nobody, so a window taken over `snap.agents` would
    scroll past rows that are not drawn and the `+N more below` count would
    contradict the screen. Everything here — the slice, the clamp, the tail —
    counts what is actually on screen.

    `section_top` is that same offset for the panel UNDER the tree — whatever a plugin
    draws as a section of its own. Two offsets because there are two panels: a wheel over
    the plans scrolls the plans and a wheel over the tree scrolls the tree, which is the
    only reading of "scroll" that still works once neither of them fits. `split_panels`
    divides the pane between the two and `section_window` windows the lower one, both
    shared with the panelled renderer so the two boards cannot come to disagree about the
    shape of the same fleet.

    `cursor` is the agent the ARROW KEYS are over, or None — the second highlight, the
    one that comes and goes. It IS drawn here, unlike `here`, and in this renderer's own
    vocabulary: a `▸` in the column before the glyph rather than a background across the
    row. A background is what this renderer cannot draw; a mark is not, and this is the
    one highlight that has to be visible on every board, because RETURN acts on it. A
    human who cannot see where the cursor is cannot press Return safely.

    `pan` is how many columns LEFT and RIGHT have moved a PLUGIN'S text. Only a plugin's:
    a plan's flowchart is the one thing on this board genuinely wider than the pane, and
    panning the agent rows as well would take names off the screen to fix a problem the
    names do not have. Headings stay put too — they are never the part that was cut off,
    and a panel whose own name has scrolled away is a panel you cannot identify.

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
    agents = status_mod.board_rows(snap.agents, show_archived=show_archived)
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
    # Whatever a plugin draws as a section of its own, sized BEFORE the tree is windowed
    # because it is what the tree has to share the pane with. A blank line above each
    # heading, so the section is held off the last agent the way `STATS` is held off the
    # first — the padding belongs to the section and travels with it, so a section that
    # gives its lines back gives the blank back too.
    #
    # NOT `_block_line` and NOT `DIM`, which is the difference between a section and the
    # block that hangs under a group. That indent is a hanging one — it says "this belongs
    # to the rows above" — and the dim says the same thing again; a section belongs to the
    # board, sits under its own heading, and is drawn at the shallow indent every other
    # section's body uses. Undimmed also means a plugin's own colours land at full
    # strength, which is the point of having let them through the seam at all.
    section: list[str] = []
    for title, lines in section_extras(agents):
        section.extend([""] + [_c(" " + title, DIM)]
                       + ["  " + pan_columns(x, pan) for x in lines])
    # How many SCREEN LINES each display row costs: its own, plus the break above it if
    # it opens a first-level group. Everything that windows or counts below reads this
    # rather than assuming one line each, the failure otherwise being a row pushed off
    # the bottom while the footer still claims it is on screen.
    breaks = [_starts_group(agents, i) for i in range(len(agents))]
    # And plus whatever a plugin draws under it: the last row of a worktree group carries
    # its group's block, so a row is no longer one or two lines but one or two plus N. This
    # is the ONE place that number is computed; everything that windows, clamps or counts
    # below reads `costs`, which is why a variable-height block needed no new arithmetic.
    extras = group_extras(agents)
    costs = [(2 if b else 1) + len(extras[i]) for i, b in enumerate(breaks)]
    # THE PANE, DIVIDED — see `split_panels`, which is shared with the panelled renderer.
    # The tree keeps a floor of its own however much a plugin has to say (`MIN_AGENTS`),
    # and what it does not need goes to the section, which scrolls inside whatever it got
    # rather than running off the bottom of the pane.
    capacity, section_room = split_panels(height - CHROME, sum(costs), len(section))
    # AND THEN THE NUMBERS, on a pane too short even for what came back from that. The
    # section has already given its lines up by here — `split_panels` hands them over
    # whole on a pane that cannot hold a tree and a section at once — so what is left to
    # give is the fleet's statistics, and after them nothing: the board is the tree, and a
    # board with no agent row on it has stopped being the thing anybody opened. The
    # numbers are still charged in `CHROME` until they go, which is why this adds them
    # back rather than subtracting them.
    if capacity < 1:
        capacity += len(top_lines)
        top_lines = []
    capacity = max(1, capacity)
    # The section's own window, and the two lines it spends on saying there is more. Built
    # here and not where it is drawn, because the padding under the tree is measured off
    # what it comes to: the AGENTS panel is `capacity` lines whether or not the tree fills
    # them, which is what stops the section moving up the pane as agents finish.
    first_s, last_s = section_window(len(section), max(0, section_top), section_room)
    below: list[str] = []
    if first_s:
        below.append(_c(f"  ↑ {first_s} above", DIM))
    below.extend(section[first_s:last_s])
    if last_s < len(section):
        below.append(_c(f"  + {len(section) - last_s} more below", DIM))
    top = max(0, min(top, _max_top(costs, capacity)))
    window: list[tuple[object, bool, list[str]]] = []   # (row, break above it, its block)
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
        # THE ROW OUTRANKS ITS BLOCK. A block taller than the room left is cut and the
        # agent row is still drawn, rather than the pair of them being dropped together:
        # the tree is what this screen is for, and a plan tall enough to fill a pane must
        # not be able to push the agent it hangs off the bottom of it.
        block = extras[i][:max(0, capacity - used - cost)]
        window.append((agents[i], brk, block))
        used += cost + len(block)

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
        # them all.
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
        used = 1                                 # what the panel's padding is measured off
    else:
        # Defaults, not `max(seq)`: a window can hold no agent row at all — a
        # plugin's block hanging under a group whose rows are all above the window
        # is one — and there is then no name or state to measure. Empty-sequence
        # `max` raises, and a panel that raises is worse than one with a narrow
        # column. Columns, not characters, in both column widths and in every pad
        # and clip below — see `_visible_len`.
        w_name = max([0] + [_visible_len((INDENT * a.depth) + a.name)
                            for a, _, _ in window])
        # `display_state`, not the store's raw word: `working` drawn next to this row's
        # own `STALLED — idle …` note is the row contradicting itself, and the one thing
        # a glanceable view must never do. See `AgentStatus.display_state`.
        w_state = max([0] + [_visible_len(a.display_state)
                             for a, _, _ in window])
        for a, brk, block in window:
            if brk:
                emit(_BREAK)                # owned by nobody: a click here is a miss
            g = glyph(a)
            # The arrow-key cursor, in the column the gutter would use in the other
            # renderer — so it costs no width and moves no name. UNCOLOURED, and that is
            # deliberate: every colour on this board already means something about the
            # agent, and where the human's own cursor is is not a fact about the agent.
            lead = "\u25b8" if cursor is not None and a.name == cursor else " "
            label = (INDENT * a.depth) + a.name
            # ONE LINE, and everything on it. Identity, state and age take fixed columns;
            # whatever is left goes to `detail_bits`, in priority order, and at sixty
            # columns that is usually room for one piece — which is the whole difference
            # between this and the two-line version, and why the priority matters more
            # here than it did there.
            left = (f"{lead}{g} {_pad(label, w_name)}  {_pad(a.display_state, w_state)}  "
                    f"{status_mod.fmt_age(a.idle):>5}  ")
            line = (f"{lead}{_c(g, _GLYPH_COLOR.get(g, ''))} "
                    f"{_pad(label, w_name)}  "
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
            # The group's block, under the last row of the group. Dim and owned by nobody
            # — it is not an agent, and a click on it must miss rather than focus whatever
            # agent happens to be nearest.
            for extra in block:
                emit(_c(_block_line(pan_columns(extra, pan)), DIM))

    # THE AGENTS PANEL IS `capacity` LINES WHETHER OR NOT THE TREE FILLS THEM. Padded out
    # here, and only when there is a section to hold off: with nothing under the tree these
    # lines and the slack below are the same blank run, and spending them here would take
    # the `oo` hint's lines instead. What the padding buys is a section that sits in the
    # same place from one frame to the next rather than walking up the pane every time an
    # agent finishes.
    if below:
        for _ in range(max(0, capacity - used)):
            emit("")
    # Plugin sections, under the whole tree and owned by the SECTION — never by an agent,
    # so a click on a plan is still a miss (`agent_at`'s callers ask `if a`, and the
    # sentinel is false), and a wheel over one scrolls the section rather than the tree.
    # Already carrying their own blank line above (see `section`), so there is nothing to
    # remember here about padding.
    for line in below:
        emit(line, SECTION_ZONE)

    # The `oo`/`ww` hint, above the footer and only when there is something to open —
    # see `hint_lines`. It takes its lines out of the slack rather than off the tree, and
    # goes when a pane is too short to spare them: the tree is what the board is for.
    # `openable` is `Reports.tick`'s whole (files, has_worktree) pair — see `tick`.
    hint = hint_lines(here, *(openable or ([], False)))
    if len(rows) + len(hint) > height - 2:
        hint = []
    while len(rows) < height - 2 - len(hint):
        emit("")
    for line in hint:
        emit(_c(line, HINT))

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
    line = _c(KEYS, DIM) + ("   " + msg if msg else "")
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

    An agent, or None for chrome — a header line, a break between groups, a
    plugin's block. Every row that carries an AGENT carries a real one, because the
    board draws no stand-in rows (`status.board_rows`), so the caller reads a
    `.name` off whatever comes back that is truthy.

    Truthy, not "not None": a plugin section's line comes back as `SECTION_ZONE`,
    which is false, so a caller asking `if a` sees no agent there exactly as it did
    before the sections had an owner at all. The wheel is the one caller that asks
    which sentinel it is, because that is the question "which panel am I over".
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
    """A human jumping to a pane. Returns a line for the status bar.

    Also what `cccc` does before it cleans anything up — see `cleanup_agent`, which is
    where the ordering is argued.
    """
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


# What double-`o` opens, and how it decides. Prose fences a path in backticks nearly
# every time it names one, so that is the first cut; the rest is there because prose
# also CITES code it merely read — `board.py:1914-1929` is a citation, not a file to
# open, and the line range is what says so. So a line range REJECTS a candidate; it
# used to be stripped, which admitted the very thing it identified.
_BACKTICKED = re.compile(r"`([^`]+)`")
_LINE_SUFFIX = re.compile(r":\d[\d-]*$")
# Relative, absolute or `~`-rooted, and it must end in a short extension. Where it
# points is decided below, not here: an absolute path outside the agent's worktree is
# admitted by this and dropped by the containment check.
_PATHLIKE = re.compile(r"^(~/|/)?[\w.][\w./-]*\.[a-zA-Z0-9]{1,5}$")

# Two or three messages can name a handful of paths each, and a dozen new tabs is not
# "here is what it wrote", it is a mess to close.
MAX_OPEN_FILES = 6

# How long after an `o` a second one still counts as a double press, in seconds.
DOUBLE_PRESS = 1.0


def report_files(texts, cwd: str, *, limit: int = MAX_OPEN_FILES) -> list[str]:
    """The files an agent's recent prose named, under its worktree. Oldest named last.

    A heuristic, and two filters carry it: a line range means the agent was citing
    code rather than naming its own output, and everything left has to be a real file
    UNDER the agent's cwd. Shape alone would open half the words in a sentence; the
    filesystem answers "is this a file" better than any regex can. What survives both
    and still should not have is a file the agent read and named without a line range —
    accepted, because nothing in the text distinguishes that from one it wrote.

    Scanned NEWEST message first, so when there are more candidates than `limit` the
    ones that survive are the most recently named — the final summary's report file,
    not six files an earlier message happened to cite. The list is returned in reading
    order, so the newest lands last and is the tab the editor leaves in front.

    Containment is judged on the path as written, normalised, and NOT on
    `Path.resolve()`: `.switchboard` in a worktree is a symlink into the main checkout,
    and resolving would put the briefs this feature exists to open outside the cwd they
    were named relative to. KNOWN AND ACCEPTED COST of that choice: a symlink inside the
    worktree pointing out of it satisfies containment, so `evidence/id_rsa.pub` behind
    `evidence -> ~/.ssh` would open. It escalates nothing — the agent that could plant
    that symlink can already read the file — and the harm is a file being presented as
    the agent's own output when it is not. Resolving would close it and would break the
    ordinary case, so this is a limitation, not an oversight.

    Every path returned is ABSOLUTE, and that is load-bearing rather than incidental: an
    editor argument that came back relative could begin with a dash, and a file named
    `-g.py` would then reach `cursor -r -g` as an option instead of a path.
    """
    if limit <= 0:
        return []
    # abspath, not normpath: a relative cwd would otherwise carry through to every path
    # this returns. `cwd` is stored absolute by every writer today, so this enforces
    # what is currently only inherited.
    root = Path(os.path.abspath(cwd))
    groups: list[list[str]] = []
    seen: set[str] = set()
    total = 0
    for text in reversed(list(texts)):
        group: list[str] = []
        for span in _BACKTICKED.findall(text):
            cand = span.strip()
            if not cand or cand.startswith("http") or _LINE_SUFFIX.search(cand):
                continue
            if not _PATHLIKE.match(cand):
                continue
            try:
                joined = Path(os.path.normpath(root / Path(cand).expanduser()))
                if not joined.is_absolute() or not joined.is_relative_to(root):
                    continue
                if not joined.is_file():
                    continue
            except (OSError, ValueError):
                continue
            key = str(joined)
            if key in seen:
                continue
            seen.add(key)
            group.append(key)
            total += 1
            if total >= limit:
                break
        if group:
            groups.append(group)
        if total >= limit:
            break
    # A message at a time, so the cap is spent newest-first while each message keeps the
    # order it named things in.
    return [f for group in reversed(groups) for f in group]


def double_press(last: float, now: float, window: float = DOUBLE_PRESS):
    """-> (fire now?, the `last` to keep). A key that does nothing on its own.

    Reset-after-fire, so a third press inside the window starts a new pair rather
    than firing again off the second one. `now` is a MONOTONIC clock: on the wall
    clock a backward step between two presses makes the gap negative, which reads as
    "inside the window", and a single `o` would open the editor.
    """
    if now - last < window:
        return True, 0.0
    return False, now


def double_press_run(last: float, presses: int, now: float,
                     window: float = DOUBLE_PRESS):
    """The same, for a RUN of presses that arrived together. -> (fire?, new `last`).

    One terminal read can carry several keystrokes — `parse_sgr` hands the whole run
    back as one event with `raw="oo"`, which is what two quick presses look like
    whenever the loop was busy for a few tens of milliseconds (a refresh tick, or the
    `sb inspect` this very action runs), and what key auto-repeat looks like always.
    Membership (`"o" in raw`) counted that as ONE press, so the intended double press
    was exactly the case that never fired.

    Fires at most once per run: two pairs in one burst are a human leaning on the key,
    not a request to open the same files twice.
    """
    fired = False
    for _ in range(max(presses, 0)):
        fire, last = double_press(last, now, window)
        fired = fired or fire
    return fired, last


# How many presses of `c` clean up the highlighted agent. FOUR and not two, because it
# is the only key on this board that destroys anything — it closes two panes and can
# delete a worktree — and two is a number a hand resting on a keyboard reaches by
# accident. Four is the whole guard: there is no confirmation prompt behind it.
CLEANUP_PRESSES = 4


def multi_press(last: float, count: int, now: float, needed: int,
                window: float = DOUBLE_PRESS):
    """`double_press` for a run of `needed` of them. -> (fire?, `last`, `count`).

    A COUNTER, where the double press needs only a float: two presses can be told from
    one by "is there an unspent press inside the window", which is exactly what a
    non-zero `last` says, and three cannot. So `double_press` is left as it is — a count
    that is only ever 0 or 1 improves nothing there — and this is the shape the four-press
    key needs.

    The window is BETWEEN CONSECUTIVE PRESSES rather than around the run as a whole, and
    that is what makes this four presses rather than two doubles: `cc` … pause … `cc`
    fires under a chained-doubles reading and does nothing at all under this one. A pause
    is a hand that stopped, and what the guard has to establish is that it did not.

    Reset-after-fire, exactly as `double_press`: a fifth press starts a new count rather
    than firing again off the fourth.
    """
    count = count + 1 if now - last < window else 1
    if count >= needed:
        return True, 0.0, 0
    return False, now, count


def multi_press_run(last: float, count: int, presses: int, now: float, needed: int,
                    window: float = DOUBLE_PRESS):
    """The same, for a RUN that arrived together. -> (fire?, new `last`, new `count`).

    `double_press_run`'s reason, and more of it: one terminal read carries whatever was
    waiting, so four quick presses of one key reach the loop as a single event with
    `raw="cccc"` whenever the loop was busy for a few tens of milliseconds, and key
    auto-repeat is that always. Four presses in a row is the shape MOST likely to arrive
    coalesced, which makes `raw="cccc"` the ordinary spelling of this keystroke rather
    than an exotic one — counting per character, not membership, is what makes it fire.

    Fires at most once per run: somebody leaning on `c` is one request to clean an agent
    up, and a second firing would land on whatever the board highlights next.
    """
    fired = False
    for _ in range(max(presses, 0)):
        fire, last, count = multi_press(last, count, now, needed, window)
        fired = fired or fire
    return fired, last, count


def next_focus(rows, name: str) -> Optional[str]:
    """Which agent to focus once `name` is cleaned up, in board order. Pure.

    THE POINT IS THAT A BOARD IS STILL ON SCREEN, not which board: cleanup closes the
    pane pair the human is sitting in, and any other live agent comes back up in its own
    two-pane layout. So this takes the reading that needs no explaining — the row below,
    or the row above when the one going away was the last.

    ARCHIVED ROWS ARE NOT CANDIDATES. Archived is exactly "herdr has no pane for it"
    (`AgentStatus.archived`), and focusing a pane that does not exist gets a refusal
    instead of a board. `a` draws those rows, so they are in what this is given and have
    to be dropped here.

    None when nothing else is left to look at, which the caller reports rather than
    turning into a focus of nobody.
    """
    order = [a.name for a in rows]
    i = order.index(name) if name in order else -1
    below = [a.name for a in rows[i + 1:] if not a.archived and a.name != name]
    if below:
        return below[0]
    above = [a.name for a in rows[:max(i, 0)] if not a.archived and a.name != name]
    return above[-1] if above else None


def open_report_files(name: Optional[str]) -> str:
    """Double-`o`: what the highlighted agent wrote, in the editor. Files only.

    ONE shell-out, `cursor -r <every file at once>`, and no folder argument: `ww`
    opens the worktree now, and this used to open it first — a second, still-in-flight
    subprocess the file calls were racing. `-r` is not about recency, whatever the
    one-line CLI doc says: it sets `forceReuseWindow`, which is what stops the user's
    own `window.openFilesInNewWindow` setting overriding the editor's own choice of
    window. That choice is CONTAINMENT — a window whose folder holds the file wins,
    longest match first — so the files land in the worktree's own window whenever it
    is open, and fall back to the last active one only when no window contains them.
    With no editor window at all the fallback is a ROOTLESS window: the files as tabs
    and no file tree. Pressing `ww` first is the fix for that, and it is a habit
    rather than something this can do anything about.

    No `-g`: it only switches path parsing into `path:line:col` mode, and `_LINE_SUFFIX`
    already drops every candidate ending in a line number, so it was inert. `-g` would
    be worth reconsidering only if `_PATHLIKE` were ever loosened to admit one.

    Zero files is a NO-OP and returns before the editor is touched at all. `cursor -r`
    with no paths is a valid call that raises an empty window, so an agent that wrote
    nothing would pop the editor open to say "no files found" in the status bar.

    Where the worktree and the transcript come from is the one thing here that is not
    the obvious way round. Both live in the store, and this module may not read the
    store at ANY depth — a renderer that can reach `store.connect` can reach a schema
    rebuild, which is why `tests/test_panel.py` bans the import outright rather than
    trusting each edit to pick the read-only door. So the answer is asked of a separate
    `sb inspect --json` process, exactly as a click already asks `herdr` to focus a
    pane: out of process, on a keypress, never on the drawing path.

    NOT ON THE DRAWING THREAD — `open_tick` runs this in one of its own, for
    `Locator`'s reason and more of it. Eight subprocesses at ten seconds each is eighty
    seconds a synchronous version could freeze the loop for, and a frozen board is worse
    than it sounds: raw mode has cleared ISIG, so ctrl-C is a byte in a buffer and not a
    signal, and nothing the human types would end it. Off the thread the loop keeps
    drawing and the answer arrives in the status bar when it arrives.

    Returns a line for the status bar and never raises: an exception here would take the
    board down over a missing binary, which is a thing a settings file can cause.
    """
    if not name:
        return "press o on a highlighted agent"
    where = locate(name)
    if where is None:
        return f"{name}: could not read this agent"
    cwd, transcript = where
    if not cwd:
        return f"{name}: no worktree to open"

    files = files_for(cwd, transcript)
    # BEFORE the editor is touched: see the docstring — a pathless `cursor -r` raises a
    # window rather than doing nothing, which is the opposite of what no files means.
    if not files:
        return f"{name}: no files found in recent messages"
    try:
        _editor("-r", *files)
    except FileNotFoundError:
        return f"{name}: {_EDITOR} not on PATH"
    except PermissionError:
        # A command that is there and cannot be run: a wrapper script nobody chmodded,
        # or `command` naming the .app bundle rather than the CLI inside it.
        return f"{name}: {_EDITOR} is not executable"
    except subprocess.TimeoutExpired:
        return f"{name}: {_EDITOR} timed out"
    except subprocess.CalledProcessError as e:
        # The editor RAN and refused. BEFORE the clause below, which would catch it —
        # this is the one failure whose reason is both actionable and already written
        # for us, so it gets the line rather than a generic "failed".
        return f"{name}: {_editor_said(e)}"
    except (OSError, subprocess.SubprocessError) as e:
        # Everything else the exec can fail with — a fork that runs out of memory, a
        # bad interpreter line. A setting must not be able to end the board.
        return f"{name}: {_EDITOR} failed: {status_mod.clip(str(e), 40)}"
    return f"→ {name}: opened {len(files)} file(s)"


def open_worktree(name: Optional[str]) -> str:
    """Double-`w`: the highlighted agent's worktree folder in the editor.

    `open_report_files`' other half, and the one that gives a window a ROOT. `cursor
    <cwd>` and no `-r`: for a folder, `-r` would force whatever window was last active
    to change what it is showing, where the bare call is the one that skips a window
    already open on exactly that folder and focuses it instead. Two ways that skip
    still misses, both accepted: a worktree that is one folder of a MULTI-ROOT window
    (the skip wants a single-folder window), and a `cwd` reaching the same directory
    through a symlink (the match is URI equality, not realpath). Both open a second
    window on something already visible.

    The directory is checked first because nothing else here would: `open_report_files`
    gets a deleted worktree for free — no file under it survives `is_file()`, so it
    says "no files found" — and this has no such filter.

    Returns a line for the status bar and never raises, for `open_report_files`' reason:
    a settings file must not be able to take the board down.
    """
    if not name:
        return "press w on a highlighted agent"
    where = locate(name)
    if where is None:
        return f"{name}: could not read this agent"
    cwd, _ = where
    if not cwd:
        return f"{name}: no worktree to open"
    if not os.path.isdir(cwd):
        return f"{name}: worktree no longer exists"
    try:
        _editor(cwd)
    except FileNotFoundError:
        return f"{name}: {_EDITOR} not on PATH"
    except PermissionError:
        return f"{name}: {_EDITOR} is not executable"
    except subprocess.TimeoutExpired:
        return f"{name}: {_EDITOR} timed out"
    except subprocess.CalledProcessError as e:
        return f"{name}: {_editor_said(e)}"      # see `open_report_files`
    except (OSError, subprocess.SubprocessError) as e:
        return f"{name}: {_EDITOR} failed: {status_mod.clip(str(e), 40)}"
    return f"→ {name}: opened worktree"


# How long a `locate` answer is trusted, and how often a highlighted agent with no
# transcript yet is asked about again, in seconds. It bounds the ONLY subprocess on the
# hint's path to one a minute for the one agent that is highlighted — a session id that
# changed under a restore, or a transcript that did not exist when the board first
# looked, is picked up within that and nothing is asked again in between.
_REPORTS_RECHECK = 60.0


def hint_lines(name: Optional[str], files, has_worktree: bool = False) -> list[str]:
    """The `oo`/`ww` hint: two lines, one, or nothing. Both renderers draw these strings.

    Shown ONLY when the highlighted agent has something to open, which is what makes it
    a hint rather than chrome: a key that would do nothing is not advertised, and the
    count is the thing worth knowing before pressing it. Files are what `oo` needs and
    a worktree is what `ww` needs, so an agent with a worktree and nothing written yet
    gets the one line that is true for it.

    ONE block and never two, because the budget is two lines of slack (see `layout`)
    and a second gate would want a third: the files case carries `ww` on its second
    line rather than adding a line of its own.

    `ww` goes FIRST on that shared line, which reads a little backwards and is about
    clipping: a narrow pane cuts the line from the right (`_fit`), and with `oo` first
    the cut lands mid-`ww` and leaves "· w" on screen — a key that is advertised and
    does nothing. Losing the `oo` tail instead costs nothing, since the line above it
    is already about the files.
    """
    if not name:
        return []
    if files:
        n = len(files)
        return [f"{name} wrote {n} file{'' if n == 1 else 's'} you can open",
                "press ww for the worktree · oo for "
                f"{'it' if n == 1 else 'them'} in {_EDITOR}"]
    if has_worktree:
        return [f"press ww to open {name}'s worktree in {_EDITOR}"]
    return []


class Reports:
    """Whether the highlighted agent has anything for `oo`/`ww` to open — every frame.

    The hint only shows when there is something to open, so the drawing thread has to
    know the answer every frame, and it costs a fork plus a transcript read. This is
    the whole of what makes that affordable:

      * per frame, ONE `stat` of the transcript, and nothing else;
      * the answer is cached against `(agent, transcript mtime)`, so while the highlight
        sits on one agent and its transcript is not growing, every frame is that stat and
        a dict lookup;
      * the recompute, when the key does change, runs OFF THE DRAWING THREAD — the frame
        that asked draws the previous answer and the new one lands a frame or two later;
      * the `sb inspect` fork happens once per agent per `_REPORTS_RECHECK` — WHATEVER
        that lookup found, including nothing at all. An agent writing its report moves
        the mtime every couple of seconds, and a highlight moving between tabs asks about
        a different agent every time it lands; neither may turn into a fork per frame, so
        the age of the lookup is what decides, never what it happened to return.

    A transcript that grows is the point: the hint flips on by itself the moment the
    agent names a file, without anything polling for it.
    """

    def __init__(self):
        # agent -> (cwd, transcript, when it was looked up). A miss is REMEMBERED, with
        # its timestamp, so an agent that has no worktree or no transcript yet is asked
        # about on the same schedule as one that does rather than on every frame.
        self._where: dict = {}
        # ((agent, mtime), files, has_worktree) — published as ONE tuple, and read as
        # one. Two assignments with an `os.stat` between them is long enough for a frame
        # to read the new agent's files under the old agent's name, and the hint would
        # then be showing A the number of files B wrote.
        #
        # `has_worktree` rides INSIDE that tuple rather than being read off `_where`,
        # which is where a drawing thread would naturally go looking for it. `_where` is
        # written by `_recompute` before `_answer`, so a read of one beside the other
        # crosses exactly the seam this tuple exists to close — and `_where` has no
        # `name` guard and no entry at all until the first recompute lands, so the
        # worktree-only hint, the one case with no files to fall back on, would be blank
        # for the first frames after every move of the highlight.
        self._answer = None
        self._at = 0.0                # when the last recompute finished
        self._busy = False

    def tick(self, name: Optional[str]):
        """What `oo`/`ww` would open for `name` — (files, has_worktree). Never blocks.

        Returned as one pair, and threaded on as one `openable` value: a second
        parameter beside it would have to be added to `draw`, `frame` and both
        renderers' `layout`, and the cost of missing one of those is not a crash but
        the two renderers quietly promising different hints.
        """
        if not name:
            return [], False
        located = self._where.get(name)
        transcript = located[1] if located else None
        key = (name, _mtime(transcript))
        answer = self._answer
        due = time.monotonic() - self._at >= _REPORTS_RECHECK
        if not self._busy and (due or answer is None or key != answer[0]):
            self._busy = True
            try:
                threading.Thread(target=self._recompute, args=(name,),
                                 daemon=True).start()
            except RuntimeError:
                # Thread exhaustion. The hint is the last thing on this board that may
                # take the draw loop down, and a `_busy` left true would wedge it.
                self._busy = False
        return (answer[1], answer[2]) if answer and answer[0][0] == name else ([], False)

    def _recompute(self, name: str) -> None:
        try:
            located = self._where.get(name)
            # THE FORK, and the whole reason for the cache. Its age is the only thing
            # that decides — a miss is cached exactly like a hit, or an agent with no
            # transcript would re-fork every time the highlight came back to it.
            if located is None or time.monotonic() - located[2] >= _REPORTS_RECHECK:
                found = locate(name) or (None, None)
                located = (found[0], found[1], time.monotonic())
                self._where[name] = located
            cwd, transcript = located[0], located[1]
            files = files_for(cwd, transcript)
            self._answer = ((name, _mtime(transcript)), files, bool(cwd))
        except BaseException:                       # noqa: BLE001 — a hint may not be
            self._answer = ((name, None), [], False)    # able to take the board with it
        finally:
            self._at = time.monotonic()
            self._busy = False


def _mtime(path) -> Optional[float]:
    """The one filesystem call the drawing thread makes per frame.

    Its argument came out of another process's JSON, so the type is not ours to assume:
    a `TypeError` here would be a crash on the hot path, every frame.
    """
    if not path or not isinstance(path, str):
        return None
    try:
        return os.stat(path).st_mtime
    except (OSError, ValueError):
        return None


def locate(name: str):
    """An agent's worktree and transcript. -> (cwd, transcript or None), or None.

    The one subprocess on this path, and the reason everything above caches it: the
    board may not read the store (see `open_report_files`), so this is the only way to
    turn a highlighted row into a directory, and it costs a fork.

    `cwd` comes back ABSOLUTE, for `report_files`' reason: an editor argument that
    starts with a dash is an option, not a path.
    """
    detail = _inspect(name)
    if detail is None:
        return None
    cwd = detail.get("cwd")
    return (os.path.abspath(cwd) if cwd else None), detail.get("transcript")


def files_for(cwd: Optional[str], transcript: Optional[str]) -> list[str]:
    """What a double-`o` would open. ONE definition, for the hint and the key alike.

    The hint on screen promises exactly what the keypress does because both come
    through here: two answers to "which files" would drift the first time either side
    was tuned, and the hint would then be advertising files that do not open.
    """
    if not cwd:
        return []
    return report_files(last_assistant_texts(Path(transcript)) if transcript else [],
                        cwd)


# How long `sb cleanup` gets. Its own herdr calls are each bounded by
# `timeouts.subprocess`, and it makes several of them and then deletes a worktree, so the
# flat one-call ceiling would fire on a perfectly healthy teardown. Something has to
# bound it — the slot it holds is the one `oo` and `ww` share, and a wedged `sb` would
# hold that for the life of the board — so it gets a multiple of the same knob rather
# than a number of its own.
_CLEANUP_TIMEOUT = _SUBPROCESS_TIMEOUT * 6


def cleanup_agent(name: Optional[str], follow: Optional[str] = None) -> str:
    """Four `c`s: `sb cleanup <name>`, with a board still on screen afterwards.

    Plain `sb cleanup <name>`, exactly what a human types: no `--force` ever from the
    board, no scoping flags, no separate "is it finished?" question first. Cleanup's own
    gates decide, and a refusal is reported in cleanup's own words.

    THE FOCUS GOES FIRST, which is the opposite of how this reads and the whole substance
    of it. Cleanup closes the agent's pane AND the board pane beside it — this pane, the
    one this code is running in. Closing it hangs up our terminal, so a focus sequenced
    after the cleanup is a focus by a process that is being killed while it waits, and
    the human is left on whatever pane herdr happens to raise, with no board anywhere:
    exactly the outcome the focus exists to prevent. Focused first, the human is already
    looking at another agent's board before anything can be closed, and the end state on
    success is identical.

    ON A REFUSAL THAT LEAVES THEM WHERE THEY WERE: nothing was closed, so this pane is
    still alive, and the focus is taken back before the reason goes to the status bar. A
    refusal changes nothing, and the pane the human is looking at is part of nothing.
    The visible cost of the ordering is that one flick away and back.

    `start_new_session` for the same reason the order is what it is: the pane's death
    sends SIGHUP to its foreground process group, and a cleanup killed halfway through
    has closed panes and left the worktree behind. Out of that group it runs to the end
    whatever becomes of this board.

    Returns a line for the status bar and never raises — a keypress may not take the
    board down.
    """
    if not name:
        return "press c on a highlighted agent"
    sb = _sb()
    if not sb:
        return "sb not on PATH"
    # `focus` answers in a LINE and not a flag, and the arrow is the shape of one that
    # happened. A focus that did not happen — herdr missing, the pane gone — does not
    # stop the cleanup, which is what the human asked for; it only means there is no
    # board to claim they are now looking at, and nothing to put back afterwards.
    moved = focus(follow).startswith("→") if follow else False
    try:
        p = subprocess.run([sb, "cleanup", name, "--json"], capture_output=True,
                           text=True, timeout=_CLEANUP_TIMEOUT, start_new_session=True)
    except subprocess.TimeoutExpired:
        return _cleanup_kept(name, moved, f"{name}: cleanup timed out")
    except (OSError, subprocess.SubprocessError) as e:
        return _cleanup_kept(name, moved,
                             f"{name}: cleanup failed: {status_mod.clip(str(e), 40)}")
    closed, why = _cleanup_said(p, name)
    if not closed:
        return _cleanup_kept(name, moved, f"{name}: {why}")
    if moved:
        return f"→ cleaned up {name} · now on {follow}"
    return (f"→ cleaned up {name} — could not focus {follow}" if follow
            else f"→ cleaned up {name} — no other agent to focus")


def _cleanup_kept(name: str, moved: bool, msg: str) -> str:
    """A cleanup that did not happen: put the human back, and say why. -> the line."""
    if moved:
        focus(name)
    return msg


def _cleanup_said(p, name: str):
    """-> (was `name` closed?, cleanup's own reason it was not).

    `--json` and not the human text, for one reason: A REFUSAL EXITS 0. "closed:
    (nothing)" with "refused w1: still working" under it is a successful run of the
    command and a no to the question, and telling those two apart off the text means
    matching a sentence this module does not own. The JSON says both outright — `closed`
    is a list of names, `refused` a list of `{name, reason}`. Nothing else about the call
    changes: same command, same gates, same worktree deletion.

    A non-zero exit is `sb` itself failing rather than cleanup declining, and it comes
    with no JSON at all — an agent the store has never heard of exits 1 saying "sb: not
    yours to clean up, or no such agent: ghost", which is a board row that has gone stale
    under the human. Its own first line is the only part worth the width
    (`_editor_said`'s reasoning), minus the `sb: ` it opens with: the status bar has
    already put the agent's name in front of it, and "w1: sb: no such agent" is one
    colon too many.
    """
    if p.returncode != 0:
        said = [ln.strip() for ln in ((p.stderr or "") + "\n" + (p.stdout or "")
                                      ).splitlines() if ln.strip()]
        first = said[0] if said else "cleanup failed"
        return False, status_mod.clip(first[4:] if first.startswith("sb: ") else first, 50)
    try:
        d = json.loads(p.stdout)
    except (json.JSONDecodeError, TypeError):
        d = None
    if not isinstance(d, dict):
        return False, "cleanup said nothing that could be read"
    if name in (d.get("closed") or []):
        return True, ""
    for r in (d.get("refused") or []):
        if isinstance(r, dict) and r.get("name") == name and r.get("reason"):
            return False, status_mod.clip(str(r["reason"]), 50)
    return False, "cleanup closed nothing and said no reason"


# The three actions, by the key run that fires them: the noun a refusal needs to tell one
# from the other, the verb it is doing, and what runs. `cccc`'s noun is EMPTY because what
# it acts on is the agent itself and not something of the agent's — "still cleaning up A's
# cleanup" is a sentence about nothing where "still cleaning up A" is the fact.
_ACTIONS = {"oo": ("files", "opening", lambda name, follow: open_report_files(name)),
            "ww": ("worktree", "opening", lambda name, follow: open_worktree(name)),
            "cccc": ("", "cleaning up", lambda name, follow: cleanup_agent(name, follow))}


def _of(who: str, noun: str) -> str:
    """"A's files", or just "A" for an action whose object is the agent. See `_ACTIONS`."""
    return f"{who}'s {noun}" if noun else who


def open_tick(name: Optional[str], note: list, running, action: str = "oo",
              follow: Optional[str] = None):
    """Start a keypress action off the drawing thread. -> (what is running, a line).

    `running` is the `(thread, agent name, action)` this returned last, or None.
    `follow` is what `cccc` focuses afterwards, worked out by the caller from the rows
    it is drawing (`next_focus`); the editor actions have no use for it.

    ONE ACTION AT A TIME, and `oo`, `ww` and `cccc` share the slot rather than having one
    each. Leaning on `o` re-fires once per read; without this the bursts would pile up
    behind each other and every one of them would open the same tabs again. Sharing is
    also what two independent mailboxes would have cost: `drain` pops EVERY non-empty box
    and keeps the last line, which is sound only while exactly one keypress answer can be
    waiting, and two boxes would silently destroy one of two answers that landed in the
    same pass. Sharing also puts `oo` behind `ww` when both are asked for at once — the
    ordering the files want, since a worktree window that exists is the one containment
    sends them to. A cleanup asked for while an open is running is DROPPED like any other
    second action, which is the right answer for it too: four presses that arrive during
    an `oo` are four presses the human can spend again.

    What it does NOT fix: `cursor <cwd>` returns when the CLI hands off, not when the
    window is up, so a cold-start `ww` followed straight away by `oo` can still have
    the files arrive before there is a window to contain them. Press `ww`, wait for the
    window, then `oo`.

    A refusal NAMES BOTH AGENTS, because the request is dropped rather than queued and
    the board must not imply otherwise: asking for B while A is still opening leaves A's
    line to arrive afterwards, and a bare "still opening…" followed by "→ A: opened 3
    file(s)" reads, to somebody who just asked for B, like B. When the two are different
    actions it names what each one is opening as well, since "still opening A — A not
    started" is otherwise a sentence about nothing.
    """
    noun, verb, _ = _ACTIONS[action]
    if not name:
        return running, f"press {action[0]} on a highlighted agent"
    if running is not None and running[0].is_alive():
        busy_noun, busy_verb, _ = _ACTIONS[running[2]]
        if running[2] == action:
            busy, asked = running[1], name
        else:
            busy = _of(running[1], busy_noun)
            asked = _of(name, noun)
        return running, (f"still {busy_verb} {busy} — {asked} not started, "
                         f"press {action} again")
    t = threading.Thread(target=_open, args=(name, note, action, follow), daemon=True)
    try:
        t.start()
    except RuntimeError as e:
        # Thread exhaustion. Vanishingly rare and `sweep_tick` has the same exposure,
        # but this one is on a keypress, and a keypress may not end the board.
        return running, f"{name}: could not start: {status_mod.clip(str(e), 40)}"
    return (t, name, action), f"{verb} {name}…"


def drain(msg: str, *boxes: list):
    """Take one line from each worker mailbox. -> (the line to show, anything taken?).

    Oldest first within a box, so two lines that arrived together are shown in the order
    they happened; and LAST BOX WINS across boxes, which is why the caller passes the
    open's mailbox last — a sweep landing in the same pass must not swallow the answer to
    a key somebody just pressed.
    """
    drained = False
    for box in boxes:
        if box:
            msg = box.pop(0)
            drained = True
    return msg, drained


def _open(name: Optional[str], note: list, action: str = "oo",
          follow: Optional[str] = None) -> None:
    """The action itself, off the drawing thread. Never raises into it."""
    try:
        note.append(_ACTIONS[action][2](name, follow))
    except BaseException as e:                  # noqa: BLE001 — a dead thread that says
        note.append(f"{name}: {action} failed: {e}")    # nothing is the one outcome worth
                                                # ruling out; every action catches its own.
                                                # THE KEY RUN names it, not a verb: "open
                                                # failed" is a lie over a cleanup thread


# How far back a transcript is read. One JSONL record is one content block, not one
# turn, so the last few things an agent SAID can sit a long run of tool calls back.
_TRANSCRIPT_TAIL = 400


def last_assistant_texts(path: Path, n: int = 3) -> list[str]:
    """The agent's last `n` assistant TEXT blocks, oldest first.

    `output.read_transcript` renders the same file and is deliberately not used: it
    flattens tool calls and their results in too, so a caller scanning it for paths
    would be scanning everything the agent READ as well as what it said — and it lives
    in a module that imports the store, which this one may not (see `open_report_files`).
    Only the `text` parts, which is the prose a human would have seen on screen.

    Two record shapes, told apart per record exactly as `read_transcript` tells them
    apart: Claude Code's `{"type": "assistant", "message": {...}}` and codex's rollout
    envelope. Written out here rather than imported, for the module boundary above. A
    reader that knew only the first found nothing at all in a codex agent's report, so
    the board's double-`o` silently opened no files for every codex agent.
    """
    try:
        with path.open(errors="replace") as fh:
            tail = deque(fh, maxlen=_TRANSCRIPT_TAIL)
    except OSError:
        return []
    out: list[str] = []
    for line in reversed(tail):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue          # a torn last line on a live session, not a failure
        if not isinstance(rec, dict):
            continue
        texts = (_codex_assistant_texts(rec) if rec.get("type") == "event_msg"
                 else _claude_assistant_texts(rec))
        if not texts:
            continue          # a user turn, a meta record, a thinking-only one
        out.append("\n".join(texts))
        if len(out) >= n:
            break
    return list(reversed(out))


def _claude_assistant_texts(rec: dict) -> list[str]:
    if rec.get("type") != "assistant":
        return []             # user turns, and the meta records with no role at all
    message = rec.get("message")
    # isinstance, like every other field here: this file is not one switchboard
    # writes, and a `message` that is a string raises where `.get` is assumed.
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [part["text"] for part in content
            if isinstance(part, dict) and part.get("type") == "text"
            and isinstance(part.get("text"), str) and part["text"].strip()]


def _codex_assistant_texts(rec: dict) -> list[str]:
    """The assistant prose of one codex rollout record.

    Read off `event_msg` only — the TUI's own item stream, which is what a person
    watching the pane saw. Codex writes each turn twice, and the other half
    (`response_item`) would double every line. `agent_message` is `codex exec`'s shape and
    `item_completed`/`AgentMessage` the TUI's; switchboard only spawns the TUI, but a
    rollout is a rollout and a reader that answers for one of them silently shows nothing.
    """
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return []
    if payload.get("type") == "agent_message":
        text = payload.get("message")
        return [text] if isinstance(text, str) and text.strip() else []
    if payload.get("type") != "item_completed":
        return []
    item = payload.get("item")
    if not isinstance(item, dict) or item.get("type") != "AgentMessage":
        return []
    content = item.get("content")
    if isinstance(content, str):
        return [content] if content.strip() else []
    if not isinstance(content, list):
        return []
    # `text`/`Text` in the item stream, `output_text` in the raw model items — the same
    # four part names `codex.content_text` reads, and matched case-insensitively for
    # the same reason: the TUI capitalises where the model items do not.
    return [str(p["text"]) for p in content
            if isinstance(p, dict)
            and str(p.get("type", "")).lower() in ("text", "input_text", "output_text")
            and isinstance(p.get("text"), str) and p["text"].strip()]


def _sb() -> Optional[str]:
    """THIS build's `sb`, or whatever is on PATH, or None if there is neither.

    For `collector.doorbell_sb`'s reason — the `sb` symlink points at the main checkout,
    so a board running a branch would otherwise ask a different build. Its lines are
    copied from there rather than imported: `collector` reaches the store, and a renderer
    may not name a module that does.
    """
    own = Path(__file__).resolve().parent.parent / "bin" / "sb"
    return str(own) if os.access(own, os.X_OK) else shutil.which("sb")


def _inspect(name: str) -> Optional[dict]:
    """One agent's row, as JSON, from a separate process. None if anything went wrong."""
    sb = _sb()
    if not sb:
        return None
    try:
        p = subprocess.run([sb, "inspect", name, "--json", "-n", "1", "--events", "1"],
                           capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


# `cursor` and `code` are not always the editor CLI, and on WSL they are usually not.
# Both names go through a shim — `resources/app/bin/cursor`, the remote-WSL extension,
# then `~/.cursor-server/.../remote-cli/cursor` — whose last step `exec`s the Cursor
# AGENT CLI whenever `~/.local/bin/cursor-agent` exists, which it installs itself the
# first time it looks. That is a different program: it reads `<folder>` as a PROMPT,
# opens no window, and exits asking to be logged in. `<folder>` is the whole of what
# `ww` runs, so on such a machine `ww` opened nothing, ever. This is the shim's own
# way back to the editor CLI, and it is a name no other editor reads, so it costs
# nothing to send always.
_EDITOR_ENV = {"CURSOR_CLI_BLOCK_CURSOR_AGENT": "true"}


def _editor(*args: str) -> None:
    """Run the editor CLI. Raises `CalledProcessError` when it RAN and refused.

    `check=True` is the whole of what this board was blind to. Without it every
    non-zero exit — an unrecognised flag, a binary that wants a login, the wrong
    program behind the name — came back indistinguishable from an open that worked,
    and both actions said "opened" over a desktop where nothing had happened. A
    keypress that lies is worse than one that fails.
    """
    subprocess.run([_EDITOR, *args], capture_output=True, text=True, check=True,
                   timeout=_SUBPROCESS_TIMEOUT, env={**os.environ, **_EDITOR_ENV})


def _editor_said(e: subprocess.CalledProcessError) -> str:
    """The editor's own words for a refusal, for the status bar.

    Its first line of output rather than `str(e)`: "Command '[...]' returned non-zero
    exit status 1" spends the whole line on the argv and never says why, and why is
    the only part worth a line — "unknown option '-r'" and "Authentication required"
    are each one glance from the fix.
    """
    said = [ln.strip() for ln
            in ((e.stderr or "") + "\n" + (e.stdout or "")).splitlines() if ln.strip()]
    return (f"{_EDITOR}: {status_mod.clip(said[0], 60)}" if said
            else f"{_EDITOR} exited {e.returncode}")


def _board_command() -> str:
    """The line the board pane runs — with this checkout on `PYTHONPATH`.

    `-m` puts the pane's own cwd at the front of `sys.path`, and in a switchboard
    worktree that was the whole of the import: the pane stands in a checkout that HAS
    a `switchboard/` package. In ANY OTHER REPO it does not, and the pane's python
    exited on `No module named 'switchboard'` before it could draw a frame. It is an
    `exec`, so the shell went with it and the split closed again — every agent spawned
    in a non-switchboard repo therefore came up with no board and nothing on screen
    saying why. Reproduced by running this command in a fresh `git init` directory.

    Same fix, same reason and same shape as `panel.ensure_collector`'s: `switchboard`
    is not installed anywhere — `bin/sb` puts the checkout on `sys.path` itself — so a
    `-m` child with a different cwd cannot import it.

    THIS checkout, not the main one. The board beside an agent should be drawn by the
    build whose `sb` opened it, the same rule the pane's PATH pin follows
    (`Broker._ready_pane`); `panel.canonical_checkout` deliberately answers otherwise
    for the COLLECTOR, and that difference is deliberate too — one fleet-wide answer
    for the numbers, this pane's own code for this pane's frame.

    cwd still wins over `PYTHONPATH` under `-m`, so a pane standing in a switchboard
    worktree draws that worktree's copy exactly as it did before this existed.

    Quoted, because both paths come from the environment and this text reaches a
    shell. Nothing agent-authored is in it — see `Herdr.prompt_pane`, which takes
    fixed commands only.
    """
    own = Path(__file__).resolve().parent.parent
    existing = os.environ.get("PYTHONPATH")
    pythonpath = f"{own}{os.pathsep}{existing}" if existing else str(own)
    return (f"exec env PYTHONPATH={shlex.quote(pythonpath)} "
            f"{shlex.quote(sys.executable)} -m switchboard.board")


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
    human-only gate on the way in. `_board_command` is what makes that line
    importable from a pane standing anywhere.
    """
    from .herdr import HerdrError

    try:
        pane = h.split_pane(pane_id, direction="right", ratio=1 - BOARD_SHARE, cwd=cwd)
    except (HerdrError, OSError):
        return None
    try:
        h.prompt_pane(pane, _board_command())
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
           stats: Optional[dict] = None, openable=None, section_top: int = 0,
           cursor: Optional[str] = None, pan: int = 0
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
                            stats=stats, openable=openable, section_top=section_top,
                            cursor=cursor, pan=pan)
    if rows is not None:
        return rows
    return layout(snap, top=top, height=height, width=width, msg=msg,
                  note_text=note_text, show_archived=show_archived, here=here,
                  stats=stats, openable=openable, section_top=section_top,
                  cursor=cursor, pan=pan)


def draw(snap, top: int, msg: str, note_text: str, show_archived: bool,
         here: Optional[str] = None, stats: Optional[dict] = None,
         openable=None, section_top: int = 0, cursor: Optional[str] = None,
         pan: int = 0) -> list:
    height, width = _size()
    rows = _frame(snap, top=top, height=height, width=width, msg=msg,
                  note_text=note_text, show_archived=show_archived, here=here,
                  stats=stats, openable=openable, section_top=section_top,
                  cursor=cursor, pan=pan)
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
    # TWO scroll offsets, because there are two panels: the tree, and whatever a plugin
    # draws under it. A wheel scrolls the one it is over (`SECTION_ZONE`), so a long list
    # of plans is read by scrolling the plans rather than by the plans eating the tree.
    top, section_top, msg, buf = 0, 0, "", ""
    # THE ARROW KEYS. `cursor` is the agent UP and DOWN are over and `cursor_at` is when
    # they last moved it, on the monotonic clock: the mark stands for `CURSOR_HOLD` and
    # then the board goes back to showing one highlight. `pan` is how far LEFT and RIGHT
    # have moved a plugin's text, in columns. All three are pane-local and none is
    # persisted, for the reason `show_archived` is not: a panel is cheap and every pane
    # has its own.
    cursor, cursor_at, pan = None, 0.0, 0

    def scroll(value: int, by: int, section: bool = False) -> int:
        """One panel's offset, moved and BOUNDED by what there is to scroll to.

        The renderers clamp what they DRAW, and that was enough while a wheel was the only
        thing that moved an offset — a board scrolled far past its end looks exactly like
        one scrolled to it. It is not enough now: a held-down arrow at the bottom of the
        tree would run the offset up into the hundreds, and then the way back is however
        many presses it took to get there, with the screen still as it was. So down is
        bounded here and up costs nothing to bound.

        The bound is loose on purpose — the last ROW at the top of the pane, rather than
        the last screenful, which is what the renderers work out and neither of them is
        asked for here. It is a leash, not a layout.
        """
        if by <= 0:
            return max(0, value + by)
        drawn = status_mod.board_rows(snap.agents, show_archived=show_archived)
        room = (sum(2 + len(lines) for _, lines in section_extras(drawn)) if section
                else len(drawn))
        return min(value + by, max(0, room - 1))
    # When `o` and `w` were last pressed on their own, on the monotonic clock. One float
    # each is the whole double-press state: a single `o` is not a command, so nothing
    # happens until a second one lands inside `DOUBLE_PRESS` — see `double_press_run`,
    # which is where a pair arriving in ONE read is handled. The two floats are separate
    # and the counting is per character, so `owo` is a double-`o` and not a cross-key
    # anything. `open_note` is the worker thread's one-slot mailbox, `sweep_note`'s shape
    # and for its reason: the open shells out, and this pane may not be written to by
    # anything but the frame loop. ONE mailbox and one `opening` slot for both keys —
    # see `open_tick` for why two would break `drain`.
    last_o, last_w, open_note, opening = 0.0, 0.0, [], None
    # `c` is the four-press one, so it carries a COUNT beside its float — see
    # `multi_press`, which is where the difference is. Its own pair of variables and
    # nobody else's, for the reason `o` and `w` have one each: counting is per character,
    # so no key can fire off another's presses.
    last_c, presses_c = 0.0, 0
    show_archived = status_mod.SHOW_ARCHIVED
    # Which agent shares this pane's tab — the row this board highlights. Built here and
    # not at import, so the environment it reads is this process's own, and asked again per
    # frame because the answer is a NAME resolved against the rows being drawn.
    where = Locator()
    # Whether the highlighted agent has anything for `oo` to open. Asked every frame and
    # answered from cache — the fork and the transcript read are its own, off this thread.
    reports = Reports()
    # The slot this board started in, so the first sweep is at the next boundary and never
    # at startup — see `sweep_tick`. `sweep_note` is the worker thread's one-slot mailbox.
    armed, sweep_note = sweep_mod.slot_of(time.time()), []
    try:
        tty.setraw(fd)
        sys.stdout.write(MOUSE_ON + HIDE_CURSOR)
        sys.stdout.flush()

        snap, note_text, stats = refresh(sup)
        where.tick()
        here = where.name(snap.agents)
        def paint():
            """This board, as it now stands. THE ONLY PLACE THE FRAME IS DRAWN.

            A closure over the loop's own variables rather than nine arguments repeated
            at three call sites: the arrow keys added a third, and a call site that
            forgets one of them is a board that draws yesterday's cursor.
            """
            return draw(snap, top, msg, note_text, show_archived, here, stats,
                        openable=reports.tick(here), section_top=section_top,
                        cursor=cursor, pan=pan)

        rows = paint()
        last = time.time()

        while True:
            # Both worker mailboxes, drained BEFORE this pass reads the keyboard and in
            # this order, which is what keeps the status line honest. Oldest first, so
            # two lines that arrived together are shown in the order they happened. The
            # open drains last of the two, so a sweep landing in the same pass cannot
            # swallow the answer to a key somebody just pressed. And both drain ahead of
            # the keypress handler, so a result that arrived since the last pass cannot
            # overwrite the "opening…" that this pass is about to set.
            msg, drained = drain(msg, sweep_note, open_note)
            dirty[0] = dirty[0] or drained
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
                        for key in arrows(ev):
                            dirty[0] = True
                            if key in ("left", "right"):
                                # A plugin's text, moved under a fixed heading. Never
                                # below zero: there is nothing to the left of the margin.
                                pan = max(0, pan + PAN_STEP * (1 if key == "right"
                                                               else -1))
                                continue
                            step = 1 if key == "down" else -1
                            moved = step_cursor(
                                [a.name for a in status_mod.board_rows(
                                    snap.agents, show_archived=show_archived)],
                                cursor, step)
                            cursor, cursor_at = moved, time.monotonic()
                            # The cursor walked off the window: bring the window with it,
                            # in the direction the key went, UNTIL THE ROW IS ON SCREEN.
                            # Not one row per press: a window that has something above it
                            # and something below it spends two of its lines saying so, so
                            # a fixed step of one never catches a cursor that has just
                            # crossed the edge — it trails it forever, one row down.
                            #
                            # REDRAWN INSIDE THE LOOP, and that is the part that is not
                            # optional. One terminal read carries a whole burst of a
                            # held-down key, so without this every press in the burst
                            # would ask the same stale frame whether the row it landed on
                            # is drawn, and the walk would outrun the window.
                            #
                            # Terminates: `top` strictly changes every turn and `scroll`
                            # bounds it, and a `top` that will not move is the other way
                            # out. Costs a frame per turn, which is what the board draws
                            # twice a second anyway.
                            while moved is not None and moved not in drawn_names(rows):
                                was = top
                                top = scroll(top, step)
                                if top == was:
                                    break
                                rows = paint()
                        if entered(ev) and cursor:
                            # EXACTLY WHAT A CLICK ON THAT ROW DOES, and it says so with
                            # the same status line. The cursor is spent by it: the offer
                            # was taken, and a mark left standing over a pane the human
                            # is now sitting in says nothing.
                            msg, cursor = focus(cursor), None
                            dirty[0] = True
                        if "r" in ev["raw"]:
                            last = 0.0
                        if "a" in ev["raw"]:
                            show_archived = not show_archived
                            dirty[0] = True
                        # `w` BEFORE `o`, and the order is load-bearing: one read can
                        # carry `wwoo`, both branches fire in this same iteration, and
                        # both write `msg` — so the branch that runs LAST owns the status
                        # line. `oo`'s answer is the more informative of the two.
                        if "w" in ev["raw"]:
                            fire, last_w = double_press_run(
                                last_w, ev["raw"].count("w"), time.monotonic())
                            if fire:
                                opening, msg = open_tick(
                                    where.name(snap.agents), open_note, opening, "ww")
                                dirty[0] = True
                        if "o" in ev["raw"]:
                            fire, last_o = double_press_run(
                                last_o, ev["raw"].count("o"), time.monotonic())
                            if fire:
                                opening, msg = open_tick(
                                    where.name(snap.agents), open_note, opening, "oo")
                                dirty[0] = True
                        # LAST of the three, so that when one read carries `c`s beside
                        # anything else the cleanup owns the status line: it is the only
                        # one of them whose answer is about something that was destroyed.
                        if "c" in ev["raw"]:
                            fire, last_c, presses_c = multi_press_run(
                                last_c, presses_c, ev["raw"].count("c"),
                                time.monotonic(), CLEANUP_PRESSES)
                            if fire:
                                # THE HIGHLIGHTED agent, exactly as `oo` and `ww` take it
                                # — the one sharing this pane's tab, not the arrow-key
                                # cursor. And who to focus afterwards is decided HERE,
                                # off the rows this board is drawing: the worker thread
                                # has no snapshot, and by the time it needs the answer
                                # the agent it is about is gone.
                                who = where.name(snap.agents)
                                opening, msg = open_tick(
                                    who, open_note, opening, "cccc",
                                    follow=next_focus(
                                        status_mod.board_rows(
                                            snap.agents,
                                            show_archived=show_archived), who)
                                    if who else None)
                                dirty[0] = True
                        continue
                    step = wheel(ev)
                    if step:
                        # WHICH PANEL THE POINTER IS OVER, asked of the frame that is on
                        # screen rather than computed from a row number: the owner was
                        # recorded as the line was drawn, which is the same answer a click
                        # gets and cannot drift from what the human is looking at.
                        if agent_at(rows, ev["row"]) is SECTION_ZONE:
                            section_top = scroll(section_top, step * 3, section=True)
                        else:
                            top = scroll(top, step * 3)
                        dirty[0] = True
                        continue
                    if is_left_click(ev):
                        a = agent_at(rows, ev["row"])
                        # A click still focuses, and now that is ALL it does: the row
                        # background stopped meaning "the one you just touched" and
                        # started meaning "the one beside you", and one board cannot
                        # have two meanings for one mark. What a click did that was
                        # worth keeping — jumping to the pane — is here, and what it
                        # said on screen is said by the status line. Every row that
                        # carries an owner is an agent now (`status.board_rows`), so
                        # there is nothing else a click can land on but chrome.
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
            # The cursor is a standing offer with a clock on it, so it is read where the
            # frame is decided rather than where a key is pressed: nothing else in this
            # loop knows the time has passed. Cheap, and the refresh tick below marks the
            # board dirty twice a second, so the mark goes out on its own within a frame
            # of expiring.
            if cursor is not None and time.monotonic() - cursor_at >= CURSOR_HOLD:
                cursor, dirty[0] = None, True

            if dirty[0]:
                # Asked HERE, on the frame being drawn, rather than when the pane list came
                # back: the cached answer is a set of pane IDS, and turning those into the
                # name of a row is done against the rows this frame actually has. So an
                # agent that is restored, renamed away, or dropped from the snapshot stops
                # or starts being highlighted on the next frame, with no subprocess in it.
                here = where.name(snap.agents)
                rows = paint()
                dirty[0] = False
    except KeyboardInterrupt:
        pass
    finally:
        restore()
    return 0


if __name__ == "__main__":
    sys.exit(main())
