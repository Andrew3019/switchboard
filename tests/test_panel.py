"""The panel mechanism: one collector, many renderers.

The first class is the point of the whole design and the rest is plumbing that has to
hold underneath it. `RendererImports` fails if a renderer ever gains a path to `store` —
statically, so a lazy `from . import store` inside a function is caught, and dynamically,
so a transitive one through some other module is caught too. That test IS the guarantee
that 39 of 40 panes cannot migrate a schema, reap an agent or drop a table; every other
statement of it is a docstring somebody has to keep choosing to honour.

What the rest pins, in the order a failure would hurt:

- the snapshot file is `sb status --json` and survives a round trip with every field;
- a reader mid-write gets the previous good snapshot, never a truncated one;
- the collector's lock is released by the kernel when it dies, so a renderer takes over;
- a collector that is up and failing goes STALE on screen instead of holding a wrong
  answer still;
- a renderer resolves its own paths without spawning `git`, and the collector spawns it
  once per process rather than once per tick.
"""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import collector, panel, status, store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Every module a panel process loads on the way to drawing a screen. `board` is the UI and
# `panel` is its data path; if either can reach the store, forty panes can.
RENDERER_MODULES = ("switchboard/panel.py", "switchboard/board.py")


def a_snapshot(*names, herdr_error=None, hidden=0, now=1000):
    return status.Snapshot(
        now=now, herdr_error=herdr_error, hidden=hidden,
        agents=[status.AgentStatus(
            name=n, role="worker", parent=None, depth=0, state="working",
            herdr_state="working", alive=True, stalled=False, gone=False, unread=0,
            age=10, idle=5, last_activity=now - 5, workspace="api", task="do it",
            blocked_why=None, summary=None) for n in names])


def published(paths, snap, **counters):
    """Put a snapshot on disk the way the collector would."""
    meta = {"pid": 1, "started_at": 0.0, "polls": 1, "errors": 0,
            "collected_at": panel.now(), "wrote_at": panel.now(), "tick_ms": 12.0,
            "last_error": None, "last_error_at": None}
    meta.update(counters)
    panel.publish(paths, panel.envelope(snap.as_dict(), meta))
    return meta


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = panel.Paths(Path(self.tmp.name) / "panel")


# ---------------------------------------------------------------------------


class RendererImports(unittest.TestCase):
    """The load-bearing property, and the only test here that is not about plumbing.

    `store.connect()` re-stamps `meta`, ALTERs tables and backfills every agent row, and
    when a table is missing it drops `agents`, `messages` and `events` — 53 agent rows and
    162 messages in the probe that found it. `1c10745` closed all three for a reader, and
    that fix holds (tests/test_readonly.py). But it is a fix that has to be chosen again on
    every future edit of every process that connects, and a panel per agent is forty such
    processes. This is the version that cannot be un-chosen by accident.
    """

    def test_a_renderer_does_not_load_the_store_even_transitively(self):
        """Importing the whole renderer must not pull `switchboard.store` into sys.modules.

        A fresh interpreter, because this test's own process has imported the store to run
        the rest of the file.
        """
        for module in ("switchboard.panel", "switchboard.board"):
            with self.subTest(module=module):
                out = subprocess.run(
                    [sys.executable, "-c",
                     f"import {module}, sys; print('switchboard.store' in sys.modules)"],
                    cwd=str(ROOT), capture_output=True, text=True, check=True)
                self.assertEqual(out.stdout.strip(), "False")

    def test_no_renderer_module_names_store_anywhere_in_its_source(self):
        """The static half, and the one that catches the regression that matters.

        `from . import store` inside a function is invisible to the test above until that
        function is called — and the whole claim is that no such function exists, not that
        nobody calls it. So: no import of `store` at any depth of the syntax tree.
        """
        for rel in RENDERER_MODULES:
            with self.subTest(module=rel):
                tree = ast.parse((ROOT / rel).read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [a.name.split(".")[-1] for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [a.name for a in node.names] + [(node.module or "")]
                    else:
                        continue
                    self.assertNotIn(
                        "store", names,
                        f"{rel}:{node.lineno} imports `store`. A renderer must not be able "
                        f"to reach a write — see switchboard/panel.py.")

    def test_the_collector_is_the_one_process_that_may(self):
        """The counterpart, so the rule above reads as a split and not as a blanket ban:
        somebody has to open the store, and it is exactly one process."""
        src = (ROOT / "switchboard/collector.py").read_text()
        self.assertIn("from . import store", src)


# ---------------------------------------------------------------------------


class PathsWithoutGit(unittest.TestCase):
    """A renderer must find its snapshot without `git rev-parse --git-common-dir`.

    That subprocess was measured at 12.3 ms of a 23.4 ms tick — more than the herdr call
    and every query put together — asking a question whose answer is fixed for the life of
    the process. Forty renderers paying it twice a second is most of what this design
    exists to delete, so `panel.git_common_dir` answers it in Python. The risk that buys is
    two spellings of one path, and these are what stop them disagreeing.
    """

    def _repo(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        root.mkdir()
        for cmd in (["init", "-q", "-b", "main"],
                    ["-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(["git", *cmd], cwd=str(root), check=True,
                           capture_output=True)
        return root

    def test_it_agrees_with_store_in_a_plain_checkout(self):
        root = self._repo()
        self.assertEqual(panel.git_common_dir(root), store.repo_root(root))

    def test_it_agrees_with_store_from_a_subdirectory(self):
        root = self._repo()
        sub = root / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(panel.git_common_dir(sub), store.repo_root(sub))

    def test_it_agrees_with_store_inside_a_linked_worktree(self):
        """The case that makes this more than a `.git` lookup: in a worktree `.git` is a
        FILE pointing at a private gitdir, and the shared directory is one more hop through
        `commondir`. Agents live in worktrees, so this is the normal case here, not the
        exotic one."""
        root = self._repo()
        wt = Path(root).parent / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(wt)],
                       cwd=str(root), check=True, capture_output=True)
        self.assertTrue((wt / ".git").is_file())
        self.assertEqual(panel.git_common_dir(wt), store.repo_root(wt))

    def test_resolving_a_renderer_path_spawns_nothing(self):
        """The claim itself, made unfalsifiable-by-accident: any subprocess at all fails
        this, so swapping `store.repo_root()` back in is caught."""
        root = self._repo()
        boom = mock.Mock(side_effect=AssertionError("a renderer spawned a subprocess"))
        with mock.patch("subprocess.run", boom), mock.patch("subprocess.Popen", boom):
            paths = panel.Paths.resolve(root)
            self.assertTrue(str(paths.snapshot).endswith("panel/snapshot.json"))

    def test_not_a_repo_says_so_rather_than_guessing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(RuntimeError):
            panel.git_common_dir(Path(tmp.name))


# ---------------------------------------------------------------------------


class TheFormatIsStatusJson(PanelTest):
    """`sb status --json` verbatim, so the panel and the JSON are one contract.

    `from_dict` lives in `panel.py` while `as_dict` lives in `status.py`, which is a place
    for the two to drift. These close it: the field list is read off the dataclass, so a
    field added to `AgentStatus` that the panel does not carry fails here rather than
    silently vanishing from forty screens.
    """

    def test_every_declared_field_survives_the_round_trip(self):
        import dataclasses
        a = a_snapshot("w1").agents[0]
        a.summary, a.undelivered, a.undelivered_age = "shipped it", 3, 90
        a.blocked_why, a.gone, a.stalled = "needs a key", True, True
        back = panel.agent_from_dict(json.loads(json.dumps(a.as_dict())))
        for f in dataclasses.fields(status.AgentStatus):
            self.assertEqual(getattr(back, f.name), getattr(a, f.name), f.name)

    def test_the_derived_flags_are_recomputed_not_replayed(self):
        """A renderer must not draw a rule a collector running older code decided — the
        same argument `reap=False` makes about ending a turn."""
        a = a_snapshot("w1").agents[0]
        d = a.as_dict()
        d.update(needs_human=True, at_prompt=True, finished=True, blocked=True,
                 waiting_to_be_rung=True)
        back = panel.agent_from_dict(d)
        self.assertFalse(back.needs_human)
        self.assertFalse(back.at_prompt)
        self.assertFalse(back.finished)

    def test_the_snapshot_carries_every_one_of_its_own_fields_too(self):
        """`hidden` is the one that got away: `as_dict` publishes it inside `counts`, so a
        naive field-for-field inverse silently drops it and every panel reports nothing
        filtered. Enumerated off the dataclass so the next field added cannot."""
        import dataclasses
        s = a_snapshot("w1", "w2", herdr_error="herdr: connection refused", hidden=4)
        back = panel.snapshot_from_dict(json.loads(json.dumps(s.as_dict())))
        for f in dataclasses.fields(status.Snapshot):
            if f.name == "agents":
                self.assertEqual([a.name for a in back.agents], ["w1", "w2"])
            else:
                self.assertEqual(getattr(back, f.name), getattr(s, f.name), f.name)

    def test_an_envelope_written_before_the_first_collect_still_draws(self):
        """A collector that failed on tick one has no snapshot to publish, and a panel
        must draw the reason rather than raise into a raw terminal."""
        back = panel.snapshot_from_dict({})
        self.assertEqual((back.now, back.agents, back.hidden), (0, [], 0))

    def test_the_counts_a_panel_draws_come_out_the_same(self):
        """The header line every pane shows is computed from the rebuilt snapshot, so the
        file and `sb status` cannot disagree about how many agents are trouble."""
        s = a_snapshot("w1", "w2")
        s.agents[0].gone = True
        s.agents[1].unread = 2
        published(self.paths, s)
        back = panel.read(self.paths).snap
        self.assertEqual(back.counts, s.counts)
        self.assertEqual(status.summary_line(back), status.summary_line(s))

    def test_a_format_from_different_code_is_refused_not_half_drawn(self):
        panel.publish(self.paths, {"format": 999, "snapshot": {}, "collector": {}})
        r = panel.read(self.paths)
        self.assertIn("running different code", r.note)
        self.assertEqual(r.snap.agents, [])


# ---------------------------------------------------------------------------


class NeverATornRead(PanelTest):
    """Forty readers at 2 Hz against a writer at 0.5 Hz makes a half-written file a
    certainty rather than a risk, and a torn read of JSON is a traceback in a raw
    terminal."""

    def test_a_reader_racing_the_writer_only_ever_sees_a_whole_snapshot(self):
        sizes = list(range(1, 60))
        stop = threading.Event()
        seen: list[int] = []
        errors: list[str] = []

        def write():
            while not stop.is_set():
                for n in sizes:
                    published(self.paths, a_snapshot(*[f"w{i}" for i in range(n)]))
                    if stop.is_set():
                        return

        published(self.paths, a_snapshot("w0"))
        t = threading.Thread(target=write, daemon=True)
        t.start()
        try:
            for _ in range(400):
                r = panel.read(self.paths)
                if r.error:
                    errors.append(r.error)
                else:
                    seen.append(len(r.snap.agents))
        finally:
            stop.set()
            t.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertTrue(seen)
        # Every read landed on a snapshot somebody actually published, not on a prefix of
        # one: a truncated file cannot parse, and a short one would show a count nobody
        # wrote.
        self.assertTrue(set(seen) <= set(sizes) | {1})

    def test_the_temporary_is_never_left_where_a_renderer_looks(self):
        published(self.paths, a_snapshot("w1"))
        self.assertEqual([p.name for p in self.paths.dir.iterdir() if ".tmp" in p.name], [])

    def test_a_truncated_file_is_reported_rather_than_raised(self):
        """`publish` cannot produce this, which is why it is worth pinning: if it ever
        does, a panel says so on screen instead of tracebacking into raw mode."""
        self.paths.dir.mkdir(parents=True, exist_ok=True)
        self.paths.snapshot.write_text('{"format": 1, "snapsh')
        r = panel.read(self.paths)
        self.assertIn("not readable JSON", r.note)
        self.assertEqual(r.snap.agents, [])


# ---------------------------------------------------------------------------


class Election(PanelTest):
    """Whoever holds the flock is the collector, for as long as it lives."""

    def test_only_one_collector_can_hold_it(self):
        first = panel.acquire(self.paths)
        self.addCleanup(panel.release, first)
        self.assertIsNotNone(first)
        self.assertIsNone(panel.acquire(self.paths))
        self.assertTrue(panel.collector_running(self.paths))

    def test_a_second_collector_exits_instead_of_double_writing(self):
        """Two renderers racing to start one is normal and must be harmless: the loser
        finds the lock taken and stops, rather than publishing a second stream of
        snapshots over the first."""
        held = panel.acquire(self.paths)
        self.addCleanup(panel.release, held)
        with mock.patch.dict(os.environ, {panel.DIR_ENV: str(self.paths.dir)}):
            self.assertEqual(collector.run(max_ticks=1), 3)
        self.assertFalse(self.paths.snapshot.exists())

    def test_the_kernel_drops_the_lock_when_the_holder_is_killed(self):
        """The whole takeover story, and the design's one un-prototyped claim. A holder
        that dies without unwinding — `kill -9`, a herdr restart, a crash — must not leave
        the fleet with a lock nobody can take and no collector.
        """
        code = ("import sys, time; sys.path.insert(0, %r);"
                "from switchboard import panel;"
                "p = panel.Paths(__import__('pathlib').Path(%r));"
                "fd = panel.acquire(p); print('held' if fd else 'no', flush=True);"
                "time.sleep(60)") % (str(ROOT), str(self.paths.dir))
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                             text=True)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.kill)
        self.assertEqual(p.stdout.readline().strip(), "held")
        self.assertIsNone(panel.acquire(self.paths))     # genuinely held, cross-process

        p.send_signal(signal.SIGKILL)
        p.wait(timeout=10)
        for _ in range(100):                             # the kernel is not instantaneous
            fd = panel.acquire(self.paths)
            if fd is not None:
                panel.release(fd)
                return
            time.sleep(0.05)
        self.fail("the lock outlived the process that held it — no renderer can take over")

    def test_a_renderer_starts_one_only_when_there_is_none(self):
        with mock.patch.object(panel.subprocess, "Popen") as popen:
            held = panel.acquire(self.paths)
            self.assertFalse(panel.ensure_collector(self.paths))
            popen.assert_not_called()
            panel.release(held)
            self.assertTrue(panel.ensure_collector(self.paths))
            self.assertEqual(popen.call_args.args[0][1:],
                             ["-m", "switchboard.collector"])

    def test_a_collector_that_cannot_start_is_not_respawned_every_tick(self):
        """Otherwise a broken checkout means forty panes forking twice a second forever."""
        with mock.patch.object(panel.subprocess, "Popen") as popen:
            sup = panel.Supervisor(self.paths, cooldown=30.0)
            sup.tick(at=1000.0)
            sup.tick(at=1001.0)
            sup.tick(at=1002.0)
            self.assertEqual(popen.call_count, 1)
            sup.tick(at=1040.0)
            self.assertEqual(popen.call_count, 2)


# ---------------------------------------------------------------------------


class Staleness(PanelTest):
    """The one failure a shared snapshot introduces, and so the one it is loudest about."""

    def test_a_fresh_snapshot_says_nothing(self):
        published(self.paths, a_snapshot("w1"))
        self.assertEqual(panel.read(self.paths).note, "")
        self.assertFalse(panel.read(self.paths).stale)

    def test_an_old_snapshot_says_how_old_rather_than_passing_as_now(self):
        at = panel.now()
        published(self.paths, a_snapshot("w1"), collected_at=at - 40)
        r = panel.read(self.paths, at=at)
        self.assertTrue(r.stale)
        self.assertIn("snapshot 40s old", r.note)
        # ...and still hands the rows over, because a stale tree beside a loud label is
        # more use than a blank pane.
        self.assertEqual([a.name for a in r.snap.agents], ["w1"])

    def test_a_collector_that_is_up_and_failing_reads_as_stale_with_the_reason(self):
        at = panel.now()
        published(self.paths, a_snapshot("w1"), collected_at=at - 30, wrote_at=at,
                  errors=14, last_error="could not read the tree: no such column: branch")
        r = panel.read(self.paths, at=at)
        self.assertTrue(r.stale)                 # measured from the last SUCCESS...
        self.assertIn("30s old", r.note)
        self.assertIn("no such column", r.note)  # ...and it says why

    def test_a_collector_that_never_managed_a_collect_does_not_look_fresh(self):
        published(self.paths, status.Snapshot(now=0, agents=[]), collected_at=None,
                  errors=1, last_error="store unavailable: no store yet at /x/state.db")
        r = panel.read(self.paths)
        self.assertTrue(r.stale)
        self.assertIn("has not read the tree yet", r.note)
        self.assertIn("no store yet", r.note)

    def test_no_snapshot_at_all_says_a_collector_is_coming(self):
        r = panel.read(self.paths)
        self.assertTrue(r.stale)
        self.assertIn("no collector has published one", r.note)
        self.assertEqual(r.snap.agents, [])

    def test_staleness_outranks_a_herdr_hiccup(self):
        """A stale snapshot means the herdr line inside it may be describing a minute
        ago, so it cannot be the thing on screen."""
        at = panel.now()
        published(self.paths, a_snapshot("w1", herdr_error="connection refused"),
                  collected_at=at - 30)
        self.assertIn("snapshot 30s old", panel.read(self.paths, at=at).note)

    def test_a_fresh_snapshot_still_reports_herdr(self):
        published(self.paths, a_snapshot("w1", herdr_error="connection refused"))
        self.assertIn("herdr unreachable", panel.read(self.paths).note)


# ---------------------------------------------------------------------------


class CountersInsteadOfEvents(PanelTest):
    """The design's refusal of `on_event` on the collector's `Herdr`, with the number
    behind it: one herdr event per tick is ~1.1 MB/hour/collector, which is 4.5x the
    entire existing event log per shift, and `sb log` becomes unreadable underneath a
    fleet of them. The counters ride in a file that is being written anyway."""

    def test_the_collector_neither_logs_an_event_nor_asks_herdr_to(self):
        """Tokens rather than words, so the docstring that explains the refusal does not
        trip the test that enforces it."""
        src = (ROOT / "switchboard/collector.py").read_text()
        self.assertNotIn("log_event(", src)
        self.assertNotIn("on_event=", src)

    def test_doctor_reads_the_counters_out_of_the_snapshot(self):
        published(self.paths, a_snapshot("w1"), pid=4242, polls=4210, errors=0,
                  tick_ms=24.0)
        line = panel.doctor_line(self.paths)
        for bit in ("pid 4242", "4210 polls", "0 errors", "last tick 24 ms"):
            self.assertIn(bit, line)

    def test_doctor_says_when_nobody_holds_the_lock(self):
        published(self.paths, a_snapshot("w1"))
        self.assertIn("0 up", panel.doctor_line(self.paths))
        fd = panel.acquire(self.paths)
        self.addCleanup(panel.release, fd)
        self.assertIn("1 up", panel.doctor_line(self.paths))

    def test_doctor_is_loud_about_a_stale_panel(self):
        """The question `on_event` could not have answered: is the thing on forty screens
        actually current?"""
        at = panel.now()
        published(self.paths, a_snapshot("w1"), collected_at=at - 300, errors=9,
                  last_error="herdr unreachable")
        line = panel.doctor_line(self.paths, at=at)
        self.assertIn("STALE", line)
        self.assertIn("9 errors", line)

    def test_doctor_survives_there_being_no_panel_at_all(self):
        self.assertIn("no collector", panel.doctor_line(self.paths))
        self.assertFalse(panel.doctor_dict(self.paths)["up"])


# ---------------------------------------------------------------------------


class CollectorLoop(PanelTest):
    """The tick itself: what it publishes, what it does on failure, and when it stops."""

    def _run(self, snapshot_returns, **kw):
        """Run the collector against a stubbed collect, in-process."""
        calls = iter(snapshot_returns)
        with mock.patch.dict(os.environ, {panel.DIR_ENV: str(self.paths.dir)}), \
             mock.patch.object(collector, "snapshot", lambda *a, **k: next(calls)), \
             mock.patch.object(store, "db_path", lambda *a, **k: Path("/x/state.db")):
            return collector.run(interval=0.0,
                                 max_ticks=kw.pop("max_ticks", len(snapshot_returns)),
                                 **kw)

    def test_a_tick_publishes_the_tree_and_its_counters(self):
        self.assertEqual(self._run([(a_snapshot("w1", "w2"), None)]), 0)
        r = panel.read(self.paths)
        self.assertEqual([a.name for a in r.snap.agents], ["w1", "w2"])
        self.assertEqual(r.collector["polls"], 1)
        self.assertEqual(r.collector["errors"], 0)
        self.assertEqual(r.collector["pid"], os.getpid())
        self.assertIsNotNone(r.collector["tick_ms"])
        self.assertFalse(r.stale)

    def test_a_failing_tick_keeps_the_last_good_tree_and_lets_it_age(self):
        """Blanking the panel on one bad tick would be worse than showing the last good
        one — but showing it as current would be worse than either, so `collected_at`
        stays where it was and every pane starts counting."""
        at = panel.now()
        self._run([(a_snapshot("w1"), None),
                   (None, "could not read the tree: no such column: agents.branch")])
        r = panel.read(self.paths, at=at + 30)
        self.assertEqual([a.name for a in r.snap.agents], ["w1"])   # still drawable
        self.assertEqual(r.collector["errors"], 1)
        self.assertIn("no such column", r.collector["last_error"])
        self.assertTrue(r.stale)                                    # and visibly old
        self.assertIn("no such column", r.note)

    def test_a_first_tick_that_fails_publishes_the_reason_rather_than_nothing(self):
        self._run([(None, "store unavailable: no store yet at /x/state.db")])
        r = panel.read(self.paths)
        self.assertIsNone(r.collector["collected_at"])
        self.assertIn("no store yet", r.note)

    def test_the_lock_is_held_for_the_whole_run_and_released_after(self):
        seen = []

        def peek(*_a, **_k):
            seen.append(panel.collector_running(self.paths))
            return (a_snapshot("w1"), None)

        with mock.patch.dict(os.environ, {panel.DIR_ENV: str(self.paths.dir)}), \
             mock.patch.object(collector, "snapshot", peek), \
             mock.patch.object(store, "db_path", lambda *a, **k: Path("/x/state.db")):
            collector.run(interval=0.0, max_ticks=2)
        self.assertEqual(seen, [True, True])
        self.assertFalse(panel.collector_running(self.paths))

    def test_it_retires_when_no_panel_has_looked_for_a_while(self):
        """It outlives the pane that started it on purpose. This is what stops that being
        a daemon nobody owns: close every panel and it goes away by itself."""
        panel.want(self.paths)
        os.utime(self.paths.demand, (0, panel.now() - 3600))
        self.assertEqual(self._run([(a_snapshot("w1"), None)] * 5, idle_exit=60.0,
                                   max_ticks=5), 0)
        self.assertEqual(panel.read(self.paths).collector["polls"], 1)   # stopped after 1

    def test_it_keeps_going_while_a_panel_is_still_drawing(self):
        panel.want(self.paths)
        self._run([(a_snapshot("w1"), None)] * 3, idle_exit=60.0, max_ticks=3)
        self.assertEqual(panel.read(self.paths).collector["polls"], 3)

    def test_a_collector_started_before_its_renderer_draws_does_not_retire_at_once(self):
        """`demand` is stamped by the first draw, which happens a few milliseconds AFTER
        the renderer starts the collector. Reading "never stamped" as "nobody wants this"
        would make every panel a restart loop."""
        self.assertFalse(self.paths.demand.exists())
        self._run([(a_snapshot("w1"), None)] * 3, idle_exit=60.0, max_ticks=3)
        self.assertEqual(panel.read(self.paths).collector["polls"], 3)


class GitIsPaidOncePerCollector(PanelTest):
    """`store.connect()` reaches `git rev-parse --git-common-dir`, 12.3 ms of a 23.4 ms
    tick. One collector pays it instead of forty boards — but only if it pays it once."""

    def test_the_path_is_resolved_at_startup_and_not_re_derived_every_tick(self):
        seen = []
        with mock.patch.dict(os.environ, {panel.DIR_ENV: str(self.paths.dir)}), \
             mock.patch.object(collector, "snapshot",
                               lambda p=None: (seen.append(p), (a_snapshot("w1"), None))[1]), \
             mock.patch.object(store, "db_path",
                               mock.Mock(return_value=Path("/x/state.db"))) as dbp:
            collector.run(interval=0.0, max_ticks=5)
        self.assertEqual(dbp.call_count, 1)
        # ...and every tick was handed that path, so `connect` never looks it up again.
        self.assertEqual(seen, [Path("/x/state.db")] * 5)


if __name__ == "__main__":
    unittest.main()
