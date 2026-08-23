"""Status tests — the join between the store and herdr.

The store half is real (a temp database); the herdr half is a fake `agent list`, because
every case worth testing here is "what happens when the two disagree".
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import cli as cli_mod, config  # noqa: E402
from switchboard import herdr as herdr_mod, status, store  # noqa: E402
from switchboard.herdr import Agent, Herdr, HerdrError  # noqa: E402


class FakeHerdr:
    """Just enough herdr to answer `agent list`, and a counter to prove we call it once."""

    def __init__(self, agents=(), error=None):
        self.agents = list(agents)
        self.error = error
        self.calls = 0

    def list_agents(self):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.agents)


def alive(name, state="working", session="", terminal=""):
    return Agent(name=name, pane_id=f"w1:{name}", state=state, session_id=session,
                 terminal_id=terminal)


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def by_name(self, snap):
        return {a.name: a for a in snap.agents}

    def past_the_floor(self, seconds=1):
        """`now`, far enough on that an idle row's idleness MEANS something. -> epoch.

        `status.STALLED_FLOOR` is the floor under every stall, so a row built in this
        second is a row that has this instant ended a turn: excused, not stalled. Every
        test below about a REAL stall says so with this, and the clock moves rather than
        the store so nothing else on the row reads differently than it otherwise would.
        """
        return store.now() + int(status.STALLED_FLOOR) + seconds

    def confirm_gone(self, h=None, *, at=None):
        """Collect twice, a confirmation window apart — what it now takes to record a death.

        One absent reading only remembers the absence (see `status._confirmed_gone`), so a
        test about what gets WRITTEN has to look twice, with the clock moved on in between.
        Anything asserting on the flag rather than on the row wants one plain `collect`.
        """
        h = FakeHerdr([]) if h is None else h
        at = store.now() if at is None else at
        status.collect(self.db, h, now=at)
        return status.collect(self.db, h, now=at + int(status.GONE_CONFIRM_GRACE) + 1)

    # -- drift: the reason this module exists ----------------------------

    def test_working_in_the_store_but_idle_in_herdr_is_stalled(self):
        # `session_id` is what says this one has taken a turn at all: a session-less row
        # this young has not started yet, and is held off (see the stall-grace tests).
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                              now=self.past_the_floor())
        a = self.by_name(snap)["w1"]
        self.assertTrue(a.stalled)
        self.assertEqual(a.state, "working")      # the store is reported, not rewritten
        self.assertEqual(a.herdr_state, "idle")

    def test_a_lead_waiting_on_a_live_child_is_idle_but_not_stalled(self):
        """The exemption the stop gate and the reconciler already apply, read one step
        earlier so the board agrees with them: an orchestrator that ended its turn because
        the protocol told it to and is waiting to be poked is idle WITH a reason. It goes
        back to stalled the moment nothing of its own is running."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2")
        h = FakeHerdr([alive("lead", "idle"), alive("w1", "working")])
        at = self.past_the_floor()
        lead = self.by_name(status.collect(self.db, h, now=at))["lead"]
        self.assertFalse(lead.stalled)
        self.assertFalse(lead.needs_human)
        self.assertEqual(lead.display_state, "idle")

        store.set_state(self.db, "w1", "done")
        lead = self.by_name(status.collect(self.db, h, now=at))["lead"]
        self.assertTrue(lead.stalled)
        self.assertEqual(lead.display_state, "idle")   # never `working` beside a stall

    def test_herdrs_derived_done_counts_as_idle(self):
        """herdr shows `done` for idle-and-unviewed; missing that hides real drift."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "done")]),
                              now=self.past_the_floor())
        self.assertTrue(self.by_name(snap)["w1"].stalled)

    def test_drift_is_not_repaired(self):
        """Marking it done here would fabricate a summary its parent never got."""
        store.create_agent(self.db, name="w1", role="worker")
        status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "working")

    # -- drift in the mailbox: written, never announced --------------------

    def test_mail_never_announced_is_counted_apart_from_mail_ignored(self):
        """Unread means we rang and it has not looked. Undelivered is the subset it was
        never told about and has not read either — invisible from inside the agent, with
        nothing on its screen and nothing in its context, so it can sit forever."""
        store.create_agent(self.db, name="w1", role="worker")
        mid = store.put_message(self.db, from_agent="human", to_agent="w1",
                                kind="tell", body="hello")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "working")]))
        a = self.by_name(snap)["w1"]
        self.assertEqual((a.unread, a.undelivered), (1, 1))
        self.assertTrue(a.waiting_to_be_rung)
        self.assertTrue(a.needs_human)

        store.mark_delivered(self.db, "w1")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "working")])))["w1"]
        self.assertEqual((a.unread, a.undelivered), (1, 0))   # rung; now it is the agent's
        self.assertFalse(a.waiting_to_be_rung)
        self.assertIsNotNone(mid)

    def test_a_row_addressed_to_the_human_is_never_undelivered(self):
        """Nothing is addressed to a person any more, but old stores still hold such rows.

        They must not become a permanent UNDELIVERED warning: there is no doorbell to ring
        and nobody the mail was ever going to reach.
        """
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="w1", to_agent="human",
                          kind="tell", body="which branch?")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "working")]))
        self.assertEqual(snap.counts["undelivered"], 0)
        self.assertEqual(snap.counts["unread"], 0)      # a person holds no unread either

    def test_undelivered_age_is_the_oldest_not_the_newest(self):
        """How long mail has been stranded is the question; the newest one cannot say."""
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="human", to_agent="w1", kind="tell", body="a")
        store.put_message(self.db, from_agent="human", to_agent="w1", kind="tell", body="b")
        now = store.now()
        self.db.execute("UPDATE messages SET created_at=? WHERE body='a'", (now - 600,))
        self.db.commit()
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "working")]),
                                        now=now))["w1"]
        self.assertEqual(a.undelivered, 2)
        self.assertGreaterEqual(a.undelivered_age, 600)

    # -- our own signal, and where herdr is still asked ---------------------
    #
    # `agents.turn` is written by the hooks in `hooks.py` at the two edges of a turn. These
    # are the join, not the hooks: the write is pinned in `test_hooks.py` and the fact that
    # Claude Code fires the events is proved live, in an isolated clone.

    def test_our_signal_outranks_herdrs_reading_in_both_directions(self):
        """The bug this exists for, and its mirror.

        herdr infers a running turn from Claude's spinner glyphs; 2.1.228 changed them and
        every pane on the machine read `idle`, including agents mid-tool-call. An agent
        whose turn we KNOW is running is working, whatever the screen looks like — and an
        agent whose turn we know has ended is stalled even while herdr insists otherwise.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))["w1"]
        self.assertFalse(a.stalled)
        self.assertEqual(a.display_state, "working")

        store.set_turn(self.db, "w1", store.TURN_IDLE)
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "working")]),
                                        now=self.past_the_floor()))["w1"]
        self.assertTrue(a.stalled)
        self.assertEqual(a.display_state, "idle")

    def test_a_long_tool_call_never_reads_idle(self):
        """No N, and this is why the design needs none. The longest tool call in this
        repo's history ran 18 minutes; a turn that started and has not ended reads
        `working` for however long it runs, with nothing to tune."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)
        now = store.now() + 3600
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                        now=now))["w1"]
        self.assertGreaterEqual(a.idle, 3600)
        self.assertFalse(a.stalled)
        self.assertFalse(a.signal_drift)
        self.assertEqual(a.display_state, "working")

    def test_a_row_with_no_signal_of_ours_still_reads_herdr(self):
        """The fallback, and it is the whole compatibility story: a row predating the
        column, an agent nobody spawned with our settings file, or one freshly restored
        behaves exactly as it did before any of this existed."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.assertIsNone(store.get_agent(self.db, "w1")["turn"])
        at = self.past_the_floor()
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                        now=at))["w1"]
        self.assertTrue(a.stalled)
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "working")]),
                                        now=at))["w1"]
        self.assertFalse(a.stalled)

    def test_a_session_that_died_mid_turn_is_surfaced_not_left_working(self):
        """The failure mode the signal introduces: no `Stop` ever fires, so `working` is
        the last word forever and nothing in the fleet would ever move that row.

        herdr is the cross-check, on the one reading of its that the broken spinner regex
        cannot fake: `unknown` is "no Claude rule matched anything", i.e. a pane with no
        agent in it. Not repaired here — surfacing beats guessing — but it reaches a
        person, which is the whole requirement.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)
        now = store.now() + int(status.STALL_GRACE) + 1
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "unknown")]),
                                        now=now))["w1"]
        self.assertTrue(a.signal_drift)
        self.assertTrue(a.needs_human)
        self.assertFalse(a.stalled)                       # not the same fact
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "working")  # not repaired
        self.assertIn("NO SESSION", status.render(status.Snapshot(now=now, agents=[a])))

    def test_a_pane_that_reads_unknown_for_a_moment_is_not_a_dead_session(self):
        """The debounce, and the reason it is not a timeout: a pane can read `unknown`
        while a tool call has a full-screen program in it. Nothing here is being asked to
        tell a long tool call from a finished turn — the edges already did that."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "unknown")])))["w1"]
        self.assertFalse(a.signal_drift)

    # -- the repair: a `working` edge that was never closed --------------------
    #
    # The cost of owning the signal, and the one thing about it that is worse than what it
    # replaced. A `Stop` that fails to write — a locked database, the blanket `except`, the
    # hook's own 10 s timeout, all silent — leaves `working` on a live pane for good, and
    # that row is pinged by nothing, swept by nothing and holds its mail forever.
    # These pin the way out.

    def stale(self, name="w1", *, herdr="idle", at=None):
        """Collect twice over a doubt long enough to be confirmed. -> the second snapshot.

        One reading only remembers the doubt — the whole safety of this is that a single
        herdr disagreement can never move a row — so a test about what gets WRITTEN has to
        look twice, with the clock past both windows.
        """
        h = FakeHerdr([alive(name, herdr)])
        at = (store.now() + int(status.TURN_STALE_GRACE) + 1) if at is None else at
        status.collect(self.db, h, now=at)
        return status.collect(self.db, h, now=at + int(status.TURN_DOUBT_GRACE) + 1)

    def test_a_working_edge_nothing_stands_behind_is_dropped_and_the_row_moves_again(self):
        """The wedge, and what ends it. The edge is dropped back to NULL rather than
        rewritten to idle: NULL is what a row with no signal has always held, so the row
        goes back to being read exactly as it was before the signal existed — stalled,
        therefore pingable, therefore reachable by everything else. Nothing is invented:
        `state` is untouched and no end is recorded."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)

        first = self.by_name(status.collect(
            self.db, FakeHerdr([alive("w1", "idle")]),
            now=store.now() + int(status.TURN_STALE_GRACE) + 1))["w1"]
        self.assertTrue(first.turn_doubted)               # doubted...
        self.assertFalse(first.stalled)                   # ...and still believed
        self.assertEqual(store.get_agent(self.db, "w1")["turn"], store.TURN_WORKING)

        self.stale()
        self.assertIsNone(store.get_agent(self.db, "w1")["turn"])
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "working")

        # The next reading is the repaired one — the write lands after the snapshot it was
        # computed from, exactly as `_record_gone`'s does.
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                        now=self.past_the_floor()))["w1"]
        self.assertTrue(a.stalled)
        self.assertEqual(a.display_state, "idle")

    def test_one_reading_that_disagrees_with_the_doubt_starts_the_clock_over(self):
        """Fail safe, and the reason this works at all. herdr's busy detector is
        intermittent rather than dead, so a genuinely working agent reads `working` to it
        sooner or later — and ONE such reading anywhere in the window clears the doubt. So
        does one `sb` command from the agent, which resets the staleness half. An agent
        that is quiet because its turn really ended produces neither."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)
        t = store.now() + int(status.TURN_STALE_GRACE) + 1

        status.collect(self.db, FakeHerdr([alive("w1", "idle")]), now=t)
        status.collect(self.db, FakeHerdr([alive("w1", "working")]), now=t + 1)
        self.assertIsNone(store.get_agent(self.db, "w1")["turn_doubt_since"])

        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                        now=t + int(status.TURN_DOUBT_GRACE) + 2))["w1"]
        self.assertEqual(store.get_agent(self.db, "w1")["turn"], store.TURN_WORKING)
        self.assertEqual(a.display_state, "working")

    def test_a_long_tool_call_is_never_doubted_and_neither_is_a_pane_with_nobody_in_it(self):
        """The two readings that must not reach the repair. Under the staleness bound
        nothing is even asked — that bound is set clear of the longest tool call this repo
        has recorded — and `unknown` is `signal_drift`'s case: a pane with no agent in it
        has nothing to be pinged back to life, so it stays a person's to decide about."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_WORKING)
        soon = store.now() + int(status.TURN_STALE_GRACE) - 60
        self.assertFalse(self.by_name(status.collect(
            self.db, FakeHerdr([alive("w1", "idle")]), now=soon))["w1"].turn_doubted)

        a = self.by_name(self.stale(herdr="unknown"))["w1"]
        self.assertFalse(a.turn_doubted)
        self.assertTrue(a.signal_drift)
        self.assertEqual(store.get_agent(self.db, "w1")["turn"], store.TURN_WORKING)

    def test_a_finished_agent_sitting_idle_is_not_drift(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "done")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        self.assertFalse(self.by_name(snap)["w1"].stalled)

    def test_unknown_from_herdr_proves_nothing(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "unknown")]))
        self.assertFalse(self.by_name(snap)["w1"].stalled)

    # -- idle because nobody has asked for anything -----------------------
    #
    # A lead or a top-level orchestrator is spawned before there is work for it, and sits
    # idle on purpose until somebody speaks. STALLED means "this needed to be doing
    # something and is not", which is false there, and a warning that is routinely false
    # is one the reader learns to skip past on the day it is true.

    def test_an_agent_nobody_has_asked_for_anything_is_not_stalled(self):
        store.create_agent(self.db, name="lead", role="lead", awaiting_task=True)
        snap = status.collect(self.db, FakeHerdr([alive("lead", "idle")]))
        a = self.by_name(snap)["lead"]
        self.assertFalse(a.stalled)
        self.assertEqual(a.state, "working")      # only the label changes; the row is as it was

    def test_idling_for_a_week_never_makes_it_stalled(self):
        """It is not a grace period. Nothing has been asked of this agent, so no amount of
        elapsed time turns its silence into drift."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1",
                           awaiting_task=True)
        later = store.now() + 7 * 24 * 3600
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("lead", "idle")]),
                                        now=later))["lead"]
        self.assertFalse(a.stalled)

    def test_the_same_agent_is_stalled_once_it_has_been_given_work(self):
        """The whole point of keeping the flag: told something and then quiet IS drift."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1",
                           awaiting_task=True)
        store.put_message(self.db, from_agent="human", to_agent="lead",
                          kind="tell", body="do the thing")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("lead", "idle")]),
                                        now=self.past_the_floor()))["lead"]
        self.assertTrue(a.stalled)

    def test_an_ordinary_agent_is_stalled_from_the_start(self):
        """A delegated worker is given its work AT spawn, so it is stalled-eligible with
        no message ever arriving for it. The default has to be this way round: the failure
        that costs something is a stuck agent nobody is warned about."""
        store.create_agent(self.db, name="w1", role="worker", task="fix the parser",
                           session_id="s1")
        self.assertTrue(self.by_name(status.collect(
            self.db, FakeHerdr([alive("w1", "idle")]),
            now=self.past_the_floor()))["w1"].stalled)

    # -- the floor under a stall, and the question that excuses one ---------
    #
    # `stalled` had no duration term in it at all: the `Stop` hook writes `turn='idle'` at
    # the end of every turn, so an ordinary worker was stalled at ZERO seconds — pinged and
    # put in front of a person in the instant it finished speaking. Two answers, and these
    # pin both. Neither touches the reconciler, which still pings exactly the stalled set.

    def test_a_turn_that_just_ended_is_not_a_stall_yet(self):
        """The zero-second stall, and what ends it. Both halves in one, because the floor
        is only worth anything if the stall still ARRIVES: three seconds later this same
        row is stalled, with nothing else about it changed."""
        store.create_agent(self.db, name="w1", role="worker", task="fix the parser",
                           session_id="s1")
        store.set_turn(self.db, "w1", store.TURN_IDLE)
        h = FakeHerdr([alive("w1", "idle")])

        fresh = self.by_name(status.collect(self.db, h, now=store.now()))["w1"]
        self.assertFalse(fresh.stalled)
        self.assertFalse(fresh.needs_human)
        self.assertEqual(fresh.idle_excuse, "just finished a turn")

        held = self.by_name(status.collect(self.db, h, now=self.past_the_floor()))["w1"]
        self.assertTrue(held.stalled)
        self.assertTrue(held.needs_human)
        self.assertIsNone(held.idle_excuse)

    def test_an_agent_waiting_on_a_reply_it_asked_for_is_not_stalled(self):
        """The sharpest case the eager stall got wrong: `sb tell --needs-reply` and end the
        turn is exactly what the protocol says to do, and it summoned a person for it."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.create_agent(self.db, name="w2", role="worker", session_id="s2")
        store.put_message(self.db, from_agent="w1", to_agent="w2", kind="tell",
                          body="which branch?", needs_reply=True)
        h = FakeHerdr([alive("w1", "idle"), alive("w2", "working")])
        a = self.by_name(status.collect(self.db, h, now=self.past_the_floor()))["w1"]
        self.assertFalse(a.stalled)
        self.assertFalse(a.needs_human)
        self.assertEqual(a.idle_excuse, "waiting on a reply")

    def test_the_answer_ends_the_excuse(self):
        """It excuses a WAIT and not a name: anything back from the agent it asked spends
        the question, and the row is a stall again like any other."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.create_agent(self.db, name="w2", role="worker", session_id="s2")
        store.put_message(self.db, from_agent="w1", to_agent="w2", kind="tell",
                          body="which branch?", needs_reply=True)
        store.put_message(self.db, from_agent="w2", to_agent="w1", kind="tell",
                          body="main")
        h = FakeHerdr([alive("w1", "idle"), alive("w2", "working")])
        a = self.by_name(status.collect(self.db, h, now=self.past_the_floor()))["w1"]
        self.assertTrue(a.stalled)
        self.assertIsNone(a.idle_excuse)

    def test_a_question_nobody_is_left_to_answer_is_not_an_excuse(self):
        """The bound on a wait with no clock on it. The recipient reported and its row is
        closed, so no answer is ever coming — and an agent waiting for one is stuck, which
        is the thing STALLED exists to say."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.create_agent(self.db, name="w2", role="worker", session_id="s2")
        store.put_message(self.db, from_agent="w1", to_agent="w2", kind="tell",
                          body="which branch?", needs_reply=True)
        store.set_state(self.db, "w2", "done")
        h = FakeHerdr([alive("w1", "idle")])
        a = self.by_name(status.collect(self.db, h, now=self.past_the_floor()))["w1"]
        self.assertTrue(a.stalled)

    # -- the other half of the same test: WHY an idle agent is idle ------

    def test_an_idle_agent_says_which_excuse_it_is_idle_on(self):
        """A lead waiting on its children and an agent that quietly died are both `idle`
        and are told apart by exactly one thing. `stalled` says nothing explains this;
        this says what does, so a reader never has to infer either."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1",
                           task="mind the children")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2", task="do it")
        a = self.by_name(status.collect(
            self.db, FakeHerdr([alive("lead", "idle"), alive("w1", "working")])))["lead"]
        self.assertFalse(a.stalled)
        self.assertEqual(a.idle_excuse, "waiting on children")

    def test_idle_with_nothing_to_explain_it_carries_no_excuse(self):
        """The pair the whole distinction rests on: `stalled` is idle and this is None."""
        store.create_agent(self.db, name="w1", role="worker", task="fix the parser",
                           session_id="s1")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                        now=self.past_the_floor()))["w1"]
        self.assertTrue(a.stalled)
        self.assertIsNone(a.idle_excuse)

    def test_an_agent_that_is_not_idle_has_no_excuse_to_offer(self):
        """A working parent with a live child is WORKING. An excuse for something that is
        not happening would be a note about nothing."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2")
        a = self.by_name(status.collect(
            self.db, FakeHerdr([alive("lead", "working"), alive("w1", "working")])))["lead"]
        self.assertIsNone(a.idle_excuse)

    def test_a_store_without_the_column_still_reads(self):
        """The board and the collector hold a READ-ONLY connection and cannot migrate, so
        they meet a store an older `sb` last stamped. Missing reads as the label the row
        already had, rather than raising on every tick until a writer runs."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.db.execute("ALTER TABLE agents DROP COLUMN awaiting_task")
        self.db.commit()
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                        now=self.past_the_floor()))["w1"]
        self.assertTrue(a.stalled)

    def test_an_agent_that_has_never_run_sb_is_not_stalled_yet(self):
        """The spurious nudge, from the other end. An agent two seconds out of `delegate`
        looks exactly like one whose turn ended and said nothing — its row is `working`,
        herdr says idle because no turn has started, and it holds no placeholder. It was
        pinged in that window. No session id means it has
        never run an `sb` command, so nothing here has seen it take a turn; after
        `STALL_GRACE` the reading is trusted, because by then it should have."""
        store.create_agent(self.db, name="w1", role="worker", task="fix the parser")
        h = FakeHerdr([alive("w1", "idle")])
        self.assertFalse(self.by_name(status.collect(self.db, h))["w1"].stalled)
        later = store.now() + int(status.STALL_GRACE) + 1
        self.assertTrue(self.by_name(status.collect(self.db, h, now=later))["w1"].stalled)

    def test_working_but_absent_from_herdr_is_gone(self):
        # `session_id` is what says this one got past its spawn: a session-less row this
        # young is a claim, and claims are held off (see the spawn-grace tests below).
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = status.collect(self.db, FakeHerdr([]))
        a = self.by_name(snap)["w1"]
        self.assertTrue(a.gone)
        self.assertFalse(a.alive)
        self.assertFalse(a.stalled)               # a closed pane is a different problem

    # -- reconciliation: the drift is written back ------------------------

    def row(self, name):
        return store.get_agent(self.db, name)

    def test_a_gone_agent_is_recorded_as_ended(self):
        """Nothing else ever closes a row that died abnormally. `sb done` is the agent's
        own, and `sb cleanup` only touches rows that are already finished — so without
        this the row claims `working` for good and no sweep can reach it."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = self.confirm_gone()
        self.assertTrue(self.by_name(snap)["w1"].gone)   # still reported as observed

        a = self.row("w1")
        self.assertEqual(a["state"], status.GONE_STATE)
        self.assertIsNotNone(a["ended_at"])
        self.assertIn(a["state"], status.FINISHED)       # what `sb cleanup` gates on
        self.assertEqual([e["kind"] for e in store.recent_events(self.db, agent="w1")],
                         ["gone"])

    def test_a_failure_puts_one_message_in_the_parents_mailbox(self):
        """DESIGN-TRUTH's "telling the parent that it has failed", and Andrew's ruling that
        it must act the way `sb done` does. The row on the board was passive: a parent that
        ended its turn to wait for a poke never looks at a board. So the failure is a
        `messages` row, undelivered, which is the same thing a `done` leaves behind for
        `flush_pending` to ring when the parent is free.

        It names the child and what it was doing — a bare "an agent failed" makes the
        parent go digging — and it is NOT a `done`, so nothing is attributed to an agent
        that never reported: `AgentStatus.summary` reads `done` rows only.
        """
        store.create_agent(self.db, name="lead", role="lead", session_id="s1")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2", task="rewrite the parser")
        self.confirm_gone(FakeHerdr([alive("lead")]))

        [m] = store.unread_for(self.db, "lead", mark=False)
        self.assertEqual((m["kind"], m["from_agent"]), ("failed", "w1"))
        self.assertIsNone(m["delivered_at"])             # `flush_pending`'s work list
        self.assertIn("w1", m["body"])
        self.assertIn("rewrite the parser", m["body"])
        self.assertEqual(len(m["body"].splitlines()), 1)  # a notification, not a report
        self.assertIsNone(self.by_name(status.collect(self.db, FakeHerdr([alive("lead")])))
                          ["w1"].summary)

    def test_a_failure_pings_once_however_often_the_row_is_read(self):
        """The row stays `failed` forever and every `sb status` reads it again. Once-only
        is the state transition, not a memory: the UPDATE is conditional on the row still
        being RUNNING, and only a row it actually changed gets a message."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2", task="rewrite the parser")
        h = FakeHerdr([alive("lead")])
        self.confirm_gone(h)
        for _ in range(3):
            status.collect(self.db, h)
        self.assertEqual(len(store.unread_for(self.db, "lead", mark=False)), 1)
        self.assertEqual([e["kind"] for e in store.recent_events(self.db, agent="w1")],
                         ["gone"])

    def test_a_root_that_dies_pings_nobody_and_raises_nothing(self):
        """No parent, and the human has no mailbox — so the failure stays a row and an
        event, exactly as it was before the ping existed. The one case a person still has
        to see on the board."""
        store.create_agent(self.db, name="top", role="lead", session_id="s1")
        self.confirm_gone()
        self.assertEqual(self.row("top")["state"], status.GONE_STATE)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    # -- a blocked agent: waiting, or gone? --------------------------------

    def test_a_blocked_agent_whose_pane_died_is_recorded_failed_and_its_parent_told(self):
        """`states.running` is `working` alone, so a blocked agent was never `gone`, never
        reaped, never `failed` and its parent never told — it simply stayed BLOCKED on the
        board for good. `states.reapable` is the wider list this one question asks."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2", task="rewrite the parser")
        store.set_state(self.db, "w1", "blocked")

        self.confirm_gone(FakeHerdr([alive("lead")]))
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)
        self.assertIsNotNone(self.row("w1")["ended_at"])
        [m] = store.unread_for(self.db, "lead", mark=False)
        self.assertEqual((m["kind"], m["from_agent"]), ("failed", "w1"))

    def test_a_blocked_agent_that_is_merely_waiting_is_left_entirely_alone(self):
        """The half that matters most: a block is SUPPOSED to sit there until a human
        answers. Its pane is the only thing that separates the two, so an agent herdr still
        lists is never gone however long it waits — and never stalled either, which is what
        would put the reconciler's "your turn ended without a report" in front of an agent
        that stopped on purpose."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s1")
        store.create_agent(self.db, name="w1", role="worker", parent="lead",
                           session_id="s2")
        store.set_state(self.db, "w1", "blocked")
        h = FakeHerdr([alive("lead"), alive("w1", "idle")])

        at = store.now()
        for step in (0, int(status.GONE_CONFIRM_GRACE) + 1, int(status.STALL_GRACE) + 1):
            a = self.by_name(status.collect(self.db, h, now=at + step))["w1"]
            self.assertFalse(a.gone)
            self.assertFalse(a.stalled)
        self.assertEqual(self.row("w1")["state"], "blocked")
        self.assertIsNone(self.row("w1")["ended_at"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    # -- the spawn grace: a claim is not evidence of a live agent ----------

    def test_a_fresh_session_less_row_is_a_claim_and_is_not_reaped(self):
        """`delegate` writes the row before herdr is asked to start anything, and
        `agent start` is retried for seconds. herdr not listing the name during that
        window proves nothing — reaping there kills an agent during its own spawn."""
        store.create_agent(self.db, name="w1", role="worker", pane_id="w1:p1")
        a = self.by_name(status.collect(self.db, FakeHerdr([])))["w1"]
        self.assertFalse(a.gone)
        self.assertEqual(self.row("w1")["state"], "working")
        self.assertIsNone(self.row("w1")["ended_at"])

    def test_a_claim_older_than_the_grace_is_reaped(self):
        """The grace is a window, not an exemption: a spawn that never landed must still
        end up reachable by `sb cleanup`."""
        store.create_agent(self.db, name="w1", role="worker", pane_id="w1:p1")
        later = store.now() + int(status.SPAWN_GRACE) + 1
        a = self.by_name(self.confirm_gone(at=later))["w1"]
        self.assertTrue(a.gone)
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)

    def test_the_grace_only_covers_rows_with_no_session(self):
        """A session id means the agent got past its spawn and called `sb` itself, so
        herdr's silence about it is real drift however young the row is."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.assertTrue(self.by_name(status.collect(self.db, FakeHerdr([])))["w1"].gone)

    def test_the_grace_outlasts_herdrs_own_retry_loop(self):
        """The relationship, not the number: whatever herdr's retry policy becomes, the
        window still has to cover a spawn running its whole worst case.

        Measured by driving the real loop rather than by restating its arithmetic — every
        attempt allowed the timeout it asked herdr for, plus every sleep the loop actually
        took. Restating it is what went wrong: the grace was `timeout x attempts` = 270 s
        against a 282 s loop, having missed the backoff — including the sleep the loop
        takes after its LAST failure, which no reading of `2 + 4` predicts.

        WHAT THIS DELIBERATELY DOES NOT COVER, decided by the human when the two branches
        met: `--timeout` is what the loop asks HERDR to spend, and since `64a8099` there
        is a second, outer deadline — `herdr._grace(timeout_ms)`, ten seconds longer —
        that only fires when herdr answers nothing at all. Against that bound the true
        worst case is 3 x 100 + 12 = 312 s, and `SPAWN_GRACE` is 287. So a spawn CAN
        outlive the grace by 25 s and be reaped mid-spawn, but only in the herdr-hung
        case the outer bound was added for. The grace stays derived from herdr's own
        policy, and that hole stays open.

        `**_` because the runner is the injected `_run`, and `_spawn` passes it the outer
        deadline as `timeout=`. Reading that kwarg here instead of `--timeout` is exactly
        the change that would close the gap above.
        """
        naps: list[float] = []
        bounds: list[int] = []

        def runner(argv, **_):
            argv = list(argv)
            bounds.append(int(argv[argv.index("--timeout") + 1]))
            body = {"id": "x", "error": {"code": "timeout", "message": "startup"}}
            return subprocess.CompletedProcess([], 0, json.dumps(body), "")

        h = Herdr("herdr", runner=runner, sleep=naps.append)
        with self.assertRaises(HerdrError):
            h.start_agent("w1", "w1:p1")            # the real loop, real policy defaults

        worst = sum(bounds) / 1000 + sum(naps)
        self.assertEqual(len(bounds), herdr_mod.SPAWN_ATTEMPTS)
        self.assertGreaterEqual(status.SPAWN_GRACE, worst)

    def test_an_unreachable_herdr_never_reaps_anything(self):
        """The guard. Absent herdr's side every row looks gone, and a hiccup would end
        every agent on the machine."""
        store.create_agent(self.db, name="w1", role="worker")
        status.collect(self.db, FakeHerdr(error=HerdrError("down", "no server")))
        self.assertEqual(self.row("w1")["state"], "working")
        self.assertIsNone(self.row("w1")["ended_at"])

    # -- the confirmation grace: one absent reading is a hiccup, not a death ----
    #
    # `agent list` coming back short is not proof of anything on its own — herdr restarts,
    # answers under load, and the store's own history has three agents marked failed during
    # one night's startups off exactly that. So an absence is remembered and has to last.

    def test_one_absent_reading_records_nothing(self):
        """The bug this exists for: a single short `agent list` used to end a live agent."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        a = self.by_name(status.collect(self.db, FakeHerdr([])))["w1"]
        self.assertTrue(a.gone)                   # observed, and said so on screen
        self.assertEqual(self.row("w1")["state"], "working")     # but not written down
        self.assertIsNone(self.row("w1")["ended_at"])
        self.assertEqual(store.recent_events(self.db, agent="w1"), [])
        self.assertIsNotNone(self.row("w1")["absent_since"])     # only remembered

    def test_absence_inside_the_window_still_records_nothing(self):
        """A window, not a second look: two readings a moment apart are the same hiccup."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        now = store.now()
        status.collect(self.db, FakeHerdr([]), now=now)
        status.collect(self.db, FakeHerdr([]),
                       now=now + int(status.GONE_CONFIRM_GRACE) - 1)
        self.assertEqual(self.row("w1")["state"], "working")

    def test_absence_past_the_window_is_recorded(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.confirm_gone()
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)
        self.assertIsNone(self.row("w1")["absent_since"])   # the count is over, not running

    def test_an_absence_that_is_interrupted_starts_again(self):
        """CONTINUOUSLY is the whole word. An agent herdr listed again in between has not
        been dying for a minute — it was there — and adding the two gaps together would
        confirm a death that never happened."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        now = store.now()
        half = int(status.GONE_CONFIRM_GRACE / 2) + 1
        status.collect(self.db, FakeHerdr([]), now=now)
        status.collect(self.db, FakeHerdr([alive("w1")]), now=now + half)
        self.assertIsNone(self.row("w1")["absent_since"])   # forgotten, not paused

        status.collect(self.db, FakeHerdr([]), now=now + 2 * half)
        # Past the window counting from the FIRST absence, inside it counting from the
        # second — which is the reading that decides.
        self.assertEqual(self.row("w1")["state"], "working")
        status.collect(self.db, FakeHerdr([]),
                       now=now + 2 * half + int(status.GONE_CONFIRM_GRACE) + 1)
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)

    def test_a_reader_never_stamps_an_absence(self):
        """`reap=False` writes NOTHING, including the half of the debounce that only
        remembers. The board holds a read-only connection (see `store.connect`), so a stamp
        from there is not a policy choice — it is an exception on every tick."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        status.collect(self.db, FakeHerdr([]), reap=False)
        self.assertIsNone(self.row("w1")["absent_since"])

    def test_an_unreachable_herdr_forgets_nothing_and_remembers_nothing(self):
        """A herdr that cannot be reached is not a herdr that says the agent is gone: the
        absence already counted must neither advance nor be cleared by it."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        now = store.now()
        status.collect(self.db, FakeHerdr([]), now=now)
        stamped = self.row("w1")["absent_since"]
        status.collect(self.db, FakeHerdr(error=HerdrError("down", "no server")),
                       now=now + int(status.GONE_CONFIRM_GRACE) + 1)
        self.assertEqual(self.row("w1")["absent_since"], stamped)
        self.assertEqual(self.row("w1")["state"], "working")

    def test_a_store_without_the_column_still_reaps(self):
        """A store an older `sb` last stamped has nowhere to remember an absence. Recording
        on sight is what shipped before the column and is the right fallback: a row nothing
        can ever record as gone is a row `sb cleanup` can never reach."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.db.execute("ALTER TABLE agents DROP COLUMN absent_since")
        self.db.commit()
        status.collect(self.db, FakeHerdr([]))
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)

    # -- a name is not an identity: herdr's list is machine-global ----------
    #
    # Every store on a machine mints names from the same role vocabulary independently, so
    # a name match alone reads a stranger's live agent as our own dead one. Reproduced live: a row
    # dead four days came back onto its own board as an ordinary live agent the moment an
    # unrelated clone started an agent of the same name (`notes/qa-ghost-repro-isolated.md`).

    def test_a_stranger_wearing_our_name_is_not_our_agent(self):
        """Terminal id and not session id is what catches it in the field: herdr's
        `agent list` reports no `agent_session` at all today, so the session half of the
        guard can never fire on its own."""
        store.create_agent(self.db, name="w1", role="worker", session_id="ours",
                           terminal_id="term_ours")
        a = self.by_name(status.collect(
            self.db, FakeHerdr([alive("w1", terminal="term_theirs")])))["w1"]
        self.assertFalse(a.alive)          # not resurrected by somebody else's fleet
        self.assertIsNone(a.herdr_state)   # and no state borrowed from it either

    def test_a_stranger_does_not_clear_the_gone_debounce(self):
        """The second half of the same bug, and the reason it never healed: the false
        "present again" forgot the remembered absence, so the row could never accumulate a
        confirmation window and sat `working` for as long as the stranger ran."""
        store.create_agent(self.db, name="w1", role="worker", session_id="ours",
                           terminal_id="term_ours")
        self.confirm_gone(FakeHerdr([alive("w1", terminal="term_theirs")]))
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)

    def test_a_match_stands_when_the_ids_agree_or_are_unknown(self):
        """The guard fires on DISAGREEMENT only. Our own agent still matches, and so does
        one where either side has nothing to compare — a row mid-spawn has neither id yet,
        and that window is covered by the spawn grace, not by this."""
        store.create_agent(self.db, name="w1", role="worker", session_id="ours",
                           terminal_id="term_ours")
        store.create_agent(self.db, name="w2", role="worker", session_id="ours2")
        by = self.by_name(status.collect(self.db, FakeHerdr(
            [alive("w1", terminal="term_ours"), alive("w2")])))
        self.assertTrue(by["w1"].alive)
        self.assertTrue(by["w2"].alive)    # no terminal id on either side: the name stands

    def test_a_session_id_that_disagrees_is_enough_on_its_own(self):
        """Nothing catches this today — herdr reports no session id — and it is here for
        the day it does: the session id is the stronger identity, so a disagreement there
        stands alone rather than waiting on the terminal id."""
        store.create_agent(self.db, name="w1", role="worker", session_id="ours")
        a = self.by_name(status.collect(
            self.db, FakeHerdr([alive("w1", session="theirs")])))["w1"]
        self.assertFalse(a.alive)

    # -- reap=False: a reader that outlives its own code ------------------

    def test_a_readout_can_see_the_drift_without_writing_it(self):
        """What `sb board` passes. It refreshes every two seconds for hours on the
        `status.py` it imported at startup, so drift written from there is written by a
        heuristic nobody is running any more — three such boards reaped every spawn of one
        night. The flag is still computed, so the screen says exactly what it said before."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = status.collect(self.db, FakeHerdr([]), reap=False)
        self.assertTrue(self.by_name(snap)["w1"].gone)   # still reported

        self.assertEqual(self.row("w1")["state"], "working")
        self.assertIsNone(self.row("w1")["ended_at"])
        self.assertEqual(store.recent_events(self.db, agent="w1"), [])

    def test_not_reaping_leaves_the_row_reachable_by_a_later_reap(self):
        """`reap=False` defers the write, it does not veto it: the next `sb status` — a
        short-lived process on current code — still closes a genuinely dead row."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        status.collect(self.db, FakeHerdr([]), reap=False)
        self.confirm_gone()
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)

    def test_no_herdr_at_all_never_reaps_anything(self):
        store.create_agent(self.db, name="w1", role="worker")
        status.collect(self.db, None)
        self.assertEqual(self.row("w1")["state"], "working")

    def test_a_stalled_agent_is_left_alone(self):
        """Its pane is still there. Ending it here would invent a summary its parent
        never received — the drift is reported, not resolved."""
        store.create_agent(self.db, name="w1", role="worker")
        status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        self.assertEqual(self.row("w1")["state"], "working")

    def test_a_finished_agent_is_not_reaped_again(self):
        """Idempotent, and it must not overwrite how the agent actually ended."""
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "done")
        ended = self.row("w1")["ended_at"]
        status.collect(self.db, FakeHerdr([]))
        self.assertEqual(self.row("w1")["state"], "done")
        self.assertEqual(self.row("w1")["ended_at"], ended)

    def test_a_reaped_agent_reads_as_ended_on_the_next_look(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.confirm_gone()
        a = self.by_name(status.collect(self.db, FakeHerdr([])))["w1"]
        self.assertEqual(a.state, status.GONE_STATE)
        self.assertFalse(a.gone)                  # no longer drift: the store agrees now
        self.assertTrue(a.finished)

    def test_herdr_blocked_means_a_human_is_being_asked_something(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "blocked")]))
        a = self.by_name(snap)["w1"]
        self.assertTrue(a.at_prompt)
        self.assertTrue(a.needs_human)
        self.assertFalse(a.stalled)

    # -- one herdr call ---------------------------------------------------

    def test_herdr_is_called_exactly_once_for_the_whole_tree(self):
        for i in range(6):
            store.create_agent(self.db, name=f"w{i}", role="worker",
                               parent=(f"w{i - 1}" if i else None))
        h = FakeHerdr([alive(f"w{i}") for i in range(6)])
        status.collect(self.db, h)
        self.assertEqual(h.calls, 1)

    def test_an_unreachable_herdr_degrades_instead_of_failing(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr(error=HerdrError("down", "no server")))
        a = self.by_name(snap)["w1"]
        self.assertIsNone(a.alive)                # unknown, not False
        self.assertFalse(a.stalled)               # never guess drift from half the data
        self.assertFalse(a.gone)
        self.assertIn("no server", snap.herdr_error)
        self.assertIn("herdr unreachable", status.render(snap))

    # -- the tree ---------------------------------------------------------

    def test_roots_are_at_depth_zero_and_children_indent(self):
        store.create_agent(self.db, name="root", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        store.create_agent(self.db, name="grandkid", role="worker", parent="kid")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual([(a.name, a.depth) for a in snap.agents],
                         [("root", 0), ("kid", 1), ("grandkid", 2)])

    def test_a_parent_immediately_precedes_its_children(self):
        store.create_agent(self.db, name="a", role="lead")
        store.create_agent(self.db, name="b", role="lead")
        store.create_agent(self.db, name="a1", role="worker", parent="a")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual([a.name for a in snap.agents], ["a", "a1", "b"])

    def test_an_orphan_still_appears(self):
        """The store is disposable, so a missing parent row is normal, not corruption."""
        store.create_agent(self.db, name="kid", role="worker", parent="vanished")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual([(a.name, a.depth) for a in snap.agents], [("kid", 0)])
        self.assertEqual(snap.agents[0].parent, "vanished")   # the link is still reported

    def test_a_parent_cycle_does_not_hang_or_lose_agents(self):
        store.create_agent(self.db, name="a", role="worker", parent="b")
        store.create_agent(self.db, name="b", role="worker", parent="a")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual({a.name for a in snap.agents}, {"a", "b"})

    # -- mail -------------------------------------------------------------

    def test_unread_is_counted_per_agent(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="b")
        snap = status.collect(self.db, FakeHerdr([alive("w1")]))
        a = self.by_name(snap)["w1"]
        self.assertEqual(a.unread, 2)
        self.assertTrue(a.needs_human)

    def test_reading_status_never_consumes_mail(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        status.collect(self.db, FakeHerdr([alive("w1")]))
        status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertEqual(len(store.unread_for(self.db, "w1", mark=False)), 1)

    def test_the_human_has_no_mailbox_to_surface(self):
        """`sb status` never points a person at an inbox — they do not have one."""
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="w1", to_agent="human", kind="ask", body="?")
        snap = status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertEqual(snap.counts["unread"], 0)
        self.assertNotIn("sb inbox", status.render(snap))

    # -- undelivered: mail nobody ever rang about --------------------------

    def deliver(self, name):
        store.mark_delivered(self.db, name)

    def test_mail_the_agent_read_itself_is_not_undelivered(self):
        """An agent may read its inbox without waiting to be rung, and then it knows.

        It is mid-turn, so the doorbell is held back; it runs `sb inbox` anyway; the rows
        stay un-announced for good, because the ring that would have cleared them is the
        ring they were owed. Counting those is how one row came to read `MAIL -` and
        `<< UNDELIVERED 8` about the same mailbox.
        """
        store.create_agent(self.db, name="w1", role="worker")
        for body in ("a", "b", "c"):
            store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body=body)
        store.unread_for(self.db, "w1")                   # proactive: read, never rung
        self.assertEqual(len(store.undelivered(self.db, exclude=["human"])), 3)
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")])))["w1"]
        self.assertEqual((a.unread, a.undelivered), (0, 0))
        self.assertFalse(a.waiting_to_be_rung)
        self.assertFalse(a.needs_human)
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        self.assertNotIn("UNDELIVERED", out)

    def test_only_the_unread_part_of_unannounced_mail_is_counted(self):
        """The I > R case: more un-announced than unread, and the warning follows unread.

        Three rows nobody ever rang about, two of which the agent read itself. Only the
        third is news to it, and only the third may drive the age, the flag, or NEEDS YOU.
        """
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        for body in ("old1", "old2"):
            store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body=body)
        self.db.execute("UPDATE messages SET created_at=?", (t - 600,))
        self.db.commit()
        store.unread_for(self.db, "w1")                   # it read those two, unrung
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="fresh")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")]), now=t))["w1"]
        self.assertEqual(len(store.undelivered(self.db, exclude=["human"])), 3)  # all unrung
        self.assertEqual((a.unread, a.undelivered), (1, 1))
        # The age of the one it does not know about, NOT of the pair it handled at once.
        self.assertEqual(a.undelivered_age, 0)
        self.assertTrue(a.waiting_to_be_rung)
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")]), now=t))
        self.assertIn("1 never announced to it", out)
        self.assertNotIn("unread it WAS told about", out)   # there is no such remainder

    def test_the_age_is_of_the_oldest_not_the_newest(self):
        """A fresh message arriving behind a stuck one must not reset the clock."""
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="old")
        self.db.execute("UPDATE messages SET created_at=? WHERE body='old'", (t - 600,))
        self.db.commit()
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="new")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")]), now=t))["w1"]
        self.assertEqual(a.undelivered, 2)
        self.assertEqual(a.undelivered_age, 600)

    def test_counting_undelivered_mail_never_delivers_it(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        status.collect(self.db, FakeHerdr([alive("w1")]))
        status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertEqual(len(store.undelivered(self.db, exclude=["human"])), 1)

    def test_needs_me_keeps_an_agent_whose_only_problem_is_undelivered_mail(self):
        store.create_agent(self.db, name="quiet", role="worker")
        store.create_agent(self.db, name="stuck", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="stuck", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr([alive("quiet"), alive("stuck")]),
                              needs_me=True)
        self.assertEqual([a.name for a in snap.agents], ["stuck"])

    def test_mail_it_was_told_about_is_still_distinguished_when_both_exist(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="rung")
        self.deliver("w1")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="silent")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        self.assertIn("1 never announced to it", out)
        self.assertIn("1 unread it WAS told about", out)

    # -- blocked ----------------------------------------------------------

    def test_blocked_carries_its_reason(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "blocked")
        store.log_event(self.db, kind="blocked", agent="w1", why="cannot find the config")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        a = self.by_name(snap)["w1"]
        self.assertTrue(a.blocked)
        self.assertTrue(a.needs_human)
        self.assertEqual(a.blocked_why, "cannot find the config")
        self.assertIn("cannot find the config", status.render(snap))

    def test_blocked_is_never_reported_as_stalled(self):
        """`blocked` is not a running state, so idleness is expected, not drift."""
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "blocked")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        self.assertFalse(self.by_name(snap)["w1"].stalled)

    def test_a_blocked_agents_undelivered_mail_is_not_explained_as_waiting_for_idle(self):
        """The explanation branches, because the mechanism does.

        A blocked agent's mail is held on `_is_blocked` in `_ring`/`flush_pending` and
        released by the human's answer alone — going idle is not a state it passes
        through. The unbranched sentence told the reader to wait for something that will
        never happen.
        """
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "blocked")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))
        self.assertIn("held until the human", out)
        self.assertIn("not until it goes idle", out)

    def test_an_unblocked_agent_is_still_told_the_doorbell_waits_for_idle(self):
        """The branch is an exception, not a replacement: this case is unchanged."""
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        self.assertIn("released when it goes idle", out)
        self.assertNotIn("not until it goes idle", out)

    def test_the_blocked_row_names_who_can_actually_answer(self):
        """Only the human's `tell` clears a block (`answer=(me == HUMAN)`)."""
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "blocked")
        store.log_event(self.db, kind="blocked", agent="w1", why="which branch?")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))
        self.assertIn("the human answers it: sb tell w1", out)

    def test_the_latest_block_reason_wins(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.log_event(self.db, kind="blocked", agent="w1", why="first")
        store.log_event(self.db, kind="blocked", agent="w1", why="second")
        store.set_state(self.db, "w1", "blocked")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual(self.by_name(snap)["w1"].blocked_why, "second")

    # -- clocks -----------------------------------------------------------

    def test_age_counts_from_creation(self):
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 3600, "w1"))
        self.db.commit()
        snap = status.collect(self.db, FakeHerdr([alive("w1")]), now=t)
        self.assertEqual(self.by_name(snap)["w1"].age, 3600)

    def test_an_event_resets_the_idle_clock(self):
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 3600, "w1"))
        self.db.commit()
        store.log_event(self.db, kind="delegate", agent="w1")
        self.db.execute("UPDATE events SET created_at=? WHERE agent=?", (t - 60, "w1"))
        self.db.commit()
        snap = status.collect(self.db, FakeHerdr([alive("w1")]), now=t)
        self.assertEqual(self.by_name(snap)["w1"].idle, 60)

    def test_incoming_mail_does_not_reset_the_idle_clock(self):
        """Somebody else acting is not this agent acting — that is the whole signal."""
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 3600, "w1"))
        self.db.commit()
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="hi")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]), now=t)
        self.assertEqual(self.by_name(snap)["w1"].idle, 3600)

    def test_a_doorbell_held_for_a_busy_agent_is_not_that_agents_activity(self):
        """The events half of the same rule, which is where it leaked. `_ring` logs
        `ring_deferred` against the RECIPIENT, so mail arriving advanced the recipient's
        idle clock through `events` after being excluded from `messages` — and an agent
        with a backlog could therefore never look idle for the thirty minutes
        `turn_doubted` needs, which is why the stale-turn repair could never fire for it.
        """
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 3600, "w1"))
        self.db.commit()
        for kind in status.DONE_TO_THE_AGENT:
            store.log_event(self.db, kind=kind, agent="w1")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]), now=t)
        self.assertEqual(self.by_name(snap)["w1"].idle, 3600)

    def test_the_agents_own_events_still_count(self):
        """The denylist is narrow on purpose: everything else an event says about an agent
        IS that agent acting, and reading its own `sb` calls as silence would be the same
        bug pointing the other way."""
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 3600, "w1"))
        self.db.commit()
        for kind in ("done", "blocked", "delegate", "turn_end", "plugin"):
            with self.subTest(kind=kind):
                self.assertNotIn(kind, status.DONE_TO_THE_AGENT)
        store.log_event(self.db, kind="blocked", agent="w1", why="ask")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]), now=t)
        self.assertLess(self.by_name(snap)["w1"].idle, 10)

    def test_a_message_the_agent_sent_counts_as_activity(self):
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 3600, "w1"))
        self.db.commit()
        store.put_message(self.db, from_agent="w1", to_agent="x", kind="tell", body="hi")
        snap = status.collect(self.db, FakeHerdr([alive("w1")]), now=t)
        self.assertLess(self.by_name(snap)["w1"].idle, 10)

    # -- live_only --------------------------------------------------------

    def test_live_only_hides_finished_agents(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.create_agent(self.db, name="w2", role="worker")
        store.set_state(self.db, "w2", "done")
        snap = status.collect(self.db, FakeHerdr([alive("w1")]), live_only=True)
        self.assertEqual([a.name for a in snap.agents], ["w1"])
        self.assertEqual(snap.hidden, 1)

    def test_live_only_keeps_a_finished_agent_holding_unread_mail(self):
        store.create_agent(self.db, name="w2", role="worker")
        store.set_state(self.db, "w2", "done")
        store.put_message(self.db, from_agent="x", to_agent="w2", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr(), live_only=True)
        self.assertEqual([a.name for a in snap.agents], ["w2"])

    def test_live_only_keeps_ancestors_so_the_tree_still_reads(self):
        store.create_agent(self.db, name="root", role="lead")
        store.set_state(self.db, "root", "done")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr([alive("kid")]), live_only=True)
        self.assertEqual([(a.name, a.depth) for a in snap.agents], [("root", 0), ("kid", 1)])

    # -- filters ----------------------------------------------------------

    def test_needs_me_keeps_only_what_is_owed_an_action(self):
        store.create_agent(self.db, name="busy", role="worker")
        store.create_agent(self.db, name="stuck", role="worker")
        store.create_agent(self.db, name="mail", role="worker")
        store.set_state(self.db, "stuck", "blocked")
        store.put_message(self.db, from_agent="x", to_agent="mail", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr([alive("busy"), alive("mail")]),
                              needs_me=True)
        self.assertEqual({a.name for a in snap.agents}, {"stuck", "mail"})
        self.assertEqual(snap.hidden, 1)

    def test_needs_me_includes_a_stalled_agent(self):
        """It is not asking for anything, and that is exactly the problem: its turn ended
        without `sb done`, so the store says `working` forever, no doorbell rings it again
        and no sweep closes it. Only a person moves it, so it is owed an action."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]), needs_me=True,
                              now=self.past_the_floor())
        self.assertEqual([a.name for a in snap.agents], ["w1"])
        self.assertTrue(self.by_name(snap)["w1"].needs_human)

    def test_a_stalled_agent_is_named_in_the_inbox_with_the_way_out(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                           now=self.past_the_floor()))
        self.assertIn("NEEDS YOU", out)
        self.assertIn("stalled", out)
        self.assertIn('sb tell w1 "wrap up and run sb done"', out)
        # Not the unread branch's sentence, which would blame it for silence of ours.
        self.assertNotIn("0 unread", out)

    def test_mine_is_the_callers_own_subtree(self):
        store.create_agent(self.db, name="root", role="lead")
        store.create_agent(self.db, name="me", role="lead", parent="root")
        store.create_agent(self.db, name="kid", role="worker", parent="me")
        store.create_agent(self.db, name="grandkid", role="worker", parent="kid")
        store.create_agent(self.db, name="stranger", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="me")
        self.assertEqual([a.name for a in snap.agents], ["me", "kid", "grandkid"])

    def test_mine_never_climbs_back_out_to_a_parent(self):
        """Ancestors exist to keep the indentation honest, not to widen the scope."""
        store.create_agent(self.db, name="root", role="lead")
        store.create_agent(self.db, name="me", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="me")
        self.assertEqual([a.name for a in snap.agents], ["me"])

    def test_mine_for_a_human_is_every_agent(self):
        store.create_agent(self.db, name="root", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="human")
        self.assertEqual([a.name for a in snap.agents], ["root", "kid"])
        self.assertEqual(snap.hidden, 0)

    def test_mine_for_somebody_with_no_agents_is_empty_not_everything(self):
        store.create_agent(self.db, name="root", role="lead")
        snap = status.collect(self.db, FakeHerdr(), mine="ghost")
        self.assertEqual(snap.agents, [])
        self.assertEqual(snap.hidden, 1)

    def test_filters_and_together(self):
        store.create_agent(self.db, name="me", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="me")
        store.create_agent(self.db, name="stranger", role="worker")
        store.set_state(self.db, "kid", "done")
        store.put_message(self.db, from_agent="x", to_agent="stranger", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr(), mine="me", live_only=True)
        self.assertEqual([a.name for a in snap.agents], ["me"])

    def test_a_cycle_does_not_hang_the_ancestor_walk_under_a_filter(self):
        store.create_agent(self.db, name="a", role="worker", parent="b")
        store.create_agent(self.db, name="b", role="worker", parent="a")
        store.set_state(self.db, "a", "blocked")
        snap = status.collect(self.db, FakeHerdr(), needs_me=True)
        self.assertIn("a", {x.name for x in snap.agents})

    # -- task and summary --------------------------------------------------

    def test_the_task_is_carried_and_rendered(self):
        """'who is doing what' is the most common question; the board must answer it."""
        store.create_agent(self.db, name="w1", role="worker", task="rewrite the parser")
        snap = status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertEqual(self.by_name(snap)["w1"].task, "rewrite the parser")
        self.assertIn("rewrite the parser", status.render(snap))

    def test_a_long_task_is_clipped_not_wrapped(self):
        store.create_agent(self.db, name="w1", role="worker", task="x " * 200)
        for line in status.render(status.collect(self.db, FakeHerdr([alive("w1")]))).splitlines():
            self.assertLessEqual(len(line), 140)

    def test_the_last_summary_is_shown_on_a_done_row(self):
        store.create_agent(self.db, name="w1", role="worker", task="rewrite the parser")
        store.put_message(self.db, from_agent="w1", to_agent="orch", kind="done",
                          body="[done] parser rewritten, 12 tests added")
        store.set_state(self.db, "w1", "done")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        a = self.by_name(snap)["w1"]
        self.assertEqual(a.summary, "parser rewritten, 12 tests added")   # no `[done] `
        self.assertIn("parser rewritten, 12 tests added", status.render(snap))

    def test_a_summary_is_not_shown_while_the_agent_is_still_running(self):
        """A summary on a `working` row would read as 'finished', which it is not."""
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="w1", to_agent="orch", kind="done",
                          body="[done] an earlier run")
        snap = status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertNotIn("an earlier run", status.render(snap))

    # -- output -----------------------------------------------------------

    def test_render_shows_every_required_field(self):
        store.create_agent(self.db, name="w1", role="researcher", workspace="feature-x")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "working")])))
        for expected in ("w1", "researcher", "working", "feature-x"):
            self.assertIn(expected, out)

    def test_render_names_drift_loudly(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")]),
                                           now=self.past_the_floor()))
        self.assertIn("STALLED", out)
        self.assertIn("sb done", out)             # says what was actually skipped

    def test_render_indents_children(self):
        store.create_agent(self.db, name="root", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        out = status.render(status.collect(self.db, FakeHerdr()))
        kid = next(l for l in out.splitlines() if l.lstrip().startswith("kid"))
        root = next(l for l in out.splitlines() if l.startswith("root"))
        self.assertTrue(kid.startswith("  "))
        self.assertFalse(root.startswith(" "))

    def test_the_summary_leads_with_alive_and_keeps_the_rest(self):
        """The number a person reads first was the one with least to do with now: the
        line opened `51 agents · 1 alive · 253 hidden`. Alive leads; nothing is dropped."""
        snap = status.Snapshot(now=0, hidden=253, agents=[
            status.AgentStatus(
                name=f"a{i}", role="worker", parent=None, depth=0, state="working",
                herdr_state="working", alive=(i == 0), stalled=False, gone=False,
                unread=0, age=1, idle=1, last_activity=0, workspace=None, task=None,
                blocked_why=None)
            for i in range(51)])
        line = status.summary_line(snap)
        self.assertTrue(line.startswith("1 alive"), line)
        self.assertIn("51 agents", line)
        self.assertIn("253 hidden", line)
        self.assertLess(line.index("51 agents"), line.index("253 hidden"))
        self.assertGreater(line.index("51 agents"), line.index("1 alive"))

    def test_render_survives_an_empty_store(self):
        self.assertIn("no agents", status.render(status.collect(self.db, FakeHerdr())))

    def test_json_carries_the_same_facts(self):
        store.create_agent(self.db, name="root", role="lead", workspace="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root",
                           session_id="s1")
        store.put_message(self.db, from_agent="x", to_agent="kid", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr([alive("root"), alive("kid", "idle")]),
                              now=self.past_the_floor())
        d = json.loads(json.dumps(snap.as_dict()))          # must be plain JSON types

        self.assertEqual(d["herdr"], "ok")
        self.assertEqual([a["name"] for a in d["agents"]], ["root", "kid"])
        kid = d["agents"][1]
        self.assertEqual(kid["parent"], "root")
        self.assertEqual(kid["depth"], 1)
        self.assertEqual(kid["state"], "working")
        self.assertEqual(kid["herdr_state"], "idle")
        self.assertTrue(kid["alive"])
        self.assertTrue(kid["stalled"])
        self.assertTrue(kid["needs_human"])
        self.assertEqual(kid["unread"], 1)
        self.assertIn("age", kid)
        self.assertIn("idle", kid)
        self.assertEqual(d["agents"][0]["workspace"], "main")
        self.assertEqual(d["counts"]["stalled"], 1)
        self.assertEqual(d["counts"]["unread"], 1)


class StatusCliTest(unittest.TestCase):
    """The wiring: `sb status` must parse, and `--json` must work on either side."""

    def test_active_is_the_same_flag_as_live(self):
        """`--live` is in scripts and in muscle memory; one dest, so they cannot differ."""
        from switchboard.cli import build_parser
        self.assertTrue(build_parser().parse_args(["status", "--active"]).live)

    def test_every_subcommand_takes_json_on_either_side(self):
        """cli.py has always documented `--json` as per-command. It was global-only, and
        the first three spawn attempts of the QA run died on `sb delegate ... --json`.

        Built from the parser's own subcommand list, so a verb added later is covered
        without anyone remembering to add it here.
        """
        from switchboard.cli import build_parser
        sample = {                                  # a minimal legal argv per verb
            "start": [], "delegate": ["do a thing"],
            "tell": ["w1", "hi"], "inbox": [], "done": ["finished"], "block": ["why"],
            "status": [], "presets": [], "models": [], "init": [], "doctor": [],
            "cleanup": [], "workspace": ["list"], "restore": ["w1"],
            "grant": ["w1", "spawn"],
            "who-holds": ["spawn"],
            "merge": ["w1"],
            "inspect": ["w1"], "log": [],
            "board": [], "flush": [], "reconcile": [], "sweep": [],
            # Retired: a hard error naming `sb presets` and `sb plugin list`. Still parsed,
            # so it can print that instead of an argparse usage dump.
            "plugins": [],
            # A namespace, not a verb. Its own arguments are a REMAINDER handed to the
            # subparser sb builds from the plugin's declaration, so `--json` typed AFTER a
            # plugin name belongs to that parser rather than this one — `sb plugin todo
            # list --json` still emits JSON, and `tests/test_plugins.py` is where that is
            # checked. With no name typed there is no remainder yet, so the rule below
            # holds here too.
            "plugin": [],
        }
        verbs = build_parser()._subparsers._group_actions[0].choices
        self.assertEqual(set(verbs), set(sample), "a verb was added or removed")
        for verb, rest in sample.items():
            with self.subTest(verb=verb):
                after = build_parser().parse_args([verb, *rest, "--json"])
                before = build_parser().parse_args(["--json", verb, *rest])
                plain = build_parser().parse_args([verb, *rest])
                self.assertTrue(after.json)
                self.assertTrue(before.json)     # the per-command flag must not undo this
                self.assertFalse(plain.json)

    def test_naming_an_agent_is_spelled_the_same_way_everywhere(self):
        """One way to name an agent: `--name`, on both verbs that spawn. `--agent` was
        the odd one out on `sb workspace new`, and went with it."""
        from switchboard.cli import build_parser
        for argv in (["start", "--name", "x"], ["delegate", "t", "--name", "x"]):
            self.assertEqual(build_parser().parse_args(argv).name, "x")
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["delegate", "t", "--agent", "x"])

    def test_a_missing_thing_reads_the_same_whichever_verb_named_it(self):
        """`str(KeyError)` adds quotes and `str(ValueError)` does not, so half the errors
        printed came out quoted and half did not, for no reason a reader could see."""
        from switchboard.cli import _reason
        self.assertEqual(_reason(KeyError("no such agent: w1")), "no such agent: w1")
        self.assertEqual(_reason(ValueError("no such agent: w1")), "no such agent: w1")
        self.assertEqual(_reason(KeyError()), "")

class StatusArchivedCliTest(unittest.TestCase):
    """`sb status` end to end, because the parser alone cannot see the wiring.

    A flag that parses and is then dropped on the way to `render` looks identical to a
    working one from the parser's side, and so does a call site that passes `False` where
    it should pass "no opinion" and let `display.show_archived` answer.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        for cmd in (["git", "init", "-q", "-b", "main"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, cwd=self.repo, capture_output=True)

        db = store.connect(self.repo)
        store.create_agent(db, name="lead", role="lead", session_id="s0")
        store.create_agent(db, name="w1", role="worker", parent="lead", session_id="s1")
        old = store.now() - int(status.SPAWN_GRACE) - 1     # past the spawn grace
        db.execute("UPDATE agents SET created_at = ?", (old,))
        db.commit()
        db.close()

        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        # herdr answers, and lists nobody: `alive is False`, which is what archived needs.
        # Patched on `cli`, not on `herdr`: cli did `from .herdr import Herdr` at import
        # time, so replacing the attribute on the herdr module leaves cli holding the real
        # class and the run quietly shells out to a herdr binary instead of to this fake.
        h = mock.patch.object(cli_mod, "Herdr", lambda *a, **k: FakeHerdr([]))
        h.start()
        self.addCleanup(h.stop)

    def run_sb(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_mod.main(list(argv))
        self.assertEqual(code, 0, err.getvalue())
        return out.getvalue()

    def tree(self, text):
        return text.split("\n\n")[0]

    def test_sb_status_collapses_by_default(self):
        self.assertIn("archived", self.tree(self.run_sb("status")))
        self.assertNotIn("w1", self.tree(self.run_sb("status")))

    def test_the_archived_flag_reaches_the_renderer(self):
        """Not just that it parses — that the value arrives."""
        self.assertIn("w1", self.tree(self.run_sb("status", "--archived")))

    def test_a_repo_that_sets_show_archived_gets_it_without_passing_a_flag(self):
        """The call site must pass "no opinion", not `False`. Passing `False` parses the
        same, renders the same by default, and silently ignores the setting forever."""
        sb = self.repo / ".switchboard"
        sb.mkdir()
        (sb / "settings.toml").write_text("[display]\nshow_archived = true\n")
        with mock.patch.object(status, "SHOW_ARCHIVED",
                               config.flag("display.show_archived", self.repo)):
            self.assertIn("w1", self.tree(self.run_sb("status")))

    def test_json_carries_every_row_whatever_the_tree_does(self):
        payload = json.loads(self.run_sb("status", "--json"))
        self.assertEqual(sorted(a["name"] for a in payload["agents"]), ["lead", "w1"])
        self.assertTrue(all(a["archived"] for a in payload["agents"]))


class ReconcileReapsTest(unittest.TestCase):
    """`sb reconcile` is where failure detection meets a path that runs by itself.

    `collect(reap=True)` used to have exactly one caller — `sb status` — so a dead child
    was recorded, and its parent pinged, only when somebody happened to look at the board.
    The collector already spawns `sb reconcile` on its own loop, so that is the verb this
    moved onto. End to end through `cli.main`, because the wiring is the whole claim.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        for cmd in (["git", "init", "-q", "-b", "main"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(cmd, cwd=self.repo, capture_output=True)

        db = store.connect(self.repo)
        store.create_agent(db, name="lead", role="lead", session_id="s0")
        store.create_agent(db, name="w1", role="worker", parent="lead", session_id="s1",
                           task="rewrite the parser")
        db.execute("UPDATE agents SET created_at = ?",
                   (store.now() - int(status.SPAWN_GRACE) - 1,))
        db.commit()
        db.close()

        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        # herdr answers and has the lead but not w1 — the pane closed under it.
        self.enterContext(mock.patch.object(
            cli_mod, "Herdr", lambda *a, **k: self.FakeSb([alive("lead", "idle")])))
        # The debounce is not what is under test here; two readings are.
        self.enterContext(mock.patch.object(status, "GONE_CONFIRM_GRACE", 0))

    class FakeSb(FakeHerdr):
        def prompt(self, who, text):
            return None

    def run_sb(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_mod.main(list(argv))
        self.assertEqual(code, 0, err.getvalue())
        return out.getvalue()

    def state_of(self, name):
        db = store.connect(self.repo)
        try:
            return store.get_agent(db, name)["state"]
        finally:
            db.close()

    def test_sb_reconcile_records_the_death_and_tells_the_parent(self):
        self.run_sb("reconcile")
        self.run_sb("reconcile")            # the second reading is what confirms it
        self.assertEqual(self.state_of("w1"), status.GONE_STATE)
        db = store.connect(self.repo)
        self.addCleanup(db.close)
        [m] = store.unread_for(db, "lead", mark=False)
        self.assertEqual((m["kind"], m["from_agent"]), ("failed", "w1"))

    def test_the_other_unattended_verb_still_reaps_nothing(self):
        """`sb flush` runs at the top of every `sb` command and asks herdr nothing when the
        mailbox is quiet. Reaping there would buy an `agent list` subprocess for every
        `sb log` in the fleet, so the placement is deliberate rather than incidental."""
        for _ in range(3):
            self.run_sb("flush")
        self.assertEqual(self.state_of("w1"), "working")


class ArchivedTest(unittest.TestCase):
    """The `archived` predicate: absent from herdr, past the grace, never written.

    The store half is real, so "never written" is checked against the database rather
    than argued.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def old(self):
        """A `now` far enough ahead that the spawn grace has certainly passed."""
        return store.now() + int(status.SPAWN_GRACE) + 1

    def collect(self, herdr, **kw):
        kw.setdefault("reap", False)
        return status.collect(self.db, herdr, **kw)

    def by_name(self, snap):
        return {a.name: a for a in snap.agents}

    def tree(self, snap, **kw):
        """Just the tree body — collapse touches that and nothing below it.

        Asserting against the whole readout would be the wrong test: an archived agent is
        still named in DRIFT, in NEEDS YOU and in UNDELIVERED, deliberately.
        """
        body = status.render(snap, **kw).split("\n\n")[0].splitlines()
        return "\n".join(body[1:])          # drop the column header

    # -- the predicate ----------------------------------------------------

    def test_an_agent_herdr_no_longer_lists_is_archived_once_the_grace_has_passed(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        a = self.by_name(self.collect(FakeHerdr([]), now=self.old()))["w1"]
        self.assertTrue(a.archived)

    def test_an_agent_herdr_still_lists_is_never_archived(self):
        """Including one that has reported done: it is on herdr, so it can still be
        clicked, read and talked to."""
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "done")
        a = self.by_name(self.collect(FakeHerdr([alive("w1", "idle")]), now=self.old()))["w1"]
        self.assertFalse(a.archived)

    def test_an_agent_mid_spawn_is_not_archived_and_stays_on_the_board(self):
        """herdr does not list an agent until it has started, and a spawn is retried for
        minutes. Without the grace every new agent vanishes from the board during its own
        spawn — the row the human is waiting to see appear is the row that disappears."""
        store.create_agent(self.db, name="lead", role="lead")
        store.create_agent(self.db, name="w1", role="worker", parent="lead")
        snap = self.collect(FakeHerdr([alive("lead")]))          # w1 not started yet
        self.assertFalse(self.by_name(snap)["w1"].archived)
        self.assertIn("w1", status.render(snap))

    def test_a_herdr_outage_archives_nothing_and_the_whole_tree_still_draws(self):
        """The failure this predicate exists to survive. Absent herdr's answer every row
        looks missing, and a naive read collapses a live fleet to one `+ N archived` line
        on a subprocess hiccup. `alive` is None, not False, so nothing qualifies."""
        for n in ("lead", "w1", "w2"):
            store.create_agent(self.db, name=n, role="worker",
                               parent=None if n == "lead" else "lead")
        snap = self.collect(FakeHerdr(error=HerdrError("down", "no server")),
                            now=self.old())
        self.assertEqual([a.alive for a in snap.agents], [None, None, None])
        self.assertFalse(any(a.archived for a in snap.agents))
        out = status.render(snap)
        for n in ("lead", "w1", "w2"):
            self.assertIn(n, out)
        self.assertNotIn("archived", out)

    def test_archived_does_not_read_the_stores_state(self):
        """Archived means one thing — herdr does not have this pane. What the store
        believes is the STATE column's question, and `blocked` must not buy an exemption
        (nor `working`, nor `done`)."""
        for n, st in (("a", "working"), ("b", "blocked"), ("c", "done")):
            store.create_agent(self.db, name=n, role="worker", session_id=f"s-{n}")
            store.set_state(self.db, n, st)
        by = self.by_name(self.collect(FakeHerdr([]), now=self.old()))
        self.assertEqual([by[n].archived for n in "abc"], [True, True, True])

    # -- never stored -----------------------------------------------------

    def test_drawing_an_archived_agent_writes_nothing_at_all(self):
        """The whole safety argument. This is the same signal that ended live agents when
        it was RECORDED; it is only safe because a wrong guess costs one frame."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        before = dict(store.get_agent(self.db, "w1"))
        events = self.db.execute("SELECT count(*) FROM events").fetchone()[0]

        snap = self.collect(FakeHerdr([]), now=self.old())
        status.render(snap)

        self.assertTrue(self.by_name(snap)["w1"].archived)
        self.assertEqual(dict(store.get_agent(self.db, "w1")), before)
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], events)

    def test_archived_is_a_property_and_not_a_column(self):
        """A collector can run for hours against a stale SPAWN_GRACE. A property makes
        every renderer decide with its own code; a field would let a renderer draw a rule
        some older process decided.

        Pinned two ways because they fail differently: the field check is what a careless
        `archived: bool = False` in the dataclass trips, and `getattr_static` is what
        catches it being replaced by anything that is no longer computed per read.
        """
        self.assertNotIn("archived", {f.name for f in dataclasses.fields(status.AgentStatus)})
        self.assertIsInstance(inspect.getattr_static(status.AgentStatus, "archived"), property)

    def test_json_carries_archived_and_a_reader_recomputes_it_rather_than_reading_it(self):
        """The key is in `--json` for consumers, and the round trip drops it: a renderer
        rebuilding an `AgentStatus` gets the answer ITS OWN code gives for the `alive` and
        `age` it was handed, never the answer a collector running older code wrote down.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        d = self.by_name(self.collect(FakeHerdr([]), now=self.old()))["w1"].as_dict()
        self.assertTrue(d["archived"])

        fields = {f.name for f in dataclasses.fields(status.AgentStatus)}
        self.assertNotIn("archived", fields)
        # The stale flag says archived; the inputs say herdr could not be reached. The
        # inputs win, which is the whole reason it is a property.
        back = status.AgentStatus(**{k: v for k, v in d.items() if k in fields} | {"alive": None})
        self.assertFalse(back.archived)

    # -- render -----------------------------------------------------------

    def test_the_counts_still_count_every_agent_a_collapse_hid(self):
        """Collapse shortens the tree, not the readout."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s0")
        store.create_agent(self.db, name="w1", role="worker", parent="lead", session_id="s1")
        snap = self.collect(FakeHerdr([]), now=self.old())
        self.assertEqual(snap.counts["agents"], 2)
        self.assertIn("2 agents", status.render(snap))

    def test_an_archived_agent_that_needs_a_person_is_still_named_in_full(self):
        """The sharp end of "archived is archived". A blocked agent whose pane died is a
        question nobody can answer any more, so it may be collapsed out of the tree but it
        must not become invisible: NEEDS YOU reads `snap.agents` and never sees collapse.
        """
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        store.set_state(self.db, "w1", "blocked")
        store.log_event(self.db, kind="blocked", agent="w1", why="which database?")
        snap = self.collect(FakeHerdr([]), now=self.old())
        out = status.render(snap)

        self.assertEqual(self.tree(snap), "+ 1 archived · 1 need you")
        self.assertIn("w1", out)                    # by name, below, in NEEDS YOU
        self.assertIn("which database?", out)

    def test_the_setting_decides_when_no_caller_has_an_opinion(self):
        """`display.show_archived`. A caller that passes nothing must not silently
        hard-code a default of its own, or the setting is a setting in name only."""
        store.create_agent(self.db, name="lead", role="lead", session_id="s0")
        store.create_agent(self.db, name="w1", role="worker", parent="lead", session_id="s1")
        snap = self.collect(FakeHerdr([]), now=self.old())

        self.assertIs(status.SHOW_ARCHIVED, False)          # what the repo ships
        self.assertNotIn("w1", self.tree(snap))
        with mock.patch.object(status, "SHOW_ARCHIVED", True):
            self.assertIn("w1", self.tree(snap))
            self.assertNotIn("archived", self.tree(snap))

    def test_a_board_of_nothing_but_archived_agents_still_renders(self):
        """Every root collapses, so there is no agent left to size the ROLE column
        against — which is a crash, not a narrower table, if the widths are taken from
        `max(x, *rows)`."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = self.collect(FakeHerdr([]), now=self.old())
        self.assertEqual(self.tree(snap), "+ 1 archived")


def _mk(name, *, parent=None, depth=0, archived=False, needs_human=False):
    """One `AgentStatus`, archived or not, via the real predicate.

    `alive=False` plus a big `age` is what being absent from herdr looks like after the
    grace; `alive=True` is what herdr listing it looks like. Nothing here mocks
    `archived` — these tests fail if the predicate changes meaning.
    """
    return status.AgentStatus(
        name=name, role="worker", parent=parent, depth=depth,
        state="blocked" if needs_human else "working", herdr_state=None,
        alive=False if archived else True,
        stalled=False, gone=False, unread=0,
        age=int(status.SPAWN_GRACE) + 1 if archived else 0,
        idle=0, last_activity=0, workspace=None, task=None,
        blocked_why="?" if needs_human else None,
    )


class CollapseTest(unittest.TestCase):
    """The tree rule, over the worked examples in `.switchboard/design/archived.md` §4.2.

    Pure: `display_rows` takes the rows it is given and touches neither store nor herdr.
    """

    def rows(self, agents, **kw):
        """What gets drawn: agent names in order, and `+N` for a collapsed row."""
        return [f"+{r.count}" if isinstance(r, status.Collapsed) else r.name
                for r in status.display_rows(agents, **kw)]

    def groups(self, agents, **kw):
        return [r for r in status.display_rows(agents, **kw)
                if isinstance(r, status.Collapsed)]

    def test_example_a_all_children_archived_becomes_one_row(self):
        agents = [_mk("main"),
                  _mk("a", parent="main", depth=1, archived=True),
                  _mk("b", parent="main", depth=1, archived=True)]
        self.assertEqual(self.rows(agents), ["main", "+2"])
        self.assertEqual(self.groups(agents)[0].depth, 1)   # the level they were drawn at

    def test_example_b_nested_levels_give_one_row_at_the_highest_level(self):
        """Not a chain of `+ 1 archived` at each depth — the collapse root is the HIGHEST
        sealed node, so its sealed children are inside its subtree, not separate groups."""
        agents = [_mk("main"),
                  _mk("lead", parent="main", depth=1, archived=True),
                  _mk("w1", parent="lead", depth=2, archived=True),
                  _mk("w2", parent="lead", depth=2, archived=True),
                  _mk("w2a", parent="w2", depth=3, archived=True)]
        self.assertEqual(self.rows(agents), ["main", "+4"])
        self.assertEqual(len(self.groups(agents)), 1)
        self.assertEqual(self.groups(agents)[0].depth, 1)

    def test_example_d_groups_at_two_levels_at_once(self):
        agents = [_mk("main"),
                  _mk("lead", parent="main", depth=1),
                  _mk("w2", parent="lead", depth=2),
                  _mk("g1", parent="w2", depth=3, archived=True),
                  _mk("g2", parent="w2", depth=3, archived=True),
                  _mk("w1", parent="lead", depth=2, archived=True),
                  _mk("w3", parent="lead", depth=2, archived=True),
                  _mk("w3a", parent="w3", depth=3, archived=True),
                  _mk("other", parent=None, depth=0, archived=True),
                  _mk("o1", parent="other", depth=1, archived=True),
                  _mk("g0", parent=None, depth=0, archived=True)]
        self.assertEqual(self.rows(agents), ["main", "lead", "w2", "+2", "+3", "+3"])
        self.assertEqual([g.depth for g in self.groups(agents)], [3, 2, 0])

    def test_example_f_an_archived_parent_with_a_live_child_is_drawn_not_hidden(self):
        """The shape the invariant says must not exist. It is not a rendering case: the
        rule declines to hide a parent whose child must be drawn, and that falls out of
        `sealed` rather than being handled."""
        agents = [_mk("lead", archived=True),
                  _mk("w1", parent="lead", depth=1),
                  _mk("w2", parent="lead", depth=1, archived=True)]
        self.assertEqual(self.rows(agents), ["lead", "w1", "+1"])

    def test_the_row_carries_how_many_of_the_hidden_still_need_a_person(self):
        agents = [_mk("main"),
                  _mk("a", parent="main", depth=1, archived=True, needs_human=True),
                  _mk("b", parent="main", depth=1, archived=True, needs_human=True),
                  _mk("c", parent="main", depth=1, archived=True)]
        g = self.groups(agents)[0]
        self.assertEqual((g.count, g.needs_human), (3, 2))
        self.assertEqual(status.collapsed_label(g), "  + 3 archived · 2 need you")

    def test_a_row_whose_parent_was_filtered_out_is_a_root_here(self):
        """Computed over the rows it is GIVEN. `--mine` and `--live` have already dropped
        rows, and re-deriving the tree from the store would collapse against a tree the
        caller is not looking at."""
        agents = [_mk("w1", parent="missing", depth=1, archived=True)]
        self.assertEqual(self.rows(agents), ["+1"])

    def test_a_cycle_is_one_group_and_does_not_hang(self):
        """`_tree` breaks cycles rather than following them and shows the stranded rows at
        the left margin; this must do the same instead of recursing forever."""
        a = _mk("x", parent="y", archived=True)
        b = _mk("y", parent="x", archived=True)
        self.assertEqual(self.rows([a, b]), ["+2"])

    def test_the_real_board_collapses_to_the_measured_shape(self):
        """The live store on the night this was designed: 64 rows, 55 of them archived,
        9 alive. The whole point of the exercise is this number."""
        live = {"main", "status-board", "panel-core", "fix-invariant", "archived-2",
                "prompt-work", "t-done", "t-bug", "t-block"}
        tree = [("main", None), ("status-board", "main"), ("prompt-work", "main")]
        tree += [("panel-core", "status-board"), ("fix-invariant", "status-board"),
                 ("archived-2", "status-board")]
        tree += [(n, "prompt-work") for n in ("t-done", "t-bug", "t-block")]
        tree += [(f"sb-{i}", "status-board") for i in range(17)]      # sealed leaves
        tree += [("plugins-redesign-lead", "main")]
        tree += [(f"pr-{i}", "plugins-redesign-lead") for i in range(16)]
        tree += [("workspace-model-lead", "main")]
        tree += [(f"wm-{i}", "workspace-model-lead") for i in range(11)]
        tree += [("spawn-prompts", "main")]
        tree += [(f"sp-{i}", "spawn-prompts") for i in range(6)]
        tree += [("workspace-debug", "main"), ("sb-guard", "main")]

        depth = {}
        agents = []
        for name, parent in tree:
            depth[name] = 0 if parent is None else depth[parent] + 1
            agents.append(_mk(name, parent=parent, depth=depth[name],
                              archived=name not in live))
        self.assertEqual(len(agents), 64)
        self.assertEqual(sum(1 for a in agents if a.archived), 55)

        self.assertEqual(
            self.rows(agents),
            ["main", "status-board", "panel-core", "fix-invariant", "archived-2", "+17",
             "prompt-work", "t-done", "t-bug", "t-block", "+38"])
        self.assertEqual(len(status.display_rows(agents)), 11)


class BoardRowsTest(unittest.TestCase):
    """The BOARD's rule, which is not `sb status`'s: agents only, and never a stand-in.

    Pure, like `display_rows`: the rows it is given, and neither store nor herdr.
    """

    def rows(self, agents, **kw):
        got = status.board_rows(agents, **kw)
        self.assertTrue(all(isinstance(r, status.AgentStatus) for r in got))
        return [r.name for r in got]

    def test_a_finished_subtree_is_dropped_with_nothing_standing_in_for_it(self):
        """Where `sb status` draws `+ 2 archived`, the board draws nothing at all."""
        agents = [_mk("main"),
                  _mk("lead", parent="main", depth=1, archived=True),
                  _mk("w1", parent="lead", depth=2, archived=True)]
        self.assertEqual(self.rows(agents), ["main"])
        self.assertEqual(self.rows(agents, show_archived=True), ["main", "lead", "w1"])

    def test_archived_with_no_live_ancestor_is_never_drawn_even_under_a(self):
        """The dispatcher that owned this tree is gone, so `a` is not about it. The live
        tree beside it shows its archived rows, which is what `a` is for."""
        agents = [_mk("main"),
                  _mk("kid", parent="main", depth=1, archived=True),
                  _mk("old", archived=True),
                  _mk("older", parent="old", depth=1, archived=True)]
        self.assertEqual(self.rows(agents, show_archived=True), ["main", "kid"])
        self.assertEqual(self.rows(agents), ["main"])

    def test_an_archived_row_with_a_live_descendant_is_always_kept(self):
        """Both directions of the invariant: no live row is ever hidden, and no row a
        live row hangs off is either — with `a` on or off, the tree stays connected."""
        agents = [_mk("old", archived=True),
                  _mk("lead", parent="old", depth=1, archived=True),
                  _mk("live", parent="lead", depth=2)]
        self.assertEqual(self.rows(agents), ["old", "lead", "live"])
        self.assertEqual(self.rows(agents, show_archived=True), ["old", "lead", "live"])

    def test_a_cycle_is_broken_rather_than_followed(self):
        """Two archived rows that parent each other are their own ancestors and nobody
        else's — no live ancestor, no live descendant, and no hang either."""
        agents = [_mk("a", parent="b", archived=True), _mk("b", parent="a", archived=True)]
        self.assertEqual(self.rows(agents), [])
        self.assertEqual(self.rows(agents, show_archived=True), [])


class NeedsSettleTest(unittest.TestCase):
    """The NEEDS YOU debounce: `stamp_needs_for` times a summons, `settled` gates it.

    Two decisions are pinned here and nothing else. WHICH summonses are debounced — the
    inferred ones only, so a block a human is waiting on is never held back — and that the
    timing is CONTINUOUS, so a row that goes quiet, works, and goes quiet again starts its
    window again rather than inheriting the old one. Both are the difference between a
    debounce and a delay.
    """

    def row(self, name="w1", **kw):
        kw.setdefault("state", "working")
        return status.AgentStatus(
            name=name, role="worker", parent=None, depth=0,
            herdr_state=kw.pop("herdr_state", "idle"), alive=True,
            stalled=kw.pop("stalled", False), gone=False, unread=0, age=100,
            idle=kw.pop("idle", 60), last_activity=0, workspace=None, task=None,
            blocked_why=kw.pop("blocked_why", None), **kw)

    def snap(self, *rows, now):
        return status.Snapshot(now=now, agents=list(rows))

    def test_a_summons_is_unsettled_until_it_has_held_for_the_window(self):
        a = self.row(stalled=True)
        snap = self.snap(a, now=1000)
        since = status.stamp_needs_for(snap, {})
        self.assertEqual(a.needs_for, 0)
        self.assertFalse(a.settled)

        later = self.row(stalled=True)
        status.stamp_needs_for(self.snap(later, now=1000 + int(status.NEEDS_SETTLE)), since)
        self.assertEqual(later.needs_for, int(status.NEEDS_SETTLE))
        self.assertTrue(later.settled)

    def test_a_summons_that_lapses_starts_its_window_again(self):
        """The turn gap this whole thing exists for, twice: idle, working, idle again is
        two short summonses and not one long one."""
        first = self.row(stalled=True)
        since = status.stamp_needs_for(self.snap(first, now=1000), {})
        working = self.row(stalled=False)
        since = status.stamp_needs_for(self.snap(working, now=1010), since)
        self.assertEqual(since, {})                       # dropped, not zeroed
        again = self.row(stalled=True)
        status.stamp_needs_for(self.snap(again, now=1020), since)
        self.assertEqual(again.needs_for, 0)
        self.assertFalse(again.settled)

    def test_a_block_and_an_unwatched_row_are_never_held_back(self):
        """`blocked` is a word the agent wrote, so it is drawn the instant it is seen —
        and a row nobody timed (`sb status`, an older collector) is shown, never hidden."""
        blocked = self.row(state="blocked", blocked_why="which pane?")
        status.stamp_needs_for(self.snap(blocked, now=1000), {})
        self.assertIsNone(blocked.needs_for)              # not an inferred summons at all
        self.assertTrue(blocked.settled)
        self.assertTrue(self.row(stalled=True).settled)   # never stamped -> unknown -> show


class AwaitingKeypressTest(unittest.TestCase):
    """The narrower label on top of STALLED, and the two things it must not cost.

    The payloads below are not hand-written: they are what `herdr agent explain --json`
    actually answered when re-run against the pane text of `research/modal-captures/01`
    (a first-run theme picker) and `07` (an agent that ended its turn without `sb done`
    and is sitting at an ordinary prompt — honest STALLED, the case this must never
    claim). Clipped to the three keys the rule reads, which is also what pins the rule to
    reading only those.

    No fake herdr models pane content and none is grown to: the decision is a plain
    function over one parsed payload, and the wiring is exercised by calling it with a
    stub that counts who it was asked about. What that leaves unproven is the real
    subprocess — that `herdr agent explain <name> --json` is spelled right and parses —
    which only a live run can show.
    """

    def setUp(self):
        status._KEYPRESS_SEEN.clear()

    tearDown = setUp

    @staticmethod
    def row(name, *, stalled=False, idle_excuse=None, idle=600):
        return status.AgentStatus(
            name=name, role="worker", parent=None, depth=0, state="working",
            herdr_state="idle", alive=True, stalled=stalled, gone=False, unread=0,
            age=600, idle=idle, last_activity=0, workspace=None, task=None,
            blocked_why=None, idle_excuse=idle_excuse)

    MODAL = {"state": "idle", "matched_rule": None,
             "fallback_reason": "default_known_agent_idle_fallback"}
    AT_PROMPT = {"state": "idle", "fallback_reason": None,
                 "matched_rule": {"id": "live_prompt_box", "priority": 950,
                                  "region": "prompt_box_body", "state": "idle"}}

    def test_only_an_unmatched_screen_counts_and_anything_unreadable_is_no_opinion(self):
        self.assertTrue(status.awaiting_keypress_screen(self.MODAL))
        # Capture 07. A matched rule is herdr recognising the screen, whatever it matched.
        self.assertFalse(status.awaiting_keypress_screen(self.AT_PROMPT))
        for junk in (None, "", {}, [], {"matched_rule": None, "fallback_reason": "other"},
                     {"matched_rule": None,
                      "fallback_reason": "default_known_agent_idle_fallback",
                      "state": "working"}):
            self.assertFalse(status.awaiting_keypress_screen(junk), junk)

    def test_only_already_stalled_rows_cost_a_subprocess(self):
        """The whole cost story: idle stays free, and a row that is merely idle-looking
        — starting up, waiting on a child, working — is never even asked about, so this
        can never pull a STARTING agent into the state."""
        asked = []

        class Spy:
            def explain_agent(_, name):
                asked.append(name)
                return AwaitingKeypressTest.MODAL

        rows = [
            self.row("stuck", stalled=True),
            self.row("working"),                                     # not stalled
            self.row("starting", idle_excuse="starting up"),         # excused, not stalled
            self.row("waiting", idle_excuse="waiting on children"),  # ditto
        ]
        status._mark_awaiting_keypress(Spy(), rows, 1000)
        self.assertEqual(asked, ["stuck"])
        self.assertEqual([a.name for a in rows if a.awaiting_keypress], ["stuck"])

        # Failure is no opinion, never `modal` — the required degrade. A herdr that times
        # out, and one that has never heard of the question, both leave the row with the
        # STALLED it already had rather than a claim nothing observed.
        class Broken:
            def explain_agent(_, name):
                raise HerdrError("timeout", "herdr did not return")

        status._KEYPRESS_SEEN.clear()
        rows[0].awaiting_keypress = False
        status._mark_awaiting_keypress(Broken(), rows, 2000)
        status._mark_awaiting_keypress(FakeHerdr(), rows, 3000)
        self.assertFalse(any(a.awaiting_keypress for a in rows))
        self.assertTrue(rows[0].stalled)

    def test_the_board_at_half_a_second_does_not_pay_for_the_same_stall_every_tick(self):
        """The two gates the 0.5 s refresh added. A stall that has not held for the
        settle window is not asked about at all — it is not going to be drawn as a
        summons either — and a stall that HAS held is asked about once per
        `KEYPRESS_PROBE_GAP`, not once per frame, which is the difference between 4 ms
        and 240 ms on a tick that is only 500 ms long."""
        asked = []

        class Spy:
            def explain_agent(_, name):
                asked.append(name)
                return AwaitingKeypressTest.MODAL

        fresh = [self.row("gap", stalled=True, idle=int(status.NEEDS_SETTLE) - 1)]
        status._mark_awaiting_keypress(Spy(), fresh, 1000)
        self.assertEqual(asked, [])                     # a turn gap costs nothing
        self.assertFalse(fresh[0].awaiting_keypress)

        # Held. Asked once, then answered from the last reading for the whole gap, and
        # asked again on the far side of it.
        for t in range(1000, 1000 + int(status.KEYPRESS_PROBE_GAP), 5):
            row = self.row("stuck", stalled=True)
            status._mark_awaiting_keypress(Spy(), [row], t)
            self.assertTrue(row.awaiting_keypress)      # the label holds between probes
        self.assertEqual(asked, ["stuck"])
        status._mark_awaiting_keypress(
            Spy(), [self.row("stuck", stalled=True)], 1000 + int(status.KEYPRESS_PROBE_GAP))
        self.assertEqual(asked, ["stuck", "stuck"])

    def test_a_booting_agent_is_not_asked_about_however_its_row_got_there(self):
        """qa-10 caught a real one: `sb restore` keeps the session id and clears the turn,
        so the startup grace does not cover it, and a resumed Claude still drawing its
        splash screen read AWAITING KEYPRESS for ~1.25 s. The settle gate closes it from
        the other end — restore logs an event, so the row's idle clock is at zero and
        stays under the window for the whole boot, whatever its session id says."""
        asked = []

        class Spy:
            def explain_agent(_, name):
                asked.append(name)
                return AwaitingKeypressTest.MODAL

        restored = self.row("restored", stalled=True, idle=1)   # `restore` just fired
        status._mark_awaiting_keypress(Spy(), [restored], 1000)
        self.assertEqual(asked, [])
        self.assertFalse(restored.awaiting_keypress)

    def test_no_row_s_label_depends_on_who_else_is_stalled(self):
        """The other one qa-10 caught: with a small cap over `agents` order, an unrelated
        agent stalling flipped a parked modal between AWAITING KEYPRESS and STALLED frame
        after frame. A row's answer must be a fact about its own pane."""
        seen = []

        class Spy:
            def explain_agent(_, name):
                return (AwaitingKeypressTest.MODAL if name == "modal"
                        else AwaitingKeypressTest.AT_PROMPT)

        for tick, others in enumerate([1, 9, 2, 9, 30, 0]):
            rows = [self.row(f"other-{i}", stalled=True) for i in range(others)]
            rows.append(self.row("modal", stalled=True))
            status._mark_awaiting_keypress(Spy(), rows, 1000 + tick)
            seen.append({a.name: a.awaiting_keypress for a in rows}["modal"])
        self.assertEqual(seen, [True] * 6)


if __name__ == "__main__":
    unittest.main()
