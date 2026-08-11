"""The Stop gate — the decision, its loop cap, and the wiring that delivers it.

Three tests, deliberately. What a test can pin here is the DECISION (a real store, real
rows) and the fact that every spawn carries the settings file. What it cannot pin is that
Claude honours the response, so that half is proved live, in an isolated clone, and written
up in `audit/phase3.8-scope.md` — not simulated here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import hooks, store  # noqa: E402
from switchboard.herdr import Herdr  # noqa: E402
from tests.test_herdr import AGENT_JSON, FakeHerdr, ok  # noqa: E402


class StopGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def payload(self, **kw):
        return {"session_id": "sess-1", "hook_event_name": "Stop", **kw}

    def test_a_working_agent_is_stopped_and_a_reported_one_is_not(self):
        """The whole point: a turn ending with nothing said does not end."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        reason = hooks.stop_gate(self.payload(), self.db)
        self.assertIsNotNone(reason)
        self.assertIn("sb done", reason)
        self.assertIn("sb block", reason)

        store.set_state(self.db, "w1", "done")
        self.assertIsNone(hooks.stop_gate(self.payload(), self.db))

        # `blocked` is a report too — it is the one way an agent reaches a person.
        store.set_state(self.db, "w1", "blocked")
        self.assertIsNone(hooks.stop_gate(self.payload(), self.db))

    def test_stop_hook_active_is_the_loop_cap(self):
        """One nudge per stop-chain, or the gate is the loop it is meant to prevent.

        The flag is set by the CLI on a turn this gate itself caused (verified against the
        real CLI, 2026-08-11). Honouring it is what makes "blocked, so take another turn,
        which ends, so block again" terminate — at most once, whatever the agent does.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.assertIsNotNone(hooks.stop_gate(self.payload(), self.db))
        self.assertIsNone(hooks.stop_gate(self.payload(stop_hook_active=True), self.db))


class SpawnCarriesTheHookTest(unittest.TestCase):
    def test_every_spawn_passes_the_settings_file_and_it_holds_a_stop_hook(self):
        """Wiring, in the one place every spawn and restore passes through.

        `--settings` merges into that session only and `--bare` is absent, which is what
        makes the hook reach our agents and nobody else's sessions.
        """
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent("w1", "w1:p9")
        argv = fake.argv()
        self.assertIn("--settings", argv)
        self.assertNotIn("--bare", argv)

        path = Path(hooks.settings_file())
        self.assertIn(str(path), argv)
        body = json.loads(path.read_text())
        cmd = body["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(cmd.split()[0].endswith("bin/sb-stop-hook"), cmd)


if __name__ == "__main__":
    unittest.main()
