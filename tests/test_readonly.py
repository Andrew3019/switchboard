"""A reader must not be able to migrate the store.

`store.connect()` is not a reader. On a store whose SCHEMA text was written by a different
checkout it re-stamps `meta`, CREATEs and ALTERs tables and backfills every agent row,
and — when something missing can be given to no existing row — REBUILDS the store,
dropping every table `SCHEMA` declares. Three worktrees on three branches share one store
here, so "the SCHEMA text differs" is the normal case, and a board reconnecting every two
seconds is the process most likely to reach every one of those paths.

These tests do not check that a flag exists. Each one arranges the exact store shape that
made a reader destructive and asserts the destruction did not happen: the stamp, the
columns and the rows are all still what the writer left.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from switchboard import collector, store
from switchboard import herdr as herdr_mod

FOREIGN = "ffffffffffffffff"          # some other checkout's SCHEMA text stamped the store


class ReadonlyConnection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.db"
        db = store.connect(path=self.path)
        store.create_agent(db, name="w1", role="worker", session_id="s1")
        store.put_message(db, from_agent="w1", to_agent="lead", kind="tell", body="hello")
        db.close()

    def _stamp_foreign(self, extra_sql: str = "") -> None:
        """Make the store look like another checkout's, which is what arms `_reconcile`."""
        db = sqlite3.connect(str(self.path))
        db.execute("UPDATE meta SET value=? WHERE key='schema_hash'", (FOREIGN,))
        if extra_sql:
            db.executescript(extra_sql)
        db.commit()
        db.close()

    def _read(self, sql: str):
        db = sqlite3.connect(str(self.path))
        db.row_factory = sqlite3.Row
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()

    # -- the guarantee ---------------------------------------------------

    def test_every_kind_of_write_raises_rather_than_being_ignored(self):
        """Loudly, not silently. A reader that no-ops its way past a write is a worse bug
        than one that writes: the second is visible in the store, the first is visible
        nowhere."""
        db = store.connect(path=self.path, readonly=True)
        self.addCleanup(db.close)
        for sql in (
            "UPDATE agents SET state='failed' WHERE name='w1'",
            "INSERT INTO events(kind, created_at) VALUES ('x', 1)",
            "DELETE FROM messages",
            "ALTER TABLE agents ADD COLUMN newer_col TEXT",
            "DROP TABLE events",
            # `connect()`'s own first statement. (`IF NOT EXISTS` against a table that is
            # already there is a real no-op and raises nothing — the write is what fails,
            # so the case worth pinning is the one where there is a write to attempt.)
            "CREATE TABLE IF NOT EXISTS meta2 (key TEXT PRIMARY KEY, value TEXT)",
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', 'x')",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.OperationalError) as cm:
                    db.execute(sql)
                self.assertIn("readonly", str(cm.exception))
        self.assertEqual(self._read("SELECT state FROM agents")[0]["state"], "working")

    def test_reading_still_works(self):
        db = store.connect(path=self.path, readonly=True)
        self.addCleanup(db.close)
        self.assertEqual(store.get_agent(db, "w1")["role"], "worker")
        self.assertEqual(len(store.unread_for(db, "lead", mark=False)), 1)

    # -- the three write paths a board tick holds ------------------------

    def test_A_a_foreign_stamp_is_not_restamped(self):
        """`_reconcile`'s cheapest outcome, and the gateway to the other two. Benign in
        content; a write transaction on a shared store all the same, and with a newer `sb`
        in another checkout it is a stamp-back-and-forth at 0.5 Hz forever."""
        self._stamp_foreign("ALTER TABLE agents ADD COLUMN newer_col TEXT;")
        db = store.connect(path=self.path, readonly=True)
        self.addCleanup(db.close)
        self.assertEqual(store.get_agent(db, "w1")["name"], "w1")   # it still reads
        after = self._read("SELECT value FROM meta WHERE key='schema_hash'")[0]["value"]
        self.assertEqual(after, FOREIGN)

    def test_B_a_missing_column_is_not_altered_in_and_no_row_is_backfilled(self):
        """The path that wrote all 53 agent rows in the probe: ALTER TABLE, then
        `_backfill_branch` over every row."""
        self._stamp_foreign("ALTER TABLE agents DROP COLUMN branch;")
        db = store.connect(path=self.path, readonly=True)
        self.addCleanup(db.close)
        self.assertNotIn("branch", store._columns(db, "agents"))
        # And it says so instead of fixing it — the right answer for a viewer.
        with self.assertRaises(sqlite3.OperationalError):
            db.execute("SELECT branch FROM agents").fetchall()
        self.assertNotIn("branch", {r[1] for r in self._read("PRAGMA table_info(agents)")})
        self.assertEqual(self._read("SELECT value FROM meta WHERE key='schema_hash'")[0][0],
                         FOREIGN)

    def test_C_a_reader_cannot_drop_the_store(self):
        """The unrecoverable one. `events` declares NOT NULL columns with no default, so a
        store without it is missing rows this code cannot invent for it: still `blocking`,
        where an all-nullable missing table is created and filled instead. `_reconcile`
        answers `blocking` with `_reset`, and `_reset` drops every table `SCHEMA` declares.
        In the probe on the live store this cost 53 agent rows and 162 messages."""
        self._stamp_foreign(
            "UPDATE agents SET state='done', ended_at=1;"      # nothing live to guard them
            "DROP TABLE events;"
        )
        db = store.connect(path=self.path, readonly=True)
        self.addCleanup(db.close)
        self.assertEqual(self._read("SELECT COUNT(*) c FROM agents")[0]["c"], 1)
        self.assertEqual(self._read("SELECT COUNT(*) c FROM messages")[0]["c"], 1)
        # `events` was missing before and is still missing: not recreated, not repaired.
        self.assertEqual(self._read(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name='events'"
        )[0]["c"], 0)

    # -- the store that is not there yet ---------------------------------

    def test_a_reader_does_not_create_a_store_that_is_not_there(self):
        """`mode=ro` cannot create the file, and we do not create it for it. An empty store
        conjured by a viewer is indistinguishable from a real one, and would tell the next
        writer its schema was current."""
        missing = Path(self.tmp.name) / "sub" / "nothing.db"
        with self.assertRaises(FileNotFoundError) as cm:
            store.connect(path=missing, readonly=True)
        self.assertIn("no store yet", str(cm.exception))
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())   # not even the directory

    def test_a_writer_still_creates_it(self):
        """The counterpart, so the asymmetry is the tested thing rather than a side effect
        of the reader's check."""
        fresh = Path(self.tmp.name) / "sub" / "fresh.db"
        db = store.connect(path=fresh)
        self.addCleanup(db.close)
        self.assertTrue(fresh.exists())
        self.assertEqual(store.live_agents(db), [])


class CollectorTick(unittest.TestCase):
    """The same thing end to end, through the process that actually does it.

    `ReadonlyConnection` proves the connection cannot write. This proves the long-lived
    poller asks for that connection — the one line that turns the guarantee into a fix.

    It used to say `board`. The connect moved to `switchboard/collector.py` when the panel
    split into one collector and many renderers, and this test moved with it, unchanged in
    substance: the subject was never "the board" but "the process that connects every two
    seconds for hours on the code it imported at startup". There is now exactly one of
    those per repo instead of one per pane, and the board cannot reach the store at all
    (`tests/test_panel.py::RendererImports`).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.db"
        db = store.connect(path=self.path)
        store.create_agent(db, name="w1", role="worker", session_id="s1")
        db.execute("UPDATE meta SET value=? WHERE key='schema_hash'", (FOREIGN,))
        db.execute("ALTER TABLE agents ADD COLUMN newer_col TEXT")   # a newer `sb`'s column
        db.commit()
        db.close()

    def test_a_tick_against_a_foreign_stamp_migrates_nothing(self):
        class NoAgents:
            def list_agents(self): return []

        with mock.patch.object(store, "db_path", lambda *a, **k: self.path), \
             mock.patch.object(herdr_mod, "Herdr", NoAgents):
            s, err = collector.snapshot()

        self.assertIsNone(err)
        self.assertTrue(s.agents[0].gone)        # it still renders the drift

        db = sqlite3.connect(str(self.path))
        self.addCleanup(db.close)
        stamp = db.execute("SELECT value FROM meta WHERE key='schema_hash'").fetchone()[0]
        self.assertEqual(stamp, FOREIGN)         # ...and stamped nothing
        row = db.execute("SELECT state, ended_at FROM agents WHERE name='w1'").fetchone()
        self.assertEqual(row[0], "working")
        self.assertIsNone(row[1])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_a_collector_against_a_store_that_does_not_exist_says_so(self):
        """And says it into the snapshot, where every panel shows it — see
        `tests/test_panel.py::Staleness`."""
        missing = Path(self.tmp.name) / "gone.db"
        with mock.patch.object(store, "db_path", lambda *a, **k: missing):
            s, err = collector.snapshot()
        self.assertIsNone(s)
        self.assertIn("no store yet", err)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
