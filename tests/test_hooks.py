"""The two turn edges — the activity signal.

There WAS a Stop gate here, refusing the end of a turn nobody had reported, with a cap and
four waivers. It is gone (#325): a silent finish is a passive reading on the board now, and
nothing speaks to the agent about it. What is left is the signal (`agents.turn`): the two
edges, and the one thing `run` may still return.

What a test can pin here is the WRITE (a real store, real rows) and the fact that every
spawn carries the settings file. What it cannot pin is that Claude fires the events at all,
so that half is proved live, in an isolated clone.
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


class StopHookNeverBlocksTest(unittest.TestCase):
    """The enforcement is gone, and this is what took its place: nothing.

    The gate used to answer `{"decision": "block", "reason": …}` for a turn that ended with
    nothing reported, and four waivers existed only to decide when not to. Every one of
    those shapes is here, and every one of them ends its turn.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.db = store.connect(path=self.path)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def payload(self, **kw):
        return {"session_id": "sess-1", "hook_event_name": "Stop", **kw}

    def stop(self, **kw):
        return hooks.run(json.dumps(self.payload(**kw)), db_path=self.path)

    def test_a_silent_finish_ends_its_turn_and_is_told_nothing(self):
        """THE removal. An agent that ends a turn having reported nothing simply ends; its
        silence surfaces on the board (`status` draws it STALLED) rather than being argued
        with in its own pane."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.assertEqual(self.stop(), {})
        self.assertEqual(store.get_agent(self.db, "w1")["turn"], store.TURN_IDLE)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) c FROM events WHERE kind LIKE 'stop_gate%'").fetchone()["c"], 0)

    def test_every_shape_the_waivers_existed_for_ends_the_same_way(self):
        """The four waivers are gone because there is no decision left to waive."""
        store.create_agent(self.db, name="lead", role="lead")
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1",
                           parent="lead")
        store.put_message(self.db, from_agent="w1", to_agent="lead", kind="tell",
                          body="which one?", needs_reply=True)
        store.set_wait(self.db, "w1", "background")
        self.assertEqual(self.stop(), {})
        self.assertEqual(self.stop(stop_hook_active=True), {})

    def test_the_gate_is_not_importable_any_more(self):
        """Named rather than left to a grep: the verb it offered (`sb block`) is gone too,
        so a reader reaching for the gate is reaching for both halves of a removed design."""
        for gone in ("stop_gate", "BLOCK_REASON", "REPORTED", "_already_nudged",
                     "_has_live_child", "_awaiting_reply", "_explicit_wait"):
            self.assertFalse(hasattr(hooks, gone), gone)


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

    def test_an_agent_with_an_open_question_has_ended_its_turn(self):
        """Asking a person is not a state and does not stop anything: the row stays
        `working`, the turn edge says the turn ended, and the open Question is what says it
        is waiting. All three are true at once and they answer different questions."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        self.start()
        store.create_question(self.db, asker="w1", target=store.Q_HUMAN, body="which one?")
        self.assertEqual(self.stop(), {})
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "working")
        self.assertEqual(self.turn(), store.TURN_IDLE)

    def test_a_new_turn_leaves_the_terminal_state_column_untouched(self):
        """The STATE-column bug Andrew reported is fixed at the READING (see
        `AgentStatus.display_state`), not by rewriting `state`: a `done` row spoken to keeps
        `state='done'` in the store — so `stop_gate` still sees the report and `sb cleanup`
        still closes it — while the board reads it as `working` off the live turn edge. This
        pins the half that lives here: the turn edge is written and the terminal word is
        left alone."""
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")
        store.set_state(self.db, "w1", "done")               # the report landed; turn ended
        hooks.run_activity(json.dumps(self.payload()), db_path=self.path)  # spoken to again
        row = store.get_agent(self.db, "w1")
        self.assertEqual(row["state"], "done")               # the self-report is untouched
        self.assertEqual(row["turn"], store.TURN_WORKING)    # but the turn edge says working

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
    def test_every_spawn_passes_the_settings_file_and_it_holds_all_claude_hooks(self):
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
        failure = body["hooks"]["StopFailure"][0]
        self.assertEqual(failure["matcher"], "rate_limit")
        limit = failure["hooks"][0]["command"]
        self.assertTrue(limit.split()[0].endswith("bin/sb-usage-limit-hook"), limit)
        # Every hook names the same store explicitly, rather than resolving it from
        # wherever the agent happens to be standing when they fire.
        self.assertIn("--db", cmd)
        self.assertIn("--db", start)
        self.assertIn("--db", limit)


class UsageLimitStopFailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.transcript = Path(self.tmp.name) / "session.jsonl"
        self.db = store.connect(path=self.path)
        store.create_agent(self.db, name="w1", role="worker", session_id="sess-1")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def payload(self, error="rate_limit"):
        return {
            "session_id": "sess-1",
            "hook_event_name": "StopFailure",
            "error": error,
            "transcript_path": str(self.transcript),
        }

    def write_limit(self, kind="five_hour", reset_at=1788044400):
        record = {
            "type": "assistant",
            "quotaLimits": {"resetsAt": reset_at, "rateLimitType": kind},
            "error": "rate_limit",
            "isApiErrorMessage": True,
        }
        self.transcript.write_text(json.dumps({"type": "user"}) + "\n" +
                                   json.dumps(record) + "\n")

    def test_five_hour_limit_is_persisted_and_logged(self):
        self.write_limit()
        hooks.run_usage_limit(json.dumps(self.payload()), db_path=self.path)
        row = store.get_agent(self.db, "w1")
        self.assertEqual(row["usage_limit_reset_at"], 1788044400)
        event = self.db.execute(
            "SELECT kind, payload FROM events WHERE agent='w1' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(event["kind"], "usage_limit_recorded")
        self.assertEqual(json.loads(event["payload"])["rate_limit_type"], "five_hour")

    def test_weekly_limit_is_ignored_entirely(self):
        self.write_limit(kind="seven_day")
        hooks.run_usage_limit(json.dumps(self.payload()), db_path=self.path)
        self.assertIsNone(store.get_agent(self.db, "w1")["usage_limit_reset_at"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM events WHERE kind='usage_limit_recorded'"
        ).fetchone()[0], 0)

    def test_non_rate_limit_stop_failure_is_ignored(self):
        self.write_limit()
        hooks.run_usage_limit(json.dumps(self.payload(error="overloaded")), db_path=self.path)
        self.assertIsNone(store.get_agent(self.db, "w1")["usage_limit_reset_at"])


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
        """openai/codex#37937 is an open unbounded-no-escape loop on a repeatedly blocking
        Stop hook, and nothing here can meet it any more: `run` returns `{}` unconditionally
        and `codex_hook_commands` wires the same scripts rather than a gate of its own."""
        for name in ("mark_turn", "run", "run_activity"):
            self.assertTrue(hasattr(hooks, name))
        self.assertFalse([n for n in dir(hooks) if n.startswith("codex_") and n != "codex_hook_commands"])


if __name__ == "__main__":
    unittest.main()
