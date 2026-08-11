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

    def read_pane(self, pane_id, *, lines=40):
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
        return status.inspect(self.db, h or FakeHerdr([alive(name)]), name, **kw)

    # -- the facts --------------------------------------------------------

    def test_carries_the_task_which_is_the_question_people_actually_have(self):
        self.agent(task="rewrite the parser")
        self.assertEqual(self.inspect().agent.task, "rewrite the parser")

    def test_carries_where_the_agent_lives(self):
        self.agent(workspace="feature-x", cwd="/repo/feature-x", pane_id="w1:p9",
                   session_id="sess-1", terminal_id="t7")
        d = self.inspect()
        self.assertEqual(d.agent.workspace, "feature-x")
        self.assertEqual(d.cwd, "/repo/feature-x")
        self.assertEqual(d.pane_id, "w1:p9")
        self.assertEqual(d.session_id, "sess-1")
        self.assertEqual(d.terminal_id, "t7")

    def test_reports_drift_exactly_as_status_does(self):
        """One rule for stalled, in one place — or two readouts disagree about reality."""
        self.agent()
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

    def test_the_latest_summary_wins(self):
        self.agent()
        for s in ("first", "second"):
            store.put_message(self.db, from_agent="w1", to_agent="main", kind="done",
                              body=f"[done] {s}")
        self.assertEqual(self.inspect().agent.summary, "second")

    # -- mail: the part that used to need hand-written python -------------

    def test_unread_mail_is_listed_not_just_counted(self):
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="tell",
                          body="use the other library")
        d = self.inspect()
        self.assertEqual(d.agent.unread, 1)
        self.assertEqual(d.unread[0]["from"], "main")
        self.assertIn("use the other library", d.unread[0]["body"])

    def test_an_unanswered_ask_is_surfaced_even_after_it_was_read(self):
        """The dangerous one: read and never answered LOOKS handled, and is not."""
        self.agent()
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="ask",
                          body="which database?")
        store.unread_for(self.db, "w1")                    # the agent read it
        d = self.inspect()
        self.assertEqual(d.agent.unread, 0)                # nothing in the mailbox
        self.assertEqual(len(d.owed), 1)                   # but somebody is still stuck
        self.assertEqual(d.owed[0]["from"], "main")
        self.assertTrue(d.owed[0]["read"])
        out = status.render_detail(d)
        self.assertIn("UNANSWERED ASK", out)
        self.assertIn("which database?", out)

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

    def test_an_answered_ask_is_not_surfaced(self):
        self.agent()
        mid = store.put_message(self.db, from_agent="main", to_agent="w1", kind="ask",
                                body="which database?")
        store.put_message(self.db, from_agent="w1", to_agent="main", kind="tell",
                          body="postgres", reply_to=mid)
        self.assertEqual(self.inspect().owed, [])

    def test_what_the_agent_itself_is_waiting_on_is_kept_separate(self):
        """Opposite meanings: one is somebody stuck on it, one is it stuck on somebody."""
        self.agent()
        store.put_message(self.db, from_agent="w1", to_agent="main", kind="ask",
                          body="may I force-push?")
        d = self.inspect()
        self.assertEqual(d.owed, [])
        self.assertEqual(len(d.waiting_on), 1)
        self.assertEqual(d.waiting_on[0]["to"], "main")
        self.assertIn("IT IS WAITING ON", status.render_detail(d))

    # -- the terminal, via output.py --------------------------------------

    def test_the_live_pane_is_included(self):
        self.agent(pane_id="w1:p9")
        h = FakeHerdr([alive("w1")], pane_text="Traceback: boom\n")
        d = status.inspect(self.db, h, "w1")
        self.assertEqual(d.output.source, PANE)
        self.assertIn("boom", d.output.text)
        self.assertEqual(h.reads, [("w1:p9", 40)])

    def test_the_line_count_reaches_the_reader(self):
        self.agent(pane_id="w1:p9")
        h = FakeHerdr([alive("w1")], pane_text="x\n")
        status.inspect(self.db, h, "w1", lines=120)
        self.assertEqual(h.reads, [("w1:p9", 120)])

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
                   "Detail is in audit/2026-08-09/CONSOLIDATED.md.")
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

    def test_inspecting_never_repairs_drift(self):
        self.agent()
        status.inspect(self.db, FakeHerdr([alive("w1", "idle")]), "w1")
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "working")

    # -- json --------------------------------------------------------------

    def test_json_carries_the_same_facts(self):
        self.agent(task="rewrite the parser", workspace="feature-x", pane_id="w1:p9",
                   cwd="/repo", session_id="sess-1", parent=None)
        store.put_message(self.db, from_agent="main", to_agent="w1", kind="ask", body="q?")
        store.log_event(self.db, kind="delegate", agent="w1")
        h = FakeHerdr([alive("w1", "idle")], pane_text="on screen\n")
        d = json.loads(json.dumps(status.inspect(self.db, h, "w1").as_dict()))

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
        self.assertEqual(d["owed"][0]["from"], "main")
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

    def test_render_names_drift_here_too(self):
        self.agent()
        out = status.render_detail(
            status.inspect(self.db, FakeHerdr([alive("w1", "idle")]), "w1"))
        self.assertIn("STALLED", out)

    def test_render_survives_an_agent_with_nothing_recorded(self):
        self.agent()
        out = status.render_detail(self.inspect())
        self.assertIn("w1", out)
        self.assertIn("(none recorded)", out)               # no task, and it says so


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------


class WaitHerdr:
    """A herdr whose `wait` really blocks — represented as a scripted list of wake-ups.

    Each entry is either an Agent (herdr announced a state change) or a HerdrError (the
    wait ran its slice out and nothing happened). `on_wake` fires just before each one is
    handed back, which is how a test makes the store change *while* we are blocked.
    """

    def __init__(self, current, wakeups=(), on_wake=None):
        self.current = current
        self.wakeups = list(wakeups)
        self.on_wake = on_wake or (lambda i: None)
        self.waits: list[dict] = []
        self.lists = 0

    def get_agent(self, name):
        self.lists += 1
        return self.current

    def wait(self, name, *, until="idle", since_seq=None, timeout_ms=0):
        i = len(self.waits)
        self.waits.append({"name": name, "until": until,
                           "since_seq": since_seq, "timeout_ms": timeout_ms})
        self.on_wake(i)
        if i >= len(self.wakeups):
            raise HerdrError("wait_timeout", "nothing happened")
        got = self.wakeups[i]
        if isinstance(got, HerdrError):
            raise got
        self.current = got
        return got


class FakeClock:
    """Time only moves when a wait consumes it, so tests never actually sleep."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class WaitTest(Base):
    def agent(self, name="w1", **fields):
        fields.setdefault("role", "worker")
        return store.create_agent(self.db, name=name, **fields)

    # -- the point: no polling ---------------------------------------------

    def test_it_blocks_in_herdr_rather_than_polling_the_store(self):
        self.agent()
        clock = FakeClock()

        def done_while_we_are_blocked(i):
            clock.t += 5
            store.set_state(self.db, "w1", "done")

        h = WaitHerdr(alive("w1", "working", seq=7),
                      wakeups=[alive("w1", "idle", seq=8)],
                      on_wake=done_while_we_are_blocked)
        r = status.wait_for(self.db, h, "w1", clock=clock)
        self.assertTrue(r.ok)
        self.assertEqual(r.state, "done")
        self.assertEqual(len(h.waits), 1)          # ONE blocking call, not a poll loop

    def test_an_already_finished_agent_returns_without_waiting_at_all(self):
        self.agent()
        store.set_state(self.db, "w1", "done")
        h = WaitHerdr(alive("w1", "idle"))
        r = status.wait_for(self.db, h, "w1", clock=FakeClock())
        self.assertTrue(r.ok)
        self.assertEqual(h.waits, [])
        self.assertEqual(h.lists, 0)               # herdr is not even consulted

    def test_the_stale_wait_guard_is_used(self):
        """herdr's `agent wait` is not turn-scoped; without since_seq it returns instantly
        on a transition that happened before we ever asked."""
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "idle", seq=41), on_wake=lambda i: setattr(clock, "t", clock.t + 60))
        status.wait_for(self.db, h, "w1", timeout=90, clock=clock)
        self.assertEqual(h.waits[0]["since_seq"], 41)   # snapshotted BEFORE waiting

    def test_a_slice_that_expires_just_loops_and_re_reads_the_store(self):
        """The safety net for a herdr state write that was silently dropped."""
        self.agent()
        clock = FakeClock()

        def tick(i):
            clock.t += 30
            if i == 1:
                store.set_state(self.db, "w1", "done")   # no herdr change ever announced

        h = WaitHerdr(alive("w1", "working", seq=1), wakeups=[], on_wake=tick)
        r = status.wait_for(self.db, h, "w1", timeout=300, clock=clock)
        self.assertTrue(r.ok)
        self.assertEqual(len(h.waits), 2)
        self.assertLessEqual(h.waits[0]["timeout_ms"], status.WAIT_SLICE_MS)

    # -- outcomes -----------------------------------------------------------

    def test_timeout_is_reported_not_raised(self):
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "working", seq=1),
                      on_wake=lambda i: setattr(clock, "t", clock.t + 30))
        r = status.wait_for(self.db, h, "w1", timeout=60, clock=clock)
        self.assertFalse(r.ok)
        self.assertIn("timed out", r.reason)
        self.assertEqual(r.state, "working")
        self.assertIn("did not reach done", r.render())

    def test_finishing_the_other_way_stops_immediately(self):
        """Waiting out the full timeout on an agent that will never move again is a lie."""
        self.agent()
        clock = FakeClock()

        def fail_it(i):
            clock.t += 5
            store.set_state(self.db, "w1", "failed")

        h = WaitHerdr(alive("w1", "working", seq=1),
                      wakeups=[alive("w1", "idle", seq=2)], on_wake=fail_it)
        r = status.wait_for(self.db, h, "w1", timeout=900, clock=clock)
        self.assertFalse(r.ok)
        self.assertEqual(r.state, "failed")
        self.assertIn("finished as failed", r.reason)
        self.assertLess(clock.t, 1000 + 900)       # it did not sit out the timeout

    def test_an_agent_herdr_does_not_know_is_reported_at_once(self):
        self.agent()
        h = WaitHerdr(None)
        r = status.wait_for(self.db, h, "w1", clock=FakeClock())
        self.assertFalse(r.ok)
        self.assertIn("herdr does not know", r.reason)
        self.assertEqual(h.waits, [])

    def test_a_herdr_that_fails_instantly_does_not_spin(self):
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "working", seq=1),
                      wakeups=[HerdrError("connection_refused", "no server")])
        r = status.wait_for(self.db, h, "w1", timeout=900, clock=clock)
        self.assertFalse(r.ok)
        self.assertIn("connection_refused", r.reason)
        self.assertEqual(len(h.waits), 1)

    def test_unknown_agent_is_loud(self):
        with self.assertRaises(KeyError):
            status.wait_for(self.db, WaitHerdr(None), "nobody", clock=FakeClock())

    def test_an_impossible_target_state_is_refused_before_blocking(self):
        self.agent()
        with self.assertRaises(ValueError):
            status.wait_for(self.db, WaitHerdr(None), "w1", until="banana")

    # -- --for --------------------------------------------------------------

    def test_for_blocked_is_satisfied_by_the_store(self):
        self.agent()
        clock = FakeClock()

        def block_it(i):
            clock.t += 5
            store.set_state(self.db, "w1", "blocked")

        h = WaitHerdr(alive("w1", "working", seq=1),
                      wakeups=[alive("w1", "idle", seq=2)], on_wake=block_it)
        r = status.wait_for(self.db, h, "w1", until="blocked", clock=clock)
        self.assertTrue(r.ok)
        self.assertEqual(r.state, "blocked")

    def test_an_already_idle_agent_is_waited_toward_working_not_idle(self):
        """`agent wait --until idle` returns INSTANTLY on an idle agent, and the stale-wait
        guard then re-waits with no backoff — a spin, not a wait. See BUGS.md."""
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "idle", seq=3),
                      on_wake=lambda i: setattr(clock, "t", clock.t + 30))
        status.wait_for(self.db, h, "w1", timeout=40, clock=clock)
        self.assertEqual(h.waits[0]["until"], "working")

    def test_herdrs_derived_done_counts_as_already_idle_here_too(self):
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "done", seq=3),
                      on_wake=lambda i: setattr(clock, "t", clock.t + 30))
        status.wait_for(self.db, h, "w1", timeout=40, clock=clock)
        self.assertEqual(h.waits[0]["until"], "working")

    def test_a_working_agent_is_waited_toward_idle(self):
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "working", seq=3),
                      on_wake=lambda i: setattr(clock, "t", clock.t + 30))
        status.wait_for(self.db, h, "w1", timeout=40, clock=clock)
        self.assertEqual(h.waits[0]["until"], "idle")

    def test_the_transition_is_re_chosen_each_time_round(self):
        """idle → wait for working → working → wait for idle → the turn has ended."""
        self.agent()
        clock = FakeClock()

        def tick(i):
            clock.t += 5
            if i == 1:
                store.set_state(self.db, "w1", "done")

        h = WaitHerdr(alive("w1", "idle", seq=1),
                      wakeups=[alive("w1", "working", seq=2), alive("w1", "idle", seq=3)],
                      on_wake=tick)
        r = status.wait_for(self.db, h, "w1", timeout=300, clock=clock)
        self.assertTrue(r.ok)
        self.assertEqual([c["until"] for c in h.waits], ["working", "idle"])

    def test_for_done_never_succeeds_while_the_store_says_working(self):
        """The property behind the "`sb wait` returned success while it was still working"
        report in BUGS.md, which is not reproducible against this code.

        `--for done` is satisfied by ONE thing: the store saying `done`. Not by herdr going
        idle (that is `--for idle`), not by a state change, not by a wait slice expiring.
        A caller that proceeds early draws the whole `$SECONDS` class of false conclusion,
        so the property is pinned rather than left to inspection.
        """
        self.agent()
        clock = FakeClock()
        # herdr transitions all it likes; the store never moves.
        h = WaitHerdr(alive("w1", "working", seq=1),
                      wakeups=[alive("w1", "idle", seq=2), alive("w1", "working", seq=3),
                               alive("w1", "idle", seq=4)],
                      on_wake=lambda i: setattr(clock, "t", clock.t + 20))
        r = status.wait_for(self.db, h, "w1", until="done", timeout=60, clock=clock)
        self.assertFalse(r.ok)
        self.assertEqual(r.state, "working")
        self.assertIn("timed out", r.reason)

    def test_for_done_reports_failure_rather_than_success_on_a_failed_agent(self):
        """`failed` is finished, so waiting is over — but it is not what was asked for."""
        self.agent()
        store.set_state(self.db, "w1", "failed")
        r = status.wait_for(self.db, WaitHerdr(None), "w1", until="done", clock=FakeClock())
        self.assertFalse(r.ok)
        self.assertIn("finished as failed", r.reason)

    def test_only_one_herdr_state_is_ever_asked_for(self):
        """herdr 0.8.0 refuses `--until idle,blocked` — see BUGS.md. `Herdr.wait`
        takes one state for that reason, and this pins that nothing here hands it a
        collection that would silently comma-join back into the rejected form."""
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "working", seq=1),
                      on_wake=lambda i: setattr(clock, "t", clock.t + 30))
        for until in status.WAIT_STATES:
            h.waits.clear()
            status.wait_for(self.db, h, "w1", until=until, timeout=20, clock=clock)
            for call in h.waits:
                self.assertIsInstance(call["until"], str)
                self.assertIn(call["until"], herdr_mod.STATES, until)

    def test_for_idle_catches_an_agent_that_stalls_without_calling_done(self):
        """`done` never arrives, so only the herdr half can satisfy this one."""
        self.agent()
        clock = FakeClock()
        h = WaitHerdr(alive("w1", "working", seq=1),
                      wakeups=[alive("w1", "idle", seq=2)],
                      on_wake=lambda i: setattr(clock, "t", clock.t + 5))
        r = status.wait_for(self.db, h, "w1", until="idle", clock=clock)
        self.assertTrue(r.ok)
        self.assertEqual(r.state, "working")       # the store is reported, not rewritten
        self.assertEqual(r.herdr_state, "idle")

    def test_for_idle_is_satisfied_by_a_finished_agent_too(self):
        self.agent()
        store.set_state(self.db, "w1", "done")
        r = status.wait_for(self.db, WaitHerdr(None), "w1", until="idle", clock=FakeClock())
        self.assertTrue(r.ok)

    def test_waiting_for_working_watches_the_other_transition(self):
        self.agent()
        store.set_state(self.db, "w1", "blocked")
        clock = FakeClock()

        def unblock(i):
            clock.t += 5
            store.set_state(self.db, "w1", "working")

        h = WaitHerdr(alive("w1", "idle", seq=1), wakeups=[alive("w1", "working", seq=2)],
                      on_wake=unblock)
        r = status.wait_for(self.db, h, "w1", until="working", clock=clock)
        self.assertTrue(r.ok)
        self.assertEqual(h.waits[0]["until"], "working")

    def test_json_carries_the_outcome(self):
        self.agent()
        store.set_state(self.db, "w1", "done")
        d = json.loads(json.dumps(
            status.wait_for(self.db, WaitHerdr(None), "w1", clock=FakeClock()).as_dict()))
        self.assertTrue(d["ok"])
        self.assertEqual(d["until"], "done")
        self.assertEqual(d["state"], "done")
        self.assertIn("waited", d)


# ---------------------------------------------------------------------------
# the wiring
# ---------------------------------------------------------------------------


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

    def test_inspect_takes_a_name_and_a_line_count(self):
        args = self.parse(["inspect", "w1", "-n", "80"])
        self.assertEqual(args.name, "w1")
        self.assertEqual(args.n, 80)

    def test_inspect_json_on_either_side(self):
        self.assertTrue(self.parse(["inspect", "w1", "--json"]).json)
        self.assertTrue(self.parse(["--json", "inspect", "w1"]).json)

    def test_wait_defaults_to_done(self):
        args = self.parse(["wait", "w1"])
        self.assertEqual(args.until, "done")
        self.assertEqual(args.timeout, 900)

    def test_wait_takes_for_and_timeout(self):
        args = self.parse(["wait", "w1", "--for", "blocked", "--timeout", "30"])
        self.assertEqual(args.until, "blocked")
        self.assertEqual(args.timeout, 30)

    def test_wait_refuses_a_state_it_cannot_ever_see(self):
        self.refused(["wait", "w1", "--for", "banana"])

    def test_wait_says_in_its_help_that_it_is_not_for_agents(self):
        """The one verb an agent must never call, said where a misuser is looking."""
        from switchboard.cli import build_parser
        sub = build_parser()._subparsers._group_actions[0].choices["wait"]
        text = (sub.description or "") + (sub.format_help() or "")
        self.assertIn("Agents must NOT use this", text)
        self.assertIn("end your turn", text)


if __name__ == "__main__":
    unittest.main()
