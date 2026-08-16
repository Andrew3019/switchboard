"""Fleet-wide numbers for the board's top section — and the cadence that makes them free.

Three groups of number, each with a different real cost, and the whole design is about
keeping the expensive ones off the caller's clock:

- **From the store** — turns, spawns and messages in the last hour. Three counts, computed
  inline on expiry because a sqlite connection belongs to the thread that opened it. There
  is no index on `created_at`, so all three are table scans: ~370 ms on the FIRST call in a
  process (a 17 MB store, 32k events, nothing of it in this process's page cache) and
  ~5-20 ms on every later expiry. That first call is why this belongs in the collector,
  where a slow tick is invisible, and not in something drawing a frame.
- **From git** — lines changed in the last hour. ONE `git log --all` walk of the shared
  repository, not one `git diff` per checkout: this store holds 275 workspace rows, 153 of
  whose checkouts still exist on disk, and a subprocess each would be ~45 s of work for a
  number that changes when somebody commits. Every worktree shares one `.git`, so one walk
  over all refs already covers all of them — ~0.3 s of CPU, 1.5-5 s of wall time while
  fifteen agents are running their own git in the same repository.
- **From the machine** — CPU and resident memory across the fleet's process tree. `lsof`
  plus `ps`, ~0.4 s, and the reason the caching in here exists at all.

**CALL THIS FROM THE COLLECTOR, NEVER FROM A RENDERER.** `switchboard/panel.py` states the
load-bearing property of the panel split — a renderer imports `status` and not `store`, and
spawns no subprocess at all — and `tests/test_panel.py::RendererImports` pins both. This
module reads the store (through a handle its caller opens) and shells out to `git`, `lsof`
and `ps`, so a renderer that imported it would break the second half of that property and,
if it passed a connection, the first. The way these numbers reach forty panes is the way
every other number does: the collector computes them once and publishes them in the
snapshot, and the panes read a dict. `Stats.as_dict()` is here for exactly that.

Nothing in here blocks on a scan. `collect()` returns whatever the last sample said and
kicks a background one when that goes stale, so a caller redrawing twice a second pays
nothing for the two expensive groups — and a caller that has no sample yet gets `None`
rather than a wait. `None` is "unknown" everywhere in `Stats` and never means zero: a fake
zero on screen reads as a real measurement, and "no lines changed in the last hour" and
"git would not answer" are not the same sentence. Each group is also given a `max_age`
past which its cached value stops being served — a CPU figure from ten minutes ago is not
a stale reading, it is a wrong one.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config
from . import live

SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

# The git walk gets its own, longer allowance. Measured on this repo — 358 refs, an hour
# with 40 commits in it — the walk costs ~0.3 s of CPU but 1.5-5 s of WALL time while a
# fleet of agents is doing its own git in the same repository. It runs on a background
# thread that nothing waits on, so the shared 10 s is the wrong trade here: it would turn a
# busy repository into a permanently unknown number, and a slow answer is still an answer.
GIT_TIMEOUT = 30.0

# The window every "last hour" number is counted over. One number so the store counts and
# the git walk cannot drift apart on screen.
WINDOW = 3600

# Per group: how old a value may get before the next `collect()` refreshes it, and how old
# it may get before it stops being served at all. The second is not the first with a bigger
# number — it is the difference between "worth refreshing" and "no longer true".
STORE_TTL, STORE_MAX_AGE = 10.0, 120.0
GIT_TTL, GIT_MAX_AGE = 60.0, 600.0
# A few seconds, per the board's own refresh being ~2x a second: this is the sample the
# whole module exists to keep off that clock. `max_age` is deliberately tight — CPU is an
# instantaneous-ish reading and a minute-old one is not a dimmer version of it.
PROC_TTL, PROC_MAX_AGE = 5.0, 30.0

# What "non-docs" excludes. `*.md` anywhere, plus the two trees that are prose by
# convention in this repo. Matched on the FIRST path component, which is what "the `notes/`
# tree" means — a `switchboard/notes.py` is code and stays counted.
DOC_SUFFIX = ".md"
DOC_TREES = ("notes", "learnings")


# ---------------------------------------------------------------------------
# What a caller gets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    """Every field is `None` when it could not be computed. `None` is never zero.

    The `*_age` fields are seconds since that group was last sampled successfully, or
    `None` if it never has been. They are here so a renderer can dim or drop a number that
    is older than it looks, without having to know this module's cadences.
    """

    # From the store.
    turns_last_hour: Optional[int] = None
    spawns_last_hour: Optional[int] = None
    # Inter-agent messages — `sb tell`/`ask`/`done`/`failed` rows. NOT "sb calls": nothing
    # logs every `sb` invocation (`store.log_event` is called from specific sites only), so
    # that number does not exist to be reported and this one must not be labelled as it.
    messages_last_hour: Optional[int] = None
    store_age: Optional[float] = None

    # From git — commits made in the last hour on ANY ref of the shared repository.
    lines_changed: Optional[int] = None
    lines_changed_nondocs: Optional[int] = None
    commits_last_hour: Optional[int] = None
    git_age: Optional[float] = None

    # From the machine.
    cpu_percent: Optional[float] = None       # summed across the tree; >100 on many cores
    memory_bytes: Optional[int] = None        # summed RSS; shared pages counted per process
    processes: Optional[int] = None
    cpu_cores: Optional[int] = None           # so a caller can turn cpu_percent into a share
    proc_age: Optional[float] = None

    def as_dict(self) -> dict:
        """For riding in the collector's snapshot JSON. `None` survives the round trip."""
        return dataclasses.asdict(self)


def collect(db: Optional[sqlite3.Connection] = None, *,
            repo: Optional[Path] = None, wait: bool = False) -> Stats:
    """Every number the top section wants. **Never raises, never blocks on a scan.**

    `db` is an OPEN connection — this module never opens one, so it can never be the thing
    that migrates or rebuilds a store (`store.connect` does both). Pass the collector's
    read-only handle. Without one the three store counts come back unknown and the rest
    still works. `repo` is any directory inside the repository, for the git walk; the
    process's own cwd is used when it is not given.

    `wait=True` computes the two background groups in this thread instead of returning the
    last sample. It exists for one-shot callers — a test, a script, `sb` printing these
    once — and must not be used by anything that redraws.

    The store counts are computed inline on expiry rather than in a thread, because a
    sqlite connection belongs to the thread that opened it and handing this one to a
    sampler would be a `ProgrammingError` waiting for the first cache miss. That is the one
    real cost left on a caller's clock — ~370 ms on the first call in a process against the
    17 MB store measured, ~5-20 ms on each `STORE_TTL` expiry after it. Measured warm, with
    every sample in hand, a call is ~0.07 ms.
    """
    counts, store_age = ((None, None) if db is None
                         else _STORE.get(lambda: _store_counts(db), wait=True))
    lines, git_age = _GIT.get(lambda: _git_lines(repo), wait=wait)
    # The checkouts are read HERE, on the caller's thread, and handed to the sampler as
    # plain paths — same connection-affinity rule as above, and the reason this is not
    # simply `lambda: _proc_sample(_checkouts(db))`. Behind `due()` so a warm call does no
    # SQL at all: this one runs at the caller's rate, not the sampler's. If the ttl expires
    # in the microseconds between `due()` and `get()`, the sampler gets no roots, declines
    # to answer and leaves the previous value standing — one skipped sample, and the next
    # call finds `due()` true and takes it.
    roots = _checkouts(db) if (wait or _PROC.due()) else []
    procs, proc_age = _PROC.get(lambda: _proc_sample(roots), wait=wait)

    counts = counts or {}
    lines = lines or {}
    procs = procs or {}
    return Stats(
        turns_last_hour=counts.get("turns"),
        spawns_last_hour=counts.get("spawns"),
        messages_last_hour=counts.get("messages"),
        store_age=store_age,
        lines_changed=lines.get("total"),
        lines_changed_nondocs=lines.get("nondocs"),
        commits_last_hour=lines.get("commits"),
        git_age=git_age,
        cpu_percent=procs.get("cpu"),
        memory_bytes=procs.get("rss"),
        processes=procs.get("count"),
        cpu_cores=os.cpu_count(),
        proc_age=proc_age,
    )


# ---------------------------------------------------------------------------
# The cadence
# ---------------------------------------------------------------------------


class Sampler:
    """One value, refreshed off the caller's clock. The whole of the caching story.

    Three states and they are deliberately distinct: fresh (serve it), stale-but-usable
    (serve it AND start a refresh), and too old (serve `None`, still start a refresh). The
    last is what stops a sampler whose subprocess has started timing out from quietly
    presenting a reading from ten minutes ago as the current one.

    A refresh runs on a daemon thread, one at a time — `_running` is not an optimisation
    but the thing that stops a slow sampler being started again on every one of the two
    hundred redraws it takes to finish. Daemon, so a sample in flight can never hold up a
    process that wants to exit.

    A sample that raises or returns `None` leaves the previous value alone and ages it; it
    does not blank it. The failure is a failure to LEARN something new, and the last thing
    known is still the last thing known — until `max_age`, which is where that stops being
    true.

    `clock` is monotonic, not wall clock: these are elapsed times, and the one thing a
    cadence must survive is the system clock moving under it.
    """

    def __init__(self, ttl: float, max_age: float,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.max_age = max_age
        self.clock = clock
        self._lock = threading.Lock()
        self._value = None
        self._at: Optional[float] = None
        self._running = False

    def due(self) -> bool:
        """Would the next `get()` start a refresh? Asked by a caller that has to prepare one."""
        with self._lock:
            at = self._at
        return at is None or (self.clock() - at) >= self.ttl

    def get(self, sample: Callable[[], Optional[dict]], *, wait: bool = False):
        """-> (value or None, age in seconds or None). Never raises."""
        with self._lock:
            value, at, running = self._value, self._at, self._running
        age = None if at is None else self.clock() - at

        if age is None or age >= self.ttl:
            if wait:
                self._store(_guard(sample))
                with self._lock:
                    value, at = self._value, self._at
                age = None if at is None else self.clock() - at
            elif not running:
                self._spawn(sample)

        if age is None or age > self.max_age:
            return None, age
        return value, age

    def _spawn(self, sample: Callable[[], Optional[dict]]) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._run, args=(sample,), daemon=True).start()

    def _run(self, sample: Callable[[], Optional[dict]]) -> None:
        try:
            self._store(_guard(sample))
        finally:
            with self._lock:
                self._running = False

    def _store(self, value: Optional[dict]) -> None:
        if value is None:
            return                              # a failed sample ages the old one
        with self._lock:
            self._value, self._at = value, self.clock()


def _guard(sample: Callable[[], Optional[dict]]) -> Optional[dict]:
    """A sample that raises is a sample that did not happen, not a crashed board."""
    try:
        return sample()
    except Exception:                           # noqa: BLE001 — any failure is "unknown"
        return None


_STORE = Sampler(STORE_TTL, STORE_MAX_AGE)
_GIT = Sampler(GIT_TTL, GIT_MAX_AGE)
_PROC = Sampler(PROC_TTL, PROC_MAX_AGE)


def reset() -> None:
    """Forget every sample. For tests, and for a caller that has changed repository."""
    global _STORE, _GIT, _PROC
    _STORE = Sampler(STORE_TTL, STORE_MAX_AGE)
    _GIT = Sampler(GIT_TTL, GIT_MAX_AGE)
    _PROC = Sampler(PROC_TTL, PROC_MAX_AGE)


# ---------------------------------------------------------------------------
# From the store
# ---------------------------------------------------------------------------


def _store_counts(db: Optional[sqlite3.Connection]) -> Optional[dict]:
    """Three counts over the last hour, each independently unknown-able.

    Separately, rather than one query with three sub-selects, because a degraded store is a
    real state here (`store.schema_deficit`): a missing `events` table must cost the turn
    count and not the other two.
    """
    if db is None:
        return None
    cut = int(time.time()) - WINDOW
    return {
        "turns": _count(db, "SELECT COUNT(*) FROM events WHERE kind='turn_end' "
                            "AND created_at>=?", cut),
        "spawns": _count(db, "SELECT COUNT(*) FROM agents WHERE created_at>=?", cut),
        "messages": _count(db, "SELECT COUNT(*) FROM messages WHERE created_at>=?", cut),
    }


def _count(db: sqlite3.Connection, sql: str, *args) -> Optional[int]:
    try:
        return int(db.execute(sql, args).fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError):
        return None


def _checkouts(db: Optional[sqlite3.Connection]) -> list[str]:
    """Every live workspace's checkout — the roots the process scan is scoped to.

    Retired workspaces are left out; a checkout recorded for one that no longer exists on
    disk costs nothing here, since a path nothing is standing in simply never matches.
    """
    if db is None:
        return []
    try:
        rows = db.execute("SELECT checkout FROM workspaces "
                          "WHERE retired_at IS NULL AND checkout IS NOT NULL").fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows if r[0]]


# ---------------------------------------------------------------------------
# From git
# ---------------------------------------------------------------------------

# `--all` and not one walk per checkout: every worktree of this repo shares one `.git`, so
# all their branches are refs here already. `--no-merges` because a merge shows no numstat
# by default anyway, and saying so is cheaper than explaining the empty output later.
_GIT_LOG = ("git", "-c", "core.quotepath=false", "log", "--all", "--no-merges",
            "--numstat", "--format=%H")

# `dir/{old => new}/file.py`, and the plain `old => new`. Rewritten to the NEW path, which
# is the one the docs filter should judge.
_RENAME_BRACED = re.compile(r"\{[^{}]*? => ([^{}]*?)\}")


def _git_lines(repo: Optional[Path]) -> Optional[dict]:
    """Lines added+deleted in the last hour, total and excluding docs. **None** if git won't say.

    None rather than zero on every failure — not a repo, no git, a walk that timed out. An
    hour in which nobody committed and an hour nobody could ask about look identical as a
    zero, and only one of them is a fact.

    What this counts is COMMITS MADE in the window, on any ref of the shared repository,
    and three things follow that a caller putting it on screen should know:

    - Uncommitted work in a worktree is not in it. Catching that means a `git diff` per
      checkout, which is the 153-subprocess sweep this walk exists to avoid.
    - `--all` includes remote-tracking refs, so a fetch brings somebody else's commits into
      the hour they were fetched in.
    - A branch squash-merged within the same hour is counted twice, once as the branch's
      commits and once as the merge's. This is a real overcount and it is the honest cheap
      answer; distinguishing them costs the per-checkout sweep again.
    """
    cut = int(time.time()) - WINDOW
    try:
        out = subprocess.run([*_GIT_LOG, f"--since=@{cut}"],
                             cwd=str(repo) if repo else None,
                             capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return _parse_numstat(out.stdout)


def _parse_numstat(text: str) -> dict:
    """Sum a `--numstat` walk. Binary files ("-\t-") count as a file, not as lines.

    Lenient where `live._parse` is strict, and for the opposite reason: nothing destructive
    is decided here, the shapes are open-ended (a 40-char sha line, a blank line, a numstat
    row, a path with a rename arrow in it), and a line this does not recognise costs one
    file's lines rather than the honesty of a gate.
    """
    total = nondocs = commits = 0
    for line in text.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            commits += 1                        # the `%H` line
            continue
        added, deleted, path = parts
        try:
            n = int(added) + int(deleted)
        except ValueError:
            continue                            # "-\t-": a binary file has no line count
        total += n
        if not is_docs(path):
            nondocs += n
    return {"total": total, "nondocs": nondocs, "commits": commits}


def is_docs(path: str) -> bool:
    """Is this path prose? `*.md` anywhere, or anything in the `notes/`/`learnings/` trees.

    A rename is judged on where the file ENDED UP: `git log --numstat` writes those as
    `dir/{old => new}/file`, so the arrow is resolved before the decision rather than
    leaving `notes/{a => b}.md` to be matched as neither.
    """
    path = _RENAME_BRACED.sub(r"\1", path)
    if " => " in path:                          # the unbraced form: `old => new`
        path = path.split(" => ")[-1]
    path = path.strip().strip("/")
    if path.lower().endswith(DOC_SUFFIX):
        return True
    return path.split("/")[0] in DOC_TREES


# ---------------------------------------------------------------------------
# From the machine
# ---------------------------------------------------------------------------

# pid, parent, resident set in KB, and %CPU. One process for the whole table, the same
# shape `broker._parents` reads and for the same reason: `ps` is the only place a parent
# link comes from, and here it is also the only place the numbers do.
_PS = ("ps", "-Ao", "pid=,ppid=,rss=,pcpu=")


def _proc_sample(roots: list[str]) -> Optional[dict]:
    """Aggregate CPU% and RSS for everything working in a fleet checkout. **None** if unaskable.

    "The sb process tree" is defined here as: every process of ours whose cwd is inside a
    live workspace's checkout, plus everything descended from those. The first half is what
    `live.scan` already answers and covers the agent panes and the short-lived `git`, `sb`
    and test processes they run; the second catches a child that changed directory, which
    a cwd scan alone would drop. It walks DOWN only — the pane's own parents are tmux and
    herdr, which are not this fleet's cost.

    Three honesty notes, because all three are visible on screen as a number:

    - Bare workspaces have no checkout, so an agent in one is not counted.
    - `%CPU` from `ps` is not instantaneous. On macOS it is a decaying average over up to a
      minute of real time, on Linux an average over the process's whole life. Summed across
      a tree it can exceed 100 on a multi-core machine, which is why `Stats.cpu_cores` is
      published beside it.
    - Summed RSS counts a shared page once per process sharing it, so this is an upper
      bound on real memory rather than a measurement of it.

    Unprivileged `lsof` sees only the caller's own processes (see `live`'s module note),
    which is the right scope here — agents run as the caller — and is still narrower than
    "asked the machine".
    """
    if not roots:
        return None                             # nothing to be under: unknown, not zero
    procs = live.scan()
    if procs is None:
        return None
    table = _ps_table()
    if table is None:
        return None

    under = _resolved(roots)
    seeds = {p.pid for p in procs if _inside(p.cwd, under)}
    tree = _descendants(seeds, table)
    cpu = sum(table[pid][2] for pid in tree if pid in table)
    rss = sum(table[pid][1] for pid in tree if pid in table)
    return {"cpu": round(cpu, 1), "rss": rss * 1024, "count": len(tree)}


def _ps_table() -> Optional[dict]:
    """pid -> (ppid, rss_kb, pcpu) for every process, or **None** if `ps` would not say.

    Strict about the shape for `broker._parents`' reason: a line the parser did not
    understand is a line it does not understand, and skipping it would quietly shrink the
    fleet's measured memory rather than admitting the scan failed.
    """
    try:
        out = subprocess.run(list(_PS), capture_output=True, text=True,
                             timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    found = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) != 4:
            return None
        try:
            found[int(parts[0])] = (int(parts[1]), int(parts[2]), float(parts[3]))
        except ValueError:
            return None
    return found or None


def _resolved(roots: list[str]) -> set:
    """The checkout paths as `Path`s, resolved and unresolved both.

    Both, because the two sides come from different places: a checkout path is whatever
    herdr recorded, and a cwd is whatever `lsof` printed. Resolving is what makes
    `/tmp/...` and `/private/tmp/...` the same directory; keeping the raw one costs a set
    entry and covers a root that cannot be resolved at all because it has been deleted.
    """
    out = set()
    for r in roots:
        p = Path(r)
        out.add(p)
        try:
            out.add(p.resolve())
        except (OSError, RuntimeError):          # unreadable, or a symlink loop
            pass
    return out


def _inside(cwd: str, roots: set) -> bool:
    """Is `cwd` one of `roots` or under one? Component-wise, never `str.startswith`.

    Sibling worktrees genuinely nest as strings here — `.../fix-options-2` starts with
    `.../fix-options` — and `live.is_under` exists because of it. This is that comparison
    with the roots hoisted out: `is_under` resolves its root on every call, which is one
    filesystem walk per process per root and the difference between a 5 ms answer and a
    slow one.
    """
    p = Path(cwd)
    if p in roots:
        return True
    return any(parent in roots for parent in p.parents)


def _descendants(seeds: set, table: dict) -> set:
    """`seeds` and everything below them in the process tree. Cycle-safe.

    Cycle-safe for `broker._ancestry`'s reason rather than because a process table is
    expected to contain a loop: this runs on a background thread of a process that must
    keep drawing, and a hang there is invisible.
    """
    children: dict = {}
    for pid, (ppid, _rss, _cpu) in table.items():
        children.setdefault(ppid, []).append(pid)
    seen = set()
    queue = [pid for pid in seeds if pid in table]
    while queue:
        pid = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        queue.extend(children.get(pid, ()))
    return seen
