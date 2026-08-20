"""One todo list per repo, shared across every worktree.

Deliberately dumb, and the list of things it is not is longer than the list of things it
is. There is no `claim`, no `release`, no `owner` and no assignment, because that turns a
store into a work queue and a work queue into a scheduler — an orchestrator reading the
list and delegating is an orchestrator doing its job, not a feature of this plugin. There
is nothing reserved for `sb status` either: a hook nothing calls is worse than no hook.

`created_by` is provenance — who filed it — and it is not an assignment. Nothing here says
who should do the work, because nothing here is entitled to.

The record
----------

    {"id": "t-7", "text": "…", "labels": ["config"], "state": "open",
     "created_by": "orchestrator", "created_at": 1754570000,
     "closed_at": null, "note": null}

`state` is an OPEN VOCABULARY, not a closed enum. `open`, `done` and `dropped` are what
this plugin's own verbs write; `--state blocked` works the day somebody wants it, with no
edit to sb and no release. `--state` therefore declares no `choices` — the named failure
this is avoiding is a shipped system whose role vocabulary became a Go enum and whose every
add-one request was closed unimplemented.

Ids are `t-<n>`, monotonic, and never reused, so a commit message citing `t-7` stays true
for the life of the repo. That is why `next_id` is a stored field rather than `max(id)+1`:
a human who deletes a row by hand must not cause the next `add` to mint an id somebody has
already written down.

`drop` marks `state: "dropped"` rather than deleting the row, for the same reason. The
alternative would make `t-7` cite nothing, and would make `dropped` — a state value §9.2 of
the design names as shipped — a word that never appears anywhere.

Storage is one JSON file, rewritten whole via tmp + `os.replace` under the lock sb already
holds around the handler. That is correct because sb owns the lock, and it is the simplest
thing that works; the lost-write race between two concurrent `add`s is the entire reason
somebody would otherwise reach for sqlite here.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from switchboard.plugins import Result

API = 1
VERSION = "1.0.0"
SCOPE = "repo"
LOCK = True

# The file, and the shape written into it. `format` is this plugin's own, versioned by
# `VERSION` and migrated by this plugin if it ever needs to be — sb neither reads it nor
# has an opinion about it.
FILE = "todos.json"
FORMAT = 1

# What the two closing verbs write. Not an enum and not enforced anywhere: these are the
# words this plugin happens to use, and `--state` accepts any other.
OPEN, DONE, DROPPED = "open", "done", "dropped"

# `t-7`, `T-7` and a bare `7` all name the same row. A human reads ids out of a commit
# message and retypes them, and being strict about the prefix buys nothing.
_ID = re.compile(r"^(?:t-)?(\d+)$", re.IGNORECASE)

# A label is a word you can grep for and pass on a command line without quoting.
_LABEL = re.compile(r"^[a-z0-9][a-z0-9._/-]*$", re.IGNORECASE)

# Long enough for a real sentence, short enough that the list stays a list. A todo that
# needs more than this wants a brief, and briefs are files.
MAX_TEXT = 500


def register(reg):
    reg.command(
        "add", add, audience="both", help="add a todo",
        args=[reg.arg("text", help="what needs doing"),
              reg.arg("--label", repeat=True, help="a label; repeat for more"),
              reg.arg("--state", help="the state to file it in (default: open)")])
    reg.command(
        "list", ls, audience="both", help="list todos (open ones by default)",
        args=[reg.arg("--state", help="exactly this state — open, done, dropped, "
                                      "or any word you have used"),
              reg.arg("--label", repeat=True, help="only todos carrying every label given"),
              reg.arg("--all", flag=True, help="include closed todos")])
    reg.command(
        "show", show, audience="both", help="one todo in full",
        args=[reg.arg("id", help="a todo id, e.g. t-7")])
    reg.command(
        "done", done, audience="both", help="close a todo as finished",
        args=[reg.arg("id", help="a todo id, e.g. t-7"),
              reg.arg("--note", help="what happened")])
    # Agents too. `drop` was the human's on the reasoning that *not going to happen* is a
    # call about the work rather than about the row — but an agent that files a todo by
    # mistake could then not withdraw it, and `done` would be a lie about what happened.
    # Nothing is lost either way: this marks `state: "dropped"` and keeps the row, so the
    # id still cites something and the changelog still says who closed it and why.
    reg.command(
        "drop", drop, audience="both", help="close a todo as not-going-to-happen",
        args=[reg.arg("id", help="a todo id, e.g. t-7"),
              reg.arg("--note", help="why")])


# -- the handlers --------------------------------------------------------------


def add(ctx, args) -> Result:
    text = (args.text or "").strip()
    if not text:
        return Result(ok=False, human="a todo needs some text")
    if len(text) > MAX_TEXT:
        return Result(ok=False, human=f"that is {len(text)} characters; "
                                      f"a todo is at most {MAX_TEXT}. Write the long "
                                      f"version somewhere a todo can point at.")
    labels, bad = _labels(args.label)
    if bad:
        return Result(ok=False, human=f"'{bad}' is not a usable label — letters, digits, "
                                      f"and . _ - /")
    state = (args.state or OPEN).strip() or OPEN

    doc = _read(ctx.state_dir)
    row = {"id": f"t-{doc['next_id']}", "text": text, "labels": labels, "state": state,
           # Provenance, not assignment. A human typing at a terminal has no agent row and
           # is recorded as one, rather than as the absence of one.
           "created_by": ctx.agent or "human", "created_at": int(time.time()),
           "closed_at": None, "note": None}
    doc["next_id"] += 1
    doc["todos"].append(row)
    _write(ctx.state_dir, doc)
    return Result(human=f"{row['id']}  {text}", data=row)


def ls(ctx, args) -> Result:
    rows = _read(ctx.state_dir)["todos"]
    if args.state:
        # An exact state, over everything. This is the escape hatch for any word this
        # plugin has never heard of, including the two it writes itself.
        rows = [r for r in rows if r.get("state") == args.state]
    elif not args.all:
        # The default filter is STRUCTURAL, not a word: a todo is listed unless something
        # closed it. `--state blocked` therefore shows up in a bare `list` without
        # `blocked` having to be known to anybody, which is the whole point of an open
        # vocabulary.
        rows = [r for r in rows if not r.get("closed_at")]
    want, bad = _labels(args.label)
    if bad:
        return Result(ok=False, human=f"'{bad}' is not a usable label")
    if want:
        rows = [r for r in rows if set(want) <= set(r.get("labels") or ())]

    if not rows:
        return Result(human=_nothing(args), data=[])
    return Result(human="\n".join(_line(r) for r in rows), data=rows)


def show(ctx, args) -> Result:
    doc = _read(ctx.state_dir)
    row = _find(doc, args.id)
    if row is None:
        return Result(ok=False, human=_no_such(doc, args.id))
    return Result(human=_full(row), data=row)


def done(ctx, args) -> Result:
    return _close(ctx, args, DONE)


def drop(ctx, args) -> Result:
    return _close(ctx, args, DROPPED)


def _close(ctx, args, state: str) -> Result:
    doc = _read(ctx.state_dir)
    row = _find(doc, args.id)
    if row is None:
        return Result(ok=False, human=_no_such(doc, args.id))
    if row.get("closed_at"):
        # Not an error: re-closing something already closed is a no-op with a different
        # word on it, and re-stamping the time would lose when it actually happened.
        return Result(ok=False,
                      human=f"{row['id']} is already {row.get('state')} — "
                            f"closed {_when(row['closed_at'])}", data=row)
    row["state"] = state
    row["closed_at"] = int(time.time())
    row["note"] = (args.note or "").strip() or None
    _write(ctx.state_dir, doc)
    return Result(human=f"{row['id']}  {state}  {row['text']}", data=row)


# -- the file ------------------------------------------------------------------


def _read(d: Path) -> dict:
    """The whole file, or an empty one. Never raises for a file that is not there yet."""
    p = d / FILE
    if not p.exists():
        return {"format": FORMAT, "next_id": 1, "todos": []}
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.setdefault("format", FORMAT)
    doc.setdefault("todos", [])
    # Recomputed as a floor rather than trusted outright, so a hand-edited file that lost
    # its counter still cannot mint an id somebody already wrote in a commit message.
    high = max((n for n in (_num(r.get("id")) for r in doc["todos"]) if n), default=0)
    doc["next_id"] = max(int(doc.get("next_id") or 1), high + 1)
    return doc


def _write(d: Path, doc: dict) -> None:
    """Whole-file rewrite via tmp + `os.replace`, under the lock sb is already holding.

    `os.replace` is atomic within a directory, so a reader either sees the old file or the
    new one and never a half-written one — which matters even though sb serialises the
    writers, because `todos.json` is a plain file somebody may well `cat` mid-run.
    """
    tmp = d / f".{FILE}.tmp"
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, d / FILE)


# -- rendering and lookup ------------------------------------------------------


def _find(doc: dict, given: str) -> Optional[dict]:
    n = _num(given)
    return next((r for r in doc["todos"] if _num(r.get("id")) == n), None) if n else None


def _num(given: Any) -> Optional[int]:
    m = _ID.match(str(given or "").strip())
    return int(m.group(1)) if m else None


def _labels(given) -> tuple[list[str], Optional[str]]:
    """The labels, de-duplicated in the order given, plus the first unusable one."""
    out: list[str] = []
    for raw in given or ():
        label = str(raw).strip()
        if not _LABEL.match(label):
            return out, label or "(empty)"
        if label not in out:
            out.append(label)
    return out, None


def _line(r: dict) -> str:
    labels = " ".join(f"[{x}]" for x in (r.get("labels") or ()))
    return f"{r['id']:<6}{r.get('state', ''):<10}{(labels + ' ') if labels else ''}{r['text']}"


def _full(r: dict) -> str:
    lines = [f"{r['id']}  {r['text']}",
             f"  state       {r.get('state')}",
             f"  labels      {', '.join(r.get('labels') or ()) or '—'}",
             f"  filed by    {r.get('created_by')} ({_when(r.get('created_at'))})"]
    if r.get("closed_at"):
        lines.append(f"  closed      {_when(r['closed_at'])}")
    if r.get("note"):
        lines.append(f"  note        {r['note']}")
    return "\n".join(lines)


def _when(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def _no_such(doc: dict, given: str) -> str:
    if _num(given) is None:
        return f"'{given}' is not a todo id — they look like t-7"
    # Named rather than merely denied: ids are never reused, so "there is no t-9 yet" and
    # "t-9 was there and is gone" are different things, and only the first can happen.
    high = max((n for n in (_num(r.get("id")) for r in doc["todos"]) if n), default=0)
    return (f"no todo {given} — nothing has been filed yet" if not high
            else f"no todo {given} — the highest is t-{high}")


def _nothing(args) -> str:
    if args.state:
        return f"(nothing in state '{args.state}')"
    if args.label:
        return f"(nothing labelled {', '.join(args.label)})"
    return "(no open todos)" if not args.all else "(nothing filed)"
