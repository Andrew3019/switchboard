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
        or a person typing starts a fresh chain with the flag false, and the gate blocked
        the same agent a second time twelve seconds later. The store is what
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

    def test_an_agent_waiting_on_a_reply_it_asked_for_ends_its_turn(self):
        """The state that had no verb. `tell --needs-reply` says end your turn and be poked
        with the answer, and the gate used to demand a report there was nothing to make."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        store.create_agent(self.db, name="lead", role="lead")
        store.put_message(self.db, from_agent="w1", to_agent="lead", kind="tell",
                          body="which one?", needs_reply=True)
        self.assertIsNone(hooks.stop_gate(self.payload(), self.db))

    def test_the_answer_ends_the_excuse(self):
        """Any message back from whoever was asked, and the next silent end is a silence
        like any other — nothing here excuses a row for the rest of its life."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        store.create_agent(self.db, name="lead", role="lead")
        store.put_message(self.db, from_agent="w1", to_agent="lead", kind="tell",
                          body="which one?", needs_reply=True)
        store.put_message(self.db, from_agent="lead", to_agent="w1", kind="tell",
                          body="the second one")
        self.assertIsNotNone(hooks.stop_gate(self.payload(), self.db))

    def test_a_question_nobody_is_left_to_answer_excuses_nothing(self):
        """The recipient's `sb done` has landed, so no answer is coming and waiting on it
        is a silent finish like any other."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        store.create_agent(self.db, name="lead", role="lead")
        store.put_message(self.db, from_agent="w1", to_agent="lead", kind="tell",
                          body="which one?", needs_reply=True)
        store.set_state(self.db, "lead", "done")   # its `sb done` landed; no answer is coming
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
        Marking idle there would hand its held mail over mid-turn and put a working agent
        on the board as one whose turn ended without a report.
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
        """Logged against no agent, with the target in the payload.
        `status._last_activity` counts every event that NAMES an agent, and the idle clock
        it keeps is what says an agent has gone quiet at all — so an edge logged against
        the agent would let anything reading that clock see its own footprint as the agent
        having done something."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.start()
        rows = self.db.execute(
            "SELECT agent, payload FROM events WHERE kind='turn_start'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["agent"])
        self.assertIn("w1", rows[0]["payload"])


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


class CodexHookShapeTest(unittest.TestCase):
    """The other provider's wiring for the same two hooks.

    What is pinned here is that both events are wired, to the same two scripts, naming
    the same store explicitly — i.e. that the codex path cannot quietly lose one of them.
    What no test here can pin is that codex honours the block, which is why that half was
    proved live against the real binary instead (both hooks fired, with arguments, and
    the payload carried `stop_hook_active`).
    """

    def test_both_events_are_wired_to_the_same_scripts_and_store(self):
        cmds = hooks.codex_hook_commands()
        self.assertEqual(set(cmds), {"Stop", "UserPromptSubmit"})
        self.assertTrue(cmds["Stop"].split()[0].endswith("bin/sb-stop-hook"), cmds["Stop"])
        self.assertTrue(
            cmds["UserPromptSubmit"].split()[0].endswith("bin/sb-activity-hook"),
            cmds["UserPromptSubmit"])
        for c in cmds.values():
            self.assertIn("--db", c)
            self.assertIn(str(store.db_path()), c)

    def test_the_decision_is_shared_rather_than_a_second_gate(self):
        """The cap especially. It is defensive for Claude and MANDATORY for codex —
        openai/codex#37937 is an open unbounded-no-escape loop on a repeatedly blocking
        Stop hook — so a codex-specific gate that forgot it would be the bug. There is no
        codex gate to forget it in: `codex_hook_commands` wires the same scripts."""
        for name in ("stop_gate", "mark_turn", "run", "run_activity"):
            self.assertTrue(hasattr(hooks, name))
        self.assertFalse([n for n in dir(hooks) if n.startswith("codex_") and n != "codex_hook_commands"])


if __name__ == "__main__":
    unittest.main()
