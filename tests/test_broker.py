"""Broker tests — the verb semantics.

A fake herdr records what would have been called, so these run fast and spawn nothing.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import status  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard.broker import HUMAN, MAIN, MAIN_NAME, Broker, Undeliverable  # noqa: E402
from switchboard.herdr import Agent, HerdrError  # noqa: E402


class FakeHerdrAPI:
    def __init__(self):
        self.prompts: list[tuple[str, str]] = []
        self.notifications: list[str] = []
        self.states: list[tuple[str, str, str]] = []
        self.closed: list[str] = []
        self.started: list[dict] = []
        self.keys: list[tuple] = []
        self.pane_prompts: list[tuple] = []
        self.unreachable: set = set()
        self.states_by_name: dict = {}
        self.list_error: Optional[HerdrError] = None   # herdr itself cannot be asked
        self.workspaces: list = []
        self.tabs: list = []
        self._n = 0

    def create_tab(self, *, workspace=None, **kw):
        self._n += 1
        self.tabs.append(workspace)
        return f"{workspace or 'w1'}:p{self._n}"

    def start_agent(self, name, pane, *, prompts=(), model_args=(), resume=None, **kw):
        self.started.append({"name": name, "pane": pane, "prompts": list(prompts),
                             "model_args": list(model_args), "resume": resume})
        return Agent(name=name, pane_id=pane, terminal_id=f"term_{name}",
                     session_id=f"sess-{name}")

    def prompt(self, name, text):
        if name in self.unreachable:
            from switchboard.herdr import HerdrError
            raise HerdrError("agent_not_found", f"agent target {name} not found")
        self.prompts.append((name, text))

    def prompt_pane(self, pane, text): self.pane_prompts.append((pane, text))

    def list_agents(self):
        from switchboard.herdr import Agent as _A
        if self.list_error:
            raise self.list_error
        return [_A(name=n, pane_id="w1:p0", state=st) for n, st in self.states_by_name.items()]

    def create_workspace(self, label, *, cwd=None, focus=False):
        self._ws = getattr(self, "_ws", 100) + 1
        self.workspaces.append(label)
        return {"workspace": {"workspace_id": f"w{self._ws}"},
                "root_pane": {"pane_id": f"w{self._ws}:p1"}}
    def send_keys(self, name, *keys): self.keys.append((name, keys))
    def notify(self, text): self.notifications.append(text)
    def report_state(self, pane, name, state, seq, **kw): self.states.append((name, state, pane))
    def report_session(self, pane, name, sid, seq, **kw): pass
    def release_agent(self, pane, name, seq): pass
    def close_pane(self, pane): self.closed.append(pane)


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        # Point the global model config at a path inside the temp repo, i.e. at nothing.
        # Without this, a models.toml in the developer's own ~/.config decides what tier
        # the spawn assertions below see, and the suite passes or fails per machine.
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdrAPI()
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def restart_sb(self):
        """The next `sb` command is a new PROCESS, and herdr's answer is cached for the
        life of one. A test that reuses a Broker across two invocations is reading the
        world as it stood during the first."""
        self.b = Broker(self.db, self.h, repo=self.repo)
        return self.b

    # -- identity --------------------------------------------------------

    def test_whoami_is_human_outside_a_pane(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.b.whoami(), HUMAN)

    def test_a_finished_agent_is_still_itself(self):
        """Reporting done ends a TURN, not an existence.

        Resolving a finished agent to HUMAN made it attribute its messages to the human
        and be unable to call `sb done` at all. Observed in the wild with an agent given a
        follow-up task after reporting done.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p9")
        store.set_state(self.db, "w", "done")
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p9"}, clear=True):
            self.assertEqual(self.b.whoami(), "w")
        a = store.get_agent(self.db, "w")
        self.assertIsNone(a["ended_at"])                  # revived: it is working again
        self.assertEqual(a["state"], "working")

    def test_session_id_wins_over_a_recycled_pane(self):
        """Pane ids are recycled once a pane closes; a stale row must not capture a new
        agent, so the unambiguous key is preferred."""
        store.create_agent(self.db, name="old", role="worker", pane_id="w1:p9",
                           session_id="sess-old")
        store.set_state(self.db, "old", "done")
        store.create_agent(self.db, name="new", role="worker", pane_id="w1:p9",
                           session_id="sess-new")
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p9",
                                          "CLAUDE_CODE_SESSION_ID": "sess-new"}, clear=True):
            self.assertEqual(self.b.whoami(), "new")

    def test_whoami_resolves_from_injected_pane_id(self):
        """Identity comes from HERDR_PANE_ID, which exists before the agent acts."""
        store.create_agent(self.db, name="w1", role="worker", pane_id="w1:p9")
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p9"}, clear=True):
            self.assertEqual(self.b.whoami(), "w1")

    # -- delegate --------------------------------------------------------

    def test_delegate_lands_in_the_callers_own_workspace(self):
        """An empty workspace id means "wherever herdr is focused" — which is whatever
        was focused last, so a child would land in a stranger's workspace."""
        self.h.tabs = []
        with mock.patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "w1"}, clear=False):
            self.b.delegate("t", role="worker", me=HUMAN)
        self.assertEqual(self.h.tabs[-1], "w1")

    def test_delegate_records_parent_and_pokes_with_the_task(self):
        name = self.b.delegate("compute 2+2", role="worker", me="orch")
        a = store.get_agent(self.db, name)
        self.assertEqual(a["parent"], "orch")
        self.assertEqual(a["session_id"], f"sess-{name}")
        self.assertIn((name, "compute 2+2"), self.h.prompts)

    def test_delegate_prompts_are_single_line(self):
        """herdr rejects multi-line agent args outright."""
        self.b.delegate("t", role="researcher", with_=["extra guidance"], me="orch")
        for p in self.h.started[0]["prompts"]:
            self.assertNotIn("\n", p)

    def test_role_selects_a_model_tier(self):
        """A role names a tier; what reaches the CLI is that tier's resolved flags.

        Effort rides along — the bug this replaces passed only the model id, so a tier's
        effort was silently dropped on every spawn.
        """
        self.b.delegate("t", role="researcher", me="orch")     # researcher = cheap
        self.assertEqual(self.h.started[0]["model_args"],
                         ["--model", "sonnet", "--effort", "medium"])

    def test_an_explicit_model_is_a_tier_name_too(self):
        """`--model strong` must be resolved, not handed to the CLI as a model id."""
        self.b.delegate("t", role="worker", model="strong", me="orch")
        self.assertEqual(self.h.started[0]["model_args"],
                         ["--model", "opus", "--effort", "high"])

    def test_an_unknown_model_still_passes_through_as_an_id(self):
        """The escape hatch survives the tier lookup (see models.Tiers.resolve)."""
        self.b.delegate("t", role="worker", model="claude-fable-5", me="orch")
        self.assertEqual(self.h.started[0]["model_args"], ["--model", "claude-fable-5"])

    def test_a_tier_with_no_model_sends_no_flags(self):
        """`default` defers to the provider CLI, which means sending nothing at all."""
        self.b.delegate("t", role="worker", me="orch")
        self.assertEqual(self.h.started[0]["model_args"], [])

    def test_unknown_role_still_works(self):
        """Vocabulary is data — an undefined role inherits defaults, it does not error."""
        name = self.b.delegate("t", role="wizard", me="orch")
        self.assertEqual(store.get_agent(self.db, name)["role"], "wizard")

    def test_as_prompt_overrides_the_role_prompt(self):
        self.b.delegate("t", role="worker", as_prompt="You are a haiku critic.", me="orch")
        joined = " ".join(self.h.started[0]["prompts"])
        self.assertIn("haiku critic", joined)

    # -- the spawn race: a claim is not a dead agent -----------------------

    def _collect_during_spawn(self):
        """Make the board refresh in the middle of `agent start`.

        Not contrived: `delegate` claims the row before herdr is called, `agent start`
        retries a flaky first attempt over a couple of seconds, and the board refreshes
        every 2 s — as does every `sb` invocation. herdr does not know the name yet
        (`states_by_name` is empty), so this is exactly the look that used to reap it.
        """
        real = self.h.start_agent
        seen = []

        def racing(*a, **kw):
            seen.append(status.collect(self.db, self.h))
            return real(*a, **kw)

        self.h.start_agent = racing
        return seen

    def test_a_claim_survives_a_status_collect_mid_spawn(self):
        self._collect_during_spawn()
        name = self.b.delegate("t", role="worker", me="orch")
        a = store.get_agent(self.db, name)
        self.assertEqual(a["state"], "working")
        self.assertIsNone(a["ended_at"])
        # And nothing was invented about it: no `gone` event was ever logged.
        self.assertNotIn("gone", [e["kind"] for e in store.recent_events(self.db, agent=name)])

    def test_a_spawn_slower_than_the_grace_is_repaired_when_it_lands(self):
        """The second guard. If the spawn outruns the grace the reaper does close the
        row — and only the successful spawn can undo that, because `update_agent` cannot
        write `state` or `ended_at` and so the false `failed` used to stick forever."""
        self._collect_during_spawn()
        with mock.patch.object(status, "SPAWN_GRACE", 0):
            name = self.b.delegate("t", role="worker", me="orch")
        a = store.get_agent(self.db, name)
        self.assertEqual(a["state"], "working")
        self.assertIsNone(a["ended_at"])

    def test_names_do_not_collide(self):
        a = self.b.delegate("t", role="calc", me="orch")
        b = self.b.delegate("t", role="calc", me="orch")
        self.assertNotEqual(a, b)

    # -- messaging -------------------------------------------------------

    def test_tell_rings_the_doorbell_without_the_payload(self):
        store.create_agent(self.db, name="b", role="worker")
        self.b.tell(["b"], "the actual secret payload", me="a")
        self.assertEqual(len(self.h.prompts), 1)
        self.assertNotIn("secret payload", self.h.prompts[0][1])  # payload stays in the store

    def test_parent_resolves(self):
        store.create_agent(self.db, name="kid", role="worker", parent="mum")
        store.create_agent(self.db, name="mum", role="orchestrator")
        self.b.tell(["parent"], "hi", me="kid")
        self.assertEqual(store.unread_for(self.db, "mum")[0]["body"], "hi")

    def test_tell_answers_a_pending_ask_without_a_reply_verb(self):
        store.create_agent(self.db, name="b", role="worker")
        mid = store.put_message(self.db, from_agent="a", to_agent="b", kind="ask", body="q?")
        self.b.tell(["a"], "the answer", me="b")
        self.assertEqual(store.reply_to_ask(self.db, mid)["body"], "the answer")

    def test_ask_returns_once_every_target_answers(self):
        store.create_agent(self.db, name="x", role="worker")
        store.create_agent(self.db, name="y", role="worker")

        def answer_both(*_a, **_k):
            for t in ("x", "y"):
                p = store.pending_ask(self.db, asker="orch", target=t)
                if p:
                    store.put_message(self.db, from_agent=t, to_agent="orch",
                                      kind="tell", body=f"{t}-done", reply_to=p["id"])
        self.h.prompt = answer_both
        got = self.b.ask(["x", "y"], "status?", me="orch", timeout=5, poll=0.01)
        self.assertEqual(got, {"x": "x-done", "y": "y-done"})

    def test_ask_gives_up_on_a_target_that_vanished_without_recording(self):
        """A child can die recording nothing — no done, no failed. The store has no reason
        to stop waiting, so without this an `ask` sits out its whole timeout."""
        from switchboard import broker as bmod
        store.create_agent(self.db, name="ghost", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {}                      # herdr has never heard of it
        with mock.patch.object(bmod, "GONE_GRACE", 0.05):
            got = self.b.ask(["ghost"], "q?", me="orch", timeout=30, poll=0.01)
        self.assertIsNone(got["ghost"])                 # gave up early, did not hang

    def test_a_single_missing_reading_is_not_treated_as_death(self):
        """One absent reading is indistinguishable from a herdr hiccup."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {}
        started = time.time()
        got = self.b.ask(["w"], "q?", me="orch", timeout=0.4, poll=0.01)
        self.assertIsNone(got["w"])
        self.assertGreater(time.time() - started, 0.3)  # it kept waiting

    def test_ask_times_out_with_none_rather_than_hanging(self):
        store.create_agent(self.db, name="z", role="worker")
        got = self.b.ask(["z"], "q?", me="orch", timeout=0.2, poll=0.05)
        self.assertIsNone(got["z"])          # caller decides (C9)

    def test_there_is_no_way_to_ask_the_human_and_wait(self):
        """One way to reach a person, and it is `sb block`.

        Waiting on a human held the turn open for an answer that can take hours: the agent
        showed as working the whole time, a live process sat there, and the tool call could
        time out on top of it. Refused rather than silently aliased to `block`, because the
        caller of `ask` goes on to use a return value and the caller of `block` stops.
        """
        store.create_agent(self.db, name="orch", role="orchestrator", pane_id="w1:p0")
        with self.assertRaises(ValueError) as e:
            self.b.ask([HUMAN], "which approach?", me="orch", timeout=0.1, poll=0.05)
        self.assertIn("sb block", str(e.exception))
        self.assertEqual(store.get_agent(self.db, "orch")["state"], "working")

    # -- done / block ----------------------------------------------------

    def test_done_notifies_the_parent_so_it_need_not_poll(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.done("computed 144", me="kid")
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "done")
        self.assertIn("[done] computed 144", store.unread_for(self.db, "orch")[0]["body"])
        self.assertTrue(any(n == "orch" for n, _ in self.h.prompts))

    def test_a_root_agents_summary_is_recorded_without_being_mailed(self):
        """Nobody is above a root agent, and the human has no mailbox.

        The summary still has to reach a person, so it does — through the readouts, which
        take it from the event log: the done row on `sb status`, and `sb inspect` in full.
        """
        store.create_agent(self.db, name="root", role="orchestrator", pane_id="w1:p1")
        self.b.done("shipped the parser", me="root")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"], 0)
        self.assertEqual(store.get_agent(self.db, "root")["state"], "done")
        [a] = status.collect(self.db, self.h).agents
        self.assertEqual(a.summary, "shipped the parser")
        self.assertIn("shipped the parser",
                      status.render_detail(status.inspect(self.db, None, "root", lines=0)))

    def test_a_childs_summary_still_reaches_its_parent_as_mail(self):
        """Only the human lost a mailbox. Agent-to-agent handoff is untouched."""
        store.create_agent(self.db, name="orch", role="orchestrator", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.done("counted 144", me="kid")
        [m] = store.unread_for(self.db, "orch", mark=False)
        self.assertIn("[done] counted 144", m["body"])

    def test_done_pushes_idle_because_herdr_has_no_done_state(self):
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.done("x", me="kid")
        self.assertEqual(self.h.states[-1][1], "idle")

    def test_block_does_not_push_herdrs_blocked_state(self):
        """herdr's `blocked` makes an agent permanently un-targetable — the name drops
        out and never comes back, so the human could never answer the block."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.block("need a decision", me="w")
        self.assertEqual(store.get_agent(self.db, "w")["state"], "blocked")  # our truth
        self.assertEqual(self.h.states[-1][1], "idle")                       # reachable
        self.assertTrue(self.h.notifications)                                # you hear it

    def test_block_goes_to_the_human_not_the_parent(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.block("need a decision", me="kid")
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "blocked")
        self.assertTrue(self.h.notifications)
        self.assertEqual(store.unread_for(self.db, "orch"), [])   # parent context untouched

    def test_a_block_writes_no_mail_but_keeps_a_durable_record(self):
        """The human has no mailbox, and the record must survive anyway.

        A desktop notification is gone the moment it is dismissed, which is why a mailbox
        row was written here once. The event log is that record now, and it is what
        `sb status --needs-me` reads the reason out of — so nothing is lost by not
        addressing anybody.
        """
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) c FROM messages WHERE to_agent=?",
                            (HUMAN,)).fetchone()["c"], 0)
        why = [r for r in store.recent_events(self.db, agent="kid") if r["kind"] == "blocked"]
        self.assertIn("which branch?", why[0]["payload"])
        [needs] = status.collect(self.db, self.h, needs_me=True).agents
        self.assertEqual((needs.name, needs.blocked_why), ("kid", "which branch?"))

    def test_answering_a_block_unblocks_it_and_does_ring(self):
        """The reply is what restarts the agent: its turn ended, so unlike an answer to a
        pending `ask` this one has nobody waiting to collect it."""
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        self.h.prompts.clear()
        self.b.tell(["kid"], "use main", me=HUMAN)
        self.assertEqual([n for n, _ in self.h.prompts], ["kid"])
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "working")

    def test_an_interrupt_is_recorded_as_well_as_delivered(self):
        """It travels inline rather than as a doorbell, so without the row the instruction
        would exist only in a pane — and the store is the only memory (C7)."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.interrupt("w", "stop and do this instead")
        [m] = self.db.execute(
            "SELECT * FROM messages WHERE to_agent='w'").fetchall()
        self.assertIn("stop and do this instead", m["body"])
        self.assertIsNotNone(m["read_at"])          # it already arrived, inline
        self.assertIsNotNone(m["delivered_at"])     # so nothing re-rings for it

    def test_the_doorbell_is_held_back_while_the_target_is_mid_turn(self):
        """`agent prompt` INTERLEAVES — it lands inside the current turn rather than
        after it — so ringing a working agent interrupts whatever it was doing."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "not urgent", me=HUMAN)
        self.assertEqual(self.h.prompts, [])                       # not rung
        self.assertEqual(len(store.undelivered(self.db)), 1)       # but not lost

    def test_pending_mail_is_rung_once_the_target_goes_idle(self):
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "later", me=HUMAN)
        self.h.states_by_name = {"w": "idle"}
        self.b._alive_cache = None
        self.assertEqual(self.b.flush_pending(), ["w"])
        self.assertEqual(store.undelivered(self.db), [])

    def test_flush_costs_nothing_when_there_is_no_pending_mail(self):
        self.assertEqual(self.b.flush_pending(), [])
        self.assertIsNone(self.b._alive_cache)                     # herdr never consulted

    def test_an_interrupt_always_lands_now(self):
        """Deferring an interrupt would defeat its entire purpose."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.interrupt("w", "stop")
        self.assertTrue(any(n == "w" for n, _ in self.h.prompts))

    def test_an_unrung_doorbell_never_falls_back_to_the_pane_shell(self):
        """`pane run` types into the pane's SHELL, so the fallback executed the text.

        It was not a recovery path either: herdr drops the name binding when the agent
        leaves the foreground, and an agent whose TUI is gone cannot read typed-in text
        any more than it can read a prompt. So the ring just fails, and the message stays
        queued for the next `flush_pending`.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.unreachable.add("w")
        self.b.tell(["w"], "you have mail", me=HUMAN)
        self.assertEqual(self.h.pane_prompts, [])
        self.assertEqual(self.h.prompts, [])
        # Still undelivered, so the next `sb` command rings it again.
        self.assertEqual([m["to_agent"] for m in store.undelivered(self.db)], ["w"])

    def test_an_undeliverable_interrupt_fails_loudly_instead_of_being_marked_read(self):
        """`mark_collected` used to fire before delivery was attempted, so an interrupt
        that never arrived was recorded as one the agent had already read."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.unreachable.add("w")
        with self.assertRaises(Undeliverable) as cm:
            self.b.interrupt("w", "stop what you are doing")
        self.assertEqual(cm.exception.who, "w")
        self.assertIn("agent_not_found", cm.exception.message)   # what herdr actually said
        self.assertIn("sb inbox", cm.exception.message)          # and what to do about it
        self.assertEqual(self.h.pane_prompts, [])                # no shell fallback
        [m] = store.undelivered(self.db)                         # queued, not read
        self.assertIsNone(m["read_at"])

    def test_a_delivered_interrupt_is_still_marked_read(self):
        """It travelled inline, so there is nothing left for `sb inbox` to announce."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.interrupt("w", "change course")
        self.assertEqual(store.undelivered(self.db), [])

    def test_messaging_a_blocked_agent_unblocks_it_first(self):
        """herdr makes a blocked agent un-targetable, so the doorbell would silently fail.

        Answering a blocked agent is what unblocking means, so the transition is correct
        rather than a workaround.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "blocked")
        self.b.tell(["w"], "here is your answer", me=HUMAN)
        self.assertEqual(self.h.states[-1][1], "working")     # re-registered before poking
        self.assertEqual(store.get_agent(self.db, "w")["state"], "working")
        self.assertTrue(any(n == "w" for n, _ in self.h.prompts))

    def test_messaging_a_working_agent_does_not_touch_state(self):
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.tell(["w"], "fyi", me=HUMAN)
        self.assertEqual(self.h.states, [])

    def test_restore_brings_the_agent_back_to_life(self):
        """whoami() matches on `ended_at IS NULL`; leaving it set makes a restored agent
        resolve to HUMAN, so everything it sends is attributed to a person."""
        store.create_agent(self.db, name="w", role="worker", session_id="s",
                           cwd=str(self.repo), pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        self.assertIsNotNone(store.get_agent(self.db, "w")["ended_at"])
        self.b.restore("w")
        a = store.get_agent(self.db, "w")
        self.assertIsNone(a["ended_at"])
        self.assertEqual(a["state"], "working")

    def test_interrupt_cancels_the_current_turn_first(self):
        """`agent prompt` alone only queues — the in-flight work would still finish."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.interrupt("w", "stop, do this instead")
        self.assertEqual(self.h.keys[0], ("w", ("esc",)))
        self.assertIn("INTERRUPT", self.h.prompts[-1][1])

    # -- cleanup / restore -----------------------------------------------

    def test_cleanup_closes_finished_children(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close")
        store.set_state(self.db, "kid", "done")
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])
        self.assertIn("w1:p1", self.h.closed)

    def test_cleanup_reaches_an_agent_that_died_without_reporting(self):
        """What reconciling drift buys. Every sweep gates on the row being finished, and
        a crashed agent's row never gets there on its own — so until `sb status` writes
        the death back, the one agent that most needs sweeping is the one nothing can."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        # `session_id` marks it as past its spawn — status holds off on reaping a
        # session-less row this young, since that is a claim mid-spawn.
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close", session_id="s-kid")
        self.h.states_by_name = {}                     # herdr has never heard of it
        self.assertEqual(self.b.cleanup(me="orch"), [])          # still reads 'working'
        status.collect(self.db, self.h)
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])

    def test_cleanup_closes_a_finished_agent_herdr_still_has(self):
        """The normal sweep, and the reason the liveness gate is scoped to `failed`: an
        agent that called `sb done` keeps a live idle pane, and herdr lists it. Gating
        every close on herdr's silence would leave nothing for `sb cleanup` to do."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close", session_id="s-kid")
        store.set_state(self.db, "kid", "done")
        self.h.states_by_name = {"kid": "idle"}
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])

    def test_cleanup_never_closes_a_reaped_agent_herdr_still_has(self):
        """The one that already destroyed two live agents. `failed` is not a report — it
        is `status._record_gone`'s inference from one `agent list`, and a readout taken
        during a slow spawn writes it about an agent that is very much alive. herdr still
        listing the name refutes the row, so a bare sweep must leave it alone."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close", session_id="s-kid")
        self.h.states_by_name = {}                     # a readout mid-spawn sees nothing
        status.collect(self.db, self.h)
        self.assertEqual(store.get_agent(self.db, "kid")["state"], status.GONE_STATE)

        self.h.states_by_name = {"kid": "working"}     # the spawn landed after all
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])
        self.assertEqual(self.h.closed, [])

    def test_cleanup_will_not_close_a_reaped_agent_when_herdr_cannot_be_asked(self):
        """Fail CLOSED, alone in this file. Everywhere else "cannot tell" means carry on,
        because the cost is a doorbell or a duplicate root. Here it is a live pane, and
        for a row that never got a session id there is no `sb restore` to undo it — so
        an unreachable herdr must stop the sweep, not wave it through."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close", session_id="s-kid")
        self.h.states_by_name = {}
        status.collect(self.db, self.h)                # reaped while herdr was answering

        self.h.list_error = HerdrError("down", "no server")
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])
        self.assertEqual(self.h.closed, [])
        # And it is a skip, not a state change: the row is untouched for the next sweep.
        self.assertEqual(store.get_agent(self.db, "kid")["state"], status.GONE_STATE)

    def test_cleanup_dry_run_does_not_offer_a_reaped_agent_herdr_still_has(self):
        """`--dry-run` is what a human reads before sweeping; listing a live agent there
        is how they learn to trust the sweep that kills it."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close", session_id="s-kid")
        self.h.states_by_name = {}
        status.collect(self.db, self.h)
        self.h.states_by_name = {"kid": "working"}
        self.assertEqual(self.restart_sb().cleanup(me="orch", dry_run=True), [])

    def test_cleanup_force_still_closes_a_named_agent_herdr_has(self):
        """The escape hatch has to survive the new gate, or an agent herdr has genuinely
        lost track of — listed but dead — becomes unreachable by any command."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close", session_id="s-kid")
        self.h.states_by_name = {}
        status.collect(self.db, self.h)
        self.h.states_by_name = {"kid": "working"}
        self.assertEqual(self.restart_sb().cleanup(["kid"], me="orch", force=True), ["kid"])

    def test_cleanup_never_closes_a_blocked_agent(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        store.set_state(self.db, "kid", "blocked")
        self.assertEqual(self.b.cleanup(me="orch", include_kept=True), [])

    def test_cleanup_never_closes_an_agent_with_unread_mail(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")
        store.put_message(self.db, from_agent="orch", to_agent="kid", kind="tell", body="wait")
        self.assertEqual(self.b.cleanup(me="orch"), [])

    def test_cleanup_never_escapes_the_callers_subtree(self):
        """A sweeping agent must not close a sibling's agents."""
        store.create_agent(self.db, name="mine", role="orchestrator")
        store.create_agent(self.db, name="my-kid", role="worker", parent="mine",
                           pane_id="w1:p1", cleanup="close")
        store.create_agent(self.db, name="theirs", role="orchestrator")
        store.create_agent(self.db, name="their-kid", role="worker", parent="theirs",
                           pane_id="w1:p2", cleanup="close")
        for n in ("my-kid", "their-kid"):
            store.set_state(self.db, n, "done")
        self.assertEqual(self.b.cleanup(me="mine", include_kept=True), ["my-kid"])
        self.assertNotIn("w1:p2", self.h.closed)

    def test_cleanup_reaches_grandchildren(self):
        store.create_agent(self.db, name="top", role="orchestrator")
        store.create_agent(self.db, name="mid", role="orchestrator", parent="top")
        store.create_agent(self.db, name="leaf", role="worker", parent="mid",
                           pane_id="w1:p3", cleanup="close")
        store.set_state(self.db, "leaf", "done")
        self.assertIn("leaf", self.b.cleanup(me="top", include_kept=True))

    def test_ask_fails_fast_on_an_unknown_target(self):
        """Otherwise the caller blocks the entire timeout waiting on nobody."""
        with self.assertRaises(KeyError):
            self.b.ask(["no-such"], "q?", me="orch", timeout=0.1)

    def test_ask_stops_waiting_on_a_child_that_finished_without_answering(self):
        """Otherwise the parent sits out its whole fifteen minutes for an answer that
        cannot arrive — `sb done` does not satisfy a pending ask."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")
        answers = self.b.ask(["kid"], "q?", me="orch", timeout=60, poll=0.01)
        self.assertEqual(answers, {"kid": None})

    def test_ask_keeps_waiting_on_a_child_that_is_merely_quiet(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        polls = []

        def answer_on_the_third_poll(_):
            polls.append(1)
            if len(polls) == 3:
                self.b.tell(["orch"], "here you go", me="kid")

        with mock.patch("time.sleep", answer_on_the_third_poll):
            answers = self.b.ask(["kid"], "q?", me="orch", timeout=60, poll=0.01)
        self.assertEqual(answers, {"kid": "here you go"})
        self.assertGreaterEqual(len(polls), 3)

    def test_asking_the_human_never_waits_and_never_takes_a_turn(self):
        """The trap this closes: a fifteen-minute call holding the turn open for nothing."""
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        started = time.time()
        with self.assertRaises(ValueError):
            self.b.ask([HUMAN], "which branch?", me="kid", timeout=30, poll=0.05)
        self.assertLess(time.time() - started, 1)              # it did not wait at all

    def test_a_refused_ask_leaves_no_half_sent_fan_out(self):
        """The human is checked before anything is written, so a mixed ask sends nothing.

        Half a fan-out would be worse than none: the peers would answer into a call that
        raised, and the caller would never collect what it asked for.
        """
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        store.create_agent(self.db, name="peer", role="worker", pane_id="w1:p2")
        with self.assertRaises(ValueError):
            self.b.ask([HUMAN, "peer"], "which branch?", me="kid", timeout=0.2, poll=0.05)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"], 0)

    def test_a_root_agents_ask_to_parent_is_refused_too(self):
        """`parent` resolves to the human for a root agent, and there is no asking one."""
        store.create_agent(self.db, name="root", role="orchestrator", pane_id="w1:p1")
        with self.assertRaises(ValueError):
            self.b.ask(["parent"], "which branch?", me="root", timeout=0.2, poll=0.05)

    def test_a_human_running_inbox_is_told_where_to_look_instead(self):
        """`(no new messages)` would read as "nothing needs you", which is a lie."""
        import argparse, contextlib, io
        from switchboard import cli
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        args = argparse.Namespace(cmd="inbox", json=False, peek=False)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(cli._dispatch(args, self.b, self.db, self.h), 0)
        self.assertIn("--needs-me", buf.getvalue())
        self.assertNotIn("no new messages", buf.getvalue())

    def test_telling_the_human_is_refused_rather_than_written_and_lost(self):
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        with self.assertRaises(ValueError):
            self.b.tell([HUMAN], "fyi", me="kid")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"], 0)

    def test_a_root_agents_tell_to_parent_is_refused_too(self):
        """`parent` resolves to the human for a root agent, and the human has no mailbox."""
        store.create_agent(self.db, name="root", role="orchestrator", pane_id="w1:p1")
        with self.assertRaises(ValueError):
            self.b.tell(["parent"], "progress", me="root")

    def test_cleanup_can_be_forced_on_one_named_stuck_agent(self):
        """The escape hatch. An agent whose state never advanced, or that holds mail it
        can never read, is unreachable by every sweep — and there was no other way out."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="stuck", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="keep")
        store.put_message(self.db, from_agent="orch", to_agent="stuck",
                          kind="tell", body="unreadable")
        self.assertEqual(self.b.cleanup(me="orch"), [])                    # every gate holds
        self.assertEqual(self.b.cleanup(["stuck"], me="orch", force=True), ["stuck"])
        self.assertIn("w1:p1", self.h.closed)

    def test_force_refuses_to_be_a_sweep(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        with self.assertRaises(ValueError):
            self.b.cleanup(me="orch", force=True)

    def test_cleanup_never_reaches_outside_the_callers_subtree_by_name_either(self):
        store.create_agent(self.db, name="mine", role="orchestrator")
        store.create_agent(self.db, name="theirs", role="worker", pane_id="w1:p9")
        store.set_state(self.db, "theirs", "done")
        with self.assertRaises(KeyError):
            self.b.cleanup(["theirs"], me="mine", force=True)
        self.assertEqual(self.h.closed, [])

    def test_cleanup_clears_the_pane_it_closed(self):
        """A row still claiming a closed pane defeats the 'already gone' guard, so every
        later sweep retries release/close against a dead pane and logs a failure."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close")
        store.set_state(self.db, "kid", "done")
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])
        self.assertFalse(store.get_agent(self.db, "kid")["pane_id"])
        self.h.closed.clear()
        self.assertEqual(self.b.cleanup(me="orch"), [])                   # nothing retried
        self.assertEqual(self.h.closed, [])

    # -- answers do not ring ----------------------------------------------

    def test_an_answer_to_a_pending_ask_rings_nobody(self):
        """The asker is blocked inside `sb ask` collecting it. Ringing anyway delivered
        every answer three times and cost the asker a turn per ask (C0)."""
        store.create_agent(self.db, name="orch", role="orchestrator", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.put_message(self.db, from_agent="orch", to_agent="kid", kind="ask",
                          body="how many?")
        self.h.prompts.clear()
        [mid] = self.b.tell(["orch"], "42", me="kid")
        self.assertEqual(self.h.prompts, [])                              # no doorbell
        m = store.get_message(self.db, mid)
        self.assertIsNotNone(m["reply_to"])                               # still correlated
        self.assertIsNotNone(m["read_at"])                                # and not pinning
        self.assertIsNotNone(m["delivered_at"])       # so flush_pending will not ring later
        self.assertNotIn(mid, [r["id"] for r in
                               store.undelivered(self.db, exclude=(HUMAN,))])

    def test_an_ordinary_tell_still_rings(self):
        store.create_agent(self.db, name="orch", role="orchestrator", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        self.b.tell(["orch"], "fyi", me="kid")
        self.assertEqual([n for n, _ in self.h.prompts], ["orch"])

    def test_a_blocked_ask_retries_a_doorbell_that_was_held_back(self):
        """Nothing else runs while `ask` blocks, so if it did not re-ring here a question
        sent to a mid-turn agent would wait out its whole timeout unannounced."""
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        self.h.states_by_name = {"kid": "working"}
        rung: list[str] = []

        def go_idle(_):
            self.h.states_by_name = {"kid": "idle"}
            rung.append("turn ended")

        with mock.patch("time.sleep", go_idle):
            self.b.ask(["kid"], "q?", me="orch", timeout=0.1, poll=0.01)
        self.assertEqual([n for n, _ in self.h.prompts], ["kid"])         # rung once, late

    # -- restore ----------------------------------------------------------

    def test_restore_refuses_a_live_agent_before_making_a_tab(self):
        """`agent start` fails all three attempts under a name herdr already runs, and the
        tab created ahead of it was left behind — one orphan pane per attempt."""
        store.create_agent(self.db, name="w", role="worker", session_id="s",
                           cwd=str(self.repo), pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}
        with self.assertRaises(ValueError):
            self.b.restore("w")
        self.assertEqual(self.h.tabs, [])

    def test_a_failed_restore_takes_its_tab_back_out(self):
        store.create_agent(self.db, name="w", role="worker", session_id="s",
                           cwd=str(self.repo), pane_id="w1:p1")

        def boom(*a, **kw):
            raise HerdrError("spawn_failed", "after 3 attempts")

        self.h.start_agent = boom
        with self.assertRaises(HerdrError):
            self.b.restore("w")
        self.assertEqual(len(self.h.closed), 1)

    def test_cleanup_dry_run_closes_nothing(self):
        store.create_agent(self.db, name="orch", role="orchestrator")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", cleanup="close")
        store.set_state(self.db, "kid", "done")
        self.assertEqual(self.b.cleanup(me="orch", dry_run=True), ["kid"])
        self.assertEqual(self.h.closed, [])

    def test_restore_resumes_the_stored_session(self):
        store.create_agent(self.db, name="kid", role="worker", session_id="sess-kid",
                           cwd=str(self.repo), pane_id="w1:p1")
        self.b.restore("kid")
        self.assertEqual(self.h.started[-1]["resume"], "sess-kid")

    def test_restore_comes_back_on_the_roles_tier(self):
        """Restoring must not quietly demote an agent to the CLI's default model."""
        store.create_agent(self.db, name="kid", role="researcher", session_id="sess-kid",
                           cwd=str(self.repo), pane_id="w1:p1")
        self.b.restore("kid")
        self.assertEqual(self.h.started[-1]["model_args"],
                         ["--model", "sonnet", "--effort", "medium"])

    def test_restore_without_a_session_is_an_error(self):
        store.create_agent(self.db, name="kid", role="worker")
        with self.assertRaises(ValueError):
            self.b.restore("kid")

    # -- start (the one command) ------------------------------------------

    def test_start_creates_the_top_orchestrator_as_a_root(self):
        self.h.list_agents = lambda: []
        self.h.focus = lambda n: None
        name = self.b.start()
        a = store.get_agent(self.db, name)
        self.assertEqual(name, MAIN_NAME)
        self.assertIsNone(a["parent"])          # root: parent NULL, not "human"
        self.assertEqual(a["cleanup"], "keep")  # never swept away

    def test_start_returns_to_the_existing_one_by_default(self):
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.h.list_agents = lambda: [HAgent(name=MAIN_NAME, pane_id="w1:p1")]
        before = len(self.h.started)
        self.b.start()
        self.assertEqual(len(self.h.started), before)   # "take me back" is the default

    def test_start_new_spawns_another_top_level(self):
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        first = self.b.start()
        self.h.list_agents = lambda: [HAgent(name=first, pane_id="w1:p1")]
        second = self.b.start(new=True)
        self.assertNotEqual(first, second)
        self.assertEqual(second, "main-2")
        self.assertIsNone(store.get_agent(self.db, second)["parent"])

    def test_start_asks_before_creating_a_second(self):
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.h.list_agents = lambda: [HAgent(name=MAIN_NAME, pane_id="w1:p1")]
        self.restart_sb()
        asked = {}

        def yes(existing):
            asked["existing"] = existing
            return True
        self.assertEqual(self.b.start(confirm=yes), "main-2")
        self.assertEqual(asked["existing"], [MAIN_NAME])

    def test_declining_the_prompt_returns_to_the_existing_one(self):
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.h.list_agents = lambda: [HAgent(name=MAIN_NAME, pane_id="w1:p1")]
        self.assertEqual(self.restart_sb().start(confirm=lambda _: False), MAIN_NAME)

    def test_explicit_name_creates_a_distinct_orchestrator(self):
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.assertEqual(self.b.start(name="triage"), "triage")

    def test_start_restores_a_closed_orchestrator(self):
        """Not running is not the same as gone. `sb start` still means "take me back"."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        store.update_agent(self.db, MAIN_NAME, session_id="sess-main")
        self.restart_sb().start()
        self.assertEqual(self.h.started[-1]["resume"], "sess-main")

    def test_start_with_a_task_tells_an_existing_orchestrator(self):
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.h.list_agents = lambda: [HAgent(name=MAIN_NAME, pane_id="w1:p1")]
        self.restart_sb().start(task="merge PR 41")
        self.assertEqual(store.unread_for(self.db, MAIN_NAME)[-1]["body"], "merge PR 41")

    # -- start: what "already running" is allowed to mean -------------------

    def _dead_top(self, name, state="done"):
        """A top-level orchestrator that ended and said so.

        MAIN is the ROLE every orchestrator has; MAIN_NAME is only the default NAME of
        the top-level one. Passing either where the other belongs matches nothing.
        """
        store.create_agent(self.db, name=name, role=MAIN, pane_id=f"w1:{name}")
        store.set_state(self.db, name, state)

    def test_finished_orchestrators_are_not_already_running(self):
        """The bug: five ended orchestrators announced as live, with only one up.

        The store keeps every root ever created, so the unfiltered query is a history.
        """
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        for i, name in enumerate([MAIN_NAME, "main-2", "main-3", "main-4"]):
            self._dead_top(name, "failed" if i == 2 else "done")
        store.create_agent(self.db, name="main-5", role=MAIN, pane_id="w1:p5")
        self.h.list_agents = lambda: [HAgent(name="main-5", pane_id="w1:p5")]

        asked = {}
        self.assertEqual(
            self.b.start(confirm=lambda e: asked.setdefault("existing", e) and False),
            "main-5")
        self.assertEqual(asked["existing"], ["main-5"])

    def test_an_orchestrator_herdr_has_never_heard_of_is_not_running(self):
        """Nothing writes a row back on an abnormal death — a crash, a pane closed from
        the outside, a herdr restart — so `working` alone proves nothing."""
        self.h.focus = lambda n: None
        store.create_agent(self.db, name=MAIN_NAME, role=MAIN, pane_id="w1:p1")
        self.h.list_agents = lambda: []
        self.assertEqual(self.b._running_tops(), [])

    def test_an_unreachable_herdr_leaves_the_list_alone(self):
        """Fails OPEN, and this is the one that matters: guessing death here spawns a
        second orchestrator on top of a live one."""
        self.h.focus = lambda n: None
        store.create_agent(self.db, name=MAIN_NAME, role=MAIN, pane_id="w1:p1")

        def down():
            raise HerdrError("no_server", "connection refused")
        self.h.list_agents = down
        self.assertEqual(self.b._running_tops(), [MAIN_NAME])

        asked = {}
        self.assertEqual(
            self.restart_sb().start(confirm=lambda e: asked.setdefault("existing", e) and False),
            MAIN_NAME)
        self.assertEqual(asked["existing"], [MAIN_NAME])

    def test_nothing_running_is_not_worth_asking_about(self):
        """With no orchestrator up there is no "another" to start, so `sb start` does
        what it usually means and takes you back to the last one."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self._dead_top(MAIN_NAME)
        store.update_agent(self.db, MAIN_NAME, session_id="sess-main")

        def never(existing):
            raise AssertionError(f"asked about {existing}")
        self.assertEqual(self.b.start(confirm=never), MAIN_NAME)
        self.assertEqual(self.h.started[-1]["resume"], "sess-main")   # taken back, not
                                                                     # replaced

    def test_the_name_slots_of_dead_orchestrators_stay_taken(self):
        """Slot reuse is unchanged: `--new` gets the next free name, not a dead one's."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        for name in (MAIN_NAME, "main-2"):
            self._dead_top(name)
        self.assertEqual(self.b.start(new=True), "main-3")

    # -- worktree config links -------------------------------------------

    def _repo_with_worktree(self):
        import subprocess
        main = self.repo / "main"; main.mkdir()
        run = lambda *a, **k: subprocess.run(a, cwd=k.get("cwd", main), capture_output=True)
        run("git", "init", "-q", "-b", "main")
        run("git", "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "x")
        wt = self.repo / "wt"
        run("git", "worktree", "add", "-q", str(wt), "-b", "side")
        (main / "CLAUDE.md").write_text("# switchboard protocol\n")
        (main / ".switchboard").mkdir()
        return main, wt

    def test_worktree_gets_symlinks_not_copies(self):
        """Config is never committed; a worktree points at the main checkout's copy."""
        main, wt = self._repo_with_worktree()
        b = Broker(self.db, self.h, repo=wt)
        self.assertEqual(sorted(b.link_config()), [".switchboard", "CLAUDE.md"])
        self.assertTrue((wt / "CLAUDE.md").is_symlink())
        self.assertEqual((wt / "CLAUDE.md").resolve(), (main / "CLAUDE.md").resolve())

    def test_linking_is_idempotent_and_never_clobbers(self):
        main, wt = self._repo_with_worktree()
        b = Broker(self.db, self.h, repo=wt)
        b.link_config()
        self.assertEqual(b.link_config(), [])          # second run does nothing
        (wt / "own.md").write_text("mine")
        real = wt / "CLAUDE.md"
        real.unlink(); real.write_text("a real local file")
        self.assertEqual(b.link_config(), [])          # refuses to replace a real file
        self.assertEqual(real.read_text(), "a real local file")

    def test_links_are_git_ignored_locally(self):
        main, wt = self._repo_with_worktree()
        Broker(self.db, self.h, repo=wt).link_config()
        exclude = (main / ".git" / "info" / "exclude").read_text()
        self.assertIn("CLAUDE.md", exclude)             # keeps `git status` clean
        self.assertIn(".switchboard", exclude)

    def test_init_pins_the_main_checkout_for_worktrees_to_find(self):
        main, wt = self._repo_with_worktree()
        Broker(self.db, self.h, repo=main).init()
        self.assertEqual(store.read_config(main)["main_checkout"], str(main))
        # a worktree resolves the same directory without inferring from .git
        self.assertEqual(store.main_checkout(wt).resolve(), main.resolve())

    def test_worktree_links_follow_the_pinned_main(self):
        main, wt = self._repo_with_worktree()
        Broker(self.db, self.h, repo=main).init()
        Broker(self.db, self.h, repo=wt).link_config()
        self.assertEqual((wt / "CLAUDE.md").resolve(), (main / "CLAUDE.md").resolve())

    def test_main_checkout_falls_back_to_inference_when_uninited(self):
        main, wt = self._repo_with_worktree()
        self.assertEqual(store.main_checkout(wt).resolve(), main.resolve())  # works pre-init

    def test_main_checkout_links_nothing(self):
        main, _ = self._repo_with_worktree()
        self.assertEqual(Broker(self.db, self.h, repo=main).link_config(), [])

    # -- init ------------------------------------------------------------

    def test_init_writes_no_claude_md_anywhere(self):
        """Ordinary Claude sessions must never see the protocol.

        A global ~/.claude/CLAUDE.md leaks into every session everywhere; a repo
        CLAUDE.md leaks into every session in that repo and is usually tracked.
        """
        main, _ = self._repo_with_worktree()
        (main / "CLAUDE.md").unlink()
        Broker(self.db, self.h, repo=main).init()
        self.assertFalse((main / "CLAUDE.md").exists())

    def test_init_pins_and_excludes_only(self):
        main, _ = self._repo_with_worktree()
        Broker(self.db, self.h, repo=main).init()
        self.assertEqual(store.read_config(main)["main_checkout"], str(main))
        self.assertIn(".switchboard", (main / ".git" / "info" / "exclude").read_text())

    # -- protocol travels as a system prompt -----------------------------

    def test_every_agent_gets_the_protocol_at_spawn(self):
        from switchboard.broker import PROTOCOL_LINE
        self.b.delegate("t", role="worker", me="orch")
        self.assertIn(PROTOCOL_LINE, self.h.started[0]["prompts"])

    def test_protocol_is_single_line(self):
        """herdr rejects newlines in agent args outright — length is fine."""
        from switchboard.broker import PROTOCOL_LINE
        self.assertNotIn("\n", PROTOCOL_LINE)
        self.assertIn("sb done", PROTOCOL_LINE)
        self.assertIn("sb block", PROTOCOL_LINE)
        self.assertNotIn("sb ask human", PROTOCOL_LINE)   # there is only one way

    def test_protocol_cannot_go_stale(self):
        """Generated at every spawn, so there is no copy to fall out of date."""
        from switchboard import broker as bmod
        with mock.patch.object(bmod, "PROTOCOL_LINE", "NEW PROTOCOL v2"):
            self.b.delegate("t", role="worker", me="orch")
        self.assertIn("NEW PROTOCOL v2", self.h.started[-1]["prompts"])

    def test_a_repo_can_replace_the_protocol_and_it_reaches_the_spawn(self):
        """The config layer, end to end: a file in this repo, a flag on this spawn.

        Wholesale, not merged — see config.protocol. A protocol assembled from a shipped
        half and a repo half is a protocol nobody can read.
        """
        from switchboard.broker import PROTOCOL_LINE
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "protocol.md").write_text("# ours\n\nSAY LESS.\n")
        Broker(self.db, self.h, repo=self.repo).delegate("t", role="worker", me="orch")
        prompts = self.h.started[-1]["prompts"]
        self.assertIn("SAY LESS.", prompts)
        self.assertNotIn(PROTOCOL_LINE, prompts)

    def test_a_repo_can_reword_a_spawn_prompt_without_touching_python(self):
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "prompts.toml").write_text(
            '[spawn]\nidentity = "You are {name}. {parent} sent you."\n')
        Broker(self.db, self.h, repo=self.repo).delegate(
            "t", role="worker", name="w9", me="orch")
        self.assertIn("You are w9. orch sent you.", self.h.started[-1]["prompts"])

    def test_a_repo_role_prompt_reaches_the_spawn(self):
        """A markdown file in `.switchboard/roles/`, straight onto the agent's system
        prompt — the whole point of a role's prompt being prose in a file."""
        d = self.repo / ".switchboard" / "roles"
        d.mkdir(parents=True, exist_ok=True)
        (d / "worker.md").write_text("+++\n+++\n\nMeasure twice.\n")
        Broker(self.db, self.h, repo=self.repo).delegate("t", role="worker", me="orch")
        self.assertIn("Measure twice.", self.h.started[-1]["prompts"])

    # -- worktree config links -------------------------------------------

    def _repo_with_worktree(self):
        import subprocess
        main = self.repo / "main"; main.mkdir()
        run = lambda *a, **k: subprocess.run(a, cwd=k.get("cwd", main), capture_output=True)
        run("git", "init", "-q", "-b", "main")
        run("git", "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "x")
        wt = self.repo / "wt"
        run("git", "worktree", "add", "-q", str(wt), "-b", "side")
        (main / "CLAUDE.md").write_text("# switchboard protocol\n")
        (main / ".switchboard").mkdir()
        return main, wt

    def test_worktree_gets_symlinks_not_copies(self):
        """Config is never committed; a worktree points at the main checkout's copy."""
        main, wt = self._repo_with_worktree()
        b = Broker(self.db, self.h, repo=wt)
        self.assertEqual(sorted(b.link_config()), [".switchboard", "CLAUDE.md"])
        self.assertTrue((wt / "CLAUDE.md").is_symlink())
        self.assertEqual((wt / "CLAUDE.md").resolve(), (main / "CLAUDE.md").resolve())

    def test_linking_is_idempotent_and_never_clobbers(self):
        main, wt = self._repo_with_worktree()
        b = Broker(self.db, self.h, repo=wt)
        b.link_config()
        self.assertEqual(b.link_config(), [])          # second run does nothing
        (wt / "own.md").write_text("mine")
        real = wt / "CLAUDE.md"
        real.unlink(); real.write_text("a real local file")
        self.assertEqual(b.link_config(), [])          # refuses to replace a real file
        self.assertEqual(real.read_text(), "a real local file")

    def test_links_are_git_ignored_locally(self):
        main, wt = self._repo_with_worktree()
        Broker(self.db, self.h, repo=wt).link_config()
        exclude = (main / ".git" / "info" / "exclude").read_text()
        self.assertIn("CLAUDE.md", exclude)             # keeps `git status` clean
        self.assertIn(".switchboard", exclude)

    def test_init_pins_the_main_checkout_for_worktrees_to_find(self):
        main, wt = self._repo_with_worktree()
        Broker(self.db, self.h, repo=main).init()
        self.assertEqual(store.read_config(main)["main_checkout"], str(main))
        # a worktree resolves the same directory without inferring from .git
        self.assertEqual(store.main_checkout(wt).resolve(), main.resolve())

    def test_worktree_links_follow_the_pinned_main(self):
        main, wt = self._repo_with_worktree()
        Broker(self.db, self.h, repo=main).init()
        Broker(self.db, self.h, repo=wt).link_config()
        self.assertEqual((wt / "CLAUDE.md").resolve(), (main / "CLAUDE.md").resolve())

    def test_main_checkout_falls_back_to_inference_when_uninited(self):
        main, wt = self._repo_with_worktree()
        self.assertEqual(store.main_checkout(wt).resolve(), main.resolve())  # works pre-init

    def test_main_checkout_links_nothing(self):
        main, _ = self._repo_with_worktree()
        self.assertEqual(Broker(self.db, self.h, repo=main).link_config(), [])

    # -- init ------------------------------------------------------------

    # -- protocol sync ---------------------------------------------------



class WorkspacePlacementTest(unittest.TestCase):
    """Which herdr workspace a child's tab is created in.

    There are five possible answers and they disagree in practice. Resolving a workspace
    NAME goes via its checkout path, and one checkout can be open in several herdr
    workspaces at once — so the name lookup is one-to-many with nothing to validate the
    answer. Observed: `main`, living in w7 over the main checkout, delegated a child and
    the child landed in w1, the OTHER workspace over that same checkout.

    Every tier here except the last is a statement of fact about where the parent IS.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdrAPI()
        self.b = Broker(self.db, self.h, repo=self.repo)
        self.derived: list = []                  # every name the path derivation was asked
        self.b._workspace_id = self._derive

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _derive(self, name):
        self.derived.append(name)
        return "w-derived"

    def _parent(self, **kw):
        store.create_agent(self.db, name="parent", role="main", workspace="main",
                           cwd=str(self.repo), pane_id="p-parent", **kw)

    def _live(self, wsid):
        """What `agent list` says about the parent's pane right now."""
        self.h.get_agent = lambda n: Agent(name=n, pane_id="p-parent", workspace_id=wsid)

    def _spawn(self, *, env="w-env", **kw):
        with mock.patch.dict(os.environ, {}, clear=False):
            if env:
                os.environ["HERDR_WORKSPACE_ID"] = env
            else:
                os.environ.pop("HERDR_WORKSPACE_ID", None)
            name = self.b.delegate("t", role="worker", me="parent", **kw)
        return self.h.tabs[-1], name

    # -- the order -------------------------------------------------------

    def test_explicit_argument_wins(self):
        self._parent(workspace_id="w-store")
        self._live("w-live")
        self.assertEqual(self._spawn(workspace_id="w-arg")[0], "w-arg")
        self.assertEqual(self.derived, [])

    def test_the_parents_recorded_id_beats_everything_below_it(self):
        self._parent(workspace_id="w-store")
        self._live("w-live")
        self.assertEqual(self._spawn()[0], "w-store")
        self.assertEqual(self.derived, [])

    def test_the_live_pane_answers_when_nothing_was_recorded(self):
        self._parent()                            # pre-existing row, workspace_id NULL
        self._live("w-live")
        self.assertEqual(self._spawn()[0], "w-live")
        self.assertEqual(self.derived, [])

    def test_the_injected_env_answers_when_herdr_has_forgotten_the_agent(self):
        self._parent()
        self.h.get_agent = lambda n: None         # herdr loses name bindings; it happens
        self.assertEqual(self._spawn()[0], "w-env")
        self.assertEqual(self.derived, [])

    def test_the_path_derivation_is_the_last_resort(self):
        self._parent()
        self.h.get_agent = lambda n: None
        self.assertEqual(self._spawn(env=None)[0], "w-derived")
        self.assertEqual(self.derived, ["main"])  # only now is the name resolved

    def test_a_herdr_adapter_without_get_agent_still_spawns(self):
        """The adapter is replaceable by design; a missing method must not cost a spawn."""
        self._parent()
        self.assertEqual(self._spawn()[0], "w-env")

    # -- the bug ---------------------------------------------------------

    def test_a_child_lands_where_its_parent_is_not_where_the_name_resolves(self):
        """The regression. `main` is in wA; the name 'main' resolves to wB."""
        self._parent(workspace_id="wA")
        self.b._workspace_id = lambda name: "wB"
        tab, _ = self._spawn(env="wB")
        self.assertEqual(tab, "wA")

    # -- persistence -----------------------------------------------------

    def test_the_resolved_id_is_recorded_not_re_derived(self):
        """The right answer used to be computed once and thrown away, forcing every later
        spawn to guess again."""
        self._parent(workspace_id="wA")
        _, child = self._spawn()
        self.assertEqual(store.get_agent(self.db, child)["workspace_id"], "wA")

    def test_a_grandchild_inherits_it_through_the_store(self):
        self._parent(workspace_id="wA")
        _, child = self._spawn()
        self.derived.clear()
        self.b.delegate("t", role="worker", me=child)
        self.assertEqual(self.h.tabs[-1], "wA")
        self.assertEqual(self.derived, [])

    def test_a_row_with_no_workspace_id_does_not_crash(self):
        """Rows predating the column read as NULL, which must fall through, not raise."""
        self._parent()
        self.h.get_agent = lambda n: None
        self.assertEqual(self._spawn()[0], "w-env")
        self.assertIsNone(store.get_agent(self.db, "parent")["workspace_id"])

    def test_restore_brings_an_agent_back_to_its_recorded_workspace(self):
        """Same ambiguity, same answer: the name lookup would put it somewhere else."""
        self._parent(workspace_id="wA", session_id="sess-parent")
        self.b._workspace_id = lambda name: "wB"
        self.b.restore("parent")
        self.assertEqual(self.h.tabs[-1], "wA")
