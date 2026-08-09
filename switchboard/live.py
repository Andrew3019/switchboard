"""Who is actually working in a directory — asked of the machine, not of our rows.

Every other liveness question in switchboard is answered by the store or by herdr, and
both are wrong in the same direction here. A herdr that has restarted answers
*successfully* with a smaller world — `agent list` has no failure branch at all, verified
against a throwaway server (`notes/probe-lsof-herdr-findings.md`) — so an empty answer is
not evidence of an empty workspace, it is no evidence either way. And a human with an
editor open has no `agents` row to be finished. This module is the only signal that can
be right about either, which is why it is a module rather than a helper buried in the
caller: a destructive command is eventually going to spend it.

Two rules come out of that and neither is optional:

- **"Nothing is running" and "I could not tell" are different answers.** None is "could
  not tell", the same convention `Broker._alive` follows. The parser is strict so the two
  stay structurally disjoint: a clean exit-0 parse with no matching cwd is the first, and
  a missing binary, a non-zero exit, a timeout or output that fails the shape check is the
  second. A lenient parser that scrapes what it recognises and skips the rest hands both
  answers the same shape, which is the one thing this must not do.
- **Containment is compared component-wise, never as a string prefix.** Worktrees are
  siblings in one directory and their names nest as strings on this machine right now:
  `.../worktrees/switchboard/fix-options-2/anything` passes a `startswith` test against
  `.../worktrees/switchboard/fix-options`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Collection, NamedTuple, Optional

from . import config

SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

# `-d cwd` asks for one file-descriptor type per process — the current directory — rather
# than open files; `+D <path>` is the expensive recursive scan of what has a directory's
# CONTENTS open, which is a different question. `-a` ANDs the selection criteria, a no-op
# with one criterion and the thing that stops a second one silently becoming an OR. `-F
# pcn` is the machine-readable form: pid, command, name.
#
# Deliberately unfiltered and whole-machine. Scoping with `-p` to exclude the caller's own
# tree exits 1 with empty output when the list matches nothing, which is indistinguishable
# from a real failure — and this is the one check that must not have an ambiguous shape in
# it. Exclusion happens in the parser, by pid. The cost of asking for everything was
# measured: 0.23s, 0.07s, 0.06s over 328 processes.
CWD_SCAN = ("lsof", "-a", "-d", "cwd", "-F", "pcn")


class Proc(NamedTuple):
    """One process and the directory it is sitting in."""

    pid: int
    command: str
    cwd: str


def scan(timeout: float = SUBPROCESS_TIMEOUT) -> Optional[list[Proc]]:
    """Every process on this machine and its cwd, or **None** when we could not tell.

    None covers all four ways of not getting an answer, and they are one answer here: the
    binary is missing, the exit is non-zero, it hung, or the output is not the shape this
    parser knows. Note the first of those — with an argv list and no shell, a missing
    `lsof` raises `FileNotFoundError` rather than returning a non-zero exit, so a caller
    that only inspected `returncode` would crash where it meant to refuse.

    The output is strict repeating four-line groups — `p<pid>`, `c<command>`, `fcwd`,
    `n<absolute path>` — confirmed over 328 processes with no exceptions. Anything else is
    a failure rather than a line to skip; see the module docstring for why.
    """
    try:
        out = subprocess.run(list(CWD_SCAN), capture_output=True, text=True,
                             timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None                            # missing, unrunnable, or hung
    if out.returncode != 0:
        return None
    return _parse(out.stdout)


def _parse(text: str) -> Optional[list[Proc]]:
    lines = text.splitlines()
    if len(lines) % 4:
        return None                            # a truncated group is not a short answer
    found = []
    for i in range(0, len(lines), 4):
        pid, command, fd, name = lines[i:i + 4]
        if not (pid.startswith("p") and command.startswith("c")
                and fd == "fcwd" and name.startswith("n/")):
            return None
        try:
            found.append(Proc(int(pid[1:]), command[1:], name[1:]))
        except ValueError:
            return None
    return found


def is_under(path: str, root: str) -> bool:
    """Does `path` sit inside `root`, or is it `root` itself?

    Both sides resolved and compared as path components. Never `str.startswith`: sibling
    worktree names genuinely nest as strings here, and a prefix match gates the shorter
    name forever on processes belonging to the longer one.

    A cwd that no longer exists still answers, which is the direction that matters: macOS
    reports the original path string for a process whose directory was deleted underneath
    it, with no marker, so the comparison still catches it.
    """
    try:
        p, r = Path(path).resolve(), Path(root).resolve()
    except OSError:                            # unreadable, or a symlink loop
        return False
    return p.parts[:len(r.parts)] == r.parts


def processes_in(root: str, *, exclude: Collection[int] = ()) -> Optional[list[Proc]]:
    """What is live under `root`, or **None** when the machine could not be asked.

    An empty list is a real answer — nothing is in that directory — and None is not a
    quieter version of it. A caller about to destroy something treats None as a refusal.

    `exclude` is pids to leave out, which is how the caller's own process tree stops
    counting against a gate it is itself running: an agent told to close the workspace it
    works in is sitting under that checkout by definition. It is done here, on parsed
    output, rather than by narrowing the scan — see `CWD_SCAN`.
    """
    seen = scan()
    if seen is None:
        return None
    return [p for p in seen if p.pid not in exclude and is_under(p.cwd, root)]
