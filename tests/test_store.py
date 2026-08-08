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

    def test_an_unknown_column_does_not_force_a_reset(self):
        """A newer `sb`, run from another checkout against the same store, adds a column
        this code has never heard of. Older code must keep working: two checkouts share
        one store, and reading the extra column as destructive wedged every agent on the
        machine once already."""
        p = Path(self.tmp.name) / "destructive.db"
        d = store.connect(path=p)
        store.create_agent(d, name="w", role="worker")
        d.execute("ALTER TABLE agents ADD COLUMN added_by_newer_sb TEXT")
        self.assertEqual(store._deficit(d), ([], []))         # nothing missing: no reset
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

    _SPLIT = "    ended_at      INTEGER,\n    branch        TEXT NOT NULL\n"

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
            self.assertIn("branch", {r[1] for r in d3.execute("PRAGMA table_info(agents)")})
            d3.close()

    def test_a_missing_table_is_blocking_not_addable(self):
        p = Path(self.tmp.name) / "notable.db"
        d = store.connect(path=p)
        d.execute("DROP TABLE events")
        addable, blocking = store._deficit(d)
        self.assertEqual(addable, [])
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


if __name__ == "__main__":
    unittest.main()
