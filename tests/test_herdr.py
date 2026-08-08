"""herdr adapter tests.

Uses a fake runner, so these run without herdr installed and without spawning agents.
Every case here encodes something verified against the live binary.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
        Herdr("herdr", runner=fake).start_agent("w1", "w1:p9", prompts=["you are w1"])
        argv = fake.argv()
        self.assertIn("-- --permission-mode auto", argv)   # default is manual: agents stall
        self.assertIn("--append-system-prompt you are w1", argv)

    def test_every_prompt_is_delivered_in_ONE_flag(self):
        """The regression that made every prompt in `defaults/` a fiction.

        `claude` honours only the LAST `--append-system-prompt` it is given and silently
        discards every earlier one. Verified against the real CLI: three flags carrying
        ALPHA, BRAVO and CHARLIE answer "CHARLIE"; one flag carrying all three answers all
        three. switchboard appends protocol, identity, workspace, role and presets in that
        order — so one flag per fragment meant every agent ever spawned received its last
        preset fragment and NOTHING else: no protocol, no role prompt.

        Asserted two ways on purpose. Counting the flags is what actually pins the bug —
        an assertion that each fragment merely APPEARS in argv passes happily while the
        CLI throws all but the last away.
        """
        fake = FakeHerdr(ok({"agent": AGENT_JSON}))
        Herdr("herdr", runner=fake).start_agent(
            "w1", "w1:p9", prompts=["PROTOCOL here", "you are w1", "role text", "a preset"])
        argv = fake.argv()
        self.assertEqual(argv.count("--append-system-prompt"), 1,
                         "one flag per fragment: the CLI keeps only the last one")
        self.assertIn("--append-system-prompt PROTOCOL here you are w1 role text a preset",
                      argv)

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

    def test_detects_installed_integration(self):
        self.assertTrue(self._herdr(self.STATUS_INSTALLED).integration_installed("claude"))

    def test_detects_absent_integration(self):
        self.assertFalse(self._herdr(self.STATUS_ABSENT).integration_installed("claude"))

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

    def test_returns_immediately_when_no_snapshot_given(self):
        fake = FakeHerdr(ok({}), ok({"agents": [AGENT_JSON]}))
        self.assertEqual(Herdr("herdr", runner=fake).wait("w1").name, "w1")

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
        See BUGS.md.
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
        measured at 77% of a core for a six-second wait. See BUGS.md.
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
