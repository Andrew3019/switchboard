"""Store tests. stdlib unittest — no dependencies.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    # -- agents ----------------------------------------------------------

    def test_identity_by_session(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-abc")
        self.assertEqual(store.agent_by_session(self.db, "sess-abc")["name"], "w1")
        self.assertIsNone(store.agent_by_session(self.db, "nope"))

    def test_state_transitions_set_ended_at(self):
        store.create_agent(self.db, name="w", role="worker")
        store.set_state(self.db, "w", "blocked")
        self.assertIsNone(store.get_agent(self.db, "w")["ended_at"])
        store.set_state(self.db, "w", "done")
        self.assertIsNotNone(store.get_agent(self.db, "w")["ended_at"])

    def test_seq_is_strictly_increasing(self):
        store.create_agent(self.db, name="w", role="worker")
        seqs = [store.next_seq(self.db, "w") for _ in range(5)]
        self.assertEqual(seqs, [1, 2, 3, 4, 5])
        self.assertEqual(sorted(set(seqs)), seqs)  # never reused: herdr drops stale seq

    def test_update_agent_rejects_unknown_field(self):
        store.create_agent(self.db, name="w", role="worker")
        with self.assertRaises(ValueError):
            store.update_agent(self.db, "w", state="done")  # must go through set_state

    def test_mark_spawned_reopens_a_row_closed_under_the_spawn(self):
        """The one narrow exception to that allowlist, and why it exists: the board can
        close a claim while its `agent start` is still retrying, and nothing else in the
        store can undo that."""
        store.create_agent(self.db, name="w", role="worker")
        store.set_state(self.db, "w", "failed")
        store.mark_spawned(self.db, "w")
        a = store.get_agent(self.db, "w")
        self.assertEqual(a["state"], "working")
        self.assertIsNone(a["ended_at"])

    def test_live_tops_is_what_is_running_not_what_ever_ran(self):
        """The store keeps every top ever created; without the filter this is history."""
        for name in ("main", "main-2", "main-3"):
            store.create_agent(self.db, name=name, role="dispatcher", is_top=True)
        store.create_agent(self.db, name="kid", role="lead", parent="main")
        store.set_state(self.db, "main", "done")
        store.set_state(self.db, "main-2", "failed")
        store.create_agent(self.db, name="side", role="worker")   # a root, but no stamp
        self.assertEqual([r["name"] for r in store.live_tops(self.db)],
                         ["main-3"])            # not the ended ones, not a child, not an
                                                # unstamped root

    def test_live_tops_finds_a_top_stamped_under_the_retired_role_name(self):
        """The regression this function was rewritten for. It filtered on `role=?` against
        `[vocabulary] main_role`, so renaming the top's role from `orchestrator` to
        `dispatcher` hid every top already in the store — on the live store that afternoon,
        both of them, one of them blocked and waiting on Andrew, and the next bare
        `sb start` would have opened a third and said nothing about either."""
        store.create_agent(self.db, name="main-15", role="orchestrator", is_top=True)
        self.assertEqual([r["name"] for r in store.live_tops(self.db)], ["main-15"])

    def test_live_tops_keeps_a_blocked_one(self):
        """Blocked is waiting on a person, not finished — it is still up. It is also the
        one a human most needs named back to them."""
        store.create_agent(self.db, name="main", role="dispatcher", is_top=True)
        store.set_state(self.db, "main", "blocked")
        self.assertEqual([r["name"] for r in store.live_tops(self.db)], ["main"])

    # -- messages --------------------------------------------------------

    def test_inbox_returns_all_unread_and_marks_read(self):
        store.create_agent(self.db, name="p", role="lead")
        for i in range(3):
            store.put_message(self.db, from_agent="c", to_agent="p", kind="tell", body=f"m{i}")
        first = store.unread_for(self.db, "p")
        self.assertEqual(len(first), 3)          # one call, not one per message (C0)
        self.assertEqual(store.unread_for(self.db, "p"), [])

    def test_peek_does_not_mark_read(self):
        store.put_message(self.db, from_agent="c", to_agent="p", kind="tell", body="x")
        self.assertEqual(len(store.unread_for(self.db, "p", mark=False)), 1)
        self.assertEqual(len(store.unread_for(self.db, "p")), 1)

    def test_bad_kind_rejected(self):
        with self.assertRaises(ValueError):
            store.put_message(self.db, from_agent="a", to_agent="b", kind="shout", body="x")

    def test_the_ask_correlation_helpers_are_gone(self):
        """`sb ask` is deleted, so nothing writes `kind='ask'` and nothing may grow a
        reader for it again. An OLD row still reads back as ordinary mail."""
        self.assertFalse(hasattr(store, "pending_ask"))
        self.assertFalse(hasattr(store, "reply_to_ask"))
        store.put_message(self.db, from_agent="p", to_agent="c", kind="ask", body="q?")
        self.assertEqual(store.unread_for(self.db, "c")[0]["body"], "q?")

    # -- events ----------------------------------------------------------

    def test_events_capture_failures(self):
        store.log_event(self.db, kind="spawn", agent="w", error="invalid_agent_argument")
        e = store.recent_events(self.db)[0]
        self.assertEqual(e["kind"], "spawn")
        self.assertIn("invalid_agent_argument", e["payload"])

    # -- schema lifecycle ------------------------------------------------

    def test_reset_refuses_while_agents_live(self):
        """Only agents herdr confirms are running — the store's own 'working' drifts."""
        from unittest import mock
        store.create_agent(self.db, name="w", role="worker")
        with mock.patch.object(store, "_herdr_alive", lambda: {"w"}):
            with self.assertRaises(store.LiveAgentsError):
                store._reset(self.db)

    def test_reset_allowed_once_idle(self):
        store.create_agent(self.db, name="w", role="worker")
        store.set_state(self.db, "w", "done")
        store._reset(self.db)                                   # disposable by construction
        self.assertEqual(store.get_agent(self.db, "w"), None)

    # -- schema evolution ------------------------------------------------

    @contextlib.contextmanager
    def _schema(self, old: str, new: str):
        """Run the body as if this code shipped a different SCHEMA.

        Which is the only honest way to test any of this: the interesting case is always
        *two* versions of `sb` meeting over one store, and a test that edits the store
        instead of the code is testing the mirror image of the thing that breaks.
        """
        original, original_hash = store.SCHEMA, store._SCHEMA_HASH
        store.SCHEMA = original.replace(old, new)
        self.assertNotEqual(store.SCHEMA, original, "the SCHEMA anchor no longer matches")
        store._SCHEMA_HASH = hashlib.sha256(store.SCHEMA.encode()).hexdigest()[:16]
        try:
            yield
        finally:
            store.SCHEMA, store._SCHEMA_HASH = original, original_hash

    _ENDED = "    ended_at      INTEGER\n"

    def test_an_added_column_migrates_instead_of_resetting(self):
        """A schema change must never wedge running agents.

        `connect()` is what every `sb` command calls — including the `sb done` an agent
        needs in order to stop being 'live'. One agent adding a column once wedged every
        other agent on the machine, unrecoverably.
        """
        p = Path(self.tmp.name) / "mig.db"
        d1 = store.connect(path=p)
        store.create_agent(d1, name="w", role="worker")
        d1.close()

        with self._schema(self._ENDED, self._ENDED.rstrip("\n") + ",\n    newcol   TEXT\n"):
            d2 = store.connect(path=p)
            self.assertIsNotNone(store.get_agent(d2, "w"))     # data survived
            self.assertIn("newcol", {r[1] for r in d2.execute("PRAGMA table_info(agents)")})
            self.assertEqual(store.schema_deficit(d2), [])     # and is fully caught up
            d2.close()

    def test_a_new_index_reaches_a_store_that_predates_it(self):
        """An index ADDED to an existing table's declaration must be created on an old
        store, not only on ones built from scratch. `_deficit` reports missing tables and
        columns and never a missing index, so without `_reconcile` ensuring the declared
        indexes an old store would keep paying the full-table scans the index exists to
        remove. This is the migration behind the collector-tick fix."""
        idx = "CREATE INDEX idx_events_agent_created ON events(agent, created_at, kind);\n"
        self.assertIn(idx, store.SCHEMA, "the index anchor no longer matches")
        p = Path(self.tmp.name) / "idxmig.db"
        # An OLD store: the same code minus this one index declaration.
        with self._schema(idx, ""):
            d1 = store.connect(path=p)
            store.create_agent(d1, name="w", role="worker")
            names = {r[0] for r in d1.execute("SELECT name FROM sqlite_master "
                                              "WHERE type='index'")}
            self.assertNotIn("idx_events_agent_created", names)
            d1.close()
        # Current code (the real SCHEMA declares it) migrates it in.
        d2 = store.connect(path=p)
        names = {r[0] for r in d2.execute("SELECT name FROM sqlite_master "
                                          "WHERE type='index'")}
        self.assertIn("idx_events_agent_created", names)
        self.assertIsNotNone(store.get_agent(d2, "w"))       # data survived
        self.assertEqual(store.schema_deficit(d2), [])       # and is fully caught up
        d2.close()

    def test_index_ddl_emits_every_declared_index(self):
        """`_index_ddl` parses SCHEMA with a regex, and a declaration it fails to match is
        dropped SILENTLY — an index that would then never migrate onto an existing store.
        Pin the emitted set against the indexes SCHEMA actually declares, so a future
        declaration the regex cannot read fails here instead of on a slow board."""
        declared = re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", store.SCHEMA)
        emitted = [re.search(r"INDEX IF NOT EXISTS (\w+)", s).group(1)
                   for s in store._index_ddl()]
        self.assertEqual(sorted(emitted), sorted(declared))
        self.assertTrue(all("IF NOT EXISTS" in s for s in store._index_ddl()))

    # -- the branch column -----------------------------------------------
    #
    # `workspace` is a NAME and nothing more — a branch for a worktree space, an agent-ish
    # label for a bare one, with nothing to tell them apart. `branch` is the fact.

    def test_a_row_has_no_branch_unless_it_is_given_one(self):
        """Bare is the default: NULL means "no checkout of my own", and guessing the other
        way hands an agent somebody else's tree."""
        store.create_agent(self.db, name="root", role="lead", workspace="main")
        self.assertIsNone(store.get_agent(self.db, "root")["branch"])
        self.assertIsNone(store.agent_branch(self.db, "root"))

    def test_the_branch_is_recorded_and_read_back(self):
        store.create_agent(self.db, name="lead", role="lead", workspace="api",
                           branch="api")
        self.assertEqual(store.agent_branch(self.db, "lead"), "api")

    def test_a_workspaces_branch_comes_from_whichever_row_recorded_one(self):
        """A checkout belongs to the workspace, so any row in it can answer for it."""
        store.claim_agent(self.db, name="lead", role="lead", workspace="api",
                          branch="api")
        store.claim_agent(self.db, name="kid", role="worker", workspace="api",
                          branch="api")
        self.assertEqual(store.workspace_branch(self.db, "api"), "api")

    def test_a_bare_workspace_has_no_branch_but_is_still_known(self):
        """The two answers that must not be confused: a place with no checkout, and a name
        we have never heard of."""
        store.create_agent(self.db, name="root", role="lead", workspace="scratch")
        self.assertIsNone(store.workspace_branch(self.db, "scratch"))
        self.assertTrue(store.known_workspace(self.db, "scratch"))
        self.assertFalse(store.known_workspace(self.db, "never-seen"))

    # -- migrating the rows that predate it ------------------------------

    def _old_store(self, p: Path):
        """A store as it was before `branch` existed."""
        d = store.connect(path=p)
        d.execute("ALTER TABLE agents DROP COLUMN branch")
        d.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'old')")
        d.commit()
        return d

    def _git_repo(self, name: str = "repo") -> Path:
        import subprocess
        main = Path(self.tmp.name) / name
        main.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=main, capture_output=True)
        return main

    def test_existing_rows_are_given_the_branch_they_were_always_on(self):
        """The migration. A row in a named workspace, running somewhere other than the
        main checkout, was in a worktree — and the workspace name is the branch it was
        forked as. A row in the main checkout was the bare space, and stays bare."""
        main = self._git_repo()
        p = Path(self.tmp.name) / "old.db"
        d = self._old_store(p)
        d.execute(
            "INSERT INTO agents (name, role, state, cwd, workspace, cleanup, created_at) "
            "VALUES ('lead', 'lead', 'working', ?, 'api', 'keep', 1)",
            (str(main / "worktrees" / "api"),))
        d.execute(
            "INSERT INTO agents (name, role, state, cwd, workspace, cleanup, created_at) "
            "VALUES ('root', 'main', 'working', ?, 'main', 'keep', 1)", (str(main),))
        d.commit(); d.close()

        d2 = store.connect(main, path=p)
        self.assertEqual(store.agent_branch(d2, "lead"), "api")
        self.assertIsNone(store.agent_branch(d2, "root"))     # the bare space stays bare
        d2.close()

    def test_a_row_with_no_workspace_is_left_alone_by_the_migration(self):
        main = self._git_repo()
        p = Path(self.tmp.name) / "plain.db"
        d = self._old_store(p)
        d.execute("INSERT INTO agents (name, role, state, cwd, cleanup, created_at) "
                  "VALUES ('w', 'worker', 'working', '/somewhere/else', 'close', 1)")
        d.commit(); d.close()

        d2 = store.connect(main, path=p)
        self.assertIsNone(store.agent_branch(d2, "w"))
        d2.close()

    def test_the_migration_gives_up_rather_than_guess_outside_a_repo(self):
        """No main checkout to compare against means no way to tell a worktree from the
        primary tree. NULL costs a fork; a wrong branch costs somebody's main checkout."""
        p = Path(self.tmp.name) / "norepo.db"
        d = self._old_store(p)
        d.execute("INSERT INTO agents (name, role, state, cwd, workspace, cleanup, "
                  "created_at) VALUES ('lead', 'lead', 'working', '/wt/api', "
                  "'api', 'keep', 1)")
        d.commit(); d.close()

        nowhere = Path(self.tmp.name) / "not-a-repo"
        nowhere.mkdir()
        d2 = store.connect(nowhere, path=p)
        self.assertIsNotNone(store.get_agent(d2, "lead"))      # the rows survive
        self.assertIsNone(store.agent_branch(d2, "lead"))      # unguessed, not guessed
        d2.close()

    def test_rows_that_predate_awaiting_task_read_as_ordinary_agents(self):
        """The column arrives by ALTER, and its default is the direction that costs
        nothing: a row written before it existed is stalled-eligible exactly as it was.
        Defaulting the other way would silence the warning for every agent on the
        machine, which is the one failure this flag must not be able to cause."""
        p = Path(self.tmp.name) / "preflag.db"
        d = store.connect(path=p)
        store.create_agent(d, name="w", role="worker")
        d.execute("ALTER TABLE agents DROP COLUMN awaiting_task")
        d.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'old')")
        d.commit(); d.close()

        d2 = store.connect(path=p)
        self.assertEqual(store.get_agent(d2, "w")["awaiting_task"], 0)
        d2.close()

    def test_an_unknown_column_does_not_force_a_reset(self):
        """A newer `sb`, run from another checkout against the same store, adds a column
        this code has never heard of. Older code must keep working: two checkouts share
        one store, and reading the extra column as destructive wedged every agent on the
        machine once already."""
        p = Path(self.tmp.name) / "destructive.db"
        d = store.connect(path=p)
        store.create_agent(d, name="w", role="worker")
        d.execute("ALTER TABLE agents ADD COLUMN added_by_newer_sb TEXT")
        self.assertEqual(store._deficit(d), ([], [], []))     # nothing missing: no reset
        self.assertIsNotNone(store.get_agent(d, "w"))         # and the fleet survives
        d.close()

    def test_a_cosmetic_schema_edit_costs_nothing(self):
        """The hash covers the SCHEMA string verbatim, so editing a COMMENT in it changed
        it. That must not so much as touch the store."""
        p = Path(self.tmp.name) / "comment.db"
        d1 = store.connect(path=p)
        store.create_agent(d1, name="w", role="worker")
        d1.close()
        with self._schema("-- JSON", "-- JSON, one day maybe msgpack"):
            d2 = store.connect(path=p)
            self.assertIsNotNone(store.get_agent(d2, "w"))
            self.assertEqual(store.schema_deficit(d2), [])
            d2.close()

    # -- the deadlock ----------------------------------------------------
    #
    # A change that ALTER TABLE cannot apply — here a NOT NULL column with no literal
    # default, which is the shape that split `workspace` in two and bricked the fleet.

    # NOT the real `branch` column, which this code now ships: a hypothetical column has
    # to be one the schema does NOT have, or there is no gap to be blocked on and the test
    # passes over a store that was never degraded.
    _SPLIT = "    ended_at      INTEGER,\n    checkout      TEXT NOT NULL\n"

    def test_a_non_additive_change_under_a_live_fleet_degrades_not_deadlocks(self):
        from unittest import mock
        p = Path(self.tmp.name) / "deadlock.db"
        d1 = store.connect(path=p)
        store.create_agent(d1, name="w", role="worker")
        d1.close()

        with self._schema(self._ENDED, self._SPLIT):
            with mock.patch.object(store, "_herdr_alive", lambda: {"w"}):
                d2 = store.connect(path=p)                     # NO exception: this is the fix
            self.assertIsNotNone(store.get_agent(d2, "w"))     # the fleet's state is intact
            self.assertTrue(store.schema_deficit(d2))          # and it says why, by name
            store.set_state(d2, "w", "done")                   # `sb done` still reaches it
            self.assertEqual(store.get_agent(d2, "w")["state"], "done")
            d2.close()

    def test_the_store_rebuilds_itself_once_the_fleet_drains(self):
        """The degraded store is not stamped, so the next process retries — which is how
        this clears without anyone having to remember it happened."""
        from unittest import mock
        p = Path(self.tmp.name) / "drains.db"
        d1 = store.connect(path=p)
        store.create_agent(d1, name="w", role="worker")
        d1.close()

        with self._schema(self._ENDED, self._SPLIT):
            with mock.patch.object(store, "_herdr_alive", lambda: {"w"}):
                store.connect(path=p).close()                  # degraded, deferred
            with mock.patch.object(store, "_herdr_alive", lambda: set()):
                d3 = store.connect(path=p)                     # last agent gone: rebuild
            self.assertEqual(store.schema_deficit(d3), [])
            self.assertIn("checkout", {r[1] for r in d3.execute("PRAGMA table_info(agents)")})
            d3.close()

    def test_a_missing_table_whose_rows_cannot_be_invented_is_still_blocking(self):
        """`events` declares NOT NULL columns, so a store without it is missing rows this
        code cannot write for it — the same test `_deficit` applies to a column, one level
        up. An all-nullable table is a different answer; see `AddingATableTest`."""
        p = Path(self.tmp.name) / "notable.db"
        d = store.connect(path=p)
        d.execute("DROP TABLE events")
        tables, columns, blocking = store._deficit(d)
        self.assertEqual((tables, columns), ([], []))
        self.assertTrue(any("events" in b for b in blocking))
        d.close()

    def test_liveness_is_judged_by_herdr_not_the_store(self):
        """Store state drifts — an agent that finished without reporting reads as
        'working' forever, and must not be able to block a reset."""
        from unittest import mock
        d = store.connect(path=Path(self.tmp.name) / "live.db")
        store.create_agent(d, name="ghost", role="worker")      # store says working
        with mock.patch.object(store, "_herdr_alive", lambda: set()):
            store._reset(d)                                     # herdr never heard of it
        self.assertIsNone(store.get_agent(d, "ghost"))
        d.close()

    def test_a_herdr_we_could_not_reach_refuses_the_wipe(self):
        """The distinction the whole guard turns on: an ANSWER of "nobody" is evidence,
        and no answer at all is not. Failing toward the empty set meant a herdr installed
        somewhere else — or slow, or exiting non-zero — was enough to drop `agents`,
        `messages` and `events` under a live fleet, unrecoverably and unlogged."""
        from unittest import mock
        d = store.connect(path=Path(self.tmp.name) / "unknown.db")
        store.create_agent(d, name="real", role="worker")
        with mock.patch.object(store, "_herdr_alive", lambda: None):
            with self.assertRaises(store.LiveAgentsError) as cm:
                store._reset(d)
        self.assertIn("herdr could not be reached", str(cm.exception))
        self.assertIsNotNone(store.get_agent(d, "real"))
        d.close()

    def test_every_way_of_not_getting_an_answer_reads_as_unknown(self):
        """Not-installed, non-zero, hung, and unparseable are all `None`, never `set()`."""
        import subprocess as sp
        from unittest import mock

        def ran(rc=0, out=""):
            return lambda *a, **k: sp.CompletedProcess(a[0], rc, out, "")

        cases = {
            "not installed": mock.Mock(side_effect=FileNotFoundError()),
            "non-zero exit": ran(1, ""),
            "hung": mock.Mock(side_effect=sp.TimeoutExpired("herdr", 5)),
            "not json": ran(0, "herdr: no daemon"),
            "json of another shape": ran(0, '{"error": "nope"}'),
        }
        for label, runner in cases.items():
            with self.subTest(label):
                with mock.patch.object(store.subprocess, "run", runner):
                    self.assertIsNone(store._herdr_alive())
        with mock.patch.object(store.subprocess, "run",
                               ran(0, '{"result": {"agents": [{"name": "a"}, {}]}}')):
            self.assertEqual(store._herdr_alive(), {"a"})       # an answer is still an answer

    def test_the_herdr_binary_is_the_one_on_PATH(self):
        """A hardcoded ~/.local/bin/herdr made "installed elsewhere" mean "nobody is
        alive". Resolved like the adapter does it (`herdr.Herdr.__init__`)."""
        from unittest import mock
        seen = []
        with mock.patch.object(store.shutil, "which", lambda n: "/opt/homebrew/bin/herdr"), \
             mock.patch.object(store.subprocess, "run",
                               lambda argv, **k: seen.append(argv) or
                               __import__("subprocess").CompletedProcess(argv, 1, "", "")):
            store._herdr_alive()
        self.assertEqual(seen[0][0], "/opt/homebrew/bin/herdr")

    def test_force_escapes_the_guard(self):
        from unittest import mock
        d = store.connect(path=Path(self.tmp.name) / "force.db")
        store.create_agent(d, name="real", role="worker")
        with mock.patch.object(store, "_herdr_alive", lambda: {"real"}):
            with self.assertRaises(store.LiveAgentsError):
                store._reset(d)
            store._reset(d, force=True)                         # always an escape hatch
        d.close()

    # -- path resolution -------------------------------------------------

    def _mkrepo(self, name):
        import subprocess
        d = Path(self.tmp.name) / name; d.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], cwd=d, capture_output=True)
        return d

    def test_repo_root_is_anchored_to_the_given_dir_not_the_process_cwd(self):
        """git returns --git-common-dir RELATIVE to where it ran.

        Resolving that against the process cwd would hand back whichever repo the caller
        happens to be standing in — i.e. writing to the wrong store entirely.
        """
        a, b = self._mkrepo("a"), self._mkrepo("b")
        self.assertEqual(store.repo_root(a), (a / ".git").resolve())
        self.assertEqual(store.repo_root(b), (b / ".git").resolve())
        self.assertNotEqual(store.db_path(a), store.db_path(b))

    def test_store_is_shared_across_worktrees_but_worktree_root_is_not(self):
        """One store per repo, visible from every worktree; each tree still sees itself.

        Required because the top-level orchestrator lives on main while its children live
        in worktrees, and parent links must survive across them.
        """
        import subprocess
        main = self._mkrepo("wtmain")
        wt = Path(self.tmp.name) / "wtside"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "side"],
                       cwd=main, capture_output=True)
        self.assertEqual(store.db_path(main), store.db_path(wt))
        self.assertNotEqual(store.worktree_root(main), store.worktree_root(wt))

    # -- transcripts -----------------------------------------------------

class AddingATableTest(unittest.TestCase):
    """The one schema change that used to cost everybody their store.

    A missing table was `blocking`, `_reconcile` answers `blocking` with `_reset`, and
    `_reset` dropped `agents`, `messages` and `events`. Against a copy of the real store
    with the fleet drained — the ordinary state of this machine between sessions — appending
    one table took 101 agents, 254 messages and 11752 events to zero. The live-agent guard
    postponed that; it never prevented it.

    So these tests are run against a store shaped like the real one, and what they assert is
    that the rows are all still there afterwards.
    """

    # A fourth table, deliberately NOT the one Wave 3 wants. The capability has to hold for
    # a table nothing else in the tree has heard of, which is also what makes this a test
    # and not a rehearsal of one particular migration.
    _FOURTH = """
CREATE TABLE notes (
    subject       TEXT PRIMARY KEY,
    body          TEXT,
    created_at    INTEGER
);
CREATE INDEX idx_notes_subject ON notes(subject, created_at);
"""

    # The same table with one column that cannot be given to rows that already exist.
    _FOURTH_NOT_NULL = _FOURTH.replace("    body          TEXT,",
                                       "    body          TEXT NOT NULL,")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    # -- the fixture -----------------------------------------------------

    def _populated_store(self) -> Path:
        """A store the size and shape of the real one, then stamped as another checkout's.

        The stamp is what arms `_reconcile`: a store whose hash matches is never looked at.
        Row counts are the real machine's, because the failure this guards against is
        measured in rows and a fixture of three of them would not show it.
        """
        self._made = getattr(self, "_made", 0) + 1
        p = Path(self.tmp.name) / f"real-ish-{self._made}.db"
        db = store.connect(path=p)
        db.executemany(
            "INSERT INTO agents (name, role, state, cwd, workspace, cleanup, created_at) "
            "VALUES (?, 'worker', ?, ?, ?, 'close', 1)",
            [(f"a{i}", "working" if i % 5 else "done", f"/wt/ws{i % 21}", f"ws{i % 21}")
             for i in range(101)],
        )
        db.executemany(
            "INSERT INTO messages (from_agent, to_agent, kind, body, created_at) "
            "VALUES ('a1', 'a2', 'tell', ?, 1)", [(f"m{i}",) for i in range(254)],
        )
        db.executemany(
            "INSERT INTO events (agent, kind, created_at) VALUES ('a1', 'tick', 1)",
            [() for _ in range(11752)],
        )
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'older')")
        db.commit()
        db.close()
        return p

    def _counts(self, db) -> tuple:
        return tuple(db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                     for t in ("agents", "messages", "events"))

    @contextlib.contextmanager
    def _fourth(self, *, schema: str = "", first: bool = False, backfill: bool = True):
        """Run the body as if this code shipped a fourth table.

        `first=True` declares it ahead of `agents`, which is the half of `_reset`'s old bug
        that bricked the store rather than merely emptying it. Which half you land in was
        decided by declaration order, so both orders are tested.
        """
        text = schema or self._FOURTH
        original, original_hash = store.SCHEMA, store._SCHEMA_HASH
        store.SCHEMA = text + original if first else original + text
        store._SCHEMA_HASH = hashlib.sha256(store.SCHEMA.encode()).hexdigest()[:16]
        if backfill:
            store._TABLE_BACKFILLS["notes"] = self._fill_notes
        self.addCleanup(store._TABLE_BACKFILLS.pop, "notes", None)
        try:
            yield
        finally:
            store.SCHEMA, store._SCHEMA_HASH = original, original_hash
            store._TABLE_BACKFILLS.pop("notes", None)

    @staticmethod
    def _fill_notes(db, cwd) -> None:
        """A `workspaces`-shaped fill: one row per thing the existing rows already imply."""
        db.executemany(
            "INSERT OR IGNORE INTO notes(subject, created_at) VALUES(?, 1)",
            [(r[0],) for r in db.execute(
                "SELECT DISTINCT workspace FROM agents WHERE workspace IS NOT NULL")],
        )

    # -- the reproduction, run in reverse --------------------------------

    def test_adding_a_table_keeps_every_row(self):
        """The proof. Fleet drained, so nothing postpones the rebuild — and no rebuild
        happens, because a table of nullable columns is now something to add."""
        p = self._populated_store()
        with mock.patch.object(store, "_herdr_alive", lambda: set()):
            before = self._counts(store.connect(path=p))       # armed, but not yet migrated
            with self._fourth():
                db = store.connect(path=p)
                self.assertEqual(self._counts(db), before)
                self.assertEqual(before, (101, 254, 11752))
                self.assertEqual(store.schema_deficit(db), [])
                self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 21)
                db.close()

    def test_it_holds_whichever_side_of_the_schema_the_table_is_declared_on(self):
        for first in (False, True):
            with self.subTest(declared_first=first):
                p = self._populated_store()
                with mock.patch.object(store, "_herdr_alive", lambda: set()):
                    with self._fourth(first=first):
                        db = store.connect(path=p)
                        self.assertEqual(self._counts(db), (101, 254, 11752))
                        db.close()

    # -- the classification ----------------------------------------------

    def test_a_table_of_nullable_columns_is_addable_not_blocking(self):
        db = store.connect(path=Path(self.tmp.name) / "d.db")
        with self._fourth():
            self.assertEqual(store._deficit(db), (["notes"], [], []))
        db.close()

    def test_a_table_this_code_could_not_fill_stays_blocking(self):
        """The nullable rule is what keeps this honest: a NOT NULL column with no default is
        a value the migration would have to invent for every row it writes."""
        db = store.connect(path=Path(self.tmp.name) / "nn.db")
        with self._fourth(schema=self._FOURTH_NOT_NULL):
            tables, columns, blocking = store._deficit(db)
            self.assertEqual((tables, columns), ([], []))
            self.assertEqual(blocking, ["table notes is missing"])
        db.close()

    def test_the_indexes_come_with_the_table(self):
        p = Path(self.tmp.name) / "idx.db"
        store.connect(path=p).close()
        with self._fourth():
            db = store.connect(path=p)
            names = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_notes_subject", names)
            db.close()

    # -- `_reset` derives what it drops ----------------------------------

    def test_reset_drops_every_table_the_schema_declares(self):
        """`_reset` re-runs the WHOLE schema, so a table it did not drop is one `_create`
        then trips over. Declared after the three that used to be hardcoded, the store came
        back empty and the error escaped `connect()`; declared before them, the three were
        dropped and never recreated and every `sb` command on the machine failed until
        somebody deleted the store by hand."""
        for first in (False, True):
            with self.subTest(declared_first=first):
                p = self._populated_store()
                with self._fourth(first=first):
                    db = store.connect(path=p)                 # migrates, keeps the rows
                    store._reset(db, force=True)               # and now: on purpose
                    self.assertEqual(self._counts(db), (0, 0, 0))
                    self.assertEqual(
                        db.execute("SELECT count(*) FROM notes").fetchone()[0], 0)
                    self.assertEqual(store.schema_deficit(db), [])
                    db.close()

    def test_a_rebuilt_store_still_opens(self):
        """The brick, stated as the thing it broke: every later `connect()`."""
        p = self._populated_store()
        with self._fourth(first=True):
            db = store.connect(path=p)
            store._reset(db, force=True)
            db.close()
            again = store.connect(path=p)                      # this used to raise, forever
            self.assertEqual(store.schema_deficit(again), [])
            again.close()

    # -- two processes at once -------------------------------------------

    def test_the_loser_of_a_concurrent_create_does_not_escape_connect(self):
        """Both processes computed the deficit before either acted, which is the ordinary
        state of a machine where every `sb` command opens the store. `connect()` is what
        `sb done` calls, so nothing here may raise."""
        p = self._populated_store()
        with self._fourth():
            other = sqlite3.connect(str(p))
            store._create_table(other, "notes")                # the winner, already done
            other.commit()
            other.close()
            db = store.connect(path=p)                         # the loser, acting on a
            self.assertEqual(self._counts(db), (101, 254, 11752))   # stale deficit
            self.assertEqual(store.schema_deficit(db), [])
            db.close()

    def test_the_ddl_is_idempotent_before_anything_is_caught(self):
        """Belt and braces, and both halves are wanted: the statements themselves say IF
        NOT EXISTS, and the loser's error is caught on top of that. A caught exception is
        the last line of defence, not the design."""
        with self._fourth():
            stmts = store._table_ddl("notes")
            self.assertEqual(len(stmts), 2)                    # the table and its index
            for stmt in stmts:
                self.assertIn("IF NOT EXISTS", stmt)

    def test_an_already_exists_is_caught_even_so(self):
        """The other half, on its own: whatever reaches sqlite, "it is already there" is
        the loser finding nothing to do, and `connect()` may not raise over it."""
        db = store.connect(path=Path(self.tmp.name) / "caught.db")
        with mock.patch.object(store, "_table_ddl",
                               lambda t: [f"CREATE TABLE {t} (x TEXT)"]):
            store._create_table(db, "agents")                  # no IF NOT EXISTS anywhere
        self.assertIn("name", store._columns(db, "agents"))    # and it changed nothing
        db.close()

    def test_the_loser_of_a_concurrent_alter_does_not_escape_connect(self):
        p = self._populated_store()
        stale = (["notes"], [("agents", "later_column", "INTEGER")], [])
        with self._fourth():
            db = store.connect(path=p)
            db.execute("ALTER TABLE agents ADD COLUMN later_column INTEGER")   # the winner
            with mock.patch.object(store, "_deficit", lambda _db: stale):
                store._reconcile(db)                    # the loser, on a stale plan: both
            self.assertEqual(self._counts(db), (101, 254, 11752))   # statements already ran
            db.close()

    def test_a_racing_hash_stamp_cannot_suppress_the_one_time_fill(self):
        """`CREATE TABLE` autocommits, so the table exists for everybody the instant it is
        made and the filled rows do not exist for anybody until they commit. A process that
        read the shape and stamped the hash on it would short-circuit `_reconcile` for every
        later process, and the one-time fill would never run again — for anyone, ever. So
        the fill records that it happened, and the stamp waits for that record."""
        p = self._populated_store()
        with self._fourth():
            # A: creates the table, starts filling it, and is killed.
            a = sqlite3.connect(str(p))
            store._create_table(a, "notes")
            a.execute("INSERT INTO notes(subject, created_at) VALUES('half-done', 1)")
            a.close()                                          # rolled back: notes is empty

            # B: finds nothing missing. It must not call the store current on that alone.
            b = store.connect(path=p)
            self.assertTrue(store._backfill_recorded(b, "notes"))
            self.assertEqual(b.execute("SELECT count(*) FROM notes").fetchone()[0], 21)
            b.close()

            # C: arrives later, hash current, nothing left to do — and the rows are there.
            c = store.connect(path=p)
            self.assertEqual(c.execute("SELECT count(*) FROM notes").fetchone()[0], 21)
            c.close()

    def test_a_fill_that_never_committed_is_run_again(self):
        """The other half of the same rule: the table being there is not evidence that
        anybody finished filling it."""
        p = self._populated_store()
        with self._fourth():
            store._create_table(sqlite3.connect(str(p)), "notes")
            db = store.connect(path=p)
            self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 21)
            db.close()

    def test_a_fill_is_not_run_twice(self):
        p = self._populated_store()
        with self._fourth():
            db = store.connect(path=p)
            db.execute("DELETE FROM notes")                     # somebody cleared it since
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'x')")
            db.commit()
            store._reconcile(db)                                # recorded: leave it alone
            self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 0)
            db.close()

    def test_a_store_built_from_scratch_has_nothing_to_fill(self):
        """No history to derive anything from, so its fills are done by definition — and
        recorded as such, rather than left looking half-migrated forever."""
        with self._fourth():
            db = store.connect(path=Path(self.tmp.name) / "fresh.db")
            self.assertTrue(store._backfill_recorded(db, "notes"))
            self.assertEqual(store.schema_deficit(db), [])
            db.close()


class WorkspacesTableTest(unittest.TestCase):
    """The `workspaces` table itself, arriving through the capability above.

    Same grain as `AddingATableTest`: a store the shape and size of the real one, stamped
    by another checkout, met by code that declares a table it does not have. What differs
    is that the table is the real one, so the fill has a rule to get right rather than a
    stand-in — and the fixture carries the two names on this machine whose rows disagree
    about `branch`, because that disagreement is where the rule was wrong.
    """

    # Rows per bare orchestrator, and the one checkout they all share — this suite's own,
    # so the fixture carries a real path on whatever machine it runs on. Four of them over
    # one directory is why the key is the name: keyed on the path they would be one row,
    # and retiring any one of them would retire the other three.
    _BARE = ("main", "main-2", "main-3", "main-4")
    _CLONE = str(Path(__file__).resolve().parent.parent)

    # The regression fixture, from the real store: one cwd, one workspace, genuinely
    # worktree-backed, and some rows whose `branch` was never written — the shape
    # `delegate` produces when `branch is None` and the workspace was named rather than
    # inherited. Read as "any NULL-branch row means bare", both come out with no checkout
    # and are routed to the bare teardown path forever.
    _MIXED = {"plugins-redesign": (14, 3), "workspace-model": (11, 1)}

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._made = 0

    # -- the fixture -----------------------------------------------------

    def _rows(self) -> list:
        """101 agent rows over 18 workspace names, in the proportions the real store has."""
        rows, at = [], 0

        def row(name, workspace, branch, cwd):
            nonlocal at
            at += 1
            rows.append((name, "working" if at % 5 else "done", cwd, workspace, branch, at))

        for ws in self._BARE:                              # bare: no branch, one clone
            for i in range(3):
                row(f"{ws}-{i}", ws, None, self._CLONE)
        for ws, (with_branch, without) in self._MIXED.items():
            for i in range(without):                       # earliest, so "first row wins"
                row(f"{ws}-n{i}", ws, None, f"/wt/{ws}")   # readings fail here too
            for i in range(with_branch):
                row(f"{ws}-b{i}", ws, ws, f"/wt/{ws}")
        for n in range(12):                                # ordinary worktree spaces
            for i in range(5):
                row(f"ws{n}-{i}", f"ws{n}", f"ws{n}", f"/wt/ws{n}")
        return rows

    def _populated_store(self) -> Path:
        """A real-ish store that predates the table: no `workspaces`, no fill recorded."""
        self._made += 1
        p = Path(self.tmp.name) / f"real-ish-{self._made}.db"
        db = store.connect(path=p)
        db.executemany(
            "INSERT INTO agents (name, role, state, cwd, workspace, branch, cleanup,"
            " created_at) VALUES (?, 'worker', ?, ?, ?, ?, 'close', ?)", self._rows(),
        )
        db.executemany(
            "INSERT INTO messages (from_agent, to_agent, kind, body, created_at) "
            "VALUES ('a1', 'a2', 'tell', ?, 1)", [(f"m{i}",) for i in range(254)],
        )
        db.executemany(
            "INSERT INTO events (agent, kind, created_at) VALUES ('a1', 'tick', 1)",
            [() for _ in range(11752)],
        )
        # What a store written before this code looks like: the table is not there, its
        # fill was never recorded, and the hash is some other checkout's.
        db.execute("DROP TABLE workspaces")
        db.execute("DELETE FROM meta WHERE key='backfill:workspaces'")
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'older')")
        db.commit()
        db.close()
        return p

    def _counts(self, db) -> tuple:
        return tuple(db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                     for t in ("agents", "messages", "events"))

    def _migrated(self, p: Path = None):
        with mock.patch.object(store, "_herdr_alive", lambda: set()):
            return store.connect(path=p or self._populated_store())

    # -- the migration ---------------------------------------------------

    def test_the_table_arrives_and_every_row_survives_it(self):
        db = self._migrated()
        self.assertEqual(self._counts(db), (101, 254, 11752))
        self.assertEqual(store.schema_deficit(db), [])
        self.assertTrue(store._backfill_recorded(db, "workspaces"))
        db.close()

    def test_one_row_per_workspace_name(self):
        """Per NAME, which is the whole argument for the key: the four bare orchestrators
        over one clone are four workspaces, and a table that held one row for them would
        retire all four together and lock three live ones out of their own space."""
        db = self._migrated()
        names = [r["name"] for r in store.all_workspaces(db)]
        self.assertEqual(len(names), 18)
        for ws in self._BARE:
            self.assertIn(ws, names)
        self.assertEqual(
            [r["checkout"] for r in store.all_workspaces(db) if r["name"] in self._BARE],
            [None] * 4,                                    # NULL is what bare means
        )
        db.close()

    def test_a_workspace_is_bare_only_when_no_row_carries_a_branch(self):
        """The selector reads the PRESENCE of a branch, never the absence of one.

        `plugins-redesign` and `workspace-model` are real names with real worktrees whose
        rows disagree about `branch`. Under the looser reading they fill in as having no
        checkout — which destroys nothing on the day, and permanently routes two real
        worktrees to the bare path: no gate, no live observation, and nothing left that
        can ever remove the worktree or the branch. The fill runs once, so it is the
        permanent answer.
        """
        db = self._migrated()
        for ws in self._MIXED:
            with self.subTest(ws):
                self.assertEqual(store.get_workspace(db, ws)["checkout"], f"/wt/{ws}")
        db.close()

    def test_the_fill_is_safe_to_run_a_second_time(self):
        """Its create and its fill are two transactions, so a fill may meet a table
        somebody else made and rows somebody else wrote."""
        db = self._migrated()
        store.record_workspace(db, "main", "/somewhere/else")
        store._backfill_workspaces(db, None)
        self.assertEqual(store.get_workspace(db, "main")["checkout"], "/somewhere/else")
        self.assertEqual(len(store.all_workspaces(db)), 18)
        db.close()

    # -- the fill's completion, and a store where it never ran -----------

    def test_a_store_where_the_fill_never_ran_says_so_rather_than_reading_empty(self):
        """The fill's only input is `agents.cwd`, and it is not durable: anything that
        empties the store between this shipping and the first `sb` that runs the fill
        leaves it permanently unperformed. An unfilled store and a store with genuinely no
        workspaces are the same empty query, so anything about to act on a workspace being
        unrecorded has to ask — and refuse with what it is told, naming what a person can
        do about it, rather than silently treating every workspace as unrecorded."""
        p = self._populated_store()
        db = sqlite3.connect(str(p))                       # opened without reconciling
        db.row_factory = sqlite3.Row
        gap = store.workspace_fill_gap(db)
        self.assertIsNotNone(gap)
        self.assertIn("never been filled", gap)
        self.assertIn("sb status", gap)                    # and what to do about it
        db.close()
        self.assertIsNone(store.workspace_fill_gap(self._migrated()))

    def test_a_fresh_store_has_no_gap_to_report(self):
        """Nothing to derive, so nothing outstanding — a new store is not a broken one."""
        db = store.connect(path=Path(self.tmp.name) / "fresh.db")
        self.assertIsNone(store.workspace_fill_gap(db))
        self.assertEqual(store.all_workspaces(db), [])
        db.close()

    # -- the retiring mark -----------------------------------------------

    def test_only_one_of_two_racing_callers_takes_the_retiring_mark(self):
        """Two connections, one row, the same instant. `rowcount` on a write guarded by
        `retiring IS NULL` is the arbiter — the same shape as `claim_agent`, and for the
        same reason: a read followed by a write is two statements with a race between
        them, and this one guards a destructive command."""
        p = self._populated_store()
        one, two = self._migrated(p), store.connect(path=p)   # one store, two processes
        store.record_workspace(one, "adv-r4", "/wt/adv-r4")
        won = [store.claim_retiring(db, "adv-r4", owner)
               for db, owner in ((one, "alice"), (two, "bob"))]
        self.assertEqual(won, [True, False])
        row = store.get_workspace(two, "adv-r4")
        self.assertEqual(row["retiring"], "alice")
        self.assertIsNotNone(row["retiring_at"])           # and when, so a refusal can say
        one.close(); two.close()

    def test_a_mark_is_released_by_its_owner_and_by_nobody_else(self):
        """A flag has no owner and a losing invocation could clear it. This one cannot."""
        db = self._migrated()
        store.record_workspace(db, "adv-r4", "/wt/adv-r4")
        self.assertTrue(store.claim_retiring(db, "adv-r4", "alice"))
        self.assertFalse(store.release_retiring(db, "adv-r4", "bob"))
        self.assertEqual(store.get_workspace(db, "adv-r4")["retiring"], "alice")
        self.assertTrue(store.release_retiring(db, "adv-r4", "alice"))
        self.assertIsNone(store.get_workspace(db, "adv-r4")["retiring"])
        self.assertTrue(store.claim_retiring(db, "adv-r4", "bob"))   # free again
        db.close()

    def test_nothing_claims_a_mark_on_a_workspace_that_has_no_row(self):
        db = self._migrated()
        self.assertFalse(store.claim_retiring(db, "never-heard-of-it", "alice"))
        self.assertIsNone(store.get_workspace(db, "never-heard-of-it"))
        db.close()

    # -- the path as a record, and retirement ----------------------------

    def test_the_path_records_where_the_checkout_is_not_where_it_was(self):
        db = self._migrated()
        store.record_workspace(db, "ws0", "/wt/moved")     # re-written on every attach
        self.assertEqual(store.get_workspace(db, "ws0")["checkout"], "/wt/moved")
        db.close()

    def test_retiring_clears_the_path_and_reopening_makes_the_name_live_again(self):
        """Retirement is not a tombstone on a name: the name is identity, and a person who
        types it again means the workspace they are naming."""
        db = self._migrated()
        store.claim_retiring(db, "ws0", "alice")
        store.retire_workspace(db, "ws0")
        row = store.get_workspace(db, "ws0")
        self.assertIsNotNone(row["retired_at"])
        self.assertIsNone(row["checkout"])                 # there is no checkout now
        self.assertIsNone(row["retiring"])
        store.reopen_workspace(db, "ws0", "/wt/ws0")
        row = store.get_workspace(db, "ws0")
        self.assertIsNone(row["retired_at"])
        self.assertEqual(row["checkout"], "/wt/ws0")
        db.close()

    # -- re-validation, which has three answers ---------------------------

    def _repo(self, name: str) -> Path:
        import subprocess
        d = Path(self.tmp.name) / name
        d.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "-m", "x"], cwd=d, capture_output=True)
        return d

    def _worktree(self, repo: Path, name: str) -> Path:
        import subprocess
        wt = Path(self.tmp.name) / name
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", name],
                       cwd=repo, capture_output=True)
        return wt

    def test_a_live_worktree_of_this_repo_is_the_first_verdict(self):
        repo = self._repo("repo")
        wt = self._worktree(repo, "side")
        self.assertEqual(store.checkout_verdict(str(wt), repo), store.CHECKOUT_OK)
        # git reports the primary checkout alongside the linked ones, and it is one.
        self.assertEqual(store.checkout_verdict(str(repo), repo), store.CHECKOUT_OK)

    def test_a_directory_that_is_gone_is_a_resolved_answer_not_an_unresolvable_one(self):
        """The second verdict is the whole reason there are three. Every path in the store
        is a filled-in one and six of them point at directories that no longer exist —
        exactly the population the cheap already-gone path exists for. Collapsed into a
        boolean, the rule that stops a filled-in path being trusted is the rule that makes
        that path refuse on the rows it was written for."""
        import shutil as sh
        repo = self._repo("repo")
        wt = self._worktree(repo, "side")
        sh.rmtree(wt)                                      # the worktree is still registered
        self.assertEqual(store.checkout_verdict(str(wt), repo), store.CHECKOUT_ABSENT)
        self.assertEqual(store.checkout_verdict(str(repo / "never-existed"), repo),
                         store.CHECKOUT_ABSENT)

    def test_anything_else_refuses_because_unknown_is_not_empty(self):
        repo = self._repo("repo")
        other = self._repo("other")                        # a real checkout of another repo
        plain = Path(self.tmp.name) / "plain"; plain.mkdir()
        afile = Path(self.tmp.name) / "afile"; afile.write_text("x")
        cases = {
            "another repo": str(other),
            "not a worktree at all": str(plain),
            "not a directory": str(afile),
            "no path on a workspace that is not bare": None,
        }
        for label, path in cases.items():
            with self.subTest(label):
                self.assertEqual(store.checkout_verdict(path, repo),
                                 store.CHECKOUT_UNUSABLE)

    def test_a_git_that_will_not_answer_refuses_too(self):
        """"Cannot tell" is not "nobody is there", and this is asked in front of a
        destructive command."""
        wt = self._worktree(self._repo("repo"), "side")
        outside = Path(self.tmp.name) / "outside"; outside.mkdir()
        self.assertEqual(store.checkout_verdict(str(wt), outside),
                         store.CHECKOUT_UNUSABLE)

    def test_a_git_that_never_answers_is_bounded_and_refuses(self):
        """The regression. This call was the one subprocess in the teardown change with no
        timeout, so a hung git did not produce a wrong verdict — it produced no verdict at
        all, hanging the destructive command before it had decided anything."""
        import subprocess
        wt = self._worktree(self._repo("repo"), "side")
        seen = {}
        real = subprocess.run

        def run(args, **kw):
            seen.update(kw)
            raise subprocess.TimeoutExpired(args, kw.get("timeout"))
        subprocess.run = run
        try:
            verdict = store.checkout_verdict(str(wt), Path(self.tmp.name))
        finally:
            subprocess.run = real
        self.assertEqual(verdict, store.CHECKOUT_UNUSABLE)
        self.assertTrue(seen.get("timeout"), "the call runs with no timeout")


class UnhookedTurnRepairTest(unittest.TestCase):
    """The one-time repair of `agents.turn` values no hook ever wrote.

    `Broker._revive` used to stamp `working` on any agent that ran an `sb` command after
    reporting done. For a session that carries the hooks that was redundant; for one that
    predates them it was permanent, because that session has no `Stop` hook to write the
    matching end. The writer is gone — this is what it left behind, and the only thing
    that tells a wedged edge from a live one is whether a hook was ever seen for that row.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")
        self.addCleanup(self.db.close)
        # `connect` has already run and recorded it; these rows are the ones an older
        # checkout left, so put the store back to before it ran.
        self.db.execute("DELETE FROM meta WHERE key=?",
                        (f"backfill:{store._TURN_REPAIR_KEY}",))
        self.db.commit()

    def test_an_edge_no_hook_wrote_is_dropped_and_one_that_was_is_kept(self):
        store.create_agent(self.db, name="top", role="lead")
        store.create_agent(self.db, name="kid", role="worker")
        for name in ("top", "kid"):
            store.set_turn(self.db, name, store.TURN_WORKING)
        # Only `kid` has a hook behind its edge — `mark_turn` logs one beside every write.
        store.log_event(self.db, kind="turn_start", target="kid")

        store._repair_unhooked_turn(self.db)

        self.assertIsNone(store.get_agent(self.db, "top")["turn"])
        self.assertEqual(store.get_agent(self.db, "kid")["turn"], store.TURN_WORKING)

    def test_it_runs_once_and_never_touches_a_later_edge(self):
        """Recorded in `meta`, so an agent whose hooks write `working` after the repair has
        run is not re-repaired on the next command — the mark is a fact about having run,
        not an inference from the schema."""
        store.create_agent(self.db, name="top", role="lead")
        store.set_turn(self.db, "top", store.TURN_WORKING)
        store._repair_unhooked_turn(self.db)
        self.assertIsNone(store.get_agent(self.db, "top")["turn"])

        store.set_turn(self.db, "top", store.TURN_WORKING)   # a hook, later
        store._repair_unhooked_turn(self.db)
        self.assertEqual(store.get_agent(self.db, "top")["turn"], store.TURN_WORKING)


if __name__ == "__main__":
    unittest.main()
