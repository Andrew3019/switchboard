"""D4 — worktree backpressure: the count is SURFACED, never capped (#163-B, §2.2).

Decoupling `fork` from `is_top` (D2) removed an accidental resource bound — historically
only tops held an open worktree, so the count was small by construction — and afterwards
any `fork`-holding lead can mint N isolated children. The chosen answer is **visibility,
not policing**, so what is pinned here is a NUMBER on a row and the absence of everything
else:

* the **open-worktree count per lead** rides in `sb status`'s WORKSPACE column, off the
  `workspaces.created_by` the fork already records — no new counter, no new column;
* a **lead's row aggregates its subtree**, the way C3's divergence marker already does, so
  a twenty-way fan-out's cost is one cell rather than twenty leaf rows added up by eye;
* **nothing refuses or caps.** A soft fan-out nudge is delivered through the guidance
  ledger before a shared write-tracked child is started; status itself remains a quiet
  count and never grows a warning or refusal.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import board, status as status_mod, store  # noqa: E402

from test_workspace import Fixture  # noqa: E402


class Backpressure(Fixture):
    def snap(self):
        """The readout as `sb status` computes it: this repo's roles, no herdr."""
        return status_mod.collect(self.db, None, repo=self.repo)

    def cell(self, name: str) -> str:
        return {a.name: a.workspace_cell for a in self.snap().agents}[name]

    def fan_out(self, me: str, n: int, prefix: str = "w") -> list[str]:
        """`n` isolated children of `me`. A lead's fan-out, which is what the count counts."""
        return [self.b.delegate("t", topic=f"{prefix}{i}", role="worker", me=me,
                                isolation="own")
                for i in range(n)]


# ---------------------------------------------------------------------------
# The count itself
# ---------------------------------------------------------------------------


class WorktreeCountTest(Backpressure, unittest.TestCase):

    def test_the_open_worktree_count_rides_on_the_minting_agents_row(self):
        """Objective 1. The fork already records who minted the space, so the count is a
        GROUP BY over data that was there — and it lands on the agent that spent the
        resource, not on the children holding it."""
        root = self._root()
        kids = self.fan_out(root, 3)
        self.assertEqual(self.cell(root), "scratch wt3")
        for k in kids:
            self.assertEqual(self.cell(k), k)      # a holder is not a minter

    def test_an_agent_that_minted_nothing_says_what_it_always_said(self):
        """The absence of a count is the resting state: a row that forked nothing draws
        its workspace name and nothing else, exactly as before D4."""
        root = self._root()
        kid = self.b.delegate("t", topic="shared", role="worker", me=root,
                              isolation="shared")
        self.assertEqual(self.cell(kid), self.cell(kid).split(" ")[0])
        self.assertNotIn("wt", self.cell(kid))

    def test_a_retired_workspace_stops_being_an_OPEN_worktree(self):
        """OPEN is the point: the number answers "what is on disk right now", so a
        workspace whose worktree has been taken away must leave it."""
        root = self._root()
        kids = self.fan_out(root, 2)
        self.assertEqual(self.cell(root), "scratch wt2")
        store.retire_workspace(self.db, kids[0])
        self.assertEqual(self.cell(root), "scratch wt1")

    def test_a_bare_workspace_is_never_counted_as_a_worktree(self):
        """A bare workspace has no checkout of its own (`checkout IS NULL` is exactly what
        bare MEANS) — four orchestrators over one primary clone are not four worktrees, and
        counting them would make the number meaningless on the machine it matters on."""
        root = self._root()
        store.record_workspace(self.db, "bare-space", None, created_by=root)
        self.assertEqual(self.cell(root), "scratch")


# ---------------------------------------------------------------------------
# The lead-row aggregate (§2.5, with C3)
# ---------------------------------------------------------------------------


class SubtreeAggregateTest(Backpressure, unittest.TestCase):

    def test_a_leads_row_carries_what_its_descendants_hold(self):
        """Objective 5. The same aggregation the divergence marker performs, over a count:
        at 20+ rows, adding up leaf cells to find what a fan-out cost is not a glance. The
        subtree number is drawn APART from the row's own so neither is double-counted."""
        root = self._root()
        lead = self.b.delegate("t", topic="a", role="lead", me=root, isolation="own")
        self.fan_out(lead, 4)
        self.assertEqual(self.cell(lead), f"{lead} wt4")
        self.assertEqual(self.cell(root), "scratch wt1 ↓4")

    def test_the_aggregate_climbs_and_never_goes_sideways(self):
        """Ancestors only. A sibling's fan-out is not this lead's to answer for, and a row
        that claimed it would send a reader down the wrong subtree."""
        root = self._root()
        busy = self.b.delegate("t", topic="busy", role="lead", me=root, isolation="own")
        quiet = self.b.delegate("t", topic="quiet", role="lead", me=root, isolation="own")
        deep = self.b.delegate("t", topic="deep", role="lead", me=busy, isolation="own")
        self.fan_out(deep, 2)
        self.assertEqual(self.cell(quiet), quiet)                 # untouched
        self.assertEqual(self.cell(deep), f"{deep} wt2")
        self.assertEqual(self.cell(busy), f"{busy} wt1 ↓2")  # its own + below
        self.assertEqual(self.cell(root), "scratch wt2 ↓3")  # all the way up

    def test_the_column_is_sized_to_the_count_and_nothing_is_clipped(self):
        """Like ROLE, the WORKSPACE column is sized to content — the count widens it rather
        than pushing the row's flags off the end of the line."""
        root = self._root()
        self.fan_out(root, 3)
        text = status_mod.render(self.snap())
        self.assertIn("scratch wt3", text)


# ---------------------------------------------------------------------------
# What D4 deliberately does NOT do
# ---------------------------------------------------------------------------


class NoHardCapTest(Backpressure, unittest.TestCase):

    def test_a_twenty_way_fan_out_is_not_refused(self):
        """Objective 2, and the reason the whole unit is a number instead of a ceiling: a
        hard cap would refuse a legitimate 20-way fan-out at exactly the moment the fleet
        is doing its most valuable work."""
        root = self._root()
        kids = self.fan_out(root, 20)
        self.assertEqual(len(set(kids)), 20)
        self.assertGreater(20, status_mod.WORKTREE_SOFT_THRESHOLD)   # well past it
        self.assertEqual(self.cell(root), "scratch wt20")

    def test_past_the_soft_threshold_status_stays_a_quiet_count(self):
        """Objective 3: the nudge belongs to the spawn path, not the status renderer. The
        count past the threshold is drawn exactly like a count below it — a renderer that
        started shouting would be the hard cap in a different hat."""
        root = self._root()
        self.fan_out(root, status_mod.WORKTREE_SOFT_THRESHOLD + 1)
        text = status_mod.render(self.snap())
        self.assertIn(f"scratch wt{status_mod.WORKTREE_SOFT_THRESHOLD + 1}", text)
        for shout in ("threshold", "too many", "worktrees!", "WARNING"):
            self.assertNotIn(shout, text)

    def test_nothing_competes_for_the_boards_one_trouble_slot(self):
        """Objective 7. A worktree count is news to read, not a row a human must act on
        this second — `board.marker` stays BLOCKED/GONE/STALLED only."""
        root = self._root()
        self.fan_out(root, status_mod.WORKTREE_SOFT_THRESHOLD + 5)
        rows = {a.name: a for a in self.snap().agents}
        self.assertEqual(board.marker(rows[root]), "")
