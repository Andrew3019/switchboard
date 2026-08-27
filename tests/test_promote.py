"""Unit F2 — PROMOTE: `sb done --preserve-children` (spec §2.3, §2.0, §2.1, §6.7, §10.2).

The last unit of the build, and the first `UPDATE agents SET parent` this codebase has ever
had. F1 shipped the resolver and simulated the write with a raw `UPDATE`; this is the
write, issued for real, on the transaction the `done` already needed.

What each group pins:

* **the command** — live children rise one level onto the promoter's own parent, the
  promoter drops out of the chain, and the done-chain from the workers up is clean;
* **no capability** — promote is self-service, there is no `reparent` string anywhere, and
  an agent holding nothing at all may do it;
* **two structural refusals** — the top may not promote (a predicate, not a gate), and a
  parentless NON-top may, because that is the human-spawned case;
* **atomicity** — one transaction, one statement, no row minted, and a failure anywhere in
  it leaves the tree exactly where it was;
* **two parties, not three** — every re-homed child and the grandparent, `1 + N` messages,
  and nothing digestible;
* **the gate and the race** — promote EMPTIES the live-descendants gate rather than
  fighting it, and the `cleanup --force` interleaving is benign;
* **pointer only** — nothing about a checkout, a pane or a capability set moves.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import broker as broker_mod  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import HUMAN, SIGNAL  # noqa: E402
from switchboard.cli import build_parser  # noqa: E402

from test_grants import Fixture  # noqa: E402


class PromoteFixture(Fixture):
    def canonical(self) -> None:
        """The spec's own case: a top spawns a researcher, which spawns a lead below it.

        End state after the promote is `dispatcher -> lead -> workers`, with no proxy row
        left in the reporting chain.
        """
        store.create_agent(self.db, name="top", role="dispatcher", is_top=True,
                           pane_id="w1:p0", cwd=str(self.repo), workspace="top")
        store.create_agent(self.db, name="res", role="researcher", parent="top",
                           pane_id="w1:p1", cwd=str(self.repo), workspace="top")
        store.create_agent(self.db, name="lead", role="lead", parent="res",
                           pane_id="w1:p2", cwd=str(self.repo / "wt"), workspace="lead",
                           branch="lead")
        store.create_agent(self.db, name="worker", role="worker", parent="lead",
                           pane_id="w1:p3")

    def mail(self, who: str) -> list:
        return list(self.db.execute(
            "SELECT * FROM messages WHERE to_agent=? ORDER BY id", (who,)).fetchall())


class TheCommandTest(PromoteFixture, unittest.TestCase):
    """Obj. 1–6: what promote actually does."""

    def test_live_children_rise_one_level_onto_the_promoters_own_parent(self):
        """Obj. 1. The whole primitive, and the resolver is what answers afterwards —
        the column moved, so `current_parent` moves with it."""
        self.canonical()
        self.assertEqual(self.b.done("handed over", me="res", preserve_children=True), [])
        self.assertEqual(self.b.current_parent("lead"), "top")
        self.assertEqual(self.b.current_parent("res"), "top")     # the promoter's own
        self.assertEqual(self.b.current_parent("worker"), "lead")  # untouched, deeper down
        self.assertEqual(self.b.promoted, ["lead"])

    def test_the_done_chain_is_clean_afterwards(self):
        """Obj. 3, 6. The point of the primitive: the promoted lead reports to the
        ORIGINAL parent, not to a proxy row that has finished. `done` resolves the parent
        at the point of use (F1), so this follows the move with nothing else changed."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.b.done("shipped it", me="lead")
        got = [m["body"] for m in self.mail("top") if m["kind"] == "done"]
        self.assertIn("[done] shipped it", got)
        self.assertEqual([m for m in self.mail("res") if m["kind"] == "done"], [])

    def test_it_is_inherently_the_batch_every_live_child_in_one_call(self):
        """Obj. 5. Multi-target is retired WITH the primitive because there is nothing to
        target: one call moves every live child, so the reorg signal storm the multi-target
        form existed to cut never forms."""
        self.canonical()
        for n in ("l2", "l3"):
            store.create_agent(self.db, name=n, role="lead", parent="res", pane_id=f"p-{n}")
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.b.promoted, ["lead", "l2", "l3"])
        for n in ("lead", "l2", "l3"):
            self.assertEqual(self.b.current_parent(n), "top")

    def test_finished_children_stay_where_they_are(self):
        """The predicate is LIVE children. A finished row reports to nobody, nothing waits
        on its summary, and moving it would rewrite the record the event log is of."""
        self.canonical()
        store.set_state(self.db, "lead", "done")
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.b.promoted, [])
        self.assertEqual(self.b.current_parent("lead"), "res")

    def test_a_promoter_with_nothing_underneath_it_still_reports_done(self):
        """A no-op, not an error: "hand up whatever is still running" is a true statement
        about nothing, and refusing it makes the flag something a caller must check first."""
        self.canonical()
        self.b.done("nothing to hand over", me="worker", preserve_children=True)
        self.assertEqual(self.b.promoted, [])
        self.assertEqual(store.get_agent(self.db, "worker")["state"], "done")

    def test_the_flag_lives_on_done_and_there_is_no_handoff_verb(self):
        """Obj. 2, 4. One flag on the verb that already exists — the spawn half IS
        `sb delegate`, unchanged. And the retired names are gone: no `sb handoff`, no
        `insert-above`, no `assume-role`."""
        p = build_parser()
        self.assertTrue(p.parse_args(["done", "s", "--preserve-children"]).preserve_children)
        self.assertFalse(p.parse_args(["done", "s"]).preserve_children)
        with self.assertRaises(SystemExit):
            p.parse_args(["handoff", "lead"])

    def test_the_retired_primitives_have_no_surviving_reference(self):
        """Obj. 4. `assume-role` and `insert-above` are retired with the design that
        replaced them; the shipped code and defaults say "promote" throughout."""
        root = Path(__file__).resolve().parent.parent
        files = [*(root / "switchboard").rglob("*.py"), *(root / "defaults").rglob("*.*")]
        for f in files:
            text = f.read_text(errors="ignore").lower()
            for dead in ("assume-role", "assume_role", "insert-above", "insert_above"):
                self.assertNotIn(dead, text, f"{dead} survives in {f}")


class NoCapabilityTest(PromoteFixture, unittest.TestCase):
    """Obj. 7–11: self-service. It seizes nothing, so it is gated by nothing."""

    def test_an_agent_holding_nothing_at_all_may_promote(self):
        """Obj. 7. There is no gate to pass and no capability to hold. A researcher's
        template is `{}` — the emptiest set anything in this fleet has — and it promotes."""
        self.canonical()
        store.seed_capabilities(self.db, "res", set())
        self.assertEqual(store.held_capabilities(self.db, "res"), set())
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.b.current_parent("lead"), "top")

    def test_reparent_is_not_a_capability_string_anywhere(self):
        """Obj. 7, 10. Verified ABSENT rather than merely unused: no bundle carries it, no
        `require_capability` asks for it, and it is in no role template."""
        src = (Path(__file__).resolve().parent.parent / "switchboard").rglob("*.py")
        for f in src:
            self.assertNotIn("reparent", f.read_text(errors="ignore"))
        for role in list(self.b.roles) + ["invented"]:
            for is_top in (False, True):
                self.assertNotIn("reparent", self.b.seed_for(role, is_top))

    def test_the_children_were_already_the_grandparents_descendants(self):
        """Obj. 8, 11. The justification, as a property: `_descendants` is a transitive
        parent walk, so the grandparent's cleanup scope and ancestry ALREADY reached these
        rows. Only the direct pointer moves; the set does not change at all."""
        self.canonical()
        before = sorted(a["name"] for a in self.b._descendants("top"))
        self.b.done("handed over", me="res", preserve_children=True)
        after = sorted(a["name"] for a in self.b._descendants("top"))
        self.assertEqual(before, after)
        self.assertEqual(before, ["lead", "res", "worker"])

    def test_promote_can_only_shrink_who_may_close_a_row(self):
        """Obj. 9, 11. Nobody loses a right against their will and nobody gains one: the
        promoter's cleanup scope SHRINKS (it gave it up by finishing), the grandparent's is
        unchanged, and no third authority is keyed off `parent`."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual([a["name"] for a in self.b._descendants("res")], [])


class RefusalsTest(PromoteFixture, unittest.TestCase):
    """Obj. 12–14: two structural refusals, one of which is not a refusal."""

    def test_the_top_may_not_promote(self):
        """Obj. 12, 14. A predicate in the generic layer, not a capability check: the top
        has `parent IS NULL` by construction, and promoting it would give its children none
        — a second rootless island, with no `sb start` to anchor it."""
        self.canonical()
        with self.assertRaises(ValueError) as e:
            self.b.done("all finished", me="top", preserve_children=True)
        self.assertIn("cannot promote", str(e.exception))
        self.assertEqual(self.b.current_parent("res"), "top")
        self.assertEqual(store.get_agent(self.db, "top")["state"], "working")
        self.assertEqual(len(store.live_tops(self.db)), 1)

    def test_the_refusal_reads_the_stamp_not_a_null_parent(self):
        """Obj. 12 vs 13. Inferring the top from `parent IS NULL` would refuse exactly the
        legal case below — the human-spawned agent — so the predicate is the `is_top` stamp
        and nothing derived."""
        store.create_agent(self.db, name="solo", role="researcher", pane_id="p1")
        self.assertIsNone(self.b.current_parent("solo"))
        self.assertFalse(self.b.is_top("solo"))
        self.b._refuse_top_promote("solo")               # does not raise

    def test_a_parentless_non_top_promoter_is_legal_and_its_children_surface(self):
        """Obj. 13. Not a special case — the code already has the branch. A human-spawned
        agent has `parent IS NULL`, so its children simply inherit that, and their `done`
        takes the root branch and surfaces to the human rather than mailing a row that is
        no longer there."""
        store.create_agent(self.db, name="solo", role="researcher", pane_id="p1")
        store.create_agent(self.db, name="kid", role="lead", parent="solo", pane_id="p2")
        self.b.done("handed over", me="solo", preserve_children=True)
        self.assertEqual(self.b.promoted, ["kid"])
        self.assertIsNone(self.b.current_parent("kid"))
        self.h.notifications.clear()
        self.b.done("finished", me="kid")
        self.assertTrue(any("kid: done — finished" in n for n in self.h.notifications))
        self.assertEqual(self.mail(HUMAN), [])            # a person has no mailbox

    def test_no_promote_creates_a_second_top(self):
        """Obj. 14. The invariant the refusal exists for, asserted on the store's own
        question rather than on the refusal's error text."""
        store.create_agent(self.db, name="solo", role="researcher", pane_id="p1")
        store.create_agent(self.db, name="kid", role="lead", parent="solo", pane_id="p2")
        self.b.done("handed over", me="solo", preserve_children=True)
        self.assertEqual([r["name"] for r in store.live_tops(self.db)], [])
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual([r["name"] for r in store.live_tops(self.db)], ["top"])
        self.assertFalse(self.b.is_top("lead"))


class AtomicityTest(PromoteFixture, unittest.TestCase):
    """Obj. 15–18: one transaction, one statement, nothing minted, nothing torn."""

    def test_the_topology_half_is_a_single_update(self):
        """Obj. 16. A torn intermediate has no SHAPE to take — not merely no window. Every
        reader of `parent` is a plain equality read, so one statement means each of them
        sees the pre-state or the post-state."""
        self.canonical()
        store.create_agent(self.db, name="l2", role="lead", parent="res", pane_id="p-l2")
        seen: list[str] = []
        self.db.set_trace_callback(seen.append)
        try:
            self.b.done("handed over", me="res", preserve_children=True)
        finally:
            self.db.set_trace_callback(None)
        updates = [q for q in seen if "UPDATE agents SET parent" in q]
        self.assertEqual(len(updates), 1)                 # two children, one statement

    def test_no_row_is_created_and_none_is_deleted(self):
        """Obj. 16. The shape that made `insert-above` hard is simply absent: a set of
        pointers moves up a level and the row count does not change."""
        self.canonical()
        before = self.db.execute("SELECT COUNT(*) c FROM agents").fetchone()["c"]
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) c FROM agents").fetchone()["c"],
                         before)

    def test_a_failure_anywhere_in_it_leaves_the_tree_exactly_where_it_was(self):
        """Obj. 15, 29. The topology write, the `done` it rides on, the state write and
        every signal are ONE transaction. A promote that committed without its signals is
        precisely the silent divergence the signal rule exists to prevent, so the whole lot
        rolls back — including the `done` itself."""
        self.canonical()
        with mock.patch.object(broker_mod.Broker, "_mutation_signals",
                               side_effect=sqlite3.OperationalError("boom")):
            with self.assertRaises(sqlite3.OperationalError):
                self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.b.current_parent("lead"), "res")
        self.assertEqual(store.get_agent(self.db, "res")["state"], "working")
        self.assertEqual(self.mail("top"), [])
        self.assertEqual(self.mail("lead"), [])

    def test_a_concurrent_reader_sees_the_pre_state_or_the_post_state(self):
        """Obj. 16, and the property F1 was built for. The write lock is taken up front
        (`store.mutation` -> `BEGIN IMMEDIATE`), and the answer another connection gets is
        one tree or the other — never a lead under `res` and a `res` that has finished."""
        self.canonical()
        other = sqlite3.connect(str(self.repo / "state.db"), timeout=5)
        other.row_factory = sqlite3.Row
        try:
            before = store.current_parent(other, "lead")
            self.b.done("handed over", me="res", preserve_children=True)
            after = store.current_parent(other, "lead")
        finally:
            other.close()
        self.assertEqual((before, after), ("res", "top"))

    def test_acyclicity_holds_by_construction(self):
        """Obj. 17. The new parent is an ancestor of every row moved, so a cycle would need
        it to sit BELOW one of them — which a tree forbids. Worth pinning because
        `_descendants` does not terminate on a cycle at all."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        for name in ("top", "res", "lead", "worker"):
            seen, cur = set(), name
            while cur is not None:
                self.assertNotIn(cur, seen, f"cycle through {name}")
                seen.add(cur)
                cur = self.b.current_parent(cur)

    def test_single_root_and_no_orphan_hold_because_the_move_is_only_ever_upward(self):
        """Obj. 18. Every moved row lands on a parent that exists (the promoter's own), or
        on the root branch that the promoter itself was already on."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        for r in self.db.execute("SELECT name, parent FROM agents"):
            if r["parent"] is not None:
                self.assertIsNotNone(store.get_agent(self.db, r["parent"]))


class SignalsTest(PromoteFixture, unittest.TestCase):
    """Obj. 23–29: two parties, not three."""

    def test_every_re_homed_child_is_told_and_so_is_the_grandparent(self):
        """Obj. 23, 24, 25. `1 + N` messages for N children, in one call. The child because
        "You report to '{parent}'" is baked into its spawn prompt once and is now stale; the
        grandparent because it gains direct children — new `done` mail and a bigger cleanup
        scope — and would otherwise close agents it never saw."""
        self.canonical()
        store.create_agent(self.db, name="l2", role="lead", parent="res", pane_id="p-l2")
        self.b.done("handed over", me="res", preserve_children=True)
        for kid in ("lead", "l2"):
            sig = [m for m in self.mail(kid) if m["kind"] == SIGNAL]
            self.assertEqual(len(sig), 1)
            self.assertIn("you report to 'top'", sig[0]["body"])
            self.assertIn("handed you up a level", sig[0]["body"])
            self.assertIn("res", sig[0]["body"])
        top = self.mail("top")
        self.assertEqual(len(top), 1)                     # the done, carrying the promote
        self.assertEqual(len(top) + 2, 3)                 # 1 + N, exactly
        self.assertIn("[promote]", top[0]["body"])
        self.assertIn("lead, l2", top[0]["body"])

    def test_the_grandparents_signal_rides_in_on_the_done_it_was_getting_anyway(self):
        """Obj. 26. It costs nothing extra: one more LINE on a message that agent is
        already being handed in this same transaction, not a second row and a second
        doorbell."""
        self.canonical()
        self.b.done("findings are in the brief", me="res", preserve_children=True)
        top = self.mail("top")
        self.assertEqual([m["kind"] for m in top], ["done"])
        self.assertTrue(top[0]["body"].startswith("[done] findings are in the brief"))
        self.assertIn("[promote]", top[0]["body"])

    def test_nobody_else_is_told(self):
        """Obj. 25. There is no third "old parent": the old parent IS the promoter, the
        agent performing the act, and it needs no news of its own call."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.mail("res"), [])
        self.assertEqual(self.mail("worker"), [])         # a grandchild is not a party

    def test_a_human_grandparent_has_no_mailbox_so_the_surfaced_line_carries_it(self):
        """Obj. 27. Where the grandparent is the human there is nothing to write to, so the
        promote is named in the line `done` already surfaces."""
        store.create_agent(self.db, name="solo", role="researcher", pane_id="p1")
        store.create_agent(self.db, name="kid", role="lead", parent="solo", pane_id="p2")
        self.h.notifications.clear()
        self.b.done("all yours", me="solo", preserve_children=True)
        self.assertTrue(any("handed up to you: kid" in n for n in self.h.notifications),
                        self.h.notifications)

    def test_the_signals_are_the_never_digested_held_ring_class(self):
        """Obj. 28. `signal` is exempt from the envelope digest BY SHAPE — the digest reads
        `done` rows — and it is in `HELD_RING_KINDS`, so a promote of ten children coalesces
        into one doorbell instead of ten. `block` and `--interrupt` stay exempt by shape."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual([m["kind"] for m in self.mail("lead")], [SIGNAL])
        self.assertIn(SIGNAL, broker_mod.HELD_RING_KINDS)

    def test_a_repeat_done_still_promotes_and_the_grandparent_still_hears(self):
        """The corner the `1 + N` rule has to survive: a repeat `done` mails nothing, so the
        line the grandparent's signal would have ridden on does not exist. It gets its own
        signal row instead, and the count is `1 + N` either way. Promoting on a repeat is
        deliberate — it is the ordinary way an agent that reported done and then thought
        better of leaving its children stranded puts it right."""
        self.canonical()
        self.b.done("finished", me="res")
        self.b.done("finished", me="res", preserve_children=True)
        self.assertTrue(self.b.done_repeat)
        self.assertEqual(self.b.current_parent("lead"), "top")
        kinds = sorted(m["kind"] for m in self.mail("top"))
        self.assertEqual(kinds, ["done", SIGNAL])
        self.assertEqual(len(self.mail("lead")), 1)


class TheGateAndTheRaceTest(PromoteFixture, unittest.TestCase):
    """Obj. 19–22: promote empties the live-descendants gate; the `--force` race is benign."""

    def test_promote_empties_the_live_descendants_gate_rather_than_fighting_it(self):
        """Obj. 22. That gate is exactly what makes a done-with-live-children agent linger.
        The promoter has no live descendants left, so the parent's ordinary sweep — no
        `--force`, no naming — takes its row."""
        self.canonical()
        self.b.done("still going", me="res")
        with self.assertRaises(ValueError) as e:          # refused: lead is live under it
            self.b.cleanup(["res"], me="top")
        self.assertIn("still working underneath", str(e.exception))
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(list(self.b.cleanup(["res"], me="top")), ["res"])
        self.assertEqual(store.get_agent(self.db, "lead")["state"], "working")

    def test_no_agent_closes_its_own_row_and_promote_does_not_change_that(self):
        """Obj. 21. "Closing" is the ordinary close. `cleanup`'s scope is strictly BELOW
        the caller, before the promote and after it."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertNotIn("res", [a["name"] for a in self.b._descendants("res")])
        with self.assertRaises(KeyError):      # not in its own scope, so not nameable
            self.b.cleanup(["res"], me="res")

    def test_the_promote_vs_cleanup_force_race_is_benign(self):
        """Obj. 19. `--force` reads the subtree first and then closes it leaves-first. A
        promote committing between the read and the closes means it closes rows that are by
        then the GRANDPARENT's own direct children — and the grandparent is the caller, and
        `--force` on a named subtree is already documented as taking live descendants with
        it. The outcome is the close the operator asked for, one moment earlier."""
        self.canonical()
        real = broker_mod.Broker._leaves_up

        def race(self_b, candidates):
            out = real(self_b, candidates)
            other = sqlite3.connect(str(self.repo / "state.db"), timeout=5)
            try:                                  # the promote lands mid-`--force`
                other.execute("UPDATE agents SET parent='top' WHERE parent='res'")
                other.commit()
            finally:
                other.close()
            return out

        with mock.patch.object(broker_mod.Broker, "_leaves_up", race):
            closed = list(self.b.cleanup(["res"], me="top", force=True))
        self.assertEqual(closed, ["worker", "lead", "res"])
        self.assertEqual(self.h.closed, ["w1:p3", "w1:p2", "w1:p1"])

    def test_the_dangerous_inverse_cannot_occur(self):
        """Obj. 20. A `--force` reaching rows OUTSIDE the caller's subtree is the failure
        that would matter, and it cannot happen: promote only ever moves rows UP, into a
        scope that already contained them. A sibling's subtree is never reachable."""
        self.canonical()
        store.create_agent(self.db, name="other", role="lead", parent="top", pane_id="p-o")
        store.create_agent(self.db, name="theirs", role="worker", parent="other",
                           pane_id="p-t")
        self.b.done("handed over", me="res", preserve_children=True)
        closed = list(self.b.cleanup(["res"], me="top", force=True))
        self.assertEqual(closed, ["res"])
        self.assertEqual(store.get_agent(self.db, "theirs")["state"], "working")
        self.assertEqual(store.get_agent(self.db, "lead")["state"], "working")


class PointerOnlyTest(PromoteFixture, unittest.TestCase):
    """Obj. 30–31: the reporting line moves and nothing else does."""

    def test_the_re_homed_child_keeps_its_pane_its_checkout_and_its_branch(self):
        """Obj. 30. Moving a live agent's cwd or workspace is out of scope BY DESIGN
        (§2.2); nothing here moves a checkout. The child carries on in the pane it is in."""
        self.canonical()
        before = dict(store.get_agent(self.db, "lead"))
        self.b.done("handed over", me="res", preserve_children=True)
        after = dict(store.get_agent(self.db, "lead"))
        self.assertEqual(before.pop("parent"), "res")
        self.assertEqual(after.pop("parent"), "top")
        self.assertEqual(before, after)                   # every other column identical

    def test_the_promoted_leads_capability_set_is_untouched(self):
        """Obj. 31. Seeding composes and promote is not part of it: the lead's caps were
        seeded by the ORDINARY `delegate` that created it, `template(lead) ∩
        passable(researcher)`, and a promote neither re-seeds nor re-checks them."""
        top = self.top()
        res = self.b.delegate("t", topic="r", role="researcher", me=top)
        self.b.grant(res, broker_mod.CAP_SPAWN, me=top)
        self.b.grant(res, broker_mod.CAP_WRITE_TRACKED, me=top, delegable=True)
        lead = self.b.delegate("t", topic="l", role="lead", me=res)
        before = store.held_capabilities(self.db, lead)
        self.b.done("handed over", me=res, preserve_children=True)
        self.assertEqual(store.held_capabilities(self.db, lead), before)
        self.assertIn(broker_mod.CAP_WRITE_TRACKED, before)
        # and the researcher stays read-only through all of it
        self.assertNotIn(broker_mod.CAP_WRITE_TRACKED, store.held_capabilities(self.db, res))


class CliTest(PromoteFixture, unittest.TestCase):
    """What the CLI reads back to the caller, at the seam the CLI reads it from.

    The note TEXT is not asserted here: printing it needs `cli.main`, which builds a real
    herdr adapter and rings a real doorbell. What is pinned is the contract between the two
    — the flag's dest, and the attribute the note is built from — and the text itself is
    proven by the live run (see the unit's report).
    """

    def test_the_flag_parses_to_the_keyword_done_takes(self):
        args = build_parser().parse_args(["done", "s", "--preserve-children"])
        self.assertTrue(args.preserve_children)

    def test_promoted_is_reset_per_call_so_a_later_done_cannot_report_an_earlier_one(self):
        """The CLI prints `b.promoted` after every `done`, so a stale list from a previous
        call in the same process would tell an agent it had handed up somebody it had
        not."""
        self.canonical()
        self.b.done("handed over", me="res", preserve_children=True)
        self.assertEqual(self.b.promoted, ["lead"])
        self.b.done("finished", me="worker")
        self.assertEqual(self.b.promoted, [])
        self.assertEqual(self.b.live_descendants("res"), [])


if __name__ == "__main__":
    unittest.main()
