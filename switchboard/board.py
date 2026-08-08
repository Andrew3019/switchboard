"""The clickable board — a human's live view of the tree.

Three ways in, all the same screen: `sb start` opens one beside the orchestrator
it starts (`--no-board` declines), `sb board` opens one here, and
`python3 -m switchboard.board` is the plumbing both go through.

This is a HUMAN-ONLY surface and must stay one. `sb board` is hidden from
`--help` and refuses any caller that `whoami()` resolves to an agent, and the
board appears nowhere in defaults/protocol.md, which is where an agent actually
learns what `sb` can do. Everything here is read-only against the store, with
exactly one side effect — `herdr agent focus`, a human jumping to a pane.

Proved out by `scripts/05-mouse.py` and `scripts/06-board.py`: herdr forwards
SGR mouse events to a pane, and a decoded row maps back to an agent. Those two
stay as the record of what was proven; this is the version that is maintained.

`open_beside()` below was once removed as dead code, because it was written a
turn before anything called it. It is now called from `broker._top`, and that is
the only reason it belongs here — if that call ever goes away, this should go
with it. Auto-opening a board IS a decision about a human's screen, which is why
it is one `--no-board` can decline rather than one nobody gets a say in.
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
from . import status as status_mod

# 1000h = press/release reporting. 1006h = SGR encoding, which is the only one
# that survives past column 223 and the only one 05-mouse saw herdr emit.
MOUSE_ON = "\033[?1000h\033[?1006h"
MOUSE_OFF = "\033[?1006l\033[?1000l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

SGR = re.compile(r"\033\[<(\d+);(\d+);(\d+)([Mm])")

# Both `[display]` in defaults/settings.toml.
REFRESH = config.setting("display.board_refresh")   # how often the tree is re-collected
CHROME = config.setting("display.board_chrome")       # header, blank, blank, status —
                                                     # lines not available to agents
_SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

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


def layout(snap, *, top: int, height: int, width: int, msg: str,
           note_text: str = "") -> list[tuple[str, Optional[object]]]:
    """Build the whole screen as (text, agent) pairs — one per line, in order.

    The agent a row belongs to is carried BY the row rather than recomputed from
    an index, so a click can never resolve to a different agent than the one the
    human is looking at. Everything downstream just indexes this list.

    `top` is the scroll offset in agents. Returns at most `height` lines.
    """
    rows: list[tuple[str, Optional[object]]] = []
    agents = snap.agents
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
        w_name = max(len(("  " * a.depth) + a.name) for a in window)
        w_state = max(len(a.state) for a in window)
        for a in window:
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
    rows.append((_c("click a row to focus it · scroll to pan · q quits", DIM)
                 + ("   " + msg if msg else ""), None))

    # The one invariant this view rests on: no line may ever wrap. A wrapped line
    # pushes every row below it down by one, and the next click focuses the wrong
    # agent — silently, and looking exactly like a correct click.
    return [(_fit(text, width), a) for text, a in rows[:height]]


def agent_at(rows, row: int):
    """Screen row (1-based) -> the agent drawn there, or None."""
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
# Impure: the store, herdr, the terminal
# ---------------------------------------------------------------------------


def snapshot():
    """-> (snapshot, note). Never raises.

    A board that tracebacks into a raw terminal is worse than a board that says
    it cannot see anything, so every failure below becomes a line on screen.
    """
    from . import store
    from .herdr import Herdr

    try:
        db = store.connect()
    except Exception as e:                       # not a repo, unreadable db, ...
        return _empty(), f"store unavailable: {e}"
    try:
        snap = status_mod.collect(db, Herdr())
    except Exception as e:
        return _empty(), f"could not read the tree: {e}"
    finally:
        db.close()

    return snap, (f"herdr unreachable ({snap.herdr_error}) — "
                  f"alive and stalled are unknown" if snap.herdr_error else "")


def _empty():
    return status_mod.Snapshot(now=0, agents=[])


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


def open_beside(h, pane_id: str, *, cwd: str, ratio: float = 0.38) -> Optional[str]:
    """Split `pane_id` and run the board in the new pane. -> new pane id, or None.

    Called by `broker._top`, so `sb start` lands you on the orchestrator with the
    tree already up beside it.

    Returns None rather than raising on any herdr failure, and `_top` ignores the
    result: `sb start` failing because a *view* would not open is a far worse bug
    than starting without one.

    Launches `sys.executable -m switchboard.board` rather than `sb board`, so it
    does not depend on `sb` being on PATH in that pane, and cannot trip the
    human-only gate on the way in.
    """
    from .herdr import HerdrError

    try:
        pane = h.split_pane(pane_id, direction="right", ratio=ratio, cwd=cwd)
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


def draw(snap, top: int, msg: str, note_text: str) -> list:
    height, width = _size()
    rows = layout(snap, top=top, height=height, width=width, msg=msg,
                  note_text=note_text)
    out = ["\033[H\033[2J"]
    out.append("\r\n".join(text for text, _ in rows))
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    return rows


def main() -> int:
    if not sys.stdin.isatty():
        print("board: stdin is not a tty — run this in a pane.", file=sys.stderr)
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

    top, msg, buf = 0, "", ""
    try:
        tty.setraw(fd)
        sys.stdout.write(MOUSE_ON + HIDE_CURSOR)
        sys.stdout.flush()

        snap, note_text = snapshot()
        rows = draw(snap, top, msg, note_text)
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
                        continue
                    step = wheel(ev)
                    if step:
                        top = max(0, top + step * 3)
                        dirty[0] = True
                        continue
                    if is_left_click(ev):
                        a = agent_at(rows, ev["row"])
                        msg = focus(a.name) if a else ""
                        dirty[0] = True

            if time.time() - last >= REFRESH:
                snap, note_text = snapshot()
                dirty[0] = True
                last = time.time()
            if dirty[0]:
                rows = draw(snap, top, msg, note_text)
                dirty[0] = False
    except KeyboardInterrupt:
        pass
    finally:
        restore()
    return 0


if __name__ == "__main__":
    sys.exit(main())
