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

from switchboard import roles as roles_mod  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import (  # noqa: E402
    CAP_FORK, CAP_SPAWN, CAP_WRITE_TRACKED, HUMAN, Broker,
)

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
    """The fork decision is the stamp's, exactly as it was.

    It was written when `mints_space` read `fork` and the two were the same fact (`fork`
    was seeded from the `is_top` stamp and from nothing else). D2 gave `fork` a second,
    weaker meaning — may this caller ASK for an isolated child — so `mints_space` asks the
    stamp directly again and these assertions, which were always about the stamp, are
    unchanged."""

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
        """C1 widened the vocabulary a seed may contain (`dispatch`, `write-tracked`), so
        the assertion is the one this test was always about — `start` is in no row — and
        not the incidental "only these two strings exist" it could be written as while
        only two did."""
        self.b.delegate("t", topic="t", role="lead", me=self._top())
        held = {r["cap"] for r in self.db.execute("SELECT cap FROM capabilities")}
        self.assertTrue(held)                          # something was seeded to look at
        self.assertNotIn("start", held)


class RoleBundleTest(Fixture, unittest.TestCase):
    """Phase 1 — the role side becomes DATA. A role carries a default capability bundle
    instead of a `delegate` bool, and what an agent is seeded with is that bundle."""

    def test_each_shipped_role_seeds_its_own_bundle(self):
        """§6.2's table, one assertion per role. `fork` reaches the `lead` seed because its
        template names it (D2): the fork DECISION is still the stamp's (`mints_space`), so
        a seeded lead's ordinary spawns are unaffected — what the cap buys it is the right
        to ASK, with `delegate(isolation="own")`. Every other bundle is untouched, because
        none of them named `fork` in the first place."""
        expected = {
            "dispatcher": ["dispatch", "spawn", "write-tracked"],
            "lead":       ["dispatch", "fork", "spawn", "write-tracked"],
            "worker":     ["write-tracked"],
            "researcher": [],
            "reviewer":   ["write-tracked"],   # scoped minor fixes, 2026-08-27
            "qa":         [],                                       # read-only by default
        }
        for role, caps in expected.items():
            with self.subTest(role=role):
                self.assertEqual(self.b.seed_for(role, is_top=False), caps)

    def test_the_top_takes_its_fixed_set_and_never_write_tracked(self):
        """§2.0: the top is a placement, a stamp and a FIXED bundle — not a template. It
        holds `fork` because forking is what a top is for, and never `write-tracked`,
        which is the whole invariant over a person's own checkout."""
        for role in ("dispatcher", "lead", "worker"):
            with self.subTest(role=role):
                self.assertEqual(self.b.seed_for(role, is_top=True),
                                 ["dispatch", "fork", "spawn"])
                self.assertNotIn(CAP_WRITE_TRACKED, self.b.seed_for(role, is_top=True))

    def test_no_bundle_carries_a_topology_capability(self):
        """Promote is self-service (§2.3), so `reparent` is not a capability and the string
        does not exist — stated as a test so it is not re-derived as a new primitive."""
        for role in list(self.b.roles) + ["invented-yesterday"]:
            for is_top in (False, True):
                self.assertNotIn("reparent", self.b.seed_for(role, is_top))

    def test_an_old_roles_toml_still_reads(self):
        """BACK-COMPAT. A file in the wild still says `delegate = true/false`; it must load
        without error and map onto the bundle it always meant, or retiring the field breaks
        somebody's config on upgrade."""
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "roles.toml").write_text(
            "[foreman]\ndelegate = true\n[dogsbody]\ndelegate = false\n")
        b = Broker(self.db, self.h, repo=self.repo)     # reads the file just written
        self.assertIn(CAP_SPAWN, b.seed_for("foreman", is_top=False))
        self.assertNotIn(CAP_SPAWN, b.seed_for("dogsbody", is_top=False))
        self.assertIn("foreman", b._delegating_roles())
        # And the gate itself still decides the way the bool did.
        store.create_agent(self.db, name="f", role="foreman", parent=self._top(),
                           workspace="api", branch="api")
        store.create_agent(self.db, name="d", role="dogsbody", parent="f",
                           workspace="api", branch="api")
        b.require_capability("f", CAP_SPAWN)                    # does not raise
        with self.assertRaises(ValueError):
            b.require_capability("d", CAP_SPAWN)

    def test_an_old_bool_still_overrides_a_shipped_bundle_both_ways(self):
        """The half of back-compat that is easy to lose. `delegate` is layered config: a
        repo writing it over a SHIPPED role whose file now names `capabilities` must still
        decide, and in both directions — the bool replaced what was underneath, it never
        added to it, so a `false` must narrow rather than union."""
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "roles.toml").write_text(
            "[qa]\ndelegate = true\n[lead]\ndelegate = false\n")
        b = Broker(self.db, self.h, repo=self.repo)
        self.assertIn(CAP_SPAWN, b.seed_for("qa", is_top=False))          # widened
        self.assertNotIn(CAP_SPAWN, b.seed_for("lead", is_top=False))     # and narrowed
        self.assertEqual(b._delegating_roles(), ["dispatcher", "qa"])

    def test_delegating_roles_is_capability_membership_and_names_the_same_roles(self):
        """`_delegating_roles()` filtered `.delegate`; it filters `spawn` in the bundle.
        Same answer — the shipped roles that spawn are the two halves of the split — and
        the refusal message that quotes it is unchanged in structure."""
        self.assertEqual(self.b._delegating_roles(), ["dispatcher", "lead"])
        self.assertEqual(
            self.b._delegating_roles(),
            sorted(n for n, r in self.b.roles.items()
                   if CAP_SPAWN in r.capabilities))

    def test_the_role_model_no_longer_carries_the_bool(self):
        """Fully removed, not deprecated in place: a field the model still accepted is a
        field somebody could still read."""
        self.assertFalse(hasattr(roles_mod.Role("worker"), "delegate"))


if __name__ == "__main__":
    unittest.main()
