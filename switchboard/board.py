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
every sb-made view is split with the board (DESIGN-TRUTH.md's "`--no-board`").
"""

from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import sys
import termios
import time
import tty
from typing import Optional

from . import config
from . import panel
from . import status as status_mod

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
CHROME = config.setting("display.board_chrome")       # header, blank, blank, status —
                                                     # lines not available to agents
_SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

# How much of the width the board takes when it opens beside an agent. A third:
# the tree is a glance, and the pane a human actually reads is the agent's own
# session. See `open_beside`, which inverts this into herdr's `--ratio`.
BOARD_SHARE = 0.34

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
    if a.stalled:
        return "◌"
    if a.finished:
        return "○"
    if a.alive is None:
        return "?"
    return "●"


_GLYPH_COLOR = {"✗": RED, "◐": YELLOW, "◌": YELLOW, "○": DIM, "?": DIM, "●": GREEN}


def wants_you(a) -> bool:
    """Whether this row is asking for something, as opposed to just reporting.

    Broader than `AgentStatus.needs_human`: a gone or stalled agent needs a
    person too, it just does not know it.
    """
    return bool(a.needs_human or a.gone or a.stalled)


def note(a) -> str:
    """The one thing worth saying about this agent, right of its state.

    Strictly ranked, and only ever one: a board that shows an agent's task and
    its mail and its summary is a board nobody can scan. Whatever is most
    actionable wins.
    """
    if a.gone:
        return "GONE — herdr has no such agent"
    if a.at_prompt:
        return "AT PROMPT — waiting on you"
    if a.blocked:
        return f"BLOCKED — {a.blocked_why or 'no reason recorded'}"
    if a.stalled:
        return f"STALLED — idle {status_mod.fmt_age(a.idle)}"
    if a.unread:
        return f"{a.unread} unread"
    if a.finished and a.summary:
        return f"done: {a.summary}"
    if a.task:
        return a.task
    return ""


def _note_color(a) -> str:
    if a.gone:
        return RED
    if a.at_prompt or a.blocked or a.stalled or a.unread:
        return YELLOW
    return DIM


# ---------------------------------------------------------------------------
# Pure: layout
# ---------------------------------------------------------------------------


def _is_group(row) -> bool:
    """Is this display row a collapsed group rather than an agent?

    One predicate, used by everything that reads a row, so there is exactly one
    place that knows how the two are told apart. Everything downstream of
    `layout` receives whatever the row carries, and reading `.name` off a group
    is the failure `layout`'s closing comment is about.
    """
    return isinstance(row, status_mod.Collapsed)


def layout(snap, *, top: int, height: int, width: int, msg: str,
           note_text: str = "", show_archived: Optional[bool] = None
           ) -> list[tuple[str, Optional[object]]]:
    """Build the whole screen as (text, agent) pairs — one per line, in order.

    The agent a row belongs to is carried BY the row rather than recomputed from
    an index, so a click can never resolve to a different agent than the one the
    human is looking at. Everything downstream just indexes this list.

    `top` is the scroll offset in DISPLAY rows, not in agents. Those stopped
    being the same thing when collapse landed: `display_rows` replaces whole
    archived subtrees with one `Collapsed`, so a window taken over `snap.agents`
    would scroll past rows that are not drawn and the `+N more below` count would
    contradict the screen. Everything here — the slice, the clamp, the tail —
    counts what is actually on screen.

    Returns at most `height` lines.
    """
    rows: list[tuple[str, Optional[object]]] = []
    if show_archived is None:                       # `display.show_archived`, via status,
        show_archived = status_mod.SHOW_ARCHIVED    # so both readouts share one default
    agents = status_mod.display_rows(snap.agents, show_archived=show_archived)
    capacity = max(1, height - CHROME)
    top = max(0, min(top, max(0, len(agents) - capacity)))
    window = agents[top:top + capacity]

    head = _c("switchboard", BLUE) + _c("  ·  " + status_mod.summary_line(snap), DIM)
    rows.append((head, None))
    rows.append(("", None))

    if not agents:
        why = note_text or "nothing running — sb start"
        rows.append((_c(f"  ({why})", DIM), None))
    else:
        # Defaults, not `max(seq)`: a window can be nothing but collapsed rows —
        # which is the ORDINARY end-of-session state, every agent finished and
        # its pane closed — and there is then no agent to measure a name or a
        # state against. Empty-sequence `max` raises, and a panel that raises at
        # the end of every session is worse than one with a narrow column.
        w_name = max([0] + [len(("  " * a.depth) + a.name)
                            for a in window if not _is_group(a)])
        w_state = max([0] + [len(a.state) for a in window if not _is_group(a)])
        for a in window:
            if _is_group(a):
                # No glyph, no state, no note. It is not an agent and must not
                # read as one — `agent_at` hands this very object to the click
                # handler, which has to be able to tell them apart.
                rows.append((_c("   " + status_mod.collapsed_label(a), DIM), a))
                continue
            g = glyph(a)
            label = ("  " * a.depth) + a.name
            # Measured plain and coloured in parallel: only the glyph is coloured,
            # so the two stay the same visible width.
            left = f" {g} {label:<{w_name}}  {a.state:<{w_state}}  {status_mod.fmt_age(a.idle):>5}  "
            line = (f" {_c(g, _GLYPH_COLOR.get(g, ''))} {label:<{w_name}}  "
                    f"{a.state:<{w_state}}  {status_mod.fmt_age(a.idle):>5}  ")
            n = note(a)
            lead = "← " if wants_you(a) else "  "
            room = width - len(left) - len(lead)
            if n and room >= 6:
                line += _c(lead + status_mod.clip(n, room), _note_color(a))
            rows.append((line, a))

    while len(rows) < height - 2:
        rows.append(("", None))

    hidden = len(agents) - (top + len(window)) if agents else 0
    tail = f"+{hidden} more below" if hidden > 0 else ("scroll ↑" if top else "")
    if note_text and agents:
        tail = note_text
    rows.append((_c(tail, DIM), None))
    rows.append((_c("click a row to focus it · scroll to pan · a archived · q quits", DIM)
                 + ("   " + msg if msg else ""), None))

    # The one invariant this view rests on: no line may ever wrap. A wrapped line
    # pushes every row below it down by one, and the next click focuses the wrong
    # agent — silently, and looking exactly like a correct click.
    return [(_fit(text, width), a) for text, a in rows[:height]]


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


def _visible_len(s: str) -> int:
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _fit(text: str, width: int) -> str:
    """Guarantee a line occupies one terminal row.

    Slicing coloured text would cut an escape sequence in half, so an overlong
    line loses its colour rather than its correctness — this only happens in a
    pane too narrow to be pretty anyway.
    """
    if _visible_len(text) <= width:
        return text
    return re.sub(r"\033\[[0-9;]*m", "", text)[:width]


# ---------------------------------------------------------------------------
# Impure: the snapshot file, herdr, the terminal. NOT the store — see the module note.
# ---------------------------------------------------------------------------


def refresh(sup: panel.Supervisor):
    """-> (snapshot, note). One tick of a renderer. Never raises.

    Two things, and neither of them touches the store. Say a panel is still
    being looked at, starting a collector if none is up — which is how takeover
    works: the dead holder's flock is gone, so the next panel to tick replaces
    it. Then read the file.

    `note` is the panel's own condition, ranked in `panel.Reading.note`, and the
    staleness line is the reason it exists. A shared snapshot introduces exactly
    one new failure — a wedged collector leaving forty screens quietly agreeing
    on old data — so the age is printed the moment it is worth printing, and the
    board says "snapshot 40s old" instead of presenting it as now.
    """
    sup.tick()
    r = panel.read(sup.paths)
    return r.snap, r.note


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


def open_beside(h, pane_id: str, *, cwd: str, share: float = BOARD_SHARE) -> Optional[str]:
    """Split `pane_id` and run the board in the new pane. -> new pane id, or None.

    Called by `broker._open_board`, so every agent lands with the tree up beside
    it — `sb start`'s orchestrator and every `sb delegate` child alike.

    `share` is the BOARD's share of the width, which is the number a reader wants
    to reason about; herdr's `--ratio` is the *other* number — what the pane being
    split keeps — so it is inverted on the way out. The board is the small pane:
    the agent's own session is the thing being read, and the tree beside it is a
    glance.

    Returns None rather than raising on any herdr failure, and callers ignore the
    result: a spawn failing because a *view* would not open is a far worse bug
    than spawning without one.

    Launches `sys.executable -m switchboard.board` rather than `sb board`, so it
    does not depend on `sb` being on PATH in that pane, and cannot trip the
    human-only gate on the way in.
    """
    from .herdr import HerdrError

    try:
        pane = h.split_pane(pane_id, direction="right", ratio=1 - share, cwd=cwd)
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


def draw(snap, top: int, msg: str, note_text: str, show_archived: bool) -> list:
    height, width = _size()
    rows = layout(snap, top=top, height=height, width=width, msg=msg,
                  note_text=note_text, show_archived=show_archived)
    out = ["\033[H\033[2J"]
    out.append("\r\n".join(text for text, _ in rows))
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    return rows


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
    try:
        tty.setraw(fd)
        sys.stdout.write(MOUSE_ON + HIDE_CURSOR)
        sys.stdout.flush()

        snap, note_text = refresh(sup)
        rows = draw(snap, top, msg, note_text, show_archived)
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
                            msg = focus(a.name) if a else ""
                        dirty[0] = True

            if time.time() - last >= REFRESH:
                snap, note_text = refresh(sup)
                dirty[0] = True
                last = time.time()
            if dirty[0]:
                rows = draw(snap, top, msg, note_text, show_archived)
                dirty[0] = False
    except KeyboardInterrupt:
        pass
    finally:
        restore()
    return 0


if __name__ == "__main__":
    sys.exit(main())
