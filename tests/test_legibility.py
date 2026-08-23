"""Phase 1 — legibility: `sb who-holds` and the divergence marker (#163-A, C3).

Capabilities are now fluid — seeded by intersection, widened by a grant — while the ROLE
label is frozen at spawn. That is a readable design only if the drift between the two is
VISIBLE, and these pin the two devices that make it so (§2.5):

* the **`sb status` ROLE column** carries a SIGNED marker — widened and narrowed are
  different news, and one undirected mark would collapse them into an unreadable bit;
* **`sb who-holds <cap>`** answers the reverse question no per-row rendering can, in one
  scan that reads no parent column and therefore survives a promote.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import board, status as status_mod, store  # noqa: E402
from switchboard.broker import (  # noqa: E402
    CAP_DISPATCH, CAP_SPAWN, CAP_WRITE_TRACKED,
)

from test_grants import Fixture  # noqa: E402


class Legibility(Fixture):
    def snap(self):
        """The readout as `sb status` computes it: this repo's roles, no herdr."""
        return status_mod.collect(self.db, None, repo=self.repo)

    def cell(self, name: str) -> str:
        return {a.name: a.role_cell for a in self.snap().agents}[name]


# ---------------------------------------------------------------------------
# `sb who-holds <cap>`
# ---------------------------------------------------------------------------


class WhoHoldsTest(Legibility, unittest.TestCase):

    def test_it_lists_every_holder_and_keeps_delegable_apart(self):
        """Objectives 1 and 4. Held and delegable-only are different answers to "who can
        write?" — one is a writer, the other only equips writers — and provenance rides
        along because the ROLE column deliberately does not carry it."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        worker = self.spawn(lead, "worker", "w")
        researcher = self.spawn(lead, "researcher", "r")
        self.b.grant(researcher, CAP_WRITE_TRACKED, delegable=True, me=lead,
                     reason="to equip its workers")

        holders = {h["agent"]: h for h in self.b.who_holds(CAP_WRITE_TRACKED)}
        self.assertEqual(set(holders), {lead, worker, researcher})
        self.assertNotIn(top, holders)                       # the top never writes
        self.assertTrue(holders[worker]["held"])
        self.assertIsNone(holders[worker]["granted_by"])      # seeded, nobody's decision
        self.assertFalse(holders[researcher]["held"])         # pass-through only
        self.assertTrue(holders[researcher]["delegable"])
        self.assertEqual(holders[researcher]["granted_by"], lead)
        self.assertEqual(holders[researcher]["reason"], "to equip its workers")

    def test_it_does_not_depend_on_the_tree_shape(self):
        """Objective 3: the audit a promote cannot invalidate. `parent` is write-once
        today, so this moves the row the way F2 eventually will and asserts the answer is
        the same — the query reads no parent column at all."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        other = self.spawn(top, "lead", "l2")
        worker = self.spawn(lead, "worker", "w")
        before = self.b.who_holds(CAP_WRITE_TRACKED)
        self.db.execute("UPDATE agents SET parent=? WHERE name=?", (other, worker))
        self.db.commit()
        self.assertEqual(self.b.who_holds(CAP_WRITE_TRACKED), before)

    def test_a_capability_that_does_not_exist_is_refused_not_answered(self):
        """`sb who-holds wrte-tracked` returning "nobody" reads as an all-clear. Same
        fail-closed rule the grant path applies to the same typo."""
        self.top()
        with self.assertRaises(ValueError):
            self.b.who_holds("wrte-tracked")


# ---------------------------------------------------------------------------
# The `sb status` ROLE column
# ---------------------------------------------------------------------------


class DivergenceMarkerTest(Legibility, unittest.TestCase):

    def test_caps_equal_to_the_template_draw_the_plain_role_name(self):
        """The absence of a marker IS the signal — a label with no mark must be
        trustworthy, or every row has to be checked against `sb who-holds`."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        worker = self.spawn(lead, "worker", "w")
        self.assertEqual(self.cell(top), "dispatcher")
        self.assertEqual(self.cell(lead), "lead")
        self.assertEqual(self.cell(worker), "worker")

    def test_the_mark_is_signed_so_widened_and_narrowed_read_apart(self):
        """Objectives 7 and 8, in one assertion each way: a granted reviewer is MORE
        powerful than its label and a ∩-seeded lead is crippled, and one undirected mark
        would say the same thing about both."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        reviewer = self.spawn(lead, "reviewer", "rv")
        self.b.grant(reviewer, CAP_SPAWN, me=lead)
        self.assertEqual(self.cell(reviewer), "reviewer +spawn")

        worker = self.spawn(lead, "worker", "w")
        self.b.grant(worker, CAP_SPAWN, me=lead)
        crippled = self.spawn(worker, "lead", "sub")          # ∩-seeded: no dispatch
        self.assertNotIn(CAP_DISPATCH, store.held_capabilities(self.db, crippled))
        self.assertEqual(self.cell(crippled), "lead−")
        self.assertNotEqual(self.cell(crippled), self.cell(reviewer))

    def test_a_delegable_only_cap_is_drawn_distinctly_from_a_held_one(self):
        """"May pass this to its children" must never read as "does this itself" — the
        researcher below still fails the gate on the very capability its row names."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        researcher = self.spawn(lead, "researcher", "r")
        self.b.grant(researcher, CAP_WRITE_TRACKED, delegable=True, me=lead)
        self.assertEqual(self.cell(researcher), "researcher →write-tracked")
        with self.assertRaises(ValueError):
            self.b.require_capability(researcher, CAP_WRITE_TRACKED)

        # And the held form of the same capability on the same role reads differently.
        other = self.spawn(lead, "researcher", "r2")
        self.b.grant(other, CAP_WRITE_TRACKED, me=lead)
        self.assertEqual(self.cell(other), "researcher +write-tracked")

    def test_a_lead_row_carries_the_mark_when_a_descendant_diverges(self):
        """Objective 12. At 20+ sibling rows, finding the one granted child by reading
        every leaf is not a glance — so the ancestors say "look below me", and say it
        without claiming the divergence is their own."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        worker = self.spawn(lead, "worker", "w")
        quiet = self.spawn(lead, "worker", "w2")
        self.assertEqual(self.cell(lead), "lead")             # nothing below it yet
        self.b.grant(worker, CAP_SPAWN, me=lead)

        self.assertEqual(self.cell(worker), "worker +spawn")
        self.assertEqual(self.cell(lead), "lead ↓")      # aggregated, not its own
        self.assertEqual(self.cell(top), "dispatcher ↓")  # all the way up
        self.assertEqual(self.cell(quiet), "worker")          # and never sideways

    def test_the_column_is_sized_to_the_marker_and_nothing_is_clipped(self):
        """The ROLE column has no clip, so the marker widens it rather than being cut off
        — the property §2.5 chose `sb status` over a board glyph for."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        reviewer = self.spawn(lead, "reviewer", "rv")
        self.b.grant(reviewer, CAP_SPAWN, me=lead)
        text = status_mod.render(self.snap())
        self.assertIn("reviewer +spawn", text)

    def test_the_names_are_dropped_for_a_bare_sign_before_the_line_wraps(self):
        """A heavily granted row must not push every other column off a terminal. The
        SIGN is what survives, exactly as `richboard.marker_short` keeps the word."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        reviewer = self.spawn(lead, "reviewer", "rv")
        for cap in (CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED):
            self.b.grant(reviewer, cap, me=lead)
        self.assertEqual(self.cell(reviewer), "reviewer+")

    def test_a_row_older_than_the_substrate_draws_no_marker(self):
        """A NULL seed is a row nobody seeded, not a row seeded with nothing: its set is
        DERIVED at the gate, so there is nothing to diverge and a marker on it would be
        the substrate inventing news about a row that predates it."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        self.db.execute("UPDATE agents SET seed_capabilities=NULL WHERE name=?", (lead,))
        self.db.execute("DELETE FROM capabilities WHERE agent=?", (lead,))
        self.db.commit()
        self.assertEqual(self.cell(lead), "lead")

    def test_nothing_competes_for_the_boards_one_trouble_slot(self):
        """Objective 11: `board.marker` stays BLOCKED/GONE/STALLED only. A rights change
        is news to read, not a row a human has to act on this second."""
        top = self.top()
        lead = self.spawn(top, "lead", "l")
        worker = self.spawn(lead, "worker", "w")
        self.b.grant(worker, CAP_SPAWN, me=lead)
        rows = {a.name: a for a in self.snap().agents}
        self.assertEqual(board.marker(rows[worker]), "")
        self.assertEqual(board.marker(rows[lead]), "")
