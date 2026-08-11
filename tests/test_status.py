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


def alive(name, state="working"):
    return Agent(name=name, pane_id=f"w1:{name}", state=state)


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.connect(path=Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def by_name(self, snap):
        return {a.name: a for a in snap.agents}

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
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        a = self.by_name(snap)["w1"]
        self.assertTrue(a.stalled)
        self.assertEqual(a.state, "working")      # the store is reported, not rewritten
        self.assertEqual(a.herdr_state, "idle")

    def test_herdrs_derived_done_counts_as_idle(self):
        """herdr shows `done` for idle-and-unviewed; missing that hides real drift."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "done")]))
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
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("lead", "idle")])))["lead"]
        self.assertTrue(a.stalled)

    def test_an_ordinary_agent_is_stalled_from_the_start(self):
        """A delegated worker is given its work AT spawn, so it is stalled-eligible with
        no message ever arriving for it. The default has to be this way round: the failure
        that costs something is a stuck agent nobody is warned about."""
        store.create_agent(self.db, name="w1", role="worker", task="fix the parser",
                           session_id="s1")
        self.assertTrue(self.by_name(
            status.collect(self.db, FakeHerdr([alive("w1", "idle")])))["w1"].stalled)

    def test_a_store_without_the_column_still_reads(self):
        """The board and the collector hold a READ-ONLY connection and cannot migrate, so
        they meet a store an older `sb` last stamped. Missing reads as the label the row
        already had, rather than raising on every tick until a writer runs."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.db.execute("ALTER TABLE agents DROP COLUMN awaiting_task")
        self.db.commit()
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))["w1"]
        self.assertTrue(a.stalled)

    def test_an_agent_that_has_never_run_sb_is_not_stalled_yet(self):
        """The spurious nudge, from the other end. An agent two seconds out of `delegate`
        looks exactly like one whose turn ended and said nothing — its row is `working`,
        herdr says idle because no turn has started, and it holds no placeholder. It was
        pinged in that window (`audit/phase3-integration.md`). No session id means it has
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
        policy; see `BUGS.md` for the hole that leaves open.

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
        store.create_agent(self.db, name="root", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        store.create_agent(self.db, name="grandkid", role="worker", parent="kid")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual([(a.name, a.depth) for a in snap.agents],
                         [("root", 0), ("kid", 1), ("grandkid", 2)])

    def test_a_parent_immediately_precedes_its_children(self):
        store.create_agent(self.db, name="a", role="orchestrator")
        store.create_agent(self.db, name="b", role="orchestrator")
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
        store.create_agent(self.db, name="root", role="orchestrator")
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
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]), needs_me=True)
        self.assertEqual([a.name for a in snap.agents], ["w1"])
        self.assertTrue(self.by_name(snap)["w1"].needs_human)

    def test_a_stalled_agent_is_named_in_the_inbox_with_the_way_out(self):
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))
        self.assertIn("NEEDS YOU", out)
        self.assertIn("stalled", out)
        self.assertIn('sb tell w1 "wrap up and run sb done"', out)
        # Not the unread branch's sentence, which would blame it for silence of ours.
        self.assertNotIn("0 unread", out)

    def test_mine_is_the_callers_own_subtree(self):
        store.create_agent(self.db, name="root", role="orchestrator")
        store.create_agent(self.db, name="me", role="orchestrator", parent="root")
        store.create_agent(self.db, name="kid", role="worker", parent="me")
        store.create_agent(self.db, name="grandkid", role="worker", parent="kid")
        store.create_agent(self.db, name="stranger", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="me")
        self.assertEqual([a.name for a in snap.agents], ["me", "kid", "grandkid"])

    def test_mine_never_climbs_back_out_to_a_parent(self):
        """Ancestors exist to keep the indentation honest, not to widen the scope."""
        store.create_agent(self.db, name="root", role="orchestrator")
        store.create_agent(self.db, name="me", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="me")
        self.assertEqual([a.name for a in snap.agents], ["me"])

    def test_mine_for_a_human_is_every_agent(self):
        store.create_agent(self.db, name="root", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="human")
        self.assertEqual([a.name for a in snap.agents], ["root", "kid"])
        self.assertEqual(snap.hidden, 0)

    def test_mine_for_somebody_with_no_agents_is_empty_not_everything(self):
        store.create_agent(self.db, name="root", role="orchestrator")
        snap = status.collect(self.db, FakeHerdr(), mine="ghost")
        self.assertEqual(snap.agents, [])
        self.assertEqual(snap.hidden, 1)

    def test_filters_and_together(self):
        store.create_agent(self.db, name="me", role="orchestrator")
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
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))
        self.assertIn("STALLED", out)
        self.assertIn("sb done", out)             # says what was actually skipped

    def test_render_indents_children(self):
        store.create_agent(self.db, name="root", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        out = status.render(status.collect(self.db, FakeHerdr()))
        kid = next(l for l in out.splitlines() if l.lstrip().startswith("kid"))
        root = next(l for l in out.splitlines() if l.startswith("root"))
        self.assertTrue(kid.startswith("  "))
        self.assertFalse(root.startswith(" "))

    def test_render_survives_an_empty_store(self):
        self.assertIn("no agents", status.render(status.collect(self.db, FakeHerdr())))

    def test_json_carries_the_same_facts(self):
        store.create_agent(self.db, name="root", role="orchestrator", workspace="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root",
                           session_id="s1")
        store.put_message(self.db, from_agent="x", to_agent="kid", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr([alive("root"), alive("kid", "idle")]))
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
            "cleanup": [], "workspace": ["new"], "restore": ["w1"],
            "inspect": ["w1"], "log": [],
            "board": [], "flush": [], "reconcile": [],
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
        """One way to name an agent. `--agent` was the odd one out on `workspace new`."""
        from switchboard.cli import build_parser
        for argv in (["start", "--name", "x"], ["delegate", "t", "--name", "x"]):
            self.assertEqual(build_parser().parse_args(argv).name, "x")
        for flag in ("--name", "--agent"):
            args = build_parser().parse_args(["workspace", "new", "api", flag, "x"])
            self.assertEqual(args.agent, "x")

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
        h = mock.patch.object(herdr_mod, "Herdr", lambda *a, **k: FakeHerdr([]))
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


if __name__ == "__main__":
    unittest.main()
