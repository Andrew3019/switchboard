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

from switchboard import collector, panel, stats, status, store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Every module a panel process loads on the way to drawing a screen. `board` is the UI and
# `panel` is its data path; if either can reach the store, forty panes can.
RENDERER_MODULES = ("switchboard/panel.py", "switchboard/board.py",
                    "switchboard/richboard.py")


def a_snapshot(*names, herdr_error=None, hidden=0, now=1000, stalled=False):
    return status.Snapshot(
        now=now, herdr_error=herdr_error, hidden=hidden,
        agents=[status.AgentStatus(
            name=n, role="worker", parent=None, depth=0, state="working",
            herdr_state="idle" if stalled else "working", alive=True, stalled=stalled,
            gone=False, unread=0,
            age=10, idle=5, last_activity=now - 5, workspace="api", task="do it",
            blocked_why=None, summary=None) for n in names])


def a_git_repo(root: Path) -> Path:
    """A real checkout, so path code is exercised against `git` and not against a mock."""
    root.mkdir(parents=True, exist_ok=True)
    for cmd in (["init", "-q", "-b", "main"],
                ["-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *cmd], cwd=str(root), check=True, capture_output=True)
    return root


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

    `store.connect()` re-stamps `meta`, CREATEs and ALTERs tables and backfills every agent
    row, and when something missing can be given to no existing row it rebuilds the store,
    dropping every table `SCHEMA` declares — 53 agent rows and 162 messages in the probe
    that found it. `1c10745` closed those paths for a reader, and that fix holds
    (tests/test_readonly.py). But it is a fix that has to be chosen again on every future
    edit of every process that connects, and a panel per agent is forty such processes.
    This is the version that cannot be un-chosen by accident.
    """

    def test_a_renderer_does_not_load_the_store_even_transitively(self):
        """Importing the whole renderer must not pull `switchboard.store` into sys.modules.

        A fresh interpreter, because this test's own process has imported the store to run
        the rest of the file.
        """
        for module in ("switchboard.panel", "switchboard.board",
                       "switchboard.richboard"):
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

    def test_no_renderer_module_reaches_the_stats_collector(self):
        """The same rule, for the other module that would break it.

        `stats.collect()` reads the store — through a handle its caller opens, so it would
        need the import banned above — and shells out to `git`, `lsof` and `ps`. A renderer
        that imported it would break the second half of the property (a renderer spawns no
        subprocess at all) even without a connection to hand it. The numbers reach forty
        panes as an already-computed dict in the snapshot instead: `collector.FleetStats`
        makes the call, `panel.envelope` carries it, `Reading.stats` is what a renderer
        reads.
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
                        "stats", names,
                        f"{rel}:{node.lineno} imports `stats`. A renderer draws the fleet "
                        f"numbers out of `panel.Reading.stats`; collecting them is the "
                        f"collector's — see switchboard/stats.py.")

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
        return a_git_repo(Path(tmp.name) / "repo")

    def test_it_agrees_with_store_in_a_plain_checkout(self):
        root = self._repo()
        self.assertEqual(panel.git_common_dir(root), store.repo_root(root))

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
        # Set to something, not left at its default: this field is the join key a board
        # highlights its own tab's agent by (`board.Locator`), and a None that survives as
        # None would pass this test while every board silently highlighted nothing.
        a.pane_id = "w1:p3"
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

    def test_the_collector_is_told_where_to_import_switchboard_from(self):
        """`switchboard` is not installed — `bin/sb` puts the checkout on `sys.path`
        itself — so `-m` in a child with a different cwd cannot import it. Without this
        the collector dies before it can publish the error saying why, and every panel
        shows "no collector has published one" forever with nothing to point at.
        `TwoRealProcesses` caught exactly that; this pins it without spawning anything.

        WHICH checkout is `WhichCheckoutTheCollectorRuns`' subject: it is the repo's
        primary worktree, not this one, whenever the two differ.
        """
        with mock.patch.object(panel.subprocess, "Popen") as popen:
            panel.ensure_collector(self.paths, cwd=Path("/"))
        env = popen.call_args.kwargs["env"]
        self.assertIn(str(panel.canonical_checkout(self.paths) or ROOT),
                      env["PYTHONPATH"].split(os.pathsep))
        self.assertEqual(env[panel.DIR_ENV], str(self.paths.dir))

    def test_an_existing_pythonpath_is_kept_rather_than_replaced(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/somewhere/else"}), \
             mock.patch.object(panel.subprocess, "Popen") as popen:
            panel.ensure_collector(self.paths)
        parts = popen.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(parts, [str(panel.canonical_checkout(self.paths) or ROOT),
                                 "/somewhere/else"])

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


class WhichCheckoutTheCollectorRuns(PanelTest):
    """One repo, one collector, one canonical copy of the code — whoever elects it.

    The election is a race between forty renderer panes standing in forty worktrees, most
    of them on old branches. Launching the collector from the winner's checkout let that
    race decide which code drew every board in the fleet: on 2026-08-16 a worktree older
    than `switchboard/stats.py` kept winning and every board said `not measured` about a
    feature that had been on `main` for hours. The collector must run the primary
    worktree's code no matter who starts it.
    """

    def _checkout(self, root: Path) -> Path:
        """A git repo that also looks like a switchboard checkout."""
        a_git_repo(root)
        (root / "switchboard").mkdir(exist_ok=True)
        (root / "switchboard" / "collector.py").write_text("# primary\n")
        return root

    def _tmp(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_a_linked_worktree_resolves_to_the_primary_and_not_to_itself(self):
        """The bug, in one assertion."""
        base = self._tmp()
        root = self._checkout(base / "repo")
        wt = base / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(wt)],
                       cwd=str(root), check=True, capture_output=True)
        self.assertTrue((wt / ".git").is_file())         # genuinely a linked worktree
        self.assertEqual(panel.primary_worktree(wt), root.resolve())

    def test_a_plain_clone_is_its_own_primary(self):
        """The single-checkout case, which must behave exactly as it always did."""
        root = self._checkout(self._tmp() / "repo")
        self.assertEqual(panel.primary_worktree(root), root.resolve())

    def test_somewhere_that_is_not_a_switchboard_checkout_is_refused(self):
        """A bare repo, or a `.git` living apart from its working tree, would otherwise
        put a directory belonging to nobody on the collector's `sys.path`."""
        root = a_git_repo(self._tmp() / "repo")          # no `switchboard/` in it
        self.assertIsNone(panel.primary_worktree(root))

    def test_outside_a_repo_it_says_it_does_not_know(self):
        self.assertIsNone(panel.primary_worktree(self._tmp()))

    def test_it_redirects_a_collector_serving_its_own_repo(self):
        """The live case: forty worktrees, one shared `.git`, one panel directory."""
        paths = panel.Paths.resolve(ROOT)
        got = panel.canonical_checkout(paths)
        self.assertEqual(got, panel.primary_worktree(ROOT))
        self.assertIsNotNone(got)
        self.assertTrue((got / "switchboard" / "collector.py").is_file())
        if (ROOT / ".git").is_file():                    # these tests run in a worktree
            self.assertNotEqual(got, ROOT)

    def test_it_leaves_a_collector_for_a_different_repo_where_it_was(self):
        """The collector reads its store from its own cwd, so moving it to a checkout of
        another repo would quietly serve that repo's fleet to these panes. A switchboard
        checkout driving somebody else's repo keeps today's launch."""
        elsewhere = self._checkout(self._tmp() / "other")
        paths = panel.Paths.resolve(elsewhere)
        self.assertIsNone(panel.canonical_checkout(paths))

    def test_the_child_both_stands_in_the_primary_and_imports_from_it(self):
        """cwd and `PYTHONPATH` are one decision, not two. `-m` puts cwd at the FRONT of
        the child's `sys.path`, so a collector standing in the electing worktree would
        import that worktree's `switchboard` however good its `PYTHONPATH` was."""
        primary = self._checkout(self._tmp() / "repo")
        with mock.patch.object(panel, "canonical_checkout", lambda *a, **k: primary), \
             mock.patch.object(panel.subprocess, "Popen") as popen:
            self.assertTrue(panel.ensure_collector(self.paths, cwd=Path("/elsewhere")))
        self.assertEqual(popen.call_args.kwargs["cwd"], str(primary))
        self.assertEqual(popen.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0],
                         str(primary))

    def test_an_unknowable_primary_launches_from_this_checkout_rather_than_not_at_all(self):
        """A fleet with a wrong-code collector still beats a fleet with none."""
        with mock.patch.object(panel, "canonical_checkout", lambda *a, **k: None), \
             mock.patch.object(panel.subprocess, "Popen") as popen:
            self.assertTrue(panel.ensure_collector(self.paths, cwd=Path("/elsewhere")))
        self.assertEqual(popen.call_args.kwargs["cwd"], "/elsewhere")
        self.assertEqual(popen.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0],
                         str(ROOT))

    def test_a_tick_that_finds_a_collector_running_pays_nothing_for_this(self):
        """The lookup belongs to the launch, which happens once per collector, and not to
        the tick, which happens twice a second in forty panes."""
        boom = mock.Mock(side_effect=AssertionError("resolved on the hot path"))
        held = panel.acquire(self.paths)
        self.addCleanup(panel.release, held)
        with mock.patch.object(panel, "canonical_checkout", boom):
            self.assertFalse(panel.Supervisor(self.paths).tick(at=1000.0))


class Staleness(PanelTest):
    """The one failure a shared snapshot introduces, and so the one it is loudest about."""

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

    def test_doctor_is_loud_about_a_stale_panel(self):
        """The question `on_event` could not have answered: is the thing on forty screens
        actually current?"""
        at = panel.now()
        published(self.paths, a_snapshot("w1"), collected_at=at - 300, errors=9,
                  last_error="herdr unreachable")
        line = panel.doctor_line(self.paths, at=at)
        self.assertIn("STALE", line)
        self.assertIn("9 errors", line)

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

    def test_it_times_each_summons_across_ticks_and_publishes_the_age(self):
        """The debounce's memory is this loop's, and the published `needs_for` is the only
        way a renderer can know a summons is a second old rather than an hour.

        Two ticks ten seconds apart on the same stalled agent: the second says ten.
        """
        self._run([(a_snapshot("w1", stalled=True, now=1000), None),
                   (a_snapshot("w1", stalled=True, now=1010), None)])
        a = panel.read(self.paths).snap.agents[0]
        self.assertEqual(a.needs_for, 10)

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


class TheFleetNumbersRideAlong(PanelTest):
    """The board's top section: collected here, drawn there, and a plain dict in between.

    `stats.collect()` reads the store and shells out to `git`, `lsof` and `ps` — both
    halves of what `RendererImports` above says a renderer must not do — so the numbers
    take the same route the tree does: one process computes them, forty read a file. What
    is worth pinning about the middle of that pipe is exactly two things, and they are the
    two below: that `None` still means "unknown" at the far end, and that the one expensive
    call never lands on the tick every pane is waiting for.
    """

    def _stats(self, **kw) -> dict:
        """A reading with real field names, taken off the dataclass rather than typed out,
        so a renamed field fails here instead of quietly becoming a key nobody reads."""
        return stats.Stats(**kw).as_dict()

    def test_a_collector_that_publishes_none_is_read_as_unknown_and_not_as_broken(self):
        """Why `panel.FORMAT` is not bumped for this key: during a rollout some panes read
        a file an older collector wrote. A missing key must be "we do not know yet", not
        forty screens refusing to draw."""
        panel.publish(self.paths, {"format": panel.FORMAT, "snapshot": {},
                                   "collector": {"pid": 1, "collected_at": panel.now()}})
        r = panel.read(self.paths)
        self.assertEqual(r.stats, {})
        self.assertIsNone(r.error)

    def test_the_first_tick_does_not_wait_for_the_cold_scan(self):
        """The reason the call is primed on a thread instead of made in `tick`.

        The three store counts are table scans of an un-indexed `created_at` — ~370 ms on
        the first call in a process, against ~0.07 ms warm. Paid on the tick that publishes
        the first snapshot, that is a third of a second in which no pane can draw anything
        at all, for three numbers at the top of the screen. So a read before the scan lands
        answers "unknown" at once, and picks the numbers up once it has.
        """
        gate = threading.Event()
        landed = self._stats(turns_last_hour=41)

        class Slow(collector.FleetStats):
            samples = 0

            def _sample(self):
                Slow.samples += 1
                gate.wait(10)
                return dict(landed)

        fleet = Slow(Path("/x/state.db"))
        t0 = time.perf_counter()
        first = fleet.read()
        self.assertLess(time.perf_counter() - t0, 0.5)      # did not wait for the scan
        self.assertIsNone(first["turns_last_hour"])         # and said so rather than 0
        self.assertEqual(Slow.samples, 1)                   # one primer, on its own thread

        gate.set()
        for _ in range(200):
            if fleet.read()["turns_last_hour"] == 41:
                break
            time.sleep(0.01)
        self.assertEqual(fleet.read()["turns_last_hour"], 41)

    def test_a_tick_publishes_them_beside_the_tree_with_unknown_still_unknown(self):
        """End to end through the loop, and the one thing a zero would silently ruin.

        `stats.py` is careful that `None` is never a zero — "no lines changed in the last
        hour" and "git would not answer" are different sentences, and only one of them is a
        measurement. Nothing on screen would look wrong if that distinction were flattened
        in transit, which is exactly why it is pinned rather than trusted.
        """
        landed = self._stats(turns_last_hour=41, spawns_last_hour=0, cpu_percent=317.5)

        class Stub:
            def prime(self):
                return False

            def read(self):
                return dict(landed)

        with mock.patch.object(collector, "FleetStats", lambda *a, **k: Stub()):
            CollectorLoop._run(self, [(a_snapshot("w1", "w2"), None)])
        r = panel.read(self.paths)
        self.assertEqual([a.name for a in r.snap.agents], ["w1", "w2"])   # tree undisturbed
        self.assertEqual(r.stats["turns_last_hour"], 41)
        self.assertEqual(r.stats["spawns_last_hour"], 0)          # a real, measured zero
        self.assertEqual(r.stats["cpu_percent"], 317.5)
        self.assertIn("code_added", r.stats)                      # present, and unknown —
        self.assertIsNone(r.stats["code_added"])                  # never dropped, never 0


class WhatAFasterBoardMayCost(PanelTest):
    """The guard on the interval: a cheap tick honours it, an expensive one backs off.

    `display.board_refresh` went from two seconds to half a second, and the renderers' side
    of that is free — a read of one small file. The collector's is not: measured at 57 ms
    per tick uncontended on the largest store in this fleet, and 146 ms with occasional
    ticks near a second on a machine under load. A fixed half-second gap at that price is
    two thirds of a core, forever, for a readout nobody is looking at that hard.
    """

    def test_a_cheap_tick_sleeps_the_whole_interval(self):
        self.assertEqual(collector._gap(0.5, 0.057), 0.5)

    def test_an_expensive_tick_gives_back_more_than_it_took(self):
        """The interval stops being a floor on the cost the moment honouring it would
        spend more than `MAX_DUTY` of this process's life collecting."""
        gap = collector._gap(0.5, 1.0)
        self.assertAlmostEqual(gap, 3.0)                                  # MAX_DUTY = 0.25
        self.assertLessEqual(1.0 / (1.0 + gap), collector.MAX_DUTY + 1e-9)

    def test_the_backoff_stays_inside_the_staleness_threshold(self):
        """A board that slows down must not become forty panes announcing a stale
        snapshot: the worst tick measured, backed off, is still younger than
        `panel.stale_after`."""
        worst = 1.11                                     # the slowest live tick sampled
        self.assertLess(worst + collector._gap(0.5, worst), panel.STALE_AFTER)


class TheCollectorNoticingItsOwnCodeChanged(PanelTest):
    """It holds the repo's one lock for hours and loads its code once, so a fix could be on
    disk and not in the process running it — about four hours of held mail on 2026-08-11.
    It now hashes its own `switchboard/*.py` and leaves through the existing exit if that
    differs from what it started with, so a renderer starts a fresh import."""

    def _run_with_signatures(self, sigs, **kw):
        """As `CollectorLoop._run`, plus a scripted `source_signature`. The first value is
        the one taken at startup; each later one answers one check."""
        calls = iter(sigs)
        with mock.patch.object(collector, "source_signature", lambda: next(calls)), \
             mock.patch.object(collector, "SOURCE_CHECK_GAP", 0.0):
            return CollectorLoop._run(self, [(a_snapshot("w1"), None)] * 20, **kw)

    def test_it_exits_on_the_tick_that_first_sees_different_source(self):
        """Exactly there and not a tick later: the whole value of this is that the next
        tick behaves per the new code."""
        rc = self._run_with_signatures(["old", "old", "new", "new"], max_ticks=9)
        self.assertEqual(rc, 0)
        self.assertEqual(panel.read(self.paths).collector["polls"], 2)
        self.assertFalse(panel.collector_running(self.paths))   # and the lock is back

    def test_an_unchanged_checkout_never_costs_a_restart(self):
        self._run_with_signatures(["same"] * 6, max_ticks=4)
        self.assertEqual(panel.read(self.paths).collector["polls"], 4)

    def test_the_signature_covers_the_whole_package_and_not_just_this_file(self):
        """`ring_doorbell` decides nothing itself — `ringable` is `status.py`'s, imported
        once and frozen exactly as hard. A fix there has to count as a change."""
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "switchboard"
            pkg.mkdir()
            for name in ("collector.py", "status.py"):
                (pkg / name).write_text("# v1\n")
            with mock.patch.object(collector, "__file__", str(pkg / "collector.py")):
                before = collector.source_signature()
                self.assertEqual(before, collector.source_signature())   # stable
                (pkg / "status.py").write_text("# v2 — the ringable fix\n")
                self.assertNotEqual(before, collector.source_signature())


class TheDoorbellTrigger(PanelTest):
    """The one loop in the fleet that ticks on its own is what rings the doorbell.

    A message held back because its target was mid-turn used to wait for the next `sb`
    command somebody happened to run — so a parent whose last child reported while it was
    busy was never woken at all. This is the minimal trigger for that and nothing else: it
    runs `sb`, which flushes at startup like every `sb` command, and every decision about
    who may be rung stays in `Broker.flush_pending`.
    """

    def setUp(self):
        super().setUp()
        self.ran: list[list[str]] = []
        # The thread runs its target here and now, so a test never races the doorbell.
        self.enterContext(mock.patch.object(
            collector.threading, "Thread",
            lambda target, args=(), **kw: mock.Mock(start=lambda: target(*args))))
        self.ran_cwd: list = []                # the directory each one was run FROM

        def record(argv, **kw):
            self.ran.append(argv)
            self.ran_cwd.append(kw.get("cwd"))
            return mock.Mock(returncode=0)

        self.enterContext(mock.patch.object(collector.shutil, "which", lambda n: "/bin/sb"))
        self.enterContext(mock.patch.object(collector.subprocess, "run", record))
        # Which `sb` gets picked is `WhichSbTheDoorbellRuns`'s subject, and it answers with
        # this checkout's real `bin/sb` — a path these tests would then have to know. They
        # are about WHEN it runs, so they take the PATH answer.
        self.enterContext(mock.patch.object(
            collector, "doorbell_sb", lambda: collector.shutil.which("sb")))

    def _snap(self, undelivered):
        snap = a_snapshot("w1")
        snap.agents[0].undelivered = undelivered
        return snap

    def test_mail_nobody_has_been_told_about_runs_sb(self):
        state = collector.State(pid=1, started_at=0.0)
        self.assertTrue(collector.ring_doorbell(self._snap(1), state, Path("/r/.sb/s.db")))
        self.assertEqual(self.ran, [["/bin/sb", "flush"]])
        self.assertEqual(state.doorbells, 1)
        self.assertIsNone(state.doorbell_error)

    def test_an_idle_fleet_costs_nothing(self):
        state = collector.State(pid=1, started_at=0.0)
        self.assertFalse(collector.ring_doorbell(self._snap(0), state, None))
        self.assertEqual((self.ran, state.doorbells), ([], 0))

    def test_a_target_that_stays_busy_does_not_cost_a_process_a_tick(self):
        """Mail held back stays pending, tick after tick. Without the floor this would
        spawn one `sb` every two seconds for as long as that agent keeps working."""
        state = collector.State(pid=1, started_at=0.0)
        collector.ring_doorbell(self._snap(1), state, None)
        self.assertFalse(collector.ring_doorbell(self._snap(1), state, None))
        self.assertEqual(len(self.ran), 1)

        state.last_doorbell -= collector.DOORBELL_GAP + 1      # ...and again once it lapses
        self.assertTrue(collector.ring_doorbell(self._snap(1), state, None))
        self.assertEqual(len(self.ran), 2)

    def test_a_blocked_agents_held_mail_does_not_cost_a_process_a_tick(self):
        """The floor divides the cost of a stuck target; it does not end it.

        Mail for a blocked agent is undelivered and stays that way — the agent is waiting
        on a person, not idle — so every tick rediscovers it, spawns `sb flush`, and
        `flush_pending` holds it again. Measured at 85 processes for one block held
        thirteen minutes, bounded by nothing but how long the human takes.
        """
        state = collector.State(pid=1, started_at=0.0)
        snap = self._snap(2)
        snap.agents[0].state = "blocked"
        for _ in range(3):
            self.assertFalse(collector.ring_doorbell(snap, state, None))
            state.last_doorbell = None                    # the floor is not what stops it
        self.assertEqual((self.ran, state.doorbells), ([], 0))

    def test_the_humans_answer_to_a_blocked_agent_still_rings(self):
        """The one ring `_ring` lets a block through, so it is the one the doorbell must
        still chase — the answer's own `sb tell` flushes, but a target that was mid-turn
        at that moment has nothing else coming."""
        state = collector.State(pid=1, started_at=0.0)
        snap = self._snap(2)
        snap.agents[0].state = "blocked"
        snap.agents[0].undelivered_answer = True
        self.assertTrue(collector.ring_doorbell(snap, state, None))
        self.assertEqual(self.ran, [["/bin/sb", "flush"]])

    def test_a_failing_sb_is_a_counter_and_not_a_stale_snapshot(self):
        """`last_error` is what every panel reads as "this data is old". A doorbell that
        will not run is a different complaint about perfectly good data."""
        state = collector.State(pid=1, started_at=0.0)
        with mock.patch.object(collector.subprocess, "run",
                               lambda *a, **k: mock.Mock(returncode=2, stderr="boom",
                                                         stdout="")):
            collector.ring_doorbell(self._snap(1), state, None)
        self.assertEqual(state.doorbell_error, "boom")
        self.assertIsNone(state.last_error)

    def test_with_no_sb_to_run_it_says_so_rather_than_writing_itself(self):
        """Falling back to this process's own code would put the write back in the one
        process that is read-only and version-stale on purpose."""
        state = collector.State(pid=1, started_at=0.0)
        with mock.patch.object(collector, "doorbell_sb", lambda: None):
            self.assertFalse(collector.ring_doorbell(self._snap(1), state, None))
        self.assertEqual((self.ran, state.doorbells), ([], 0))
        self.assertIn("nothing can ring the doorbell", state.doorbell_error)

    def test_sb_is_run_from_the_checkout_and_never_from_dot_git(self):
        """The store sits INSIDE `.git`, which is not a work tree. Running `sb` there
        made every doorbell die in `store.worktree_root()` before it did anything —
        one directory, on every machine, whatever was on PATH."""
        state = collector.State(pid=1, started_at=0.0)
        collector.ring_doorbell(self._snap(1), state,
                                Path("/r/.git/agentflow/state.db"))
        self.assertEqual(self.ran_cwd, ["/r"])

    def test_the_verb_it_runs_exists(self):
        """The collector spawns `sb flush` by name. If that verb is ever renamed, the
        trigger fails silently in a thread nobody is watching."""
        from switchboard import cli
        args = cli.build_parser().parse_args(["flush"])
        self.assertEqual(args.cmd, "flush")


class TheReconcilerTrigger(PanelTest):
    """T3 — the second trigger on the same loop (3.5).

    Same subject as the doorbell's tests above: WHEN a process is spawned, never what it
    then decides. Who is pinged, who is exempt and how often is `Broker.reconcile`'s, and
    that is tested where the store is (`tests/test_broker.py`).
    """

    def setUp(self):
        super().setUp()
        self.ran: list[list[str]] = []
        self.enterContext(mock.patch.object(
            collector.threading, "Thread",
            lambda target, args=(), **kw: mock.Mock(start=lambda: target(*args))))
        self.enterContext(mock.patch.object(
            collector.subprocess, "run",
            lambda argv, **kw: (self.ran.append(argv), mock.Mock(returncode=0))[1]))
        self.enterContext(mock.patch.object(collector, "doorbell_sb", lambda: "/bin/sb"))

    def sb_runs(self) -> list:
        """Only the spawns this trigger made. `collector.subprocess` is the one module
        object, so patching it catches every `git` anything else in the process runs."""
        return [a for a in self.ran if a[0] == "/bin/sb"]

    def _stalled(self, *names):
        snap = a_snapshot(*names)
        for a in snap.agents:
            a.stalled = True
        return snap

    def _gone(self, *names):
        snap = a_snapshot(*names)
        for a in snap.agents:
            a.gone = True
        return snap

    def test_a_death_spawns_sb_reconcile_with_nobody_stalled(self):
        """`sb reconcile` is the one unattended path that reaps (`cli.main`), so a dead
        agent has to be able to start one — otherwise the reaping waits behind a stalled
        agent that may not exist, and a dead child is recorded only when a person runs
        `sb status`.

        Gone names are deliberately NOT held in the `reconciled` memory the way a stall is:
        this work list empties itself the moment the row is written `failed`, and the
        repeat inside `GONE_CONFIRM_GRACE` is the debounce — a second reap-capable reading
        a minute after the first is what confirms the absence at all.
        """
        state = collector.State(pid=1, started_at=0.0)

        self.assertTrue(collector.run_reconciler(self._gone("w1"), state, None))
        self.assertEqual(self.sb_runs(), [["/bin/sb", "reconcile"]])
        self.assertEqual(state.reconciled, [])          # not remembered, unlike a stall

        state.last_reconcile -= collector.RECONCILE_GAP + 1
        self.assertTrue(collector.run_reconciler(self._gone("w1"), state, None))
        self.assertEqual(len(self.sb_runs()), 2)

        # And once the death is recorded the row is `failed`, so it is no longer gone and
        # the trigger goes quiet on its own.
        state.last_reconcile -= collector.RECONCILE_SWEEP
        self.assertFalse(collector.run_reconciler(a_snapshot("w1"), state, None))
        self.assertEqual(len(self.sb_runs()), 2)

    def test_a_stall_spawns_sb_reconcile_once_and_a_new_name_within_one_cycle(self):
        """Three facts, one run of the trigger, because they are one behaviour.

        A stall does not clear itself the way delivered mail does — the same name is
        stalled on every tick for as long as it lasts — so without the set the trigger
        would spawn a process every two seconds for it. A name that goes stalled *after*
        that must still be seen on the next tick, which is the pass this item is held to.
        """
        from switchboard import cli
        state = collector.State(pid=1, started_at=0.0)

        self.assertTrue(collector.run_reconciler(self._stalled("w1"), state, None))
        self.assertEqual(self.sb_runs(), [["/bin/sb", "reconcile"]])
        self.assertEqual((state.reconciles, state.reconcile_error), (1, None))
        # Spawned by name, so a rename would fail silently in a thread nobody watches.
        self.assertEqual(cli.build_parser().parse_args(["reconcile"]).cmd, "reconcile")

        for _ in range(3):                                        # the same stall, again
            state.last_reconcile -= collector.RECONCILE_GAP + 1   # the floor is not it
            self.assertFalse(collector.run_reconciler(self._stalled("w1"), state, None))
        self.assertEqual(len(self.sb_runs()), 1)

        state.last_reconcile -= collector.RECONCILE_SWEEP         # the sweep is
        self.assertTrue(collector.run_reconciler(self._stalled("w1"), state, None))

        state.last_reconcile -= collector.RECONCILE_GAP + 1       # and a NEW stalled name
        self.assertTrue(collector.run_reconciler(self._stalled("w1", "w2"), state, None))
        self.assertEqual(len(self.sb_runs()), 3)

        # A fleet with nobody stalled costs nothing at all.
        state.last_reconcile -= collector.RECONCILE_SWEEP
        self.assertFalse(collector.run_reconciler(a_snapshot("w1"), state, None))
        self.assertEqual(len(self.sb_runs()), 3)


class WhichSbTheDoorbellRuns(PanelTest):
    """WHICH `sb` binary the doorbell spawns — the last environment fact it depended on.

    `shutil.which("sb")` asks the board pane's PATH, and that resolves the one machine-wide
    symlink into the main checkout. A collector running a branch's code therefore rang the
    doorbell by running a DIFFERENT build, and when the verb it needs is newer than the
    installed one every ring dies in argparse: 55 doorbells in 5.5 minutes, all failed,
    five reports left undelivered, until the collector was restarted by hand with the right
    `bin` in front. Nothing pins a board pane —
    `_pin_sb` covers spawned agents only — so the fix is for the doorbell to name its own
    build rather than to arrange anybody's PATH.
    """

    def test_it_runs_the_sb_of_the_checkout_it_is_running_from(self):
        """The collector is launched with its checkout on PYTHONPATH, so its own
        `__file__` names that checkout, and that checkout's `bin/sb` is the same file
        `_pin_sb` puts in front of an agent's PATH."""
        own = Path(collector.__file__).resolve().parent.parent / "bin" / "sb"
        self.assertTrue(os.access(own, os.X_OK))          # the premise, asserted
        self.assertEqual(collector.doorbell_sb(), str(own))

    def test_an_unrelated_sb_on_path_cannot_win(self):
        """The whole point: a correct doorbell must not be defeated by whatever binary
        happens to be installed. Nothing here arranges PATH, and PATH is not consulted."""
        with mock.patch.object(collector.shutil, "which", lambda n: "/usr/local/bin/sb"):
            self.assertNotEqual(collector.doorbell_sb(), "/usr/local/bin/sb")

    def test_and_it_is_the_binary_that_actually_gets_spawned(self):
        """`ring_doorbell` asks the same question — the resolution is not left where only
        a unit test can see it."""
        ran = []
        with mock.patch.object(collector.threading, "Thread",
                               lambda target, args=(), **kw: mock.Mock(
                                   start=lambda: target(*args))), \
             mock.patch.object(collector.subprocess, "run",
                               lambda argv, **kw: ran.append(argv) or mock.Mock(
                                   returncode=0)), \
             mock.patch.object(collector, "doorbell_sb", lambda: "/checkout/bin/sb"):
            snap = a_snapshot("w1")
            snap.agents[0].undelivered = 1
            collector.ring_doorbell(snap, collector.State(pid=1, started_at=0.0), None)
        self.assertEqual(ran, [["/checkout/bin/sb", "flush"]])

    def test_a_switchboard_with_no_bin_beside_it_falls_back_to_path(self):
        """Installed as a package, or vendored: there is no build of its own to run, and
        the installed `sb` is then the only one it could have meant."""
        with mock.patch.object(collector.os, "access", lambda p, m: False), \
             mock.patch.object(collector.shutil, "which", lambda n: "/usr/local/bin/sb"):
            self.assertEqual(collector.doorbell_sb(), "/usr/local/bin/sb")

class TheDoorbellsWorkingDirectory(PanelTest):
    """Which directory the spawned `sb` is run FROM, which decides whether it runs at all.

    The store lives inside `.git`, and the first version of this handed `sb` the store's
    grandparent — the `.git` directory itself. `cli.main` resolves `store.worktree_root()`
    for every verb and `git rev-parse --show-toplevel` fails inside `.git`, so every
    doorbell ever rung died there before it delivered anything, on every machine, whatever
    was on PATH. Real repositories here rather than
    mocked paths, because the thing that was wrong was a real path.
    """

    def test_the_directory_it_picks_is_one_sb_can_actually_run_in(self):
        """The assertion the counter could not make: `sb` calls `store.worktree_root()`
        for every verb, so the doorbell's cwd has to satisfy `--show-toplevel`."""
        root = a_git_repo(Path(self.tmp.name) / "repo")
        cwd = collector._doorbell_cwd(store.db_path(root))
        self.assertEqual(store.worktree_root(Path(cwd)), root.resolve())

    def test_a_collector_started_in_a_worktree_rings_from_the_main_checkout(self):
        """The normal case here: agents live in worktrees, and every worktree shares the
        one `.git`. Its parent is the main checkout, a work tree like any other, so the
        flush lands on the right store from a directory `sb` accepts."""
        root = a_git_repo(Path(self.tmp.name) / "repo")
        wt = Path(self.tmp.name) / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(wt)],
                       cwd=str(root), check=True, capture_output=True)
        self.assertEqual(store.db_path(wt), store.db_path(root))     # one store, shared
        cwd = collector._doorbell_cwd(store.db_path(wt))
        self.assertEqual(store.worktree_root(Path(cwd)), root.resolve())

    def test_a_relocated_git_dir_uses_the_checkout_sb_init_recorded(self):
        """`.git`'s parent is only the checkout in an ordinary layout. `sb init` writes
        the answer down for the rest; this reads the same file `store.main_checkout` does
        rather than importing it, so the doorbell half stays importless."""
        root = a_git_repo(Path(self.tmp.name) / "repo")
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        store.write_config({"main_checkout": str(elsewhere)}, cwd=root)
        self.assertEqual(collector._doorbell_cwd(store.db_path(root)), str(elsewhere))

    def test_a_recorded_checkout_that_is_gone_falls_back_to_the_inference(self):
        root = a_git_repo(Path(self.tmp.name) / "repo")
        store.write_config({"main_checkout": str(Path(self.tmp.name) / "deleted")},
                           cwd=root)
        cwd = collector._doorbell_cwd(store.db_path(root))
        self.assertEqual(store.worktree_root(Path(cwd)), root.resolve())

    def test_with_no_store_at_all_it_inherits_the_collectors_own_directory(self):
        self.assertEqual(collector._doorbell_cwd(Path("/r/.git/agentflow/state.db")), "/r")
        self.assertIsNone(collector._doorbell_cwd(None))


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


class TwoRealProcesses(unittest.TestCase):
    """The mechanism as processes rather than as functions.

    Everything above stubs one side or the other. This runs an actual collector, started
    the way an actual renderer starts one, against an actual store in an actual repo, and
    reads what lands on disk. It is the only test that would catch the whole thing being
    wired up correctly and not working — a bad module path in `ensure_collector`, an env
    var the child does not read, a collector that elects itself and then exits.

    It leaves nothing behind: the collector is killed in cleanup, and it would retire on
    its own inside a minute anyway (`panel.collector_idle_exit`) because no renderer is
    stamping `demand`.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        for cmd in (["init", "-q", "-b", "main"],
                    ["-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(["git", *cmd], cwd=str(self.repo), check=True,
                           capture_output=True)
        db = store.connect(path=store.db_path(self.repo))
        store.create_agent(db, name="w1", role="worker", session_id="s1", task="do it")
        db.close()
        self.paths = panel.Paths.resolve(self.repo)
        self.addCleanup(self._kill)

    def _kill(self):
        r = panel.read(self.paths)
        pid = (r.collector or {}).get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def test_a_renderer_starts_a_collector_and_reads_what_it_publishes(self):
        sup = panel.Supervisor(self.paths, cwd=self.repo)
        self.assertTrue(sup.tick(), "no collector was launched")

        for _ in range(150):
            r = panel.read(self.paths)
            if not r.error:
                break
            time.sleep(0.1)
        else:
            self.fail(f"the collector published nothing: {panel.read(self.paths).error}")

        self.assertEqual([a.name for a in r.snap.agents], ["w1"])
        self.assertEqual(r.snap.agents[0].task, "do it")
        self.assertFalse(r.stale)
        self.assertGreaterEqual(r.collector["polls"], 1)
        self.assertTrue(panel.collector_running(self.paths))
        # ...and the store it read is byte-for-byte what it was handed.
        db = store.connect(path=store.db_path(self.repo), readonly=True)
        self.addCleanup(db.close)
        row = store.get_agent(db, "w1")
        self.assertEqual((row["state"], row["ended_at"]), ("working", None))


if __name__ == "__main__":
    unittest.main()
