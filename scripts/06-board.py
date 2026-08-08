#!/usr/bin/env python3
"""06 — the minimal clickable agent tree.

Real agents from the real store, redrawn every ~2s. Click a row, herdr focuses
that agent. Human-only surface: no agent ever runs this, and it is never an `sb`
verb.

Terminal machinery is duplicated from 05 on purpose. These are probes, not a
library.

Run from the repo root:  python3 scripts/06-board.py
"""

import os
import re
import select
import signal
import subprocess
import sys
import termios
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MOUSE_ON = "\033[?1000h\033[?1006h"
MOUSE_OFF = "\033[?1006l\033[?1000l"
SGR = re.compile(r"\033\[<(\d+);(\d+);(\d+)([Mm])")

FIRST_AGENT_ROW = 3        # row 1 title, row 2 blank, agents from row 3 (1-based)
REFRESH = 2.0


def parse_sgr(buf: str):
    """Pure. -> (events, leftover). Same shape as 05."""
    events = []
    pos = 0
    for m in SGR.finditer(buf):
        if m.start() != pos:
            events.append({"button": None, "col": None, "row": None,
                           "press": None, "raw": buf[pos:m.start()]})
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
        if tail:
            events.append({"button": None, "col": None, "row": None,
                           "press": None, "raw": tail})
        return events, ""
    if cut > 0:
        events.append({"button": None, "col": None, "row": None,
                       "press": None, "raw": tail[:cut]})
    return events, tail[cut:]


def agent_at(agents, row, first=FIRST_AGENT_ROW):
    """Pure. Screen row (1-based) -> agent, or None if that row is not an agent.

    `Snapshot.agents` is documented as tree order, so index == line offset.
    """
    i = row - first
    if i < 0 or i >= len(agents):
        return None
    return agents[i]


def line_for(a):
    return f"{'  ' * a.depth}{a.name}  [{a.state}]"


def snapshot():
    """-> (agents, note). Never raises: an empty board with a reason beats a
    traceback into a raw terminal."""
    try:
        from switchboard import status, store
        from switchboard.herdr import Herdr
    except Exception as e:
        return [], f"import failed: {e}"
    try:
        db = store.connect()
    except Exception as e:
        return [], f"store unavailable: {e}"
    try:
        snap = status.collect(db, Herdr())
    except Exception as e:
        return [], f"collect failed: {e}"
    finally:
        db.close()
    note = f"herdr unavailable ({snap.herdr_error})" if snap.herdr_error else ""
    return snap.agents, note


def focus(name):
    """Simplest thing that works. Returns a one-line result for the status bar."""
    try:
        p = subprocess.run(["herdr", "agent", "focus", name],
                           capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return "herdr not found on PATH"
    except subprocess.TimeoutExpired:
        return f"focus {name}: timed out"
    if p.returncode != 0:
        return f"focus {name}: {(p.stderr or p.stdout or 'failed').strip()[:60]}"
    return f"focused {name}"


def draw(agents, note, msg):
    out = ["\033[H\033[2J"]                      # home + clear
    out.append("06-board — click a row to focus that agent, q to quit\r\n")
    out.append("\r\n")
    if not agents:
        out.append(f"  (no agents{': ' + note if note else ''})\r\n")
    else:
        for a in agents:
            out.append(line_for(a) + "\r\n")
    out.append("\r\n")
    if note and agents:
        out.append(f"! {note}\r\n")
    out.append(f"> {msg}\r\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def main():
    if not sys.stdin.isatty():
        print("06-board: stdin is not a tty — run this in a real pane.", file=sys.stderr)
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
            os.write(sys.stdout.fileno(), MOUSE_OFF.encode())
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    def bail(sig, _frame):
        restore()
        os.write(sys.stdout.fileno(), b"\r\n[06-board] terminal restored.\r\n")
        os._exit(0)

    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGTERM, bail)
    signal.signal(signal.SIGHUP, bail)

    try:
        tty.setraw(fd)
        sys.stdout.write(MOUSE_ON)
        sys.stdout.flush()
        agents, note = snapshot()
        msg = "ready"
        draw(agents, note, msg)
        last = time.time()
        buf = ""
        while True:
            r, _, _ = select.select([fd], [], [], 0.25)
            if r:
                data = os.read(fd, 1024)
                if not data:
                    break
                buf += data.decode("utf-8", "replace")
                events, buf = parse_sgr(buf)
                for ev in events:
                    if ev["button"] is None:
                        if "q" in ev["raw"] or "\x03" in ev["raw"]:
                            raise KeyboardInterrupt
                        continue
                    # Press only, plain left button. Release would fire twice.
                    if not ev["press"] or ev["button"] != 0:
                        continue
                    a = agent_at(agents, ev["row"])
                    msg = focus(a.name) if a else f"row {ev['row']}: no agent there"
                    draw(agents, note, msg)
            if time.time() - last >= REFRESH:
                agents, note = snapshot()
                draw(agents, note, msg)
                last = time.time()
    except KeyboardInterrupt:
        pass
    finally:
        restore()
        print("\n[06-board] terminal restored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
