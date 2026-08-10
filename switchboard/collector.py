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

**It is also the thing that rings the doorbell, and it rings it by SPAWNING `sb`.**
A message to an agent that was mid-turn is held back rather than injected into its turn,
and until this, the only thing that ever re-rang it was the next `sb` command somebody
happened to run — so a parent whose last child reported while it was busy was never woken
at all, and mail to an idle agent sat for forty minutes (`2026-08-09-004538`,
`2026-08-09-035933`). This loop is the only thing in the fleet that ticks on its own, so
it is where that trigger belongs.

It does NOT call `flush_pending` itself, and that is the whole design of it: this process
is read-only and version-stale on purpose (see above), and both properties would be lost
the moment it wrote. It runs `sb` from PATH instead — a short-lived process of whatever
version is installed, which flushes at startup like every other `sb` command — so the
write is made by current code and this file keeps its two invariants. Nothing is imported
to do it and no state is kept: the snapshot it already has says whether anything is
waiting, and `DOORBELL_GAP` keeps a target that stays busy from costing a process a tick.

**It cannot become a daemon nobody owns.** Renderers stamp `panel/demand` as they draw,
and this exits once nothing has looked for `panel.collector_idle_exit` seconds. Closing
the last panel retires the collector within a minute; opening one starts another.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import signal
import subprocess
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
# The floor between two doorbell runs, in seconds. Not a tunable: it is the one number
# that decides how much a stuck target costs. Mail held back for an agent that stays busy
# stays pending tick after tick, so without a floor this would spawn a process every
# `INTERVAL` for as long as that agent works — and the latency being bought is "somebody
# is woken within seconds instead of never", which ten does as well as two.
DOORBELL_GAP = 10.0
# How long the spawned `sb` is given before it is given up on. It is one flush and a
# handful of herdr calls; anything past this is a herdr that is not answering, and waiting
# longer only stacks threads.
DOORBELL_TIMEOUT = 30.0


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
    # The doorbell, counted the same way and for the same reason: a trigger nobody can see
    # is indistinguishable from one that is not running. `doorbell_error` is kept apart
    # from `last_error` deliberately — an `sb` that will not run is not a stale snapshot,
    # and saying so on forty screens would be a lie about the data they are showing.
    doorbells: int = 0
    last_doorbell: Optional[float] = None
    doorbell_error: Optional[str] = None

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


def ring_doorbell(snap, state: State, db_path: Optional[Path]) -> bool:
    """Run `sb` so that whatever is waiting gets announced. -> whether one was started.

    The minimal trigger, and deliberately nothing more. It answers one question from the
    snapshot it already has — is anybody holding a message that has never been announced?
    — and if so runs one `sb` command. That command flushes the doorbell at startup like
    every `sb` command does, which is the entire mechanism; who is idle, who is busy, who
    is blocked and what is safe to ring are decisions `Broker.flush_pending` already
    makes, and duplicating any of them here would be a second opinion in a second process.

    It does not look at stalled agents, does not correct a state, and pings nobody. An
    agent that is idle without having reported is a different problem with a different
    answer (the reconciler, phase 3.5), and a half of it built here would be thrown away.

    `undelivered` and not `unread`: an agent that read its own inbox needs no doorbell,
    and the snapshot's `undelivered` is derived from the same pair `flush_pending` chases
    (`status._undelivered_counts`), so this cannot ask for a ring that will not happen.
    """
    now = panel.now()
    if state.last_doorbell is not None and now - state.last_doorbell < DOORBELL_GAP:
        return False
    if not any(a.undelivered for a in snap.agents):
        return False
    sb = shutil.which("sb")
    if sb is None:
        # Nothing to fall back to: running this module's own code would put the write back
        # in this process, which is the one thing the arrangement above exists to prevent.
        state.doorbell_error = "no `sb` on PATH — nothing can ring the doorbell"
        return False
    state.last_doorbell = now
    state.doorbells += 1
    # In a thread, because a tick is 24 ms and an `sb` command is not: the fleet's one
    # readout must not stutter every time somebody has mail. Daemon, so it can never hold
    # this process open, and it reaps its own child so the collector grows no zombies.
    threading.Thread(target=_run_doorbell, args=(sb, db_path, state),
                     daemon=True).start()
    return True


def _doorbell_cwd(db_path: Optional[Path]) -> Optional[str]:
    """Where to run `sb` — a WORK TREE, and not the `.git` the store lives in.

    `db_path` is `<git-common-dir>/agentflow/state.db`, so its grandparent is `.git`
    itself. `cli.main` calls `store.worktree_root()` for every verb and
    `git rev-parse --show-toplevel` fails inside a `.git` directory, so every doorbell
    since the mechanism was written died there before it did anything — one directory,
    on every machine, whatever was on PATH (`audit/phase1-acceptance-2.md` §3.3).

    The checkout is `.git`'s parent, except under `--separate-git-dir` or a relocated
    `.git`, where it is whatever `sb init` recorded — the same rule `store.main_checkout`
    follows, read from the file here rather than asked of `store` so that this half stays
    importless and cannot be the thing that makes the collector write (module note).
    """
    if db_path is None:
        return None
    store_dir = db_path.parent
    recorded = None
    try:
        recorded = json.loads((store_dir / "config.json").read_text()).get("main_checkout")
    except Exception:                          # no config yet, or unreadable — infer
        pass
    if recorded and Path(recorded).is_dir():
        return str(recorded)
    return str(store_dir.parent.parent)


def _run_doorbell(sb: str, db_path: Optional[Path], state: State) -> None:
    """The spawned half. Swallows everything: a doorbell that fails is a line in the
    counters, never a collector that dies."""
    cwd = _doorbell_cwd(db_path)
    try:
        p = subprocess.run([sb, "flush"], cwd=cwd, capture_output=True, text=True,
                           timeout=DOORBELL_TIMEOUT)
        state.doorbell_error = None if p.returncode == 0 else \
            (p.stderr or p.stdout or f"sb flush exited {p.returncode}").strip()[:200]
    except Exception as e:                     # noqa: BLE001 — never fatal, by design
        state.doorbell_error = str(e)[:200]


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
        ring_doorbell(snap, state, db_path)

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
