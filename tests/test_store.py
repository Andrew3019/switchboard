"""Store tests. stdlib unittest — no dependencies.

Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import hashlib
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

    def test_create_and_fetch(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        a = store.get_agent(self.db, "orch")
        self.assertEqual(a["role"], "orchestrator")
        self.assertEqual(a["state"], "working")
        self.assertIsNone(a["parent"])          # root
        self.assertEqual(a["cleanup"], "close") # aggressive default; restore makes it safe

    def test_identity_by_session(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-abc")
        self.assertEqual(store.agent_by_session(self.db, "sess-abc")["name"], "w1")
        self.assertIsNone(store.agent_by_session(self.db, "nope"))

    def test_tree(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="a", role="calc", parent="orch")
        store.create_agent(self.db, name="b", role="calc", parent="orch")
        self.assertEqual([r["name"] for r in store.children_of(self.db, "orch")], ["a", "b"])

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

    def test_seq_is_per_agent(self):
        store.create_agent(self.db, name="a", role="worker")
        store.create_agent(self.db, name="b", role="worker")
        store.next_seq(self.db, "a"); store.next_seq(self.db, "a")
        self.assertEqual(store.next_seq(self.db, "b"), 1)  # scoped per (source, pane)

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

    def test_live_roots_is_what_is_running_not_what_ever_ran(self):
        """The store keeps every root ever created; without the filter this is history.

        The argument is a ROLE. Agent names ('main', 'main-2') are not roles, and passing
        one here matches nothing at all — the failure mode this filter exists to fix.
        """
        for name in ("main", "main-2", "main-3"):
            store.create_agent(self.db, name=name, role="orchestrator")
        store.create_agent(self.db, name="kid", role="orchestrator", parent="main")
        store.set_state(self.db, "main", "done")
        store.set_state(self.db, "main-2", "failed")
        store.create_agent(self.db, name="side", role="worker")
        self.assertEqual([r["name"] for r in store.live_roots(self.db, "orchestrator")],
                         ["main-3"])            # not the ended ones, not a child, not
                                                # another role
        self.assertEqual(store.live_roots(self.db, "main"), [])     # a name is not a role

    def test_live_roots_keeps_a_blocked_one(self):
        """Blocked is waiting on a person, not finished — it is still up."""
        store.create_agent(self.db, name="main", role="orchestrator")
        store.set_state(self.db, "main", "blocked")
        self.assertEqual([r["name"] for r in store.live_roots(self.db, "orchestrator")],
                         ["main"])

    # -- messages --------------------------------------------------------

    def test_inbox_returns_all_unread_and_marks_read(self):
        store.create_agent(self.db, name="p", role="orchestrator")
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

    def test_pending_ask_correlation(self):
        """A plain `tell` answers an `ask`; correlation is the tool's job, not the agent's."""
        ask = store.put_message(self.db, from_agent="p", to_agent="c", kind="ask", body="q?")
        self.assertEqual(store.pending_ask(self.db, asker="p", target="c")["id"], ask)

        store.put_message(self.db, from_agent="c", to_agent="p", kind="tell",
                          body="a!", reply_to=ask)
        self.assertIsNone(store.pending_ask(self.db, asker="p", target="c"))
        self.assertEqual(store.reply_to_ask(self.db, ask)["body"], "a!")

    def test_pending_ask_picks_most_recent(self):
        store.put_message(self.db, from_agent="p", to_agent="c", kind="ask", body="q1")
        second = store.put_message(self.db, from_agent="p", to_agent="c", kind="ask", body="q2")
        self.assertEqual(store.pending_ask(self.db, asker="p", target="c")["id"], second)

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

    def test_reconnect_preserves_data(self):
        p = Path(self.tmp.name) / "again.db"
        d1 = store.connect(path=p)
        store.create_agent(d1, name="w", role="worker")
        d1.close()
        d2 = store.connect(path=p)
        self.assertIsNotNone(store.get_agent(d2, "w"))          # no spurious reset
        d2.close()

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

    # -- the branch column -----------------------------------------------
    #
    # `workspace` is a NAME and nothing more — a branch for a worktree space, an agent-ish
    # label for a bare one, with nothing to tell them apart. `branch` is the fact.

    def test_a_row_has_no_branch_unless_it_is_given_one(self):
        """Bare is the default: NULL means "no checkout of my own", and guessing the other
        way hands an agent somebody else's tree."""
        store.create_agent(self.db, name="root", role="main", workspace="main")
        self.assertIsNone(store.get_agent(self.db, "root")["branch"])
        self.assertIsNone(store.agent_branch(self.db, "root"))

    def test_the_branch_is_recorded_and_read_back(self):
        store.create_agent(self.db, name="lead", role="orchestrator", workspace="api",
                           branch="api")
        self.assertEqual(store.agent_branch(self.db, "lead"), "api")

    def test_agent_branch_of_someone_we_have_no_row_for_is_none(self):
        self.assertIsNone(store.agent_branch(self.db, "stranger"))

    def test_a_workspaces_branch_comes_from_whichever_row_recorded_one(self):
        """A checkout belongs to the workspace, so any row in it can answer for it."""
        store.claim_agent(self.db, name="lead", role="orchestrator", workspace="api",
                          branch="api")
        store.claim_agent(self.db, name="kid", role="worker", workspace="api",
                          branch="api")
        self.assertEqual(store.workspace_branch(self.db, "api"), "api")

    def test_a_bare_workspace_has_no_branch_but_is_still_known(self):
        """The two answers that must not be confused: a place with no checkout, and a name
        we have never heard of."""
        store.create_agent(self.db, name="root", role="main", workspace="scratch")
        self.assertIsNone(store.workspace_branch(self.db, "scratch"))
        self.assertTrue(store.known_workspace(self.db, "scratch"))
        self.assertFalse(store.known_workspace(self.db, "never-seen"))

    def test_the_branch_may_be_updated(self):
        store.create_agent(self.db, name="w", role="worker", workspace="api")
        store.update_agent(self.db, "w", branch="api")
        self.assertEqual(store.agent_branch(self.db, "w"), "api")

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
            "VALUES ('lead', 'orchestrator', 'working', ?, 'api', 'keep', 1)",
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
                  "created_at) VALUES ('lead', 'orchestrator', 'working', '/wt/api', "
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

    def test_transcript_path_needs_session_and_cwd(self):
        store.create_agent(self.db, name="w", role="worker")
        self.assertIsNone(store.transcript_path(store.get_agent(self.db, "w")))


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


if __name__ == "__main__":
    unittest.main()
