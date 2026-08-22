"""Phase 0 — the capability substrate, and the only thing it is allowed to change: nothing.

Two hardcoded gates became one generic `require_capability` over a per-agent set. These
tests are about PARITY, not about capabilities: each one pins a decision the old code made
and asserts the new code makes the same one, including for rows that predate the substrate
entirely (a NULL `seed_capabilities`, no rows in the table — the shape every row in a live
store has the moment this ships).

The rowless fail-open gets its own test because it is the one way this refactor becomes a
regression: `sb start` runs against a store that has not caught up yet, and a caller with
no row must be allowed rather than refused for having no role to read.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import CAP_FORK, CAP_SPAWN, HUMAN, Broker  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


class Fixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdr(self.repo / "worktrees")
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _top(self, name: str = "top") -> str:
        store.create_agent(self.db, name=name, role="lead", workspace=name,
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)
        return name


class SpawnGateParityTest(Fixture, unittest.TestCase):
    """The spawn gate decides the same way through the seeded set and through the derived
    fallback — which is the claim "no behaviour changed" reduced to one assertion."""

    def test_a_bare_role_is_still_refused_in_the_same_words(self):
        store.create_agent(self.db, name="w", role="worker", parent=self._top(),
                           workspace="api", branch="api")
        with self.assertRaises(ValueError) as cm:
            self.b.require_capability("w", CAP_SPAWN)
        self.assertIn("does not spawn agents", str(cm.exception))
        self.assertIn("lead", str(cm.exception))       # and what CAN, by name

    def test_a_delegating_role_is_still_allowed(self):
        store.create_agent(self.db, name="l", role="lead", parent=self._top(),
                           workspace="api", branch="api")
        self.b.require_capability("l", CAP_SPAWN)      # does not raise

    def test_the_seeded_set_and_the_derived_fallback_agree(self):
        """A spawned agent HAS capability rows; a row written straight to the table has
        none. Both must answer the same, or the substrate refuses somebody it used to
        allow the first time an old store meets this code."""
        seeded = self.b.delegate("t", topic="t", role="worker", me=self._top())
        store.create_agent(self.db, name="derived", role="worker", parent="top",
                           workspace="api", branch="api")
        self.assertIsNotNone(store.get_agent(self.db, seeded)["seed_capabilities"])
        self.assertIsNone(store.get_agent(self.db, "derived")["seed_capabilities"])
        for who in (seeded, "derived"):
            with self.assertRaises(ValueError, msg=who):
                self.b.require_capability(who, CAP_SPAWN)
            self.assertFalse(self.b.holds_capability(who, CAP_SPAWN))


class RowlessCallerFailsOpenTest(Fixture, unittest.TestCase):
    """Three-valued, and the third value is ALLOW. A caller we hold no row for is not
    refused, because there is no role to read and inventing one refuses `sb start` on a
    store that has not caught up yet."""

    def test_a_cold_store_still_lets_an_unknown_caller_spawn(self):
        self.assertEqual(
            [r["name"] for r in self.db.execute("SELECT name FROM agents")], [])
        self.b.require_capability("nobody", CAP_SPAWN)          # does not raise
        self.b.require_capability(HUMAN, CAP_SPAWN)             # nor the human
        self.assertTrue(self.b.holds_capability("nobody", CAP_FORK))
        self.assertTrue(self.b.holds_capability(HUMAN, CAP_FORK))

    def test_a_row_present_with_the_cap_absent_is_the_refusal_case(self):
        """The middle value, stated apart from the other two: it is row-presence that
        turns the check from allow into refuse, not the empty table."""
        store.create_agent(self.db, name="w", role="worker", parent=self._top())
        self.assertFalse(self.b.holds_capability("w", CAP_SPAWN))


class ForkRuleParityTest(Fixture, unittest.TestCase):
    """`mints_space` reads `fork`, `fork` is seeded from the `is_top` STAMP and from
    nothing else, so the fork decision is the stamp's exactly as it was."""

    def test_the_fork_answer_is_still_the_stamp_for_every_row(self):
        top = self._top()
        lead = self.b.delegate("t", topic="t", role="lead", me=top)
        kid = self.b.delegate("t", topic="t", role="worker", me=lead)
        store.create_agent(self.db, name="scout", role="lead", parent=lead,
                           workspace="api")          # bare non-top, no seed at all
        for name in (top, lead, kid, "scout"):
            row = store.get_agent(self.db, name)
            self.assertEqual(self.b.mints_space(name), bool(row["is_top"]), name)

    def test_a_worktree_less_non_top_still_does_not_fork(self):
        """The phase-5 bug, asked of the capability set instead of the branch column."""
        store.create_agent(self.db, name="scout", role="lead", parent=self._top(),
                           workspace="api")
        self.assertFalse(self.b.has_worktree("scout"))
        self.assertFalse(self.b.mints_space("scout"))
        self.assertTrue(self.b.mints_space("top"))


class NoStartCapabilityTest(Fixture, unittest.TestCase):
    """`sb start` is not a capability and never becomes one: nothing seeds the string, so
    there is nothing for a later grant path to hand out."""

    def test_no_role_seeds_a_start_capability(self):
        for role in self.b.roles:
            for is_top in (False, True):
                self.assertNotIn("start", self.b.seed_for(role, is_top))

    def test_the_string_appears_in_no_seeded_row(self):
        self.b.delegate("t", topic="t", role="lead", me=self._top())
        held = {r["cap"] for r in self.db.execute("SELECT cap FROM capabilities")}
        self.assertTrue(held <= {CAP_SPAWN, CAP_FORK}, held)


if __name__ == "__main__":
    unittest.main()
