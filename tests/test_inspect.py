"""Inspect and wait tests.

`sb inspect` is the whole join at one agent's width, so the tests care about two things:
that it gathers every fact somebody would otherwise have written python to dig out, and
that it never mutates anything while doing it.

`sb wait` is tested for the property that motivated it: it must block IN HERDR, not poll
the store. The fake herdr counts its own calls and the tests assert on those counts, so a
regression to a store-polling loop fails here rather than in production at 200 reads a
second.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import herdr as herdr_mod, status, store  # noqa: E402
from switchboard.herdr import Agent, HerdrError  # noqa: E402
from switchboard.output import PANE, TRANSCRIPT, UNAVAILABLE  # noqa: E402


class FakeHerdr:
    """`agent list` plus a pane read — everything inspect touches."""

    def __init__(self, agents=(), pane_text="", pane_error=None):
        self.agents = list(agents)
        self.pane_text = pane_text
        self.pane_error = pane_error
        self.reads: list[tuple[str, int]] = []

    def list_agents(self):
        return list(self.agents)

    def get_agent(self, name):
        return next((a for a in self.agents if a.name == name), None)

    def read_pane(self, pane_id, *, lines=100):
        self.reads.append((pane_id, lines))
        if self.pane_error:
            raise self.pane_error
        return self.pane_text


def alive(name, state="working", seq=1):
    return Agent(name=name, pane_id=f"w1:{name}", state=state, change_seq=seq)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = store.connect(path=self.root / "state.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


class InspectTest(Base):
    def agent(self, name="w1", **fields):
        fields.setdefault("role", "worker")
        return store.create_agent(self.db, name=name, **fields)

    def inspect(self, name="w1", h=None, **kw):
        # A moment on, past `status.STALLED_FLOOR`: a row read in the second it was
        # written has just ended a turn and is excused rather than stalled, and every
        # test here about a stall would agree for that reason instead of its own.
        kw.setdefault("now", store.now() + int(status.STALLED_FLOOR) + 1)
        return status.inspect(self.db, h or FakeHerdr([alive(name)]), name, **kw)

    # -- the facts --------------------------------------------------------

    def test_carries_the_task_which_is_the_question_people_actually_have(self):
        self.agent(task="rewrite the parser")
        self.assertEqual(self.inspect().agent.task, "rewrite the parser")

    def test_reports_drift_exactly_as_status_does(self):
        """One rule for stalled, in one place — or two readouts disagree about reality."""
        self.agent(session_id="s1")     # past its spawn, as above
        d = self.inspect(h=FakeHerdr([alive("w1", "idle")]))
        self.assertTrue(d.agent.stalled)
        self.assertEqual(d.agent.state, "working")
        self.assertEqual(d.agent.herdr_state, "idle")

    def test_an_agent_herdr_has_never_heard_of_is_gone_not_an_error(self):
        self.agent(session_id="s1")     # past its spawn; a session-less row this young
        d = self.inspect(h=FakeHerdr([]))   # would be a claim, and claims are not reaped
        self.assertTrue(d.agent.gone)

    def test_unknown_agent_is_loud(self):
        with self.assertRaises(KeyError):
            self.inspect("nobody")

    def test_recent_events_are_oldest_first(self):
        self.agent()
        for k in ("delegate", "herdr", "done"):
            store.log_event(self.db, kind=k, agent="w1")
        store.log_event(self.db, kind="other", agent="w2")
        d = self.inspect()
        self.assertEqual([e["kind"] for e in d.events], ["delegate", "herdr", "done"])

    def test_events_are_limited_to_the_tail(self):
        self.agent()
        for i in range(30):
            store.log_event(self.db, kind=f"e{i}", agent="w1")
        d = self.inspect(events=5)
        self.assertEqual([e["kind"] for e in d.events],
                         ["e25", "e26", "e27", "e28", "e29"])

    def test_the_last_done_summary_is_shown(self):
        self.agent()
        store.put_message(self.db, from_agent="w1", to_agent="main", kind="done",
                          body="[done] shipped the parser")
        store.set_state(self.db, "w1", "done")
        d = self.inspect()
        self.assertEqual(d.agent.summary, "shipped the parser")   # prefix is not the reader's problem
        self.assertIn("shipped the parser", status.render_detail(d))

    # -- mail: the part that used to need hand-written python -------------

    def test_unread_mail_is_listed_not_just_counted(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell",
                          body="use the other library")
        d = self.inspect()
        self.assertEqual(d.agent.unread, 1)
        self.assertEqual(d.unread[0]["from"], "main")
        self.assertIn("use the other library", d.unread[0]["body"])

    def test_an_old_ask_row_renders_as_ordinary_mail_and_gets_no_panel(self):
        """`sb ask` is gone, so the two "unanswered" panels went with it — but a store
        written before the deletion still holds `kind='ask'` rows, and inspecting the
        agent they belong to must neither crash nor claim somebody is blocked on it."""
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="ask",
                          body="which database?")
        d = self.inspect()
        self.assertEqual(d.agent.unread, 1)
        self.assertEqual(d.unread[0]["kind"], "ask")
        out = status.render_detail(d)
        self.assertIn("which database?", out)              # still readable
        self.assertNotIn("UNANSWERED ASK", out)
        self.assertNotIn("IT IS WAITING ON", out)
        self.assertFalse(hasattr(d, "owed"))

    def test_undelivered_mail_is_listed_apart_from_unread(self):
        """Two different failures: one we caused, one the agent did."""
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell",
                          body="rung about this one")
        store.mark_delivered(self.db, "w1")
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell",
                          body="never announced")
        d = self.inspect()
        self.assertEqual([m["body"] for m in d.undelivered], ["never announced"])
        self.assertEqual(len(d.unread), 2)              # both are unread
        self.assertEqual(d.agent.undelivered, 1)
        out = status.render_detail(d)
        self.assertIn("UNDELIVERED", out)
        self.assertIn("never announced", out)
        # Listed once, under the heading that explains why it is unread — not again under
        # "not picked up", which would contradict it.
        self.assertEqual(out.count("never announced"), 2)   # the heading and the body
        self.assertIn("MAIL — 1 unread, announced and not picked up", out)

    def test_mail_never_announced_is_not_also_listed_as_ignored(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="a")
        out = status.render_detail(self.inspect())
        self.assertIn("UNDELIVERED", out)
        self.assertNotIn("not picked up", out)          # there is nothing it ignored

    def test_a_blocked_agent_is_told_its_mail_waits_on_the_human_not_on_idle(self):
        """Same branch as `sb status`, because it is the same held mail.

        `_ring` holds a blocked agent's mail on `_is_blocked` until a `tell` from the
        human specifically. "Released when it goes idle" describes a path this agent no
        longer takes at all — `block` stopped reporting herdr state.
        """
        self.agent()
        store.set_state(self.db, "w1", "blocked")
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="a")
        out = status.render_detail(self.inspect(h=FakeHerdr([alive("w1", "idle")])))
        self.assertIn("held until the human", out)
        self.assertNotIn("released when it", out)

    def test_no_undelivered_section_when_everything_was_announced(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="a")
        store.mark_delivered(self.db, "w1")
        d = self.inspect()
        self.assertEqual(d.undelivered, [])
        self.assertNotIn("UNDELIVERED", status.render_detail(d))

    def test_inspecting_never_delivers_the_mail_it_reports(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="a")
        self.inspect()
        self.inspect()
        self.assertEqual(len(store.undelivered(self.db, exclude=["human"])), 1)

    def test_undelivered_is_in_the_json_as_both_a_count_and_the_bodies(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="hi")
        d = json.loads(json.dumps(self.inspect().as_dict()))
        self.assertEqual(d["undelivered"], 1)                       # the board's number
        self.assertEqual(d["undelivered_mail"][0]["body"], "hi")    # and the message
        self.assertTrue(d["waiting_to_be_rung"])

    # -- the terminal, via output.py --------------------------------------

    def test_the_live_pane_is_included(self):
        self.agent(pane_id="w1:p9")
        h = FakeHerdr([alive("w1")], pane_text="Traceback: boom\n")
        d = status.inspect(self.db, h, "w1")
        self.assertEqual(d.output.source, PANE)
        self.assertIn("boom", d.output.text)
        self.assertEqual(h.reads, [("w1:p9", 100)])

    def test_a_closed_pane_falls_back_to_the_transcript(self):
        """output.py's whole point, and it must survive being called from here."""
        home = self.root / "home"
        cwd = self.root / "work"
        cwd.mkdir()
        d = home / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))
        d.mkdir(parents=True)
        (d / "sess-1.jsonl").write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "I cannot build this."}]},
        }) + "\n")
        self.agent(pane_id="w1:p9", session_id="sess-1", cwd=str(cwd))
        h = FakeHerdr([alive("w1")],
                      pane_error=HerdrError("pane_not_found", "no such pane"))
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            got = status.inspect(self.db, h, "w1")
        self.assertEqual(got.output.source, TRANSCRIPT)
        self.assertIn("I cannot build this.", got.output.text)
        self.assertIn("pane_not_found", got.output.detail)   # provenance, never silent
        self.assertTrue(got.transcript.endswith("sess-1.jsonl"))

    def test_a_long_message_still_reaches_the_human_through_the_chat(self):
        """The capability the short `sb block` reason must not cost anyone.

        `validate.reason` caps the `why` at one line, so this is the path that has to carry
        a full question: the agent writes it in its own chat, blocks with a one-line note,
        and the human reads the chat here — every paragraph of it, with the reason only
        marking the row. Asserted end to end rather than trusted, because if this failed the
        cap would be taking a capability away instead of moving it.
        """
        message = ("Need human input: the audit found three ways the spawn path drops a "
                   "prompt.\n\n"
                   "1. Fix spawn before the prompts? Recommended: yes.\n"
                   "2. Ship the prompt rewrite anyway? Recommended: no.\n\n"
                   "Detail is in the 2026-08-09 CONSOLIDATED.md write-up.")
        self.agent(pane_id="w1:p9")
        store.set_state(self.db, "w1", "blocked")
        store.log_event(self.db, kind="blocked", agent="w1", why="need a decision on spawn")
        h = FakeHerdr([alive("w1", "idle")], pane_text=message + "\n")
        d = status.inspect(self.db, h, "w1", lines=100)
        self.assertEqual(d.agent.blocked_why, "need a decision on spawn")   # the row
        for part in ("Need human input", "Recommended: yes", "Recommended: no",
                     "CONSOLIDATED.md"):
            self.assertIn(part, d.output.text)                              # the message
        self.assertIn("Recommended: yes", status.render_detail(d))

    def test_no_terminal_anywhere_is_reported_not_hidden(self):
        self.agent()
        d = self.inspect()
        self.assertEqual(d.output.source, UNAVAILABLE)
        self.assertIn("no pane recorded", d.output.detail)

    def test_this_calls_own_read_event_is_not_reported_back_at_you(self):
        self.agent(pane_id="w1:p9")
        d = status.inspect(self.db, FakeHerdr([alive("w1")], pane_text="hi\n"), "w1")
        self.assertNotIn("read_output", [e["kind"] for e in d.events])

    # -- reading never mutates --------------------------------------------

    def test_inspecting_never_consumes_mail(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="a")
        self.inspect()
        self.inspect()
        self.assertEqual(len(store.unread_for(self.db, "w1", mark=False)), 1)

    # -- json --------------------------------------------------------------

    def test_json_carries_the_same_facts(self):
        self.agent(task="rewrite the parser", workspace="feature-x", pane_id="w1:p9",
                   cwd="/repo", session_id="sess-1", parent=None)
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell", body="q?")
        store.log_event(self.db, kind="delegate", agent="w1")
        h = FakeHerdr([alive("w1", "idle")], pane_text="on screen\n")
        d = json.loads(json.dumps(status.inspect(
            self.db, h, "w1",
            now=store.now() + int(status.STALLED_FLOOR) + 1).as_dict()))

        self.assertEqual(d["name"], "w1")
        self.assertEqual(d["task"], "rewrite the parser")
        self.assertEqual(d["state"], "working")
        self.assertEqual(d["herdr_state"], "idle")
        self.assertTrue(d["stalled"])
        self.assertEqual(d["workspace"], "feature-x")
        self.assertEqual(d["cwd"], "/repo")
        self.assertEqual(d["pane_id"], "w1:p9")
        self.assertEqual(d["session_id"], "sess-1")
        # The COUNT keeps the name it has on the board; the bodies get their own key. One
        # key that is a number in `sb status --json` and a list in `sb inspect --json` is
        # a trap for anything reading both.
        self.assertEqual(d["unread"], 1)
        self.assertEqual(d["unread_mail"][0]["body"], "q?")
        self.assertEqual([e["kind"] for e in d["events"]], ["delegate"])
        self.assertEqual(d["output"]["source"], PANE)
        self.assertIn("on screen", d["output"]["text"])

    # -- render ------------------------------------------------------------

    def test_render_shows_every_field_somebody_would_have_dug_out_by_hand(self):
        self.agent(task="rewrite the parser", workspace="feature-x", pane_id="w1:p9",
                   cwd="/repo", session_id="sess-1")
        store.log_event(self.db, kind="delegate", agent="w1")
        out = status.render_detail(
            status.inspect(self.db, FakeHerdr([alive("w1")], pane_text="on screen\n"), "w1"))
        for expected in ("w1", "worker", "rewrite the parser", "feature-x", "/repo",
                         "w1:p9", "sess-1", "delegate", "on screen"):
            self.assertIn(expected, out)

    def test_render_survives_an_agent_with_nothing_recorded(self):
        self.agent()
        out = status.render_detail(self.inspect())
        self.assertIn("w1", out)
        self.assertIn("(none recorded)", out)               # no task, and it says so


class CliTest(unittest.TestCase):
    def parse(self, argv):
        from switchboard.cli import build_parser
        return build_parser().parse_args(argv)

    def refused(self, argv):
        """argparse prints its usage to stderr on the way out; not worth reading here."""
        with open(os.devnull, "w") as null, mock.patch("sys.stderr", null):
            with self.assertRaises(SystemExit):
                self.parse(argv)

    def test_output_is_gone_as_a_verb(self):
        """One command answers 'what is going on with this agent', not two halves of it."""
        self.refused(["output", "w1"])

    def test_wait_is_gone_as_a_verb(self):
        """DESIGN-TRUTH.md: "There is `tell` only. No agent ever waits on another agent." An agent ends its turn
        and is poked when a child reports; a human reads the board."""
        self.refused(["wait", "w1"])


if __name__ == "__main__":
    unittest.main()
