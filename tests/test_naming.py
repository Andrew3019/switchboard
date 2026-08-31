"""What a delegated agent is CALLED: `<role>-<topic>`, composed in one place.

The name is not cosmetic and this file is not a style test. An agent's name is also its
workspace and its git branch (`Broker._fork_for`), so it is the string a person reads the
whole job by — on the board, in `git branch`, on the pull request. It used to be
`<role>-<n>` whenever nobody passed one, and 247 of this store's first 717 agents were
named that way: `worker-69` is a row that says nothing about what it is doing.

Three facts are pinned here, and they are the three that could regress quietly:
the composition, the refusal that replaced the number, and the truncation.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import store, validate  # noqa: E402
from switchboard.broker import Broker  # noqa: E402
from switchboard.herdr import Agent, HerdrError  # noqa: E402

from test_workspace import FakeHerdr  # noqa: E402


class ComposedNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.b = Broker(self.db, FakeHerdr(self.repo / "worktrees"), repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def test_the_name_carries_the_role_and_the_subject(self):
        self.assertEqual(self.b._compose_name("lead", "triage bugs"), "lead-triage-bugs")

    def test_a_topicless_spawn_is_refused_rather_than_numbered(self):
        """The whole point of the change: there is no `<role>-<n>` fallback to fall into,
        so a parent that names nothing is told to, once."""
        for nothing in (None, "", "   "):
            with self.assertRaises(ValueError) as e:
                self.b._compose_name("worker", nothing)
            self.assertIn("--name", str(e.exception))

    def test_a_second_job_on_the_same_subject_counts_from_two(self):
        store.create_agent(self.db, name="lead-triage-bugs", role="lead")
        self.assertEqual(self.b._compose_name("lead", "triage bugs"), "lead-triage-bugs-2")

    def test_a_name_herdr_holds_machine_wide_is_skipped_even_with_an_empty_store(self):
        """The fresh-clone bug: the store is per-clone and empty, so a bare stem looked
        free here while herdr already held it from another clone — and the spawn does not
        retry `agent_name_taken`. Consulting herdr picks the suffix on the first try."""
        self.b.h.live["lead-triage-bugs"] = Agent(
            name="lead-triage-bugs", pane_id="w9:p1", terminal_id="t", session_id="s")
        # Nothing in this clone's store — only herdr holds it.
        self.assertIsNone(store.get_agent(self.db, "lead-triage-bugs"))
        self.assertEqual(self.b._compose_name("lead", "triage bugs"), "lead-triage-bugs-2")

    def test_an_unreachable_herdr_falls_back_to_the_store_only_check(self):
        """Best-effort: a herdr that cannot answer must not block a spawn, so the name is
        composed from the store alone, exactly as before this check existed."""
        def boom():
            raise HerdrError("cli_failure", "herdr is down")
        self.b.h.list_agents = boom
        self.assertEqual(self.b._compose_name("lead", "triage bugs"), "lead-triage-bugs")

    def test_truncation_cuts_the_topic_and_never_the_prefix(self):
        """herdr allows 32 characters. A long topic loses its tail; the role half is what
        the name is unreadable without, so it cannot be what gets cut."""
        got = self.b._compose_name("researcher", "spawn prompt assembly and the tiers "
                                                 "it resolves through")
        self.assertTrue(got.startswith("researcher-"), got)
        self.assertEqual(validate.agent_name(got), got)      # legal for herdr


if __name__ == "__main__":
    unittest.main()
