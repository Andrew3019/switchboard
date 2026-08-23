"""Unit F1 — `parent` as a mutable column behind a THIN resolver (spec §2.3, §6.7, §10.2).

Nothing re-parents yet: promote is F2. What F1 ships is the resolver and the torn-read
safety the mutation will need, so every test here drives the move with a raw `UPDATE` —
the exact statement F2 will issue — and asks whether the readers follow it.

The properties, one test each:

* the resolver follows the column, and `done`/`cleanup` follow the resolver rather than a
  row read earlier in the same call;
* the ONE reader that is a multi-statement walk (`_descendants`) sees the pre-state or the
  post-state and never a torn mix of both — with a control that shows the walk really does
  tear without its snapshot, so the guard is pinned to a hazard rather than a hope;
* `hooks._has_live_child` stays a raw, broker-independent, fail-open copy — the reason the
  resolver has to stay thin in the first place.
"""

from __future__ import annotations

import ast
import inspect
import re
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import broker as broker_mod  # noqa: E402
from switchboard import hooks  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import HUMAN  # noqa: E402

from test_grants import Fixture  # noqa: E402


def _reparent(db_path: Path, child: str, new_parent) -> None:
    """The re-parent write, from ANOTHER connection — one committed `UPDATE`.

    A second connection on purpose: the point of every concurrency test here is that the
    write lands from somewhere else, mid-read, exactly as a promote by another `sb`
    process would.
    """
    other = sqlite3.connect(str(db_path), timeout=5)
    try:
        other.execute("UPDATE agents SET parent=? WHERE name=?", (new_parent, child))
        other.commit()
    finally:
        other.close()


class ResolverTest(Fixture, unittest.TestCase):
    def family(self) -> None:
        store.create_agent(self.db, name="top", role="dispatcher", is_top=True)
        store.create_agent(self.db, name="proxy", role="researcher", parent="top")
        store.create_agent(self.db, name="kid", role="worker", parent="proxy",
                           pane_id="w1:p1")

    def test_the_resolver_reads_the_column_now_not_at_spawn(self):
        self.family()
        self.assertEqual(self.b.current_parent("kid"), "proxy")
        _reparent(self.repo / "state.db", "kid", "top")
        self.assertEqual(self.b.current_parent("kid"), "top")
        self.assertEqual(store.current_parent(self.db, "kid"), "top")

    def test_the_resolver_says_none_for_a_root_and_for_a_row_that_is_not_there(self):
        """Thin means thin: no fallback, no invention. `None` for both, and it is the
        caller that turns it into HUMAN (`_resolve`) or into 'nobody to mail' (`done`)."""
        store.create_agent(self.db, name="root", role="lead")
        self.assertIsNone(self.b.current_parent("root"))
        self.assertIsNone(self.b.current_parent("never-existed"))

    def test_done_mails_the_parent_it_has_now(self):
        """Raw reader 3. `done` read `a["parent"]` off a row fetched at the top of the
        call; with a mutable column that copy can predate the move."""
        self.family()
        _reparent(self.repo / "state.db", "kid", "top")
        self.b.done("finished", me="kid")
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "top")],
                         ["[done] finished"])
        self.assertEqual(store.unread_for(self.db, "proxy"), [])

    def test_tell_parent_resolves_live(self):
        """Raw reader 1 — the PARENT sentinel."""
        self.family()
        _reparent(self.repo / "state.db", "kid", "top")
        self.b.tell(["parent"], "hi", me="kid")
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "top")], ["hi"])
        self.assertEqual(store.unread_for(self.db, "proxy"), [])

    def test_a_parentless_agent_still_resolves_to_the_human(self):
        store.create_agent(self.db, name="root", role="lead")
        self.assertEqual(self.b._resolve("parent", "root"), HUMAN)

    def test_cleanup_scope_and_the_board_follow_a_re_parent(self):
        """Raw readers 2 and 4 — `_parentage` for the board, `_descendants` for the scope
        `cleanup` and `live_descendants` are computed from."""
        self.family()
        _reparent(self.repo / "state.db", "kid", "top")
        self.assertEqual([a["name"] for a in self.b._descendants("proxy")], [])
        self.assertEqual(sorted(a["name"] for a in self.b._descendants("top")),
                         ["kid", "proxy"])
        self.assertEqual(sorted(self.b.live_descendants("top")), ["kid", "proxy"])
        self.assertEqual(self.b._parentage()["kid"], ("top", False))


class TornWalkTest(Fixture, unittest.TestCase):
    """`_descendants` is the one raw reader that is not a single statement.

    The shape that tears: the walk visits `b` before `a`, collects `b`'s child, and a
    re-parent then moves that child under `a` before `a` is visited. Without one snapshot
    over the walk the child is collected TWICE — a subtree assembled from two different
    trees, which is what `cleanup` would go on to close.
    """

    def setUp(self):
        super().setUp()
        store.create_agent(self.db, name="top", role="dispatcher", is_top=True)
        store.create_agent(self.db, name="a", role="lead", parent="top")
        store.create_agent(self.db, name="b", role="lead", parent="top")
        store.create_agent(self.db, name="b1", role="worker", parent="b")
        self.path = self.repo / "state.db"

    def _move_b1_after_b_is_read(self):
        """`children_of`, wrapped to commit the re-parent the instant `b` is read."""
        real = store.children_of
        state = {"done": False}

        def wrapper(db, name):
            rows = real(db, name)
            if name == "b" and not state["done"]:
                state["done"] = True
                _reparent(self.path, "b1", "a")
            return rows
        return mock.patch.object(store, "children_of", wrapper)

    def test_the_walk_sees_one_tree_when_a_re_parent_lands_mid_walk(self):
        with self._move_b1_after_b_is_read():
            names = [a["name"] for a in self.b._descendants("top")]
        self.assertEqual(sorted(names), ["a", "b", "b1"])       # never twice, never lost
        self.assertEqual(len(names), len(set(names)))
        # and the move really did land mid-walk — otherwise this proves nothing
        self.assertEqual(store.current_parent(self.db, "b1"), "a")

    def test_the_same_walk_without_the_snapshot_does_tear(self):
        """The control. Same loop, same injected write, no `read_snapshot` — the hazard is
        real and this is the line that says so."""
        out, frontier = [], ["top"]
        with self._move_b1_after_b_is_read():
            while frontier:
                kids = store.children_of(self.db, frontier.pop())
                out.extend(kids)
                frontier.extend(k["name"] for k in kids)
        names = [a["name"] for a in out]
        self.assertEqual(names.count("b1"), 2)

    def test_a_snapshot_nests_without_raising_and_reads_the_open_transaction(self):
        """`_descendants` is called from inside `store.mutation` blocks. Nesting must be a
        no-op — the outer transaction is already one consistent view."""
        with store.mutation(self.db):
            self.assertEqual(sorted(a["name"] for a in self.b._descendants("top")),
                             ["a", "b", "b1"])
        self.assertFalse(self.db.in_transaction)


class StopHookStaysRawTest(Fixture, unittest.TestCase):
    """Raw reader 6 — `hooks._has_live_child`, and why the resolver has to stay thin.

    The Stop hook runs in a process that must not import `broker` and must fail open, so
    its `WHERE parent=?` is a deliberate second copy. It is NOT routed through the
    resolver, and these tests are what stops a later hand routing it there.
    """

    def test_the_hook_module_does_not_import_the_broker(self):
        tree = ast.parse(Path(hooks.__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(a.name for a in node.names)
        self.assertNotIn("broker", imported)
        self.assertFalse([m for m in imported if m.endswith("broker")])

    def test_the_two_copies_of_the_parent_sql_still_say_the_same_thing(self):
        def sql(fn) -> str:
            src = inspect.getsource(fn)
            body = "".join(re.findall(r'"([^"]*)"', src.split("db.execute(", 1)[1]))
            return " ".join(body.split())
        self.assertEqual(sql(hooks._has_live_child),
                         sql(broker_mod.Broker._has_live_child))
        self.assertIn("WHERE parent=?", sql(hooks._has_live_child))

    def test_the_raw_copy_follows_a_re_parent_on_its_own(self):
        store.create_agent(self.db, name="top", role="dispatcher", is_top=True)
        store.create_agent(self.db, name="proxy", role="researcher", parent="top")
        store.create_agent(self.db, name="kid", role="worker", parent="proxy")
        store.set_state(self.db, "proxy", "done")   # the promoter, on its way out
        self.assertTrue(hooks._has_live_child(self.db, "proxy"))
        self.assertFalse(hooks._has_live_child(self.db, "top"))
        _reparent(self.repo / "state.db", "kid", "top")
        self.assertFalse(hooks._has_live_child(self.db, "proxy"))
        self.assertTrue(hooks._has_live_child(self.db, "top"))
        # and the broker's own copy agrees, without either asking the other
        self.assertTrue(self.b._has_live_child("top"))

    def test_the_gate_still_fails_open_if_that_read_raises(self):
        store.create_agent(self.db, name="kid", role="worker", session_id="s1")
        boom = mock.patch.object(hooks, "_has_live_child",
                                 side_effect=sqlite3.OperationalError("no such column"))
        with boom:
            out = hooks.run('{"session_id": "s1"}', db_path=self.repo / "state.db")
        self.assertEqual(out, {})       # no `decision`, no block — the turn proceeds


if __name__ == "__main__":
    unittest.main()
