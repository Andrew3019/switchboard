#!/usr/bin/env python3
"""05 — does a herdr pane forward mouse clicks to a TUI at all?

The whole probe. Turn on SGR mouse reporting, sit in raw mode, print every event
decoded AND raw. If nothing appears when you click, the answer is no and the
clickable board idea dies here.

Nothing here is the product. It's a probe.
"""

import os
import re
import select
import signal
import sys
import termios
import tty

# 1000h = report button press/release. 1006h = SGR encoding (works past column 223).
MOUSE_ON = "\033[?1000h\033[?1006h"
MOUSE_OFF = "\033[?1006l\033[?1000l"

# ESC [ < button ; col ; row (M=press, m=release)
SGR = re.compile(r"\033\[<(\d+);(\d+);(\d+)([Mm])")


def parse_sgr(buf: str):
    """Pure. -> (events, leftover). Split out so it is testable without a terminal.

    Each event: {"button": int, "col": int, "row": int, "press": bool, "raw": str}.
    Bytes that are not a complete SGR event stay in `leftover` — a half-arrived
    escape sequence must not be reported as garbage.
    """
    events = []
    pos = 0
    for m in SGR.finditer(buf):
        if m.start() != pos:
            events.append({"button": None, "col": None, "row": None,
                           "press": None, "raw": buf[pos:m.start()]})
        b = int(m.group(1))
        events.append({
            "button": b,
            "col": int(m.group(2)),
            "row": int(m.group(3)),
            "press": m.group(4) == "M",
            "raw": m.group(0),
        })
        pos = m.end()
    tail = buf[pos:]
    # Keep a possibly-incomplete escape sequence for the next read; anything else
    # is plain input (keystrokes) and is reported now.
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


def button_name(b):
    if b is None:
        return "?"
    base = b & 0b11
    names = {0: "left", 1: "middle", 2: "right", 3: "none"}
    n = names.get(base, str(base))
    if b & 64:
        n = "wheel-up" if base == 0 else "wheel-down"
    mods = []
    if b & 4:
        mods.append("shift")
    if b & 8:
        mods.append("alt")
    if b & 16:
        mods.append("ctrl")
    if b & 32:
        mods.append("drag")
    return "+".join(mods + [n])


def show(ev):
    raw = ev["raw"].replace("\033", "\\e").replace("\r", "\\r").replace("\n", "\\n")
    if ev["button"] is None:
        return f"  other  raw={raw!r}"
    kind = "press  " if ev["press"] else "release"
    return (f"  {kind} {button_name(ev['button']):>12}  "
            f"col={ev['col']:<4} row={ev['row']:<4} raw={raw!r}")


def main():
    if not sys.stdin.isatty():
        print("05-mouse: stdin is not a tty — run this in a real pane.", file=sys.stderr)
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

    # Signals as well as try/finally: a SIGTERM skips finally entirely, and a pane
    # left in raw mode with mouse reporting on is a failed probe even if it worked.
    def bail(sig, _frame):
        restore()
        os.write(sys.stdout.fileno(), b"\r\n[05-mouse] terminal restored.\r\n")
        os._exit(0)

    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGTERM, bail)
    signal.signal(signal.SIGHUP, bail)

    print("05-mouse — click anywhere in this pane.")
    print("Expect one 'press' line and one 'release' line per click, with the")
    print("column and row you clicked. Nothing at all = herdr does not forward clicks.")
    print("Press q (or Ctrl-C) to quit.\n")
    sys.stdout.flush()

    try:
        tty.setraw(fd)
        sys.stdout.write(MOUSE_ON)
        sys.stdout.flush()
        buf = ""
        while True:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                continue
            data = os.read(fd, 1024)
            if not data:                       # stdin closed
                break
            buf += data.decode("utf-8", "replace")
            events, buf = parse_sgr(buf)
            for ev in events:
                if ev["button"] is None and "q" in ev["raw"]:
                    raise KeyboardInterrupt
                if ev["button"] is None and "\x03" in ev["raw"]:
                    raise KeyboardInterrupt
                sys.stdout.write(show(ev) + "\r\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        restore()
        print("\n[05-mouse] terminal restored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
