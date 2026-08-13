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
on the board: this process outlives the code it started with. It ticks against the
`status.py` and the `store.SCHEMA` string that existed when it was launched, so anything
it writes is written by a version nobody is running any more. `reap=False`
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
the moment it wrote. It spawns `sb` instead — a short-lived process that flushes at
startup like every other `sb` command — so the write is made by code running now and this
file keeps its two invariants. The `sb` it spawns is THIS checkout's `bin/sb` and not
whatever the pane's PATH resolves (`doorbell_sb`), so the doorbell cannot be defeated by
an unrelated build being installed. Nothing is imported to do it and no state is kept: the
snapshot it already has says whether anything is waiting, and `DOORBELL_GAP` keeps a
target that stays busy from costing a process a tick.

**It cannot become a daemon nobody owns.** Renderers stamp `panel/demand` as they draw,
and this exits once nothing has looked for `panel.collector_idle_exit` seconds. Closing
the last panel retires the collector within a minute; opening one starts another.

**It cannot keep running code that has been fixed, either.** Being version-stale is safe
for the store (above) and was never safe for the decisions — `ringable` and the
undelivered counts are `status.py`'s, imported once, so a doorbell fix could sit on disk
while the process ringing it used the old rule, which is what cost about four hours of
held mail on 2026-08-11. It now hashes its own `switchboard/*.py` every
`SOURCE_CHECK_GAP` seconds and, if that differs from what it started with, takes the exit
above (`source_signature`). A renderer starts a replacement within seconds, and the
replacement is a fresh import: the same retire-and-be-restarted mechanism, given a second
reason to fire.
"""

from __future__ import annotations

import dataclasses
import hashlib
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
#
# It is a floor and not a bound: it divides the cost of a stuck target, it does not end
# it. A target that stays stuck for hours — a blocked agent waiting on a person — costs a
# process every ten seconds for all of them, which is why that case is kept out of the
# trigger's work list entirely rather than merely rate-limited (`ring_doorbell`).
DOORBELL_GAP = 10.0
# How long the spawned `sb` is given before it is given up on. It is one flush and a
# handful of herdr calls; anything past this is a herdr that is not answering, and waiting
# longer only stacks threads.
DOORBELL_TIMEOUT = 30.0
# The floor between two source checks, in seconds. Not a tunable, for `DOORBELL_GAP`'s
# reason: it is the one number that decides how long a fix can be on disk and not in the
# process running it, and the latency being bought is "within a minute instead of never".
# Checking every tick would buy two seconds instead of forty and read the whole package
# thirty times a minute for it.
SOURCE_CHECK_GAP = 45.0
# The floor between two reconciler runs, in seconds, and the period at which a stall that
# is still there is looked at again. Two numbers because the trigger has two reasons to
# fire: a name that has newly gone stalled (the pass this item is held to — pinged within
# one cycle), and a sweep for the stall that has been there a while, which exists only so
# that an agent which woke, acted and stalled again is eventually seen even though the
# stalled SET never changed. The per-agent "once per stall" rule lives in
# `Broker.reconcile` where the store is; these two only decide how often a process is
# spawned to ask it.
RECONCILE_GAP = 10.0
RECONCILE_SWEEP = 600.0


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
    # What this process's own source looked like when it started, and when that was last
    # re-checked. Published for the same reason as the rest: a mechanism nobody can see is
    # indistinguishable from one that is not running, and `pid` changing after an edit is
    # what says this worked.
    source_signature: Optional[str] = None
    last_source_check: Optional[float] = None
    # The reconciler, counted like the doorbell and beside it because it is the same shape:
    # a trigger that spawns `sb`. `reconciled` is the set of stalled names the last run was
    # spawned for — a list rather than a set only because this dataclass is published as
    # JSON — and it is what makes a stall that nobody attends to cost one process every
    # `RECONCILE_SWEEP` instead of one every tick.
    reconciles: int = 0
    last_reconcile: Optional[float] = None
    reconcile_error: Optional[str] = None
    reconciled: list = dataclasses.field(default_factory=list)

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

    `ringable` and not `undelivered`, for the one case where that is not enough. Mail for
    a BLOCKED agent is undelivered and must stay that way — the agent is waiting on a
    person, not idle — so `flush_pending` looks at it, holds it, and changes nothing,
    every ten seconds, for as long as the human takes. Measured: 85 spawned processes for
    one block held thirteen minutes, bounded by nothing but the person
    (`audit/phase1-acceptance-4.md` §4). Nothing about the mail changes here — it stays
    held, still counted, still on the board — and nothing needs this trigger to deliver
    it, because the only thing that lifts a block is an `sb tell` from the human, which
    flushes in its own process. `AgentStatus.ringable` is the predicate and it lives in
    `status.py` beside the count it refines, so this and `flush_pending` cannot come to
    disagree about which mail a ring would move.
    """
    now = panel.now()
    if state.last_doorbell is not None and now - state.last_doorbell < DOORBELL_GAP:
        return False
    if not any(a.ringable for a in snap.agents):
        return False
    sb = doorbell_sb()
    if sb is None:
        # Nothing to fall back to: running this module's own code would put the write back
        # in this process, which is the one thing the arrangement above exists to prevent.
        state.doorbell_error = ("no `sb` in this checkout's `bin/` and none on PATH — "
                                "nothing can ring the doorbell")
        return False
    state.last_doorbell = now
    state.doorbells += 1
    # In a thread, because a tick is 24 ms and an `sb` command is not: the fleet's one
    # readout must not stutter every time somebody has mail. Daemon, so it can never hold
    # this process open, and it reaps its own child so the collector grows no zombies.
    threading.Thread(target=_run_sb, args=(sb, "flush", db_path, state, "doorbell"),
                     daemon=True).start()
    return True


def run_reconciler(snap, state: State, db_path: Optional[Path]) -> bool:
    """Run `sb reconcile` so that an agent which went quiet is told. -> whether one started.

    The doorbell's twin, deliberately built to the same rule: this asks one question of the
    snapshot it already has — is anybody stalled? — and if so spawns one `sb` command,
    which decides everything else. Who is exempt, who has already been pinged, and what a
    ping says are `Broker.reconcile`'s, running in a process on current code, for the
    reason the module note gives: this one is version-stale on purpose and must not be the
    place a rule lives (the four-hour doorbell incident was exactly that mistake).

    **Two triggers, and the second is why this is not just `DOORBELL_GAP` again.** Mail
    stops being pending once it is delivered, so the doorbell's work list empties itself; a
    stall does not. An agent that goes quiet and is never attended to stays `stalled` on
    every tick for the rest of the day, and a plain gap would spawn a process for it every
    ten seconds — the cost `ring_doorbell` designs out for blocked agents by keeping them
    out of the work list entirely. So the trigger fires on a stalled name this collector
    has not already spawned for, and otherwise only every `RECONCILE_SWEEP`. The sweep is
    not decoration: an agent that wakes on its ping, acts, and stalls again is the same
    name in the same set, and the sweep is the only thing that looks at it again.

    In-process memory, like `last_doorbell`: a replacement collector re-spawning once for
    a stall it did not see happen costs one process, and `Broker.reconcile`'s own once-per-
    stall rule is what stops that becoming a second ping.
    """
    now = panel.now()
    stalled = sorted(a.name for a in snap.agents if a.stalled)
    state.reconciled = [n for n in state.reconciled if n in stalled]
    if not stalled:
        return False
    fresh = [n for n in stalled if n not in state.reconciled]
    due = state.last_reconcile is None or now - state.last_reconcile >= RECONCILE_SWEEP
    if not fresh and not due:
        return False
    if state.last_reconcile is not None and now - state.last_reconcile < RECONCILE_GAP:
        return False
    sb = doorbell_sb()
    if sb is None:
        state.reconcile_error = ("no `sb` in this checkout's `bin/` and none on PATH — "
                                 "nothing can run the reconciler")
        return False
    state.last_reconcile = now
    state.reconciles += 1
    state.reconciled = stalled
    threading.Thread(target=_run_sb, args=(sb, "reconcile", db_path, state, "reconcile"),
                     daemon=True).start()
    return True


def doorbell_sb() -> Optional[str]:
    """Which `sb` the doorbell runs — THIS build's, not whatever is installed.

    THE PROBLEM, measured. `shutil.which("sb")` asks the board pane's PATH, and that PATH
    is one machine-wide symlink into the main checkout. So a collector running a branch's
    code rang the branch's doorbell by spawning a *different* build — and when the verb it
    needs is newer than the installed one, every ring dies in argparse. 55 doorbells in
    5.5 minutes, all failed, five reports left undelivered, until the collector was
    restarted by hand with the right `bin` on its PATH, after which everything landed in
    one tick (`audit/phase1-acceptance-3.md` §3.2-3.3).

    `_ready_pane` already solves this shape for a spawned agent's pane, but a board pane is
    nobody's agent and nothing pins it. The fix does not need a pin at all: this process
    IS the build, launched with the checkout on `PYTHONPATH` by `panel.ensure_collector`,
    so its own `__file__` names the checkout, and that checkout's `bin/sb` is the same
    file `_ready_pane` puts at the front of an agent's PATH. Naming it here removes the
    environment from the question entirely: no PATH, no symlink, no ordering, and a
    correct doorbell can no longer be defeated by an unrelated binary.

    PATH remains the fallback, and only that: a `switchboard` imported from somewhere with
    no `bin/sb` beside it (installed as a package, vendored) has nothing of its own to run,
    and the installed build is then the only `sb` it could have meant.
    """
    own = Path(__file__).resolve().parent.parent / "bin" / "sb"
    if os.access(own, os.X_OK):
        return str(own)
    return shutil.which("sb")


def source_signature() -> Optional[str]:
    """A hash of this checkout's `switchboard/*.py`. -> the digest, or None if unreadable.

    THE PROBLEM, measured. This process loads its code once, at the import that starts it,
    and then holds the repo's one collector lock for hours — so a fix can be on disk and
    not in the process running it, with nothing but every panel going quiet for a minute
    to end it. That is not hypothetical: a doorbell fix landed and a day-old collector kept
    ringing with pre-fix logic for about four hours on 2026-08-11.

    CONTENT, not a commit. `git rev-parse HEAD` answers "has the ref moved", and the case
    that actually happens here is an edit saved in the working tree while somebody is
    iterating — uncommitted, and invisible to any ref. mtime would catch that too, a touch
    cheaper, but it has both failure directions (a touch with no edit restarts for nothing;
    a writer that preserves mtime never restarts) and content hashing has neither.

    THE WHOLE PACKAGE, not a file list. The stale logic in that incident was not in this
    file: `ring_doorbell` only asks `AgentStatus.ringable`, which is `status.py`'s, imported
    once and frozen exactly as hard. Every module this process's read path reaches is
    equally stale, and a hand-maintained list of them silently rots the next time a fix
    lands somewhere this file does not obviously touch. The package is under a megabyte;
    hashing all of it costs a few milliseconds every `SOURCE_CHECK_GAP` and removes the
    maintenance hazard rather than restating it.

    THIS process's own checkout (`__file__`), not a canonical one — `ensure_collector`
    launches the collector with the spawning renderer's checkout on `PYTHONPATH`, so which
    one that is depends on who won the election. The question being asked is "has the code
    I loaded changed underneath me", and `__file__` is the only thing that answers it. A
    *different* worktree of the same repo is different code, not this code gone stale.

    Same technique as `store._SCHEMA_HASH` — hash a source string, compare it to what was
    true earlier — pointed at `.py` files instead of the schema.
    """
    h = hashlib.sha256()
    try:
        for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
            h.update(p.name.encode())     # so a rename or a deletion counts as a change
            h.update(b"\0")
            h.update(p.read_bytes())
    except OSError:                       # mid-write, unreadable, gone — see `_source_changed`
        return None
    return h.hexdigest()[:16]


def _source_changed(state: State, gap: Optional[float] = None) -> bool:
    """Whether this process is now running code that is no longer what is on disk.

    Rate-limited off `state.last_source_check` the way `ring_doorbell` is off
    `last_doorbell`, and for the same kind of reason: nothing needs sub-doorbell latency
    here, and a floor keeps the read off the hot tick.

    Unreadable answers to either half — at startup or now — are read as "no", never as
    "changed". A file caught half-written by an editor would otherwise restart a collector
    for a version of the source nobody ever meant to run, twice: once for the truncated
    file and once for the whole one.
    """
    if state.source_signature is None:
        return False
    gap = SOURCE_CHECK_GAP if gap is None else gap   # read now, so a test can set it
    now = panel.now()
    if state.last_source_check is not None and now - state.last_source_check < gap:
        return False
    state.last_source_check = now
    current = source_signature()
    return current is not None and current != state.source_signature


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


def _run_sb(sb: str, verb: str, db_path: Optional[Path], state: State,
            which: str = "doorbell") -> None:
    """The spawned half, shared by both triggers. Swallows everything: a trigger that fails
    is a line in the counters, never a collector that dies.

    `which` names the counter the failure lands in — the two are kept apart for the reason
    `doorbell_error` is kept apart from `last_error`: a reconciler that will not run is a
    different fact from a doorbell that will not, and reporting either as the other would
    be a lie on forty screens."""
    cwd = _doorbell_cwd(db_path)
    field = f"{which}_error"
    try:
        p = subprocess.run([sb, verb], cwd=cwd, capture_output=True, text=True,
                           timeout=DOORBELL_TIMEOUT)
        setattr(state, field, None if p.returncode == 0 else
                (p.stderr or p.stdout or f"sb {verb} exited {p.returncode}").strip()[:200])
    except Exception as e:                     # noqa: BLE001 — never fatal, by design
        setattr(state, field, str(e)[:200])


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
        # The second trigger on the same loop, which is where DESIGN-TRUTH puts it
        # ("maybe the same loop `sb board` runs on"). Independent of the first: a stalled
        # agent usually has no mail pending, so a shared gate would mean each mechanism
        # only ran when the other had work.
        run_reconciler(snap, state, db_path)

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
    # What "my code" is, taken once, here, before the first tick — everything after this
    # is compared against it (`source_signature`).
    state.source_signature = source_signature()
    state.last_source_check = state.started_at
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
            # A second reason to take the exit that already exists, and nothing more: the
            # lock goes with the process, a renderer starts a replacement on its next tick
            # whatever the reason this one is gone, and the replacement is a fresh import.
            # It is checked here, at a tick boundary after `tick` has published, so no
            # panel can read a half-written envelope out of it.
            if _source_changed(state):
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
