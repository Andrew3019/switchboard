"""M3b — reading another agent's terminal output.

Broker-level, but its own module: it is the one read path that reaches *around* the
message protocol. Everywhere else a parent learns about a child from its summaries
(C4) — here an orchestrator, or the human, looks at what the child's terminal actually
said, because "the child failed and I cannot see why" is otherwise a dead end.

Two sources, in order:

  1. the live pane, via herdr — what is on screen right now;
  2. the on-disk transcript Claude Code already wrote — which survives the pane.

The fallback is the whole point. By the time anyone wants to debug a child, its pane is
often already gone: `sb cleanup` closes finished agents, and closing is deliberately
cheap precisely because the transcript outlives it. A reader that only knew about panes
would answer "nothing here" exactly when it is asked the real question.

Provenance always travels with the text (`Output.source`, `Output.detail`) — reading a
transcript is not the same as reading a live pane, and a debugger who cannot tell the
difference will misread a stale tail as the current state.

There is no `sb output` verb and no `Broker.output`. `status.inspect` calls `read_output`
directly, because "show me the terminal" was never the question anyone actually had — the
question is "what is going on with this agent", and the terminal is one section of that
answer. This module stays separate because it is a different KIND of read (around the
message protocol rather than through it), not because it is a different command.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import config, store
from .herdr import HerdrError

# Where the text came from. Never inferred by the caller — an empty string means the
# same thing from all three, and only `source` says which.
PANE = "pane"
TRANSCRIPT = "transcript"
UNAVAILABLE = "unavailable"

# All three are `[display]` / `[limits]` in defaults/settings.toml, where the reasoning for
# each sits next to the number.
DEFAULT_LINES = config.setting("display.output_lines")
CLIP = config.setting("limits.output_clip")
_RECORD_OVERSCAN = config.setting("display.record_overscan")

# How much of the fallback explanation reaches the event log.
_EVENT_CLIP = config.setting("limits.event_clip")

# `task_arrived`, which reads the end of a transcript to answer whether a task landed.
# The record it is looking for was written seconds ago, so the tail is the whole search
# space; the slack is for the two clocks involved (ours, and the timestamp Claude Code
# stamps its own records with) not agreeing to the second.
_ARRIVAL_RECORDS = 50
_CLOCK_SLOP = 5.0


@dataclass
class Output:
    """Text plus where it came from."""

    agent: str
    source: str              # PANE | TRANSCRIPT | UNAVAILABLE
    text: str = ""
    detail: str = ""         # why we fell back, or why there is nothing
    path: Optional[str] = None

    @property
    def found(self) -> bool:
        return self.source != UNAVAILABLE

    def render(self) -> str:
        """One block, provenance first. What a CLI prints verbatim."""
        head = f"--- {self.agent}: {self.source}"
        if self.path:
            head += f" {self.path}"
        head += " ---"
        note = f"({self.detail})" if self.detail else ""
        body = self.text.rstrip("\n") or note or "(no output)"
        if note and self.text.strip():
            head += f"\n{note}"
        return f"{head}\n{body}"


def read_output(
    db: sqlite3.Connection,
    herdr: Any,
    name: str,
    *,
    lines: int = DEFAULT_LINES,
) -> Output:
    """Recent output from the agent called `name`, live pane first, transcript after.

    Takes a NAME because that is the only handle anything above the adapter has (P0):
    pane ids are not stable across a pane move, and an agent that has been cleaned up has
    no pane at all. The lookup, the fallback, and the reason for it are the tool's job.
    """
    agent = store.get_agent(db, name)
    if agent is None:
        raise KeyError(f"no such agent: {name}")

    why = ""
    if agent["pane_id"]:
        text = ""
        try:
            text = herdr.read_pane(agent["pane_id"], lines=lines)
        except HerdrError as e:
            # The usual cause: the pane was closed. Not an error to propagate — it is
            # exactly the case the transcript exists for.
            why = f"pane {agent['pane_id']} unreadable ({e.code})"
        if text.strip():
            return _done(db, Output(agent=name, source=PANE, text=text), lines)
        why = why or f"pane {agent['pane_id']} is empty"
    else:
        why = "no pane recorded (closed, or never spawned by us)"

    path = store.transcript_path(agent)
    if path is None:
        why += "; no transcript on disk (needs both a session id and a cwd)"
        return _done(db, Output(agent=name, source=UNAVAILABLE, detail=why), lines)

    text = read_transcript(path, lines=lines)
    if not text.strip():
        why += f"; transcript {path} has nothing readable"
        return _done(db, Output(agent=name, source=UNAVAILABLE, detail=why,
                                path=str(path)), lines)
    return _done(db, Output(agent=name, source=TRANSCRIPT, text=text, detail=why,
                            path=str(path)), lines)


def task_arrived(cwd: Optional[str], text: str, *, since: float) -> bool:
    """Has `text` actually been submitted to an agent working in `cwd`?

    The one honest answer to "did the task arrive", and the reason this module is read
    from the spawn path at all. Everything herdr can tell us about a freshly started
    agent is a reading of its terminal — and a Claude Code that is showing its workspace
    trust dialog swallows the prompt whole while its herdr status changes anyway, which
    is precisely how a spawn came to report a name for an agent that never ran
    (`Herdr.deliver`). Claude Code's own transcript is not a reading of anything: the
    submitted text is appended to it, verbatim, about a second after it goes in, and a
    prompt eaten by a dialog leaves no record because it never happened.

    Matched by CONTENT, not by session id, because at delivery time there may be no
    session — a spawn that never took its prompt never started one, and the whole
    directory is empty. `since` keeps a re-send from being confirmed by some older turn
    that happened to carry the same words; files untouched since then are skipped
    unread, which is what keeps this cheap enough to poll.
    """
    d = store.transcript_dir(cwd)
    if d is None or not d.is_dir():
        return False
    needle = text.strip()
    if not needle:
        return False
    floor = since - _CLOCK_SLOP
    for f in sorted(d.glob("*.jsonl")):
        try:
            if f.stat().st_mtime < floor:
                continue
        except OSError:
            continue
        # The tail only: text submitted seconds ago is at the END of the file, and this
        # is polled twice a second against a session that may be hours long.
        for rec in _tail_records(f, _ARRIVAL_RECORDS):
            if rec.get("type") != "user":
                continue
            when = _record_time(rec)
            if when is not None and when < floor:
                continue
            content = (rec.get("message") or {}).get("content")
            if not isinstance(content, str):
                content = json.dumps(content)
            if needle in content:
                return True
    return False


def _record_time(rec: dict) -> Optional[float]:
    """When a transcript record was written, or None if it does not say.

    None is deliberately NOT "too old": the file it came from has already been shown to
    have been written since the text went in, and a record shape that stopped carrying a
    timestamp would otherwise turn every delivery into a failed spawn. Wrong in the
    direction of a duplicate task rather than a lost agent.
    """
    ts = rec.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_transcript(path: Path, *, lines: int = DEFAULT_LINES) -> str:
    """The tail of a Claude Code transcript, flattened to one line per entry.

    Not a pretty-printer: this is read when something has already gone wrong, so tool
    calls and their results are kept (that is usually where the cause is) and the
    agent's thinking is dropped (it never reached the terminal either).
    """
    out: list[str] = []
    for rec in _tail_records(path, lines * _RECORD_OVERSCAN):
        out.extend(_render_record(rec))
    return "\n".join(out[-lines:])


# -- internals -----------------------------------------------------------------


def _done(db: sqlite3.Connection, out: Output, lines: int) -> Output:
    store.log_event(db, kind="read_output", agent=out.agent, source=out.source,
                    lines=lines, detail=out.detail[:_EVENT_CLIP])
    return out


def _tail_records(path: Path, max_records: int) -> list[dict]:
    """Last N parseable JSONL records. Memory stays bounded on a long session."""
    try:
        with path.open(errors="replace") as fh:
            tail = deque(fh, maxlen=max(max_records, 1))
    except OSError:
        return []
    recs = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue          # a torn last line on a live session, not a failure
        if isinstance(rec, dict):
            recs.append(rec)
    return recs


def _render_record(rec: dict) -> list[str]:
    role = rec.get("type") or (rec.get("message") or {}).get("role") or ""
    if role not in ("user", "assistant"):
        return []             # summaries, system meta — noise for this purpose

    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return [f"{role}: {_clip(content)}"] if content.strip() else []
    if not isinstance(content, list):
        return []

    out: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text":
            if part.get("text", "").strip():
                out.append(f"{role}: {_clip(part['text'])}")
        elif kind == "tool_use":
            args = _clip(json.dumps(part.get("input") or {}, default=str))
            out.append(f"{role}: [{part.get('name') or 'tool'}] {args}")
        elif kind == "tool_result":
            # Marked, because an is_error result is the single most useful line in a
            # transcript being read to find out why something failed.
            flag = "error" if part.get("is_error") else "result"
            out.append(f"  [{flag}] {_clip(_text_of(part.get('content')))}")
    return out


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return "" if content is None else str(content)


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= CLIP else flat[:CLIP] + "…"
