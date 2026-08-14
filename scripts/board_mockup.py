#!/usr/bin/env python3
"""A MOCKUP of a richer switchboard board. Not the board — nothing imports this.

    RUN IT:  ~/.cache/sb-board-mockup/venv/bin/python scripts/board_mockup.py
    ONE FRAME:  ~/.cache/sb-board-mockup/venv/bin/python scripts/board_mockup.py --once
    (venv made with: python3 -m venv ~/.cache/sb-board-mockup/venv &&
                     ~/.cache/sb-board-mockup/venv/bin/pip install rich)

This is a spike so Andrew can look at the "bold + panelled" look in a real pane and
say yes/no/other: a rounded bordered panel with a title, a filled header bar, each
agent's state as one coloured word, and a distinctly styled NEEDS YOU section listing
the two kinds of agent that want a person — BLOCKED and IDLE, named, not just coloured.
Sketch (c) from `notes/board-ui-looks.md` crossed with (b), rendered through `rich`.

ONE LINE PER AGENT, like the real board. It drew a second dim line with the task or the
done summary until Andrew said he does not read those on a board; they are gone, not
demoted, and `sb status` still shows both. What he does watch for is BLOCKED and MAIL,
so the row reserves columns for those two BEFORE it spends any on the name, the age or
the pill's padding — see `tail_forms` and the budget in `render`.

Tuned for a DARK terminal only. Light-terminal support is explicitly out of scope, so
there is no palette switch and no background detection here. Colour stays decorative —
every distinction is also carried by a word or a glyph — so `NO_COLOR` loses polish
and nothing else.

It reads the live snapshot the collector publishes (`<shared .git>/agentflow/panel/
snapshot.json`, the same file `switchboard/panel.py` reads) and falls back to built-in
sample data when there is none, so it runs anywhere. The footer says which it used.

Three things it deliberately does NOT do, because they belong to the real board and
this file must not pretend to be it: no mouse, no click-to-focus, no scrolling.

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

# The state word, as plain coloured text. It was a filled pill — the word on a block of
# colour — until Andrew said the fill was ugly; the colour meanings are unchanged, only
# the block is gone. Colour stays the second signal and never the only one, so a
# NO_COLOR pane still reads the word.
STATE = {
    "working": "bold green",
    "done": "bold yellow",
    "idle": "dim",
    "blocked": "bold red",
    "failed": "bold red",
    "gone": "bold red",
}
STATE_DEFAULT = "dim"

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


def clip_name(s: str, cols: int) -> str:
    """A name cut to `cols`, KEEPING ITS TAIL — `researcher-22` → `re…-22`.

    Not `clip`, which keeps the head. Switchboard names are a role and a number, and at
    the width the tail reserve leaves for this column the head is the half every sibling
    shares: three rows reading `res…` are three rows a human cannot tell apart, where
    `re…-22` and `re…-23` still name somebody.
    """
    if vlen(s) <= cols or cols < 4:
        return clip(s, cols)
    keep = 3                                # the number, near enough always
    return clip(s, cols - keep) + s[-keep:]


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
    # `workspace="worker-25"`, not `"qa-31"`: only a TOP's delegate mints a new
    # workspace, so a worker's child is a tab in the worker's own worktree. The fixture
    # said `qa-31` until the gutter started reading this field and made the error visible.
    dict(name="qa-31", role="qa", parent="worker-25", depth=2, state="working",
         alive=True, turn="idle", stalled=True, gone=False, unread=2, age=1500,
         idle=760, workspace="worker-25",
         task="Verify the mockup at 40/56/100 columns.",
         blocked_why=None, summary=None, undelivered=2, undelivered_age=300,
         waiting_to_be_rung=True,
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


def mail_note(a: dict, *, short: bool = False) -> str:
    """The mail waiting here. `short` is the form that must survive a narrow pane.

    Words, never a glyph, for `board.mail_note`'s reason: an envelope character is one
    column wide in some terminals and two in others, and a row one column wider than it
    measured is the wrap everything here is built to prevent.
    """
    bits = []
    if g(a, "waiting_to_be_rung"):
        n, age = g(a, "undelivered", 0), fmt_age(int(g(a, "undelivered_age", 0)))
        bits.append(f"UNDEL {n}" if short else f"UNDELIVERED {n}, {age}")
    told = int(g(a, "unread", 0)) - int(g(a, "undelivered", 0))
    if told > 0:
        bits.append(f"{told} unread")
    if not bits:
        return ""
    joined = " · ".join(bits)
    return joined if short else "mail: " + joined


def marker_short(a: dict) -> str:
    """The marker cut to its WORD — `BLOCKED`, `AT PROMPT`, `GONE`, `STALLED`.

    The half of the marker that must never be the thing a narrow pane drops: the reason
    after the dash is recoverable from the agent's own pane, the word is not.
    """
    m = marker(a)
    return m.split(" — ")[0] if " — " in m else m


def tail_forms(a: dict) -> list[str]:
    """Everything the row's tail could say, WIDEST FIRST, narrowest last.

    Andrew watches for two things — BLOCKED and MAIL — so those are what the row gives
    up last. The ladder degrades the *wording* before it gives up either piece, and the
    last rung (the word plus the count) is what `render` reserves columns for before it
    spends any on the name, the age or the pill's padding. Only a pane too narrow for
    even that rung clips this, which is the one case the layout cannot honour.

    The task head and the done summary are not here at all. They were the dim second
    line this mockup used to draw; Andrew asked for one line per agent and does not read
    them on the board, so they are gone rather than demoted — `sb status` still has both.
    """
    full_m, short_m = marker(a), marker_short(a)
    full_x, short_x = mail_note(a), mail_note(a, short=True)
    if full_m and full_x:
        forms = [f"{full_m} · {full_x}", f"{full_m} · {short_x}",
                 f"{short_m} · {short_x}"]
    elif full_m:
        forms = [full_m, short_m]
    elif full_x:
        forms = [full_x, short_x]
    else:
        return []
    out: list[str] = []
    for f in forms:                         # the ladder, without repeated rungs
        if f not in out:
            out.append(f)
    return out


def squeeze(a: dict, room: int) -> str:
    """The tail when no whole rung of the ladder fits: fill `room`, mail first.

    Two jobs. It uses the room a rung would have left empty — a 25-column tail says
    `BLOCKED — which pane s…`, not a bare `BLOCKED` with fifteen columns of nothing
    after it — and it decides what gets cut when the pane is narrower than even the
    bottom rung: the marker's REASON goes, then its word, and the mail is kept whole to
    the last. Mail is the shorter of the two and the only one with no other
    representation on the row — the pill beside it already says `blocked`, and NEEDS
    YOU below names the agent again — so an unanswered message is what a clip here
    would really lose. `board._MAIL_RESERVE` makes the same trade for the same reason.
    """
    full, word = marker(a), marker_short(a)
    if not full:
        return clip(mail_note(a) if vlen(mail_note(a)) <= room
                    else mail_note(a, short=True), room)
    for x in (mail_note(a), mail_note(a, short=True)):
        if not x:
            continue
        gap = vlen(x) + 3
        if room - gap >= vlen(word) + 2:    # the word survives, plus a hint of the why
            return clip(full, room - gap) + " · " + x
    x = mail_note(a, short=True)
    if x:
        if room - vlen(x) - 3 >= 1:
            return clip(word, room - vlen(x) - 3) + " · " + x
        return clip(x, room)                # the last thing standing
    return clip(full if room >= vlen(word) + 2 else word, room)


def wants_you(a: dict) -> bool:
    return bool(g(a, "gone") or g(a, "stalled") or g(a, "signal_drift")
                or g(a, "blocked") or g(a, "at_prompt"))


def needs_kind(a: dict) -> str:
    """Which of NEEDS YOU's TWO kinds this agent is, or `""` for neither.

    `"blocked"` — an agent waiting on a human, whether it called `sb block` or is simply
    sitting at its prompt. `"idle"` — an agent with nothing running: stalled, or a
    session that died mid-turn with the pane still open.

    Nothing else qualifies. Unread mail used to put an agent in this list and no longer
    does: Andrew does not treat a message as something the board should summon him for,
    and the agent's own row still says `mail:` in its tail. `gone` is out too — a pane
    herdr has no agent for is neither blocked nor idle, and its row already shouts GONE
    in red. Both are still visible ON the rows; they are only out of the summons list.
    """
    if g(a, "blocked") or g(a, "at_prompt"):
        return "blocked"
    if g(a, "stalled") or g(a, "signal_drift"):
        return "idle"
    return ""


def needs_human(a: dict) -> bool:
    """Same predicate the NEEDS YOU list uses, so `+ N need you` cannot disagree with it.

    Deliberately ignores a snapshot's own `needs_human` key: the collector counts unread
    mail in it, which is exactly what this list no longer summons anybody for.
    """
    return bool(needs_kind(a))


def needs_reason(a: dict) -> str:
    """Why this agent is in the list — the half after the kind word."""
    if g(a, "at_prompt"):
        return "at a prompt, waiting on you"
    if g(a, "blocked"):
        return g(a, "blocked_why") or "no reason recorded"
    if g(a, "signal_drift"):
        return "died mid-turn, pane still open"
    if g(a, "stalled"):
        # Age first: it is the half worth reading, and the half a clip would eat if the
        # words came first.
        return f"idle {fmt_age(int(g(a, 'idle', 0)))}, nothing running"
    return ""


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


def row_depth(row: Any) -> int:
    return int((row.get("depth", 0) if is_collapsed(row) else g(row, "depth", 0)) or 0)


# ---------------------------------------------------------------------------
# The workspace gutter: grouping without spending a blank line on it
# ---------------------------------------------------------------------------

# A group is a RUN OF CONSECUTIVE ROWS SHARING A WORKSPACE — read from the data, not
# inferred from depth. An earlier draft bracketed "a depth-0 agent and its whole subtree",
# which merges several worktrees into one: researcher-32's finding
# (`notes/board-worktree-grouping.md`, branch `researcher-32`) is that a new workspace
# opens when a TOP delegates, so each direct child of a top starts its own workspace and
# the top sits alone in its own. Reading `workspace` gets that right without encoding the
# fork rule here at all, and stays right whichever way that rule goes later.
#
# The live store has a case that settles it: `workspace-debug`, a depth-1 child of `main`,
# has `workspace == "main"` — same as its parent, unlike every one of its siblings. Depth
# cannot tell that row from the ones around it; the workspace value can.
#
# Three shapes to choose between, all one rule character drawn INSIDE the indentation the
# row already has. Cost: nothing.
GUTTER_STYLES = ("bracket", "bar", "tick", "none")

# Colours. `single` is one colour for every group; `rotate` gives each group its own.
# Rotating is the tempting one and the wrong one — see the note in `gutter_column`.
# `single` was `grey42` and Andrew could not tell it had a colour at all; it is now cyan,
# which is outside the board's status vocabulary (green/yellow/red) and not the panel
# border's blue.
GUTTER_SINGLE = "bold cyan"
GUTTER_ROTATE = ("bold cyan", "bold magenta", "bold green", "bold blue",
                 "bold yellow", "bold red")


def group_runs(rows: list[Any]) -> list[tuple[int, int]]:
    """`(first, last)` row index for each run of consecutive rows sharing a workspace.

    Collapsed-archive markers carry no workspace of their own — the agents they stand for
    may be several workspaces — so they belong to no run and end whichever run they
    follow. In practice a collapsed row sits at the end of a subtree, so this splits
    nothing real; a collapsed row landing mid-run would cut that group's rule in two.
    """
    runs: list[list[int]] = []
    current: Optional[str] = None
    for i, row in enumerate(rows):
        ws = None if is_collapsed(row) else g(row, "workspace")
        if ws is not None and ws == current:
            runs[-1][1] = i
        elif ws is not None:
            runs.append([i, i])
        current = ws
    return [(a, b) for a, b in runs]


def gutter_column(rows: list[Any], style: str,
                  colour: str) -> list[Optional[tuple[str, str, int]]]:
    """Per row: `(char, style, indent_offset)`, or `None` for rows with no rule.

    The rule lives in the INDENTATION, between the glyph and the name, at the column the
    group's shallowest row indents to. Every row in a run is at least that deep, so the
    rule always lands on a space and the name column never moves — the gutter costs zero
    columns. Only a run whose shallowest row is at depth 0 has no indent to draw in; that
    one is skipped rather than shifting the whole board one column right.

    `bracket` is corner-rule-corner. `bar` is a plain rule the run's full height, no
    corners. `tick` marks only the run's first row.

    A ONE-ROW RUN DRAWS NOTHING. A bracket around a single row says "these rows go
    together" about one row, which is not information, and Andrew specifically does not
    want the top orchestrator — alone in its own workspace, always — enclosed. So the
    gutter only ever appears where a workspace actually holds more than one visible agent.

    On colour: `single` is the honest default. A terminal has a handful of reliably
    distinct colours and this fleet has run ninety-odd workspaces, so `rotate` recycles
    within one screen — and two runs sharing a colour reads as one run, which is exactly
    the thing the gutter exists to deny. The bracket already says WHERE the boundaries
    are; colour would only add WHICH group, and that is the part it does badly. `rotate`
    is here so Andrew can see that for himself.
    """
    out: list[Optional[tuple[str, str, int]]] = [None for _ in rows]
    if style not in GUTTER_STYLES or style == "none":
        return out
    n = 0
    for first, last in group_runs(rows):
        if first == last:                   # a workspace of one: nothing to enclose
            continue
        depth = min(row_depth(rows[i]) for i in range(first, last + 1))
        if depth < 1:                       # no indentation to live in
            continue
        off = 2 * (depth - 1)
        tint = GUTTER_SINGLE if colour != "rotate" else \
            GUTTER_ROTATE[n % len(GUTTER_ROTATE)]
        n += 1
        for i in range(first, last + 1):
            if style == "tick":
                ch = "▌" if i == first else " "
            elif style == "bar":
                ch = "▌"
            else:                           # bracket
                ch = "╭" if i == first else "╰" if i == last else "│"
            out[i] = (ch, tint, off)
    return out


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def bar(text: str, width: int, style: str) -> Text:
    """A filled full-width bar. Padded, never wrapped: it is exactly `width` wide."""
    return Text(pad(clip(text, width), width), style=style, no_wrap=True,
                overflow="crop")


def state_word(word: str, width: int) -> Text:
    """The state, as plain coloured text padded to the column.

    No fill and no side padding: with a background block gone, padding is invisible
    anyway, so the column is exactly as wide as the widest state word on screen.
    """
    return Text(pad(clip(word, width), width), style=STATE.get(word, STATE_DEFAULT),
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
           *, show_archived: bool = False, gutter: str = "bracket",
           gutter_colour: str = "single") -> Panel:
    """One frame. `width` is the whole pane; the panel fits inside it exactly."""
    inner = max(10, width - 4)              # 2 border columns, 2 of padding
    rows = display_rows(agents, show_archived=show_archived)
    rules = gutter_column(rows, gutter, gutter_colour)

    live = [r for r in rows if not is_collapsed(r)]
    names = [("  " * int(g(a, "depth", 0))) + str(g(a, "name", "?")) for a in live]
    states = [display_state(a) for a in live]

    # THE TAIL IS RESERVED FIRST. Everything else on the row bids for what is left.
    # BLOCKED and MAIL are what Andrew watches for, so the narrowest rung of every
    # row's ladder (`tail_forms`) is charged to the budget before the name, the age or
    # the pill's padding get any of it — the reverse of the usual "fill until full",
    # and the whole point of the layout below.
    reserve = max([0] + [vlen(f[-1]) for f in
                         (tail_forms(a) for a in live) if f])
    reserve += 2 if reserve else 0          # the two spaces before it
    w_state = max([0] + [vlen(s) for s in states])
    w_name_full = max([0] + [vlen(n) for n in names])

    # Given up in this order as the pane narrows: the age first (the state word already
    # says whether anything is running), then the name — down to six columns, below which
    # a name is not a name. Only after both is the reserve itself cut, which is the one
    # case a pane too narrow for `BLOCKED · 2 unread` forces and nothing here can prevent.
    # (There used to be a rung between those two that dropped the state pill's side
    # padding. The pill is plain text now, so there is no padding left to give up.)
    # The gutter is NOT in here. Its rule is drawn inside the indentation the name column
    # already carries, so grouping costs nothing and this budget is the same with it on
    # or off.
    fixed = 3 + 2                           # " ● " and the gap before the state
    for show_age in (True, False):
        w_name = w_name_full
        age_cols = 7 if show_age else 0
        if fixed + w_name + w_state + age_cols + reserve <= inner:
            break
    else:
        w_name = max(6, inner - fixed - w_state - reserve)
    left_used = fixed + w_name + w_state + (7 if show_age else 0)

    body: list[Any] = []
    body.append(bar(" " + " · ".join(["switchboard"] + summary_bits(agents)), inner,
                    HEADER_STYLE))

    # NO BLANK LINES BETWEEN AGENTS. Every row sits directly under the one above it and
    # the indentation alone carries the tree. An earlier draft broke groups apart with a
    # blank line above each top-level agent and its direct children; with one-line rows
    # that put an empty line between nearly every pair and roughly doubled the board's
    # height, so Andrew had it removed outright — not swapped for a rule or padding.
    # The filled bars and the panel border are what separate the sections now. The board
    # draws exactly one blank line in total, above NEEDS YOU; see there for why.
    for i, row in enumerate(rows):
        line = Text(no_wrap=True, overflow="crop")

        if is_collapsed(row):
            label = ("  " * row["depth"]) + f"+ {row['count']} archived"
            if row["needs"]:
                label += f" · {row['needs']} need you"
            line.append(clip("   " + label, inner), style=DIM)
            body.append(line)
            continue

        # A gone agent is one whose pane herdr no longer has. It is the row a future
        # "clear them all" key would sweep, so it is drawn to be picked out without
        # reading: red the whole way across, and the name struck through. The strike is
        # decoration on top of the glyph, the red and the word GONE in the tail — a
        # terminal that ignores it loses nothing that carries meaning.
        doomed = bool(g(row, "gone"))
        gl = glyph(row)
        line.append(" ")
        line.append(gl, style=GLYPH_STYLE.get(gl, ""))
        line.append(" ")
        indent = "  " * int(g(row, "depth", 0))
        label = pad(indent + clip_name(str(g(row, "name", "?")),
                                       max(1, w_name - vlen(indent))), w_name)
        name_style = ("bold red strike" if doomed
                      else "bold" if wants_you(row) else "")
        # The workspace rule, drawn INTO the indent rather than in front of it. `off` is
        # always inside this row's indentation, so the character it replaces is a space
        # and the name column stays exactly where it was.
        rule = rules[i]
        if rule is not None and rule[2] < vlen(indent):
            ch, tint, off = rule
            line.append(label[:off], style=name_style)
            line.append(ch, style=tint)
            line.append(label[off + 1:], style=name_style)
        else:
            line.append(label, style=name_style)
        line.append("  ")
        if doomed:
            line.append(pad(clip(display_state(row), w_state), w_state), style="red")
        else:
            line.append_text(state_word(display_state(row), w_state))
        if show_age:
            line.append("  " + f"{fmt_age(int(g(row, 'idle', 0))):>5}",
                        style="red" if doomed else DIM)

        # The widest rung of this row's ladder that fits in the room the budget above
        # kept for it. Never dropped: a row with a tail always draws one, clipped only
        # when even the narrowest rung is wider than the pane.
        forms = tail_forms(row)
        if forms:
            room = max(1, inner - left_used - 2)
            # The whole tail if it fits; otherwise `squeeze`, which fills the room it
            # has rather than falling back to a short rung and leaving space unused.
            text = forms[0] if vlen(forms[0]) <= room else squeeze(row, room)
            line.append("  " + clip(text, room),
                        style="bold red" if doomed else "yellow")
        body.append(line)

    # Two kinds only, blocked before idle, each named by a WORD and not just a colour —
    # `needs_kind` says which and why the rest are out.
    wanted = [a for a in agents if needs_kind(a) == "blocked"]
    wanted += [a for a in agents if needs_kind(a) == "idle"]
    if wanted:
        # The ONLY blank line on the board. Every other gap went when Andrew asked for
        # none; this one came back because NEEDS YOU is the part he acts on and it earns
        # a breath above it. Not a precedent — nothing goes under the header, between
        # agent rows or above the footer.
        body.append(Text(""))
        body.append(bar(f" NEEDS YOU · {len(wanted)}", inner, NEEDS_STYLE))
        shown = wanted[:6]
        w_kind = 7                          # "BLOCKED", the longer of the two words
        w_want = min(max(vlen(str(g(a, "name", "?"))) for a in shown), inner - 12)
        for a in shown:
            kind = needs_kind(a)
            line = Text(no_wrap=True, overflow="crop")
            line.append("  " + pad(kind.upper(), w_kind),
                        style="bold red" if kind == "blocked" else "bold yellow")
            line.append("  " + pad(clip(str(g(a, "name", "?")), w_want), w_want),
                        style="bold")
            room = inner - 2 - w_kind - 2 - w_want - 2
            # Below this the reason is all ellipsis and says less than the kind word
            # already does, so a narrow pane gets KIND + name and nothing else.
            if room >= 14:
                line.append("  " + clip(needs_reason(a), room), style=DIM)
            body.append(line)
        if len(wanted) > 6:
            body.append(Text(clip(f"  + {len(wanted) - 6} more", inner), style=DIM,
                             no_wrap=True, overflow="crop"))

    # The footer, with the gone-sweep affordance FIRST so a narrow pane clips the
    # provenance note instead of the one actionable thing on the line. It is a sketch of
    # a key, not a key: this mockup reads no input at all and clears nothing. What it
    # shows is how the offer would read, and how many rows it would take.
    doomed_n = sum(1 for a in agents if g(a, "gone"))
    foot = Text(no_wrap=True, overflow="crop")
    used = 0
    if doomed_n:
        offer = f" x  clear {doomed_n} gone "
        foot.append(clip(offer, inner), style="bold white on red")
        used = vlen(clip(offer, inner))
        if inner - used > 3:
            foot.append("  ")
            used += 2
    foot.append(clip(f"{source_note} · mockup, not the board", inner - used), style=DIM)
    body.append(foot)

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
    p.add_argument("--gutter", choices=GUTTER_STYLES, default="bracket",
                   help="how workspace groups are enclosed in the left gutter")
    p.add_argument("--gutter-colour", choices=("single", "rotate"), default="single",
                   help="one colour for every group, or one colour per group")
    p.add_argument("--refresh", type=float, default=REFRESH)
    args = p.parse_args(argv)

    console = Console(width=args.width, no_color=os.environ.get("NO_COLOR") is not None,
                      highlight=False, soft_wrap=False)

    def width() -> int:
        return args.width or max(20, console.width)

    def frame(agents: list[dict], note: str) -> Panel:
        return render(agents, width(), note, show_archived=args.archived,
                      gutter=args.gutter, gutter_colour=args.gutter_colour)

    if args.once:
        agents, note = load(args.source)
        console.print(frame(agents, note))
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
                live.update(frame(agents, note), refresh=True)
                deadline = time.time() + args.refresh
                while time.time() < deadline and not resized["flag"]:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
