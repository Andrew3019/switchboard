"""File a bug against switchboard itself, as one markdown file per report.

No index, no database, no dedup and no locking. Two agents filing at the same moment write
two different files and never meet. The same bug filed three times is three files, and
three files is itself the reproduction signal — not designing dedup is the whole point,
because a bug filed twice is evidence and a dedup table is a thing to maintain.

`list` is a directory listing. `show` is `cat`. Anything that can read markdown can read
the whole store, which is the property that survives sb being uninstalled.

User scope, not repo
--------------------

A bug in switchboard is a fact about switchboard, not about whichever repo you were
standing in when you hit it. Repo-scoped, you would file three bugs in three repos and find
none of them again. The repo and the worktree are still recorded IN the file — the context
is useful, the partitioning is not.

What is captured, and what deliberately is not
----------------------------------------------

Captured because it is cheap and deterministic: sb's own version via `git describe
--always --dirty` of sb's checkout (`--dirty` matters — most reports will be against
uncommitted work), herdr's version, python, platform, the repo and worktree the bug was hit
in, and the calling agent. Everything narrative comes from the caller, because only the
caller knows it.

Also captured, and this reverses an earlier decision: the last few lines of the filing
agent's session. The old rule was that NOTHING of the transcript went in, on the grounds
that a Claude Code transcript contains everything the agent read and hoovering it into a
report is a data-exfiltration shape even with no publishing step. That reasoning is still
right about the WHOLE transcript and wrong about a tail. A report that says "sb cleanup did
nothing" is an assertion; the same report with the last twenty lines of the pane attached
is evidence, and the difference is most of what makes a report worth filing.

So: a bounded tail, `TAIL_LINES` long, and never more. Not the whole transcript, not
configurable upward from an agent's own argument, and skipped entirely when a human filed
the report (there is no session to tail) or when the tail cannot be read. Everything the
old reasoning protects against needs the word "everything" to be true, and here it is not.

It is fetched by running `sb inspect --json` as a subprocess, for the same reason the
version strings are: a plugin gets no store handle and no broker, so the CLI is the only
door it has. Failure is silent and the section is simply absent — a bug report must never
fail because the thing it is reporting on is broken, which is exactly the likely case.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import switchboard.plugins as sb_plugins
from switchboard.plugins import Result

API = 1
VERSION = "1.0.0"
SCOPE = "user"
# Append-only, one file per report, and the filenames cannot collide (see `_create`). There
# is nothing for a lock to protect, so sb is told not to take one.
LOCK = False

# `2026-08-07-143022-cannot-spawn.md`. Sorts chronologically as a string, reads as a date,
# and carries enough of the summary that `ls` is already a useful index.
STAMP = "%Y-%m-%d-%H%M%S"
SLUG_MAX = 40

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Long enough for a real summary line, short enough to stay a summary. The detail goes in
# --expected/--actual, which have no such limit worth enforcing.
MAX_SUMMARY = 200

# How long to wait on a subprocess asked for a version string. Anything slower than this is
# broken, and a bug report is the worst possible moment to hang.
TIMEOUT = 5

# Lines of the filing agent's session kept with the report. Deliberately small: enough to
# see what happened immediately before the bug, nowhere near enough to be a transcript. The
# agent cannot raise it — the cap is the whole safeguard, so it is not an argument.
TAIL_LINES = 20


def register(reg):
    reg.command(
        "file", file_, audience="both", help="file a bug against switchboard",
        args=[reg.arg("what", help="one line: what broke"),
              reg.arg("--command", help="the exact command you ran"),
              reg.arg("--expected", help="what you expected to happen"),
              reg.arg("--actual", help="what happened instead, with the exact error text")])
    reg.command(
        "list", ls, audience="both", help="every report filed on this machine")
    reg.command(
        "show", show, audience="both", help="one report in full",
        args=[reg.arg("id", help="a report id, or enough of one to be unambiguous")])
    # `both`, unlike `todo drop` next door, which stays the human's. An agent that files a
    # report is the one that knows a minute later it filed the wrong thing, and making it
    # `sb block` for a deletion spends a human interrupt on tidying. The cost is real and
    # is not undone by the audience: this `drop` unlinks the file, so a report an agent
    # deletes is gone, and duplicate reports are the reproduction signal (see above).
    reg.command(
        "drop", drop, audience="both", help="delete a report outright",
        args=[reg.arg("id", help="a report id")])


# -- the handlers --------------------------------------------------------------


def file_(ctx, args) -> Result:
    what = (args.what or "").strip()
    if not what:
        return Result(ok=False, human="a bug report needs one line saying what broke")
    if len(what) > MAX_SUMMARY:
        return Result(ok=False, human=f"that summary is {len(what)} characters; keep it to "
                                      f"{MAX_SUMMARY} and put the detail in --actual")

    now = time.localtime()
    path = _create(ctx.state_dir, time.strftime(STAMP, now), _slug(what))
    body = _render(ctx, args, what, now)
    path.write_text(body, encoding="utf-8")
    return Result(human=f"filed {path.stem}\n  {path}",
                  data={"id": path.stem, "path": str(path), "what": what})


def ls(ctx, args) -> Result:
    """Every report on this machine, newest first, whatever repo it came from.

    Not filtered to this repo, and there is no flag to filter it: filing three bugs in
    three repos and finding none of them again is the exact failure user scope exists to
    prevent, and a repo-shaped default view would put it straight back. The repo each one
    came from is on the row.
    """
    reports = _reports(ctx.state_dir)
    if not reports:
        return Result(human="(no bug reports)", data=[])
    return Result(human="\n".join(f"{p.stem}  {m.get('what', '')}" for p, m in reports),
                  data=[{"id": p.stem, "path": str(p), **m} for p, m in reports])


def show(ctx, args) -> Result:
    p, err = _resolve(ctx.state_dir, args.id)
    if p is None:
        return Result(ok=False, human=err)
    return Result(human=p.read_text(encoding="utf-8").rstrip(),
                  data={"id": p.stem, "path": str(p),
                        "text": p.read_text(encoding="utf-8")})


def drop(ctx, args) -> Result:
    p, err = _resolve(ctx.state_dir, args.id)
    if p is None:
        return Result(ok=False, human=err)
    p.unlink()
    return Result(human=f"deleted {p.stem}", data={"id": p.stem, "path": str(p)})


# -- files ---------------------------------------------------------------------


def _create(d: Path, stamp: str, slug: str) -> Path:
    """An empty file nobody else got first.

    There is no lock (§10 says so, and there is nothing to lock), so two agents filing the
    same bug in the same second with the same words would otherwise land on one filename
    and one of the two reports would silently not exist. `O_EXCL` is not dedup and not
    coordination — it is the one line that stops a write from eating another write.
    """
    for n in range(1, 100):
        name = f"{stamp}-{slug}.md" if n == 1 else f"{stamp}-{slug}-{n}.md"
        try:
            os.close(os.open(d / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return d / name
        except FileExistsError:
            continue
    raise RuntimeError(f"cannot find a free filename for {stamp}-{slug}")


def _reports(d: Path) -> list[tuple[Path, dict]]:
    """Every report, newest first, each with the little sb needs to list it.

    The filename sorts chronologically, so `sorted` is the whole index. Each file is opened
    only far enough to recover its summary and the worktree it came from — a bug report is
    a few hundred bytes and there are tens of them, so there is nothing here worth caching.
    """
    return sorted(((p, _head(p)) for p in d.glob("*.md")),
                  key=lambda pair: pair[0].name, reverse=True)


def _head(p: Path) -> dict:
    """The summary line and the worktree, read back out of the markdown that holds them."""
    out: dict = {}
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("# ") and "what" not in out:
                out["what"] = line[2:].strip()
            elif line.startswith("- worktree:"):
                out["worktree"] = line.split(":", 1)[1].strip()
            elif line.startswith("- repo:"):
                out["repo"] = line.split(":", 1)[1].strip()
    except OSError:
        pass
    return out


def _resolve(d: Path, given: str) -> tuple[Optional[Path], str]:
    """A report id, an id with `.md` on it, or an unambiguous prefix of one."""
    given = (given or "").strip()
    for candidate in (d / given, d / f"{given}.md"):
        if candidate.is_file() and candidate.parent == d:
            return candidate, ""
    hits = [p for p, _ in _reports(d) if p.stem.startswith(given)] if given else []
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"no such report: '{given}' — see `sb plugin report-bug list --all`"
    return None, (f"'{given}' matches {len(hits)} reports: "
                  f"{', '.join(p.stem for p in hits[:4])}"
                  f"{' …' if len(hits) > 4 else ''}")


# -- the report ----------------------------------------------------------------


def _render(ctx, args, what: str, now) -> str:
    """The whole file. Markdown, because the only reader that matters is a person."""
    lines = [f"# {what}", ""]
    for label, value in (("command", args.command),
                         ("expected", args.expected),
                         ("actual", args.actual)):
        if (value or "").strip():
            lines += [f"## {label}", "", value.strip(), ""]
    lines += ["## context", "",
              f"- filed: {time.strftime('%Y-%m-%d %H:%M:%S %z', now)}",
              f"- by: {ctx.agent or 'human'}",
              f"- sb: {_sb_version()}",
              f"- herdr: {_herdr_version()}",
              f"- python: {platform.python_version()} ({sys.executable})",
              f"- platform: {platform.platform()}",
              # Recorded, not partitioned on. `repo` is the shared `.git` — the repo
              # identity — and `worktree` is the checkout the caller was standing in, which
              # are different facts and are both worth having in a bug report.
              f"- repo: {ctx.repo}",
              f"- worktree: {ctx.worktree}",
              ""]
    # Last, and fenced. Last because it is the only unbounded-looking part of the file and
    # a reader should reach the facts first; fenced because it is terminal output and
    # markdown would otherwise eat its formatting.
    tail = _session_tail(ctx.agent)
    if tail:
        lines += [f"## session (last {TAIL_LINES} lines)", "", "```", tail, "```", ""]
    return "\n".join(lines)


def _session_tail(agent: Optional[str]) -> str:
    """The last `TAIL_LINES` lines of this agent's pane, or "" if that cannot be had.

    `sb inspect --json` rather than any import: `switchboard.plugins` is the one sb module
    a plugin may reach for, and it deliberately hands over no store handle and no broker.
    Shelling out to the CLI is the same door `_sb_version` uses.

    Every failure is "": no agent (a human filed it), sb not on PATH, a non-zero exit, JSON
    that does not parse, a shape that has moved. The most likely single reason to be filing
    a bug is that sb is misbehaving, so this must never be the thing that breaks filing.
    """
    if not agent:
        return ""
    try:
        r = subprocess.run(["sb", "inspect", agent, "-n", str(TAIL_LINES), "--json"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0 or not r.stdout.strip():
            return ""
        # `inspect --json` puts the pane or transcript under `output`, as
        # {source, detail, path, text}. Only `text` is wanted, and the tail is re-clipped
        # here rather than trusted to `-n`: `-n` is a request, this is the guarantee.
        out = json.loads(r.stdout).get("output") or {}
        text = out.get("text") if isinstance(out, dict) else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return ""
    if not text:
        return ""
    return "\n".join(str(text).splitlines()[-TAIL_LINES:]).rstrip()


def _sb_version() -> str:
    """`git describe --always --dirty` of sb's own checkout.

    sb's checkout is found through `switchboard.plugins.__file__` — the one switchboard
    module a plugin is allowed to import — rather than through `switchboard.__file__`,
    so this stays inside the contract `sb doctor` polices.

    `--dirty` is the point. Most bugs will be reported against uncommitted work, and a
    report claiming the commit it was almost built from is worse than one saying it does
    not know.
    """
    root = Path(sb_plugins.__file__).resolve().parent.parent
    described = _run(["git", "describe", "--tags", "--always", "--dirty"], cwd=root)
    if not described:
        return "unknown (sb is not a git checkout)"
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    return f"{described} ({branch})" if branch else described


def _herdr_version() -> str:
    return _run(["herdr", "--version"]) or "unknown"


def _run(cmd: list[str], cwd: Optional[Path] = None) -> str:
    """One line of output, or "". A bug report never fails because a version lookup did."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""


def _slug(what: str) -> str:
    """The summary, reduced to something that is still readable in an `ls`."""
    s = _SLUG_STRIP.sub("-", what.lower()).strip("-")
    if len(s) > SLUG_MAX:
        s = s[:SLUG_MAX].rsplit("-", 1)[0] or s[:SLUG_MAX]
    return s.strip("-") or "bug"
