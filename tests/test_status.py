"""Status tests — the join between the store and herdr.

The store half is real (a temp database); the herdr half is a fake `agent list`, because
every case worth testing here is "what happens when the two disagree".
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import status, store  # noqa: E402
from switchboard.herdr import Agent, HerdrError  # noqa: E402


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

    # -- drift: the reason this module exists ----------------------------

    def test_working_in_the_store_but_idle_in_herdr_is_stalled(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        a = self.by_name(snap)["w1"]
        self.assertTrue(a.stalled)
        self.assertEqual(a.state, "working")      # the store is reported, not rewritten
        self.assertEqual(a.herdr_state, "idle")

    def test_herdrs_derived_done_counts_as_idle(self):
        """herdr shows `done` for idle-and-unviewed; missing that hides real drift."""
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "done")]))
        self.assertTrue(self.by_name(snap)["w1"].stalled)

    def test_drift_is_not_repaired(self):
        """Marking it done here would fabricate a summary its parent never got."""
        store.create_agent(self.db, name="w1", role="worker")
        status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        self.assertEqual(store.get_agent(self.db, "w1")["state"], "working")

    # -- drift in the mailbox: written, never announced --------------------

    def test_mail_never_announced_is_counted_apart_from_mail_ignored(self):
        """Unread means we rang and it has not looked. Undelivered means it was never
        told — invisible from inside the agent, so it can sit forever."""
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

    def test_counting_undelivered_mail_never_delivers_it(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="human", to_agent="w1", kind="tell", body="x")
        status.collect(self.db, FakeHerdr([alive("w1", "working")]))
        self.assertEqual(len(store.undelivered(self.db, exclude=("human",))), 1)

    def test_a_genuinely_working_agent_is_not_stalled(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "working")]))
        a = self.by_name(snap)["w1"]
        self.assertFalse(a.stalled)
        self.assertTrue(a.alive)

    def test_a_finished_agent_sitting_idle_is_not_drift(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.set_state(self.db, "w1", "done")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "idle")]))
        self.assertFalse(self.by_name(snap)["w1"].stalled)

    def test_unknown_from_herdr_proves_nothing(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "unknown")]))
        self.assertFalse(self.by_name(snap)["w1"].stalled)

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
        snap = status.collect(self.db, FakeHerdr([]))
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
        a = self.by_name(status.collect(self.db, FakeHerdr([]), now=later))["w1"]
        self.assertTrue(a.gone)
        self.assertEqual(self.row("w1")["state"], status.GONE_STATE)

    def test_the_grace_only_covers_rows_with_no_session(self):
        """A session id means the agent got past its spawn and called `sb` itself, so
        herdr's silence about it is real drift however young the row is."""
        store.create_agent(self.db, name="w1", role="worker", session_id="s1")
        self.assertTrue(self.by_name(status.collect(self.db, FakeHerdr([])))["w1"].gone)

    def test_an_unreachable_herdr_never_reaps_anything(self):
        """The guard. Absent herdr's side every row looks gone, and a hiccup would end
        every agent on the machine."""
        store.create_agent(self.db, name="w1", role="worker")
        status.collect(self.db, FakeHerdr(error=HerdrError("down", "no server")))
        self.assertEqual(self.row("w1")["state"], "working")
        self.assertIsNone(self.row("w1")["ended_at"])

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
        status.collect(self.db, FakeHerdr([]))
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

    def test_works_with_no_herdr_at_all(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, None)
        self.assertIsNone(self.by_name(snap)["w1"].alive)

    # -- the tree ---------------------------------------------------------

    def test_roots_are_at_depth_zero_and_children_indent(self):
        store.create_agent(self.db, name="root", role="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        store.create_agent(self.db, name="grandkid", role="worker", parent="kid")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual([(a.name, a.depth) for a in snap.agents],
                         [("root", 0), ("kid", 1), ("grandkid", 2)])

    def test_a_parent_immediately_precedes_its_children(self):
        store.create_agent(self.db, name="a", role="main")
        store.create_agent(self.db, name="b", role="main")
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

    def test_self_parent_does_not_hang(self):
        store.create_agent(self.db, name="a", role="worker", parent="a")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual([a.name for a in snap.agents], ["a"])

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

    def test_read_mail_is_not_counted(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        store.unread_for(self.db, "w1")                       # the agent read it
        snap = status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertEqual(self.by_name(snap)["w1"].unread, 0)

    # -- undelivered: mail nobody ever rang about --------------------------

    def deliver(self, name):
        store.mark_delivered(self.db, name)

    def test_mail_is_undelivered_until_the_doorbell_is_rung(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")])))["w1"]
        self.assertEqual(a.undelivered, 1)
        self.assertTrue(a.waiting_to_be_rung)

    def test_delivered_mail_is_no_longer_undelivered_but_is_still_unread(self):
        """The two are independent: ringing does not read, and reading is not ringing."""
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        self.deliver("w1")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")])))["w1"]
        self.assertEqual(a.undelivered, 0)
        self.assertFalse(a.waiting_to_be_rung)
        self.assertEqual(a.unread, 1)

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

    def test_no_undelivered_mail_means_no_age(self):
        store.create_agent(self.db, name="w1", role="worker")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")])))["w1"]
        self.assertEqual(a.undelivered_age, 0)
        self.assertFalse(a.waiting_to_be_rung)

    def test_the_human_is_never_undelivered_to(self):
        """No doorbell exists for a person, and no mailbox either — see broker.block."""
        store.put_message(self.db, from_agent="w1", to_agent="human", kind="ask", body="?")
        snap = status.collect(self.db, FakeHerdr())
        self.assertEqual(snap.counts["undelivered"], 0)
        self.assertEqual(snap.counts["unread"], 0)

    def test_counting_undelivered_mail_never_delivers_it(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        status.collect(self.db, FakeHerdr([alive("w1")]))
        status.collect(self.db, FakeHerdr([alive("w1")]))
        self.assertEqual(len(store.undelivered(self.db, exclude=["human"])), 1)

    def test_undelivered_counts_as_needing_a_human(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")])))["w1"]
        self.assertTrue(a.needs_human)

    def test_needs_me_keeps_an_agent_whose_only_problem_is_undelivered_mail(self):
        store.create_agent(self.db, name="quiet", role="worker")
        store.create_agent(self.db, name="stuck", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="stuck", kind="tell", body="a")
        snap = status.collect(self.db, FakeHerdr([alive("quiet"), alive("stuck")]),
                              needs_me=True)
        self.assertEqual([a.name for a in snap.agents], ["stuck"])

    def test_undelivered_is_flagged_like_stalled_and_gone(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        row = next(l for l in out.splitlines() if l.startswith("w1"))
        self.assertIn("<< UNDELIVERED", row)            # on the row, where STALLED goes
        self.assertIn("UNDELIVERED — written, never announced", out)

    def test_the_render_says_undelivered_is_not_the_agents_fault(self):
        """Reported as 'never announced', never as mail it failed to pick up."""
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        self.assertIn("never announced", out)
        # Undelivered mail is unread BY DEFINITION, so the unread wording must not also
        # fire — "not picked up" blames the agent for silence that is ours.
        self.assertNotIn("not picked up", out)

    def test_mail_it_was_told_about_is_still_distinguished_when_both_exist(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="rung")
        self.deliver("w1")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="silent")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        self.assertIn("1 never announced to it", out)
        self.assertIn("1 unread it WAS told about", out)

    def test_an_agent_with_both_reports_both(self):
        store.create_agent(self.db, name="w1", role="worker")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="rung")
        self.deliver("w1")
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="silent")
        a = self.by_name(status.collect(self.db, FakeHerdr([alive("w1")])))["w1"]
        self.assertEqual(a.unread, 2)                   # both are unread...
        self.assertEqual(a.undelivered, 1)              # ...only one was never announced
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1")])))
        self.assertIn("2 unread", out)
        self.assertIn("1 undelivered", out)

    def test_undelivered_is_in_the_json(self):
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        store.put_message(self.db, from_agent="x", to_agent="w1", kind="tell", body="a")
        self.db.execute("UPDATE messages SET created_at=?", (t - 120,))
        self.db.commit()
        d = json.loads(json.dumps(
            status.collect(self.db, FakeHerdr([alive("w1")]), now=t).as_dict()))
        w1 = d["agents"][0]
        self.assertEqual(w1["undelivered"], 1)
        self.assertEqual(w1["undelivered_age"], 120)
        self.assertTrue(w1["waiting_to_be_rung"])
        self.assertTrue(w1["needs_human"])
        self.assertEqual(d["counts"]["undelivered"], 1)
        self.assertEqual(d["counts"]["waiting_to_be_rung"], 1)

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

    def test_idle_falls_back_to_creation_when_nothing_has_happened(self):
        store.create_agent(self.db, name="w1", role="worker")
        t = store.now()
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?", (t - 300, "w1"))
        self.db.commit()
        snap = status.collect(self.db, FakeHerdr([alive("w1")]), now=t)
        self.assertEqual(self.by_name(snap)["w1"].idle, 300)

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

    def test_fmt_age_is_two_units_at_most(self):
        self.assertEqual(status.fmt_age(9), "9s")
        self.assertEqual(status.fmt_age(90), "1m")
        self.assertEqual(status.fmt_age(3660), "1h01")
        self.assertEqual(status.fmt_age(90000), "1d01h")

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
        store.create_agent(self.db, name="root", role="main")
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

    def test_needs_me_includes_an_agent_sitting_at_a_prompt(self):
        store.create_agent(self.db, name="w1", role="worker")
        snap = status.collect(self.db, FakeHerdr([alive("w1", "blocked")]), needs_me=True)
        self.assertEqual([a.name for a in snap.agents], ["w1"])

    def test_needs_me_keeps_ancestors_so_the_tree_still_reads(self):
        store.create_agent(self.db, name="root", role="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        store.set_state(self.db, "kid", "blocked")
        snap = status.collect(self.db, FakeHerdr(), needs_me=True)
        self.assertEqual([(a.name, a.depth) for a in snap.agents],
                         [("root", 0), ("kid", 1)])

    def test_mine_is_the_callers_own_subtree(self):
        store.create_agent(self.db, name="root", role="main")
        store.create_agent(self.db, name="me", role="orchestrator", parent="root")
        store.create_agent(self.db, name="kid", role="worker", parent="me")
        store.create_agent(self.db, name="grandkid", role="worker", parent="kid")
        store.create_agent(self.db, name="stranger", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="me")
        self.assertEqual([a.name for a in snap.agents], ["me", "kid", "grandkid"])

    def test_mine_never_climbs_back_out_to_a_parent(self):
        """Ancestors exist to keep the indentation honest, not to widen the scope."""
        store.create_agent(self.db, name="root", role="main")
        store.create_agent(self.db, name="me", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="me")
        self.assertEqual([a.name for a in snap.agents], ["me"])

    def test_mine_for_a_human_is_every_agent(self):
        store.create_agent(self.db, name="root", role="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        snap = status.collect(self.db, FakeHerdr(), mine="human")
        self.assertEqual([a.name for a in snap.agents], ["root", "kid"])
        self.assertEqual(snap.hidden, 0)

    def test_mine_for_somebody_with_no_agents_is_empty_not_everything(self):
        store.create_agent(self.db, name="root", role="main")
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

    def test_no_filter_shows_everything_including_a_cycle(self):
        """The default output is untouched — and the ancestor walk cannot hang on one."""
        store.create_agent(self.db, name="a", role="worker", parent="b")
        store.create_agent(self.db, name="b", role="worker", parent="a")
        store.create_agent(self.db, name="c", role="worker", parent="a")
        snap = status.collect(self.db, FakeHerdr(), needs_me=False, live_only=False)
        self.assertEqual({a.name for a in snap.agents}, {"a", "b", "c"})

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

    def test_the_latest_summary_wins(self):
        store.create_agent(self.db, name="w1", role="worker")
        for s in ("first", "second"):
            store.put_message(self.db, from_agent="w1", to_agent="orch", kind="done",
                              body=f"[done] {s}")
        self.assertEqual(self.by_name(status.collect(self.db, FakeHerdr()))["w1"].summary,
                         "second")

    def test_task_and_summary_are_in_the_json(self):
        store.create_agent(self.db, name="w1", role="worker", task="rewrite the parser")
        store.put_message(self.db, from_agent="w1", to_agent="orch", kind="done",
                          body="[done] shipped")
        d = json.loads(json.dumps(status.collect(self.db, FakeHerdr()).as_dict()))
        self.assertEqual(d["agents"][0]["task"], "rewrite the parser")
        self.assertEqual(d["agents"][0]["summary"], "shipped")

    # -- output -----------------------------------------------------------

    def test_render_shows_every_required_field(self):
        store.create_agent(self.db, name="w1", role="researcher", workspace="feature-x")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "working")])))
        for expected in ("w1", "researcher", "working", "feature-x"):
            self.assertIn(expected, out)

    def test_render_names_drift_loudly(self):
        store.create_agent(self.db, name="w1", role="worker")
        out = status.render(status.collect(self.db, FakeHerdr([alive("w1", "idle")])))
        self.assertIn("STALLED", out)
        self.assertIn("sb done", out)             # says what was actually skipped

    def test_render_indents_children(self):
        store.create_agent(self.db, name="root", role="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
        out = status.render(status.collect(self.db, FakeHerdr()))
        kid = next(l for l in out.splitlines() if l.lstrip().startswith("kid"))
        root = next(l for l in out.splitlines() if l.startswith("root"))
        self.assertTrue(kid.startswith("  "))
        self.assertFalse(root.startswith(" "))

    def test_render_survives_an_empty_store(self):
        self.assertIn("no agents", status.render(status.collect(self.db, FakeHerdr())))

    def test_json_carries_the_same_facts(self):
        store.create_agent(self.db, name="root", role="main", workspace="main")
        store.create_agent(self.db, name="kid", role="worker", parent="root")
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

    def test_json_after_the_subcommand_is_accepted(self):
        from switchboard.cli import build_parser
        args = build_parser().parse_args(["status", "--json"])
        self.assertTrue(args.json)

    def test_json_before_the_subcommand_still_works(self):
        from switchboard.cli import build_parser
        args = build_parser().parse_args(["--json", "status"])
        self.assertTrue(args.json)

    def test_live_flag_exists_and_defaults_off(self):
        from switchboard.cli import build_parser
        self.assertFalse(build_parser().parse_args(["status"]).live)
        self.assertTrue(build_parser().parse_args(["status", "--live"]).live)

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
            "start": [], "delegate": ["do a thing"], "ask": ["w1", "q?"],
            "tell": ["w1", "hi"], "inbox": [], "done": ["finished"], "block": ["why"],
            "status": [], "plugins": [], "models": [], "init": [], "doctor": [],
            "cleanup": [], "workspace": ["new"], "restore": ["w1"],
            "interrupt": ["w1", "stop"], "inspect": ["w1"], "wait": ["w1"], "log": [],
            "board": [],
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

    def test_the_filters_exist_and_default_off(self):
        from switchboard.cli import build_parser
        args = build_parser().parse_args(["status"])
        self.assertFalse(args.needs_me)
        self.assertFalse(args.mine)
        args = build_parser().parse_args(["status", "--needs-me", "--mine"])
        self.assertTrue(args.needs_me)
        self.assertTrue(args.mine)


if __name__ == "__main__":
    unittest.main()
