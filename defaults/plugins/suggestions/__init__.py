"""File a suggestion about switchboard itself, as one markdown file per suggestion.

`report-bug` catches "sb is broken". This catches the other thing: "sb works, and it is
costing me anyway." Recurring friction that an agent hits while doing its actual task
otherwise dies in a `sb done` summary nobody re-reads, and the cost is paid again by the
next agent, and the one after that.

The bar, and why it is in code
------------------------------

Three flags, all required, and a suggestion missing any of them is REFUSED rather than
filed with empty fields:

    --friction   what you actually hit, in the task you were doing. Not hypothetical.
    --cost       what it cost you: time, retries, extra agents, work thrown away.
    --recurs     why this will happen again, or where you have already seen it happen.

`--recurs` is the one that carries the design. The condition for a suggestion being worth
anything is that the friction is decently frequent, and an agent cannot be trusted to
self-assess frequency in the abstract — asked to rate it, everything it hit is important.
So it is asked for evidence of recurrence instead of a rating, which is a question about
something it has seen rather than a question about its own judgement.

Cross-task frequency needs no mechanism at all. Following `report-bug`'s no-dedup
doctrine: the same suggestion filed by five agents is five files, and five files IS the
frequency signal. Identical summaries produce identical slugs and sort next to each other,
so `list` shows the repetition for free.

Everything else is `report-bug`
-------------------------------

Same shape, same scope, same store: one markdown file per suggestion in a user-scoped
directory, no index, no database, no dedup, no lock. A suggestion about switchboard is a
fact about switchboard rather than about whichever repo you were standing in — the repo and
worktree are still recorded IN the file, because the context is useful and the partitioning
is not.

The helpers are `report-bug`'s own, imported rather than copied (see `_report_bug`): the
filename allocation, the listing, the version probes and the bounded session tail are the
same problems with the same answers, and two copies of them would drift.

Known and accepted
------------------

Nothing surfaces these. No digest, no reminder, no agent is told to read them — the same
failure mode that got `todo` unbound from `all`, accepted knowingly here rather than
overlooked. Filing a suggestion never changes code and never spawns anything, and there is
no priority field because nothing would consume one.
"""

from __future__ import annotations

import importlib.util
import platform
import sys
import time
from pathlib import Path
from typing import Optional

from switchboard.plugins import Result

API = 1
VERSION = "1.0.0"
# A suggestion about switchboard is a fact about switchboard, not about the repo you were
# standing in when you hit the friction. Same reasoning as report-bug's.
SCOPE = "user"
# Append-only, one file per suggestion, filenames that cannot collide (`_create` uses
# O_EXCL). There is nothing for a lock to protect.
LOCK = False

# `2026-08-15-143022-sb-inspect-pane-is-empty.md`. Sorts chronologically as a string, reads
# as a date, and carries enough of the summary that `ls` is already an index.
STAMP = "%Y-%m-%d-%H%M%S"

# Long enough for a real summary line, short enough to stay a summary. The detail belongs
# in the three flags, which have no limit worth enforcing.
MAX_SUMMARY = 200


def _report_bug():
    """`report-bug`'s module, imported by path from the sibling directory.

    A plugin gets no import hook of its own and `report-bug` is not importable by name (the
    hyphen, and sb loads it under a mangled key), so this is by path. It is deliberately
    done at module scope and left to raise: if `report-bug` is not next door, the honest
    outcome is `sb doctor` reporting this plugin as broken, not a silent second copy of
    every helper quietly drifting from the original.

    Loaded under sb's own key, so a process that has both plugins in play holds one module
    object rather than two.
    """
    name = "sb_plugin_report-bug"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    path = Path(__file__).resolve().parent.parent / "report-bug" / "__init__.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} is not importable")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


_rb = _report_bug()

# Aliased rather than restated, because report-bug's helpers below read them: a second
# number here that disagreed with the one `_slug` and `_session_tail` actually use would be
# a lie in the one place somebody would go to check.
SLUG_MAX = _rb.SLUG_MAX
TAIL_LINES = _rb.TAIL_LINES
TIMEOUT = _rb.TIMEOUT

# The three questions, in the order the file asks them. One list, because the refusal, the
# declaration and the rendering must never disagree about what "required" means.
REQUIRED = (
    ("friction", "what you actually hit, in the task you were doing"),
    ("cost", "what it cost you: time, retries, extra agents, work thrown away"),
    ("recurs", "why this will happen again, or where you have seen it before"),
)


def register(reg):
    reg.command(
        "file", file_, audience="both", help="suggest an improvement to switchboard",
        args=[reg.arg("what", help="one line: the improvement")]
             + [reg.arg(f"--{name}", help=help_) for name, help_ in REQUIRED])
    reg.command(
        "list", ls, audience="both", help="every suggestion filed on this machine")
    reg.command(
        "show", show, audience="both", help="one suggestion in full",
        args=[reg.arg("id", help="a suggestion id, or enough of one to be unambiguous")])
    # Human only. An agent that can bin its own or another agent's suggestion can quietly
    # undo the only record that the friction was ever paid for.
    reg.command(
        "drop", drop, audience="human", help="delete a suggestion outright",
        args=[reg.arg("id", help="a suggestion id")])


# -- the handlers --------------------------------------------------------------


def file_(ctx, args) -> Result:
    what = (args.what or "").strip()
    if not what:
        return Result(ok=False, human="a suggestion needs one line saying what to improve")
    if len(what) > MAX_SUMMARY:
        return Result(ok=False, human=f"that summary is {len(what)} characters; keep it to "
                                      f"{MAX_SUMMARY} and put the detail in --friction")
    # The bar. A suggestion short of it is refused by name rather than filed with the field
    # empty: an empty --recurs is indistinguishable from a suggestion nobody should act on,
    # and a store full of those is a store nobody reads.
    for name, prompt in REQUIRED:
        if not (getattr(args, name, None) or "").strip():
            return Result(ok=False, human=f"--{name} is required: {prompt}")

    now = time.localtime()
    path = _rb._create(ctx.state_dir, time.strftime(STAMP, now), _rb._slug(what))
    path.write_text(_render(ctx, args, what, now), encoding="utf-8")
    return Result(human=f"filed {path.stem}\n  {path}",
                  data={"id": path.stem, "path": str(path), "what": what})


def ls(ctx, args) -> Result:
    """Every suggestion on this machine, newest first, whatever repo it came from.

    Not filtered to this repo and there is no flag to filter it, for the reason user scope
    exists: friction hit in three repos would otherwise be three lists you never find
    again. The repo each one came from is in the file.
    """
    rows = _rb._reports(ctx.state_dir)
    if not rows:
        return Result(human="(no suggestions)", data=[])
    return Result(human="\n".join(f"{p.stem}  {m.get('what', '')}" for p, m in rows),
                  data=[{"id": p.stem, "path": str(p), **m} for p, m in rows])


def show(ctx, args) -> Result:
    p, err = _resolve(ctx.state_dir, args.id)
    if p is None:
        return Result(ok=False, human=err)
    text = p.read_text(encoding="utf-8")
    return Result(human=text.rstrip(), data={"id": p.stem, "path": str(p), "text": text})


def drop(ctx, args) -> Result:
    p, err = _resolve(ctx.state_dir, args.id)
    if p is None:
        return Result(ok=False, human=err)
    p.unlink()
    return Result(human=f"deleted {p.stem}", data={"id": p.stem, "path": str(p)})


# -- files ---------------------------------------------------------------------


def _resolve(d: Path, given: str) -> tuple[Optional[Path], str]:
    """An id, an id with `.md` on it, or an unambiguous prefix of one.

    Not `report-bug`'s `_resolve`, and this is the one helper worth having twice: its
    failure messages name reports and point at `sb plugin report-bug list`, which would send
    a reader looking for their suggestion in the wrong store.
    """
    given = (given or "").strip()
    for candidate in (d / given, d / f"{given}.md"):
        if candidate.is_file() and candidate.parent == d:
            return candidate, ""
    hits = [p for p, _ in _rb._reports(d) if p.stem.startswith(given)] if given else []
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"no such suggestion: '{given}' — see `sb plugin suggestions list`"
    return None, (f"'{given}' matches {len(hits)} suggestions: "
                  f"{', '.join(p.stem for p in hits[:4])}"
                  f"{' …' if len(hits) > 4 else ''}")


# -- the suggestion ------------------------------------------------------------


def _render(ctx, args, what: str, now) -> str:
    """The whole file. Markdown, because the only reader that matters is a person."""
    lines = [f"# {what}", ""]
    for name, _ in REQUIRED:
        lines += [f"## {name}", "", (getattr(args, name) or "").strip(), ""]
    lines += ["## context", "",
              f"- filed: {time.strftime('%Y-%m-%d %H:%M:%S %z', now)}",
              f"- by: {ctx.agent or 'human'}",
              f"- sb: {_rb._sb_version()}",
              f"- herdr: {_rb._herdr_version()}",
              f"- python: {platform.python_version()} ({sys.executable})",
              f"- platform: {platform.platform()}",
              # Recorded, not partitioned on. `repo` is the shared `.git` — the repo's
              # identity — and `worktree` is the checkout the caller was standing in.
              f"- repo: {ctx.repo}",
              f"- worktree: {ctx.worktree}",
              ""]
    # Last, and fenced: it is the only open-ended part of the file, so a reader should reach
    # the facts first, and it is terminal output that markdown would otherwise eat. Absent
    # when a human filed it (there is no session) or when it cannot be read.
    tail = _rb._session_tail(ctx.agent)
    if tail:
        lines += [f"## session (last {TAIL_LINES} lines)", "", "```", tail, "```", ""]
    return "\n".join(lines)
