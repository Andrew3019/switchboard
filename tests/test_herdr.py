"""herdr adapter tests.

Uses a fake runner, so these run without herdr installed and without spawning agents.
Every case here encodes something verified against the live binary.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import herdr as herdr_mod  # noqa: E402
from switchboard.herdr import (  # noqa: E402
    Agent, Herdr, HerdrError, StateWriteDropped, SOURCE,
)


def ok(result: dict) -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess([], 0, json.dumps({"id": "x", "result": result}), "")


def err(code: str, message: str = "boom") -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(
        [], 0, json.dumps({"id": "x", "error": {"code": code, "message": message}}), ""
    )


class FakeHerdr:
    """Records argv and replays queued responses."""

    def __init__(self, *responses):
        self.calls: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.responses = list(responses)

    def __call__(self, argv, *, timeout=None):
        self.calls.append(list(argv))
        self.timeouts.append(timeout)
        if not self.responses:
            return ok({})
        r = self.responses.pop(0)
        return r() if callable(r) else r

    def argv(self, i=0) -> str:
        return " ".join(self.calls[i])


AGENT_JSON = {
    "name": "w1", "pane_id": "w1:p9", "terminal_id": "term_abc",
    "agent_status": "idle", "state_change_seq": 88,
    "agent_session": {"kind": "id", "source": "herdr:claude", "value": "sess-uuid"},
}


class ParseTest(unittest.TestCase):
    def test_agent_from_json_pulls_session_and_stable_id(self):
        a = Agent.from_json(AGENT_JSON)
        self.assertEqual(a.session_id, "sess-uuid")   # identity, restore, transcripts
        self.assertEqual(a.terminal_id, "term_abc")   # stable handle
        self.assertEqual(a.change_seq, 88)


class ErrorTest(unittest.TestCase):
    def test_error_payload_raises_with_code(self):
        h = Herdr("herdr", runner=FakeHerdr(err("invalid_agent_argument", "nope")))
        with self.assertRaises(HerdrError) as cm:
            h.list_agents()
        self.assertEqual(cm.exception.code, "invalid_agent_argument")

    def test_nonzero_exit_is_never_swallowed(self):
        fake = FakeHerdr(subprocess.CompletedProcess([], 1, "", "connection refused"))
        with self.assertRaises(HerdrError) as cm:
            Herdr("herdr", runner=fake).list_agents()
        self.assertIn("connection refused", cm.exception.message)

    def test_structured_error_on_stderr_keeps_its_code(self):
        """Where herdr puts the envelope is not the caller's problem.

        Verified against the live binary: `tab create --workspace <gone>` exits 1 with
        EMPTY stdout and the error JSON on stderr. Reading stdout only turned that into
        `cli_failure`, so `_tab_for` could not tell a missing workspace from a dead herdr.
        """
        fake = FakeHerdr(subprocess.CompletedProcess(
            [], 1, "",
            '{"error":{"code":"workspace_not_found","message":"workspace wG not found"},'
            '"id":"cli:tab:create"}'))
        with self.assertRaises(HerdrError) as cm:
            Herdr("herdr", runner=fake).create_tab(workspace="wG")
        self.assertEqual(cm.exception.code, "workspace_not_found")
        self.assertIn("wG", cm.exception.message)

    def test_silent_success_is_not_an_error(self):
        # report-agent / release-agent return no output on success
        fake = FakeHerdr(subprocess.CompletedProcess([], 0, "", ""))
        Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "blocked", 1, verify=False)

    def test_every_call_is_logged_even_on_failure(self):
        seen = []
        h = Herdr("herdr", runner=FakeHerdr(err("x")), on_event=lambda **kw: seen.append(kw))
        with self.assertRaises(HerdrError):
            h.list_agents()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "herdr")


class SpawnTest(unittest.TestCase):
    def test_multiline_prompt_rejected_before_calling_herdr(self):
        fake = FakeHerdr()
        h = Herdr("herdr", runner=fake)
        with self.assertRaises(ValueError):
            h.start_agent("w", "w1:p1", prompts=["line one\nline two"])
        self.assertEqual(fake.calls, [])  # fail fast, clearer than herdr's own error

    def test_always_passes_permission_mode_auto(self):
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        try:
            Herdr("herdr", runner=fake).start_agent("w1", "w1:p9", prompts=["you are w1"])
            argv = fake.argv()
            self.assertIn("-- --permission-mode auto", argv)  # default manual: agents stall
            self.assertIn("--append-system-prompt-file", argv)
        finally:
            herdr_mod.forget_prompt_file("w1")

    def test_the_prompt_goes_down_as_a_path_and_the_typed_line_stays_short(self):
        """The MAX_CANON fix, pinned by the only number that decides it.

        `agent start` types this whole command line into the pane's shell, and a shell
        still running its startup files is in canonical mode, where the line discipline
        keeps 1024 bytes and discards the rest. Measured on this machine: 8 of 8 fresh
        panes given a 12,143-byte line delivered exactly 1024 bytes, and 8 of 8 given the
        real prompt as a quoted argument were left on `dquote>` with the quote cut open.
        8 of 8 given a ~300-byte line naming a file delivered all 12,078 bytes intact.

        So the assertion is not "a file is used", it is that the LINE fits — and that the
        prompt is whole in the file, because a command that parses while delivering half a
        protocol is the worse failure of the two.
        """
        prompt = "PROTOCOL. " + "the whole of it, twice over. " * 430   # ~12KB, as shipped
        self.assertGreater(len(prompt), 12000)
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        try:
            Herdr("herdr", runner=fake).start_agent("w1", "w1:p9", prompts=[prompt])
            argv = fake.argv()
            self.assertLess(len(argv), 1024, "the typed line must fit inside MAX_CANON")
            self.assertNotIn(prompt[:80], argv, "the prompt itself must not be typed")
            self.assertEqual(herdr_mod.prompt_file_path("w1").read_text(), prompt)
        finally:
            herdr_mod.forget_prompt_file("w1")

    def test_every_fragment_reaches_the_file_in_order(self):
        """The regression that made every prompt in `defaults/` a fiction.

        `claude` honours only the LAST `--append-system-prompt` it is given and silently
        discards every earlier one. Verified against the real CLI: three flags carrying
        ALPHA, BRAVO and CHARLIE answer "CHARLIE"; one flag carrying all three answers all
        three. switchboard appends protocol, identity, workspace, role and presets in that
        order — so one flag per fragment meant every agent ever spawned received its last
        preset fragment and NOTHING else: no protocol, no role prompt.

        One file cannot repeat the bug the way repeated flags could, but the fragments can
        still be dropped or reordered on the way into it, so the join is asserted whole.
        """
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        try:
            Herdr("herdr", runner=fake).start_agent(
                "w1", "w1:p9",
                prompts=["PROTOCOL here", "you are w1", "role text", "a preset"])
            self.assertEqual(fake.argv().count("--append-system-prompt-file"), 1)
            self.assertEqual(herdr_mod.prompt_file_path("w1").read_text(),
                             "PROTOCOL here you are w1 role text a preset")
        finally:
            herdr_mod.forget_prompt_file("w1")

    def test_a_prompt_file_that_cannot_be_written_fails_the_spawn_loudly(self):
        """No file, no spawn — and herdr is never called.

        The failure this replaces is the silent one: an agent that comes up with no
        protocol looks exactly like an agent that ignored it, and nothing downstream
        checks. `stop_hook_args` may degrade to [] because a missed nudge costs a stalled
        row somebody can see; a missing system prompt costs every rule the agent has.
        """
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "not-a-dir"
            blocked.write_text("")            # its "parent" is a file: mkdir must fail
            with mock.patch.object(herdr_mod, "prompt_file_path",
                                   return_value=blocked / "w1.txt"):
                with self.assertRaises(herdr_mod.PromptFileError):
                    Herdr("herdr", runner=fake).start_agent(
                        "w1", "w1:p9", prompts=["PROTOCOL here"])
        self.assertEqual(fake.calls, [])

    def test_no_prompts_means_no_flag_at_all(self):
        """An empty join would hand the CLI an empty system prompt rather than none."""
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent("w1", "w1:p9", prompts=[])
        self.assertNotIn("--append-system-prompt", fake.argv())

    def test_resume_and_model_args_ride_the_passthrough(self):
        """Model flags arrive pre-resolved and are spliced in verbatim.

        This adapter never builds `--model` itself: it is handed `ModelSpec.cli_args()`,
        so effort (or anything else a tier carries) reaches the CLI unaltered and no tier
        name can ever be mistaken for a model id here.
        """
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent(
            "w1", "w1:p9", model_args=["--model", "sonnet", "--effort", "low"],
            resume="sess-uuid",
        )
        argv = fake.argv()
        self.assertIn("--model sonnet --effort low", argv)
        self.assertIn("--resume sess-uuid", argv)

    def test_no_model_args_means_no_model_flag(self):
        """A tier that defers to the provider CLI must send nothing, not an empty flag."""
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent("w1", "w1:p9")
        self.assertNotIn("--model", fake.argv())

    def test_retries_the_pane_readiness_race(self):
        fake = FakeHerdr(err("not_ready"), err("not_ready"), ok({"agent": AGENT_JSON}))
        h = Herdr("herdr", runner=fake, sleep=lambda _: None)
        a = h.start_agent("w1", "w1:p9", attempts=3)
        self.assertEqual(a.name, "w1")
        self.assertEqual(len(fake.calls), 3)

    def test_gives_up_loudly_rather_than_returning_empty(self):
        fake = FakeHerdr(err("nope"), err("nope"), err("nope"))
        h = Herdr("herdr", runner=fake, sleep=lambda _: None)
        with self.assertRaises(HerdrError) as cm:
            h.start_agent("w1", "w1:p9", attempts=3)
        self.assertEqual(cm.exception.code, "spawn_failed")


class DeliverTest(unittest.TestCase):
    """`deliver` — a prompt that is confirmed to have been taken, or raises.

    The bug it exists for: `agent prompt` reports nothing about whether the text was
    submitted, pasted-and-left-sitting, or lost, so a spawn could hand back a name for an
    agent that never ran. See BUILD-PLAN item 1.1.
    """

    def herdr(self, *, takes_on=1, prompt_errors=(), moves_to="working"):
        """An agent that takes the text on its `takes_on`-th send, and never before.

        `takes_on=0` is the agent that never takes it at all. State is a property of how
        many sends have landed rather than of how many times it has been read, so the poll
        loop can turn over as often as it likes without that being the thing under test.
        `prompt_errors` is consumed one per `agent prompt`; a falsy entry succeeds.

        `moves_to` is what the agent's status becomes when it moves. `working` is a turn
        starting. The other values are the ones a startup dialog produces while eating
        the prompt — a move that is not a turn, and must not read as delivery.
        """
        state = {"sends": 0, "errs": list(prompt_errors)}
        calls: list[list[str]] = []

        def runner(argv, *, timeout=None):
            calls.append(list(argv))
            if argv[1:3] == ["agent", "prompt"]:
                e = state["errs"].pop(0) if state["errs"] else None
                if e:
                    return err(e)
                state["sends"] += 1
                return ok({})
            took = bool(takes_on) and state["sends"] >= takes_on
            return ok({"agents": [dict(AGENT_JSON,
                                       state_change_seq=88 + int(took),
                                       agent_status=moves_to if took else "idle")]})

        return Herdr("herdr", runner=runner, sleep=lambda _: None), calls

    def sends(self, calls):
        return [c for c in calls if c[1:3] == ["agent", "prompt"]]

    def test_a_prompt_the_agent_took_is_sent_once(self):
        """The agent moved: seq 88 before, 89 after. Nothing is re-sent."""
        h, calls = self.herdr(takes_on=1)
        h.deliver("w1", "do the thing")
        self.assertEqual(len(self.sends(calls)), 1)
        self.assertIn("do the thing", self.sends(calls)[0])

    def test_a_prompt_that_never_started_a_turn_is_re_sent(self):
        """Pasted without submitting: herdr took the call and the agent never moved.

        This is the mode that loses agents — `agent prompt` returns success either way,
        so only reading the agent back afterwards can tell them apart.
        """
        h, calls = self.herdr(takes_on=2)
        h.deliver("w1", "task", timeout_ms=1)
        self.assertEqual(len(self.sends(calls)), 2)

    def test_a_task_that_never_lands_raises_instead_of_reporting_success(self):
        h, calls = self.herdr(takes_on=0)
        with self.assertRaises(HerdrError) as cm:
            h.deliver("w1", "task", attempts=3, timeout_ms=1)
        self.assertEqual(cm.exception.code, "not_delivered")
        self.assertIn("w1", cm.exception.message)
        self.assertEqual(len(self.sends(calls)), 3)

    def test_a_refused_prompt_is_retried_and_then_confirmed(self):
        """The other failure mode: the call itself fails, e.g. agent_not_ready."""
        h, calls = self.herdr(takes_on=1, prompt_errors=["agent_not_ready", None])
        h.deliver("w1", "task", timeout_ms=1)
        self.assertEqual(len(self.sends(calls)), 2)

    def test_an_unaskable_herdr_is_not_mistaken_for_a_delivery(self):
        """`agent list` failing proves nothing, so it must not read as confirmation."""
        def runner(argv, *, timeout=None):
            if argv[1:3] == ["agent", "prompt"]:
                return ok({})
            return err("herdr_unavailable")

        h = Herdr("herdr", runner=runner, sleep=lambda _: None)
        with self.assertRaises(HerdrError) as cm:
            h.deliver("w1", "task", attempts=2, timeout_ms=1)
        self.assertEqual(cm.exception.code, "not_delivered")

    def test_a_status_change_that_is_not_a_turn_is_not_a_delivery(self):
        """THE BUG THIS WHOLE PATH EXISTS FOR, in its second form.

        Measured live: `agent start` returns with the pane `interactive_ready` while
        Claude Code is still showing its workspace trust dialog. The prompt types into
        the modal, the text is thrown away, the Enter answers the dialog — and the agent
        flips to `blocked` or `done` within a second. Under the old rule ("the seq
        moved") that was confirmation, and three of four spawns in one cold fan-out were
        reported as delivered having never run.
        """
        for state in ("blocked", "done", "idle"):
            with self.subTest(state=state):
                h, calls = self.herdr(takes_on=1, moves_to=state)
                with self.assertRaises(HerdrError) as cm:
                    h.deliver("w1", "task", attempts=2, timeout_ms=1)
                self.assertEqual(cm.exception.code, "not_delivered")
                self.assertEqual(len(self.sends(calls)), 2)

    def test_the_baseline_is_re_read_before_every_send(self):
        """A stale baseline confirms a new prompt with an old change.

        `before` used to be snapshotted once, ahead of the first attempt. By the third,
        anything that had moved the agent in the intervening minute — including the
        answer to the dialog that ate attempt one — satisfied it.
        """
        h, calls = self.herdr(takes_on=99)
        with self.assertRaises(HerdrError):
            h.deliver("w1", "task", attempts=3, timeout_ms=1)
        lists = [c for c in calls if c[1:3] == ["agent", "list"]]
        sends = [i for i, c in enumerate(calls) if c[1:3] == ["agent", "prompt"]]
        self.assertEqual(len(sends), 3)
        for i in sends:                          # every send is preceded by a fresh read
            self.assertEqual(calls[i - 1][1:3], ["agent", "list"])
        self.assertGreaterEqual(len(lists), 3)


class DeliverProofTest(unittest.TestCase):
    """`proof` — the agent's own record of the text, which herdr cannot fake.

    See `output.task_arrived`. When one is supplied it is the ONLY thing believed: the
    status read it replaces is a reading of the terminal, and the terminal lies during
    startup.

    `working_ms=1` alongside `timeout_ms=1` throughout, for the same reason: these are
    about how many times the text is sent, not about how long anything waits, and the
    stretch these numbers switch off has its own test below.
    """

    def herdr(self, arrives_on, *, status="working"):
        """herdr always says the agent moved; the proof only agrees on send `arrives_on`.

        `arrives_on=0` never arrives — the false-success case, with herdr insisting all
        the way through that the agent is working.
        """
        state = {"sends": 0}
        calls: list[list[str]] = []

        def runner(argv, *, timeout=None):
            calls.append(list(argv))
            if argv[1:3] == ["agent", "prompt"]:
                state["sends"] += 1
                return ok({})
            return ok({"agents": [dict(AGENT_JSON, state_change_seq=88 + state["sends"],
                                       agent_status=status)]})

        def proof(since):
            return bool(arrives_on) and state["sends"] >= arrives_on

        return Herdr("herdr", runner=runner, sleep=lambda _: None), calls, proof

    def sends(self, calls):
        return [c for c in calls if c[1:3] == ["agent", "prompt"]]

    def test_a_task_the_transcript_never_shows_is_not_a_delivery(self):
        h, calls, proof = self.herdr(0)
        with self.assertRaises(HerdrError) as cm:
            h.deliver("w1", "task", attempts=3, timeout_ms=1, working_ms=1, proof=proof)
        self.assertEqual(cm.exception.code, "not_delivered")
        self.assertEqual(len(self.sends(calls)), 3)

    def test_a_task_the_transcript_shows_is_delivered_once(self):
        h, calls, proof = self.herdr(1)
        h.deliver("w1", "task", timeout_ms=1, working_ms=1, proof=proof)
        self.assertEqual(len(self.sends(calls)), 1)

    def test_a_re_send_is_what_makes_a_swallowed_first_prompt_land(self):
        h, calls, proof = self.herdr(2)
        h.deliver("w1", "task", timeout_ms=1, working_ms=1, proof=proof)
        self.assertEqual(len(self.sends(calls)), 2)

    def test_proof_needs_no_state_change_at_all(self):
        """A task can be taken, finished and forgotten between two polls.

        The status read has to allow for that and cannot; the transcript simply has the
        text in it either way.
        """
        h, calls, proof = self.herdr(1, status="idle")
        h.deliver("w1", "task", timeout_ms=1, working_ms=1, proof=proof)
        self.assertEqual(len(self.sends(calls)), 1)

    def late(self, *, status):
        """A proof that only shows up after the send's window has already run out.

        The real thing: Claude Code flushes its transcript when it gets round to it, and
        under a six-way fan-out one was measured 35 s after the task was taken, against a
        20 s window. Nothing about the agent is wrong in that case — only the file is
        late.

        "After the window" is counted in status reads rather than in polls or seconds,
        which is what makes it exact: with a proof in hand herdr is asked exactly twice
        per send — once for the baseline before it, once when the window expires — so a
        proof that waits for the second read is a proof that arrives one moment too late,
        every time this runs.
        """
        state = {"sends": 0, "reads": 0}
        calls: list[list[str]] = []

        def runner(argv, *, timeout=None):
            calls.append(list(argv))
            if argv[1:3] == ["agent", "prompt"]:
                state["sends"] += 1
                return ok({})
            state["reads"] += 1
            return ok({"agents": [dict(AGENT_JSON, state_change_seq=88 + state["sends"],
                                       agent_status=status)]})

        def proof(since):
            return state["reads"] >= 2

        return Herdr("herdr", runner=runner, sleep=lambda _: None), calls, proof

    def test_a_running_turn_buys_a_late_proof_time_to_arrive(self):
        """The false failure this fix is for, in one send.

        The window ran out, the transcript had not been written yet, and the spawn
        reported that a working agent had never taken its task — twice in a 42-agent
        acceptance run, once for an agent that had already reported `done`. herdr saying
        `working` cannot confirm the text arrived, so it does not: it extends the window,
        and the proof itself still has to turn up.
        """
        h, calls, proof = self.late(status="working")
        h.deliver("w1", "task", attempts=1, timeout_ms=1, working_ms=5000, proof=proof)
        self.assertEqual(len(self.sends(calls)), 1)     # no re-send, and no exception

    def test_an_agent_that_is_not_running_gets_no_extra_time(self):
        """The other half, and the one that keeps the guarantee.

        An idle agent with no proof is the case the loud failure exists for: a prompt a
        dialog ate leaves an idle pane and an empty transcript. It waits exactly as long
        as it always did, so a genuinely lost task still fails as fast as it used to.
        """
        h, calls, proof = self.late(status="idle")
        with self.assertRaises(HerdrError) as cm:
            h.deliver("w1", "task", attempts=1, timeout_ms=1, working_ms=5000, proof=proof)
        self.assertEqual(cm.exception.code, "not_delivered")


class TopologyTest(unittest.TestCase):
    def test_uses_tab_not_pane_split(self):
        # verified live shape: the pane id lives under root_pane, not tab
        fake = FakeHerdr(ok({"root_pane": {"pane_id": "w1:pZ"}, "tab": {"pane_count": 1}}))
        pane = Herdr("herdr", runner=fake).create_tab()
        self.assertEqual(pane, "w1:pZ")
        self.assertIn("tab create", fake.argv())      # splits exhaust; tabs do not
        self.assertNotIn("split", fake.argv())

    def test_missing_pane_id_is_an_error_not_an_empty_string(self):
        # The exact shape that silently broke a fan-out during validation.
        h = Herdr("herdr", runner=FakeHerdr(ok({"tab": {"pane_count": 1}})))
        with self.assertRaises(HerdrError) as cm:
            h.create_tab()
        self.assertEqual(cm.exception.code, "no_pane")


class StateTest(unittest.TestCase):
    def test_report_state_includes_agent_and_seq_every_time(self):
        fake = FakeHerdr(ok({}))
        Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "blocked", 7, verify=False)
        argv = fake.argv()
        self.assertIn(f"--source {SOURCE}", argv)
        self.assertIn("--agent w1", argv)     # required on EVERY call, not just the first
        self.assertIn("--seq 7", argv)        # omitting it silently drops the write

    def test_done_is_not_a_herdr_state(self):
        h = Herdr("herdr", runner=FakeHerdr(ok({})))
        with self.assertRaises(ValueError):
            h.report_state("w1:p9", "w1", "done", 1)

    def test_report_session_registers_under_our_source(self):
        # the bundled claude integration must stay uninstalled (it blocks our state
        # writes), so we claim the session ourselves
        fake = FakeHerdr(ok({}))
        Herdr("herdr", runner=fake).report_session("w1:p9", "w1", "sess-uuid", 3)
        argv = fake.argv()
        self.assertIn("report-agent-session", argv)
        self.assertIn(f"--source {SOURCE}", argv)
        self.assertIn("--agent-session-id sess-uuid", argv)

    def test_release_is_authority_only(self):
        fake = FakeHerdr(ok({}))
        Herdr("herdr", runner=fake).release_agent("w1:p9", "w1", 9)
        self.assertIn("release-agent", fake.argv())
        self.assertIn("--agent w1", fake.argv())


class SilentDropTest(unittest.TestCase):
    """The most dangerous herdr behaviour: a write that is accepted and then ignored."""

    def test_readback_catches_a_dropped_write(self):
        stayed_idle = dict(AGENT_JSON, agent_status="idle")
        fake = FakeHerdr(ok({}), ok({"agents": [stayed_idle]}))
        with self.assertRaises(StateWriteDropped) as cm:
            Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "blocked", 7)
        self.assertIn("stale/reused seq", str(cm.exception))

    def test_readback_passes_when_the_write_landed(self):
        landed = dict(AGENT_JSON, agent_status="blocked")
        fake = FakeHerdr(ok({}), ok({"agents": [landed]}))
        Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "blocked", 7)

    def test_derived_done_counts_as_idle(self):
        # herdr shows "done" for an idle, unviewed pane — not a dropped write
        derived = dict(AGENT_JSON, agent_status="done")
        fake = FakeHerdr(ok({}), ok({"agents": [derived]}))
        Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "idle", 7)

    def test_a_vanish_after_a_working_report_is_a_dropped_write(self):
        """`got is None` used to return silently, so a write that landed nowhere read as
        confirmed. Nothing reaches gone from `working` without an intervening idle/done,
        so the agent being unknown here means the write went into a hole."""
        fake = FakeHerdr(ok({}), ok({"agents": []}))
        with self.assertRaises(StateWriteDropped) as cm:
            Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "working", 7)
        self.assertIn("no longer knows", str(cm.exception))

    def test_a_vanish_after_an_idle_report_is_an_ordinary_exit(self):
        """The other half of the pick, and the reason it is not "raise on every vanish":
        `idle` is what an agent sends moments before it disappears, so raising here would
        fire on every ordinary end of a life and dilute the one event that means the
        board has gone stale."""
        fake = FakeHerdr(ok({}), ok({"agents": []}))
        Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "idle", 7)

    def test_verify_can_be_disabled(self):
        fake = FakeHerdr(ok({}))
        Herdr("herdr", runner=fake).report_state("w1:p9", "w1", "blocked", 7, verify=False)
        self.assertEqual(len(fake.calls), 1)   # no read-back call


class IntegrationConflictTest(unittest.TestCase):
    """Regression for finding #20: an installed integration silently kills state writes."""

    STATUS_INSTALLED = "  claude: current (v7) (/Users/x/.claude/hooks/herdr-agent-state.sh)"
    STATUS_ABSENT = "  claude: not installed (/Users/x/.claude/hooks/herdr-agent-state.sh)"

    def _herdr(self, status_line, version="0.8.0"):
        def runner(argv, **_):
            if "--version" in argv:
                return subprocess.CompletedProcess([], 0, f"herdr {version}", "")
            return subprocess.CompletedProcess([], 0, status_line, "")
        return Herdr("herdr", runner=runner)

    def test_check_refuses_to_start_with_conflicting_integration(self):
        with self.assertRaises(HerdrError) as cm:
            self._herdr(self.STATUS_INSTALLED).check()
        self.assertEqual(cm.exception.code, "integration_conflict")
        self.assertIn("integration uninstall claude", cm.exception.message)

    def test_check_passes_when_clean(self):
        self._herdr(self.STATUS_ABSENT).check()


class WaitTest(unittest.TestCase):
    def test_stale_wait_is_retried_until_seq_advances(self):
        """`agent wait` is not turn-scoped: an old transition can satisfy it instantly."""
        stale = dict(AGENT_JSON, state_change_seq=88)
        fresh = dict(AGENT_JSON, state_change_seq=93)
        fake = FakeHerdr(
            ok({}), ok({"agents": [stale]}),   # satisfied by the PREVIOUS turn
            ok({}), ok({"agents": [fresh]}),   # genuinely advanced
        )
        a = Herdr("herdr", runner=fake).wait("w1", since_seq=88)
        self.assertEqual(a.change_seq, 93)

    def test_agent_vanishing_is_an_error(self):
        fake = FakeHerdr(ok({}), ok({"agents": []}))
        with self.assertRaises(HerdrError) as cm:
            Herdr("herdr", runner=fake).wait("w1")
        self.assertEqual(cm.exception.code, "agent_gone")

    def test_until_reaches_herdr_as_one_status(self):
        """herdr 0.8.0: `--until idle,blocked` is refused outright ("invalid agent status")
        and repeating the flag has no defined meaning, so exactly one may be sent.

        This is the test the method never had, which is how the DEFAULT argument of a
        public method stayed unusable — every call failed instantly and nothing waited.
        See `notes/BUGS.md`.
        """
        fake = FakeHerdr(ok({}), ok({"agents": [AGENT_JSON]}))
        Herdr("herdr", runner=fake).wait("w1")
        argv = fake.calls[0]
        self.assertEqual(argv.count("--until"), 1)
        self.assertEqual(argv[argv.index("--until") + 1], "idle")

    def test_a_state_herdr_does_not_have_is_refused_here(self):
        with self.assertRaises(ValueError):
            Herdr("herdr", runner=FakeHerdr()).wait("w1", until="done")

    def test_a_stale_wait_backs_off_instead_of_spinning(self):
        """`agent wait` returns INSTANTLY when the agent is already in the state asked
        for, so the stale-seq retry has to sleep or it pins a core for the whole timeout —
        measured at 77% of a core for a six-second wait. See `notes/BUGS.md`.
        """
        stale = ok({"agents": [dict(AGENT_JSON, state_change_seq=88)]})
        fresh = ok({"agents": [dict(AGENT_JSON, state_change_seq=99)]})
        fake = FakeHerdr(ok({}), stale, ok({}), stale, ok({}), fresh)
        naps: list[float] = []
        h = Herdr("herdr", runner=fake, sleep=naps.append)
        h.wait("w1", since_seq=88)
        # One per rejected answer: two rejections, two naps, and no third.
        self.assertEqual(len(naps), 2)
        self.assertTrue(all(n > 0 for n in naps))

    def test_the_backoff_never_sleeps_past_the_deadline(self):
        """A wait that is nearly out of time must not nap for half a second past it."""
        stale = ok({"agents": [dict(AGENT_JSON, state_change_seq=88)]})

        def runner(argv, **_):
            return ok({}) if argv[1:3] == ["agent", "wait"] else stale

        naps: list[float] = []
        h = Herdr("herdr", runner=runner, sleep=naps.append)
        with self.assertRaises(HerdrError) as cm:
            h.wait("w1", since_seq=88, timeout_ms=1)
        self.assertEqual(cm.exception.code, "wait_timeout")
        # No single nap is longer than the wait had left. (The injected sleep does not
        # actually pass time, so the loop turns over more than once here; what is being
        # pinned is that each nap is clamped, not how many there are.)
        self.assertTrue(naps)
        self.assertLessEqual(max(naps), 0.001)


class ReadTest(unittest.TestCase):
    def test_pane_read_requests_recent_source(self):
        fake = FakeHerdr(subprocess.CompletedProcess([], 0, "output", ""))
        Herdr("herdr", runner=fake).read_pane("w1:p9")
        # without --source recent, an alt-screen agent reads back as an empty prompt frame
        self.assertIn("--source recent", fake.argv())


class WaitOutputTest(unittest.TestCase):
    """The read half of `pane run` — how a caller learns a typed command did anything."""

    def test_a_match_is_yes(self):
        fake = FakeHerdr(ok({"matched": True}))
        self.assertTrue(
            Herdr("herdr", runner=fake).wait_output("w1:p9", "sb=/repo/bin/sb",
                                                    timeout_ms=5000))
        argv = fake.argv()
        self.assertIn("pane wait-output w1:p9", argv)
        self.assertIn("--match sb=/repo/bin/sb", argv)
        # A path is the usual thing matched, and a wrapped line splits one in half.
        self.assertIn("--source recent-unwrapped", argv)
        self.assertIn("--timeout 5000", argv)

    def test_the_deadline_expiring_is_no_not_an_exception(self):
        """herdr reports a miss as an error envelope. Every caller wants a yes/no —
        raising would make "the pane did not answer" indistinguishable from "herdr is
        down", and the caller has to act differently on those."""
        h = Herdr("herdr", runner=FakeHerdr(err("timeout", "no match within 5000ms")))
        self.assertFalse(h.wait_output("w1:p9", "sb=/repo/bin/sb", timeout_ms=5000))

    def test_our_ceiling_leaves_room_for_herdrs_own(self):
        """A call that is *supposed* to block for its timeout must not be killed at ten
        seconds — the same allowance `agent start` and `agent wait` get."""
        fake = FakeHerdr(ok({}))
        Herdr("herdr", runner=fake).wait_output("w1:p9", "x", timeout_ms=5000)
        self.assertGreater(fake.timeouts[0], 5.0)


class SubprocessTimeoutTest(unittest.TestCase):
    """A stuck `herdr` binary must fail, loudly, rather than hang `sb` forever.

    herdr's own `--timeout` bounds only its internal wait for readiness; nothing bounded
    how long our process would wait for the CLI to return at all, which is how one
    `sb delegate` hung until a human killed it from outside.
    """

    def _stuck(self, argv, *, timeout=None):
        raise subprocess.TimeoutExpired(list(argv), timeout or 0)

    def test_a_stuck_binary_becomes_an_error_naming_the_call_and_the_limit(self):
        h = Herdr("herdr", runner=self._stuck)
        with self.assertRaises(HerdrError) as cm:
            h.prompt("w1", "mail")
        self.assertEqual(cm.exception.code, "timeout")
        self.assertIn("agent prompt w1", cm.exception.message)   # what timed out
        self.assertIn("10s", cm.exception.message)               # and its ceiling

    def test_the_timeout_is_logged_like_any_other_call(self):
        seen = []
        h = Herdr("herdr", runner=self._stuck, on_event=lambda **kw: seen.append(kw))
        with self.assertRaises(HerdrError):
            h.list_agents()
        self.assertEqual(seen[0]["argv"], "agent list")
        self.assertIn("timed out", seen[0]["err"])

    def test_a_stuck_pane_read_times_out_too(self):
        with self.assertRaises(HerdrError) as cm:
            Herdr("herdr", runner=self._stuck).read_pane("w1:p9")
        self.assertEqual(cm.exception.code, "timeout")

    def test_ordinary_calls_get_the_flat_ceiling(self):
        fake = FakeHerdr()
        Herdr("herdr", runner=fake).prompt("w1", "mail")
        self.assertEqual(fake.timeouts, [10])

    def test_spawn_is_allowed_its_own_ninety_seconds_plus_margin(self):
        """A flat 10s would kill every spawn: `agent start` is slow on purpose."""
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent("w1", "w1:p9", timeout_ms=90000)
        self.assertEqual(fake.timeouts, [100])       # herdr's 90s deadline + 10s to return
        self.assertIn("--timeout 90000", fake.argv())

    def test_a_wait_is_allowed_the_deadline_it_asked_herdr_for(self):
        fake = FakeHerdr(ok({}), ok({"agents": [AGENT_JSON]}))
        Herdr("herdr", runner=fake).wait("w1", timeout_ms=300000)
        self.assertGreater(fake.timeouts[0], 300)    # the blocking call
        self.assertEqual(fake.timeouts[1], 10)       # the `agent list` after it


if __name__ == "__main__":
    unittest.main()
