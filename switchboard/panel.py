"""The panel mechanism, renderer half — one collector, many renderers.

A panel beside every agent means forty processes asking herdr and the store the same two
questions every two seconds, and drawing forty copies of one answer. This module is the
other shape: ONE process collects and publishes `Snapshot.as_dict()` — `sb status --json`
verbatim — to a file, and every pane reads that file. Polling goes from O(N) to O(1).

Cost is not why this exists. This is:

    A RENDERER IMPORTS `status` AND NOT `store`.

`store.connect()` re-stamps `meta`, CREATEs and ALTERs tables and backfills every agent
row, and when something missing can be given to no existing row it REBUILDS the store,
dropping every table `SCHEMA` declares (see `store._reconcile`, and
`tests/test_readonly.py` for each path reproduced). `1c10745` closed those paths for a
reader with `readonly=True`, and that fix is real — but it is a fix somebody has to keep
choosing, on every future edit, in every process that connects. The collector/renderer
split makes it structural instead: 39 of 40 panes hold no database handle and have no
import that could get them one. Read-only stops being a docstring claim and becomes a
fact about which modules are loaded, which `tests/test_panel.py::RendererImports` checks
both statically and by loading the module and looking at `sys.modules`.

So this module must never import `store`, at module scope or inside a function — not for
`repo_root`, not for `now()`, not for a type. Two consequences that look like detours and
are not:

- `git_common_dir` resolves `.git` in Python rather than calling `store.repo_root()`.
  That is also the only way the `git rev-parse --git-common-dir` subprocess stays off the
  renderer: it was measured at 12.3 ms of a 23.4 ms tick — more than herdr and the SQL
  put together — and forty renderers paying it every two seconds is most of what this
  design exists to delete. `tests/test_panel.py` pins it against `store.repo_root()` in a
  real repo and a linked worktree, and pins that a renderer spawns no subprocess at all.
- `now()` is `time.time()` here, not `store.now()`.

THE COLLECTOR IS A SEPARATE PROCESS (`switchboard/collector.py`), and this is a
considered departure from `.switchboard/design/split-tab.md` §3.2, which had every panel
process try the lock on every tick and collect in-process if it won. That version is
simpler by one process, and it cannot deliver the sentence above: a pane that may be
promoted to collector must be able to import `store`, so all forty keep the code path and
"39 of 40 cannot write" degrades to "39 of 40 happen not to". Making the collector its
own process is what makes the property literally true. The election is unchanged — an
`flock` on `collector.lock` — except that the collector holds it for its whole life
rather than for a tick, which also removes the failure the design had to argue away: a
lock cannot be left held by a process that has stopped collecting, because holding it and
collecting are now the same process's lifetime.

Two things follow from the collector outliving the pane that started it:

- **Takeover.** flock is held by an fd and the kernel drops it on exit, `kill -9`
  included. A renderer that finds the lock free knows there is no collector and starts
  one; the collector elects itself on the way up, so a duplicate started by two renderers
  in the same instant exits immediately instead of double-writing.
- **It must not become a daemon nobody owns.** Renderers stamp `demand` on every tick and
  the collector exits once nothing has looked for `panel.collector_idle_exit` seconds. A
  collector therefore cannot outlive the last panel by more than that, and nothing has to
  be installed, supervised, or cleaned up. This is the one write a renderer makes, it is
  a `utime` on an empty file that is not the store, and losing it costs one idle minute.

Staleness is the failure mode a shared cache introduces, so it is the one thing this
makes loud rather than quiet: `Reading.age` is measured from the last SUCCESSFUL collect,
never from the last write, so a collector that is running and failing goes stale on screen
instead of holding a wrong answer still. Forty panes quietly agreeing on old data is the
outcome worth spending code to prevent.
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import config
from . import status as status_mod

# `.git/agentflow` — the same directory the store lives in, resolved without `store`.
_STORE_DIRNAME = config.setting("paths.store_dirname")

# Everything the panel owns goes in one subdirectory, so it is one thing to look at and
# one thing to delete. Kept apart from `boards/` (the per-agent pane record), which is a
# different lifetime and a different owner.
PANEL_DIRNAME = "panel"

# `[panel]` in defaults/settings.toml.
STALE_AFTER = config.setting("panel.stale_after")
IDLE_EXIT = config.setting("panel.collector_idle_exit")
SPAWN_COOLDOWN = config.setting("panel.spawn_cooldown")

# An escape hatch for a spawner that already knows the directory — chiefly the collector,
# which is handed the path it was elected for rather than re-deriving it. Safe to trust
# from anywhere: everything a renderer does with it is a read.
DIR_ENV = "SB_PANEL_DIR"

# Bumped when the file's shape changes in a way an older renderer would misread. A
# renderer that does not recognise the version says so rather than drawing half of it.
FORMAT = 1


def now() -> float:
    """`time.time()`, spelled once. NOT `store.now()` — see the module note."""
    return time.time()


# ---------------------------------------------------------------------------
# Where the files are, without asking git
# ---------------------------------------------------------------------------


def git_common_dir(cwd: Optional[Path] = None) -> Path:
    """What `git rev-parse --git-common-dir` answers, without spawning git.

    The shared `.git` for this repo, valid from any worktree — the same directory
    `store.repo_root()` returns, and it must stay the same or a renderer would read a
    snapshot the collector is not writing. Pinned against `store.repo_root()` by test, in
    a plain checkout and in a linked worktree, because two ways of spelling one path is
    how the two of them come to disagree.

    Three shapes, which is all git has here:
      - `<root>/.git` is a directory          -> that is the common dir;
      - `<root>/.git` is a file, `gitdir: X`  -> a linked worktree; X is its private
        gitdir, and X/commondir points back at the shared one;
      - neither, all the way up               -> not a repo, and we say so.
    """
    start = Path(cwd).resolve() if cwd else Path.cwd().resolve()
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
    raise RuntimeError(f"not inside a git repo: {start}")


@dataclass(frozen=True)
class Paths:
    """The three files the mechanism is made of."""

    dir: Path

    @property
    def snapshot(self) -> Path:
        return self.dir / "snapshot.json"

    @property
    def lock(self) -> Path:
        """An flock. Whoever holds it IS the collector, for as long as it lives."""
        return self.dir / "collector.lock"

    @property
    def demand(self) -> Path:
        """mtime = when a renderer last looked. The collector's reason to keep running."""
        return self.dir / "demand"

    @classmethod
    def resolve(cls, cwd: Optional[Path] = None) -> "Paths":
        override = os.environ.get(DIR_ENV)
        if override:
            return cls(Path(override))
        return cls(git_common_dir(cwd) / _STORE_DIRNAME / PANEL_DIRNAME)


# ---------------------------------------------------------------------------
# The file: written whole or not at all
# ---------------------------------------------------------------------------


def publish(paths: Paths, payload: dict) -> None:
    """Replace the snapshot atomically. A reader mid-write gets the PREVIOUS good one.

    `os.replace` on the same filesystem is a rename, which is atomic: a reader either
    opens the old inode or the new one, never a file being filled in. Forty readers at
    2 Hz against a writer at 0.5 Hz makes a torn read a certainty rather than a risk if
    this is written in place, and a torn read of JSON is a traceback in a raw terminal.

    The temporary carries the writer's pid so two collectors that overlap for the instant
    it takes the loser to notice the lock cannot scribble on each other's tmp file.

    fsync before the rename: without it a crash can leave the new name pointing at a file
    whose contents have not landed, which is a torn read with extra steps. One fsync every
    two seconds, fleet-wide.
    """
    paths.dir.mkdir(parents=True, exist_ok=True)
    tmp = paths.dir / f"snapshot.json.{os.getpid()}.tmp"
    data = json.dumps(payload, separators=(",", ":"))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(paths.snapshot))


@dataclass
class Reading:
    """What one renderer knows after looking at the file once."""

    snap: status_mod.Snapshot
    collector: dict                       # the counters — see collector.State
    age: Optional[float] = None           # since the last SUCCESSFUL collect; None = never
    error: Optional[str] = None           # why there is nothing to draw

    @property
    def stale(self) -> bool:
        """Old enough to say so. `None` age counts: never-collected is not fresh."""
        return self.age is None or self.age > STALE_AFTER

    @property
    def note(self) -> str:
        """The one line the renderer puts on screen about the panel itself.

        Ranked, and only ever one, for the same reason `board.note` is: whatever is most
        wrong wins. Staleness outranks a herdr hiccup because a stale snapshot means the
        herdr line itself may be describing a minute ago.
        """
        if self.error:
            return self.error
        last = (self.collector or {}).get("last_error")
        if self.age is None:
            return f"collector has not read the tree yet{f' — {last}' if last else ''}"
        if self.stale:
            return (f"snapshot {status_mod.fmt_age(int(self.age))} old"
                    f"{f' — {last}' if last else ''}")
        if self.snap.herdr_error:
            return (f"herdr unreachable ({self.snap.herdr_error}) — "
                    f"alive and stalled are unknown")
        return ""


def read(paths: Paths, *, at: Optional[float] = None) -> Reading:
    """Read the published snapshot. Never raises.

    A panel that tracebacks into a raw terminal is worse than one that says it cannot see
    anything, so every failure below becomes a line on screen — same contract the board's
    own `snapshot()` had before the store moved out from under it.
    """
    at = now() if at is None else at
    try:
        raw = paths.snapshot.read_bytes()
    except FileNotFoundError:
        return Reading(_empty(), {}, None,
                       "no panel snapshot yet — no collector has published one")
    except OSError as e:
        return Reading(_empty(), {}, None, f"snapshot unreadable: {e}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        # Should be impossible through `publish`, and is exactly what a half-written file
        # would look like, so it is reported rather than swallowed.
        return Reading(_empty(), {}, None, f"snapshot is not readable JSON: {e}")

    if payload.get("format") != FORMAT:
        return Reading(_empty(), payload.get("collector") or {}, None,
                       f"snapshot format {payload.get('format')!r} — this panel reads "
                       f"{FORMAT}; the collector is running different code")

    meta = payload.get("collector") or {}
    try:
        snap = snapshot_from_dict(payload.get("snapshot") or {})
    except (TypeError, KeyError, AttributeError) as e:
        return Reading(_empty(), meta, None, f"snapshot does not fit this reader: {e}")

    collected = meta.get("collected_at")
    age = None if collected is None else max(0.0, at - collected)
    return Reading(snap, meta, age)


def _empty() -> status_mod.Snapshot:
    return status_mod.Snapshot(now=0, agents=[])


# ---------------------------------------------------------------------------
# The format: `Snapshot.as_dict()`, and its inverse
# ---------------------------------------------------------------------------
#
# The wire format is `sb status --json` verbatim, nested under one key so the collector's
# counters sit BESIDE it rather than inside it. That is worth more than the convenience:
# the panel and `--json` become one contract with one set of tests, and `sb status --json`
# gains a documented meaning as "the thing every panel is drawing".
#
# `from_dict` lives here rather than in `status.py` on purpose — `status.py` owns the
# model, this module owns the file. The risk that buys is drift: a field added to
# `AgentStatus` that this never learns to carry. It is closed by reading the field list
# off the dataclass itself, and by a round-trip test that asserts every declared field
# survives, so adding a field to `status.py` without touching this fails loudly here.

_AGENT_FIELDS = tuple(f.name for f in dataclasses.fields(status_mod.AgentStatus))
_SNAP_FIELDS = tuple(f.name for f in dataclasses.fields(status_mod.Snapshot))


def agent_from_dict(d: dict) -> status_mod.AgentStatus:
    """The nineteen stored fields back into the dataclass.

    The derived five — `blocked`, `at_prompt`, `finished`, `needs_human`,
    `waiting_to_be_rung` — are dropped and recomputed by the properties. Reading them back
    would let a renderer draw a rule that a collector running older code decided, which is
    the same class of bug as a long-lived board reaping on stale heuristics.
    """
    return status_mod.AgentStatus(**{k: d[k] for k in _AGENT_FIELDS if k in d})


def snapshot_from_dict(d: dict) -> status_mod.Snapshot:
    """The inverse of `Snapshot.as_dict`, which is not a plain field dump.

    Two fields do not come back from where they went out, and both are pinned by test:
    `hidden` is published inside `counts` (where `sb status --json` puts it, and that is
    the contract, not a mistake to correct here), and `now` is absent from an envelope a
    collector wrote before it managed a single collect. `now=0` for that case is what lets
    a panel draw the empty screen and the reason on it rather than raising into raw mode.
    """
    kw = {k: d[k] for k in _SNAP_FIELDS if k in d and k not in ("agents", "hidden")}
    kw.setdefault("now", 0)
    counts = d.get("counts") or {}
    if "hidden" in counts:
        kw["hidden"] = counts["hidden"]
    return status_mod.Snapshot(agents=[agent_from_dict(a) for a in d.get("agents") or []],
                               **kw)


def envelope(snapshot: dict, collector: dict) -> dict:
    return {"format": FORMAT, "snapshot": snapshot, "collector": collector}


# ---------------------------------------------------------------------------
# Election, and keeping exactly one collector up
# ---------------------------------------------------------------------------


def acquire(paths: Paths) -> Optional[int]:
    """Try to become the collector. -> an fd holding the lock, or None if one is up.

    `LOCK_EX | LOCK_NB`, so this never blocks a renderer's draw loop. The fd IS the lock:
    the kernel drops it when the process exits, `kill -9` and a herdr restart included, so
    there is no stale lock to time out and no cleanup to get wrong. The caller must keep
    the fd open for as long as it means to hold the lock — `release` exists for the caller
    that only wanted to ask.
    """
    paths.dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(paths.lock), os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:                        # BlockingIOError: somebody is collecting
        os.close(fd)
        return None
    # Whose it is, for a human reading the directory. Not load-bearing: the lock is the
    # flock, never the contents, so a stale pid in here decides nothing.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        pass
    return fd


def release(fd: Optional[int]) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def collector_running(paths: Paths) -> bool:
    """Is anyone holding the lock? Asked by taking it and giving it straight back.

    Creates nothing. That matters because `sb doctor` asks this, and a diagnostic that
    conjures a `panel/` directory and a lock file in a repo where no panel has ever run
    would be reporting on a state it had just invented — the same objection
    `store._connect_readonly` makes about a reader creating an empty store. A lock file
    that is not there is proof enough that nobody holds it.
    """
    if not paths.lock.exists():
        return False
    try:
        fd = os.open(str(paths.lock), os.O_WRONLY)        # no O_CREAT
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:                                       # somebody is collecting
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def want(paths: Paths) -> None:
    """Say a renderer is still looking. The collector's only reason to keep running.

    `utime` on an empty file, never the store. If this is lost the collector retires a
    minute early and the next tick of any panel starts another one, so the failure costs
    one blank refresh.
    """
    try:
        paths.dir.mkdir(parents=True, exist_ok=True)
        with open(paths.demand, "a"):
            pass
        os.utime(paths.demand, None)
    except OSError:
        pass


def demand_age(paths: Paths, *, at: Optional[float] = None) -> Optional[float]:
    """Seconds since a renderer last looked, or None if none ever has."""
    try:
        return max(0.0, (now() if at is None else at) - paths.demand.stat().st_mtime)
    except OSError:
        return None


def ensure_collector(paths: Paths, *, cwd: Optional[Path] = None) -> bool:
    """Start a collector if there is none. -> whether one was launched.

    Called by every renderer on every tick, which is what makes takeover free: the holder
    dying releases the lock, and the next panel to tick sees it free and starts a
    replacement. Two renderers racing here both launch, and the loser exits on its own
    election — so the race costs one process that lives for a few milliseconds, and no
    renderer has to coordinate with any other.

    Detached (`start_new_session`) so it is not killed by the pane that happened to start
    it, and silenced because there is no terminal it could usefully write to — a
    collector's errors belong in the snapshot, where forty panes can see them, not in one
    pane's scrollback.

    `PYTHONPATH` carries the checkout, and it is not optional. `switchboard` is not
    installed — `bin/sb` puts the checkout on `sys.path` itself — so `-m` in a child with a
    different cwd cannot import it, and the collector dies before it can publish the error
    saying why. Every panel then shows "no collector has published one" forever with
    nothing to point at. The child must run the same code as the renderer that started it
    in any case, so naming the parent's package directory is the correct thing to pass and
    not merely a workaround.
    """
    if collector_running(paths):
        return False
    checkout = str(Path(__file__).resolve().parent.parent)
    existing = os.environ.get("PYTHONPATH")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "switchboard.collector"],
            cwd=str(cwd) if cwd else None,
            env={**os.environ, DIR_ENV: str(paths.dir),
                 "PYTHONPATH": f"{checkout}{os.pathsep}{existing}" if existing else checkout},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        # No collector and no way to start one. The snapshot goes stale and every panel
        # says so, which is the honest outcome and the one this design is loudest about.
        return False
    return True


class Supervisor:
    """One renderer's side of keeping a collector up: `ensure_collector`, rate-limited.

    Without the limit, a collector that cannot start — no python, a broken checkout —
    would be re-spawned by forty renderers twice a second forever. With it, the whole
    fleet's worst case is one failed spawn per panel per `panel.spawn_cooldown`.
    """

    def __init__(self, paths: Paths, *, cwd: Optional[Path] = None,
                 cooldown: float = SPAWN_COOLDOWN):
        self.paths = paths
        self.cwd = cwd
        self.cooldown = cooldown
        self._last = 0.0

    def tick(self, *, at: Optional[float] = None) -> bool:
        at = now() if at is None else at
        want(self.paths)
        if at - self._last < self.cooldown:
            return False
        self._last = at
        return ensure_collector(self.paths, cwd=self.cwd)


# ---------------------------------------------------------------------------
# What `sb doctor` says about all this
# ---------------------------------------------------------------------------


def doctor_line(paths: Optional[Paths] = None, *, at: Optional[float] = None) -> str:
    """One line: is the panel everyone is looking at actually fresh?

    This is what the design chose INSTEAD of an `on_event` on the collector's `Herdr`.
    That would have made the panel a store writer on every tick — one `herdr` event per
    2 s per board, ~1.1 MB/hour/board, which for a single board is 4.5x the entire
    existing event log per shift and for forty is ~1 GB/day with `sb log` unreadable
    underneath it. The counters are published in the snapshot, which the collector is
    writing anyway, at zero extra writes; `doctor` reads that file. It also answers a
    question `on_event` could not: whether the thing on forty screens is current.
    """
    try:
        paths = Paths.resolve() if paths is None else paths
    except (RuntimeError, OSError) as e:      # `doctor` must report, never traceback
        return f"panel  cannot locate the panel directory: {e}"
    at = now() if at is None else at
    r = read(paths, at=at)
    c = r.collector or {}
    if not c:
        return f"panel  no collector — {r.error or 'nothing published'}"

    up = "1 up" if collector_running(paths) else "0 up (nobody holds the lock)"
    bits = [f"pid {c.get('pid', '?')} {up}",
            f"{c.get('polls', 0)} polls",
            f"{c.get('errors', 0)} errors"]
    if c.get("tick_ms") is not None:
        bits.append(f"last tick {c['tick_ms']:.0f} ms")
    bits.append("never collected" if r.age is None
                else f"{status_mod.fmt_age(int(r.age))} ago")
    line = "panel  " + ", ".join(bits)
    if r.stale:
        line += f"\n       STALE — {r.note}"
    elif c.get("last_error"):
        line += f"\n       last error: {c['last_error']}"
    return line


def doctor_dict(paths: Optional[Paths] = None, *, at: Optional[float] = None) -> dict:
    """The same, for `--json`."""
    try:
        paths = Paths.resolve() if paths is None else paths
    except (RuntimeError, OSError) as e:
        return {"up": False, "age": None, "stale": True, "error": str(e)}
    at = now() if at is None else at
    r = read(paths, at=at)
    return {"up": collector_running(paths), "age": r.age, "stale": r.stale,
            "error": r.error, **(r.collector or {})}


def _describe(paths: Optional[Paths] = None) -> int:
    """`python3 -m switchboard.panel` — what the fleet's panel is doing, from a shell."""
    print(doctor_line(paths))
    return 0


if __name__ == "__main__":
    sys.exit(_describe())
