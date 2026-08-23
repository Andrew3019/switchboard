"""C4 — every state mutation signals the agents it affects (#163-A, §2.1/§2.4).

`grant` is the mutation wired here; the mechanism (`Broker._mutation_signals` +
`store.mutation`) is the generic one D1's re-attach and F2's promote ride later. Each test
pins one property:

* **The recipient is told, and told the thing it needs** — that it holds the capability,
  and whether it may USE it (a `--delegable` grant never widens what its holder may do).
* **The signal is IN the mutation's transaction.** A grant that committed without its
  signal is the silent divergence the rule exists to prevent, so an injected failure
  either way must leave neither.
* **The doorbell rides A1's idle-ring holdback.** A burst of grants is one ring, not one
  per grant — what coalesces is the doorbell; every message is whole in the mailbox.
* **`block` and `--interrupt` stay exempt**, checked with a signal holdback open.
* **A mutation signal is never digested** — it is not a `done` row, so `sb status`'s
  summaries cannot see it.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import broker as broker_mod  # noqa: E402
from switchboard import status as status_mod  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import (  # noqa: E402
    CAP_FORK, CAP_SPAWN, CAP_WRITE_TRACKED, HUMAN, INTERRUPT, SIGNAL,
)

from test_grants import Fixture  # noqa: E402


class SignalFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.topa = self.top()
        self.lead = self.spawn(self.topa, "lead", "l")
        self.w1 = self.spawn(self.lead, "worker", "one")
        self.w2 = self.spawn(self.lead, "worker", "two")
        self.idle()

    def idle(self):
        """Everybody idle, and the per-process liveness cache dropped."""
        self.h.states_by_name = {n: "idle" for n in
                                 (self.topa, self.lead, self.w1, self.w2)}
        self.b._alive_cache = None

    def rings(self):
        """Doorbells only — the spawn prompts every agent is born with are not rings."""
        return [(who, text) for who, text in self.h.prompts if text != "t"]

    def mail(self, who):
        return store.unread_for(self.db, who, mark=False)

    @staticmethod
    def _later(seconds):
        """The clock the store stamps and reads with, moved on — nothing else is faked."""
        return mock.patch.object(store, "now", lambda: int(time.time()) + seconds)


class RecipientIsToldTest(SignalFixture, unittest.TestCase):
    def test_a_grant_signals_its_recipient(self):
        """§2.1: one `put_message` per mutation, and a `grant` notifies the RECIPIENT. An
        agent that does not know it holds a capability does not use it, and the lead that
        granted it has no way to tell."""
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead, reason="fan-out")
        [m] = self.mail(self.w1)
        self.assertEqual(m["kind"], SIGNAL)
        self.assertEqual(m["from_agent"], self.lead)      # provenance, in the mail itself
        self.assertIn(CAP_SPAWN, m["body"])
        self.assertIn("fan-out", m["body"])
        self.assertEqual(self.mail(self.lead), [])        # nobody else is signalled

    def test_a_delegable_grant_says_it_may_not_be_used(self):
        """The distinction #163 was filed over: a `--delegable` grant widens only what the
        recipient's CHILDREN are seeded with. Said plainly, or the recipient tries the
        action itself and reads the refusal as a bug."""
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead, delegable=True)
        [m] = self.mail(self.w1)
        self.assertIn("PASS-THROUGH ONLY", m["body"])
        self.assertNotIn(CAP_SPAWN, store.held_capabilities(self.db, self.w1))

    def test_the_signal_does_not_count_as_being_given_a_task(self):
        """`put_message` clears `awaiting_task` — "somebody gave this agent something".
        A capability grant is news, not work: clearing it would take away the excuse for
        being idle that keeps an agent waiting on its first instruction out of STALLED."""
        self.db.execute("UPDATE agents SET awaiting_task=1 WHERE name=?", (self.w1,))
        self.db.commit()
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertTrue(store.get_agent(self.db, self.w1)["awaiting_task"])


class AtomicWithTheMutationTest(SignalFixture, unittest.TestCase):
    """§2.1, objective 3: either the mutation and every one of its signals land, or none."""

    def test_a_grant_whose_signal_fails_grants_nothing(self):
        """The injected-failure test. A capability row committed without the message
        telling its holder is precisely the silent divergence the signal exists to
        prevent."""
        with mock.patch.object(store, "put_message", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertEqual(store.held_capabilities(self.db, self.w1), {CAP_WRITE_TRACKED})
        self.assertEqual(self.mail(self.w1), [])
        self.assertEqual([e["kind"] for e in store.recent_events(self.db, agent=self.w1)
                          if e["kind"] == "grant"], [])
        self.assertFalse(self.db.in_transaction)          # and the store is not left open

    def test_a_signal_whose_grant_fails_is_never_written(self):
        """The same rule read the other way: nothing announces a change that did not
        happen."""
        with mock.patch.object(store, "grant_capability",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertEqual(self.mail(self.w1), [])
        self.assertEqual(self.rings(), [])

    def test_the_doorbell_is_outside_the_transaction(self):
        """The honest limit, pinned so nobody "fixes" it later: the ring is a herdr
        SUBPROCESS and cannot join a sqlite transaction. What the transaction covers is
        the ROWS — the message is never lost relative to the grant; the ring may lag, and
        `sb inbox` has the message regardless."""
        seen = []
        real = broker_mod.Broker._ring

        def spy(self_, *a, **kw):
            seen.append(self_.db.in_transaction)
            return real(self_, *a, **kw)

        with mock.patch.object(broker_mod.Broker, "_ring", spy):
            self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertEqual(seen, [False])


class RidesTheHoldbackTest(SignalFixture, unittest.TestCase):
    """§2.4: mutation rings are in the held class and coalesce like a `done` burst."""

    def test_a_burst_of_grants_rings_the_recipient_once(self):
        """#168 on another channel. Two grants to one idle worker used to be two
        payload-free doorbells saying the same sentence twice."""
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.b.grant(self.w1, CAP_FORK, me=self.topa, delegable=True)
        self.assertEqual(self.rings(), [])                 # not one ring in the burst
        self.assertEqual(self.b.flush_pending(), [])       # nor from the drain, mid-burst

        with self._later(broker_mod.RING_HOLDBACK + 1):    # the burst goes quiet
            self.assertEqual(self.b.flush_pending(), [self.w1])
        [(who, _)] = self.rings()
        self.assertEqual(who, self.w1)
        # ONE doorbell, and nothing collapsed to make it: both signals are in the mailbox.
        self.assertEqual(len(self.mail(self.w1)), 2)

    def test_the_held_signal_is_a_late_doorbell_and_never_a_lost_message(self):
        """The holdback is about the ring only. The row is committed and readable the
        moment the grant is, whatever the doorbell did."""
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertEqual(self.rings(), [])
        self.assertTrue(self.b._holdback_open(self.w1))
        self.assertEqual([m["kind"] for m in self.b.inbox(me=self.w1)], [SIGNAL])

    def test_direct_mail_in_the_backlog_still_rings_at_once(self):
        """A signal must not become a new latency on a `tell`: one message outside the
        held class and the whole backlog goes immediately."""
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.b.tell([self.w1], "and here is the work", me=self.lead)
        self.assertEqual([who for who, _ in self.rings()], [self.w1])


class TheCarveOutsStandTest(SignalFixture, unittest.TestCase):
    """§2.4: `block` and `--interrupt` are exempt absolutely, and this path may not
    reintroduce a hold on either. Neither is exempted by name — `block` writes no message
    row, and an interrupt never reaches the when-idle branch the holdback lives on."""

    def test_an_interrupt_goes_through_an_open_signal_holdback(self):
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertTrue(self.b._holdback_open(self.w1))
        self.b.tell([self.w1], "stop, do this instead", me=HUMAN, mode=INTERRUPT)
        self.assertEqual([who for who, _ in self.rings()], [self.w1])

    def test_a_block_is_not_held_by_a_signal(self):
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        self.assertTrue(self.b._holdback_open(self.w1))
        self.b.block("need a person", me=self.w1)
        # It writes no message row at all — it reaches a person through `_surface`.
        self.assertEqual([m["kind"] for m in self.mail(self.w1)], [SIGNAL])
        self.assertTrue(any(e["kind"] == "blocked"
                            for e in store.recent_events(self.db, agent=self.w1)))


class NeverDigestedTest(SignalFixture, unittest.TestCase):
    def test_a_signal_is_not_a_summary(self):
        """Objective 5: the envelope digest reads `done` rows, so news about a rights
        change can never be merged into a count of finished children. Structural — the
        kind is different — not a filter somebody has to remember."""
        self.b.grant(self.w1, CAP_SPAWN, me=self.lead)
        [m] = self.mail(self.w1)
        self.assertNotIn(m["kind"], ("done", "failed"))
        self.assertIsNone(status_mod._last_summaries(self.db).get(self.w1))
        # And it is not a third carve-out either: exempt from the digest only, held like
        # every other coalescing ring.
        self.assertIn(SIGNAL, broker_mod.HELD_RING_KINDS)


if __name__ == "__main__":
    unittest.main()
