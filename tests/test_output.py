"""Output tests — reading another agent's terminal, by name.

The interesting half is the fallback: by the time anyone debugs a child, its pane is
usually already closed, so a reader that only knew about panes would return nothing
exactly when it is asked the real question.

Transcripts are written under a fake HOME so `store.transcript_path` is exercised for
real rather than stubbed — the cwd-slug bucketing is part of what can break.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import output, store  # noqa: E402
from switchboard.herdr import Herdr, HerdrError  # noqa: E402
from switchboard.output import PANE, TRANSCRIPT, UNAVAILABLE, Output  # noqa: E402


class FakePaneReader:
    """Stands in for the herdr adapter: replays one pane read."""

    def __init__(self, text: str = "", *, error: HerdrError | None = None):
        self.text, self.error = text, error
        self.reads: list[tuple[str, int]] = []

    def read_pane(self, pane_id: str, *, lines: int = 40) -> str:
        self.reads.append((pane_id, lines))
        if self.error:
            raise self.error
        return self.text


def entry(role: str, *parts) -> str:
    """One transcript line, in Claude Code's shape."""
    return json.dumps({"type": role, "message": {"role": role, "content": list(parts)}})


def text_part(s: str) -> dict:
    return {"type": "text", "text": s}


class OutputTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.cwd = self.root / "work"
        self.cwd.mkdir(parents=True)
        self.db = store.connect(path=self.root / "state.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def agent(self, name="w1", **fields):
        fields.setdefault("role", "worker")
        return store.create_agent(self.db, name=name, **fields)

    def write_transcript(self, session_id: str, *lines: str) -> Path:
        """Put a transcript exactly where store.transcript_path will look for it."""
        row = store.create_agent(self.db, name="_probe", role="worker",
                                 session_id=session_id, cwd=str(self.cwd))
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            slug = store.transcript_path(row)   # None: the file does not exist yet
        self.assertIsNone(slug)
        import re
        d = self.home / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(self.cwd))
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{session_id}.jsonl"
        p.write_text("".join(l if l.endswith("\n") else l + "\n" for l in lines))
        self.db.execute("DELETE FROM agents WHERE name='_probe'")
        self.db.commit()
        return p

    def read(self, name="w1", herdr=None, **kw) -> Output:
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            return output.read_output(self.db, herdr or FakePaneReader(), name, **kw)


class LivePaneTest(OutputTestBase):
    def test_reads_the_live_pane_by_agent_name(self):
        self.agent(pane_id="w1:p9")
        h = FakePaneReader("Traceback: boom\n")
        out = self.read(herdr=h)
        self.assertEqual(out.source, PANE)
        self.assertIn("boom", out.text)
        self.assertEqual(h.reads, [("w1:p9", 40)])   # name -> pane is the tool's job

    def test_line_count_reaches_herdr(self):
        self.agent(pane_id="w1:p9")
        h = FakePaneReader("x\n")
        self.read(herdr=h, lines=200)
        self.assertEqual(h.reads, [("w1:p9", 200)])

    def test_unknown_agent_is_loud(self):
        with self.assertRaises(KeyError):
            self.read("nobody")

    def test_the_read_is_logged(self):
        self.agent(pane_id="w1:p9")
        self.read(herdr=FakePaneReader("hi\n"))
        kinds = [r["kind"] for r in store.recent_events(self.db, agent="w1")]
        self.assertIn("read_output", kinds)


class ClosedPaneTest(OutputTestBase):
    """The case the feature exists for: the child is gone and nobody knows why."""

    TRANSCRIPT = (
        entry("user", text_part("build the thing")),
        entry("assistant", {"type": "thinking", "thinking": "hmm"},
              {"type": "tool_use", "name": "Bash", "input": {"command": "make"}}),
        entry("user", {"type": "tool_result", "is_error": True,
                       "content": "make: *** No rule to make target"}),
        entry("assistant", text_part("I cannot build this.")),
    )

    def test_falls_back_to_the_transcript_when_the_pane_is_gone(self):
        self.write_transcript("sess-1", *self.TRANSCRIPT)
        self.agent(pane_id="w1:p9", session_id="sess-1", cwd=str(self.cwd))
        h = FakePaneReader(error=HerdrError("pane_not_found", "no such pane"))
        out = self.read(herdr=h)
        self.assertEqual(out.source, TRANSCRIPT)
        self.assertIn("No rule to make target", out.text)
        self.assertIn("pane_not_found", out.detail)   # provenance, never silent

    def test_falls_back_when_the_agent_has_no_pane_at_all(self):
        self.write_transcript("sess-1", *self.TRANSCRIPT)
        self.agent(session_id="sess-1", cwd=str(self.cwd))
        out = self.read(herdr=FakePaneReader("never asked"))
        self.assertEqual(out.source, TRANSCRIPT)
        self.assertIn("no pane recorded", out.detail)

    def test_falls_back_when_the_pane_reads_back_empty(self):
        # An empty pane and a closed one look identical to a caller; both are useless.
        self.write_transcript("sess-1", *self.TRANSCRIPT)
        self.agent(pane_id="w1:p9", session_id="sess-1", cwd=str(self.cwd))
        out = self.read(herdr=FakePaneReader("   \n"))
        self.assertEqual(out.source, TRANSCRIPT)
        self.assertIn("empty", out.detail)

    def test_live_pane_wins_over_the_transcript(self):
        self.write_transcript("sess-1", *self.TRANSCRIPT)
        self.agent(pane_id="w1:p9", session_id="sess-1", cwd=str(self.cwd))
        out = self.read(herdr=FakePaneReader("on screen right now\n"))
        self.assertEqual(out.source, PANE)
        self.assertEqual(out.detail, "")

    def test_nothing_anywhere_says_why(self):
        self.agent(pane_id="w1:p9")                  # no session id => no transcript
        h = FakePaneReader(error=HerdrError("pane_not_found", "gone"))
        out = self.read(herdr=h)
        self.assertEqual(out.source, UNAVAILABLE)
        self.assertFalse(out.found)
        self.assertIn("pane_not_found", out.detail)
        self.assertIn("no transcript", out.detail)

    def test_empty_transcript_is_not_reported_as_output(self):
        self.write_transcript("sess-1", "")
        self.agent(session_id="sess-1", cwd=str(self.cwd))
        out = self.read()
        self.assertEqual(out.source, UNAVAILABLE)
        self.assertIn("nothing readable", out.detail)


class TranscriptRenderTest(OutputTestBase):
    def render(self, *lines, **kw) -> str:
        p = self.write_transcript("sess-r", *lines)
        return output.read_transcript(p, **kw)

    def test_keeps_tool_calls_and_marks_errors(self):
        text = self.render(
            entry("assistant", {"type": "tool_use", "name": "Bash",
                                "input": {"command": "pytest"}}),
            entry("user", {"type": "tool_result", "is_error": True, "content": "exit 1"}),
            entry("user", {"type": "tool_result", "content": "ok"}),
        )
        self.assertIn("[Bash] ", text)
        self.assertIn("pytest", text)
        self.assertIn("[error] exit 1", text)
        self.assertIn("[result] ok", text)

    def test_drops_thinking_it_never_reached_the_terminal(self):
        text = self.render(entry("assistant", {"type": "thinking", "thinking": "secret"},
                                 text_part("out loud")))
        self.assertNotIn("secret", text)
        self.assertIn("out loud", text)

    def test_plain_string_content_is_kept(self):
        line = json.dumps({"type": "user", "message": {"role": "user", "content": "do it"}})
        self.assertIn("user: do it", self.render(line))

    def test_tool_result_blocks_are_flattened(self):
        text = self.render(entry("user", {"type": "tool_result",
                                          "content": [text_part("line a"), text_part("line b")]}))
        self.assertIn("line a line b", text)

    def test_one_line_per_entry_and_tail_is_the_end(self):
        lines = [entry("assistant", text_part(f"step {i}")) for i in range(50)]
        text = self.render(*lines, lines=5)
        self.assertEqual(len(text.splitlines()), 5)
        self.assertIn("step 49", text)         # the tail, not the head
        self.assertNotIn("step 44", text)

    def test_multiline_payloads_stay_on_one_line(self):
        text = self.render(entry("assistant", text_part("a\nb\nc")))
        self.assertEqual(len(text.splitlines()), 1)

    def test_long_payloads_are_clipped_not_wrapped(self):
        text = self.render(entry("user", {"type": "tool_result", "content": "x" * 5000}))
        self.assertEqual(len(text.splitlines()), 1)
        self.assertLess(len(text), output.CLIP + 100)
        self.assertTrue(text.endswith("…"))

    def test_a_torn_last_line_does_not_lose_the_rest(self):
        # A live session is being appended to while we read it.
        text = self.render(entry("assistant", text_part("real")), '{"type": "assis')
        self.assertIn("real", text)

    def test_missing_file_is_empty_not_an_explosion(self):
        self.assertEqual(output.read_transcript(self.root / "nope.jsonl"), "")


class RenderTest(unittest.TestCase):
    def test_provenance_leads(self):
        out = Output(agent="w1", source=TRANSCRIPT, text="boom",
                     detail="pane gone", path="/t/x.jsonl")
        r = out.render()
        self.assertTrue(r.startswith("--- w1: transcript /t/x.jsonl ---"))
        self.assertIn("(pane gone)", r)
        self.assertIn("boom", r)

    def test_unavailable_renders_the_reason_as_the_body(self):
        r = Output(agent="w1", source=UNAVAILABLE, detail="no pane, no transcript").render()
        self.assertIn("no pane, no transcript", r)


class ReadPaneFailureTest(unittest.TestCase):
    """herdr's `pane read` reports a gone pane as JSON on stdout with rc=0."""

    def _runner(self, proc):
        return lambda argv: proc

    def test_error_payload_raises_instead_of_being_returned_as_output(self):
        payload = json.dumps({"id": "x", "error": {"code": "pane_not_found",
                                                   "message": "no such pane"}})
        h = Herdr("herdr", runner=self._runner(subprocess.CompletedProcess([], 0, payload, "")))
        with self.assertRaises(HerdrError) as cm:
            h.read_pane("w1:p9")
        self.assertEqual(cm.exception.code, "pane_not_found")

    def test_nonzero_exit_raises(self):
        h = Herdr("herdr", runner=self._runner(
            subprocess.CompletedProcess([], 1, "", "connection refused")))
        with self.assertRaises(HerdrError) as cm:
            h.read_pane("w1:p9")
        self.assertIn("connection refused", cm.exception.message)

    def test_pane_output_that_merely_looks_like_json_survives(self):
        body = '{"not": "an envelope"\nstill terminal output\n'
        h = Herdr("herdr", runner=self._runner(subprocess.CompletedProcess([], 0, body, "")))
        self.assertEqual(h.read_pane("w1:p9"), body)

    def test_the_read_is_logged_like_every_other_call(self):
        seen = []
        h = Herdr("herdr", runner=self._runner(subprocess.CompletedProcess([], 0, "out", "")),
                  on_event=lambda **kw: seen.append(kw))
        h.read_pane("w1:p9")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "herdr")


if __name__ == "__main__":
    unittest.main()
