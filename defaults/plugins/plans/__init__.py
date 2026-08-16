"""Plans and steps — the live state of one job, held where a lead can show it.

The design is `design/PLANS-AND-STEPS.md`; this is the first slice of it: the state model,
and the three things you can do with a plan before any step can move — make one, look at
one, and read what happened to it. The verbs that change a step (`assign`, `tick`, `skip`,
`note`, `checkpoint`, `dep`, `add-step`) are deliberately not here yet, so what this file
has to get right is the shape everything after it writes into.

The records
-----------

    plan  {"id": "p-1", "workspace": "task-guardrails-build", "title": "…",
           "steps": [...], "changelog": [...], "notes": [...],
           "created_by": "lead", "created_at": 1754570000}

    step  {"id": "s-1", "name": "…", "progress": "open", "owner": null,
           "tries": 1, "notes": [], "deps": [], "checkpoints": []}

`progress` is an OPEN VOCABULARY, exactly as `todo`'s `state` is: `open` is what `create`
writes and `done`/`skipped` are what the lifecycle verbs will, but nothing here is an enum
and a lead that wants `progress: waiting on Andrew` gets it without a release. The design
says the agent is the interpreter and there is no schema to satisfy, so a step carrying a
field this file has never heard of is a feature and not corruption — `_step()` fills in the
fields the design names and leaves everything else alone.

Ids are `p-<n>` and `s-<n>`, monotonic across the whole file and never reused, so a spawn
prompt or a changelog entry citing `s-7` stays true for the life of the repo. Step numbers
are minted from ONE counter rather than one per plan: two plans on a worktree would
otherwise both have an `s-1`, and a lead handing a worker "your step is s-1" would be
saying nothing. `next_plan`/`next_step` are stored, and recomputed as floors on read, so a
hand-deleted row cannot make the next create mint an id somebody already wrote down.

A plan is keyed on the WORKSPACE NAME, which is the branch this checkout is on — the
identity `agents.workspace` uses. It is recovered here with `git rev-parse` rather than read
from the store, because a plugin `Context` deliberately carries no store handle. Nothing
about liveness is stored: whether the workspace still exists, whether anybody is working in
it, and whether a step's owner is alive are all read at display time, by a later PR, and
never copied in here. Two records both claiming to know who is working will disagree.

The changelog
-------------

Append-only, written by the command, carrying the reason the agent supplied. That is the
whole record of how a job actually ran: a plan gets reshaped as it goes, and without this
the file keeps only the final shape. `_write` refuses a document whose changelog is shorter
than the one that was read, or whose existing entries have changed — so a bug in a future
verb that rewrites a plan wholesale fails loudly here instead of quietly losing the story.
It cannot stop somebody editing `plans.json` in an editor; nothing can, and the answer to
that is that every mutation goes through a command.

Storage is one JSON file, rewritten whole via tmp + `os.replace` under the lock sb already
holds around the handler. Whole-file rewrite is correct precisely because of that lock: a
command reads, changes the steps it names, and writes, with nothing able to interleave.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from switchboard.plugins import Result

API = 1
VERSION = "1.0.0"
SCOPE = "repo"
LOCK = True

# The file, and the shape written into it. `format` is this plugin's own; sb neither reads
# it nor has an opinion about it.
FILE = "plans.json"
FORMAT = 1

# What `create` writes into a step it makes. Not an enum — see the module docstring.
OPEN = "open"

# `p-1`, `P-1` and a bare `1` all name the same plan; likewise `s-1` for a step. An id is
# read out of a board or a spawn prompt and retyped, and being strict buys nothing.
_PLAN_ID = re.compile(r"^(?:p-)?(\d+)$", re.IGNORECASE)
_STEP_ID = re.compile(r"^(?:s-)?(\d+)$", re.IGNORECASE)

# Long enough for a real sentence, short enough that a plan stays readable when it is shown.
# Anything longer wants a brief, and briefs are files a checkpoint can point at.
MAX_TEXT = 500


def register(reg):
    reg.command(
        "create", create, audience="both",
        help="start a plan on this worktree, empty or with its steps already in it",
        args=[reg.arg("title", repeat=True, help="what this plan is for"),
              reg.arg("--step", repeat=True, help="a step to start with; repeat for more"),
              reg.arg("--note", repeat=True, help="a note on the plan; repeat for more"),
              reg.arg("--reason", help="why, for the changelog")])
    reg.command(
        "list", ls, audience="both", help="the plans on this worktree",
        args=[reg.arg("--all", flag=True, help="every plan, on every workspace")])
    reg.command(
        "show", show, audience="both", help="one plan in full — steps, deps, changelog",
        args=[reg.arg("id", help="a plan id, e.g. p-1")])
    reg.command(
        "changelog", changelog, audience="both", help="what has been done to one plan",
        args=[reg.arg("id", help="a plan id, e.g. p-1")])


# -- the handlers --------------------------------------------------------------


def create(ctx, args) -> Result:
    """A plan on this worktree, with as many of its steps as are known already.

    Both halves matter: a plan may be defined upfront, which the design says is the point
    rather than overhead, and a lead that has not shaped the work yet still gets somewhere
    to put it. Neither is the special case.
    """
    title = " ".join(str(w) for w in (args.title or ())).strip()
    steps = [str(s).strip() for s in (args.step or ()) if str(s).strip()]
    notes = [str(n).strip() for n in (args.note or ()) if str(n).strip()]
    for text in [title, *steps, *notes]:
        if len(text) > MAX_TEXT:
            return Result(ok=False, human=f"that is {len(text)} characters; a plan's text "
                                          f"is at most {MAX_TEXT}. Write the long version "
                                          f"somewhere a checkpoint can point at.")

    doc, seal = _read(ctx.state_dir)
    who = ctx.agent or "human"
    plan = {"id": f"p-{doc['next_plan']}", "workspace": _workspace(ctx), "title": title,
            "steps": [], "changelog": [], "notes": [_note(n, who) for n in notes],
            "created_by": who, "created_at": int(time.time())}
    doc["next_plan"] += 1
    for name in steps:
        plan["steps"].append(_step(f"s-{doc['next_step']}", name))
        doc["next_step"] += 1

    made = ", ".join(s["id"] for s in plan["steps"])
    _log(plan, who, "create", args.reason,
         f"{_count(plan['steps'])} ({made})" if made else "empty")
    doc["plans"].append(plan)
    _write(ctx.state_dir, doc, seal)
    return Result(human=_full(plan), data=plan)


def ls(ctx, args) -> Result:
    """This worktree's plans, because that is the only set anybody standing here is in.

    A plan belongs to one worktree and from inside it the others are invisible; `--all` is
    for a human looking across the repo, not for a lead deciding what to do next.
    """
    plans = _read(ctx.state_dir)[0]["plans"]
    here = _workspace(ctx)
    if not args.all:
        plans = [p for p in plans if p.get("workspace") == here]
    if not plans:
        return Result(human="(no plans on this worktree)" if not args.all
                            else "(no plans in this repo)", data=[])
    return Result(human="\n".join(_line(p, workspace=args.all) for p in plans), data=plans)


def show(ctx, args) -> Result:
    doc, _ = _read(ctx.state_dir)
    plan = _find(doc, args.id)
    if plan is None:
        return Result(ok=False, human=_no_such(doc, args.id))
    return Result(human=_full(plan), data=plan)


def changelog(ctx, args) -> Result:
    """The changelog alone, for reading a finished job cold without the current shape."""
    doc, _ = _read(ctx.state_dir)
    plan = _find(doc, args.id)
    if plan is None:
        return Result(ok=False, human=_no_such(doc, args.id))
    entries = plan.get("changelog") or []
    if not entries:
        return Result(human=f"({plan['id']} has no changelog — which should be impossible)",
                      data=entries)
    return Result(human="\n".join(_entry(e) for e in entries), data=entries)


# -- the records ---------------------------------------------------------------


def _step(sid: str, name: str) -> dict:
    """One step, with every field the design names it carries and nothing more.

    `tries` starts at 1 rather than 0: a step being worked is on its first try, and a count
    above one is what renders. `deps` are the ids this step comes after — fan-out and join
    are edges the lead reads, never control flow anything executes.
    """
    return {"id": sid, "name": name, "progress": OPEN, "owner": None, "tries": 1,
            "notes": [], "deps": [], "checkpoints": []}


def _note(text: str, who: str) -> dict:
    return {"text": text, "by": who, "at": int(time.time())}


def _log(plan: dict, who: str, action: str, reason: Optional[str], detail: str = "") -> None:
    """Append one changelog entry. The only way anything is ever added to a changelog.

    Every mutating command calls this, which is why it takes the reason as an argument
    rather than reading it off `args`: a verb that forgets to pass one is visible here as a
    `None` in the record, and a verb that forgets to call this at all is a diff nobody can
    miss.
    """
    plan.setdefault("changelog", []).append(
        {"at": int(time.time()), "by": who, "action": action,
         "reason": (reason or "").strip() or None, "detail": detail or None})


# -- the file ------------------------------------------------------------------


def _read(d: Path) -> tuple[dict, dict]:
    """The whole file and its seal — the changelogs as they were, for `_write` to check.

    Never raises for a file that is not there yet. The two counters are recomputed as
    floors over every id present, so a hand-edited file that lost one still cannot mint an
    id that has already been written down somewhere else.

    A file that is there and unreadable is a REFUSAL, naming the path, rather than a fresh
    empty document: starting over would silently replace every plan in the repo on the next
    `create`, and the records are the whole point of keeping them. The failing verb stops,
    nothing is written, and a human fixes or moves the file.
    """
    f = d / FILE
    if f.exists():
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"{f} is not readable JSON ({e}); nothing here will overwrite "
                             f"it. Fix it or move it aside.") from e
        if not isinstance(doc, dict) or not isinstance(doc.get("plans", []), list):
            raise ValueError(f"{f} is not a plans file — a JSON object with a 'plans' "
                             f"list. Nothing here will overwrite it.")
    else:
        doc = {"format": FORMAT, "next_plan": 1, "next_step": 1, "plans": []}
    doc.setdefault("format", FORMAT)
    doc.setdefault("plans", [])
    plans = doc["plans"]
    doc["next_plan"] = max(_counter(doc.get("next_plan")),
                           _high(_PLAN_ID, (p.get("id") for p in plans)) + 1)
    doc["next_step"] = max(_counter(doc.get("next_step")),
                           _high(_STEP_ID, (s.get("id") for p in plans
                                            for s in (p.get("steps") or ()))) + 1)
    return doc, _seal(doc)


def _counter(given: Any) -> int:
    """A stored counter, or 1 if a hand-edit left something that is not a number there.

    1 is safe because it is a floor and not the answer: `_read` takes the higher of it and
    one past the highest id actually present, so a mangled counter costs nothing and a
    mangled counter that also refused to run would cost the plan.
    """
    try:
        return max(1, int(given))
    except (TypeError, ValueError):
        return 1


def _seal(doc: dict) -> dict:
    """Every plan's changelog as it stands, keyed by plan id. Compared on the way out."""
    return {p.get("id"): json.dumps(p.get("changelog") or [], sort_keys=True)
            for p in doc["plans"]}


def _write(d: Path, doc: dict, seal: dict) -> None:
    """Whole-file rewrite via tmp + `os.replace`, under the lock sb is already holding.

    `os.replace` is atomic within a directory, so a reader sees the old file or the new one
    and never half of one — which matters even though sb serialises the writers, because
    `plans.json` is a plain file somebody may well `cat` while a job is running.

    The append-only check is here, at the single write, rather than trusted to each verb.
    A command changes the steps it names; if one ever rewrites a plan wholesale it will
    take the changelog with it, and that failure is silent everywhere except here.

    Both halves of "append-only" are checked, because dropping the plan is the easier way
    to lose a changelog than editing one: a plan that was read and is not being written
    back has lost every entry it had, and the design says records are kept and never
    erased — cleanup means dropping out of the UI.
    """
    here = {plan.get("id") for plan in doc["plans"]}
    gone = [pid for pid in seal if pid not in here]
    if gone:
        raise ValueError(f"this write would have dropped {', '.join(sorted(gone))} and "
                         f"its changelog; plans are kept, never erased")
    for plan in doc["plans"]:
        was = seal.get(plan.get("id"))
        if was is None:
            continue                    # a plan created by this command; nothing to keep
        old = json.loads(was)
        now = plan.get("changelog") or []
        if now[:len(old)] != old:
            raise ValueError(f"{plan.get('id')}'s changelog is append-only, and this write "
                             f"would have dropped or rewritten {len(old)} entries")
    tmp = d / f".{FILE}.tmp"
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, d / FILE)


def _workspace(ctx) -> str:
    """The name of the workspace this checkout is, which is the branch it is on.

    `broker.py` mints a workspace name and a branch name as one thing ("the workspace name
    IS the branch name"), and `Broker._here()` recovers it exactly this way. A plugin
    handler cannot ask the store — a `Context` carries no store handle, by design — so it
    asks git, which is the same question one layer down.

    A detached HEAD has no name to infer, and falls back to the directory. That is a plan
    filed under something that is not a workspace, which is better than refusing to make
    one: the plan is still the record of the job, and nothing here depends on the name
    resolving to a live workspace.
    """
    try:
        out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=str(ctx.worktree), capture_output=True, text=True)
    except OSError:
        return ctx.worktree.name        # no git on the path; still not a reason to refuse
    branch = (out.stdout or "").strip()
    return branch if out.returncode == 0 and branch and branch != "HEAD" \
        else ctx.worktree.name


# -- rendering and lookup ------------------------------------------------------


def _find(doc: dict, given: str) -> Optional[dict]:
    n = _num(_PLAN_ID, given)
    return next((p for p in doc["plans"] if _num(_PLAN_ID, p.get("id")) == n), None) \
        if n else None


def _num(pattern: re.Pattern, given: Any) -> Optional[int]:
    m = pattern.match(str(given or "").strip())
    return int(m.group(1)) if m else None


def _high(pattern: re.Pattern, ids) -> int:
    return max((n for n in (_num(pattern, i) for i in ids) if n), default=0)


def _count(steps: list) -> str:
    return "empty" if not steps else f"{len(steps)} step{'s' if len(steps) > 1 else ''}"


def _line(p: dict, *, workspace: bool) -> str:
    where = f"{p.get('workspace', '—'):<24}" if workspace else ""
    return (f"{p['id']:<6}{_count(p.get('steps') or []):<10}{where}"
            f"{p.get('title') or '(untitled)'}")


def _full(p: dict) -> str:
    """A plan as a lead reads it: what it is, its steps and their edges, then the story."""
    lines = [f"{p['id']}  {p.get('title') or '(untitled)'}",
             f"  workspace   {p.get('workspace') or '—'}",
             f"  created     {_when(p.get('created_at'))} by {p.get('created_by') or '—'}"]
    steps = p.get("steps") or []
    lines.append("")
    lines.extend([f"  {s}" for s in (_step_lines(steps) or ["(no steps yet)"])])
    if p.get("notes"):
        lines.append("")
        lines.append("  notes")
        lines.extend(f"    {n.get('text')}  ({n.get('by')}, {_when(n.get('at'))})"
                     for n in p["notes"])
    lines.append("")
    lines.append("  changelog")
    lines.extend(f"    {_entry(e)}" for e in (p.get("changelog") or ()))
    return "\n".join(lines)


def _step_lines(steps: list) -> list[str]:
    out = []
    for s in steps:
        bits = [f"{s.get('id', '?'):<6}{s.get('progress', '?'):<10}{s.get('name', '')}"]
        if s.get("owner"):
            bits.append(f"({s['owner']})")
        if s.get("deps"):
            # Edges the lead interprets: what this one waits for, never a wait anything runs.
            bits.append(f"after {', '.join(s['deps'])}")
        if (s.get("tries") or 1) > 1:
            bits.append(f"try {s['tries']}")
        if s.get("checkpoints"):
            bits.append(f"[{len(s['checkpoints'])} checkpoints]")
        out.append("  ".join(bits))
    return out


def _entry(e: dict) -> str:
    bits = [_when(e.get("at")), str(e.get("by") or "—"), str(e.get("action") or "—")]
    line = "  ".join(bits)
    if e.get("detail"):
        line += f"  {e['detail']}"
    # The reason last and set off, because it is the part written for somebody reading the
    # job cold months later, and the only part no command could have supplied for itself.
    return line + (f"  — {e['reason']}" if e.get("reason") else "")


def _when(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def _no_such(doc: dict, given: str) -> str:
    if _num(_PLAN_ID, given) is None:
        return f"'{given}' is not a plan id — they look like p-1"
    # Named rather than merely denied: ids are never reused, so "there is no p-9 yet" and
    # "p-9 was there and is gone" are different things, and only the first can happen.
    high = _high(_PLAN_ID, (p.get("id") for p in doc["plans"]))
    return (f"no plan {given} — none has been made yet" if not high
            else f"no plan {given} — the highest is p-{high}")
