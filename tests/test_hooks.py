"""The two turn edges — the Stop gate's decision, and the activity signal beside it.

The gate: the three tests it was built with, and two for the cap that the integration
found was not one. The signal (`agents.turn`): the two edges, and the ordering between the
gate and the idle mark, which is the likeliest bug in it.

What a test can pin here is the DECISION and the WRITE (a real store, real rows) and the
fact that every spawn carries the settings file. What it cannot pin is that Claude honours
the response or fires the events at all, so those halves are proved live, in an isolated
clone — once for the gate, once for the signal.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_the_cap_survives_a_new_stop_chain(self):
        """The cap the flag above cannot keep, and the defect it was found by.

        `stop_hook_active` is scoped to ONE stop-chain — one user prompt. A ring, a `tell`
        or the reconciler's own nudge starts a fresh chain with the flag false, and the
        gate blocked the same agent a second time twelve seconds later. The store is what
        outlives a chain, so one block
        per agent until it says something is asked of the event log.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.assertIsNotNone(hooks.stop_gate(self.payload(), self.db))
        # A new chain: the flag is false and honestly so, and it still must not block.
        self.assertIsNone(hooks.stop_gate(self.payload(), self.db))
        blocks = self.db.execute(
            "SELECT COUNT(*) c FROM events WHERE kind='stop_gate_blocked'").fetchone()["c"]
        self.assertEqual(blocks, 1)

    def test_a_report_re_arms_the_gate(self):
        """Once per SILENCE, not once per lifetime. An agent that reported and was then
        spoken to in its pane is `working` again, and that next quiet turn-end is a new
        silence — the case the scope decision deliberately does not exempt."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.assertIsNotNone(hooks.stop_gate(self.payload(), self.db))
        store.set_state(self.db, "w1", "done")
        store.log_event(self.db, kind="done", agent="w1")
        store.set_state(self.db, "w1", "working")       # revived by a person in its pane
        self.assertIsNotNone(hooks.stop_gate(self.payload(), self.db))


class ActivitySignalTest(unittest.TestCase):
    """The two edges — `agents.turn`. What a test can pin is the WRITE; that Claude Code
    fires the two events at all is proved live, in an isolated clone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.db = store.connect(path=self.path)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def payload(self, **kw):
        return {"session_id": "sess-1", **kw}

    def turn(self, name="w1"):
        return store.get_agent(self.db, name)["turn"]

    def stop(self, **kw):
        """The real Stop hook, over the real entry point's arguments."""
        return hooks.run(json.dumps(self.payload(**kw)), db_path=self.path)

    def start(self):
        hooks.run_activity(json.dumps(self.payload()), db_path=self.path)

    def test_a_turn_marks_working_at_its_start_and_idle_at_its_end(self):
        """The whole signal, in the order a turn actually happens in.

        Nothing is recorded before the first prompt: a row that has never been given
        anything has no edge to report, and NULL is what every reader falls back to herdr
        on.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.assertIsNone(self.turn())
        self.start()
        self.assertEqual(self.turn(), store.TURN_WORKING)
        store.set_state(self.db, "w1", "done")          # it reported, so the gate allows it
        self.assertEqual(self.stop(), {})
        self.assertEqual(self.turn(), store.TURN_IDLE)

    def test_a_turn_the_gate_refuses_to_end_is_not_recorded_idle(self):
        """THE ordering bug this change could most easily have shipped.

        A blocked stop is not the end of a turn: the agent is handed `BLOCK_REASON` and
        keeps going in the same turn, and `UserPromptSubmit` does not fire again for it.
        Marking idle there would hand its held mail over mid-turn and have the reconciler
        ask a working agent why its turn ended.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.start()
        out = self.stop()                               # silent finish: refused
        self.assertIn("sb done", out["reason"])
        self.assertEqual(self.turn(), store.TURN_WORKING)

        # The continued turn ends for real, carrying the flag the gate's own block sets.
        self.assertEqual(self.stop(stop_hook_active=True), {})
        self.assertEqual(self.turn(), store.TURN_IDLE)

    def test_an_agent_that_blocked_has_ended_its_turn(self):
        """`blocked` is a report, so the gate lets the stop through — and a blocked agent
        is stopped, waiting on a person. Both columns are true at once and they are
        answering different questions: state=blocked, turn=idle."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.start()
        store.set_state(self.db, "w1", "blocked")
        self.assertEqual(self.stop(), {})
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "blocked")
        self.assertEqual(self.turn(), store.TURN_IDLE)

    def test_a_session_that_is_not_ours_is_never_written(self):
        """The isolation, from the writing end. Only agents we spawned are handed the
        settings file at all, and an unresolvable caller writes nothing even so."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        with mock.patch.dict(os.environ, {}, clear=True):
            hooks.run_activity(json.dumps({"session_id": "somebody-else"}),
                               db_path=self.path)
        self.assertIsNone(self.turn())

    def test_the_edges_do_not_reset_the_idle_clock(self):
        """Logged against no agent, with the target in the payload — `Broker._nudge`'s
        rule and for its reason. `status._last_activity` counts every event that NAMES an
        agent, and the reconciler's ping IS a prompt, so an edge logged against the agent
        would let the reconciler read its own footprint as the agent having done
        something and nag forever."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.start()
        rows = self.db.execute(
            "SELECT agent, payload FROM events WHERE kind='turn_start'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["agent"])
        self.assertIn("w1", rows[0]["payload"])


class PreToolGateTest(unittest.TestCase):
    """The top-orchestrator gate. What a test can pin is the DECISION; that Claude Code
    honours the deny shape at all is proved live, in an isolated clone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def payload(self, **kw):
        return {"session_id": "sess-1", "hook_event_name": "PreToolUse",
                "tool_name": "Edit", **kw}

    def test_a_top_is_refused_an_edit_and_an_ordinary_agent_is_not(self):
        """The whole point, both directions in one test — a gate that denies everything
        enforces nothing useful, and neither does one that denies nothing."""
        store.create_agent(self.db, name="top-1", role="orchestrator",
                           session_id="sess-1", is_top=True)
        reason = hooks.pretool_gate(self.payload(), self.db)
        self.assertIsNotNone(reason)
        self.assertIn("sb delegate", reason)

        # Only the file-mutating tools. The top's own job runs through Bash (`sb delegate`).
        self.assertIsNone(hooks.pretool_gate(self.payload(tool_name="Bash"), self.db))

        # The shape, in the same test because it is the same claim: `PreToolUse` does NOT
        # use the Stop hook's `{"decision": …}` — its decision lives in `hookSpecificOutput`,
        # and a deny in the wrong shape is a gate that looks installed and enforces nothing.
        out = hooks.run_pretool(json.dumps(self.payload()),
                                db_path=Path(self.tmp.name) / "state.db")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

        self.db.execute("UPDATE agents SET is_top=0 WHERE name='top-1'")
        self.assertIsNone(hooks.pretool_gate(self.payload(), self.db))

    def test_an_unresolvable_caller_is_allowed(self):
        """Fails open, like every other hook in this file: a session we cannot name is not
        one of ours, and a false deny costs a whole agent where a missed one costs an edit
        somebody can see in `git status`."""
        store.create_agent(self.db, name="top-1", role="orchestrator",
                           session_id="sess-1", is_top=True)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(
                hooks.pretool_gate(self.payload(session_id="somebody-else"), self.db))


class SpawnCarriesTheHookTest(unittest.TestCase):
    def test_every_spawn_passes_the_settings_file_and_it_holds_both_hooks(self):
        """Wiring, in the one place every spawn and restore passes through.

        `--settings` merges into that session only and `--bare` is absent, which is what
        makes the hooks reach our agents and nobody else's sessions.
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
        start = body["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertTrue(start.split()[0].endswith("bin/sb-activity-hook"), start)
        # Both hooks name the same store explicitly, rather than resolving it from
        # wherever the agent happens to be standing when they fire.
        self.assertIn("--db", cmd)
        self.assertIn("--db", start)


if __name__ == "__main__":
    unittest.main()
