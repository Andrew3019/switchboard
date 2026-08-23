"""Phase 1 — `sb grant`, ∩-seeding, and the invariants that make them safe (#163-A, C2).

Everything here is a security property, so each test pins ONE of them and says which. The
four that matter most, because getting any of them wrong is silent and permanent:

* **A spawn narrows, never widens.** A child seeds `role-template ∩ passable(spawner)`, and
  the result is written down — `restore` reads it back, so a mis-set seed would widen or
  cripple every descendant of a restored agent too.
* **Held and passable are different sets.** `--delegable` counts at the spawn and NEVER at
  the gate; that split is the whole of #163's motivating case.
* **Nobody widens their own held set.** No self-grant, by any path.
* **The grant path fails CLOSED**, which is the opposite of the gate's rowless fail-open.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store  # noqa: E402
from switchboard.broker import (  # noqa: E402
    CAP_DISPATCH, CAP_FORK, CAP_SPAWN, CAP_WRITE_TRACKED, HUMAN, Broker,
)
from switchboard.cli import build_parser  # noqa: E402

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

    def top(self, name: str = "top") -> str:
        store.create_agent(self.db, name=name, role="dispatcher", workspace=name,
                           cwd=str(self.repo), pane_id="w1:p1", is_top=True)
        store.seed_capabilities(self.db, name, self.b.seed_for("dispatcher", is_top=True))
        return name

    def spawn(self, parent: str, role: str, topic: str) -> str:
        return self.b.delegate("t", topic=topic, role=role, me=parent)

    def held(self, name: str) -> set:
        return store.held_capabilities(self.db, name)

    def passable(self, name: str) -> set:
        return store.passable_capabilities(self.db, name)


class IntersectionSeedingTest(Fixture, unittest.TestCase):
    """§2.1: a child seeds `role-template ∩ passable(spawner)`. A spawn NARROWS."""

    def test_the_escalation_this_closes(self):
        """The exact hole from the spec: a worker granted `spawn` spawns `--role lead`, and
        the child must NOT come out with the caps the worker never held. Without the rule,
        `spawn` is a second, unguarded cap-minting path — the worker drives that child by
        `sb tell` and has escalated transitively."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        worker = self.spawn(lead, "worker", "w")
        self.b.grant(worker, CAP_SPAWN, me=lead)
        self.assertEqual(self.held(worker), {CAP_WRITE_TRACKED, CAP_SPAWN})
        child = self.spawn(worker, "lead", "sub")
        self.assertEqual(self.held(child), {CAP_SPAWN, CAP_WRITE_TRACKED})
        self.assertNotIn(CAP_DISPATCH, self.held(child))       # a crippled "lead"
        self.assertNotIn(CAP_FORK, self.held(child))

    def test_the_computed_seed_is_persisted_on_the_row(self):
        """Persisted because `restore` reseeds from it — a set recomputed later from the
        role would not be the set this agent was actually given."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        worker = self.spawn(lead, "worker", "w")
        self.b.grant(worker, CAP_SPAWN, me=lead)
        child = self.spawn(worker, "lead", "sub")
        self.assertEqual(store.get_agent(self.db, child)["seed_capabilities"],
                         "spawn write-tracked")
        self.assertEqual(set(store.get_agent(self.db, child)["seed_capabilities"].split()),
                         self.held(child))

    def test_seeded_rows_are_held_not_delegable(self):
        """A worker seeded `write-tracked` that could not write would defeat the point."""
        top = self.top()
        w = self.spawn(self.spawn(top, "lead", "l"), "worker", "w")
        rows = store.capability_rows(self.db, w)
        self.assertEqual([r["cap"] for r in rows], [CAP_WRITE_TRACKED])
        self.assertTrue(rows[0]["held"])
        self.assertFalse(rows[0]["delegable"])
        self.assertIsNone(rows[0]["granted_by"])       # a seed is nobody's decision
        self.b.require_capability(w, CAP_WRITE_TRACKED)               # and it can write

    def test_only_the_top_seeds_from_the_full_template(self):
        """THE ONE EXEMPTION. The top holds no `write-tracked` and must still commission a
        lead that does. A NON-top dispatcher holding the same set cannot: its children are
        ∩-narrowed like everyone else's."""
        top = self.top()
        self.assertNotIn(CAP_WRITE_TRACKED, self.held(top))
        lead = self.spawn(top, "lead", "l")
        self.assertEqual(self.held(lead), {CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED})

        # The same shape one level down, and the exemption is out of reach.
        inner = self.spawn(top, "dispatcher", "d")     # non-top dispatcher
        self.db.execute("DELETE FROM capabilities WHERE agent=? AND cap=?",
                        (inner, CAP_WRITE_TRACKED))
        self.db.execute("UPDATE agents SET seed_capabilities='dispatch spawn' WHERE name=?",
                        (inner,))
        self.db.commit()
        self.assertNotIn(CAP_WRITE_TRACKED, self.passable(inner))
        kid = self.spawn(inner, "lead", "k")
        self.assertNotIn(CAP_WRITE_TRACKED, self.held(kid))

    def test_a_rowless_spawner_bounds_nothing(self):
        """The gate's fail-open, in the shape ∩-seeding needs: intersecting with an empty
        set would cripple every agent spawned against a cold store."""
        self.assertEqual(set(self.b.seed_for("lead", False, spawner=HUMAN)),
                         {CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED})
        self.assertEqual(set(self.b.seed_for("lead", False, spawner="nobody")),
                         {CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED})


class GrantCommandTest(Fixture, unittest.TestCase):
    """The verb itself: its shape, what it records, and what it refuses."""

    def test_the_command_has_exactly_those_names(self):
        a = build_parser().parse_args(
            ["grant", "w1", "write-tracked", "--delegable", "--reason", "so it can fix"])
        self.assertEqual((a.agent, a.cap, a.delegable, a.reason),
                         ("w1", "write-tracked", True, "so it can fix"))
        self.assertFalse(build_parser().parse_args(["grant", "w1", "spawn"]).delegable)

    def test_there_is_no_revoke_and_no_ttl(self):
        """One-shot and lifetime-scoped: the agent's lifecycle ends the grant, and neither
        a verb nor a flag exists to end it sooner."""
        verbs = set(build_parser()._subparsers._group_actions[0].choices)
        self.assertIn("grant", verbs)
        self.assertNotIn("revoke", verbs)
        self.assertNotIn("--ttl", build_parser().parse_args(
            ["grant", "w", "spawn"]).__dict__)
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["grant", "w", "spawn", "--ttl", "1h"])

    def test_provenance_is_recorded_with_the_granters_identity(self):
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.b.grant(w, CAP_SPAWN, reason="fan out to 5 reviewers", me=lead)
        row = [r for r in store.capability_rows(self.db, w) if r["cap"] == CAP_SPAWN][0]
        self.assertEqual(row["granted_by"], lead)
        self.assertEqual(row["reason"], "fan out to 5 reviewers")
        self.assertIsNotNone(row["granted_at"])
        kinds = [e["kind"] for e in store.recent_events(self.db, agent=w)]
        self.assertIn("grant", kinds)

    def test_the_granter_must_already_hold_it(self):
        """No escalation past your own ceiling."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w1 = self.spawn(lead, "worker", "w1")
        self.b.grant(w1, CAP_SPAWN, me=lead)            # so it can have a subtree at all
        w2 = self.spawn(w1, "worker", "w2")
        self.assertNotIn(CAP_DISPATCH, self.passable(w1))
        with self.assertRaises(ValueError) as cm:
            self.b.grant(w2, CAP_DISPATCH, me=w1)
        self.assertIn("do not hold", str(cm.exception))
        self.assertNotIn(CAP_DISPATCH, self.passable(w2))

    def test_reach_is_subtree_scoped(self):
        """A grant hands a right to somebody another lead is answerable for, so it stays
        inside the region one agent can already see. Sibling subtrees, and upward, are
        both refused."""
        top = self.top()
        a = self.spawn(top, "lead", "a")
        b = self.spawn(top, "lead", "b")
        b_kid = self.spawn(b, "worker", "bk")
        with self.assertRaises(ValueError) as cm:
            self.b.grant(b_kid, CAP_SPAWN, me=a)        # into a sibling's subtree
        self.assertIn("not in your subtree", str(cm.exception))
        with self.assertRaises(ValueError):
            self.b.grant(b, CAP_SPAWN, me=b_kid)        # and never upward

    def test_a_foreign_tree_is_refused_as_a_boundary(self):
        other = self.top("other")
        mine = self.top("mine")
        kid = self.spawn(other, "worker", "k")
        with self.assertRaises(ValueError) as cm:
            self.b.grant(kid, CAP_WRITE_TRACKED, delegable=True, me=mine)
        self.assertIn("another dispatcher's tree", str(cm.exception))

    def test_the_grant_path_fails_closed_for_a_rowless_caller(self):
        """A DIFFERENT predicate from the gate. `require_capability` allows a rowless
        caller so `sb start` survives a cold store; a grant is durable, silent and
        irrevocable, and an agent in a fresh clone resolves to HUMAN — "rowless ⇒ allow"
        would mean any clone bootstrap silently grants anything."""
        top = self.top()
        w = self.spawn(self.spawn(top, "lead", "l"), "worker", "w")
        self.b.require_capability(HUMAN, CAP_SPAWN)            # the gate: allowed
        with self.assertRaises(ValueError) as cm:
            self.b.grant(w, CAP_SPAWN, me=HUMAN)               # the grant: refused
        self.assertIn("no row for you", str(cm.exception))
        with self.assertRaises(ValueError):
            self.b.grant(w, CAP_SPAWN, me="ghost-not-in-store")
        self.assertNotIn(CAP_SPAWN, self.held(w))

    def test_an_unknown_capability_is_refused_rather_than_written(self):
        """Fail-closed on an ill-formed grant: a typo that wrote a row would be a right
        nothing reads, nobody notices and no revoke can remove."""
        top = self.top()
        w = self.spawn(self.spawn(top, "lead", "l"), "worker", "w")
        for bad in ("wrte-tracked", "start", "sudo"):
            with self.subTest(cap=bad), self.assertRaises(ValueError):
                self.b.grant(w, bad, delegable=True, me=top)
        self.assertEqual(self.passable(w), {CAP_WRITE_TRACKED})

    def test_the_top_is_never_a_target(self):
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        with self.assertRaises(ValueError) as cm:
            self.b.grant(top, CAP_WRITE_TRACKED, me=lead)
        self.assertIn("fixed", str(cm.exception))
        self.assertNotIn(CAP_WRITE_TRACKED, self.passable(top))


class NoSelfWideningTest(Fixture, unittest.TestCase):
    """§2.1: held caps come from exactly two places — the ∩-seed, and a grant from SOMEBODY
    ELSE. Every other path is refused, and each path gets its own assertion."""

    def test_a_grant_never_targets_the_granter(self):
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        for cap in (CAP_SPAWN, CAP_WRITE_TRACKED, CAP_FORK):
            with self.subTest(cap=cap), self.assertRaises(ValueError) as cm:
                self.b.grant(lead, cap, me=lead)
            self.assertIn("never targets the granter", str(cm.exception))

    def test_a_delegable_only_holder_cannot_upgrade_itself_to_held(self):
        """The path the no-self-grant rule exists for: otherwise the split lasts as long as
        it takes to type one line."""
        top = self.top()
        r = self.spawn(top, "researcher", "r")
        self.b.grant(r, CAP_WRITE_TRACKED, delegable=True, me=top)
        with self.assertRaises(ValueError):
            self.b.grant(r, CAP_WRITE_TRACKED, me=r)
        self.assertNotIn(CAP_WRITE_TRACKED, self.held(r))
        with self.assertRaises(ValueError):
            self.b.require_capability(r, CAP_WRITE_TRACKED)

    def test_a_spawn_cannot_be_used_to_widen_the_spawner(self):
        """The other self-widening path: mint a capable child and drive it. The child is
        ∩-narrowed, and the spawner's own set is untouched by spawning at all."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.b.grant(w, CAP_SPAWN, me=lead)
        before = self.held(w)
        self.spawn(w, "lead", "k")
        self.assertEqual(self.held(w), before)


class DelegableTest(Fixture, unittest.TestCase):
    """`--delegable`: holding a cap and passing it on are separate. Exactly two read sites."""

    def test_the_motivating_case_from_163(self):
        """A researcher (`{}`) granted `--delegable write-tracked` spawns a worker that CAN
        write, while the researcher itself still cannot."""
        top = self.top()
        r = self.spawn(top, "researcher", "r")
        self.b.grant(r, CAP_SPAWN, me=top)
        self.b.grant(r, CAP_WRITE_TRACKED, delegable=True, me=top)
        w = self.spawn(r, "worker", "w")
        self.assertEqual(self.held(w), {CAP_WRITE_TRACKED})
        self.b.require_capability(w, CAP_WRITE_TRACKED)               # the child may write
        with self.assertRaises(ValueError):
            self.b.require_capability(r, CAP_WRITE_TRACKED)           # the hub may not
        self.assertFalse(self.b.holds_capability(r, CAP_WRITE_TRACKED))

    def test_held_and_passable_are_independent_bits(self):
        """A cap may be BOTH — granted twice, or `--delegable` over one already held — and
        neither grant may take the other bit away."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.assertEqual(self.held(w), {CAP_WRITE_TRACKED})
        self.b.grant(w, CAP_WRITE_TRACKED, delegable=True, me=lead)   # over a held cap
        self.assertIn(CAP_WRITE_TRACKED, self.held(w))                # still held
        self.assertIn(CAP_WRITE_TRACKED, self.passable(w))            # and now passable

        r = self.spawn(lead, "researcher", "r")
        self.b.grant(r, CAP_WRITE_TRACKED, delegable=True, me=lead)
        self.assertNotIn(CAP_WRITE_TRACKED, self.held(r))
        self.b.grant(r, CAP_WRITE_TRACKED, me=lead)                   # then the held form
        self.assertIn(CAP_WRITE_TRACKED, self.held(r))
        self.assertIn(CAP_WRITE_TRACKED, self.passable(r))

    def test_a_delegable_cap_arrives_HELD_and_the_bit_does_not_travel(self):
        """"One hop down" is a fact about the BIT, not about reach: the child is seeded
        with the capability HELD, and nothing it was seeded with is delegable-only. Passing
        the pass-through *decision* on is a fresh `--delegable` grant from somebody who now
        holds it."""
        top = self.top()
        r = self.spawn(top, "researcher", "r")
        self.b.grant(r, CAP_SPAWN, me=top)
        self.b.grant(r, CAP_WRITE_TRACKED, delegable=True, me=top)
        lead = self.spawn(r, "lead", "l")
        self.assertEqual(self.held(lead), {CAP_SPAWN, CAP_WRITE_TRACKED})
        self.assertFalse([row for row in store.capability_rows(self.db, lead)
                          if row["delegable"]])
        # `dispatch` is in the lead template and in nothing r may pass, so it is not there.
        self.assertNotIn(CAP_DISPATCH, self.held(lead))


class TopExemptionTest(Fixture, unittest.TestCase):
    """The top may grant what it does not hold — bounded by `--delegable`."""

    def test_the_top_may_grant_a_cap_it_does_not_hold_as_delegable(self):
        top = self.top()
        r = self.spawn(top, "researcher", "r")
        self.assertNotIn(CAP_WRITE_TRACKED, self.passable(top))
        self.b.grant(r, CAP_WRITE_TRACKED, delegable=True, me=top)
        self.assertIn(CAP_WRITE_TRACKED, self.passable(r))
        # And it never widens the target's own actions, nor the top's.
        self.assertNotIn(CAP_WRITE_TRACKED, self.held(r))
        self.assertNotIn(CAP_WRITE_TRACKED, self.held(top))
        with self.assertRaises(ValueError):
            self.b.require_capability(r, CAP_WRITE_TRACKED)

    def test_a_held_grant_of_a_cap_the_granter_lacks_is_refused(self):
        """The bound on the exemption. Spec/plan word this as "beyond the TARGET's own
        template must be --delegable"; taken literally that also refuses §2.1's own
        headline case (a lead hands a worker `spawn`) and objective 27's held `spawn` to a
        researcher, so the rule is enforced where it bites: a cap the GRANTER does not hold
        can only ever be passed through."""
        top = self.top()
        r = self.spawn(top, "researcher", "r")
        with self.assertRaises(ValueError) as cm:
            self.b.grant(r, CAP_WRITE_TRACKED, me=top)     # held, and the top holds none
        self.assertIn("--delegable", str(cm.exception))
        self.assertEqual(self.passable(r), set())

    def test_a_non_top_granter_is_unchanged_by_the_exemption(self):
        """Hold-or-delegable, subtree reach — no widening for anyone below the top."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.assertNotIn(CAP_FORK, self.passable(lead))
        for delegable in (False, True):
            with self.subTest(delegable=delegable), self.assertRaises(ValueError):
                self.b.grant(w, CAP_FORK, delegable=delegable, me=lead)
        self.assertNotIn(CAP_FORK, self.passable(w))

    def test_the_promote_seeding_chain_composes(self):
        """§2.3 end to end: a top equips a read-only researcher to seed a full lead, while
        the researcher's own held set stays `{spawn}`."""
        top = self.top()
        r = self.spawn(top, "researcher", "r")
        self.b.grant(r, CAP_SPAWN, me=top)                       # held: the top holds spawn
        for cap in (CAP_DISPATCH, CAP_WRITE_TRACKED, CAP_FORK):
            self.b.grant(r, cap, delegable=True, me=top)
        self.assertEqual(self.passable(r),
                         {CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED, CAP_FORK})
        self.assertEqual(self.held(r), {CAP_SPAWN})
        lead = self.spawn(r, "lead", "l")
        # The full lead template, less `fork` — which C1 withholds from every seed below a
        # top because `mints_space` still reads the stamp (it returns with the isolation
        # work, D2). The ∩ itself passes `fork` through: it is in `passable(r)`.
        self.assertEqual(self.held(lead), {CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED})


class RestoreTest(Fixture, unittest.TestCase):
    """`restore` drops grants and reseeds from the STORED SEED — never the role template."""

    def _closed(self, name: str) -> None:
        """Close the row the way `cleanup` leaves it, with a session to resume from."""
        self.h.live.pop(name, None)                 # herdr has let the name go, as on close
        store.update_agent(self.db, name, session_id="s-" + name, pane_id="")
        self.db.execute("UPDATE agents SET ended_at=1 WHERE name=?", (name,))
        self.db.commit()

    def test_grants_are_dropped_and_the_seed_comes_back(self):
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.b.grant(w, CAP_SPAWN, reason="fan out", me=lead)
        self.assertEqual(self.held(w), {CAP_WRITE_TRACKED, CAP_SPAWN})
        self._closed(w)
        self.b.restore(w)
        self.assertEqual(self.held(w), {CAP_WRITE_TRACKED})
        self.assertEqual(self.passable(w), {CAP_WRITE_TRACKED})

    def test_reseeding_is_from_the_seed_not_the_template(self):
        """The subtler bug: a ∩-narrowed lead must not come back as a full one. That would
        be a silent widening past the ceiling ∩-seeding exists to enforce, with no grant
        recorded and no granter in the log."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.b.grant(w, CAP_SPAWN, me=lead)
        narrow = self.spawn(w, "lead", "sub")               # {spawn, write-tracked}
        self.assertEqual(self.held(narrow), {CAP_SPAWN, CAP_WRITE_TRACKED})
        self._closed(narrow)
        self.b.restore(narrow)
        self.assertEqual(self.held(narrow), {CAP_SPAWN, CAP_WRITE_TRACKED})
        self.assertNotIn(CAP_DISPATCH, self.held(narrow))   # the template's, not its own

    def test_the_narrowing_is_surfaced_to_both_parties(self):
        """Not silent: the operator is told, and so is the agent, so the one cheap line
        that puts it right (`sb grant`) can be typed by whoever notices first."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        w = self.spawn(lead, "worker", "w")
        self.b.grant(w, CAP_SPAWN, me=lead)
        self._closed(w)
        self.b.restore(w)
        self.assertIn("not carried over", self.b.restore_note or "")
        self.assertIn("seed caps", self.b.restore_note)
        mail = " ".join(m["body"] for m in store.unread_for(self.db, w))
        self.assertIn("grant", mail)
        self.assertIn("restored", mail)

    def test_a_restore_with_nothing_granted_says_nothing(self):
        top = self.top()
        w = self.spawn(self.spawn(top, "lead", "l"), "worker", "w")
        self._closed(w)
        self.b.restore(w)
        self.assertIsNone(self.b.restore_note)
        self.assertEqual(self.held(w), {CAP_WRITE_TRACKED})
        self.assertEqual(store.unread_for(self.db, w), [])


if __name__ == "__main__":
    unittest.main()
