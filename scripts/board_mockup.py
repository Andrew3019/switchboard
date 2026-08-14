#!/usr/bin/env python3
"""A MOCKUP of a richer switchboard board. Not the board — nothing imports this.

    RUN IT:  ~/.cache/sb-board-mockup/venv/bin/python scripts/board_mockup.py
    ONE FRAME:  ~/.cache/sb-board-mockup/venv/bin/python scripts/board_mockup.py --once
    (venv made with: python3 -m venv ~/.cache/sb-board-mockup/venv &&
                     ~/.cache/sb-board-mockup/venv/bin/pip install rich)

This is a spike so Andrew can look at the "bold + panelled" look in a real pane and
say yes/no/other: a rounded bordered panel with a title, a filled header bar, each
agent's state as a small colour-filled pill, dim secondary text for the task/summary,
and a distinctly styled NEEDS YOU section. Sketch (c) from `notes/board-ui-looks.md`
crossed with (b), rendered through `rich`.

Tuned for a DARK terminal only. Light-terminal support is explicitly out of scope, so
there is no palette switch and no background detection here. Colour stays decorative —
every distinction is also carried by a word or a glyph — so `NO_COLOR` loses polish
and nothing else.

It reads the live snapshot the collector publishes (`<shared .git>/agentflow/panel/
snapshot.json`, the same file `switchboard/panel.py` reads) and falls back to built-in
sample data when there is none, so it runs anywhere. The footer says which it used.

Three things it deliberately does NOT do, because they belong to the real board and
this file must not pretend to be it: no mouse, no click-to-focus, no scrolling. It
also draws a *second*, dim line per agent, which the real board cannot do without
`layout()` charging two screen rows for that agent and `emit()` recording the owner on
both — the row-to-agent mapping is per line already, so that is a layout change, not
an impossible one. Noted in `notes/board-mockup.md`.

Never imports `switchboard.*`. It reads the published JSON as plain dicts, so it runs
from a venv with no repo on `sys.path` and cannot be the thing that opens the store.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

REFRESH = 2.0          # `display.board_refresh` — the real board's cadence
STALE_AFTER = 5.0      # `panel.stale_after`
SNAPSHOT_FORMAT = 1    # `panel.FORMAT`

# ---------------------------------------------------------------------------
# The palette. Dark terminals only — see the module note.
# ---------------------------------------------------------------------------

# A state pill: the word, on a filled block. Colour is the second signal, never the
# only one, so a NO_COLOR pane still reads the word.
PILL = {
    "working": "bold black on green",
    "done": "bold black on yellow",
    "idle": "bold white on grey35",
    "blocked": "bold white on red",
    "failed": "bold white on red",
    "gone": "bold white on red",
}
PILL_DEFAULT = "bold white on grey35"

GLYPH_STYLE = {"✗": "bold red", "◐": "bold yellow", "◌": "bold yellow",
               "○": "dim", "?": "dim", "●": "bold green"}

HEADER_STYLE = "bold white on blue"
NEEDS_STYLE = "bold black on yellow"
BORDER_STYLE = "blue"
DIM = "dim"


# ---------------------------------------------------------------------------
# Width, measured the way board.py measures it
# ---------------------------------------------------------------------------


def vlen(s: str) -> int:
    """Display columns, not characters — board.py's `_visible_len` in miniature."""
    n = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def clip(s: str, cols: int) -> str:
    """`s` cut to at most `cols` columns, with an ellipsis when it lost anything."""
    if cols <= 0:
        return ""
    if vlen(s) <= cols:
        return s
    out, used = "", 0
    for ch in s:
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if used + w > cols - 1:
            break
        out += ch
        used += w
    return out + "…"


def pad(s: str, cols: int) -> str:
    return s + " " * max(0, cols - vlen(s))


def fmt_age(seconds: int) -> str:
    """`status.fmt_age`, copied rather than imported (see the module note)."""
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}"
    d, h = divmod(h, 24)
    return f"{d}d{h:02d}h"


# ---------------------------------------------------------------------------
# Where the data comes from
# ---------------------------------------------------------------------------


def git_common_dir(start: Path) -> Optional[Path]:
    """The shared `.git`, resolved without spawning git — `panel.git_common_dir`."""
    start = start.resolve()
    for base in (start, *start.parents):
        dot = base / ".git"
        if dot.is_dir():
            gitdir = dot
        elif dot.is_file():
            text = dot.read_text().strip()
            if not text.startswith("gitdir:"):
                continue
            raw = Path(text[len("gitdir:"):].strip())
            gitdir = raw if raw.is_absolute() else (base / raw)
        else:
            continue
        common = gitdir / "commondir"
        if common.is_file():
            rel = Path(common.read_text().strip())
            gitdir = rel if rel.is_absolute() else (gitdir / rel)
        return gitdir.resolve()
    return None


def snapshot_path() -> Optional[Path]:
    override = os.environ.get("SB_PANEL_DIR")
    if override:
        return Path(override) / "snapshot.json"
    common = git_common_dir(Path.cwd())
    return None if common is None else common / "agentflow" / "panel" / "snapshot.json"


def read_live() -> tuple[Optional[list[dict]], str]:
    """(agents, note). `None` agents means "there is no live data", with why."""
    path = snapshot_path()
    if path is None:
        return None, "not inside a git repo"
    try:
        payload = json.loads(path.read_bytes())
    except FileNotFoundError:
        return None, "no collector has published a snapshot"
    except (OSError, json.JSONDecodeError) as e:
        return None, f"snapshot unreadable ({e})"
    if payload.get("format") != SNAPSHOT_FORMAT:
        return None, f"snapshot format {payload.get('format')!r}, this reads {SNAPSHOT_FORMAT}"
    agents = (payload.get("snapshot") or {}).get("agents")
    if not isinstance(agents, list):
        return None, "snapshot carries no agents"
    collected = (payload.get("collector") or {}).get("collected_at")
    age = None if collected is None else max(0.0, time.time() - collected)
    if age is None:
        note = "live snapshot, never collected"
    elif age > STALE_AFTER:
        note = f"live snapshot — STALE, {fmt_age(int(age))} old"
    else:
        note = "live snapshot"
    return agents, note


# Built-in sample data: a real `sb status` from this fleet, hand-trimmed, so the
# mockup renders something honest-looking on a machine with no collector at all.
SAMPLE: list[dict] = [
    dict(name="board-fix", role="orchestrator", parent=None, depth=0, state="working",
         alive=True, turn="working", stalled=False, gone=False, unread=0, age=3120,
         idle=2, workspace="board-fix", task="Await my instructions.",
         blocked_why=None, summary=None, undelivered=0, undelivered_age=0,
         archived=False, at_prompt=False, blocked=False, finished=False),
    dict(name="researcher-22", role="researcher", parent="board-fix", depth=1,
         state="done", alive=True, turn="idle", stalled=False, gone=False, unread=1,
         age=540, idle=185, workspace="researcher-22",
         task="Read notes/task-board-ui-current.md and do exactly what it says.",
         blocked_why=None,
         summary="that file does not exist on any branch — said so and stopped",
         undelivered=0, undelivered_age=0, archived=False, at_prompt=True,
         blocked=False, finished=True),
    dict(name="researcher-23", role="researcher", parent="board-fix", depth=1,
         state="done", alive=True, turn="idle", stalled=False, gone=False, unread=1,
         age=505, idle=180, workspace="researcher-23",
         task="Read notes/task-board-ui-techniques.md and do exactly what it says.",
         blocked_why=None,
         summary="task file missing — reported it and stopped, nothing changed",
         undelivered=0, undelivered_age=0, archived=False, at_prompt=False,
         blocked=False, finished=True),
    dict(name="researcher-26", role="researcher", parent="board-fix", depth=1,
         state="working", alive=True, turn="working", stalled=False, gone=False,
         unread=0, age=18, idle=15, workspace="researcher-26",
         task="Read notes/task-board-ui-deps.md and do exactly what it says.",
         blocked_why=None, summary=None, undelivered=0, undelivered_age=0,
         archived=False, at_prompt=False, blocked=False, finished=False),
    dict(name="worker-25", role="worker", parent="board-fix", depth=1,
         state="blocked", alive=True, turn="idle", stalled=False, gone=False,
         unread=0, age=900, idle=240, workspace="worker-25",
         task="Build a runnable mockup of a richer board.",
         blocked_why="which pane should this render into?", summary=None,
         undelivered=0, undelivered_age=0, archived=False, at_prompt=False,
         blocked=True, finished=False),
    dict(name="qa-31", role="qa", parent="worker-25", depth=2, state="working",
         alive=True, turn="idle", stalled=True, gone=False, unread=2, age=1500,
         idle=760, workspace="qa-31", task="Verify the mockup at 40/56/100 columns.",
         blocked_why=None, summary=None, undelivered=2, undelivered_age=300,
         archived=False, at_prompt=False, blocked=False, finished=False),
    dict(name="worker-19", role="worker", parent="board-fix", depth=1, state="working",
         alive=False, turn="working", stalled=False, gone=True, unread=0, age=4300,
         idle=1900, workspace="worker-19", task="Old pane, herdr has no such agent.",
         blocked_why=None, summary=None, undelivered=0, undelivered_age=0,
         archived=False, at_prompt=False, blocked=False, finished=False),
    dict(name="worker-11", role="worker", parent="board-fix", depth=1, state="done",
         alive=False, turn="idle", stalled=False, gone=False, unread=0, age=88000,
         idle=70000, workspace="worker-11", task="Earlier, finished work.",
         blocked_why=None, summary="landed on branch worker-11", undelivered=0,
         undelivered_age=0, archived=True, at_prompt=False, blocked=False,
         finished=True),
]


# ---------------------------------------------------------------------------
# What a row says — board.py's rules, over plain dicts
# ---------------------------------------------------------------------------


def g(a: dict, key: str, default: Any = None) -> Any:
    return a.get(key, default)


def display_state(a: dict) -> str:
    """`AgentStatus.display_state`, with a fallback for older snapshots.

    A live collector running older code publishes no `display_state` key, so the rule
    is recomputed here rather than the column being left blank: task still open plus a
    running turn reads `working`, task still open with nothing running reads `idle`,
    and any terminal word the agent wrote for itself stands as it is.
    """
    if a.get("display_state"):
        return a["display_state"]
    state = g(a, "state", "?")
    if state not in ("working", "open", None):
        return state
    if g(a, "alive") is False:
        return "idle"
    turn = g(a, "turn")
    if turn is not None:
        return "working" if turn == "working" else "idle"
    return "working" if g(a, "alive") else "idle"


def glyph(a: dict) -> str:
    if g(a, "gone"):
        return "✗"
    if g(a, "at_prompt") or g(a, "blocked"):
        return "◐"
    if g(a, "stalled") or g(a, "signal_drift"):
        return "◌"
    if g(a, "finished"):
        return "○"
    if g(a, "alive") is None:
        return "?"
    return "●"


def marker(a: dict) -> str:
    if g(a, "gone"):
        return "GONE — herdr has no such agent"
    if g(a, "at_prompt"):
        return "AT PROMPT — waiting on you"
    if g(a, "blocked"):
        return f"BLOCKED — {g(a, 'blocked_why') or 'no reason recorded'}"
    if g(a, "stalled"):
        return f"STALLED — idle {fmt_age(int(g(a, 'idle', 0)))}"
    if g(a, "signal_drift"):
        return "NO SESSION — died mid-turn, pane still open"
    return ""


def mail_note(a: dict) -> str:
    bits = []
    if g(a, "waiting_to_be_rung"):
        bits.append(f"UNDELIVERED {g(a, 'undelivered', 0)}, "
                    f"{fmt_age(int(g(a, 'undelivered_age', 0)))}")
    told = int(g(a, "unread", 0)) - int(g(a, "undelivered", 0))
    if told > 0:
        bits.append(f"{told} unread")
    return ("mail: " + " · ".join(bits)) if bits else ""


def secondary(a: dict) -> str:
    """The dim line under the row: what this agent is for, or what came of it."""
    if g(a, "finished") and g(a, "summary"):
        return "✓ " + str(g(a, "summary"))
    if g(a, "idle_excuse"):
        return "· " + str(g(a, "idle_excuse"))
    task = g(a, "task")
    return "↳ " + str(task) if task else ""


def wants_you(a: dict) -> bool:
    return bool(g(a, "gone") or g(a, "stalled") or g(a, "signal_drift")
                or g(a, "blocked") or g(a, "at_prompt"))


def needs_human(a: dict) -> bool:
    if "needs_human" in a:
        return bool(a["needs_human"])
    return bool(wants_you(a) or int(g(a, "unread", 0)) > 0)


def needs_reason(a: dict) -> str:
    m = marker(a)
    if m:
        return m.split(" — ")[0].lower() if " — " in m else m.lower()
    told = int(g(a, "unread", 0))
    return f"{told} unread, not picked up" if told else "wants a person"


# ---------------------------------------------------------------------------
# The tree: archived subtrees collapse, exactly as `status.display_rows` does
# ---------------------------------------------------------------------------


def display_rows(agents: list[dict], *, show_archived: bool = False) -> list[Any]:
    """Rows to draw. A fully-archived subtree becomes one `+ N archived` marker.

    `sealed(x) ≡ archived(x) ∧ ∀c ∈ children(x): sealed(c)` — the rule from
    `status.display_rows`, reimplemented over dicts. A collapsed row is a plain
    `{"collapsed": True, ...}` so a renderer cannot mistake it for an agent.
    """
    if show_archived:
        return list(agents)
    kids: dict[Optional[str], list[dict]] = {}
    for a in agents:
        kids.setdefault(g(a, "parent"), []).append(a)

    def subtree(a: dict) -> list[dict]:
        out = [a]
        for c in kids.get(a["name"], []):
            out.extend(subtree(c))
        return out

    def sealed(a: dict) -> bool:
        return bool(g(a, "archived")) and all(sealed(c) for c in kids.get(a["name"], []))

    out: list[Any] = []

    def walk(parent: Optional[str], depth: int) -> None:
        hidden, needs = 0, 0
        for a in kids.get(parent, []):
            if sealed(a):
                sub = subtree(a)
                hidden += len(sub)
                needs += sum(1 for x in sub if needs_human(x))
                continue
            out.append(a)
            walk(a["name"], depth + 1)
        if hidden:
            out.append({"collapsed": True, "depth": depth, "count": hidden,
                        "needs": needs})

    walk(None, 0)
    return out


def is_collapsed(row: Any) -> bool:
    return isinstance(row, dict) and row.get("collapsed") is True


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def bar(text: str, width: int, style: str) -> Text:
    """A filled full-width bar. Padded, never wrapped: it is exactly `width` wide."""
    return Text(pad(clip(text, width), width), style=style, no_wrap=True,
                overflow="crop")


def pill(word: str, width: int, compact: bool) -> Text:
    """The state, as a small filled block. `compact` drops the side padding."""
    body = word if compact else f" {word} "
    return Text(pad(clip(body, width), width), style=PILL.get(word, PILL_DEFAULT),
                no_wrap=True, overflow="crop")


def summary_bits(agents: list[dict]) -> list[str]:
    alive = sum(1 for a in agents if g(a, "alive"))
    at_prompt = sum(1 for a in agents if g(a, "at_prompt"))
    blocked = sum(1 for a in agents if g(a, "blocked"))
    unread = sum(int(g(a, "unread", 0)) for a in agents)
    bits = [f"{alive} alive"]
    if at_prompt:
        bits.append(f"{at_prompt} at prompt")
    if blocked:
        bits.append(f"{blocked} blocked")
    if unread:
        bits.append(f"{unread} unread")
    return bits


def render(agents: list[dict], width: int, source_note: str,
           *, show_archived: bool = False) -> Panel:
    """One frame. `width` is the whole pane; the panel fits inside it exactly."""
    inner = max(10, width - 4)              # 2 border columns, 2 of padding
    rows = display_rows(agents, show_archived=show_archived)

    live = [r for r in rows if not is_collapsed(r)]
    names = [("  " * int(g(a, "depth", 0))) + str(g(a, "name", "?")) for a in live]
    states = [display_state(a) for a in live]

    # The column budget, narrowest-first. A 40-column pane cannot hold a padded pill,
    # a full name and an age, so each is given up in turn — the age last, because two
    # rows that both say `idle` are told apart by nothing else.
    compact = False
    w_state = max([0] + [vlen(s) for s in states]) + 2
    w_name = max([0] + [vlen(n) for n in names])
    fixed = 3 + 2 + 2 + 5                   # " ● ", gaps, age column
    if fixed + w_name + w_state > inner:
        compact, w_state = True, w_state - 2
    if fixed + w_name + w_state > inner:
        w_name = max(6, inner - fixed - w_state)
    show_age = fixed + w_name + w_state <= inner

    body: list[Any] = []
    body.append(bar(" " + " · ".join(["switchboard"] + summary_bits(agents)), inner,
                    HEADER_STYLE))
    body.append(Text(""))

    for i, row in enumerate(rows):
        if i > 0 and int(g(row, "depth", 0)) <= 1:
            body.append(Text(""))           # the group break: whitespace, not a rule
        if is_collapsed(row):
            label = ("  " * row["depth"]) + f"+ {row['count']} archived"
            if row["needs"]:
                label += f" · {row['needs']} need you"
            body.append(Text(clip("   " + label, inner), style=DIM, no_wrap=True,
                             overflow="crop"))
            continue

        gl = glyph(row)
        line = Text(no_wrap=True, overflow="crop")
        line.append(" ")
        line.append(gl, style=GLYPH_STYLE.get(gl, ""))
        line.append(" ")
        line.append(pad(clip(("  " * int(g(row, "depth", 0))) + str(g(row, "name", "?")),
                             w_name), w_name),
                    style="bold" if wants_you(row) else "")
        line.append("  ")
        line.append_text(pill(display_state(row), w_state, compact))
        used = 3 + w_name + 2 + w_state
        if show_age:
            line.append("  " + f"{fmt_age(int(g(row, 'idle', 0))):>5}", style=DIM)
            used += 7

        # The tail: the trouble first, then the mail. Same ranking as `detail_bits`,
        # minus rank three — the task/summary has its own dim line below.
        tail = marker(row) or ""
        mail = mail_note(row)
        if tail and mail and vlen(tail) + 3 + vlen(mail) > inner - used - 3:
            tail = mail if wants_you(row) is False else tail
        elif mail and tail:
            tail = tail + " · " + mail
        elif mail:
            tail = mail
        if tail and inner - used > 12:
            style = "red" if g(row, "gone") else "yellow"
            line.append("  " + clip(tail, inner - used - 2), style=style)
        body.append(line)

        note = secondary(row)
        if note:
            body.append(Text(clip("      " + note, inner), style=DIM, no_wrap=True,
                             overflow="crop"))

    wanted = [a for a in agents if needs_human(a)]
    if wanted:
        body.append(Text(""))
        body.append(bar(f" NEEDS YOU · {len(wanted)}", inner, NEEDS_STYLE))
        w_want = min(max(vlen(str(g(a, "name", "?"))) for a in wanted[:6]), inner - 12)
        for a in wanted[:6]:
            line = Text(no_wrap=True, overflow="crop")
            name = pad(clip(str(g(a, "name", "?")), w_want), w_want)
            line.append("  " + name, style="bold yellow")
            room = inner - 2 - w_want - 2
            if room > 8:
                line.append("  " + clip(needs_reason(a), room), style=DIM)
            body.append(line)
        if len(wanted) > 6:
            body.append(Text(clip(f"  + {len(wanted) - 6} more", inner), style=DIM,
                             no_wrap=True, overflow="crop"))

    body.append(Text(""))
    body.append(Text(clip(f"{source_note} · mockup, not the board", inner), style=DIM,
                     no_wrap=True, overflow="crop"))

    return Panel(Group(*body), box=ROUNDED, border_style=BORDER_STYLE,
                 title="[bold]switchboard[/bold]", title_align="left",
                 padding=(0, 1), width=width, expand=False)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def load(source: str) -> tuple[list[dict], str]:
    if source != "sample":
        agents, note = read_live()
        if agents is not None:
            return agents, note
        if source == "live":
            return [], f"no live data — {note}"
        return SAMPLE, f"sample data — {note}"
    return SAMPLE, "sample data — asked for"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--once", action="store_true", help="render one frame and exit")
    p.add_argument("--width", type=int, default=None,
                   help="force a pane width, for testing narrow panes")
    p.add_argument("--source", choices=("auto", "live", "sample"), default="auto")
    p.add_argument("--archived", action="store_true", help="do not collapse archived")
    p.add_argument("--refresh", type=float, default=REFRESH)
    args = p.parse_args(argv)

    console = Console(width=args.width, no_color=os.environ.get("NO_COLOR") is not None,
                      highlight=False, soft_wrap=False)

    def width() -> int:
        return args.width or max(20, console.width)

    if args.once:
        agents, note = load(args.source)
        console.print(render(agents, width(), note, show_archived=args.archived))
        return 0

    resized = {"flag": False}

    def on_winch(*_: Any) -> None:
        resized["flag"] = True

    try:
        signal.signal(signal.SIGWINCH, on_winch)
    except (AttributeError, ValueError):
        pass                                # no SIGWINCH here; the tick still redraws

    from rich.live import Live

    with Live(console=console, screen=True, auto_refresh=False,
              transient=False) as live:
        try:
            while True:
                agents, note = load(args.source)
                # SIGWINCH only cuts the sleep short. The width itself comes from
                # `console.width`, which re-reads the terminal every render, so a
                # resize needs nothing else — it would be picked up on the next tick
                # anyway; this makes it immediate.
                resized["flag"] = False
                live.update(render(agents, width(), note,
                                   show_archived=args.archived), refresh=True)
                deadline = time.time() + args.refresh
                while time.time() < deadline and not resized["flag"]:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
