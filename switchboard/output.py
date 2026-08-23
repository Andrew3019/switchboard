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

    WHICH records count is `_submitted_text`, and it is not only the `user` one: a busy
    agent's queue record is written minutes before the turn boundary that produces a `user`
    record, and waiting for the latter is the difference between "not yet" and "no".
    """
    # `any` short-circuits on the first match, so this still stops reading at the first
    # file that answers the question — the cost that makes it pollable.
    return any(_transcripts_with(cwd, text, since=since))


def submitted_since(path: Optional[Path], text: str, *, since: float) -> bool:
    """`task_arrived`'s question, narrowed to ONE session file.

    The proof `Broker._confirm_rings` uses on a doorbell it already rang. By then the
    target has a session id, so the whole directory is the wrong place to look: `delegate`
    puts a parent and all its children in one cwd, so several live transcripts sit in that
    bucket and a sibling's turn would confirm our doorbell. `task_arrived` scans the
    directory because at SPAWN time there is no session id to narrow it with — a spawn that
    never took its prompt never started one — and that is the only reason it does.

    `None` is not a proof of anything: an agent with no session id yet, or whose transcript
    file is not on disk, is one we cannot see, and the caller must not read that as "it
    never arrived" (see `_confirm_rings`).
    """
    if path is None:
        return False
    return _carries(path, text.strip(), since - _CLOCK_SLOP)


def matched_transcript(cwd: Optional[str], text: str, *, since: float) -> Optional[str]:
    """WHICH transcript `text` landed in — the session id of the agent that took it.

    The same scan `task_arrived` makes, keeping the answer instead of throwing it away.
    A freshly spawned agent's `session_id` is otherwise written by nothing until the
    agent itself runs an `sb` command (`Broker._claim_session`), and an agent that is
    killed, interrupted or superseded before it ever does is unrecoverable for its whole
    life — `sb restore` has no session to restore. Two agents were permanently lost that
    way on 2026-08-16. Reading it here, from the delivery proof, closes the window
    before the agent has run anything.

    Content, not time, is what makes this sound: `delegate` shares one cwd between a
    parent and all its children, so the same transcript directory holds several live
    sessions at once and "the file that changed most recently" is a guess. The task text
    is the agent's own, and only its transcript carries it.

    None on ambiguity as well as on no match: if two files in the window both carry the
    text (two spawns seconds apart with textually identical first tasks — the empty
    `spawn.start_task` placeholder makes that reachable), there is no way to tell which
    is ours, and a wrong session id on the row is worse than none. An empty column is a
    known gap; a wrong one sends `sb restore` into a stranger's session.
    """
    seen: list[str] = []
    for sid in _transcripts_with(cwd, text, since=since):
        seen.append(sid)
        if len(seen) > 1:
            return None
    return seen[0] if seen else None


def _transcripts_with(cwd: Optional[str], text: str, *, since: float):
    """Session ids of the transcripts in `cwd` that carry `text`, written since `since`.

    A generator, so a caller that only needs to know THAT one exists stops at the first
    and a caller that needs to know it is the ONLY one keeps going. The scan itself is
    the one `task_arrived` has always made.
    """
    d = store.transcript_dir(cwd)
    if d is None or not d.is_dir():
        return
    needle = text.strip()
    if not needle:
        return
    floor = since - _CLOCK_SLOP
    for f in sorted(d.glob("*.jsonl")):
        if _carries(f, needle, floor):
            # The file's stem IS the session id: Claude Code names each transcript for the
            # session that wrote it, which is the same identifier `store.transcript_path`
            # turns back into a path.
            yield f.stem


def _carries(path: Path, needle: str, floor: float) -> bool:
    """Does this one transcript record `needle` being submitted, at or after `floor`?

    The whole of the proof, in one file. Both callers are polling — `Herdr.deliver` twice a
    second against a session that may be hours long — so a file untouched since the send is
    skipped unread, and only the tail of the rest is parsed: text submitted seconds ago is
    at the END.
    """
    if not needle:
        return False
    try:
        if path.stat().st_mtime < floor:
            return False
    except OSError:
        return False
    for rec in _tail_records(path, _ARRIVAL_RECORDS):
        content = _submitted_text(rec)
        if content is None:
            continue
        when = _record_time(rec)
        if when is not None and when < floor:
            continue
        if needle in content:
            return True
    return False


def _submitted_text(rec: dict) -> Optional[str]:
    """What this record says was PUT TO the agent, or None if it says nothing.

    Two record shapes, because Claude Code writes a different one depending on what the
    agent was doing when the text was submitted, and reading only the first is what made a
    correct delivery to a busy agent unprovable:

      - **idle** — a `user` record, written when the turn starts. The only evidence there
        is; no queue record is written at all.
      - **busy** — a `queue-operation`/`enqueue` record, written at SUBMIT time, carrying
        the text as a plain top-level `content`. The `user`-side record for it does not
        appear until the turn ends and the queue drains: measured at 2.29 s for the enqueue
        record against **3 min 09 s** for the `user` one, on the same send.

    So a `user`-only predicate answers "no" for three minutes about a doorbell that landed
    in three seconds — which is why `sb tell --interrupt` could raise `Undeliverable` for an
    interrupt the agent had already queued, and why a confirmation pass built on it would
    re-send every correct delivery.

    Only `enqueue`. The sibling `queue-operation`/`remove` record carries the same text on
    its way OUT of the queue, and a cancelled prompt is not an arrived one.
    """
    kind = rec.get("type")
    if kind == "user":
        content = (rec.get("message") or {}).get("content")
    elif kind == "queue-operation" and rec.get("operation") == "enqueue":
        content = rec.get("content")
    else:
        return None
    return content if isinstance(content, str) else json.dumps(content)


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
    """The tail of a transcript, flattened to one line per entry.

    Not a pretty-printer: this is read when something has already gone wrong, so tool
    calls and their results are kept (that is usually where the cause is) and the
    agent's thinking is dropped (it never reached the terminal either).

    Two record shapes, told apart per RECORD rather than per file. Codex's rollout JSONL
    is a different format from Claude Code's transcript — an outer `{timestamp, type,
    payload}` envelope around `event_msg`/`response_item`/`session_meta` — and the two
    vocabularies do not overlap, so `_render_codex_record` answers for the records it
    recognises and `_render_record` for the rest. Per record and not per file because
    that needs nothing to be known about the agent at this depth: the caller already
    resolved which file to read (`store.transcript_path`), and a renderer that also had
    to be told which provider wrote it would be a second place to get that wrong.
    """
    out: list[str] = []
    for rec in _tail_records(path, lines * _RECORD_OVERSCAN):
        out.extend(_render_codex_record(rec) if rec.get("type") in _CODEX_RECORDS
                   else _render_record(rec))
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


# The outer `type` values a codex rollout record can carry. Named rather than inferred so
# that a Claude Code record can never fall into the codex renderer by accident: the two
# formats share no value here (`user`/`assistant`/`queue-operation` against these).
_CODEX_RECORDS = frozenset({"event_msg", "response_item", "session_meta",
                            "turn_context", "world_state", "compacted"})


def _render_codex_record(rec: dict) -> list[str]:
    """One codex rollout record, in the same one-line-per-entry shape as the Claude one.

    Read off `event_msg` rather than off `response_item`, wherever both carry the same
    thing. Codex writes each turn twice — once as the event stream that drove the TUI and
    once as the raw model items — and the events are the half that says what a person
    watching the pane actually saw, which is what this read is for.

    Verified against a real rollout: `user_message`, `agent_message`, `task_started`,
    `task_complete` and `token_count` events, plus `response_item` function calls and
    their outputs. Reasoning is dropped for the Claude path's reason — it never reached
    the terminal either.
    """
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return []
    kind = payload.get("type")
    if rec.get("type") == "event_msg":
        if kind == "user_message":
            text = payload.get("message") or ""
            return [f"user: {_clip(text)}"] if text.strip() else []
        if kind == "agent_message":
            text = payload.get("message") or ""
            return [f"assistant: {_clip(text)}"] if text.strip() else []
        if kind == "error":
            return [f"  [error] {_clip(str(payload.get('message') or ''))}"]
        return []
    if rec.get("type") != "response_item":
        return []
    if kind in ("function_call", "local_shell_call", "custom_tool_call"):
        name = payload.get("name") or "tool"
        args = payload.get("arguments")
        if args is None:
            args = payload.get("action") or payload.get("input") or {}
        return [f"assistant: [{name}] "
                f"{_clip(args if isinstance(args, str) else json.dumps(args, default=str))}"]
    if kind in ("function_call_output", "local_shell_call_output",
                "custom_tool_call_output"):
        out = payload.get("output")
        # Codex stringifies a tool result as JSON carrying the real text; if it does not
        # parse, it is already the text.
        if isinstance(out, str):
            try:
                parsed = json.loads(out)
                out = parsed.get("output", out) if isinstance(parsed, dict) else out
            except json.JSONDecodeError:
                pass
        return [f"  [result] {_clip(_text_of(out))}"]
    return []


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # `text` is Claude Code's part key; `input_text`/`output_text` carrying `text` is
        # codex's. Both are read here rather than in two near-identical helpers.
        return " ".join(
            p.get("text", "") for p in content
            if isinstance(p, dict)
            and p.get("type") in ("text", "input_text", "output_text")
        )
    return "" if content is None else str(content)


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= CLIP else flat[:CLIP] + "…"
