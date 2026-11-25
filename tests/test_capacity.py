"""The memory gate: `sb delegate` refuses a spawn that would leave too little memory."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import capacity, store  # noqa: E402

from test_workspace import Fixture  # noqa: E402

MB = capacity.MB


class CapacityTest(Fixture, unittest.TestCase):
    def avail(self, mb):
        return mock.patch.object(capacity, "available_bytes", lambda: mb * MB)

    def test_plenty_of_memory_spawns(self):
        with self.avail(8000):
            kid = self.b.delegate("t", topic="ok", role="worker", me=self._root())
        self.assertIsNotNone(store.get_agent(self.db, kid))

    def test_low_memory_refuses_and_leaves_nothing_behind(self):
        root = self._root()
        before = {r["name"] for r in self.db.execute("SELECT name FROM agents")}
        with self.avail(1200), self.assertRaises(ValueError) as cm:
            self.b.delegate("t", topic="tight", role="worker", me=root)
        self.assertIn("not enough memory", str(cm.exception))
        self.assertIn("Do NOT do the work yourself", str(cm.exception))
        after = {r["name"] for r in self.db.execute("SELECT name FROM agents")}
        self.assertEqual(before, after)
        kinds = [r[0] for r in self.db.execute("SELECT kind FROM events")]
        self.assertIn("spawn_refused_memory", kinds)

    def test_unknown_memory_is_allowed(self):
        with mock.patch.object(capacity, "available_bytes", lambda: None):
            self.assertIsNone(capacity.refusal(self.repo))

    def test_threshold_is_reserve_plus_one_agent(self):
        # shipped: reserve 1024 + per-agent 500
        with self.avail(1524):
            self.assertIsNone(capacity.refusal(self.repo))
        with self.avail(1523):
            self.assertIsNotNone(capacity.refusal(self.repo))

    def test_disabled_never_refuses(self):
        with self.avail(10), mock.patch.object(
                capacity.config, "setting",
                lambda k, default=None, repo=None: False if k == "capacity.enabled" else 0):
            self.assertIsNone(capacity.refusal(self.repo))

    def test_a_top_is_never_gated(self):
        with self.avail(10):
            self.b.delegate("t", name="top2", role="lead", me=self._root(), is_top=True)


if __name__ == "__main__":
    unittest.main()
