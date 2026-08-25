"""Broker tests — the verb semantics.

A fake herdr records what would have been called, so these run fast and spawn nothing.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import status  # noqa: E402
from switchboard import store  # noqa: E402
from switchboard import broker as broker_mod  # noqa: E402
from switchboard.broker import (  # noqa: E402
    HUMAN, INTERRUPT, MAIN, MAIN_NAME, NEXT_TURN, WHEN_IDLE, Broker, PaneNotReady,
    SbUnpinned, TaskUndelivered, Undeliverable,
)
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
        self.pane_waits: list[tuple] = []
        self.unreachable: set = set()
        self.undeliverable: set = set()   # started, but never takes a task
        self.proofs: list[tuple] = []     # (name, the delivery proof it was given)
        self.states_by_name: dict = {}
        # Names herdr LISTS but no longer answers to — what `sb done` leaves behind. The
        # row comes back as `{"agent": "<name>"}` with no name binding, which is a
        # different fact from being absent and the one `Agent.bound` carries.
        self.evicted: set = set()
        self.list_error: Optional[HerdrError] = None   # herdr itself cannot be asked
        self.workspaces: list = []
        self.tabs: list = []
        self.bases: list[tuple[str, str]] = []   # (branch forked, what it was forked FROM)
        self.checks = 0
        self._wt = tempfile.TemporaryDirectory()   # where forked checkouts land
        self.check_error: Optional[HerdrError] = None   # a conflicting integration
        self.tab_envs: list[dict] = []
        self.workspace_envs: list[dict] = []
        self._n = 0

    def check(self, **kw):
        self.checks += 1
        if self.check_error:
            raise self.check_error

    def create_tab(self, *, workspace=None, env=None, **kw):
        self._n += 1
        self.tabs.append(workspace)
        # Kept because it is the one thing only the broker can get right: a pane's
        # environment is fixed when its shell launches, so anything an agent's process
        # must see has to be decided before `agent start` — see `Broker._spawn_env`.
        self.tab_envs.append(dict(env or {}))
        return f"{workspace or 'w1'}:p{self._n}"

    def start_agent(self, name, pane, *, prompts=(), model_args=(), spec=None,
                    resume=None, **kw):
        self.started.append({"name": name, "pane": pane, "prompts": list(prompts),
                             "model_args": list(model_args), "resume": resume,
                             "provider": getattr(spec, "provider", None),
                             "model": getattr(spec, "model", None)})
        return Agent(name=name, pane_id=pane, terminal_id=f"term_{name}",
                     session_id=f"sess-{name}")

    def prompt(self, name, text):
        if name in self.unreachable:
            from switchboard.herdr import HerdrError
            raise HerdrError("agent_not_found", f"agent target {name} not found")
        self.prompts.append((name, text))

    def deliver(self, name, text, *, proof=None, **kw):
        """The confirmed prompt. The confirming itself is `Herdr.deliver`'s own test —
        here it is a prompt that either lands or raises, which is all `delegate` sees.
        `proof` is kept so the one thing only the broker can get right — which agent's
        transcript is consulted — can be checked."""
        self.proofs.append((name, proof))
        if name in self.undeliverable:
            from switchboard.herdr import HerdrError
            raise HerdrError("not_delivered", f"{name}: never started a turn")
        self.prompt(name, text)

    def prompt_pane(self, pane, text): self.pane_prompts.append((pane, text))

    def wait_output(self, pane_id, match, *, timeout_ms):
        """A pane that answers. Every spawn now proves its pane before typing 12KB of
        system prompt into it (`Broker._ready_pane`), so a fake that could not answer
        would refuse every spawn in this file. The pane that will NOT answer is
        `PinningHerdr`, below, which is where that half is tested."""
        self.pane_waits.append((pane_id, match))
        return True

    def list_agents(self):
        from switchboard.herdr import Agent as _A
        if self.list_error:
            raise self.list_error
        return [_A(name=n, pane_id="w1:p0", state=st, bound=n not in self.evicted)
                for n, st in self.states_by_name.items()]

    def get_agent(self, name):
        """One name out of `list_agents`, which is exactly what the real one is
        (`Herdr.get_agent` — the same reading, narrowed). Not a capability of its own:
        `states_by_name` is still the only place a state comes from here."""
        return next((a for a in self.list_agents() if a.name == name), None)

    def create_worktree(self, branch, *, base="main", cwd=None, label=None):
        """A herdr that CAN fork.

        It has to be able to: the fork rule sends every child of a parent without a
        worktree to `_fork_for`, and a fork that fails now refuses the spawn rather than
        quietly putting the child in its parent's checkout (`ForkFailed`). A fake that
        cannot fork would make most of this file a test of that refusal.

        Real workspace identity — one workspace per branch, a second create refused — is
        `test_workspace`'s FakeHerdr. This one only needs to hand back the shape.
        """
        self._n += 1
        self.bases.append((branch, base))
        path = Path(self._wt.name) / branch
        path.mkdir(parents=True, exist_ok=True)     # a checkout anything can chdir into
        return {"workspace": {"workspace_id": f"wt{self._n}", "label": branch,
                              "worktree": {"checkout_path": str(path)}},
                "worktree": {"path": str(path), "branch": branch},
                "root_pane": {"pane_id": f"wt{self._n}:p1"}}

    def create_workspace(self, label, *, cwd=None, focus=False, env=None):
        self._ws = getattr(self, "_ws", 100) + 1
        self.workspaces.append(label)
        self.workspace_envs.append(dict(env or {}))
        return {"workspace": {"workspace_id": f"w{self._ws}"},
                "root_pane": {"pane_id": f"w{self._ws}:p1"}}
    def send_keys(self, name, *keys): self.keys.append((name, keys))
    def notify(self, text): self.notifications.append(text)
    def report_state(self, pane, name, state, seq, **kw): self.states.append((name, state, pane))
    def report_session(self, pane, name, sid, seq, **kw): pass
    def release_agent(self, pane, name, seq): pass
    def close_pane(self, pane): self.closed.append(pane)


class EvictingHerdr(FakeHerdrAPI):
    """A herdr that charges the real price for reporting state.

    `pane report-agent` replaces the pane's named agent with a source-reported record, and
    a reported record is not a target — `agent prompt <name>` answers agent_not_found from
    then on, permanently (`Herdr.report_state` carries the measurement). The pane stays in
    `agent list`, which is why `_binding_lost` can tell this apart from a dead agent, so
    `states_by_name` is left alone.

    Only the tests that are about that price use this. Everywhere else the plain fake keeps
    reporting free, which is what makes those tests about their own subject.
    """

    def report_state(self, pane, name, state, seq, **kw):
        super().report_state(pane, name, state, seq, **kw)
        self.unreachable.add(name)


class SilentSessionHerdr(FakeHerdrAPI):
    """The herdr that is actually installed: `agent start` names no session.

    The plain fake hands one back, which is convenient everywhere else and is not what
    0.8.x does — checked against every stored reply in the live store's event log. Only
    the tests about where a session id comes from when herdr supplies none use this.
    """

    def start_agent(self, name, pane, **kw):
        a = super().start_agent(name, pane, **kw)
        return replace(a, session_id="")


def reap_gone(db, h):
    """Get an absent agent recorded as `failed` — two readings, a grace window apart.

    One `agent list` that comes back short only remembers the absence now; it takes a
    second look past `GONE_CONFIRM_GRACE` to write the verdict (`status._confirmed_gone`).
    Every test here that wants a reaped row wants both, and none of them care about the
    debounce itself — that is `test_status`'s subject.
    """
    status.collect(db, h)
    status.collect(db, h, now=store.now() + int(status.GONE_CONFIRM_GRACE) + 1)


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

    # -- delegate --------------------------------------------------------

    def test_delegate_lands_in_the_callers_own_workspace(self):
        """An empty workspace id means "wherever herdr is focused" — which is whatever
        was focused last, so a child would land in a stranger's workspace.

        Delegated by a parent that HAS a worktree, because that is the case with a tab in
        it: a parent without one forks, and a forked child gets the fresh workspace's own
        root pane rather than a tab anywhere.
        """
        self.h.tabs = []
        store.create_agent(self.db, name="lead", role="lead", workspace="api",
                           branch="api", cwd=str(self.repo))
        with mock.patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "w1"}, clear=False):
            self.b.delegate("t", topic="t", role="worker", me="lead")
        self.assertEqual(self.h.tabs[-1], "w1")

    def test_delegate_records_parent_and_pokes_with_the_task(self):
        name = self.b.delegate("compute 2+2", topic="t", role="worker", me="orch")
        a = store.get_agent(self.db, name)
        self.assertEqual(a["parent"], "orch")
        self.assertEqual(a["session_id"], f"sess-{name}")
        self.assertIn((name, "compute 2+2"), self.h.prompts)

    def test_role_selects_a_model_tier(self):
        """A role names a tier; what reaches the CLI is that tier's resolved flags.

        Effort rides along — the bug this replaces passed only the model id, so a tier's
        effort was silently dropped on every spawn.
        """
        self.b.delegate("t", topic="t", role="researcher", me="orch")   # cheap
        self.assertEqual(self.h.started[0]["model_args"],
                         ["--model", "sonnet", "--effort", "medium"])

    def test_an_explicit_model_is_a_tier_name_too(self):
        """`--model strong` must be resolved, not handed to the CLI as a model id."""
        self.b.delegate("t", topic="t", role="worker", model="strong", me="orch")
        self.assertEqual(self.h.started[0]["model_args"],
                         ["--model", "opus", "--effort", "high"])

    def test_a_spawn_names_its_agent_in_its_pane_s_environment(self):
        """`SB_AGENT` for EVERY agent, whatever the provider, and before `agent start`
        types the provider's command line into that shell.

        Asserted on the READY-PANE command rather than on `--env`, because that is the one
        channel every pane has: `--env` reaches every pane switchboard creates, and the
        root pane of a forked worktree is handed over ready-made by a `worktree create`
        that takes no `--env` at all. The export covers that one and costs nothing where
        `--env` already did the job.
        """
        name = self.b.delegate("t", topic="t", role="worker", me="orch")
        typed = " ".join(cmd for _, cmd in self.h.pane_prompts)
        self.assertIn(f"export SB_AGENT={name}", typed)

    def test_unknown_role_still_works(self):
        """Vocabulary is data — an undefined role inherits defaults, it does not error."""
        name = self.b.delegate("t", topic="t", role="wizard", me="orch")
        self.assertEqual(store.get_agent(self.db, name)["role"], "wizard")

    # -- a spawn is not a success until the task is in ----------------------

    def test_a_task_that_never_arrives_fails_the_spawn_loudly(self):
        """The bug that quietly lost agents: `delegate` returned a name for an agent whose
        task was never delivered, so the caller believed it had delegated and the work was
        done by nobody. See BUILD-PLAN item 1.1."""
        self.h.undeliverable.add("ghost")
        with self.assertRaises(TaskUndelivered) as cm:
            self.b.delegate("do the thing", role="worker", name="ghost", me="orch")
        self.assertEqual(cm.exception.name, "ghost")
        self.assertIn("ghost", str(cm.exception))

    def test_an_agent_with_no_task_is_not_recorded_as_working(self):
        """It started, so it is not a husk — but it is not doing the work either, and a
        row saying `working` is the lie the whole fix exists to stop telling."""
        self.h.undeliverable.add("ghost")
        with self.assertRaises(TaskUndelivered):
            self.b.delegate("t", role="worker", name="ghost", me="orch")
        a = store.get_agent(self.db, "ghost")
        self.assertEqual(a["state"], "failed")
        self.assertTrue(a["pane_id"])          # something IS in that pane; keep the handle
        self.assertTrue(a["session_id"])
        kinds = [e["kind"] for e in store.recent_events(self.db, limit=50)]
        self.assertIn("task_undelivered", kinds)

    def test_an_unconfirmed_delivery_to_a_working_agent_is_not_a_failed_spawn(self):
        """The false failure: `sb delegate` exited 1 for an agent that was doing the work.

        The confirmation is the child's own transcript and the child flushes it when it
        feels like it — 35 s late, measured, under a six-way fan-out. Twice in a 42-agent
        acceptance run the spawn called that a lost task, recorded the agent `failed`, and
        told the caller to respawn the work and `sb cleanup --force` the pane. Both agents
        were running. An agent herdr has in a turn is not the dead pane that error
        describes, so it is returned with the caveat instead of raised over.
        """
        self.h.undeliverable.add("ghost")
        self.h.states_by_name["ghost"] = "working"
        name = self.b.delegate("do the thing", role="worker", name="ghost", me="orch")
        self.assertEqual(name, "ghost")
        a = store.get_agent(self.db, "ghost")
        self.assertEqual(a["state"], "working")        # never stamped over
        self.assertIsNone(a["ended_at"])
        note = self.b.delivery_note
        self.assertIn("not confirmed", note)           # and the caller is told so
        self.assertNotIn("--force", note)              # but not told to kill it
        kinds = [e["kind"] for e in store.recent_events(self.db, limit=50)]
        self.assertIn("task_unconfirmed", kinds)
        self.assertNotIn("task_undelivered", kinds)

    def test_an_agent_that_reported_done_is_never_recorded_failed(self):
        """The sharpest case in the acceptance run, to the second.

        `a4f5` wrote `done` with its summary at 05:02:32 and the spawn overwrote the row
        with `failed` at 05:02:33 — after which `sb status` printed the contradiction on
        two lines of one row and `sb cleanup` refused the row because "nobody reported
        this end". A row that says `done` was written BY the agent, through `sb`; it
        cannot have reported an end it never ran to.
        """
        class ReportsWhileWeWait(FakeHerdrAPI):
            """The child, not herdr: it finishes and reports mid-delivery, which is
            exactly the one-second race that was measured."""

            def __init__(self, db):
                super().__init__()
                self.db = db

            def deliver(self, name, text, *, proof=None, **kw):
                store.set_state(self.db, name, "done")
                super().deliver(name, text, proof=proof, **kw)

        self.h = ReportsWhileWeWait(self.db)
        self.h.undeliverable.add("ghost")
        self.b = Broker(self.db, self.h, repo=self.repo)
        name = self.b.delegate("do the thing", role="worker", name="ghost", me="orch")
        self.assertEqual(name, "ghost")
        self.assertEqual(store.get_agent(self.db, "ghost")["state"], "done")
        self.assertIn("reported done", self.b.delivery_note)

    def test_a_task_that_landed_just_too_late_is_not_a_failed_spawn(self):
        """The 0.9-second false negative: proof on disk, deadline already past.

        `deliver` polls for the task in the child's transcript and gives up on a clock;
        herdr's own state lags a prompt submitted a second ago and the row is not yet
        `done`. So both of the safety net's old questions answer no while the words are
        sitting in the child's transcript — measured, written at 00:16:32.619Z with the
        spawn giving up at 00:16:33.475Z. The safety net has to read the same evidence
        `deliver`'s proof reads, or a running agent is stamped gone.
        """
        home = Path(self.tmp.name) / "latehome"

        class WritesTheTranscriptTooLate(FakeHerdrAPI):
            """The child, not herdr: it submits the task while delivery is timing out,
            which is the whole of the race."""

            def deliver(self, name, text, *, proof=None, **kw):
                cwd = store.get_agent(broker_self.db, name)["cwd"]
                d = home / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", cwd)
                d.mkdir(parents=True, exist_ok=True)
                (d / "sess.jsonl").write_text(json.dumps({
                    "type": "user",
                    "message": {"role": "user", "content": text},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }) + "\n")
                super().deliver(name, text, proof=proof, **kw)

        broker_self = self
        self.h = WritesTheTranscriptTooLate()
        self.h.undeliverable.add("ghost")          # every send timed out
        self.b = Broker(self.db, self.h, repo=self.repo)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            name = self.b.delegate("do the thing", role="worker", name="ghost", me="orch")
        self.assertEqual(name, "ghost")
        a = store.get_agent(self.db, "ghost")
        self.assertEqual(a["state"], "working")    # never stamped gone
        self.assertIn("transcript", self.b.delivery_note)
        kinds = [e["kind"] for e in store.recent_events(self.db, limit=50)]
        self.assertIn("task_unconfirmed", kinds)
        self.assertNotIn("task_undelivered", kinds)

    def test_a_transcript_that_holds_nothing_still_fails_the_spawn(self):
        """The other side of the same line: a real transcript directory, and no task in
        it, is still a lost task. The new check must not be a way to pass by existing."""
        home = Path(self.tmp.name) / "emptyhome"
        self.h.undeliverable.add("ghost")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            with self.assertRaises(TaskUndelivered):
                self.b.delegate("do the thing", role="worker", name="ghost", me="orch")
        self.assertEqual(store.get_agent(self.db, "ghost")["state"], "failed")

    def test_delivery_is_confirmed_against_the_childs_own_transcript(self):
        """The wiring only the broker can get right: WHOSE record proves the delivery.

        `deliver` is handed a callable, and the callable has to look in the child's own
        checkout — the transcript bucket is keyed by cwd, so a proof pointed anywhere
        else would answer for some other agent, or for nobody.
        """
        name = self.b.delegate("do the thing", topic="t", role="worker", me="orch")
        who, proof = self.h.proofs[-1]
        self.assertEqual(who, name)
        self.assertIsNotNone(proof)

        cwd = store.get_agent(self.db, name)["cwd"]
        home = Path(self.tmp.name) / "fakehome"
        now = time.time()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.assertFalse(proof(now))       # nothing submitted anywhere yet
            d = home / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", cwd)
            d.mkdir(parents=True)
            (d / "sess.jsonl").write_text(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "do the thing"},
                "timestamp": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            }) + "\n")
            self.assertTrue(proof(now - 1))

    def _transcript(self, home: Path, cwd: str, session_id: str, text: str) -> Path:
        """A Claude Code transcript for `session_id`, holding `text` as a submitted turn."""
        d = home / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", cwd)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{session_id}.jsonl"
        p.write_text(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": text},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }) + "\n")
        return p

    def test_a_spawn_records_the_session_before_the_agent_runs_anything(self):
        """The gap two agents were permanently lost through on 2026-08-16.

        `session_id` is otherwise written only by `_claim_session`, off the agent's own
        first `sb` command — so an agent killed, interrupted or superseded before it ran
        one had no session on its row and `sb restore` had nothing to restore. The
        delivery proof has already found the right transcript by content; this keeps it.
        """
        self.b = Broker(self.db, SilentSessionHerdr(), repo=self.repo)
        store.create_agent(self.db, name="orch", role="lead", cwd=str(self.repo),
                           workspace="ws", branch="ws")
        home = Path(self.tmp.name) / "home-capture"
        self._transcript(home, str(self.repo), "sess-from-transcript", "do the thing")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            name = self.b.delegate("do the thing", topic="t", role="worker", me="orch")
        # Nothing here ran `sb` as the child: the id came from its transcript.
        self.assertEqual(store.get_agent(self.db, name)["session_id"],
                         "sess-from-transcript")

    def test_two_children_in_one_cwd_each_get_their_own_session(self):
        """`delegate` shares one cwd between a parent and all its children, so the
        transcript bucket holds several live sessions at once. Matching on the task text
        is what keeps a child from claiming its sibling's session — the shape that made
        after-the-fact recovery by cwd plus timing unsound."""
        self.b = Broker(self.db, SilentSessionHerdr(), repo=self.repo)
        store.create_agent(self.db, name="orch", role="lead", cwd=str(self.repo),
                           workspace="ws", branch="ws")
        home = Path(self.tmp.name) / "home-siblings"
        self._transcript(home, str(self.repo), "sess-first", "review the design")
        self._transcript(home, str(self.repo), "sess-second", "rewrite the parser")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            one = self.b.delegate("review the design", topic="t", role="worker", me="orch")
            two = self.b.delegate("rewrite the parser", topic="t", role="worker", me="orch")
        self.assertEqual(store.get_agent(self.db, one)["session_id"], "sess-first")
        self.assertEqual(store.get_agent(self.db, two)["session_id"], "sess-second")

    def test_a_session_herdr_reported_itself_is_not_overwritten(self):
        """If herdr ever starts answering with a real session id, its answer wins: this
        is a fallback for the hole, not a second opinion about a filled column."""
        home = Path(self.tmp.name) / "home-noclobber"
        store.create_agent(self.db, name="orch", role="lead", cwd=str(self.repo),
                           workspace="ws", branch="ws")
        self._transcript(home, str(self.repo), "sess-from-transcript", "do the thing")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            name = self.b.delegate("do the thing", topic="t", role="worker", me="orch")
        self.assertEqual(store.get_agent(self.db, name)["session_id"], f"sess-{name}")

    def test_as_prompt_overrides_the_role_prompt(self):
        self.b.delegate("t", topic="t", role="worker", me="orch",
                        as_prompt="You are a haiku critic.")
        joined = " ".join(self.h.started[0]["prompts"])
        self.assertIn("haiku critic", joined)

    # -- what a spawn is told exists ---------------------------------------

    def test_every_spawn_is_told_what_roles_exist(self):
        """DESIGN-TRUTH: "The role list is lightly audited and fine as it is" — knowing
        there are roles, and which."""
        self.b.delegate("t", topic="t", role="worker", me="orch")
        joined = " ".join(self.h.started[0]["prompts"])
        for role in ("dispatcher", "lead", "worker", "qa", "researcher", "reviewer"):
            with self.subTest(role=role):
                self.assertIn(role, joined)

    def test_the_role_list_is_generated_from_the_roles_and_not_written_down(self):
        """The whole of the requirement, and the only test that can tell the two apart:
        a role this repo invented appears in the spawn prompt with no code or prompt text
        edited. A hardcoded list passes every other check and fails this one."""
        d = self.repo / ".switchboard" / "roles"
        d.mkdir(parents=True)
        (d / "archaeologist.md").write_text("You dig.\n")
        self.restart_sb()                     # roles are read once, at Broker construction
        self.b.delegate("t", topic="t", role="worker", me="orch")
        self.assertIn("archaeologist", " ".join(self.h.started[0]["prompts"]))

    # -- the operator menu: the dispatcher's, and nobody else's ------------

    def _started_prompts(self) -> str:
        return " ".join(self.h.started[-1]["prompts"])

    def _start_top(self) -> str:
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        return self.b.start()

    def test_the_dispatcher_is_told_what_operator_procedures_this_repo_offers(self):
        """The menu exists so a person standing in front of a waiting dispatcher can be
        told what it can run, without the list being written into anyone's prose. The
        readable name leads and the command follows: the human picks by meaning, so what
        they can be shown has to be the plain words, not `sb presets sb-setup`."""
        self._start_top()
        joined = self._started_prompts()
        self.assertIn("sb presets sb-setup", joined)
        self.assertLess(joined.index("set up this repo's switchboard config"),
                        joined.index("sb presets sb-setup"))

    def test_the_menu_is_ordered_into_the_dispatchers_first_message(self):
        """The list existing in the prompt is not the requirement: dispatchers read the
        older factual phrasing and sat on the menu forever. It has to be an order about
        the very first message, an invitation the person can answer, and one that does
        not demand the list again after that."""
        self._start_top()
        joined = self._started_prompts()
        self.assertIn("very first message", joined)
        self.assertIn("Would you like to run any of these?", joined)
        self.assertIn("bulleted line", joined)
        self.assertIn("only if someone asks", joined)
        self.assertIn("repeating it unprompted is noise", joined)

    def test_a_worker_is_not_told_any_of_it(self):
        """Gated on the role, not merely on the registry being non-empty: the menu is one
        line of every spawn prompt, and only the dispatcher is ever asked to run one."""
        self.b.delegate("t", topic="t", role="worker", me="orch")
        self.assertNotIn("sb presets sb-setup", self._started_prompts())

    def test_a_repo_that_resets_the_registry_to_nothing_gets_no_fragment_at_all(self):
        """Empty means absent, the way `spawn.workspace` is absent for an agent with no
        workspace — not a dispatcher told it offers "these procedures: "."""
        d = self.repo / ".switchboard"
        d.mkdir(parents=True, exist_ok=True)
        (d / "operator_skills.toml").write_text('skill = ["!reset"]\n')
        self._start_top()
        joined = self._started_prompts()
        self.assertNotIn("sb presets sb-setup", joined)
        self.assertNotIn("Would you like to run any of these?", joined)

    def test_a_wrapped_description_does_not_kill_every_dispatcher_spawn(self):
        """`config.prompt` flattens the TEMPLATE and interpolates after, so a description
        that wraps in someone's `operator_skills.toml` would reach `Herdr.start_agent`
        with a newline still in it — and that is refused, turning a cosmetic line break
        into a dead `sb start` for every dispatcher. Each field is flattened on the way in.
        """
        d = self.repo / ".switchboard"
        d.mkdir(parents=True, exist_ok=True)
        (d / "operator_skills.toml").write_text(
            'skill = ["!reset", {command = "sb presets deploy", '
            'description = """ship it\nwhen the tests are green"""}]\n')
        self._start_top()
        prompts = self.h.started[-1]["prompts"]
        for p in prompts:                      # the rule Herdr.start_agent enforces
            self.assertNotIn("\n", p)
        joined = " ".join(prompts)
        self.assertIn("ship it", joined)
        self.assertIn("when the tests are green", joined)

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
        name = self.b.delegate("t", topic="t", role="worker", me="orch")
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
            name = self.b.delegate("t", topic="t", role="worker", me="orch")
        a = store.get_agent(self.db, name)
        self.assertEqual(a["state"], "working")
        self.assertIsNone(a["ended_at"])

    def _spawn_fails(self):
        def boom(*a, **kw):
            raise HerdrError("spawn_failed", "after 3 attempts: pane not ready")
        self.h.start_agent = boom

    def test_a_spawn_that_exhausts_its_retries_leaves_a_recorded_failure(self):
        """The claim used to be DELETED on the way out, which threw away the only
        evidence the attempt ever happened: real herdr effort, spent and failed loudly,
        and afterwards nothing on the board for a caller who backgrounded the spawn."""
        self._spawn_fails()
        with self.assertRaises(HerdrError):
            self.b.delegate("t", role="worker", name="w9", me="orch")
        a = store.get_agent(self.db, "w9")
        self.assertEqual(a["state"], status.GONE_STATE)
        self.assertTrue(a["ended_at"])
        self.assertIsNone(a["pane_id"])          # a husk: no pane, no session
        self.assertIsNone(a["session_id"])
        self.assertIn("spawn_failed",
                      [e["kind"] for e in store.recent_events(self.db, agent="w9")])

    def test_the_name_of_a_failed_spawn_can_be_used_again(self):
        """The carve-out the husk needs. `claim_agent` is an `INSERT OR IGNORE` and
        cannot tell evidence from an owner, so without this a retry under the same name
        — every `sb start --name X`, every workspace lead — is refused forever."""
        self._spawn_fails()
        with self.assertRaises(HerdrError):
            self.b.delegate("t", role="worker", name="w9", me="orch")
        self.h = FakeHerdrAPI()
        self.assertEqual(self.restart_sb().delegate("t", role="worker", name="w9",
                                                    me="orch"), "w9")
        a = store.get_agent(self.db, "w9")
        self.assertEqual(a["state"], "working")
        self.assertEqual(a["session_id"], "sess-w9")

    def test_a_husk_never_takes_a_name_off_a_live_agent(self):
        """Only the husk shape is replaceable. A `failed` row that still holds a pane or
        a session is an agent `status` reaped — its pane may be open and `sb restore` can
        still bring it back — so the name stays taken."""
        store.create_agent(self.db, name="w9", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-w9")
        store.set_state(self.db, "w9", status.GONE_STATE)
        from switchboard.broker import AgentNameTaken
        with self.assertRaises(AgentNameTaken):
            self.b.delegate("t", role="worker", name="w9", me="orch")

    # -- messaging -------------------------------------------------------

    def test_tell_rings_the_doorbell_without_the_payload(self):
        store.create_agent(self.db, name="a", role="lead")
        store.create_agent(self.db, name="b", role="worker", parent="a")
        self.b.tell(["b"], "the actual secret payload", me="a")
        self.assertEqual(len(self.h.prompts), 1)
        self.assertNotIn("secret payload", self.h.prompts[0][1])  # payload stays in the store

    def test_the_flag_is_spelled_needs_reply_on_sb_tell(self):
        """The one thing an agent types. `sb tell w "..." --needs-reply` is the spelling
        DESIGN-TRUTH: "There is `tell` only. No agent ever waits" names, and it defaults
        off."""
        from switchboard.cli import build_parser
        self.assertTrue(
            build_parser().parse_args(["tell", "w", "hi", "--needs-reply"]).needs_reply)
        self.assertFalse(build_parser().parse_args(["tell", "w", "hi"]).needs_reply)

    def test_needs_reply_is_recorded_and_still_nobody_waits(self):
        """The flag is a claim on the RECIPIENT, and on nothing else.
        DESIGN-TRUTH: "No agent ever waits on another agent." So `--needs-reply` must leave
        the sender's path identical to a plain `tell`: one doorbell, no payload, no poll."""
        store.create_agent(self.db, name="a", role="lead")
        store.create_agent(self.db, name="b", role="worker", parent="a")
        (mid,) = self.b.tell(["b"], "what did you find?", me="a", needs_reply=True)
        self.assertEqual(store.get_message(self.db, mid)["needs_reply"], 1)
        self.assertEqual(len(self.h.prompts), 1)          # rung once, like any tell
        self.assertNotIn("what did you find?", self.h.prompts[0][1])

    def test_the_recipients_inbox_is_where_the_reply_prompt_actually_lands(self):
        """The doorbell carries no payload, so `sb inbox` is the only text this can reach
        an agent through — and a plain tell must not carry it, or the prompt means
        nothing."""
        import argparse, contextlib, io
        from switchboard import cli
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        self.b.tell(["kid"], "which branch?", me="orch", needs_reply=True)
        self.b.tell(["kid"], "fyi, no answer wanted", me="orch")
        args = argparse.Namespace(cmd="inbox", json=False, peek=False)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p1"}, clear=True), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(cli._dispatch(args, self.b, self.db, self.h), 0)
        out = buf.getvalue()
        self.assertIn("The sender, orch, is waiting for a reply", out)
        self.assertIn("sb tell orch", out)                # it says HOW to answer
        self.assertEqual(out.count("waiting for a reply"), 1)   # not the plain tell too

    def test_parent_resolves(self):
        store.create_agent(self.db, name="kid", role="worker", parent="mum")
        store.create_agent(self.db, name="mum", role="lead")
        self.b.tell(["parent"], "hi", me="kid")
        self.assertEqual(store.unread_for(self.db, "mum")[0]["body"], "hi")

    def test_done_notifies_the_parent_so_it_need_not_poll(self):
        store.create_agent(self.db, name="orch", role="lead")
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
        store.create_agent(self.db, name="root", role="lead", pane_id="w1:p1")
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
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.done("counted 144", me="kid")
        [m] = store.unread_for(self.db, "orch", mark=False)
        self.assertIn("[done] counted 144", m["body"])

    def test_a_finished_agent_can_still_be_reached_on_an_evicting_herdr(self):
        """The follow-up question, against a herdr that behaves the way the real one does.

        `done` used to report `idle`, and a `pane report-agent` costs the agent its name
        for good (`EvictingHerdr` charges that price; `Herdr.report_state` carries the
        measurement). So the ordinary next move after a report — asking the agent that
        still holds the whole context one more thing — was impossible, and the only move
        left was spawning a fresh agent and re-teaching it everything. Nothing is reported
        now, so the name survives the report and the doorbell still rings.
        """
        self.h = EvictingHerdr()
        self.b = Broker(self.db, self.h, repo=self.repo)
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}
        self.b.done("shipped the parser", me="w")

        self.assertEqual(self.h.states, [])                       # nothing was reported
        self.b.tell(["w"], "one more thing", me=HUMAN)
        self.assertEqual([n for n, _ in self.h.prompts], ["w"])   # the doorbell rang
        self.assertEqual(store.undelivered(self.db), [])          # and it landed
        self.assertIsNone(self.b.unreachable("w"))

    def test_a_root_agents_done_is_announced_because_nothing_else_will(self):
        """A root has no parent to poke and the human has no mailbox, so the notification
        is the delivery rather than a copy of one — and the end of the top of the tree is
        the end of the run. A child's done is not announced: its parent gets rung."""
        store.create_agent(self.db, name="root", role="lead", pane_id="w1:p1")
        store.create_agent(self.db, name="kid", role="worker", parent="root", pane_id="w1:p2")
        self.b.done("counted 144", me="kid")
        self.assertEqual(self.h.notifications, [])
        self.b.done("shipped the parser", me="root")
        self.assertEqual(len(self.h.notifications), 1)
        self.assertIn("shipped the parser", self.h.notifications[0])

    def test_a_repeat_done_is_recorded_and_neither_mails_nor_rings_the_parent_again(self):
        """One piece of work, one report. The wild case: a child called `sb done` twice
        and its parent got two notifications and two `[done]` messages, while the board
        showed only the SECOND — a content-free rewrite silently replacing the real
        summary. The repeat is kept in the log, under its own kind, and goes nowhere else.

        Both calls go through `whoami` the way production does, on a session with NO hooks
        — the shape that a guard reading `state` rather than the log gets wrong. There,
        `_revive` fails open and puts the row back to `working` before `done` ever runs, so
        a state-based guard sees a working agent and mails the parent a second time. That
        is not a hypothetical: it is how this test's first version passed while the bug it
        names was still live, because it passed `me=` and never resolved anybody.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        env = {"HERDR_PANE_ID": "w1:p1"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.restart_sb().done("counted 144, the parser is fine")
        self.h.prompts.clear()

        with mock.patch.dict(os.environ, env, clear=True):
            self.restart_sb().done("as I said")

        self.assertTrue(self.b.done_repeat)
        # the report stands: the row says done even though `_revive` revived it on the way
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "done")
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "orch")],
                         ["[done] counted 144, the parser is fine"])
        self.assertEqual(self.h.prompts, [])              # the parent is not rung twice
        kinds = [e["kind"] for e in store.recent_events(self.db, agent="kid")]
        self.assertEqual(kinds.count("done"), 1)
        self.assertIn("done_repeated", kinds)             # kept, not dropped
        # and the board still shows the first summary, which is the harm being fixed
        [kid] = [a for a in status.collect(self.db, self.h).agents if a.name == "kid"]
        self.assertEqual(kid.summary, "counted 144, the parser is fine")

    def test_a_genuine_second_done_after_a_real_turn_still_reaches_the_parent(self):
        """The other half of the guard, and the one it must not break: a follow-up task,
        done, is a second piece of work and gets its own report. The boundary is what says
        so — the `Stop` that ended the first report's turn, and the prompt that began the
        next.
        """
        from switchboard import hooks
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="sess-kid")
        p = {"session_id": "sess-kid"}
        hooks.mark_turn(p, self.db, store.TURN_WORKING)
        self.b.done("counted 144", me="kid")
        hooks.mark_turn(p, self.db, store.TURN_IDLE)         # its turn really ended
        hooks.mark_turn(p, self.db, store.TURN_WORKING)      # a follow-up arrived

        self.restart_sb().done("and the second thing is done too", me="kid")

        self.assertFalse(self.b.done_repeat)
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "orch")],
                         ["[done] counted 144",
                          "[done] and the second thing is done too"])

    def test_the_old_summary_replayed_on_the_first_turn_back_from_a_restore_is_held(self):
        """#148. Restore, hand over new work, and the resumed agent acts out the report
        its context ends with before it has read the mail. Every signal the repeat guard
        reads says this is new work — a turn ended, another began — so that guard passes
        it, and the parent holds a `[done]` that landed one second after it delegated.

        The full sequence is driven, `restore` included: it is the event the second guard
        turns on, and stubbing it would test the query rather than the path.
        """
        from switchboard import hooks
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="sess-kid", cwd=str(self.repo))
        p = {"session_id": "sess-kid"}
        hooks.mark_turn(p, self.db, store.TURN_WORKING)
        self.b.done("counted 144, the parser is fine", me="kid")
        hooks.mark_turn(p, self.db, store.TURN_IDLE)      # that turn really ended
        self.b.restore("kid")                             # closed, then brought back
        store.put_message(self.db, from_agent="orch", to_agent="kid", kind="tell",
                          body="now count the other one")
        self.h.prompts.clear()
        hooks.mark_turn(p, self.db, store.TURN_WORKING)   # the poke: its first turn back

        self.restart_sb().done("counted 144, the parser is fine", me="kid")

        self.assertTrue(self.b.done_replay)
        self.assertFalse(self.b.done_repeat)              # not the same agent saying it twice
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "orch")],
                         ["[done] counted 144, the parser is fine"])
        self.assertEqual(self.h.prompts, [])              # and the parent is not rung again
        kinds = [e["kind"] for e in store.recent_events(self.db, agent="kid")]
        self.assertEqual(kinds.count("done"), 1)
        self.assertIn("done_replayed", kinds)             # kept, not dropped
        # The row still says working, which a repeat's does not: this agent was handed new
        # work and has not done it, and a `done` on the board would be the same lie.
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "working")

    def test_a_restored_agents_report_on_the_new_work_reaches_its_parent(self):
        """The half the guard must not break, and the common one: the restored agent reads
        its mail, does the work, and reports it in its own words. Different words, so
        nothing here applies — one restore does not make an agent's next report suspect.
        """
        from switchboard import hooks
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="sess-kid", cwd=str(self.repo))
        p = {"session_id": "sess-kid"}
        hooks.mark_turn(p, self.db, store.TURN_WORKING)
        self.b.done("counted 144, the parser is fine", me="kid")
        hooks.mark_turn(p, self.db, store.TURN_IDLE)
        self.b.restore("kid")
        hooks.mark_turn(p, self.db, store.TURN_WORKING)

        self.restart_sb().done("counted the other one too: 89", me="kid")

        self.assertFalse(self.b.done_replay)
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "orch")],
                         ["[done] counted 144, the parser is fine",
                          "[done] counted the other one too: 89"])
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "done")

    def test_matching_words_after_a_full_turn_back_from_a_restore_still_reach_the_parent(self):
        """The third condition, and the one that keeps the guard to the single turn a
        replay can happen on. An agent that has already worked a whole turn since coming
        back is not acting out its old context any more — if it reports the same sentence
        then, it means it, and the report goes through.
        """
        from switchboard import hooks
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="sess-kid", cwd=str(self.repo))
        p = {"session_id": "sess-kid"}
        hooks.mark_turn(p, self.db, store.TURN_WORKING)
        self.b.done("counted 144, the parser is fine", me="kid")
        hooks.mark_turn(p, self.db, store.TURN_IDLE)
        self.b.restore("kid")
        hooks.mark_turn(p, self.db, store.TURN_WORKING)   # a whole turn back...
        hooks.mark_turn(p, self.db, store.TURN_IDLE)      # ...that ended
        hooks.mark_turn(p, self.db, store.TURN_WORKING)

        self.restart_sb().done("counted 144, the parser is fine", me="kid")

        self.assertFalse(self.b.done_replay)
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "orch")],
                         ["[done] counted 144, the parser is fine",
                          "[done] counted 144, the parser is fine"])

    def test_block_reports_no_state_to_herdr_at_all(self):
        """The one thing that makes a block answerable.

        ANY `pane report-agent` evicts the pane's named agent for good — `idle` as surely
        as `blocked` (`Herdr.report_state` records the measurement). Blocking used to push
        `idle` to stay "reachable"; it was the call, not the value, that made blocking a
        one-way door. So the assertion is that no state is pushed, not that a safe one is.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.block("need a decision", me="w")
        self.assertEqual(store.get_agent(self.db, "w")["state"], "blocked")  # our truth
        self.assertEqual(self.h.states, [])                                  # still named
        self.assertTrue(self.h.notifications)                                # you hear it

    def test_the_humans_answer_reaches_a_blocked_agent_on_an_evicting_herdr(self):
        """The whole point, against a herdr that behaves the way the real one does.

        `EvictingHerdr` models the one fact this fix turns on: a `pane report-agent` on a
        pane costs the agent its name, for good. Under it, the old code lost the block's
        answer twice over — `block` evicted the name on the way in, `_unblock_if_needed`
        evicted it again one line before the doorbell — and the observed result was the
        block clearing while the answer sat undelivered. Neither call is made now, so the
        round trip completes.
        """
        self.h = EvictingHerdr()
        self.b = Broker(self.db, self.h, repo=self.repo)
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}
        self.b.block("which branch?", me="w")

        self.b.tell(["w"], "use main", me=HUMAN)

        self.assertEqual([n for n, _ in self.h.prompts], ["w"])   # the doorbell rang
        self.assertEqual(store.undelivered(self.db), [])          # the answer arrived
        self.assertEqual(store.get_agent(self.db, "w")["state"], "working")
        self.assertIsNone(self.b.unreachable("w"))                # and it never went lost

    def test_block_goes_to_the_human_not_the_parent(self):
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.block("need a decision", me="kid")
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "blocked")
        self.assertTrue(self.h.notifications)
        self.assertEqual(store.unread_for(self.db, "orch"), [])   # parent context untouched

    def test_block_is_refused_while_a_descendant_is_already_waiting(self):
        """One question, one row — the rule the protocol states and nothing enforced.

        The observed failure (bug 2026-08-16-152345): a child blocked on a decision, its
        dispatcher relayed the same question and blocked on top of it, and the board carried
        two human-waiting rows for one decision. The refusal names the waiting agent and
        quotes its reason, because the caller's next move turns on whether that row is
        already its own question.
        """
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")

        with self.assertRaises(ValueError) as e:
            self.b.block("kid needs to know which branch", me="orch")

        self.assertIn("kid", str(e.exception))
        self.assertIn("which branch?", str(e.exception))
        self.assertIn("sb done", str(e.exception))
        self.assertEqual(store.get_agent(self.db, "orch")["state"], "working")  # not blocked
        refused = [r for r in store.recent_events(self.db, agent="orch")
                   if r["kind"] == "block_refused_descendant_waiting"]
        self.assertEqual(len(refused), 1)

    def test_the_refusal_lifts_once_the_childs_row_clears(self):
        """Not a permanent gate, which is why it needs no escape hatch.

        A parent with a genuinely different question is not locked out — it is made to wait
        its turn. The moment the person answers the child (which clears its block), the
        parent may reach them itself.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        self.b.tell(["kid"], "use main", me=HUMAN)               # the human answers the child

        self.b.block("and now a different question", me="orch")

        self.assertEqual(store.get_agent(self.db, "orch")["state"], "blocked")

    def test_a_dead_descendant_never_holds_the_gate_shut(self):
        """A child that died holding a block is nobody the person is waiting on.

        The dangerous direction here is the opposite of `live_descendants`': a gate held by
        a row nothing can clear would take away the parent's only way to reach a person, for
        good. A block that ended with its agent is not a question anybody is still holding.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        store.set_state(self.db, "kid", "failed")     # its session died under the block

        self.b.block("nobody below me is waiting now", me="orch")

        self.assertEqual(store.get_agent(self.db, "orch")["state"], "blocked")

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

    def _hooked(self, name, sid):
        """An agent whose session carries the two hooks, mid-turn. `hooks.mark_turn` is
        called rather than imitated: the edge this gate reads is the one that hook writes,
        and a hand-rolled copy would stop proving that."""
        from switchboard import hooks
        store.create_agent(self.db, name=name, role="worker", parent="orch",
                           pane_id="w1:p9", session_id=sid)
        hooks.mark_turn({"session_id": sid}, self.db, store.TURN_WORKING)
        return hooks

    def test_a_blocked_agent_does_not_unblock_itself_by_running_a_command(self):
        """The bug: `sb block "..."` and then any other `sb` command in the SAME turn.

        Every verb resolves its caller through `whoami`, so a blocked agent that ran `sb
        status` — or, in the wild, `sb plugin report-bug file` — flipped its own row back
        to `working` and erased the one signal that says a person is needed. Nobody was
        coming for it. `Stop` has not fired between the two commands, so no `turn_end`
        edge exists after the block, and that is what this now asks for.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        self._hooked("kid", "sess-kid")
        self.b.block("which branch?", me="kid")

        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "sess-kid"},
                             clear=True):
            self.assertEqual(self.restart_sb().whoami(), "kid")   # the read-only command

        self.assertEqual(store.get_agent(self.db, "kid")["state"], "blocked")
        self.assertEqual([e for e in store.recent_events(self.db, agent="kid")
                          if e["kind"] == "unblocked"], [])
        # and the question is still on the human's board, which is the point
        [needs] = [a for a in status.collect(self.db, self.h, needs_me=True).agents
                   if a.name == "kid"]
        self.assertEqual(needs.blocked_why, "which branch?")

    def test_a_human_answering_in_the_pane_still_clears_the_block_with_hooks_live(self):
        """The regression that matters most: the behaviour above must survive.

        A person typing into a stopped agent's pane is a real turn boundary — `Stop` fired
        on the blocked turn (`turn_end`), then `UserPromptSubmit` started a new one — and
        the agent's next command clears the block exactly as it always has.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        hooks = self._hooked("kid", "sess-kid")
        self.b.block("which branch?", me="kid")
        hooks.mark_turn({"session_id": "sess-kid"}, self.db, store.TURN_IDLE)   # Stop
        hooks.mark_turn({"session_id": "sess-kid"}, self.db, store.TURN_WORKING)  # typed

        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "sess-kid"},
                             clear=True):
            self.assertEqual(self.restart_sb().whoami(), "kid")

        self.assertEqual(store.get_agent(self.db, "kid")["state"], "working")
        [e] = [e for e in store.recent_events(self.db, agent="kid")
               if e["kind"] == "unblocked"]
        self.assertIn("answered_in_pane", e["payload"])

    def test_answering_in_the_pane_clears_the_block_and_releases_its_mail(self):
        """The way a person actually answers a question: they type into the pane.

        The message lands — that is herdr's pane, not ours — and the agent carries on, but
        nothing told the store, so the row sat in NEEDS YOU with the question already
        answered and its mail held behind a block nobody was still waiting on. The agent
        taking a turn again IS the answer having arrived: blocking ends a turn, so a
        blocked agent runs no commands until something restarts it.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p9")
        self.b.block("which branch?", me="kid")
        self.h.states_by_name = {"kid": "idle"}
        self.b.tell(["kid"], "unrelated news", me="orch")     # held: it is blocked
        self.assertEqual(self.h.prompts, [])
        self.assertEqual(len([a for a in status.collect(self.db, self.h, needs_me=True)
                              .agents if a.needs_human]), 1)

        # ...the human types the answer into the pane, and the agent runs its next command.
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p9"}, clear=True):
            self.assertEqual(self.b.whoami(), "kid")

        self.assertEqual(store.get_agent(self.db, "kid")["state"], "working")
        [e] = [e for e in store.recent_events(self.db, agent="kid") if e["kind"] == "unblocked"]
        self.assertIn("answered_in_pane", e["payload"])
        self.restart_sb()                                     # the next `sb` command
        self.assertEqual(self.b.flush_pending(), ["kid"])     # the held mail goes

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
        self.b.tell(["w"], "stop and do this instead", mode=INTERRUPT)
        [m] = self.db.execute(
            "SELECT * FROM messages WHERE to_agent='w'").fetchall()
        self.assertIn("stop and do this instead", m["body"])
        self.assertIsNotNone(m["read_at"])          # it already arrived, inline
        self.assertIsNotNone(m["delivered_at"])     # so nothing re-rings for it

    def test_every_line_sb_puts_in_a_pane_names_who_sent_it(self):
        """Item 3.3. The doorbell carries no payload, so before this an agent read "You
        have mail" with no way to tell whether its parent had redirected it or a sibling
        had said hello — nor whether sb or Andrew had typed it. One tag, three call sites:
        the doorbell, the inline interrupt body, and the child-done poke."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1")
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.b.tell(["kid"], "have a look at this", me="lead")
        self.assertIn("[sb: from lead]", self.h.prompts[-1][1])
        self.b.tell(["kid"], "stop, do this instead", me=HUMAN, mode=INTERRUPT)
        self.assertIn("[sb: from human]", self.h.prompts[-1][1])   # inline body
        self.b.done("shipped it", me="kid")
        self.assertIn("[sb: from kid]", self.h.prompts[-1][1])     # the parent's poke

    def test_the_inbox_spells_the_tag_the_same_way_the_doorbell_does(self):
        """They are one claim about one message and they used to disagree — `[3] from w1:`
        in the inbox, no sender at all in the pane. A reader cannot correlate two shapes."""
        import argparse
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="w", role="worker", parent="orch",
                           pane_id="w1:p1")
        self.b.tell(["w"], "the branch is ready", me="orch")
        doorbell = self.h.prompts[-1][1]
        args = argparse.Namespace(cmd="inbox", json=False, peek=False)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p1"}, clear=True), \
                contextlib.redirect_stdout(buf):
            from switchboard import cli
            self.assertEqual(cli._dispatch(args, self.b, self.db, self.h), 0)
        self.assertIn("[sb: from orch]", doorbell)
        self.assertIn("[sb: from orch]", buf.getvalue())

    def test_the_doorbell_is_held_back_while_the_target_is_mid_turn(self):
        """WHEN IDLE only. It is no longer what an unflagged `tell` does — the default
        rings a working agent and its own system queues the text — so this pins the mode
        that still waits, which is what `sb done` uses."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "not urgent", me=HUMAN, mode=WHEN_IDLE)
        self.assertEqual(self.h.prompts, [])                       # not rung
        self.assertEqual(len(store.undelivered(self.db)), 1)       # but not lost

    def test_the_default_mode_rings_a_busy_agent_and_cancels_nothing(self):
        """Item 3.1's pass line. `agent prompt` queues — the text lands at the target's
        next tool-call boundary and the call in flight finishes (measured live), so the
        default no longer waits out a whole
        turn to say "you have mail". No `esc`: that is what separates this from interrupt,
        and a test that only checked the prompt would pass on a stealth interrupt."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "when you get a moment", me=HUMAN)
        self.assertEqual([n for n, _ in self.h.prompts], ["w"])     # rung, mid-turn
        self.assertEqual(self.h.keys, [])                           # nothing cancelled
        self.assertEqual(store.undelivered(self.db), [])            # nothing left waiting

    def test_a_blocked_agent_holds_its_mail_in_every_mode_but_interrupt(self):
        """3.4, which modes must not regress: a blocked agent is not idle, it has STOPPED
        for a person, so "next turn" is the turn its block is answered on. Ringing it early
        would clear the block and bury the answer under mail it never asked for."""
        store.create_agent(self.db, name="lead", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p1")
        store.create_agent(self.db, name="sibling", role="worker", parent="lead")
        self.b.block("which branch?", me="kid")
        self.h.prompts.clear()
        for mode in (NEXT_TURN, WHEN_IDLE):
            self.b.tell(["kid"], "unrelated", me="sibling", mode=mode)
            self.assertEqual(self.h.prompts, [], mode)
            self.assertEqual(store.get_agent(self.db, "kid")["state"], "blocked", mode)
        self.b.tell(["kid"], "use main", me=HUMAN)          # the answer still lands
        self.assertEqual([n for n, _ in self.h.prompts], ["kid"])

    def test_hold_until_free_runs_on_our_own_signal_not_the_screen(self):
        """Hold-until-free, with herdr reading exactly as it does today: idle for a pane
        that is mid-tool-call. That reading alone delivered held mail into a running
        turn; `agents.turn` is the fact that stops it, and the
        ring is released by the turn's own end rather than by anything on screen."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}              # herdr's broken reading
        store.set_turn(self.db, "w", store.TURN_WORKING)   # what the hooks recorded
        self.b.tell(["w"], "not urgent", me=HUMAN, mode=WHEN_IDLE)
        self.assertEqual(self.h.prompts, [])
        self.assertEqual(len(store.undelivered(self.db)), 1)

        store.set_turn(self.db, "w", store.TURN_IDLE)      # its `Stop` hook fired
        self.assertEqual(self.b.flush_pending(), ["w"])
        self.assertEqual(store.undelivered(self.db), [])

    def test_reviving_a_hookless_agent_does_not_manufacture_a_turn_it_cannot_close(self):
        """The wedge that held this repo's own top orchestrator's mail for a day.

        An agent whose session predates the activity signal has neither hook, so nothing
        can ever write its turn-END edge. `_revive` used to stamp `working` on it anyway
        for running an `sb` command — true about the moment, unclosable forever after —
        and `_busy` then deferred every `--when-idle` message to it for good. The column
        must stay NULL for that row: no signal, ask herdr, exactly as before the signal
        existed.
        """
        store.create_agent(self.db, name="top", role="lead", pane_id="w1:p1")
        store.set_state(self.db, "top", "done")
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p1"}, clear=True):
            self.assertEqual(self.b.whoami(), "top")       # it ran an `sb` command
        a = store.get_agent(self.db, "top")
        self.assertEqual(a["state"], "working")            # revived, as before
        self.assertIsNone(a["turn"])                       # but no edge invented

        self.h.states_by_name = {"top": "idle"}
        self.restart_sb()
        self.b.tell(["top"], "your child reported", me=HUMAN, mode=WHEN_IDLE)
        self.assertEqual([n for n, _ in self.h.prompts], ["top"])
        self.assertEqual(store.undelivered(self.db), [])

    def test_pending_mail_is_rung_once_the_target_goes_idle(self):
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "later", me=HUMAN, mode=WHEN_IDLE)
        self.h.states_by_name = {"w": "idle"}
        self.b._alive_cache = None
        self.assertEqual(self.b.flush_pending(), ["w"])
        self.assertEqual(store.undelivered(self.db), [])

    def test_a_parent_that_was_mid_turn_is_woken_by_the_next_flush(self):
        """The report that goes missing: a parent in a long turn when its last child
        finishes. `done` rings it, the ring is held back because it is working, and until
        the collector ran this on a timer the only thing that re-rang it was the next `sb`
        command a person happened to type (`2026-08-09-035933`).
        """
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1")
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.h.states_by_name = {"lead": "working", "kid": "working"}
        self.b.done("shipped it", me="kid")
        self.assertEqual(self.h.prompts, [])                       # held: mid-turn

        self.h.states_by_name = {"lead": "idle"}                   # the turn ends
        self.b._alive_cache = None
        self.assertEqual(self.b.flush_pending(), ["lead"])
        self.assertEqual([n for n, _ in self.h.prompts], ["lead"])
        self.assertEqual([m["body"] for m in self.b.inbox(me="lead")],
                         ["[done] shipped it"])

    def _fanout(self, kids=("k1", "k2", "k3")):
        """An idle lead with `kids` children all still working."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1")
        for i, k in enumerate(kids):
            store.create_agent(self.db, name=k, role="worker", parent="lead",
                               pane_id=f"w1:p{i + 2}")
        self.h.states_by_name = {"lead": "idle", **{k: "working" for k in kids}}
        self.b._alive_cache = None
        return list(kids)

    @staticmethod
    def _later(seconds):
        """The clock the store stamps and reads with, moved on. Nothing else is faked:
        the holdback is decided by `store.now()` against rows the real code wrote."""
        return mock.patch.object(store, "now", lambda: int(time.time()) + seconds)

    def test_a_burst_of_sibling_dones_rings_the_parent_once(self):
        """#168. Three children finishing inside a second rang an idle parent three
        times, and the doorbell carries no payload — so it was the same sentence three
        times over, and the parent burned a turn on each.

        The ring is held on the IDLE path and owed to `flush_pending`, which was already
        the one place that rings once for a whole backlog and names every sender in it.
        No timer and no process: the drain at the top of every `sb` command fires it.
        """
        kids = self._fanout()
        for k in kids:
            self.b.done(f"{k} shipped", me=k)
        self.assertEqual(self.h.prompts, [])            # not one ring during the burst
        self.assertEqual(self.b.flush_pending(), [])    # nor from the drain, mid-burst

        with self._later(broker_mod.RING_HOLDBACK + 1):  # the burst goes quiet
            self.assertEqual(self.b.flush_pending(), ["lead"])
        [(who, text)] = self.h.prompts
        self.assertEqual(who, "lead")
        for k in kids:                                   # ONE doorbell, naming all three
            self.assertIn(k, text)
        # And nothing was collapsed to make it: every summary is in the mailbox, whole.
        self.assertEqual([m["body"] for m in self.b.inbox(me="lead")],
                         [f"[done] {k} shipped" for k in kids])

    def test_the_holdback_never_touches_a_block_or_an_interrupt(self):
        """The two absolute carve-outs, checked while a holdback is open on the target.

        Neither is exempted by name: `block` writes no message row and reaches a person
        through `_surface`, and an interrupt is `mode=INTERRUPT`, which never reaches the
        when-idle branch the holdback lives on.
        """
        kids = self._fanout(("k1", "k2"))
        self.b.done("k1 shipped", me=kids[0])
        self.assertEqual(self.h.prompts, [])                       # a hold is open on lead
        self.assertTrue(self.b._holdback_open("lead"))

        self.b.tell(["lead"], "stop, do this instead", me=HUMAN, mode=INTERRUPT)
        self.assertEqual([n for n, _ in self.h.prompts], ["lead"])  # straight through

        self.b.done("k2 shipped", me=kids[1])                      # hold still open
        self.b.block("which branch?", me="lead")
        self.assertTrue(any("which branch?" in n for n in self.h.notifications))
        self.assertEqual(store.get_agent(self.db, "lead")["state"], "blocked")

    def test_one_child_reporting_to_an_idle_parent_still_rings_at_once(self):
        """No regression for the common shape. A parent with no other live child cannot
        have a burst, so there is nothing to coalesce with and nothing is held — the
        doorbell rings from `done` itself, exactly as before #168."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1")
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.h.states_by_name = {"lead": "idle", "kid": "working"}
        self.b.done("shipped it", me="kid")
        self.assertEqual([n for n, _ in self.h.prompts], ["lead"])
        self.assertFalse(self.b._holdback_open("lead"))
        self.assertEqual(store.undelivered(self.db), [])

    def test_a_dead_childs_ping_waits_for_a_busy_parent_and_for_a_blocked_one(self):
        """A failure travels the same rails as a `done`, so it inherits both holds without
        a line of its own: `status._record_gone` writes the message, `flush_pending` rings
        it, and `_ring`'s when-idle guards decide when. Mid-turn is held; BLOCKED is held
        too, because a blocked parent has stopped waiting on a person and a ring would
        cancel that and bury the answer underneath it.
        """
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1",
                           session_id="s1")
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p2", session_id="s2", task="rewrite the parser")
        self.h.states_by_name = {"lead": "working"}                # kid's pane is gone
        later = store.now() + int(status.GONE_CONFIRM_GRACE) + 1
        status.collect(self.db, self.h)
        status.collect(self.db, self.h, now=later)                 # the death is recorded
        self.assertEqual(store.get_agent(self.db, "kid")["state"], status.GONE_STATE)

        self.b._alive_cache = None
        self.assertEqual(self.b.flush_pending(), [])               # held: lead is mid-turn
        self.assertEqual(self.h.prompts, [])

        self.b.block("which branch?", me="lead")                   # it stops to ask a person
        self.h.states_by_name = {"lead": "idle"}                   # its turn HAS ended
        self.b._alive_cache = None
        self.assertEqual(self.b.flush_pending(), [])               # still held: not idle
        self.assertEqual(store.get_agent(self.db, "lead")["state"], "blocked")

        self.b.tell(["lead"], "use main", me=HUMAN)                # the answer arrives
        self.assertEqual([n for n, _ in self.h.prompts], ["lead"])
        bodies = [m["body"] for m in self.b.inbox(me="lead")]
        self.assertIn("rewrite the parser", bodies[0])
        self.assertTrue(bodies[0].startswith("[failed] kid "), bodies[0])

    def test_the_doorbell_does_not_ring_for_mail_the_agent_already_read(self):
        """A ring says "you have mail" — to an agent that has already got it, that is a
        whole turn spent discovering an empty inbox (C0).

        The agent is mid-turn, so the ring is held back; it runs `sb inbox` of its own
        accord and reads the message anyway. Those rows stay un-announced for good, and
        ringing on un-announced alone would chase them every `sb` command from now on.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "review the PR", me=HUMAN, mode=WHEN_IDLE)
        self.assertEqual(self.h.prompts, [])                       # held back, mid-turn
        self.assertEqual([m["body"] for m in self.b.inbox(me="w")], ["review the PR"])
        self.h.states_by_name = {"w": "idle"}
        self.b._alive_cache = None
        self.assertEqual(self.b.flush_pending(), [])               # nothing to announce
        self.assertEqual(self.h.prompts, [])
        self.assertEqual(len(store.undelivered(self.db)), 1)       # still never announced
        self.assertEqual(store.unseen(self.db), [])                # but the agent knows

    def test_a_stale_doorbell_does_not_cancel_a_block(self):
        """The block is the whole point: `_ring` unblocks before it prompts.

        An agent reads its mail proactively, then stops to ask a person. If the flush
        still rang for that already-read mail, the agent would be put back to `working`,
        drop off `sb status --needs-me`, and the question would reach nobody — cancelled
        by a doorbell carrying no news at all.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "review the PR", me=HUMAN, mode=WHEN_IDLE)
        self.b.inbox(me="w")                                       # read it, unrung
        self.b.block("which branch?", me="w")
        self.h.prompts.clear()
        self.h.states_by_name = {"w": "idle"}                      # the block leaves it idle
        self.b._alive_cache = None

        rung = self.b.flush_pending()
        # The harm first, so a regression reports what was actually lost rather than a
        # list that differs. Both of these were the observed symptom: the agent went back
        # to `working` and vanished from the one readout that would have shown a person
        # the question.
        self.assertEqual(store.get_agent(self.db, "w")["state"], "blocked")
        self.assertEqual([a.name for a in
                          status.collect(self.db, self.h, needs_me=True).agents], ["w"])
        [needs] = status.collect(self.db, self.h, needs_me=True).agents
        self.assertEqual(needs.blocked_why, "which branch?")
        self.assertEqual((rung, self.h.prompts), ([], []))

    def test_flush_costs_nothing_when_there_is_no_pending_mail(self):
        self.assertEqual(self.b.flush_pending(), [])
        self.assertIsNone(self.b._alive_cache)                     # herdr never consulted

    def test_an_interrupt_always_lands_now(self):
        """Deferring an interrupt would defeat its entire purpose."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "stop", mode=INTERRUPT)
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

    def test_a_lost_name_binding_is_recorded_as_its_own_failure(self):
        """herdr answering `agent_not_found` for an agent it is STILL listing as alive is
        the signature of a lost name binding (`2026-08-09-004626`) — not a dead agent.

        Nothing can fix it from here: the binding lives in herdr. What matters is that it
        stops being indistinguishable from an ordinary hiccup, because the mail queued
        behind it will never be announced by anything.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}        # herdr still lists it, and idle
        self.h.unreachable.add("w")                  # ...but will not answer to the name

        self.b.tell(["w"], "you have mail", me=HUMAN)

        [ev] = [r for r in store.recent_events(self.db, agent="w")
                if r["kind"] == "ring_failed"]
        self.assertIn("name_binding_lost", ev["payload"])
        self.assertIn("agent_not_found", self.b.unreachable("w"))
        self.assertEqual([m["to_agent"] for m in store.undelivered(self.db)], ["w"])

    def test_an_agent_herdr_has_dropped_is_not_called_a_lost_binding(self):
        """It is the pair that means something: refused BY NAME while still listed. An
        agent herdr no longer lists is simply gone, and saying "go look at its pane" about
        a pane that closed under it would send a person to an empty screen."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {}                   # herdr has dropped it entirely
        self.h.unreachable.add("w")

        self.b.tell(["w"], "you have mail", me=HUMAN)

        [ev] = [r for r in store.recent_events(self.db, agent="w")
                if r["kind"] == "ring_failed"]
        self.assertNotIn("name_binding_lost", ev["payload"])
        self.assertIsNone(self.b.unreachable("w"))

    def test_a_ring_that_lands_later_clears_the_unreachable_reading(self):
        """It is an observation, not a state: the next ring that works disproves it."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}
        self.h.unreachable.add("w")
        self.b.tell(["w"], "first", me=HUMAN)
        self.assertIsNotNone(self.b.unreachable("w"))

        self.h.unreachable.discard("w")              # herdr found the name again
        self.b.tell(["w"], "second", me=HUMAN)
        self.assertIsNone(self.b.unreachable("w"))

    def test_a_deferred_doorbell_is_not_an_unreachable_agent(self):
        """Mid-turn is the ordinary case and it rings itself out; promising delivery there
        is honest, which is exactly what makes the unreachable warning worth reading."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "later", me=HUMAN)
        self.assertIsNone(self.b.unreachable("w"))

    def test_an_undeliverable_interrupt_fails_loudly_instead_of_being_marked_read(self):
        """`mark_collected` used to fire before delivery was attempted, so an interrupt
        that never arrived was recorded as one the agent had already read."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.h.unreachable.add("w")
        with self.assertRaises(Undeliverable) as cm:
            self.b.tell(["w"], "stop what you are doing", mode=INTERRUPT)
        self.assertEqual(cm.exception.who, "w")
        self.assertIn("agent_not_found", cm.exception.message)   # what herdr actually said
        self.assertIn("sb inbox", cm.exception.message)          # and what to do about it
        self.assertEqual(self.h.pane_prompts, [])                # no shell fallback
        [m] = store.undelivered(self.db)                         # queued, not read
        self.assertIsNone(m["read_at"])

    def test_an_interrupt_is_delivered_confirmed_and_a_doorbell_is_not(self):
        """The interrupt is the one ring whose TEXT is the message, so it is the one ring
        a bare `agent prompt` cannot be trusted with: a first-run dialog eats the text and
        moves the agent's state anyway, and the send reports success over a wedged agent.
        Every other mode carries no payload and is re-rung from the store, so it stays a
        plain prompt — this asserts the split, not just the interrupt half."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1",
                           cwd=str(self.repo))
        self.b.tell(["w"], "you have mail", me=HUMAN)
        self.assertEqual(self.h.proofs, [])                # doorbell: fire and forget
        self.b.tell(["w"], "stop and do this instead", me=HUMAN, mode=INTERRUPT)
        self.assertEqual([n for n, _ in self.h.proofs], ["w"])
        self.assertIn("stop and do this instead", self.h.prompts[-1][1])

    def test_the_interrupts_proof_is_the_targets_own_transcript(self):
        """Which agent's record answers "did it land" is the one thing only the broker
        can get right, so the proof is run here rather than assumed: it must say no to a
        pane that swallowed the text and yes once the words are in that agent's own
        transcript. Anything read off herdr's terminal state would say yes to both."""
        home = Path(self.tmp.name) / "home"
        cwd = str(self.repo / "ws")
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1", cwd=cwd)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.b.tell(["w"], "stop and do this instead", me=HUMAN, mode=INTERRUPT)
            [(_, proof)] = self.h.proofs
            since = time.time() - 1
            self.assertFalse(proof(since))             # nothing in its record yet
            body = self.h.prompts[-1][1]
            d = home / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", cwd)
            d.mkdir(parents=True, exist_ok=True)
            (d / "sess.jsonl").write_text(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": body},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }) + "\n")
            self.assertTrue(proof(since))              # the agent itself now holds it

    def test_an_interrupt_no_send_could_confirm_stays_queued_and_unread(self):
        """The failure this fix is for: herdr's `agent prompt` returned fine and the agent
        never got the text. Now that the send must be PROVED, that is an undeliverable
        interrupt — loud, and left in the inbox for the agent to find — rather than a
        message recorded as read by an agent that never saw it."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1",
                           cwd=str(self.repo))
        self.h.undeliverable.add("w")          # prompt "works", nothing ever confirms it
        with self.assertRaises(Undeliverable) as cm:
            self.b.tell(["w"], "stop and do this instead", me=HUMAN, mode=INTERRUPT)
        self.assertEqual(cm.exception.who, "w")
        self.assertIn("not_delivered", cm.exception.message)
        self.assertEqual(self.h.prompts, [])                     # never sent, unconfirmed
        [m] = store.undelivered(self.db)
        self.assertIsNone(m["read_at"])
        self.assertIn("stop and do this instead", m["body"])

    # -- the doorbell whose Enter was dropped (7.x) ------------------------

    def _target(self) -> None:
        """An ordinary live agent with a transcript on disk, under a fake HOME."""
        self.home = Path(self.tmp.name) / "home"
        self.cwd = str(self.repo / "ws")
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1",
                           cwd=self.cwd, session_id="sess-w")
        self.bucket = (self.home / ".claude" / "projects"
                       / re.sub(r"[^a-zA-Z0-9]", "-", self.cwd))
        self.bucket.mkdir(parents=True)
        (self.bucket / "sess-w.jsonl").write_text("")

    def _age_rings(self, seconds: int = 60) -> None:
        """Put the ring bookkeeping into the past.

        Backdated rather than slept through. Nothing is judged inside `RING_SETTLE` — not
        the send, and not a repair either — so a test that did not age these would only
        ever see the confirmer decline to look.
        """
        self.db.execute("UPDATE events SET created_at=created_at-? WHERE kind LIKE 'ring%'",
                        (seconds,))
        self.db.commit()

    def _ring_and_age(self) -> str:
        """Ring w's doorbell, age it, and return the text that went out."""
        self.b.tell(["w"], "have a look at this", me=HUMAN)
        self._age_rings()
        return self.h.prompts[-1][1]

    def _confirm(self) -> list[str]:
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.b.flush_pending()
        return [r["kind"] for r in store.recent_events(self.db, agent="w")]

    def test_a_doorbell_the_busy_target_queued_is_confirmed_not_sent_again(self):
        """The false positive matters as much as the true one. A busy Claude Code records
        a prompt it takes as a `queue-operation`/`enqueue` and writes nothing user-side
        until the turn ends — 3 min 09 s later, measured — so a confirmer that cannot read
        that record re-sends every correct delivery to every working agent in the fleet."""
        self._target()
        text = self._ring_and_age()
        (self.bucket / "sess-w.jsonl").write_text(json.dumps({
            "type": "queue-operation", "operation": "enqueue", "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }) + "\n")
        self.assertIn("ring_confirmed", self._confirm())
        self.assertEqual(len(self.h.prompts), 1)          # rung once, and left alone

    def test_a_doorbell_nothing_recorded_is_re_sent_and_then_given_up_on(self):
        """The bug: `agent prompt` pasted the text and the Enter was dropped, so `sb tell`
        reported success over a message that will never be seen. The agent's own transcript
        says nothing, so the doorbell is SENT AGAIN — never Enter pressed on a box nobody
        has read, which could submit a human's half-typed line or answer a modal — and the
        repairs are capped, so an agent that cannot be reached at all is logged rather than
        rung for ever."""
        self._target()
        text = self._ring_and_age()
        self._confirm()
        self.assertEqual(len(self.h.prompts), 2)      # nothing recorded it: sent again
        self._confirm()
        self.assertEqual(len(self.h.prompts), 2)      # and the repair gets its own window

        # Measured live before that window existed: every `sb` command any agent runs comes
        # through `flush_pending`, so the second repair went out inside the same second as
        # the first, before the first could possibly have been taken.
        for _ in range(3):
            self._age_rings()
            kinds = self._confirm()
        self.assertEqual([t for _, t in self.h.prompts], [text, text, text])
        self.assertEqual(kinds.count("ring_repaired"), 2)
        self.assertIn("ring_unconfirmed", kinds)
        [m] = store.unread_for(self.db, "w", mark=False)   # still there to be read
        self.assertIn("have a look at this", m["body"])

    def test_the_repair_cap_holds_against_a_stale_read(self):
        """What `RING_REPAIRS` counts is the claim, not the count that decided to try.

        `flush_pending` runs at the head of every `sb` command, so several processes reach
        `_confirm_rings` for the same stalled ring inside one race window — reproduced with
        four, all reading `tries=0`, all believing they were repair number one, all sending.
        Handing `_claim_repair` that same stale ring over and over is that race made
        deterministic: the third call must find no slot left, whatever the read said.
        """
        self._target()
        self._ring_and_age()
        ring = self.b._last_ring("w")
        self.assertEqual(ring["tries"], 0)
        seen = [self.b._claim_repair("w", ring, store.now()) for _ in range(3)]
        self.assertEqual(seen, [1, 2, None])

    # -- applying a preset to your own session (6.4) -----------------------

    def _preset(self, name: str, text: str) -> None:
        d = self.repo / ".switchboard" / "presets"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.md").write_text(text)

    def test_applying_a_preset_pastes_it_into_the_callers_own_session(self):
        """"sb pastes it in, the same path as any other message" — so the text is on the
        wire, not merely printed by the command the agent ran."""
        self._preset("ritual", "# ritual\nCount to three before answering.")
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        self.b.apply_preset("ritual", me="w")
        [(who, text)] = self.h.prompts
        self.assertEqual(who, "w")
        self.assertIn("Count to three", text)
        self.assertIn("[sb: from w]", text)      # tagged, like every other sb line
        self.assertNotIn("\n", text)             # herdr refuses a multi-line argument

    def test_the_applied_preset_is_a_message_the_agent_sent_to_itself(self):
        """The one shape no other verb produces. It has to be durable — `sb inspect` shows
        what an agent was told, and a procedure it adopted mid-run belongs in that record."""
        self._preset("ritual", "Count to three.")
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        mid = self.b.apply_preset("ritual", me="w")
        m = store.get_message(self.db, mid)
        self.assertEqual((m["from_agent"], m["to_agent"]), ("w", "w"))
        self.assertIsNotNone(m["delivered_at"])
        # ...and NOT waiting in its own inbox: it travelled inline, so a second copy would
        # be the agent reading the same procedure twice and `cleanup` calling it unread mail.
        self.assertEqual(store.unread_for(self.db, "w", mark=False), [])

    def test_a_preset_that_does_not_exist_is_refused_before_anything_is_sent(self):
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        with self.assertRaises(KeyError):
            self.b.apply_preset("no-such-thing", me="w")
        self.assertEqual(self.h.prompts, [])

    def test_a_human_has_no_session_to_apply_a_preset_to(self):
        self._preset("ritual", "Count to three.")
        with self.assertRaises(ValueError) as cm:
            self.b.apply_preset("ritual", me=HUMAN)
        self.assertIn("sb presets ritual", str(cm.exception))   # what to type instead

    # -- mail to an agent that has finished -------------------------------

    def test_no_doorbell_is_rung_for_an_agent_that_has_finished(self):
        """A real agent stops answering to its name the moment its turn ends, so the ring
        can only fail — and `flush_pending` re-attempted it on every `sb` command anyone
        ran, forever. The message is still written: this skips the announcement, not the
        mail."""
        store.create_agent(self.db, name="w", role="worker", parent="orch", pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        self.b.tell(["w"], "one more thing", me=HUMAN)
        self.assertEqual(self.h.prompts, [])
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "w", mark=False)],
                         ["one more thing"])
        self.assertIn("ring_skipped",
                      [e["kind"] for e in store.recent_events(self.db, agent="w")])

    def test_a_finished_agent_that_herdr_still_knows_is_rung_normally(self):
        """The guard needs a positive answer, not a missing one. A done agent whose pane
        is still there can still be given a turn — and a done PARENT collecting its
        children's summaries is exactly that shape."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        self.h.states_by_name = {"w": "idle"}
        self.b.tell(["w"], "one more thing", me=HUMAN)
        self.assertEqual([n for n, _ in self.h.prompts], ["w"])

    def test_a_herdr_that_cannot_be_asked_never_silences_the_doorbell(self):
        """Unknown is not gone. Reading an outage as death would hold back the doorbell
        for a whole live fleet."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        self.h.list_error = HerdrError("connection_refused", "herdr is down")
        self.b.tell(["w"], "one more thing", me=HUMAN)
        self.assertEqual([n for n, _ in self.h.prompts], ["w"])

    def test_the_flush_stops_chasing_mail_for_an_agent_that_is_gone(self):
        """The backlog half. The guard stops NEW rings; messages already on disk for an
        agent whose pane has gone would otherwise stay in `unseen` forever, re-derived by
        every flush and reported as outstanding by every readout."""
        store.create_agent(self.db, name="w", role="worker")      # closed: no pane
        store.set_state(self.db, "w", "done")
        store.put_message(self.db, from_agent=HUMAN, to_agent="w", kind="tell", body="hi")
        self.assertEqual(self.b.flush_pending(), [])
        self.assertEqual(store.unseen(self.db), [])
        self.assertEqual(self.h.prompts, [])
        # Cleared, not discarded — the body is still there to be read in the log.
        [e] = [e for e in store.recent_events(self.db, agent="w") if e["kind"] == "mail_cleared"]
        self.assertIn("hi", e["payload"])

    def test_the_flush_keeps_mail_for_a_finished_agent_whose_pane_is_still_there(self):
        """A person can put a turn back into that pane, so its inbox is not written off —
        it only loses the doorbell.

        herdr has to SAY the pane is still there, and that is why `states_by_name` is set
        here: the `pane_id` on a finished row outlives the pane itself, so the column alone
        was never evidence of an inbox anybody could open (see `_clear_unreadable_mail`).
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        self.h.states_by_name = {"w": "idle"}
        self.h.evicted.add("w")               # listed, but no longer rung by name
        self.h.unreachable.add("w")
        store.put_message(self.db, from_agent=HUMAN, to_agent="w", kind="tell", body="hi")
        self.assertEqual(self.b.flush_pending(), [])
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "w", mark=False)], ["hi"])
        # Un-announceable, not written off: it is still owed to a mailbox that exists.
        [m] = self.db.execute("SELECT * FROM messages").fetchall()
        self.assertIsNone(m["undeliverable_at"])

    def test_mail_to_an_agent_whose_pane_died_stops_asking_the_human_for_anything(self):
        """The queue that is always full is the same as no queue (`2026-08-09-233230`).

        The row keeps its `pane_id` when an agent dies — only `cleanup` clears it — so the
        old rule read "there is still a mailbox someone could open" off a pane that no
        longer existed, stamped the mail un-announceable and left it unread forever. Unread
        is what `needs_human` counts, so the dead agent stayed on the human's list with
        nothing in the fleet able to move it.
        """
        # A session id, so its absence from herdr is a death rather than a spawn still in
        # flight (`status.collect`'s SPAWN_GRACE).
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1",
                           session_id="sess-w")
        store.put_message(self.db, from_agent="orch", to_agent="w", kind="tell",
                          body="please review the auth change")
        self.h.states_by_name = {}                  # its pane went with it
        reap_gone(self.db, self.h)
        self.assertEqual(store.get_agent(self.db, "w")["state"], "failed")

        self.restart_sb()
        self.assertEqual(self.b.flush_pending(), [])
        self.assertEqual(status.collect(self.db, self.h, needs_me=True).agents, [])

        # Nothing is discarded, and nothing is pretended to have been read: the message is
        # still in that agent's inbox, body and all, for `sb inspect` and for a restore.
        [m] = store.unread_for(self.db, "w", mark=False)
        self.assertEqual(m["body"], "please review the auth change")
        self.assertIsNotNone(m["undeliverable_at"])

    def test_closing_an_agent_clears_the_backlog_the_open_pane_left_behind(self):
        """The half no sweep could reach.

        Mail held gently while the pane was open is stamped `delivered_at`, which takes it
        out of `unseen()` — the only work list `flush_pending` has. So once the pane went,
        nothing looked at those rows again: unread forever, the agent in NEEDS YOU forever,
        and `sb cleanup` itself the one event that could have known.
        """
        self._evicted()                                   # done, pane open, name evicted
        self.b.tell(["w"], "are you there?", me=HUMAN)
        self.assertIsNone(self.db.execute(
            "SELECT undeliverable_at u FROM messages").fetchone()["u"])
        self.assertEqual(status.collect(self.db, self.h, needs_me=True).agents[0].name, "w")

        self.restart_sb()
        self.assertEqual(list(self.b.cleanup(["w"], me=HUMAN)), ["w"])
        self.assertEqual(status.collect(self.db, self.h, needs_me=True).agents, [])
        [m] = store.unread_for(self.db, "w", mark=False)   # still there, still unread
        self.assertIsNotNone(m["undeliverable_at"])

    # -- the endless ring loop: a done agent herdr still LISTS but no longer answers to --

    def _evicted(self, name="w"):
        """The ordinary state of a done agent: pane open, turn ended, name binding gone.

        herdr lists the pane as `{"agent": "<name>"}` with no `name` field, which is how it
        stays visible to `agent list` while `agent get` answers agent_not_found.
        """
        store.create_agent(self.db, name=name, role="worker", pane_id="w1:p1")
        store.set_state(self.db, name, "done")
        self.h.states_by_name = {name: "idle"}
        self.h.evicted.add(name)
        self.h.unreachable.add(name)          # and the ring would fail if it were tried

    def test_a_listed_pane_is_not_a_name_herdr_answers_to(self):
        """The defect itself, in one assertion. `Agent.from_json` fills a missing `name`
        from `agent`, so the evicted row still yields the agent's own name — and the guard
        that asked `agent list` for membership read that fallback as proof of the very
        binding it exists to detect the loss of."""
        self._evicted()
        self.assertIn("w", self.b._agent_states())        # still listed...
        self.assertFalse(self.b._name_bound("w"))         # ...and still unreachable
        self.assertTrue(self.b._finished_and_unreachable("w"))

    def test_mail_to_a_done_agent_is_not_retried_every_ten_seconds(self):
        """Measured at 21 failed rings in 71 seconds and rising, one doorbell tick each,
        for a message that can never land. It stops
        being un-announced, so neither `flush_pending` nor the collector's doorbell — both
        of which chase exactly `unseen` — has anything left to chase."""
        self._evicted()
        self.b.tell(["w"], "are you there?", me=HUMAN)
        self.assertEqual(self.h.prompts, [])
        self.assertEqual(store.unseen(self.db), [])

        for _ in range(3):                                 # three more `sb` commands
            self.restart_sb()
            self.assertEqual(self.b.flush_pending(), [])
        self.assertEqual(self.h.prompts, [])
        self.assertEqual([e["kind"] for e in store.recent_events(self.db, agent="w")
                          if e["kind"] == "ring_failed"], [])

    def test_but_the_message_is_still_there_to_be_read(self):
        """The pane is open, so a person can put a turn back into it and that agent's own
        `sb inbox` finds the mail waiting. Only the announcement is written off."""
        self._evicted()
        self.b.tell(["w"], "are you there?", me=HUMAN)
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "w", mark=False)],
                         ["are you there?"])
        [e] = [e for e in store.recent_events(self.db, agent="w")
               if e["kind"] == "mail_unannounced"]
        self.assertIn("are you there?", e["payload"])

    def test_that_mail_no_longer_pins_the_row_open(self):
        """`cleanup` refused the row with "unread mail it could still read" on every sweep
        — for mail nobody could ever read — and it took `--force` to close it."""
        self._evicted()
        self.b.tell(["w"], "are you there?", me=HUMAN)
        self.restart_sb()
        r = self.b.cleanup(me=HUMAN)
        self.assertEqual(list(r), ["w"])
        self.assertEqual(r.refused, [])
        self.assertIn("w1:p1", self.h.closed)

    def test_the_sender_is_told_it_will_never_be_announced(self):
        """"will be rung when free" is the promise this replaces: the agent is neither
        mid-turn nor coming back, and nothing will ever ring it."""
        self._evicted()
        self.b.tell(["w"], "are you there?", me=HUMAN)
        self.assertIn("no longer answers to its name", self.b.unreachable("w"))

    def test_and_sb_tell_says_so_on_the_spot(self):
        """The note is read off every target and not off the un-announced ones, because
        these rows are stamped as they are written — so reading it the old way printed the
        same bare "sent to w" a real delivery gets."""
        import argparse, contextlib, io
        from switchboard import cli
        self._evicted()
        args = argparse.Namespace(cmd="tell", who=["w"], message="are you there?",
                                  reply_to=None, needs_reply=False, json=False,
                                  mode=NEXT_TURN)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(cli._dispatch(args, self.b, self.db, self.h), 0)
        self.assertIn("UNREACHABLE", buf.getvalue())
        self.assertNotIn("will be rung when free", buf.getvalue())

    def test_a_done_agent_whose_name_still_binds_keeps_its_mail_and_its_doorbell(self):
        """The other side of the same fact, and the reason this is a name question and not
        a state one: `done` does not always cost the binding, and a done parent still
        collecting its children's summaries must stay reachable."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        self.h.states_by_name = {"w": "idle"}              # bound, not evicted
        self.b.tell(["w"], "one more thing", me=HUMAN)
        self.assertEqual([n for n, _ in self.h.prompts], ["w"])
        self.assertIsNone(self.b.unreachable("w"))

    def test_interrupting_an_agent_that_has_finished_is_refused_plainly(self):
        """There is no turn to change course. Saying so beats dressing it up as a herdr
        failure, and nothing is written — a refused interrupt leaves no half-sent row."""
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "done")
        with self.assertRaises(ValueError) as cm:
            self.b.tell(["w"], "stop what you are doing", mode=INTERRUPT)
        self.assertIn("already finished", str(cm.exception))
        self.assertEqual(self.h.keys, [])                         # no `esc` either
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM messages WHERE to_agent='w'").fetchone()[0], 0)

    def test_messaging_a_blocked_agent_unblocks_it_first(self):
        """Answering a blocked agent is what unblocking means, so the transition is
        correct rather than a workaround — and it happens in our store only.

        Unblocking used to push herdr `working` here, one line before the doorbell, in the
        belief that a report re-registers the name. It evicts it (`Herdr.report_state`), so
        that push destroyed the binding in the same breath as the ring that needed it: the
        block cleared, `agent prompt` answered agent_not_found, and the human's answer was
        never delivered. Nothing may be reported on this path.
        """
        store.create_agent(self.db, name="w", role="worker", pane_id="w1:p1")
        store.set_state(self.db, "w", "blocked")
        self.b.tell(["w"], "here is your answer", me=HUMAN)
        self.assertEqual(self.h.states, [])                   # the name still binds
        self.assertEqual(store.get_agent(self.db, "w")["state"], "working")
        self.assertTrue(any(n == "w" for n, _ in self.h.prompts))

    def test_a_siblings_mail_does_not_cancel_a_block(self):
        """The answer Andrew eventually gives would arrive buried under it.

        Blocking tells herdr nothing at all (a report would cost the name), so nothing
        downstream can tell a blocked agent from an idle one — the store is the only
        record. A
        ring used to unblock unconditionally before every delivery, so any sibling's
        ordinary `tell` put the agent back to `working` and dropped it off the one readout
        that shows a person somebody needs them.
        """
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="w", role="worker", parent="lead",
                           pane_id="w1:p1")
        store.create_agent(self.db, name="sib", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.b.block("which branch?", me="w")
        self.h.prompts.clear()

        self.b.tell(["w"], "fyi, I renamed the fixture", me="sib")

        self.assertEqual(store.get_agent(self.db, "w")["state"], "blocked")
        self.assertEqual(self.h.prompts, [])                       # not announced either
        [needs] = [a for a in status.collect(self.db, self.h, needs_me=True).agents
                   if a.needs_human]
        self.assertEqual((needs.name, needs.blocked_why), ("w", "which branch?"))
        # Held, not lost: it is still queued for once the block is answered.
        self.assertEqual(len(store.undelivered(self.db)), 1)

    def test_a_childs_done_does_not_cancel_its_parents_block(self):
        """`done` rings the parent like anything else, and a blocked parent is not idle."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1")
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.b.block("which branch?", me="lead")
        self.h.prompts.clear()

        self.b.done("shipped it", me="kid")

        self.assertEqual(store.get_agent(self.db, "lead")["state"], "blocked")
        self.assertEqual(self.h.prompts, [])
        self.assertEqual([a.name for a in
                          status.collect(self.db, self.h, needs_me=True).agents], ["lead"])

    def test_held_mail_is_rung_once_the_human_answers_the_block(self):
        """Held, never dropped: the sibling's mail lands with the answer that released it."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="w", role="worker", parent="lead",
                           pane_id="w1:p1")
        store.create_agent(self.db, name="sib", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.b.block("which branch?", me="w")
        self.b.tell(["w"], "fyi", me="sib")
        self.h.prompts.clear()

        self.b.tell(["w"], "use main", me=HUMAN)

        self.assertEqual(store.get_agent(self.db, "w")["state"], "working")
        self.assertEqual([n for n, _ in self.h.prompts], ["w"])
        self.assertEqual([m["body"] for m in self.b.inbox(me="w")], ["fyi", "use main"])

    def test_a_flush_does_not_cancel_a_block_for_a_siblings_mail(self):
        """`flush_pending` runs at the start of every `sb` command, so this fires on any
        traffic anywhere in the fleet — the fastest way to lose a block."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p0")
        store.create_agent(self.db, name="w", role="worker", parent="lead",
                           pane_id="w1:p1")
        store.create_agent(self.db, name="sib", role="worker", parent="lead",
                           pane_id="w1:p2")
        self.h.states_by_name = {"w": "working"}
        self.b.tell(["w"], "fyi", me="sib")                        # queued, mid-turn
        self.b.block("which branch?", me="w")
        self.h.prompts.clear()
        self.h.states_by_name = {"w": "idle"}                      # the block leaves it idle
        self.b._alive_cache = None

        self.assertEqual(self.b.flush_pending(), [])
        self.assertEqual(store.get_agent(self.db, "w")["state"], "blocked")
        self.assertEqual(self.h.prompts, [])

        # ...and the human's answer, arriving through the same flush, does clear it.
        self.b.tell(["w"], "use main", me=HUMAN)
        self.assertEqual(store.get_agent(self.db, "w")["state"], "working")

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
        self.b.tell(["w"], "stop, do this instead", mode=INTERRUPT)
        self.assertEqual(self.h.keys[0], ("w", ("esc",)))
        self.assertIn("INTERRUPT", self.h.prompts[-1][1])

    # -- cleanup / restore -----------------------------------------------

    def test_cleanup_closes_finished_children(self):
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])
        self.assertIn("w1:p1", self.h.closed)

    def test_cleanup_reaches_an_agent_that_died_without_reporting(self):
        """What reconciling drift buys. Every sweep gates on the row being finished, and
        a crashed agent's row never gets there on its own — so until `sb status` writes
        the death back, the one agent that most needs sweeping is the one nothing can."""
        store.create_agent(self.db, name="orch", role="lead")
        # `session_id` marks it as past its spawn — status holds off on reaping a
        # session-less row this young, since that is a claim mid-spawn.
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        self.h.states_by_name = {}                     # herdr has never heard of it
        self.assertEqual(self.b.cleanup(me="orch"), [])          # still reads 'working'
        reap_gone(self.db, self.h)
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])

    def test_cleanup_closes_a_finished_agent_herdr_still_has(self):
        """The normal sweep, and the reason the liveness gate is scoped to `failed`: an
        agent that called `sb done` keeps a live idle pane, and herdr lists it. Gating
        every close on herdr's silence would leave nothing for `sb cleanup` to do."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        store.set_state(self.db, "kid", "done")
        self.h.states_by_name = {"kid": "idle"}
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])

    def test_cleanup_never_closes_a_reaped_agent_herdr_still_has(self):
        """The one that already destroyed two live agents. `failed` is not a report — it
        is `status._record_gone`'s inference from herdr's silence, and a spawn slow enough
        to outlast the confirmation grace has it written about an agent that is very much
        alive. herdr still listing the name refutes the row, so a bare sweep must leave it
        alone."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        self.h.states_by_name = {}                     # a readout mid-spawn sees nothing
        reap_gone(self.db, self.h)
        self.assertEqual(store.get_agent(self.db, "kid")["state"], status.GONE_STATE)

        self.h.states_by_name = {"kid": "working"}     # the spawn landed after all
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])
        self.assertEqual(self.h.closed, [])

    def test_cleanup_will_not_close_a_reaped_agent_when_herdr_cannot_be_asked(self):
        """Fail CLOSED, alone in this file. Everywhere else "cannot tell" means carry on,
        because the cost is a doorbell or a duplicate root. Here it is a live pane, and
        for a row that never got a session id there is no `sb restore` to undo it — so
        an unreachable herdr must stop the sweep, not wave it through."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        self.h.states_by_name = {}
        reap_gone(self.db, self.h)                     # reaped while herdr was answering

        self.h.list_error = HerdrError("down", "no server")
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])
        self.assertEqual(self.h.closed, [])
        # And it is a skip, not a state change: the row is untouched for the next sweep.
        self.assertEqual(store.get_agent(self.db, "kid")["state"], status.GONE_STATE)

    def test_cleanup_dry_run_does_not_offer_a_reaped_agent_herdr_still_has(self):
        """`--dry-run` is what a human reads before sweeping; listing a live agent there
        is how they learn to trust the sweep that kills it."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        self.h.states_by_name = {}
        status.collect(self.db, self.h)
        self.h.states_by_name = {"kid": "working"}
        self.assertEqual(self.restart_sb().cleanup(me="orch", dry_run=True), [])

    def test_cleanup_force_still_closes_a_named_agent_herdr_has(self):
        """The escape hatch has to survive the new gate, or an agent herdr has genuinely
        lost track of — listed but dead — becomes unreachable by any command."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        self.h.states_by_name = {}
        status.collect(self.db, self.h)
        self.h.states_by_name = {"kid": "working"}
        self.assertEqual(self.restart_sb().cleanup(["kid"], me="orch", force=True), ["kid"])

    # -- whose pane is it (the ghost-name problem's close half) -----------

    def test_force_will_not_close_a_pane_a_stranger_now_holds(self):
        """The near-miss this exists for. Pane ids are recycled, herdr is machine-global,
        and two clones name their workers the same way — so a dead row's `pane_id` can
        come to mean somebody else's live agent, under the very same name. `--force`
        overrides intent, not identity: the terminal ids disagree, so nothing is closed.

        It matters most here because `--force` takes live descendants with the row, so a
        wrong close is a stranger's whole subtree and none of it comes back."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="worker-1", role="worker", parent="orch",
                           pane_id="w9:p1", session_id="s-ours", terminal_id="term-ours")
        store.set_state(self.db, "worker-1", "done")
        self.h.list_agents = lambda: [
            Agent(name="worker-1", pane_id="w9:p1", terminal_id="term-theirs",
                  state="working")]                    # the other clone's, same name
        got = self.restart_sb().cleanup(["worker-1"], me="orch", force=True)
        self.assertEqual(got, [])
        self.assertNotIn("w9:p1", self.h.closed)

    def test_the_close_follows_the_terminal_id_when_the_pane_has_moved(self):
        """Resolved, not trusted. A pane that moved changes id — herdr says so itself —
        and the recorded one is then either nothing or somebody else. The terminal id
        still names one agent, so the close goes where that agent actually is."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w9:p1", session_id="s-kid", terminal_id="term-ours")
        store.set_state(self.db, "kid", "done")
        self.h.list_agents = lambda: [
            Agent(name="kid", pane_id="w9:p7", terminal_id="term-ours", state="idle")]
        self.assertEqual(self.restart_sb().cleanup(me="orch"), ["kid"])
        self.assertIn("w9:p7", self.h.closed)
        self.assertNotIn("w9:p1", self.h.closed)

    def test_a_row_with_no_terminal_id_will_not_take_an_occupied_pane(self):
        """Identity unavailable is a refusal, not a guess. Rows written before the column
        existed, and rows still mid-spawn, have nothing to prove ownership with — so they
        may close an empty pane and never one somebody is sitting in."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w9:p1", session_id="s-kid")     # no terminal id
        store.set_state(self.db, "kid", "done")
        self.h.list_agents = lambda: [
            Agent(name="stranger", pane_id="w9:p1", terminal_id="term-theirs",
                  state="working")]
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])
        self.assertNotIn("w9:p1", self.h.closed)

    def test_cleanup_never_closes_a_blocked_agent(self):
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        store.set_state(self.db, "kid", "blocked")
        self.assertEqual(self.b.cleanup(me="orch"), [])

    def test_cleanup_never_closes_an_agent_with_unread_mail(self):
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch", pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")
        # herdr still knows the name, so the doorbell can still ring and the mail is still
        # readable — which is what the gate is protecting.
        self.h.states_by_name = {"kid": "idle"}
        store.put_message(self.db, from_agent="orch", to_agent="kid", kind="tell", body="wait")
        self.assertEqual(self.b.cleanup(me="orch"), [])

    def test_mail_nobody_can_ever_read_does_not_jam_the_row_forever(self):
        """The observed jam: `done`, a live pane id, one message, stuck for good.

        The agent reported done, so herdr no longer answers to its name — the doorbell
        cannot ring and the inbox will never be opened. The unread gate refused to close
        it anyway, so the row was closable by neither a sweep nor anything but `--force`,
        for mail nobody could ever read.
        """
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")
        store.put_message(self.db, from_agent="orch", to_agent="kid", kind="tell", body="wait")
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])
        self.assertIn("w1:p1", self.h.closed)
        # Nothing was discarded to get there: the message is still in the store, and
        # `sb restore` brings back an inbox that still holds it.
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "kid", mark=False)],
                         ["wait"])

    def test_a_pane_that_has_already_gone_counts_as_closed(self):
        """A human closes the tmux pane by hand. `close_pane` then answers
        `pane_not_found`, which was logged as a failure — so `pane_id` stayed set and
        every later sweep repeated the same doomed call, forever. It is the close having
        happened, so it is recorded as one.
        """
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")

        def gone(pane):
            raise HerdrError("pane_not_found", f"pane {pane} not found")
        self.h.close_pane = gone

        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])
        a = store.get_agent(self.db, "kid")
        self.assertIsNone(a["pane_id"])                   # nothing left to retry against
        self.assertEqual(a["state"], "done")
        kinds = [e["kind"] for e in store.recent_events(self.db, agent="kid")]
        self.assertIn("cleanup_pane_gone", kinds)
        self.assertNotIn("cleanup_failed", kinds)
        self.assertEqual(self.b.cleanup(me="orch"), [])   # and the sweep does not loop

    def test_a_close_that_fails_for_any_other_reason_still_holds_the_row(self):
        """Only "the pane is gone" is a close. A herdr blip is not, and the row must stay
        closeable rather than be marked done on a failure."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")

        def blip(pane):
            raise HerdrError("connection_refused", "herdr is down")
        self.h.close_pane = blip

        self.assertEqual(self.b.cleanup(me="orch"), [])
        self.assertEqual(store.get_agent(self.db, "kid")["pane_id"], "w1:p1")
        self.assertIn("cleanup_failed",
                      [e["kind"] for e in store.recent_events(self.db, agent="kid")])

    def test_cleanup_never_escapes_the_callers_subtree(self):
        """A sweeping agent must not close a sibling's agents."""
        store.create_agent(self.db, name="mine", role="lead")
        store.create_agent(self.db, name="my-kid", role="worker", parent="mine",
                           pane_id="w1:p1")
        store.create_agent(self.db, name="theirs", role="lead")
        store.create_agent(self.db, name="their-kid", role="worker", parent="theirs",
                           pane_id="w1:p2")
        for n in ("my-kid", "their-kid"):
            store.set_state(self.db, n, "done")
        self.assertEqual(self.b.cleanup(me="mine"), ["my-kid"])
        self.assertNotIn("w1:p2", self.h.closed)

    # -- cleanup: the invariant ------------------------------------------
    #
    # INVARIANT: an agent whose pane is closed has no descendant whose pane is still
    # working. Every test here asserts the HARM — the parent's pane being closed, or the
    # summary that then cannot be delivered — and not what `cleanup` returned.

    def _family(self, *, child_state: str = "working"):
        """orch → lead (done, pane w1:p1) → worker (still going, pane w1:p2)."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="lead", role="lead", parent="orch",
                           pane_id="w1:p1")
        store.create_agent(self.db, name="worker", role="worker", parent="lead",
                           pane_id="w1:p2")
        store.set_state(self.db, "lead", "done")
        if child_state != "working":
            store.set_state(self.db, "worker", child_state)

    def test_a_sweep_leaves_a_done_parent_whose_child_is_still_working(self):
        """The four old gates all pass for `lead`: finished, its own report, no mail, role
        says close. Nothing asked whether anything was still running underneath it."""
        self._family()
        self.b.cleanup(me="orch")
        self.assertNotIn("w1:p1", self.h.closed)
        self.assertEqual(store.get_agent(self.db, "lead")["pane_id"], "w1:p1")
        # and the log can answer "why is that one still here"
        held = [e for e in store.recent_events(self.db, agent="lead")
                if e["kind"] == "cleanup_held"]
        self.assertEqual(len(held), 1)

    def test_a_blocked_child_holds_its_parent_open_too(self):
        """A blocked child is the sharp case: it is waiting on a person, and closing the
        pane above it is how the answer stops being able to reach anyone."""
        self._family(child_state="blocked")
        self.b.cleanup(me="orch")
        self.assertNotIn("w1:p1", self.h.closed)

    def test_naming_a_parent_with_a_live_child_closes_nothing(self):
        self._family()
        with self.assertRaises(ValueError) as e:
            self.b.cleanup(["lead"], me="orch")
        self.assertIn("worker", str(e.exception))       # says which agent is holding it
        self.assertEqual(self.h.closed, [])
        self.assertEqual(store.get_agent(self.db, "lead")["pane_id"], "w1:p1")

    def test_force_takes_the_live_child_with_the_parent_leaves_first(self):
        """Issue #53's decision, reversing the one this test used to pin.

        `--force` used to stop dead at a live child, on the argument that a flag about the
        parent must not decide the fate of an agent nobody named. What that left was a row
        the board draws, refused by name and refused under force, with no command that
        could clear it. So force now does the leaves-up walk itself — and the INVARIANT is
        never broken on the way, because the child's pane is closed before the parent's.
        """
        self._family()
        r = self.b.cleanup(["lead"], me="orch", force=True)
        self.assertEqual(list(r), ["worker", "lead"])   # leaves first, in that order
        self.assertEqual(self.h.closed, ["w1:p2", "w1:p1"])
        # and the log says these came down because somebody forced their parent
        sub = [e for e in store.recent_events(self.db, agent="lead")
               if e["kind"] == "cleanup_forced_subtree"]
        self.assertEqual(len(sub), 1)
        self.assertEqual(json.loads(sub[0]["payload"])["descendants"], "worker")

    def test_one_held_parent_stops_the_whole_named_cleanup(self):
        """Refused before anything is closed. Half of `sb cleanup a b` is worse than none:
        the caller reads one error and cannot tell what already happened."""
        self._family()
        store.create_agent(self.db, name="sib", role="worker", parent="orch",
                           pane_id="w1:p3")
        store.set_state(self.db, "sib", "done")
        with self.assertRaises(ValueError):
            self.b.cleanup(["sib", "lead"], me="orch")
        self.assertEqual(self.h.closed, [])

    def test_a_dry_run_does_not_offer_a_parent_with_a_live_child(self):
        """`--dry-run` is what a human reads before sweeping, and it writes nothing."""
        self._family()
        self.assertEqual(self.b.cleanup(me="orch", dry_run=True), [])
        self.assertEqual([e["kind"] for e in store.recent_events(self.db, agent="lead")
                          if e["kind"] == "cleanup_held"], [])

    def test_closing_the_subtree_from_the_leaves_up_always_works(self):
        """The way out that keeps the invariant rather than breaking it — and the reason
        the gate needs no lifting to stay usable."""
        self._family()
        self.b.cleanup(["worker"], me="orch", force=True)
        self.b.cleanup(["lead"], me="orch")
        self.assertIn("w1:p1", self.h.closed)

    def test_only_force_closes_over_a_live_child_and_a_sweep_never_can(self):
        """What survived issue #53's decision. `--leave-children` was the one way through
        this gate and it is gone (DESIGN-TRUTH.md's "`--include-kept`,
        `--leave-children`"); `--force` is now the other, and it is illegal on a sweep. So
        nothing ever closes an unnamed subtree on its own judgement, which was the part of
        the old argument that was actually about safety."""
        self._family()
        with self.assertRaises(ValueError):
            self.b.cleanup(["lead"], me="orch")         # named, no force: still refused
        with self.assertRaises(ValueError):
            self.b.cleanup(me="orch", force=True)       # and force is not a sweep
        self.assertNotIn("w1:p1", self.h.closed)        # the parent's pane stays up
        self.assertNotIn("w1:p2", self.h.closed)        # and so does the child's
        self.assertEqual(self.b.cleanup(me="orch"), [])  # a plain sweep takes neither

    def test_force_clears_an_already_closed_row_the_board_still_draws(self):
        """Issue #53 end to end, in the shape it was actually filed in.

        The parent was closed; a descendant still held a pane, so the board kept drawing
        the parent; and every `sb cleanup <parent>` — with or without `--force` — answered
        `already closed` about a row `sb status` plainly listed. Net effect as filed: the
        agent could not be cleared from the board by name at all. Now it can, by the one
        command the operator already reached for, and the `already closed` refusal is gone
        with it: it would be a gate reported against a command that did the job.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:orch")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:kid", session_id="s-kid")
        store.set_state(self.db, "kid", "done")     # reported an end, pane still open
        store.set_state(self.db, "orch", "done")
        self.assertEqual(list(self.b.cleanup(["orch"], me=HUMAN)), ["orch"])
        self.h.closed.clear()

        r = self.b.cleanup(["orch"], me=HUMAN, force=True)
        self.assertEqual(list(r), ["kid"])              # the row itself was already gone
        self.assertEqual(r.refused, [])                 # and is not refused for being so
        self.assertEqual(self.h.closed, ["w1:kid"])
        self.assertIsNone(store.get_agent(self.db, "kid")["pane_id"])

    def test_force_walks_a_deep_subtree_from_the_deepest_row_up(self):
        """The invariant is kept by ORDER, so the order is the thing to pin: a row is only
        ever closed once everything beneath it already is. Three levels, because two
        cannot tell depth-ordering from parent-last."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="a", role="lead", parent="orch", pane_id="p-a")
        store.create_agent(self.db, name="b", role="lead", parent="a", pane_id="p-b")
        store.create_agent(self.db, name="c", role="worker", parent="b", pane_id="p-c")
        store.set_state(self.db, "a", "done")           # b and c are still born-working
        self.assertEqual(list(self.b.cleanup(["a"], me="orch", force=True)),
                         ["c", "b", "a"])
        self.assertEqual(self.h.closed, ["p-c", "p-b", "p-a"])

    def test_a_fully_finished_subtree_still_sweeps(self):
        """The gate must not cost the normal sweep. A finished child is not live work."""
        self._family(child_state="done")
        self.b.cleanup(me="orch")
        self.assertIn("w1:p1", self.h.closed)
        self.assertIn("w1:p2", self.h.closed)

    def test_a_child_of_a_pane_less_parent_cannot_deliver_its_summary(self):
        """WHY the gate exists, spelled out end to end.

        The child reports `sb done`; the summary is written to the parent and the doorbell
        rung. The parent has no pane and herdr has lost the binding that went with it, so
        the ring fails and the summary sits in the store with nobody able to read it — the
        failure class where the board looks fine and something is silently not happening.

        `cleanup` can no longer produce this state at all — `--leave-children` was the
        only route through the live-descendants gate and it is gone — so the parent's
        pane is taken away here directly. The harm is still worth pinning: it is what the
        gate exists to prevent, and any future way of losing a parent's pane meets it.
        """
        self._family()
        store.set_state(self.db, "lead", "done")
        self.db.execute("UPDATE agents SET pane_id=NULL WHERE name='lead'")
        self.db.commit()
        self.h.unreachable.add("lead")                  # the binding went with the pane

        self.b.done("my part is finished", me="worker")
        stranded = self.db.execute(
            "SELECT * FROM messages WHERE to_agent='lead' AND kind='done'").fetchall()
        self.assertEqual([m["body"] for m in stranded], ["[done] my part is finished"])
        # Recorded as skipped rather than failed: the ring is not attempted at all for a
        # finished agent with no pane. The summary is stranded either way — that is the
        # harm this test names — but nothing re-attempts it, and it does not sit in the
        # undelivered set that `flush_pending` and the collector's doorbell both chase.
        kinds = [e["kind"] for e in store.recent_events(self.db, agent="lead")]
        self.assertIn("ring_skipped", kinds)
        self.assertIn("mail_cleared", kinds)
        self.assertEqual(store.undelivered(self.db), [])

    def test_a_refused_close_keeps_the_childs_summary_deliverable(self):
        """The same story with the gate doing its job: the pane is still there, so the
        summary lands and the doorbell rings."""
        self._family()
        self.h.states_by_name = {"lead": "idle", "worker": "working"}
        with self.assertRaises(ValueError):
            self.b.cleanup(["lead"], me="orch")

        self.b.done("my part is finished", me="worker")
        self.assertEqual(store.undelivered(self.db), [])
        self.assertIn("lead", [p[0] for p in self.h.prompts])

    def test_done_with_children_still_working_stays_legal_and_is_recorded(self):
        """Deliberately NOT a protocol change: a parent that delegated and then reached
        its own end must have a legal move, and the one it would reach for otherwise is
        closing its children. The harm was never `done` — it was the close that follows,
        and that is what is gated. So this reports, records, and stays closeable-proof.
        """
        self._family(child_state="working")
        store.set_state(self.db, "lead", "working")      # about to report done itself
        self.b.done("handing off", me="lead")

        self.assertEqual(store.get_agent(self.db, "lead")["state"], "done")
        self.assertIn("done_with_live_children",
                      [e["kind"] for e in store.recent_events(self.db, agent="lead")])
        # and the summary still reached its own parent, unchanged
        self.assertEqual([m["body"] for m in store.unread_for(self.db, "orch")],
                         ["[done] handing off"])
        # the pane survives the sweep that follows
        self.b.cleanup(me="orch")
        self.assertNotIn("w1:p1", self.h.closed)

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
        # `sb board`, not `sb status --needs-me`: the board is the human's surface
        # (DESIGN-TRUTH.md), and pointing them at status is what this used to do.
        self.assertIn("sb board", buf.getvalue())
        self.assertNotIn("sb status", buf.getvalue())
        self.assertNotIn("no new messages", buf.getvalue())

    def test_telling_the_human_is_refused_rather_than_written_and_lost(self):
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        with self.assertRaises(ValueError):
            self.b.tell([HUMAN], "fyi", me="kid")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"], 0)

    def test_telling_a_name_nothing_knows_is_refused_before_the_doorbell(self):
        """A typo used to be delivered TO NOBODY, at the cost of a herdr call.

        `_resolve` passes an unknown name straight through and `same_tree` deliberately
        declines to refuse it, so `tell` wrote a durable row addressed to a name that has
        never existed and then rang `agent prompt` for it. On a machine without herdr that
        subprocess raised `FileNotFoundError` — not a `HerdrError` — straight out of `sb`
        as a traceback, which is how it turned up: red CI on every platform.
        """
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        with self.assertRaises(KeyError) as cm:
            self.b.tell(["nobdy"], "hi", me="kid")
        self.assertIn("no such agent: nobdy", str(cm.exception))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"], 0)
        self.assertEqual(self.h.prompts, [])

    def test_a_root_agents_tell_to_parent_is_refused_too(self):
        """`parent` resolves to the human for a root agent, and the human has no mailbox."""
        store.create_agent(self.db, name="root", role="lead", pane_id="w1:p1")
        with self.assertRaises(ValueError):
            self.b.tell(["parent"], "progress", me="root")

    def test_cleanup_can_be_forced_on_one_named_stuck_agent(self):
        """The escape hatch. An agent whose state never advanced, or that holds mail it
        can never read, is unreachable by every sweep — and there was no other way out."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="stuck", role="worker", parent="orch",
                           pane_id="w1:p1")
        self._legacy_keep("stuck")
        store.put_message(self.db, from_agent="orch", to_agent="stuck",
                          kind="tell", body="unreadable")
        self.assertEqual(self.b.cleanup(me="orch"), [])                    # every gate holds
        self.assertEqual(self.b.cleanup(["stuck"], me="orch", force=True), ["stuck"])
        self.assertIn("w1:p1", self.h.closed)

    # -- cleanup explains itself (1.4) -----------------------------------

    def test_cleanup_says_which_gate_refused_a_named_agent(self):
        """`closed: (nothing)` is an outcome, never a reason. Naming an agent and getting
        a blank line back left `--force` — which lifts all five gates at once — as the
        only move, with no way to learn which one had fired."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        r = self.b.cleanup(["kid"], me="orch")
        self.assertEqual(r, [])
        self.assertEqual([n for n, _ in r.refused], ["kid"])
        self.assertIn("blocked", r.refused[0][1])

    def test_cleanup_names_the_unread_mail_that_holds_a_row(self):
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id="s-kid")
        store.set_state(self.db, "kid", "done")
        self.h.states_by_name = {"kid": "idle"}      # still reachable, so the mail holds
        store.put_message(self.db, from_agent="orch", to_agent="kid",
                          kind="tell", body="one more thing")
        r = self.b.cleanup(["kid"], me="orch")
        self.assertEqual(r, [])
        self.assertIn("unread mail", r.refused[0][1])

    # -- cleanup reaches a row whose turn edge we gave up on ---------------

    def _quiet_kid(self, *, turn: Optional[str] = None, idle_for: int = 0,
                   session: Optional[str] = "s-kid") -> None:
        """A `working` row under `orch` that is not doing anything visible.

        `session_id` puts it past the spawn grace, herdr answering `idle` is the pane
        signal, and `created_at` is the idle clock — nothing has ever logged an event for
        this row, so `status._last_activity` has nothing and `idle` is its age.
        """
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1", session_id=session)
        if turn is not None:
            store.set_turn(self.db, "kid", turn)
        if idle_for:
            self.db.execute("UPDATE agents SET created_at=? WHERE name=?",
                            (store.now() - idle_for, "kid"))
            self.db.commit()
        self.h.states_by_name = {"kid": "idle"}

    def _forget_kid_turn(self) -> None:
        """Drive the real repair until `_forget_turn` throws the stuck edge away.

        Two readings a `turn_doubt_grace` apart, through `status.collect` itself rather
        than by writing the outcome — the point of the gate is that it acts on THAT
        verdict, so a test that stamped the event by hand would pin nothing about how the
        verdict is reached. Same shape as `reap_gone` above, for the sibling debounce.
        """
        status.collect(self.db, self.h)
        status.collect(self.db, self.h,
                       now=store.now() + int(status.TURN_DOUBT_GRACE) + 1)
        self.assertIsNone(store.get_agent(self.db, "kid")["turn"])

    def test_a_sweep_closes_the_row_whose_turn_edge_we_gave_up_on(self):
        """The six-and-a-half-hour row, and the only one this lifts the gate for. Its
        session died mid-turn, so the `working` edge was never closed and nothing ever
        wrote `done`; `_forget_turn` threw the edge away after the full doubt window and
        the sweep used to go on refusing the row anyway, on the strength of a `state`
        column only the agent itself could advance."""
        self._quiet_kid(turn=store.TURN_WORKING,
                        idle_for=int(status.TURN_STALE_GRACE) + 60)
        self._forget_kid_turn()

        # The live re-check first: a verdict up to a doubt window old does not outrank
        # herdr saying the pane is busy right now.
        self.h.states_by_name = {"kid": "working"}
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])
        self.assertEqual(self.h.closed, [])

        self.h.states_by_name = {"kid": "idle"}
        self.assertEqual(self.restart_sb().cleanup(me="orch"), ["kid"])
        self.assertIn("w1:p1", self.h.closed)
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "done")

    def test_a_child_that_ended_its_turn_to_wait_is_not_swept(self):
        """The cost of getting this bar wrong, and the reason it is not `status.stalled`.

        `stalled` has no idle floor in it at all: the `Stop` hook writing `turn='idle'` is
        the ORDINARY end of a turn, so a child that ran `sb tell --needs-reply` and
        stopped to wait for the answer is `stalled` at zero seconds — and leads are told
        to sweep constantly. Neither a sweep nor naming it may take that row; `--force`
        is what a person who means it types.
        """
        self._quiet_kid(turn=store.TURN_IDLE)
        self.assertEqual(self.b.cleanup(me="orch"), [])
        r = self.restart_sb().cleanup(["kid"], me="orch")
        self.assertEqual(r, [])
        self.assertIn("--force", r.refused[0][1])
        self.assertEqual(self.h.closed, [])
        self.assertEqual(self.restart_sb().cleanup(["kid"], me="orch", force=True),
                         ["kid"])

    def test_a_doubted_turn_is_not_enough_to_close_a_row_named_or_swept(self):
        """One herdr reading must never cost a pane. `turn_doubted` is a single reading
        past 30 minutes of quiet, and a live agent goes 139 minutes without an `sb` call
        at p99.9 while herdr reads a mid-tool-call pane as idle — which is why
        `turn_doubt_grace` exists and why only its verdict opens this gate.

        The NAMED call goes first, and the order is what makes this test pin anything: a
        sweep's refusal used to reset the row's idle clock, which put `turn_doubted` back
        to False on its own — so sweeping first left the named call nothing to be wrong
        about, and the test passed against the bar it was written to rule out.
        """
        self._quiet_kid(turn=store.TURN_WORKING,
                        idle_for=int(status.TURN_STALE_GRACE) + 60)
        snap = status.collect(self.db, self.h, reap=False)
        self.assertTrue(next(a for a in snap.agents if a.name == "kid").turn_doubted)
        self.assertEqual(self.b.cleanup(["kid"], me="orch"), [])
        self.assertEqual(self.restart_sb().cleanup(me="orch"), [])

    def test_refusing_a_row_does_not_reset_the_clock_that_would_free_it(self):
        """The sweep must not be able to starve its own gate.

        A refusal is `cleanup` acting ON a row, not the row acting, but it is logged with
        `agent=<name>` — so `status._last_activity` counted it and every refusal reset the
        idle clock of the row it had just declined to touch (observed live going 45s back
        to 1s). `turn_doubted` needs that clock to climb past `turn_stale_grace` before
        anything doubts the edge, `_forget_turn` needs the doubt sustained after that, and
        the gate above needs `_forget_turn` to have fired — so a lead sweeping constantly,
        which the protocol tells leads to do, could keep the rows it kept refusing from
        ever becoming sweepable at all. Fixed in `status.DONE_TO_THE_AGENT`.
        """
        self._quiet_kid(turn=store.TURN_WORKING,
                        idle_for=int(status.TURN_STALE_GRACE) + 60)
        self.assertEqual(self.b.cleanup(me="orch"), [])            # refused, and logged
        self.assertEqual(self.restart_sb().cleanup(["kid"], me="orch"), [])
        kid = next(a for a in status.collect(self.db, self.h, reap=False).agents
                   if a.name == "kid")
        self.assertGreaterEqual(kid.idle, status.TURN_STALE_GRACE)
        self.assertTrue(kid.turn_doubted)   # still on its way to the repair

    def test_a_newcomer_with_no_session_id_is_never_swept(self):
        """The one close that is NOT free. `restore` refuses a row with no session id, so
        an agent still reading its way into its first task — no `sb` call yet, so no
        session id and no turn edge of ours — is the row where a wrong sweep cannot be
        undone. No turn edge was ever recorded, so there is none to have given up on."""
        self._quiet_kid(session=None, idle_for=int(status.STALL_GRACE) + 60)
        self.assertEqual(self.b.cleanup(me="orch"), [])
        self.assertEqual(self.restart_sb().cleanup(["kid"], me="orch"), [])
        self.assertEqual(self.h.closed, [])

    def test_a_forgotten_row_restore_cannot_reach_is_refused_and_says_why(self):
        """The verdict is not enough on its own: the close has to stay free.

        A turn edge is written by the hooks, which resolve their caller by pane id when
        the store has no session id yet — so an agent that never ran a single `sb` command
        still gets one, and switchboard can give up on it. Swept, that row is gone for
        good: `restore` refuses a row with no session id. Verified live before this gate
        existed. The refusal names the session id rather than the state, because the state
        is not what holds it, and `--force` still closes it.
        """
        self._quiet_kid(session=None, turn=store.TURN_WORKING,
                        idle_for=int(status.TURN_STALE_GRACE) + 60)
        self._forget_kid_turn()
        r = self.restart_sb().cleanup(me="orch")
        self.assertEqual(r, [])
        self.assertEqual(self.h.closed, [])
        self.assertIn("session id", r.refused[0][1])
        self.assertEqual(r.notable, r.refused)      # a sweep must not swallow this one
        r = self.restart_sb().cleanup(["kid"], me="orch")
        self.assertEqual(r, [])
        self.assertIn("--force", r.refused[0][1])
        self.assertEqual(self.restart_sb().cleanup(["kid"], me="orch", force=True),
                         ["kid"])

    def test_sweeping_a_forgotten_row_does_not_unwind_the_parent_above_it(self):
        """A parent is swept on its OWN verdict and on nothing else. Its excuse for being
        idle is that it has live children, and closing the last of them takes that excuse
        away — under a bar built on `stalled` that made every sweep walk a live branch
        upward one level at a time."""
        self._quiet_kid(turn=store.TURN_WORKING,
                        idle_for=int(status.TURN_STALE_GRACE) + 60)
        self._forget_kid_turn()
        self.assertEqual(self.restart_sb().cleanup(me="orch"), ["kid"])
        self.assertEqual(self.restart_sb().cleanup(me=HUMAN), [])   # orch stays
        self.assertEqual(store.get_agent(self.db, "orch")["state"], "working")

    def test_a_forgotten_row_holding_mail_is_still_refused_and_says_so(self):
        """The mail gate stands on its own. Mail is cleared by the close and by nothing
        else, so letting the row through the finished gate must not read as the stall
        having been missed — the refusal names the gate that actually holds it."""
        self._quiet_kid(turn=store.TURN_WORKING,
                        idle_for=int(status.TURN_STALE_GRACE) + 60)
        self._forget_kid_turn()
        store.put_message(self.db, from_agent="orch", to_agent="kid",
                          kind="tell", body="one more thing")
        r = self.restart_sb().cleanup(["kid"], me="orch")
        self.assertEqual(r, [])
        self.assertIn("unread mail", r.refused[0][1])
        self.assertIn("giving up on its turn", r.refused[0][1])
        self.assertEqual(self.h.closed, [])

    def _legacy_keep(self, name: str) -> None:
        """A row as it was written before `--keep` was removed. Nothing writes this any
        more (see `store._INSERT_AGENT`), so a test that wants one writes the column."""
        self.db.execute("UPDATE agents SET cleanup='keep' WHERE name=?", (name,))
        self.db.commit()

    def test_a_row_written_before_keep_was_removed_is_still_held_by_a_sweep(self):
        """The one thing the removal must not break: an agent spawned `--keep` before the
        flag went keeps behaving exactly as it did — held by a sweep, closed when named.
        """
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="lead", parent="orch",
                           pane_id="w1:p1")
        self._legacy_keep("kid")
        store.set_state(self.db, "kid", "done")
        r = self.b.cleanup(me="orch")
        self.assertEqual(r, [])
        self.assertIn("spawned to be kept", r.refused[0][1])
        self.assertEqual(self.b.cleanup(["kid"], me="orch"), ["kid"])   # naming it closes it

    def test_nothing_spawned_now_is_ever_written_kept(self):
        """The write path is what went, not the column."""
        name = self.b.delegate("t", topic="t", role="lead", me="orch")
        self.assertEqual(store.get_agent(self.db, name)["cleanup"], "close")

    def test_cleanup_prints_the_refusals_it_collected(self):
        """The reason has to reach the person who typed the command, not just the log."""
        import argparse, contextlib, io
        from switchboard import cli
        store.create_agent(self.db, name="kid", role="worker", pane_id="w1:p1")
        self.b.block("which branch?", me="kid")
        args = argparse.Namespace(cmd="cleanup", name=["kid"], force=False,
                                  dry_run=False, json=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli._dispatch(args, self.b, self.db, self.h), 0)
        out = buf.getvalue()
        self.assertIn("closed: (nothing)", out)
        self.assertIn("refused kid", out)
        self.assertIn("blocked", out)

    def test_a_sweep_that_closes_something_still_accounts_for_what_it_kept(self):
        """The silence item 1.4 was written about, wearing a different hat.

        `closed: five names` reads as "all done", and acceptance run 4 twice watched a
        sweep leave behind exactly the row a human needed with no word of it. A row that
        was already closed, and an agent that is merely still working, are the sweep doing
        its job and stay out of the readout; a blocked agent is stopped, waiting on a
        person, and is precisely what that person must not walk away from.
        """
        store.create_agent(self.db, name="orch", role="lead")
        for n in ("done1", "blocked1", "busy1", "gone1"):
            store.create_agent(self.db, name=n, role="worker", parent="orch",
                               pane_id=f"w1:{n}", session_id=f"s-{n}")
        store.set_state(self.db, "done1", "done")
        self.b.block("which branch?", me="blocked1")
        store.set_state(self.db, "gone1", "done")          # closed before this sweep ran
        store.update_agent(self.db, "gone1", pane_id=None)
        self.h.states_by_name = {"done1": "idle", "blocked1": "idle", "busy1": "working"}

        r = self.b.cleanup(me="orch")
        self.assertEqual(list(r), ["done1"])
        self.assertEqual(sorted(n for n, _ in r.refused), ["blocked1", "busy1", "gone1"])
        # Only the one a human might have meant survives the cut.
        self.assertEqual([n for n, _ in r.notable], ["blocked1"])
        self.assertIn("blocked", r.notable[0][1])
        self.assertEqual(r.expected, {"busy1", "gone1"})

    def test_already_closed_names_the_descendant_still_holding_a_pane(self):
        """Issue #53: the store said closed while the board drew it, and nothing said why.

        A child that reported `done` and still holds its pane is dead to
        `live_descendants` and alive to the board, so the "still working underneath"
        error never fires and the operator gets a bare `already closed` about a row
        `sb status` plainly lists. The way out — close the child — has to be in the
        refusal, because it is the only thing the operator is shown.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:orch")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:kid", session_id="s-kid")
        store.set_state(self.db, "kid", "done")     # ended, but the pane is still open
        store.set_state(self.db, "orch", "done")

        self.assertEqual(list(self.b.cleanup(["orch"], me=HUMAN)), ["orch"])
        r = self.b.cleanup(["orch"], me=HUMAN)      # the operator's second try
        self.assertEqual(list(r), [])
        name, why = r.refused[0]
        self.assertEqual(name, "orch")
        self.assertIn("already closed", why)
        self.assertIn("kid", why)
        self.assertIn("leaves up", why)
        # And closing the child is what actually clears the board, as the issue found.
        self.assertEqual(list(self.b.cleanup(["kid"], me=HUMAN)), ["kid"])
        self.assertEqual(self.b.cleanup(["orch"], me=HUMAN).refused,
                         [("orch", "already closed")])

    def test_closing_over_a_pane_holding_child_is_logged_and_said_out_loud(self):
        """The same fact as the refusal above, said when it is created, not days later.

        `live_descendants` is state-only, so a `done`-but-uncleaned child does not hold
        the gate and the parent closes over it — from that moment the board draws a dead
        parent with children herdr still lists. That was only ever reconstructable by
        archaeology afterwards; now the close names it and logs it. It still CLOSES: this
        is not a gate, and turning it into one would jam a parent behind a stale pane.
        """
        store.create_agent(self.db, name="orch", role="lead", pane_id="w1:orch")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:kid", session_id="s-kid")
        store.set_state(self.db, "kid", "done")     # ended, but the pane is still open
        store.set_state(self.db, "orch", "done")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(list(self.b.cleanup(["orch"], me=HUMAN)), ["orch"])
        self.assertIn("kid", err.getvalue())
        self.assertIn("still hold a pane", err.getvalue())
        drawn = [e for e in store.recent_events(self.db, agent="orch")
                 if e["kind"] == "cleanup_still_drawn"]
        self.assertEqual(len(drawn), 1)
        self.assertEqual(json.loads(drawn[0]["payload"])["descendants"], "kid")

    def test_no_such_event_when_the_subtree_went_first(self):
        """The leaves-up order is the whole point: closed that way, nothing is left drawn.

        Covers both halves — a child cleaned up before its parent, and `--force`, which
        does that same walk itself, so the set is empty by the time the parent is reached.
        """
        self._family(child_state="done")            # orch → lead → worker, all paned
        store.create_agent(self.db, name="lead2", role="lead", parent="orch",
                           pane_id="w1:p3")
        store.create_agent(self.db, name="worker2", role="worker", parent="lead2",
                           pane_id="w1:p4")
        store.set_state(self.db, "lead2", "done")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            # by hand, leaves up
            self.assertEqual(list(self.b.cleanup(["worker", "lead"], me="orch")),
                             ["worker", "lead"])
            # and --force, which does that same walk itself
            self.assertEqual(list(self.b.cleanup(["lead2"], me="orch", force=True)),
                             ["worker2", "lead2"])
        self.assertEqual(err.getvalue(), "")
        self.assertEqual([e for e in store.recent_events(self.db)
                          if e["kind"] == "cleanup_still_drawn"], [])

    def test_already_closed_stays_bare_when_nothing_below_holds_a_pane(self):
        """The sentence is an explanation of a disagreement, not decoration."""
        store.create_agent(self.db, name="solo", role="worker", pane_id="w1:solo")
        store.set_state(self.db, "solo", "done")
        self.assertEqual(list(self.b.cleanup(["solo"], me=HUMAN)), ["solo"])
        self.assertEqual(self.b.cleanup(["solo"], me=HUMAN).refused,
                         [("solo", "already closed")])

    def test_a_sweep_prints_the_row_it_left_behind(self):
        """The cut is only worth anything if it reaches the person who typed the command.
        `--json` is unchanged and still carries every refusal of either kind."""
        import argparse
        from switchboard import cli
        store.create_agent(self.db, name="orch", role="lead")
        for n in ("done1", "blocked1", "busy1"):
            store.create_agent(self.db, name=n, role="worker", parent="orch",
                               pane_id=f"w1:{n}", session_id=f"s-{n}")
        store.set_state(self.db, "done1", "done")
        self.b.block("which branch?", me="blocked1")
        self.h.states_by_name = {"done1": "idle", "blocked1": "idle", "busy1": "working"}

        def run(as_json):
            args = argparse.Namespace(cmd="cleanup", name=[], force=False,
                                      dry_run=False, json=as_json)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli._dispatch(args, self.b, self.db, self.h), 0)
            return buf.getvalue()

        out = run(False)
        self.assertIn("closed: done1", out)
        self.assertIn("refused blocked1", out)
        self.assertIn("blocked", out)
        # A working agent is not news in itself. It still appears where it IS news —
        # as one of the live children holding its parent's row open.
        self.assertNotIn("refused busy1", out)
        self.assertIn("refused orch: still working underneath", out)
        d = json.loads(run(True))                   # the second sweep closes nothing new
        self.assertEqual(sorted(x["name"] for x in d["refused"]),
                         ["blocked1", "busy1", "done1", "orch"])
        self.assertEqual(sorted(d["expected"]), ["busy1", "done1"])

    def test_a_long_sweep_of_refusals_ends_in_a_line_and_not_a_listing(self):
        """Past a handful the lines stop being a report and start being a listing."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="done1", role="worker", parent="orch",
                           pane_id="w1:done1", session_id="s-done1")
        store.set_state(self.db, "done1", "done")
        for i in range(8):
            store.create_agent(self.db, name=f"b{i}", role="worker", parent="orch",
                               pane_id=f"w1:b{i}", session_id=f"s-b{i}")
            self.b.block("which branch?", me=f"b{i}")
        from switchboard import cli
        r = self.b.cleanup(me="orch")
        text = cli._sweep_refusals(r.notable)
        self.assertEqual(len(text.splitlines()), cli._SWEEP_REFUSALS_SHOWN + 1)
        self.assertIn("and 3 more refused", text)

    def test_forcing_a_live_agent_says_so(self):
        """`--force` skips the finished gate, so an agent mid-turn is closed exactly like
        a wedged one and the only trace was `cleanup(forced=True)`, which cannot tell the
        two apart. Nothing is refused and nothing is sent first — the event is the fix."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="busy", role="worker", parent="orch",
                           pane_id="w1:p1")                      # born working
        self.assertEqual(self.b.cleanup(["busy"], me="orch", force=True), ["busy"])
        self.assertIn("cleanup_forced_live",
                      [e["kind"] for e in store.recent_events(self.db, agent="busy")])

    def test_a_forced_close_that_failed_still_ends_done_and_says_so(self):
        """The trade, kept and made honest. `--force` is documented as the override that
        always ends done, so the bookkeeping is committed even when the close itself
        failed — but committing it silently is the row asserting a pane is gone that
        nobody confirmed is gone, and the id it discards is the last handle on it."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")

        def refuses(pane):
            raise HerdrError("cli_failure", "herdr is not answering")
        self.h.close_pane = refuses

        self.assertEqual(self.b.cleanup(["kid"], me="orch", force=True), ["kid"])
        a = store.get_agent(self.db, "kid")
        self.assertEqual(a["state"], "done")                  # the contract holds
        self.assertIsNone(a["pane_id"])
        kinds = [e["kind"] for e in store.recent_events(self.db, agent="kid")]
        self.assertIn("cleanup_forced_unconfirmed", kinds)
        # The pane id goes into the event, because the row no longer has it and a pane
        # that is still open is otherwise unreachable through the store forever.
        unconfirmed = next(e for e in store.recent_events(self.db, agent="kid")
                           if e["kind"] == "cleanup_forced_unconfirmed")
        self.assertIn("w1:p1", unconfirmed["payload"])

    def test_force_refuses_to_be_a_sweep(self):
        store.create_agent(self.db, name="orch", role="lead")
        with self.assertRaises(ValueError):
            self.b.cleanup(me="orch", force=True)

    def test_cleanup_never_reaches_outside_the_callers_subtree_by_name_either(self):
        store.create_agent(self.db, name="mine", role="lead")
        store.create_agent(self.db, name="theirs", role="worker", pane_id="w1:p9")
        store.set_state(self.db, "theirs", "done")
        with self.assertRaises(KeyError):
            self.b.cleanup(["theirs"], me="mine", force=True)
        self.assertEqual(self.h.closed, [])

    def test_cleanup_clears_the_pane_it_closed(self):
        """A row still claiming a closed pane defeats the 'already gone' guard, so every
        later sweep retries release/close against a dead pane and logs a failure."""
        store.create_agent(self.db, name="orch", role="lead")
        store.create_agent(self.db, name="kid", role="worker", parent="orch",
                           pane_id="w1:p1")
        store.set_state(self.db, "kid", "done")
        self.assertEqual(self.b.cleanup(me="orch"), ["kid"])
        self.assertFalse(store.get_agent(self.db, "kid")["pane_id"])
        self.h.closed.clear()
        self.assertEqual(self.b.cleanup(me="orch"), [])                   # nothing retried
        self.assertEqual(self.h.closed, [])

    # -- answers do not ring ----------------------------------------------

    def test_restore_refuses_a_live_agent_before_making_a_tab(self):
        """`agent start` fails all three attempts under a name herdr already runs, and the
        tab created ahead of it was left behind — one orphan pane per attempt."""
        store.create_agent(self.db, name="w", role="worker", session_id="s",
                           cwd=str(self.repo), pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}
        with self.assertRaises(ValueError):
            self.b.restore("w")
        self.assertEqual(self.h.tabs, [])

    def test_restore_is_not_a_way_back_from_a_lost_name_binding(self):
        """Written down because it is the obvious hope and it is false.

        An agent whose name herdr has stopped answering to is still IN `agent list` — that
        pairing is the whole signature `_binding_lost` reads — so `_alive` says it is
        running and `restore` refuses, pointing at `sb tell`, which is the one thing that
        cannot reach it. Nothing else recovers it either: herdr's own `pane release-agent`
        deletes the record rather than handing detection back, and `agent start` on the
        live pane refuses agent_pane_busy (both measured against 0.8.0). Prevention is the
        only fix there is, which is why `block` reports no state at all.
        """
        store.create_agent(self.db, name="w", role="worker", session_id="s",
                           cwd=str(self.repo), pane_id="w1:p1")
        self.h.states_by_name = {"w": "idle"}   # herdr still lists the pane...
        self.h.unreachable.add("w")             # ...and refuses to prompt the name
        with self.assertRaises(ValueError) as e:
            self.b.restore("w")
        self.assertIn("already running", str(e.exception))

    def test_a_failed_restore_takes_its_tab_back_out(self):
        store.create_agent(self.db, name="w", role="worker", session_id="s",
                           cwd=str(self.repo), pane_id="w1:p1")

        def boom(*a, **kw):
            raise HerdrError("spawn_failed", "after 3 attempts")

        self.h.start_agent = boom
        with self.assertRaises(HerdrError):
            self.b.restore("w")
        self.assertEqual(len(self.h.closed), 1)

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

    def test_restore_comes_back_on_the_tier_it_was_spawned_with(self):
        """Restore brings back the SAME agent, not a fresh one of its role. `--model`
        pinned the tier for the first life only until the row started recording it."""
        name = self.b.delegate("t", topic="t", role="researcher", model="strong", me="orch")
        store.set_state(self.db, name, "done")
        self.h.started.clear()
        self.b.restore(name)
        self.assertEqual(self.h.started[-1]["model_args"],
                         ["--model", "opus", "--effort", "high"])   # not researcher's

    def test_a_row_with_no_recorded_tier_restores_on_its_roles_tier(self):
        """NULL means no override was given — which is what every row written before the
        column says, so old agents come back exactly as they did."""
        store.create_agent(self.db, name="kid", role="researcher", session_id="sess-kid",
                           cwd=str(self.repo), pane_id="w1:p1")
        self.assertIsNone(store.get_agent(self.db, "kid")["tier"])
        self.b.restore("kid")
        self.assertEqual(self.h.started[-1]["model_args"],
                         ["--model", "sonnet", "--effort", "medium"])

    def test_restore_without_a_session_is_an_error(self):
        store.create_agent(self.db, name="kid", role="worker")
        with self.assertRaises(ValueError):
            self.b.restore("kid")

    def test_restore_refuses_when_the_checkout_is_gone(self):
        """herdr substitutes `$HOME` for a `--cwd` that does not exist, so this used to
        print `restored kid` and leave a live agent in Andrew's home directory with none
        of its context. DESIGN-TRUTH: restore is gone once the worktree is."""
        store.create_agent(self.db, name="kid", role="worker", session_id="sess-kid",
                           cwd=str(self.repo / "deleted-worktree"), branch="feature-x")
        store.set_state(self.db, "kid", "done")        # closed, as a restore candidate is
        with self.assertRaises(ValueError) as e:
            self.b.restore("kid")
        self.assertIn("feature-x", str(e.exception))   # where the work still is
        self.assertEqual(self.h.tabs, [])              # and no pane was made anywhere
        self.assertEqual(store.get_agent(self.db, "kid")["state"], "done")

    # -- start (the one command) ------------------------------------------

    def test_start_inside_a_worktree_is_refused_and_names_the_main_checkout(self):
        """A top's space is laid over the checkout `sb start` was run in, so run inside a
        worktree it puts a new orchestrator — and everything it delegates that cannot fork
        — over an agent's working copy and its branch. DESIGN-TRUTH refuses it."""
        main = self.repo / "checkout"
        with mock.patch.object(store, "main_checkout", lambda cwd=None: main):
            with self.assertRaises(ValueError) as cm:
                self.b.start()
        self.assertIn(str(main), str(cm.exception))       # where to run it instead
        self.assertIn(str(self.repo), str(cm.exception))  # and where they actually are
        self.assertEqual(self.h.started, [])

    def test_an_unanswerable_main_checkout_does_not_refuse(self):
        """A repo `sb init` never pinned, whose layout defeats the inference, is a reason
        not to answer — not a reason to refuse the one command worth remembering."""
        def unknowable(cwd=None):
            raise RuntimeError("not inside a git repo")

        self.h.list_agents = lambda: []
        self.h.focus = lambda n: None
        with mock.patch.object(store, "main_checkout", unknowable):
            self.assertEqual(self.b.start(), MAIN_NAME)

    def test_start_creates_the_top_orchestrator_as_a_root(self):
        self.h.list_agents = lambda: []
        self.h.focus = lambda n: None
        name = self.b.start()
        a = store.get_agent(self.db, name)
        self.assertEqual(name, MAIN_NAME)
        self.assertIsNone(a["parent"])          # root: parent NULL, not "human"

    def test_start_always_starts_another_one(self):
        """The contract: unnamed, `sb start` is only ever the start of something.

        It used to mean "take me back" — reusing the last orchestrator, or restoring it.
        Reuse now has to be asked for by name, so a bare second run must SPAWN.
        """
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        first = self.b.start()
        self.h.list_agents = lambda: [HAgent(name=first, pane_id="w1:p1")]
        before = len(self.h.started)
        second = self.b.start()
        self.assertEqual((first, second), (MAIN_NAME, "main-2"))
        self.assertEqual(len(self.h.started), before + 1)
        self.assertIsNone(store.get_agent(self.db, second)["parent"])   # a root, not a kid

    def test_a_bare_start_never_restores(self):
        """A closed orchestrator with a session id is the tempting case: `--resume` would
        work, and that is exactly what the old default did. Its context is reachable by
        name; an unnamed start must not reach for it."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        store.update_agent(self.db, MAIN_NAME, session_id="sess-main")
        self.assertEqual(self.restart_sb().start(), "main-2")
        self.assertIsNone(self.h.started[-1]["resume"])

    def test_a_bare_start_leaves_a_running_orchestrator_alone(self):
        """No prompt, no interruption, and above all no task delivered to somebody
        else's orchestrator — the new one is where the work goes."""
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.h.list_agents = lambda: [HAgent(name=MAIN_NAME, pane_id="w1:p1")]
        second = self.restart_sb().start(task="merge PR 41")
        self.assertEqual(store.unread_for(self.db, MAIN_NAME), [])
        self.assertEqual(store.get_agent(self.db, second)["task"], "merge PR 41")

    # -- "nobody has asked this one for anything yet" ---------------------
    #
    # A bare `sb start` mints an orchestrator whose only instruction is to wait, and every
    # bare start does it. The row says so, so the readouts can stop calling it STALLED.

    def test_a_bare_start_records_that_nothing_has_been_asked_of_it(self):
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        name = self.b.start()
        self.assertEqual(store.get_agent(self.db, name)["awaiting_task"], 1)

    def test_a_start_with_a_task_records_nothing_of_the_kind(self):
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        name = self.b.start(task="merge PR 41")
        self.assertEqual(store.get_agent(self.db, name)["awaiting_task"], 0)

    def test_the_first_message_clears_it(self):
        """The human types the real instruction into a waiting orchestrator: from that
        moment it is an ordinary agent, and going quiet is drift again."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        name = self.b.start()
        self.b.tell([name], "merge PR 41", me=HUMAN)
        self.assertEqual(store.get_agent(self.db, name)["awaiting_task"], 0)

    def test_a_delegated_worker_given_a_task_is_never_marked_as_waiting(self):
        """A `delegate` that carries real work must produce the ordinary row — a stuck
        worker nobody is warned about is what this flag must not be able to cause. The
        taskless spawn below is the one exception, and it is asked for explicitly."""
        self.b.delegate("fix the parser", role="worker", name="w9", me="orch")
        self.assertEqual(store.get_agent(self.db, "w9")["awaiting_task"], 0)

    # -- the taskless delegate (#145) -------------------------------------
    #
    # A parent whose real context is still coming — "spawn it, I will tell it what to do"
    # — used to have a required task argument and only a topic to put in it, so it passed
    # the topic and the child executed a bare topic label as its instruction.

    def test_a_delegate_with_no_task_spawns_a_child_that_waits(self):
        name = self.b.delegate(role="lead", name="l9", me="orch")
        row = store.get_agent(self.db, name)
        self.assertEqual(row["awaiting_task"], 1)
        self.assertIn("Await further instructions", row["task"])
        # And the placeholder is what was actually delivered to the pane, not just what
        # the row says: a child told nothing at all would sit on an empty prompt.
        self.assertIn("Await further instructions", self.h.prompts[-1][1])

    def test_a_blank_task_is_the_same_as_no_task(self):
        """Whitespace is what an agent produces when it means "nothing yet" and is trying
        to satisfy a required argument. It must not become the child's instruction."""
        name = self.b.delegate("   ", role="worker", name="w8", me="orch")
        self.assertEqual(store.get_agent(self.db, name)["awaiting_task"], 1)

    def test_rewording_the_delegate_placeholder_does_not_strand_the_flag(self):
        """Same rule as the orchestrator's placeholder above: the flag comes from whether
        a task was passed, never from comparing the text back, so a repo may reword it."""
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "prompts.toml").write_text(
            '[spawn]\ndelegate_task = "Sit tight."\n')
        b = Broker(self.db, self.h, repo=self.repo)
        b.focus = lambda *a, **k: None
        name = b.delegate(role="worker", name="w7", me="orch")
        row = store.get_agent(self.db, name)
        self.assertEqual(row["task"], "Sit tight.")
        self.assertEqual(row["awaiting_task"], 1)

    def test_the_cli_accepts_a_delegate_with_no_task_at_all(self):
        """The argument is optional at the parser too, and the validator lets None past —
        without both, the mechanism above is unreachable from the command an agent types.
        """
        from switchboard.cli import build_parser, _validate
        args = build_parser().parse_args(["delegate", "--role", "lead", "--name", "x"])
        self.assertIsNone(args.task)
        _validate(args)
        self.assertIsNone(args.task)

    def test_rewording_the_placeholder_prompt_does_not_strand_the_flag(self):
        """Nothing compares the placeholder's TEXT — the flag comes from whether a task
        was passed at all. A copy of the string, or a comparison against it, would go
        stale the moment a repo reworded the prompt, and go stale silently: the
        orchestrator would read STALLED for the rest of its life and nothing would say why.
        """
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "prompts.toml").write_text(
            '[spawn]\nstart_task = "Hold on, I am still typing."\n')
        b = Broker(self.db, self.h, repo=self.repo)
        b.focus = lambda *a, **k: None
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        name = b.start()
        row = store.get_agent(self.db, name)
        self.assertEqual(row["task"], "Hold on, I am still typing.")   # the repo's words
        self.assertEqual(row["awaiting_task"], 1)                      # and the flag holds

    def test_a_waiting_orchestrator_is_not_stalled_but_a_told_one_is(self):
        """End to end, through the readout that was getting it wrong."""
        from switchboard import status
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        name = self.b.start()
        idle = FakeHerdrAPI()
        idle.states_by_name = {name: "idle"}
        # Read a moment on, past `status.STALLED_FLOOR`: the flag being tested here is the
        # placeholder task, and a row read in the second it was written is excused by the
        # floor whatever the placeholder says.
        by_name = lambda: {a.name: a for a in status.collect(
            self.db, idle, now=store.now() + int(status.STALLED_FLOOR) + 1).agents}
        self.assertFalse(by_name()[name].stalled)
        self.b.tell([name], "merge PR 41", me=HUMAN)
        self.assertTrue(by_name()[name].stalled)

    def test_explicit_name_creates_a_distinct_orchestrator(self):
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.assertEqual(self.b.start(name="triage"), "triage")

    # -- start --name: a name is a place, not a session --------------------

    def test_naming_a_closed_orchestrator_opens_a_fresh_one(self):
        """A top-level name is somewhere a human comes back to, and the session that
        stood there has ended — so typing it opens a new one, not the old one again.

        `sb restore <name>` is the way back, and it is now the only one."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        store.update_agent(self.db, MAIN_NAME, session_id="sess-old")
        self.assertEqual(self.restart_sb().start(name=MAIN_NAME), MAIN_NAME)
        self.assertIsNone(self.h.started[-1]["resume"])          # a session, not a resume
        # The row under the name is the new agent's, not the one that ended.
        self.assertNotEqual(store.get_agent(self.db, MAIN_NAME)["session_id"], "sess-old")

    def test_reopening_a_name_does_not_hand_over_the_dead_agent_mail(self):
        """`unread_for` keys on the name alone, so a fresh session would otherwise open
        its first inbox onto instructions addressed to the agent it replaced."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        store.update_agent(self.db, MAIN_NAME, session_id="sess-old")
        store.put_message(self.db, from_agent="child", to_agent=MAIN_NAME,
                          kind="tell", body="the old summary")
        self.restart_sb().start(name=MAIN_NAME)
        self.assertEqual(store.unread_for(self.db, MAIN_NAME), [])

    def test_naming_a_running_orchestrator_hands_it_the_task(self):
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        self.b.start()
        self.h.list_agents = lambda: [HAgent(name=MAIN_NAME, pane_id="w1:p1")]
        before = len(self.h.started)
        self.restart_sb().start(name=MAIN_NAME, task="merge PR 41")
        self.assertEqual(len(self.h.started), before)          # joined, not spawned over
        self.assertEqual(store.unread_for(self.db, MAIN_NAME)[-1]["body"], "merge PR 41")

    # -- what "already running" is allowed to mean --------------------------
    #
    # Nothing branches on this any more; it is what `sb start` tells the human so they
    # can get back to the orchestrators it is no longer reusing for them. A wrong answer
    # costs them the way back, which is why it still has these tests.

    def _dead_top(self, name, state="done"):
        """A top that ended and said so.

        `is_top=True` is what `_top` stamps and what `running_tops` now reads, so a
        fixture that set only the role was modelling a top by the one property of it that
        a rename can change — which is how a role rename made two live tops invisible.
        MAIN is a ROLE and MAIN_NAME is only the default NAME of the top-level one; the
        stamp is neither.
        """
        store.create_agent(self.db, name=name, role=MAIN, pane_id=f"w1:{name}",
                           is_top=True)
        store.set_state(self.db, name, state)

    def test_finished_orchestrators_are_not_already_running(self):
        """The bug: five ended orchestrators announced as live, with only one up.

        The store keeps every root ever created, so the unfiltered query is a history.
        """
        from switchboard.herdr import Agent as HAgent
        self.h.focus = lambda n: None
        for i, name in enumerate([MAIN_NAME, "main-2", "main-3", "main-4"]):
            self._dead_top(name, "failed" if i == 2 else "done")
        store.create_agent(self.db, name="main-5", role=MAIN, pane_id="w1:p5",
                           is_top=True)
        self.h.list_agents = lambda: [HAgent(name="main-5", pane_id="w1:p5")]

        self.assertEqual(self.b.running_tops(), ["main-5"])

    def test_an_orchestrator_herdr_has_never_heard_of_is_not_running(self):
        """Nothing writes a row back on an abnormal death — a crash, a pane closed from
        the outside, a herdr restart — so `working` alone proves nothing."""
        self.h.focus = lambda n: None
        store.create_agent(self.db, name=MAIN_NAME, role=MAIN, pane_id="w1:p1",
                           is_top=True)
        self.h.list_agents = lambda: []
        self.assertEqual(self.b.running_tops(), [])

    def test_an_unreachable_herdr_leaves_the_list_alone(self):
        """Fails OPEN: herdr being down proves nothing about who is working."""
        self.h.focus = lambda n: None
        store.create_agent(self.db, name=MAIN_NAME, role=MAIN, pane_id="w1:p1",
                           is_top=True)

        def down():
            raise HerdrError("no_server", "connection refused")
        self.h.list_agents = down
        self.assertEqual(self.b.running_tops(), [MAIN_NAME])

    def test_the_name_slots_of_dead_orchestrators_stay_taken(self):
        """Free means never used, not merely not-running: two agents with two unrelated
        histories must never be filed under one name."""
        self.h.focus = lambda n: None
        self.h.list_agents = lambda: []
        for name in (MAIN_NAME, "main-2"):
            self._dead_top(name)
        self.assertEqual(self.b.start(), "main-3")

    # -- a spawning agent is not a husk -------------------------------------
    #
    # All of these are `_top` reached BY NAME, which is the only way an existing row is
    # reached at all now. The shapes it has to tell apart are unchanged.

    def _sessionless_top(self, name=MAIN_NAME, pane="w1:p1"):
        """A live orchestrator that has not run an `sb` command of its own yet.

        The normal shape, not an exotic one: herdr's `agent list` carries no session id,
        so `_claim_session` is the only writer of the column and it needs the agent
        itself to call `sb`. Backdated well past SPAWN_GRACE, because this is the steady
        state until that happens and not a spawn-window race.
        """
        store.create_agent(self.db, name=name, role=MAIN, pane_id=pane)
        self.db.execute("UPDATE agents SET created_at=? WHERE name=?",
                        (store.now() - int(status.SPAWN_GRACE) - 100, name))
        self.db.commit()
        return store.get_agent(self.db, name)

    def test_start_does_not_delete_an_agent_herdr_has_not_listed_yet(self):
        """The harm is the DELETE, so assert the row, not the return value.

        No herdr error is needed to get here: herdr answers normally and simply does not
        list the name for the whole of `start_agent`'s 282 s retry window. `sb start`
        read a pane with no session as a husk and dropped the row — session id, pane and
        parentage with it, so `restore` had nothing left and `whoami` called the still
        running agent HUMAN.
        """
        self.h.focus = lambda n: None
        before = self._sessionless_top()
        self.h.list_agents = lambda: []          # herdr is up; this name just is not in it
        self.restart_sb().start(name=MAIN_NAME)

        after = store.get_agent(self.db, MAIN_NAME)
        self.assertIsNotNone(after)
        self.assertEqual(after["pane_id"], before["pane_id"])
        self.assertEqual(after["created_at"], before["created_at"])   # the row, not a new one
        self.assertEqual(self.h.started, [])     # and nothing was spawned over the top of it

    def test_start_hands_its_task_to_the_agent_it_cannot_see(self):
        """Same name means the same agent: join it and give it the work.

        `_spawn_lead` already treats this shape as "a claim somebody made moments ago and
        is still spawning into"; `_top` cited that rule and did the opposite.
        """
        self.h.focus = lambda n: None
        self._sessionless_top()
        self.h.list_agents = lambda: []
        self.assertEqual(self.restart_sb().start(name=MAIN_NAME, task="merge PR 41"),
                         MAIN_NAME)
        self.assertIsNotNone(store.get_agent(self.db, MAIN_NAME))
        self.assertEqual(store.unread_for(self.db, MAIN_NAME)[-1]["body"], "merge PR 41")

    def test_an_unreachable_herdr_does_not_resume_a_live_orchestrator(self):
        """Doubt about a named orchestrator resolves the reversible way.

        `sb start --name` asks `_alive_or_unknown`, which fails OPEN. `_alive` fails
        CLOSED, and `_top` asking it instead resumed a live agent on nothing more than an
        unreachable herdr — a second pane on a live session, which nothing undoes.
        """
        self.h.focus = lambda n: None
        store.create_agent(self.db, name=MAIN_NAME, role=MAIN, pane_id="w1:p1",
                           session_id="sess-main")
        self.h.list_error = HerdrError("no_server", "connection refused")
        self.assertEqual(self.restart_sb().start(name=MAIN_NAME), MAIN_NAME)
        self.assertEqual(self.h.started, [])
        self.assertIsNotNone(store.get_agent(self.db, MAIN_NAME))

    def test_start_still_replaces_a_row_that_never_reached_a_pane(self):
        """The husk branch survives the narrowing: no pane AND no session is still one."""
        self.h.focus = lambda n: None
        store.create_agent(self.db, name=MAIN_NAME, role=MAIN)
        self.h.list_agents = lambda: []
        self.assertEqual(self.restart_sb().start(name=MAIN_NAME), MAIN_NAME)
        self.assertEqual(self.h.started[-1]["name"], MAIN_NAME)

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
        self.b.delegate("t", topic="t", role="worker", me="orch")
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
            self.b.delegate("t", topic="t", role="worker", me="orch")
        self.assertIn("NEW PROTOCOL v2", self.h.started[-1]["prompts"])

    def test_a_repo_can_replace_the_protocol_and_it_reaches_the_spawn(self):
        """The config layer, end to end: a file in this repo, a flag on this spawn.

        Wholesale, not merged — see config.protocol. A protocol assembled from a shipped
        half and a repo half is a protocol nobody can read.
        """
        from switchboard.broker import PROTOCOL_LINE
        (self.repo / ".switchboard").mkdir(exist_ok=True)
        (self.repo / ".switchboard" / "protocol.md").write_text("# ours\n\nSAY LESS.\n")
        Broker(self.db, self.h, repo=self.repo).delegate(
            "t", topic="t", role="worker", me="orch")
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
        Broker(self.db, self.h, repo=self.repo).delegate(
            "t", topic="t", role="worker", me="orch")
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

    # -- the reconciler (3.5) ---------------------------------------------

    def _stalled_fleet(self):
        """Four agents, one of each kind the reconciler has to tell apart. herdr says all
        four are idle; what separates them is the store."""
        for name, kw in (("quiet", {}), ("stuck", {}), ("finished", {}),
                         ("waiting", {"awaiting_task": True})):
            # `session_id` is what says each of these has taken a turn at all: a
            # session-less row this young has not started yet and is held off the stalled
            # list entirely (`status.STALL_GRACE`), which would make this fleet agree for
            # the wrong reason.
            store.create_agent(self.db, name=name, role="worker", session_id=f"s-{name}",
                               pane_id=f"w1:p{len(self.h.states_by_name)}", **kw)
            self.h.states_by_name[name] = "idle"
        store.set_state(self.db, "stuck", "blocked")
        store.set_state(self.db, "finished", "done")
        # And old enough for the idleness to MEAN something. `status.STALLED_FLOOR` is the
        # floor under every stall, so a fleet built in this second is a fleet of agents
        # that have just this moment ended a turn — excused, unpingable, and agreeing with
        # every assertion below for a reason that has nothing to do with the reconciler.
        self.db.execute("UPDATE agents SET created_at = created_at - ?",
                        (int(status.STALLED_FLOOR) + 1,))
        self.db.commit()

    def test_only_an_agent_that_went_quiet_is_pinged(self):
        """T1. The turn ended without `sb done` or `sb block` — the one case DESIGN-TRUTH
        names — and the ping goes to the agent itself, never to a parent.

        The other three are the exemptions: a blocked agent is waiting on a person, a done
        one reported, and one still holding its placeholder task was told to wait.
        """
        self._stalled_fleet()
        self.assertEqual(self.b.reconcile(), ["quiet"])
        [(who, text)] = self.h.prompts
        self.assertEqual(who, "quiet")
        self.assertIn("sb done", text)
        self.assertIn("sb block", text)

    def test_a_parent_with_a_live_child_is_left_alone(self):
        """T1, second half. The stop hook exempts it deliberately — the protocol tells a
        delegating parent to end its turn and wait for the poke — so pinging it here would
        push it to report over work still running."""
        store.create_agent(self.db, name="lead", role="lead", pane_id="w1:p1",
                           session_id="s-lead")   # past its spawn: the exemption is what
        store.create_agent(self.db, name="kid", role="worker", parent="lead",
                           pane_id="w1:p2")       # has to do the work here, not the grace
        self.h.states_by_name = {"lead": "idle", "kid": "working"}
        self.assertEqual(self.b.reconcile(), [])
        self.assertEqual(self.h.prompts, [])

    def test_a_freshly_spawned_agent_is_not_pinged_inside_its_own_spawn_window(self):
        """The defect the integration found: a nudge that is false at the moment it lands.

        The agent was pinged two seconds after its `delegate` event — herdr had not seen
        its first turn start, so it
        read idle, and the ping told it its turn had ended. Nothing new is asked of the
        reconciler here: `status` no longer calls that a stall (`STALL_GRACE`), and this
        pins that the acting half agrees.
        """
        store.create_agent(self.db, name="fresh", role="worker", task="do the thing",
                           pane_id="w1:p1")            # no session id: it has not run `sb`
        self.h.states_by_name["fresh"] = "idle"
        self.assertEqual(self.b.reconcile(), [])
        self.assertEqual(self.h.prompts, [])

        # The same agent, once the window has passed and it still has not said anything.
        self.db.execute("UPDATE agents SET created_at=created_at-? WHERE name='fresh'",
                        (int(status.STALL_GRACE) + 1,))
        self.db.commit()
        self.assertEqual(self.restart_sb().reconcile(), ["fresh"])

    def test_a_stall_is_pinged_once_and_not_every_cycle(self):
        """T2. A reconciler that nags every cycle is worse than none.

        A second ping needs the agent to have DONE something since the first — it woke,
        acted, and stalled again — and `REPING_GAP` underneath that, for the agent that
        wakes on the ping, runs one `sb` command and stops again.
        """
        self._stalled_fleet()
        self.assertEqual(self.b.reconcile(), ["quiet"])
        self.assertEqual(self.restart_sb().reconcile(), [])        # same stall, again
        self.assertEqual(len(self.h.prompts), 1)

        # It woke and did something — but inside the gap, so still not a second ping. Aged
        # past `status.STALLED_FLOOR` so the refusal is the gap's and not the floor's: an
        # agent that acted a moment ago is excused anyway, and would agree here for a
        # reason this test is not about.
        store.log_event(self.db, kind="inbox", agent="quiet")
        self.db.execute("UPDATE events SET created_at=created_at-? WHERE kind='inbox'",
                        (int(status.STALLED_FLOOR) + 1,))
        self.db.commit()
        self.assertEqual(self.restart_sb().reconcile(), [])

        # ...and once the gap has lapsed, with that activity behind it, it is pinged again.
        self.db.execute("UPDATE events SET created_at=created_at-? "
                        "WHERE kind='reconcile_ping'", (broker_mod.REPING_GAP + 1,))
        self.db.commit()
        self.assertEqual(self.restart_sb().reconcile(), ["quiet"])
        self.assertEqual(len(self.h.prompts), 2)



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
        # With a worktree of its own (`branch`), so the fork rule leaves the child in the
        # parent's space and placement — this class's whole subject — is what decides
        # where it lands. A parent without one forks, and a fork that cannot happen now
        # refuses the spawn outright (`ForkFailed`), which is `test_workspace`'s subject.
        kw.setdefault("branch", "main")
        store.create_agent(self.db, name="parent", role="lead", workspace="main",
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
            kw.setdefault("role", "worker")
            name = self.b.delegate("t", topic="t", me="parent", **kw)
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
        _, child = self._spawn(role="lead")
        self.derived.clear()
        self.b.delegate("t", topic="t", role="worker", me=child)
        self.assertEqual(self.h.tabs[-1], "wA")
        self.assertEqual(self.derived, [])

    def test_restore_brings_an_agent_back_to_its_recorded_workspace(self):
        """Same ambiguity, same answer: the name lookup would put it somewhere else."""
        self._parent(workspace_id="wA", session_id="sess-parent")
        self.b._workspace_id = lambda name: "wB"
        self.b.restore("parent")
        self.assertEqual(self.h.tabs[-1], "wA")

    # -- ids do not survive a herdr restart -------------------------------

    def _workspace_gone(self):
        """herdr's answer for a recorded id whose workspace no longer exists."""
        real = self.h.create_tab

        def create_tab(*, workspace=None, **kw):
            if workspace == "wA":
                raise HerdrError("workspace_not_found", f"workspace {workspace} not found")
            return real(workspace=workspace, **kw)

        self.h.create_tab = create_tab

    def test_a_vanished_workspace_costs_the_placement_not_the_spawn(self):
        """Ids are per herdr RUN. After a restart the store still names wG, and
        `tab create --workspace wG` fails — which used to kill `sb start` entirely."""
        self._parent(workspace_id="wA")
        self._workspace_gone()
        tab, child = self._spawn()
        self.assertIsNone(tab)                                  # a plain tab, wherever
        self.assertIsNotNone(store.get_agent(self.db, child))   # but it did spawn

    def test_a_dead_id_is_forgotten_by_every_row_holding_it(self):
        """One failed call, not one per spawn forever after."""
        self._parent(workspace_id="wA")
        store.create_agent(self.db, name="sibling", role="worker", workspace="main",
                           cwd=str(self.repo), pane_id="p-sib", workspace_id="wA")
        self._workspace_gone()
        self._spawn()
        self.assertIsNone(store.get_agent(self.db, "parent")["workspace_id"])
        self.assertIsNone(store.get_agent(self.db, "sibling")["workspace_id"])

    def test_any_other_herdr_failure_still_raises(self):
        """Only a missing workspace is survivable; a dead herdr is not something to
        paper over with a tab that will not be created either."""
        self._parent(workspace_id="wA")

        def create_tab(*, workspace=None, **kw):
            raise HerdrError("connection_refused", "no herdr")

        self.h.create_tab = create_tab
        with self.assertRaises(HerdrError):
            self._spawn()

    def test_restore_survives_a_vanished_workspace_too(self):
        """The path `sb start` actually took: restore a top-level orchestrator whose
        recorded workspace died with the previous herdr.

        It still costs the placement rather than the restore — and the placement is no
        longer simply lost: see the test below, which is why the tab here is the
        name-resolved one and not None.
        """
        self._parent(workspace_id="wA", session_id="sess-parent")
        self._workspace_gone()
        self.b.restore("parent")
        self.assertEqual(store.get_agent(self.db, "parent")["state"], "working")

    def test_restore_after_a_dead_workspace_id_lands_back_in_the_named_space(self):
        """The gap this closes. herdr hands ids out per RUN, so after a restart every
        recorded `workspace_id` 404s — and restore used to fall all the way through to a
        bare tab wherever herdr had focus, even though the space's NAME was on the row the
        whole time. "Restored into the space it came from" was not true of any agent
        restored after a restart.
        """
        self._parent(workspace_id="wA", session_id="sess-parent")
        self._workspace_gone()                 # wA is dead; the name still resolves
        self.b.restore("parent")
        self.assertEqual(self.h.tabs[-1], "w-derived")
        self.assertEqual(self.derived, ["main"])   # resolved by NAME, once

    def test_a_restore_that_re_resolves_leaves_no_empty_pane_behind(self):
        """The first attempt opens a bare tab before herdr disowns the id. It is ours, so
        it is closed rather than left as one empty shell per dead workspace."""
        self._parent(workspace_id="wA", session_id="sess-parent")
        self._workspace_gone()
        self.b.restore("parent")
        self.assertEqual(len(self.h.closed), 1)

    def test_a_space_that_is_genuinely_gone_still_degrades_to_a_bare_tab(self):
        """Re-resolving is a second guess, not a new condition of the restore: a name that
        resolves to nothing keeps today's behaviour rather than refusing."""
        self._parent(workspace_id="wA", session_id="sess-parent")
        self._workspace_gone()
        self.b._workspace_id = lambda name: ""
        self.b.restore("parent")
        self.assertIsNone(self.h.tabs[-1])
        self.assertEqual(store.get_agent(self.db, "parent")["state"], "working")

    # -- and the spawn that detected it does not re-plant it ---------------
    #
    # The clear above is store-wide, and both spawn paths used to write the id they were
    # holding BEFORE the call straight back onto the new row. So the one spawn that proved
    # the id dead was also the one that resurrected it, and every child inherited it from
    # there via tier 1 — the poisoning `restore` never had, because it rewrites the pane
    # and not the workspace.

    def test_the_spawn_that_purges_a_dead_id_does_not_record_it(self):
        self._parent(workspace_id="wA")
        self._workspace_gone()
        _, child = self._spawn(env=None)
        self.assertIsNone(store.get_agent(self.db, child)["workspace_id"])

    def test_the_dead_id_is_dropped_from_this_processs_cache_too(self):
        """The store is cleared but `_ws_ids` was not, so a second lookup of the same name
        within one invocation handed the dead id straight back out."""
        self.b._workspace_id = Broker._workspace_id.__get__(self.b)   # the real one
        self.b._ws_ids["main"] = "wA"
        self._parent(workspace_id="wA")
        self._workspace_gone()
        self._spawn(env=None)
        self.assertNotIn("main", self.b._ws_ids)

    # -- a guess is not a fact --------------------------------------------

    def test_a_name_derived_guess_places_the_tab_but_is_never_recorded(self):
        """Tier 4 asks herdr which workspace holds a checkout — a one-to-many lookup with
        nothing to validate the answer. Written down, it becomes indistinguishable from
        the three tiers above it, and every later child inherits it as fact."""
        self._parent()
        self.h.get_agent = lambda n: None
        tab, child = self._spawn(env=None)
        self.assertEqual(tab, "w-derived")                        # still aims the tab
        self.assertIsNone(store.get_agent(self.db, child)["workspace_id"])

class SbPinTest(unittest.TestCase):
    """A spawned agent must run the `sb` in its OWN checkout.

    `sb` on PATH is one symlink per machine into the main checkout, and `bin/sb` decides
    what to import from its own real path — so before this, every agent in every worktree
    ran the main checkout's code whatever branch it had out. A whole phase of merged fixes
    was acceptance-tested against a build that did not contain them, and nothing said so,
    because the wrong build still answers every command.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "checkout"
        self.repo.mkdir()
        # Resolved, because that is what the pin names: `worktree_root` asks git, which
        # answers with the real path (`/private/var/...` on macOS, not `/var/...`).
        self.repo = self.repo.resolve()
        for argv in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *argv], cwd=self.repo, check=True,
                           capture_output=True)
        self.bin = self.repo / "bin"
        self.bin.mkdir()
        sb = self.bin / "sb"
        sb.write_text("#!/bin/sh\n")
        sb.chmod(0o755)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = PinningHerdr()
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _spawn(self, **kw):
        # The board pane is opened with the same `pane run` the pin uses, and it opens
        # for every spawn now, so this class reads the FIRST of those calls — the pin,
        # which happens before the agent is started at all.
        return self.b.delegate("t", topic="t", role="worker", me=HUMAN, cwd=str(self.repo),
                               workspace="ws", **kw)

    # -- the pin ---------------------------------------------------------

    def test_the_pane_gets_its_own_checkouts_bin_at_the_front_of_path(self):
        self._spawn()
        pane, text = self.h.pane_prompts[0]
        self.assertIn(f'export PATH={self.bin}:"$PATH"', text)

    def test_it_is_pinned_before_the_agent_starts(self):
        """`agent start` runs the provider CLI in that same shell, so the export has to be
        in it already — afterwards is a shell the agent never sees."""
        self._spawn()
        self.assertEqual(self.h.order[:2], ["pin", "start"])

    def test_the_pin_is_confirmed_not_assumed(self):
        """`pane run` is accepted whether or not a shell was there to take it, and the
        failure it hides is exactly the silent wrong-build one."""
        self._spawn()
        pane, marker, _ = self.h.waits[0]
        self.assertEqual(marker, f"sb={self.bin}/sb")

    def test_the_marker_cannot_be_matched_off_the_echoed_command(self):
        """The typed line is echoed into the same pane, so a marker that appears in it
        would confirm itself. It names the resolved binary; the command does not."""
        self._spawn()
        _, text = self.h.pane_prompts[0]
        self.assertNotIn(f"sb={self.bin}/sb", text)

    # -- refusing --------------------------------------------------------

    def test_a_pane_that_never_confirms_costs_the_spawn(self):
        """Starting anyway is what the whole fix exists to stop: the agent comes up, works
        perfectly, and is running somebody else's code."""
        self.h.confirms = False
        with self.assertRaises(SbUnpinned):
            self._spawn()
        self.assertEqual(self.h.started, [])

    def test_a_refusal_leaves_no_row_and_no_held_name(self):
        """Pinned before the claim, so a refusal costs nothing a later attempt has to
        step over — and the wait stays outside the window SPAWN_GRACE covers."""
        self.h.confirms = False
        with self.assertRaises(SbUnpinned):
            self._spawn()
        self.assertIsNone(store.get_agent(self.db, "worker-1"))

    def test_it_is_retried_before_it_is_refused(self):
        """The one failure worth retrying is a shell that had not reached its prompt."""
        self.h.confirms_after = 1
        with mock.patch("switchboard.broker.time.sleep"):
            name = self._spawn()
        self.assertEqual(len(self.h.waits), 2)
        self.assertEqual(self.h.started[0]["name"], name)

    # -- leaving everything else alone -----------------------------------

    def test_a_checkout_without_its_own_sb_is_left_on_the_installed_build(self):
        """An agent sent into some other project has only one `sb` it could mean, and
        touching PATH there would be a claim about a repo we know nothing about.

        The pane is still made to answer first — that half is not about `sb` at all (see
        the next test) — but nothing is exported into it."""
        (self.bin / "sb").unlink()
        self._spawn()
        _, text = self.h.pane_prompts[0]
        self.assertNotIn("PATH", text)

    def test_a_pane_in_any_other_repo_still_has_to_answer_before_the_spawn(self):
        """The 12KB command line `agent start` types is only safe once the shell is
        reading in raw mode; before that the tty keeps 1024 bytes and drops the rest,
        which cuts the system prompt mid-quote and leaves the shell in a parse error.
        So a pane that will not answer costs the spawn here too, exactly as an unpinnable
        one does — and the marker cannot be satisfied by the echo of the command."""
        (self.bin / "sb").unlink()
        self.h.confirms = False
        with self.assertRaises(PaneNotReady):
            self._spawn()
        self.assertEqual(self.h.started, [])
        _, typed = self.h.pane_prompts[0]
        _, marker, _ = self.h.waits[0]
        self.assertNotIn(marker, typed)

    def test_a_path_with_a_space_survives(self):
        space = (Path(self.tmp.name) / "two words")
        (space / "bin").mkdir(parents=True)
        space = space.resolve()
        subprocess.run(["git", "init", "-q"], cwd=space, check=True, capture_output=True)
        (space / "bin" / "sb").write_text("#!/bin/sh\n")
        (space / "bin" / "sb").chmod(0o755)
        self.b.delegate("t", topic="t", role="worker", me=HUMAN,
                        cwd=str(space), workspace="ws")
        _, text = self.h.pane_prompts[0]
        self.assertIn(shlex.quote(str(space / "bin")), text)

    # -- restore ---------------------------------------------------------

    def test_a_restored_agent_is_pinned_too(self):
        """It comes back into the same checkout, so it would otherwise come back on the
        installed build — a restore is a spawn for every purpose this cares about."""
        store.create_agent(self.db, name="w", role="worker", cwd=str(self.repo),
                           session_id="sess-w", pane_id="old")
        store.set_state(self.db, "w", "done")
        self.b.restore("w")
        self.assertEqual(self.h.order, ["pin", "start"])

    def test_a_restore_that_cannot_be_pinned_closes_its_own_tab(self):
        store.create_agent(self.db, name="w", role="worker", cwd=str(self.repo),
                           session_id="sess-w", pane_id="old")
        store.set_state(self.db, "w", "done")
        self.h.confirms = False
        with self.assertRaises(SbUnpinned):
            self.b.restore("w")
        self.assertEqual(len(self.h.closed), 1)          # no empty shell left behind


class ForkBaseTest(unittest.TestCase):
    """What a delegated child is forked FROM.

    It used to be `origin/main`, always, whatever branch the parent was working on — so
    an orchestrator on a branch spawned children that had never seen that branch. The
    consequence was not cosmetic: no branch could be acceptance-tested by the agents its
    own orchestrator spawned, because every one of them ran the code from main.

    A real git repo, because the answer is read out of the checkout: a fake would only
    prove that whatever `_here` returns is passed along.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = (Path(self.tmp.name) / "checkout")
        self.repo.mkdir()
        self.repo = self.repo.resolve()
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        (self.repo / "f.txt").write_text("one\n")
        self._git("add", "f.txt")
        self._git("commit", "-qm", "one")
        # A real `origin`, so the `main` case exercises the fetch rather than
        # `_fork_base`'s no-remote fallback. Bare and local: no network, still a remote.
        origin = Path(self.tmp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                       check=True, capture_output=True)
        self._git("remote", "add", "origin", str(origin))
        self._git("push", "-q", "origin", "main")
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdrAPI()
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _git(self, *argv):
        subprocess.run(["git", *argv], cwd=self.repo, check=True, capture_output=True)

    def _fork(self):
        """Delegate as a parent with no worktree — the one case that forks."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            name = self.b.delegate("t", topic="t", role="worker", me="orch")
        return name, err.getvalue()

    def test_a_child_forks_from_the_branch_its_parent_is_working_on(self):
        """The whole point: work in flight is testable by the fleet doing it."""
        self._git("checkout", "-q", "-b", "fix-thing")
        self._fork()
        self.assertEqual(self.h.bases[-1][1], "fix-thing")

    def test_a_parent_on_main_still_forks_from_origin_main(self):
        """A top orchestrator starting fresh work is a checkout standing on `main`, and
        inheriting `main` means the REMOTE one, fetched — not however stale this
        checkout's local copy is. DESIGN-TRUTH: a workspace forks from `origin/main` by
        default, and that is this case."""
        self._fork()
        self.assertEqual(self.h.bases[-1][1], "origin/main")

    def test_a_detached_head_has_no_branch_to_inherit(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True).stdout.strip()
        self._git("checkout", "-q", head)
        self._fork()
        self.assertEqual(self.h.bases[-1][1], "origin/main")

    def test_a_branch_with_a_slash_in_it_is_not_read_as_a_remote(self):
        """`fix/thing` is one branch, not `thing` in a remote called `fix`. Splitting on
        the slash forked from the wrong ref — or from nothing — and said nothing."""
        self._git("checkout", "-q", "-b", "fix/thing")
        self._fork()
        self.assertEqual(self.h.bases[-1][1], "fix/thing")

    def test_uncommitted_work_does_not_travel_and_the_parent_is_told(self):
        """Inheriting a branch is not inheriting a working tree: a fork starts at a
        commit. The spawn still happens — a dirty checkout is the normal state of one —
        but a parent that believes its child can see those edits is a parent debugging
        the wrong thing."""
        self._git("checkout", "-q", "-b", "fix-thing")
        (self.repo / "f.txt").write_text("two\n")
        name, err = self._fork()
        self.assertIn("did NOT go with it", err)
        self.assertIsNotNone(store.get_agent(self.db, name))       # spawned anyway
        row = self.db.execute(
            "SELECT payload FROM events WHERE kind='fork' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(json.loads(row["payload"])["dirty"], 1)

    def test_a_clean_checkout_says_nothing_about_uncommitted_work(self):
        self._git("checkout", "-q", "-b", "fix-thing")
        _, err = self._fork()
        self.assertIn("forked from 'fix-thing'", err)     # the inheritance is still said
        self.assertNotIn("did NOT go with it", err)

    def test_forking_from_main_is_quiet(self):
        """Nothing changed for it, so there is nothing to report — and a note on every
        spawn is a note nobody reads."""
        (self.repo / "f.txt").write_text("two\n")            # dirty, and still quiet
        _, err = self._fork()
        self.assertEqual(err, "")

    def test_nothing_overrides_the_inherited_base_any_more(self):
        """`--base` went with `sb workspace new`. What a fork starts from is the caller's
        own branch, or `origin/main` when that branch IS main — and there is no longer a
        third answer anyone can ask for."""
        import inspect
        self.assertNotIn("base", inspect.signature(self.b.delegate).parameters)
        self._git("checkout", "-q", "-b", "fix-thing")
        self._git("branch", "release")
        self._fork()
        self.assertEqual(self.h.bases[-1][1], "fix-thing")


class PinningHerdr(FakeHerdrAPI):
    """A herdr that can be asked what a pane printed, and records the order it was used
    in — which is the half of the pin that matters."""

    def __init__(self):
        super().__init__()
        self.waits: list[tuple] = []
        self.order: list[str] = []
        self.confirms = True
        self.confirms_after = 0        # misses this many times first

    def prompt_pane(self, pane, text):
        self.order.append("pin")
        super().prompt_pane(pane, text)

    def wait_output(self, pane_id, match, *, timeout_ms):
        self.waits.append((pane_id, match, timeout_ms))
        if not self.confirms:
            return False
        return len(self.waits) > self.confirms_after

    def start_agent(self, *a, **kw):
        self.order.append("start")
        return super().start_agent(*a, **kw)


class RestoreSweepTest(unittest.TestCase):
    """`sb restore --sweep` — one command for the minutes after a herdr restart.

    A restart takes out whatever panes existed at that moment, across every tree the human
    had running, and leaves the rows behind. What the sweep has to get right is the scope
    (whose agents it may touch), the selection (which rows count as "just went down"), the
    order (parents first), and the report (nothing dropped in silence).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.db = store.connect(path=self.repo / "state.db")
        self.h = FakeHerdrAPI()
        self.b = Broker(self.db, self.h, repo=self.repo)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def _agent(self, name, *, parent=None, is_top=False, session=True, branch="main"):
        store.create_agent(self.db, name=name, role="lead" if is_top else "worker",
                           parent=parent, workspace="main", cwd=str(self.repo),
                           branch=branch, pane_id=f"p-{name}", is_top=is_top,
                           session_id=f"sess-{name}" if session else None)

    def _crashed(self, *names):
        """What `status._record_gone` leaves behind once the absence is confirmed."""
        for n in names:
            store.set_state(self.db, n, status.GONE_STATE)

    def _fresh_broker(self) -> Broker:
        """A second `sb` invocation. Each one is its own short-lived process, and the
        herdr probe is cached per process on purpose — so a second sweep is a second
        Broker, not a second call on this one."""
        return Broker(self.db, self.h, repo=self.repo)

    def test_restore_sweep_run_by_the_human_crosses_every_tree(self):
        """The incident's own shape: a crash cohort spans whatever trees existed, because
        a herdr restart does not respect tree boundaries. Parents come back before their
        children, so a restored child's mail has a live pane to land in — and the row
        nothing can restore is NAMED rather than left out of the list."""
        self._agent("alpha", is_top=True)
        self._agent("alpha-kid", parent="alpha")
        self._agent("bravo", is_top=True)
        self._agent("no-session", parent="bravo", session=False, branch="feature-x")
        self._crashed("alpha", "alpha-kid", "bravo", "no-session")

        r = self.b.restore_sweep(me=HUMAN)

        self.assertEqual(sorted(r), ["alpha", "alpha-kid", "bravo"])
        order = [s["name"] for s in self.h.started]
        self.assertLess(order.index("alpha"), order.index("alpha-kid"))
        self.assertEqual([n for n, _ in r.unrestorable], ["no-session"])
        self.assertIn("feature-x", r.unrestorable[0][1])

    def test_restore_sweep_run_by_an_agent_only_reaches_its_own_tree(self):
        """Deliberately under-scoped, and neither of the two ways it could regress: not a
        silent skip of the other tree, and not a `require_same_tree` exception that kills
        the whole sweep on the first foreign row."""
        self._agent("alpha", is_top=True)
        self._agent("alpha-kid", parent="alpha")
        self._agent("bravo", is_top=True)
        self._crashed("alpha-kid", "bravo")

        r = self.b.restore_sweep(me="alpha")

        self.assertEqual(list(r), ["alpha-kid"])
        self.assertEqual(r.failed, [])
        self.assertEqual(store.get_agent(self.db, "bravo")["state"], status.GONE_STATE)
        self.assertNotIn("bravo", [s["name"] for s in self.h.started])

    def test_restore_sweep_is_a_noop_on_a_second_run(self):
        """Twice is once, and it is once at the SELECTION, not only at the spawn: a
        restored row is `working` with no `ended_at` and no `absent_since`, so the second
        pass does not find it at all. Nothing is spawned a second time."""
        self._agent("alpha", is_top=True)
        self._agent("alpha-kid", parent="alpha")
        self._crashed("alpha", "alpha-kid")
        first = self.b.restore_sweep(me=HUMAN)
        self.assertEqual(sorted(first), ["alpha", "alpha-kid"])
        # herdr lists what it has started.
        self.h.states_by_name = {"alpha": "idle", "alpha-kid": "idle"}

        again = self._fresh_broker().restore_sweep(me=HUMAN)

        self.assertEqual(list(again), [])
        self.assertEqual(again.considered, 0)
        self.assertEqual(len(self.h.started), 2)          # nothing spawned twice

    def test_a_row_herdr_still_has_a_pane_for_is_skipped_not_spawned_twice(self):
        """The other half of idempotency, and the one that survives a rewritten row: a
        `failed` state is `status._record_gone`'s INFERENCE from one `agent list`, and
        that call can be taken against a herdr that hiccupped. If the pane is really still
        there, the sweep says so and leaves it alone — resuming a live agent's session in
        a second pane is the one outcome here that no command undoes."""
        self._agent("alpha", is_top=True)
        self._crashed("alpha")
        self.h.states_by_name = {"alpha": "idle"}         # herdr disagrees with the row

        r = self.b.restore_sweep(me=HUMAN)

        self.assertEqual(list(r), [])
        self.assertEqual(r.skipped, [("alpha", "already running")])
        self.assertEqual(self.h.started, [])

    def test_a_herdr_that_cannot_be_asked_refuses_the_whole_sweep(self):
        """"We cannot tell" is never reported as "nothing to restore" — that reads as
        reassurance in the one moment it is false."""
        self._agent("alpha", is_top=True)
        self._crashed("alpha")
        self.h.list_error = HerdrError("connection_refused", "no herdr")

        with self.assertRaises(ValueError) as e:
            self.b.restore_sweep(me=HUMAN)
        self.assertIn("herdr cannot be reached", str(e.exception))
        self.assertEqual(self.h.started, [])

    def test_the_cohort_is_what_went_down_recently_not_everything_that_ever_failed(self):
        """`sb restore <name>` is how an older crash comes back, one at a time, with a
        person deciding. A row still inside its absence debounce counts too — which half
        of the union a row is in depends only on when the collector last ticked."""
        self._agent("old", is_top=True)
        self._agent("mid-debounce", is_top=True)
        self._crashed("old")
        self.db.execute("UPDATE agents SET ended_at=? WHERE name=?",
                        (store.now() - broker_mod.SWEEP_RECENT - 60, "old"))
        self.db.execute("UPDATE agents SET absent_since=? WHERE name=?",
                        (store.now(), "mid-debounce"))
        self.db.commit()

        r = self.b.restore_sweep(me=HUMAN, dry_run=True)

        self.assertEqual(list(r), ["mid-debounce"])
