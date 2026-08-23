"""D1 — the workspace as an attachable resource (#163-B, §2.2).

Three properties, and each of them is one that fails SILENTLY if it is wrong:

* **The columns arrive over a live store and the branch's ownership moves with them.**
  `branch` lived on the agent row; it lives on the workspace now, and a migrated row that
  said NULL there would read as BARE — the one wrong answer this area exists to prevent.
* **`agents.branch` still answers.** It is the back-compat read through Phase 2, so every
  existing reader keeps working with no edit, and the workspace only ever ADDS an answer.
* **`attach` commits atomically or not at all, refuses a top, and refuses a live agent.**
  A failed allocation that moved the pointer anyway is torn state nothing repairs.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import ForkFailed, HerdrError, SIGNAL  # noqa: E402

from test_grants import Fixture  # noqa: E402

# The `workspaces` table exactly as it shipped BEFORE this unit (`store.py`, HEAD 85f8fab):
# no `branch`, no `base_ref`, no `created_by`. Written out rather than derived from the
# live SCHEMA, because the point of the fixture is to be the shape a real store on this
# machine is in right now.
_OLD_WORKSPACES = """CREATE TABLE workspaces (
    name          TEXT PRIMARY KEY,
    checkout      TEXT,
    retired_at    INTEGER,
    retiring      TEXT,
    retiring_at   INTEGER,
    created_at    INTEGER
)"""


class MigrationTest(unittest.TestCase):
    """A store that already has the table, met by code that declares three more columns.

    NOT the `AddingATableTest` path — that one is covered in `test_store.py` and does not
    run here, because the table's one-time fill is already RECORDED on every store this
    change will meet. What runs is the per-column path: ALTER, then the one fill that has
    a rule to get right.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "old.db"
        db = store.connect(path=self.path)
        # Two worktree spaces and one bare one, in the proportions the real store has:
        # `alpha` has rows that disagree about `branch` (the shape `delegate` writes when
        # a workspace was named rather than inherited), `beta` is ordinary, and `main` is
        # a dispatcher's bare space over the primary checkout.
        rows = [("a-none", "alpha", None, "/wt/alpha", 1),
                ("a-one", "alpha", "alpha", "/wt/alpha", 2),
                ("b-one", "beta", "beta", "/wt/beta", 3),
                ("m-one", "main", None, str(self.tmp.name), 4)]
        db.executemany(
            "INSERT INTO agents (name, role, state, workspace, branch, cwd, cleanup,"
            " created_at) VALUES (?, 'worker', 'done', ?, ?, ?, 'close', ?)", rows)
        # The table as it was, with the rows a live store already carries — including one
        # retired name, which has no branch to move and must not acquire one.
        db.execute("DROP TABLE workspaces")
        db.execute(_OLD_WORKSPACES)
        db.executemany(
            "INSERT INTO workspaces(name, checkout, retired_at, created_at) VALUES(?,?,?,?)",
            [("alpha", "/wt/alpha", None, 1), ("beta", "/wt/beta", None, 3),
             ("main", None, None, 4), ("old", None, 99, 5)])
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash','older')")
        db.commit()
        self.before = self._dump(db)
        db.close()

    @staticmethod
    def _dump(db) -> dict:
        """Every row of every table a migration must not touch, as comparable tuples."""
        return {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in ("agents", "messages", "events")}

    def _migrated(self):
        with mock.patch.object(store, "_herdr_alive", lambda: set()):
            return store.connect(path=self.path)

    def test_the_columns_arrive_and_nothing_else_moves(self):
        """The migration is an ALTER, not a rebuild: no live fleet is wedged and no row is
        rewritten. Diffed rather than spot-checked — a fill with a stray UPDATE in it is
        exactly the failure a spot-check misses."""
        db = self._migrated()
        self.assertEqual(store.schema_deficit(db), [])
        self.assertEqual(self._dump(db), self.before)
        cols = {r[1] for r in db.execute("PRAGMA table_info(workspaces)")}
        self.assertLessEqual({"branch", "base_ref", "created_by"}, cols)
        self.assertIn("name", cols)                  # STILL the name PK, not re-keyed
        self.assertEqual(
            db.execute("SELECT count(*) FROM pragma_table_info('workspaces') "
                       "WHERE pk=1 AND name='name'").fetchone()[0], 1)
        db.close()

    def test_the_branch_moves_onto_the_workspace(self):
        """Ownership, migrated: the fact every reader used to derive by grouping agent rows
        is written down once, by exactly that selector. A worktree space that came out NULL
        would be permanently BARE — no gate, no teardown, nothing that can ever remove the
        worktree or the branch."""
        db = self._migrated()
        self.assertEqual(store.get_workspace(db, "alpha")["branch"], "alpha")
        self.assertEqual(store.get_workspace(db, "beta")["branch"], "beta")
        self.assertIsNone(store.get_workspace(db, "main")["branch"])   # bare stays bare
        self.assertIsNone(store.get_workspace(db, "old")["branch"])    # no rows, no branch
        # Neither of the other two is derivable from anything the store holds, so neither
        # is invented: NULL says "nobody wrote this down".
        self.assertIsNone(store.get_workspace(db, "alpha")["base_ref"])
        self.assertIsNone(store.get_workspace(db, "alpha")["created_by"])
        db.close()

    def test_the_fill_is_safe_to_run_again(self):
        """Two processes that both computed the deficit before either acted is the ordinary
        state of this machine, so the fill may meet rows somebody else already answered
        for — and must leave them alone."""
        db = self._migrated()
        store.record_workspace(db, "beta", "/wt/beta", branch="renamed")
        store._backfill_workspace_branch(db, None)
        self.assertEqual(store.get_workspace(db, "beta")["branch"], "renamed")
        self.assertEqual(store.get_workspace(db, "alpha")["branch"], "alpha")
        db.close()

    def test_a_store_written_after_the_change_reads_the_same(self):
        """The round trip: a fresh store takes the columns from the SCHEMA, so nothing here
        depends on having been migrated."""
        db = store.connect(path=Path(self.tmp.name) / "fresh.db")
        store.record_workspace(db, "gamma", "/wt/gamma", branch="gamma",
                               base_ref="origin/main", created_by="lead-x")
        row = store.get_workspace(db, "gamma")
        self.assertEqual((row["branch"], row["base_ref"], row["created_by"]),
                         ("gamma", "origin/main", "lead-x"))
        self.assertEqual(store.workspace_branch(db, "gamma"), "gamma")
        # An attach that only knows the path does not erase what the fork recorded.
        store.record_workspace(db, "gamma", "/wt/moved")
        row = store.get_workspace(db, "gamma")
        self.assertEqual((row["checkout"], row["branch"], row["created_by"]),
                         ("/wt/moved", "gamma", "lead-x"))
        db.close()


class BackCompatReadTest(unittest.TestCase):
    """`agents.branch` is kept as a back-compat derived read through Phase 2 — so every
    existing reader keeps working with no edit."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = store.connect(path=Path(self.tmp.name) / "s.db")
        self.addCleanup(self.db.close)

    def test_the_workspace_answers_first(self):
        """Ownership moved, so the resource is asked before the row it moved off."""
        store.create_agent(self.db, name="w", role="worker", workspace="alpha",
                           branch="alpha")
        store.record_workspace(self.db, "alpha", "/wt/alpha", branch="alpha-renamed")
        self.assertEqual(store.agent_branch(self.db, "w"), "alpha-renamed")
        self.assertEqual(store.workspace_branch(self.db, "alpha"), "alpha-renamed")

    def test_the_agent_row_still_answers_when_the_workspace_cannot(self):
        """The fallback only ever ADDS an answer, and this is the case that needs it: a
        store mid-migration, a retired workspace whose branch was cleared with its
        checkout, and an agent attached to nothing. None may read as bare by accident."""
        store.create_agent(self.db, name="w", role="worker", workspace="alpha",
                           branch="alpha")
        self.assertEqual(store.agent_branch(self.db, "w"), "alpha")   # no workspace row
        store.record_workspace(self.db, "alpha", "/wt/alpha", branch="alpha")
        store.retire_workspace(self.db, "alpha")
        self.assertIsNone(store.get_workspace(self.db, "alpha")["branch"])
        self.assertEqual(store.agent_branch(self.db, "w"), "alpha")
        # And the column itself is untouched, which is what a RAW reader sees.
        self.assertEqual(
            self.db.execute("SELECT branch FROM agents WHERE name='w'").fetchone()[0],
            "alpha")

    def test_a_degraded_store_falls_back_rather_than_raising(self):
        """`connect()` may serve a store narrower than this schema rather than rebuild under
        a live fleet, and a read that raised `IndexError` there would refuse the whole
        machine — the wedge `test_schema_guard` exists for."""
        self.db.execute("DROP TABLE workspaces")
        self.db.execute(_OLD_WORKSPACES)
        store.create_agent(self.db, name="w", role="worker", workspace="alpha",
                           branch="alpha")
        self.db.execute("INSERT INTO workspaces(name, checkout) VALUES('alpha','/wt/a')")
        self.db.commit()
        self.assertEqual(store.agent_branch(self.db, "w"), "alpha")
        self.assertEqual(store.workspace_branch(self.db, "alpha"), "alpha")


class AttachTest(Fixture, unittest.TestCase):
    """`attach` — the changeable pointer, and the three things it refuses."""

    def setUp(self):
        super().setUp()
        self.topa = self.top()
        self.lead = self.spawn(self.topa, "lead", "l")      # forks a worktree of its own
        self.worker = self.spawn(self.lead, "worker", "w")  # shares the lead's space

    def _closed(self, name: str) -> str:
        """An agent that is not running — the set an attach applies to."""
        store.set_state(self.db, name, "done")
        return name

    def test_the_fork_records_the_workspace_it_minted(self):
        """The resource facts have ONE moment at which they are known, and this is it."""
        row = store.get_workspace(self.db, self.lead)
        self.assertEqual(row["branch"], self.lead)
        self.assertEqual(row["created_by"], self.topa)
        self.assertIsNotNone(row["checkout"])

    def test_an_agent_is_re_attached_and_told(self):
        """§2.2: a single changeable name reference, settable after spawn — and the move
        and the signal are one transaction (C4), so the agent cannot be somewhere it does
        not know about."""
        self._closed(self.worker)
        out = self.b.attach(self.worker, "elsewhere", me=self.lead)
        row = store.get_agent(self.db, self.worker)
        self.assertEqual(store.attached_workspace(self.db, self.worker), "elsewhere")
        self.assertEqual(out["previous"], self.lead)
        self.assertEqual(store.agent_branch(self.db, self.worker), "elsewhere")
        self.assertEqual(row["cwd"], store.get_workspace(self.db, "elsewhere")["checkout"])
        [m] = store.unread_for(self.db, self.worker, mark=False)
        self.assertEqual(m["kind"], SIGNAL)
        self.assertIn("elsewhere", m["body"])
        self.assertEqual(m["from_agent"], self.lead)

    def test_the_top_is_never_re_attached(self):
        """§2.0: the top's bare space sits ABOVE the worktrees and every fork in the fleet
        forks from it. Attaching it would put it INSIDE one, and destroy that placement
        without touching a grant, a parent link or the stamp."""
        self._closed(self.topa)
        with self.assertRaises(ValueError) as e:
            self.b.attach(self.topa, "elsewhere", me=self.topa)
        self.assertIn("top dispatcher", str(e.exception))
        self.assertEqual(store.attached_workspace(self.db, self.topa), self.topa)
        self.assertEqual(store.unread_for(self.db, self.topa, mark=False), [])

    def test_a_live_agent_is_refused(self):
        """Pointer-only, and scoped to agents that have not started: moving a running
        agent's cwd and pane is out of scope by design, and the store is never allowed to
        say a running process is somewhere it is not."""
        with self.assertRaises(ValueError) as e:
            self.b.attach(self.worker, "elsewhere", me=self.lead)
        self.assertIn("already running", str(e.exception))
        self.assertEqual(store.attached_workspace(self.db, self.worker), self.lead)

    def test_a_failed_allocation_leaves_the_pointer_where_it_was(self):
        """THE ATOMICITY PROPERTY. Attach is allocate-then-point and the allocation can
        fail (`ForkFailed`) — so it happens first and entirely outside the transaction. A
        pointer that moved anyway would name a checkout that does not exist, with no fork
        to make one and nothing that repairs it."""
        self._closed(self.worker)
        before = dict(store.get_agent(self.db, self.worker))
        with mock.patch.object(
            type(self.b), "_attach_workspace",
            side_effect=HerdrError("worktree_exists", "no")
        ):
            with self.assertRaises(ForkFailed):
                self.b.attach(self.worker, "elsewhere", me=self.lead)
        after = dict(store.get_agent(self.db, self.worker))
        self.assertEqual((after["workspace"], after["branch"], after["cwd"]),
                         (before["workspace"], before["branch"], before["cwd"]))
        self.assertIsNone(store.get_workspace(self.db, "elsewhere"))
        self.assertEqual(store.unread_for(self.db, self.worker, mark=False), [])
