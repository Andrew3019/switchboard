"""The automatic sweep: what a worktree has to be before it is allowed to go.

147 worktrees accumulated in this repo before anything ever deleted one on its own, and
63% of them held work that had already landed in `main`. Nothing expired them, because
the only thing that ever deletes a checkout is `sb cleanup`, which a person types, and
which only reaches a space whose agents it closed in that same run.

This module is the POLICY half of the fix — the questions, asked of git and of the
clock, with no authority to act on the answers. `Broker.sweep` is the acting half, and
every deletion it performs is `workspace_close`'s, gates and all. The split is the same
one `_space_ready` already keeps: a second implementation of "is it safe to delete this
directory" is the one thing this must not add.

**This module must not import `store`.** `switchboard/board.py` imports it for the
scheduling half below, and a renderer that can reach the store is a renderer that can
rebuild it (`tests/test_panel.py::RendererImports`). Nothing here needs a database: the
policy is answered by git, and the schedule by one file and one flock.

The rules, in the order they are asked (Andrew, 2026-08-16):

1. **A live agent is never touched.** Not a rule this module keeps — it is the gate's,
   and it is kept three ways over: unfinished rows under the checkout, rows filed under
   the name, and processes actually sitting in the directory.
2. **A dirty tree always holds it open**, whatever else is true. Uncommitted work is the
   one thing with no copy anywhere. Also the gate's (`_inventory_gate`), and the sweep's
   report names it rather than letting it disappear into an ignored-file count.
3. **Landed means merged OR pushed** — see `stranded` below. A pushed branch is enough:
   it is recoverable from origin, which is the bar. A PR is encouraged for visibility and
   is not required.
4. **Unpushed commits hold it open unless they are docs only** — see `docs_only`.
5. **Over a day old on BOTH clocks**: the last agent activity in the workspace and the
   last commit each more than 24h ago. Either one being recent holds it open, and this
   applies to a landed worktree exactly as it does to a stale one.

What is NOT here, deliberately. There is no PR lookup and no fetch: the sweep asks the
repository on this machine and nothing over the network, so it cannot hang on a remote
and cannot behave differently depending on whether somebody ran `git fetch` this hour. A
branch pushed but never fetched back reads as landed anyway, because the push is what
made it recoverable.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import config
from . import panel

BASE_BRANCH = config.setting("vocabulary.base_branch")
SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

ENABLED = config.setting("sweep.enabled")
PERIOD = config.setting("sweep.period")
MIN_AGE = config.setting("sweep.min_age")
DOCS_DIRS = tuple(config.setting("sweep.docs_dirs"))
DOCS_NEVER = tuple(config.setting("sweep.docs_never"))
MIN_SUBJECT = config.setting("sweep.min_subject")
IGNORED_HOLDS = config.setting("sweep.ignored_content_holds")

STORE_DIRNAME = config.setting("paths.store_dirname")


class Unknown(Exception):
    """git would not answer, so this worktree's facts are not known.

    Never collapsed into a clean answer. Every question here is asked in order to
    authorise a deletion, and "no output" and "could not run" have to stay structurally
    different or a git that is missing, hung or confused reads as "nothing unpushed" —
    which is the one wrong answer that destroys something. Same rule, same reason, as
    `live.scan` returning None: unknown is not empty.
    """


def reader(repo) -> Callable[..., str]:
    """A git that raises `Unknown` rather than returning "" when it fails.

    `Broker._git` returns "" for both an empty answer and a failure, which is right for
    the questions it is asked — a repo legitimately has no remote, no such ref, no
    answer — and wrong for every question below, where empty means "nothing is stranded
    here, delete it". So the sweep runs its own, in the same repo, with the same timeout.

    `ok` is for the handful of git commands whose non-zero exit IS an answer.
    """

    def git(*args: str, ok: Sequence[int] = (0,)) -> str:
        try:
            out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                                 text=True, timeout=SUBPROCESS_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            raise Unknown(f"git {args[0]} could not be run ({e.__class__.__name__})")
        if out.returncode not in ok:
            first = (out.stderr or out.stdout).strip().splitlines()
            raise Unknown(f"git {args[0]} failed: {first[0] if first else 'no reason given'}")
        return out.stdout

    return git


def base_ref(git: Callable[..., str]) -> str:
    """What "landed" is measured against: the remote-tracking base, or the local one.

    The same resolution `Broker._branch_facts` uses, and for the same reason — a repo
    with no `origin` has exactly one `main` and it is that one.
    """
    if git("rev-parse", "--verify", "--quiet", f"{BASE_BRANCH}^{{commit}}",
           ok=(0, 1)).strip():
        return BASE_BRANCH
    return BASE_BRANCH.partition("/")[2] or BASE_BRANCH


def tip_of(git: Callable[..., str], branch: str) -> str:
    """The commit a branch points at. `Unknown` if git will not name one."""
    tip = git("rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}",
              ok=(0, 1)).strip()
    if not tip:
        raise Unknown(f"git does not know a branch called {branch!r}")
    return tip


def stranded(git: Callable[..., str], tip: str, base: str) -> list[str]:
    """The commits that exist NOWHERE but here — the whole of what deleting could lose.

    Empty means landed, and landed means merged **or** pushed. Three ways a commit stops
    counting, weakest last:

    1. **The branch tip is on a remote** (`git branch -r --contains`). One question that
       covers both halves of the rule: a pushed branch and a branch merged into a remote
       `main` are the same fact from here — the commits are on origin, and origin is the
       bar. This is the check the old ancestry-only one was missing, and it needs no
       network: a remote-tracking ref is a fact about what was pushed FROM here.
    2. **A patch-equivalent commit is upstream** (`git cherry`). A rebase preserves patch
       ids, so a branch rebased onto main and merged reads as landed here even though its
       own commits are ancestors of nothing.
    3. **Its subject appears in the base's history.** The squash case, and the only
       heuristic in this file. A squash merge produces one commit whose patch id matches
       nothing on the branch, and whose message body is GitHub's list of the original
       subjects — so the subjects are what survives the squash and they are what is
       matched, `--fixed-strings` and whole. Two guards on it: a subject shorter than
       `sweep.min_subject` is never matched (a "wip" or a "fix" would match half a
       history), and the cost of being wrong is bounded — the branch REF is not deleted
       by a sweep, because `_finish` uses `git branch -d`, which refuses an unmerged
       branch. So a false positive costs the checkout and `sb restore`, both of which
       DESIGN-TRUTH already accepts aggressive cleanup destroying, and never a commit.

    Of the three worktrees in the 2026-08-16 census whose PR was merged but whose
    ancestry said otherwise, rule 1 catches one, rule 2 catches one and rule 3 catches
    the last.
    """
    if git("branch", "-r", "--contains", tip).strip():
        return []
    # `--not --remotes` and not just `--not <base>`: a commit pushed to its own branch is
    # recoverable whether or not it ever reached main.
    nowhere = git("rev-list", tip, "--not", "--remotes", base).split()
    if not nowhere:
        return []
    equivalent = {ln[2:].strip() for ln in git("cherry", base, tip).splitlines()
                  if ln.startswith("- ")}
    return [c for c in nowhere
            if c not in equivalent and not _subject_upstream(git, base, c)]


def _subject_upstream(git: Callable[..., str], base: str, commit: str) -> bool:
    """Does this commit's subject line appear in the base's history? See `stranded` (3)."""
    subject = git("log", "-1", "--format=%s", commit).strip()
    if len(subject) < MIN_SUBJECT:
        return False
    return bool(git("log", base, "-1", "--format=%H", "--fixed-strings",
                    f"--grep={subject}").strip())


def paths_of(git: Callable[..., str], commits: Sequence[str]) -> set[str]:
    """Every file the given commits touch, repo-relative.

    A merge commit contributes nothing here — `git show` prints no file list for one
    without `-m` — so a stranded merge commit reads as touching no files at all, which
    `docs_only` then treats as docs. Left as is rather than widened: a merge commit whose
    parents are both stranded brings its parents along into this list, and a merge whose
    other side is already upstream introduces nothing that side did not.
    """
    if not commits:
        return set()
    out = git("show", "--name-only", "--pretty=format:", *commits)
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def docs_only(paths: Sequence[str]) -> bool:
    """Is every one of these files documentation? Decided by PATH and nothing else.

    Path-based on purpose: reading the content to decide what a change "really is" is a
    judgement, and this runs unattended at :00 and :30 with a deletion behind it. A `.md`
    anywhere, or anything under one of the documentation directories, and that is the
    whole rule.

    `DESIGN-TRUTH.md` is carved out and always blocks. It is the only trusted document in
    the repo and only Andrew edits it, so an unpushed change to it is never a stale note
    somebody can regenerate — it is the one file whose loss is not recoverable by doing
    the work again.

    An empty set is docs-only. That is a stranded commit that changed no files at all,
    and there is nothing in it to lose.
    """
    if any(p in DOCS_NEVER for p in paths):
        return False
    return all(p.endswith(".md") or p.split("/")[0] in DOCS_DIRS for p in paths)


def last_commit_at(git: Callable[..., str], tip: str) -> int:
    """Committer date of the branch tip, epoch seconds."""
    out = git("log", "-1", "--format=%ct", tip).strip()
    try:
        return int(out)
    except ValueError:
        raise Unknown(f"git would not date {tip[:8]}")


def too_recent(last_commit: int, last_activity: int, now: float) -> Optional[str]:
    """None if both clocks are past `sweep.min_age`, else which one is not, in words.

    Two clocks, because either alone is wrong in a way that has already happened here. A
    worktree whose agent is mid-task has no new commit for hours, and one whose agent
    finished days ago can be re-entered by a person and committed to at any moment. So
    each has to be quiet: last agent activity in the workspace AND last commit date.

    `last_activity` of 0 is a checkout with no agent rows at all — git knows it and the
    store never did — and reads as ancient, which leaves the commit clock deciding on its
    own. That is the right answer for the shape: nothing ever worked there as far as
    anything here can tell.
    """
    for what, when in (("its last commit", last_commit),
                       ("agent activity in it", last_activity)):
        age = now - when
        if age < MIN_AGE:
            return f"{what} was {_ago(age)} ago, under the {_ago(MIN_AGE)} floor"
    return None


def _ago(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds / 60)}m"
    if seconds < 172800:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


# -- the schedule ----------------------------------------------------------------------
#
# Two ticks an hour on the system clock, from whichever board sees the boundary first.


def state_dir(cwd: Optional[Path] = None) -> Path:
    """Where the slot marker lives: beside the store, under the repo's shared `.git`.

    Shared, and it has to be — the dedup is between boards in DIFFERENT worktrees of one
    repo, which have nothing else in common. `panel.git_common_dir` is the same
    resolution the collector's own election uses, and the one thing in this file a
    renderer already imports.
    """
    return panel.git_common_dir(cwd) / STORE_DIRNAME / "sweep"


def slot_of(now: float) -> int:
    """Which half-hour of the clock this instant is in.

    Epoch seconds divided by the period, so the boundaries fall on :00 and :30 for any
    timezone offset that is a whole or half hour, with no calendar arithmetic and nothing
    to get wrong across a DST edge.
    """
    return int(now // PERIOD)


def claim(slot: int, *, cwd: Optional[Path] = None) -> bool:
    """Take this slot for this process, or answer False because somebody else has it.

    Every agent's pane opens with a board beside it, so a fleet of twenty has twenty
    boards and every one of them crosses :30 at the same moment. Exactly one may sweep.

    The flock is held only across the read-and-write, not across the sweep itself, and
    the marker is written BEFORE the sweep runs rather than after. Both are deliberate:

    - a lock held across a sweep would be a lock held for minutes by a process that can
      be closed with the pane it draws in, and the loser needs no more than to find out
      that the slot is taken;
    - writing first means a sweep that dies halfway loses its slot rather than being
      retried by the next board a second later. The next tick is thirty minutes away and
      nothing here is urgent.

    A slot in the FUTURE relative to the marker is the only thing that runs, so a clock
    that jumps backwards silently skips until it catches up, rather than sweeping on
    every tick.
    """
    d = state_dir(cwd)
    try:
        d.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(d / "slot.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False                       # another board is claiming it right now
        marker = d / "slot"
        try:
            last = int(marker.read_text().strip())
        except (OSError, ValueError):
            last = -1
        if last >= slot:
            return False
        try:
            marker.write_text(f"{slot}\n")
        except OSError:
            return False
        return True
    finally:
        os.close(fd)


def command() -> list[str]:
    """How a board runs a sweep: a short-lived process of its own, on current code.

    Not a thread, and not inline. Inline would freeze the board for as long as the sweep
    takes — an `lsof` and a handful of git calls per candidate — and a thread would need
    a database handle in a process whose whole design is that it has none
    (`tests/test_panel.py::RendererImports`). A subprocess also means the sweep runs the
    code on disk NOW, which matters for a board pane that has been open for two days.

    `-m switchboard.cli`, the same shape as the `-m switchboard.board` a board is itself
    launched with, so there is no `bin/sb` path to guess at.
    """
    return [sys.executable, "-m", "switchboard.cli", "sweep"]
