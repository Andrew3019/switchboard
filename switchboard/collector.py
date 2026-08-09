"""The panel mechanism, collecting half — the one process that touches the store.

Exactly one of these runs per repo. It is elected by an `flock` it holds for its whole
life, it collects the tree every `display.board_refresh` seconds, and it publishes
`Snapshot.as_dict()` to `panel/snapshot.json`, where every panel reads it. See
`switchboard/panel.py` for why the split exists at all; the short version is that it is
what lets 39 of 40 panes have no import that could reach a write.

This module is the 40th. It is where `store` is allowed, and everything about it is
arranged so that being the only writer-capable process in the fleet costs as little as
possible and is as visible as possible.

**`readonly=True` and `reap=False` are load-bearing here, not tidy-ups.** They are the
two arguments that moved here with the connect, and the reason is the same one they had
on the board: this process outlives the code it started with. It ticks for hours against
the `status.py` and the `store.SCHEMA` string that existed when the human opened a panel,
so anything it writes is written by a version nobody is running any more. `reap=False`
stops `collect` ending an agent's turn (`status._record_gone`); `readonly=True` stops
`connect` migrating the schema, which is the larger of the two — when something missing
can be given to no existing row it REBUILDS the store, dropping every table `SCHEMA`
declares — and the one a flag on `collect` could not reach. Both remain verified end to
end by `tests/test_readonly.py`, which follows them here.

**The `git rev-parse` is paid once per collector, not once per tick.** `store.connect()`
reaches `db_path()` -> `repo_root()` -> `git rev-parse --git-common-dir`, measured at
12.3 ms of a 23.4 ms tick — more than the herdr call and all of the SQL together, asking
a question whose answer is fixed for the life of the process. It is resolved once at
startup and the path handed to `connect(path=...)` from then on, so a tick spawns one
subprocess (herdr) instead of two. Renderers pay it zero times: `panel.git_common_dir`
answers the same question in Python.

**Errors are published, not fatal, and never overwrite good data with nothing.** A tick
that fails keeps the last good snapshot, bumps `errors`, records `last_error` — and
leaves `collected_at` where it was, so the age every panel prints keeps growing. A
collector that is up and failing therefore reads as forty screens saying "snapshot 40s
old — herdr unreachable", which is the truth, rather than forty screens holding a wrong
answer perfectly still.

**It cannot become a daemon nobody owns.** Renderers stamp `panel/demand` as they draw,
and this exits once nothing has looked for `panel.collector_idle_exit` seconds. Closing
the last panel retires the collector within a minute; opening one starts another.
"""

from __future__ import annotations

import dataclasses
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config
from . import panel
from . import status as status_mod

INTERVAL = config.setting("display.board_refresh")


@dataclass
class State:
    """The counters, published in the snapshot every tick.

    This is the design's answer to putting an `on_event` on the collector's `Herdr`, and
    it is a refusal with a number behind it: one `herdr` event per tick is ~1.1 MB/hour
    for ONE collector — 4.5x the entire existing event log per shift — and the whole point
    of the fleet-wide panel is that there could be forty of them writing it. These
    counters cost nothing: they ride in a file that is being written anyway. `sb doctor`
    reads them through `panel.doctor_line`.
    """

    pid: int
    started_at: float
    polls: int = 0
    errors: int = 0
    # The last SUCCESSFUL collect. Age is measured from this and never from `wrote_at`,
    # which is what makes a running-and-failing collector show up as stale.
    collected_at: Optional[float] = None
    wrote_at: Optional[float] = None
    tick_ms: Optional[float] = None
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def snapshot(db_path: Optional[Path] = None):
    """-> (Snapshot, error). One collection. Never raises.

    Moved here from `board.snapshot()` unchanged in substance: this is now the process
    that connects every two seconds, so the guarantee about what such a process may do
    belongs where the connect is. `tests/test_readonly.py::CollectorTick` is the same test
    it was, pointed at the same code in its new home.

    A store too old or too new for this collector therefore surfaces as "could not read
    the tree: no such column: agents.branch" on forty screens, which is what a viewer
    should say — rather than being quietly migrated to suit a stale reader.
    """
    from . import store                    # the one module the renderers may not have
    from .herdr import Herdr

    try:
        db = store.connect(path=db_path, readonly=True) if db_path is not None \
            else store.connect(readonly=True)
    except Exception as e:                 # not a repo, no store yet, unreadable, ...
        return None, f"store unavailable: {e}"
    try:
        return status_mod.collect(db, Herdr(), reap=False), None
    except Exception as e:
        return None, f"could not read the tree: {e}"
    finally:
        db.close()


def tick(paths: panel.Paths, state: State, db_path: Optional[Path],
         last_good: Optional[dict]) -> Optional[dict]:
    """One collect-and-publish. -> the snapshot dict now published.

    Publishing happens on the failure path too, and that is deliberate: a panel that can
    see the counters can say WHY it is stale, and a panel that can see nothing can only
    say that it sees nothing.
    """
    t0 = time.perf_counter()
    state.polls += 1
    snap, err = snapshot(db_path)
    state.tick_ms = (time.perf_counter() - t0) * 1000
    at = panel.now()

    if err is not None:
        state.errors += 1
        state.last_error, state.last_error_at = err, at
    else:
        last_good = snap.as_dict()
        state.collected_at = at
        # Not cleared on success: `sb doctor` wants the most recent error even on a
        # collector that has recovered, and `errors` is what says whether it is current.

    state.wrote_at = at
    panel.publish(paths, panel.envelope(last_good or {}, state.as_dict()))
    return last_good


def run(*, cwd: Optional[Path] = None, interval: float = INTERVAL,
        idle_exit: float = panel.IDLE_EXIT, max_ticks: Optional[int] = None) -> int:
    """Be the collector, if nobody else is. -> exit code.

    `3` means "somebody else already is", which is the normal outcome of two renderers
    racing to start one and is not a failure. The lock is held by the fd for the whole
    of this function, so it is released by the kernel however this process ends —
    a clean return, a signal, or `kill -9` — and the next renderer's tick starts a
    replacement. There is no stale lock and nothing to time out.
    """
    paths = panel.Paths.resolve(cwd)
    fd = panel.acquire(paths)
    if fd is None:
        return 3

    stop = _stop_on_signal()
    state = State(pid=os.getpid(), started_at=panel.now())
    last_good: Optional[dict] = None
    try:
        # The one `git rev-parse` this process will ever make. If it fails there is no
        # store to read and nothing will fix that by retrying, so it is published as the
        # error every panel shows and this exits rather than spinning on it.
        db_path: Optional[Path] = None
        try:
            from . import store
            db_path = store.db_path(cwd)
        except Exception as e:
            state.errors += 1
            state.last_error, state.last_error_at = f"store unavailable: {e}", panel.now()
            state.wrote_at = panel.now()
            panel.publish(paths, panel.envelope({}, state.as_dict()))
            return 1

        ticks = 0
        while not stop.is_set():
            last_good = tick(paths, state, db_path, last_good)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            if _nobody_is_looking(paths, state, idle_exit):
                break
            stop.wait(interval)
        return 0
    finally:
        panel.release(fd)


def _nobody_is_looking(paths: panel.Paths, state: State, idle_exit: float) -> bool:
    """Whether every panel has gone. See the module note on not becoming a daemon.

    A `demand` file that has never been stamped is read as "the renderer that started me
    has not drawn yet", not as "nobody wants this" — otherwise a collector that wins the
    election a few milliseconds before its renderer's first draw would exit immediately
    and be restarted forever. Our own start time is the floor.
    """
    age = panel.demand_age(paths)
    since_start = panel.now() - state.started_at
    if age is None:
        return since_start > idle_exit
    return age > idle_exit


def _stop_on_signal():
    """SIGTERM/SIGINT end the current tick and return, so the lock is released cleanly
    and the last snapshot on disk is a whole one."""
    stop = threading.Event()

    def handler(_sig, _frame):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, handler)
        except ValueError:                 # not the main thread — a test, in practice
            pass
    return stop


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
