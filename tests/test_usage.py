"""Usage logging: transparent counting, bounded JSONL, retention, and aggregation."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from switchboard import cli, usage


class PluginCaptureLeakTests(unittest.TestCase):
    """The sizes-only log must never keep a message body typed after a plugin name."""

    def test_body_text_in_the_remainder_is_never_captured_as_subcommand(self):
        # `sb plugin todo "buy milk before it's too late"`: the body sits in the argparse
        # REMAINDER (`rest`). `plugin_command` is taken only from a RESOLVED subcommand, so
        # before/without validation none is captured — the body cannot reach the log even
        # when `_validate` then fails and the second capture pass never runs.
        args = cli.build_parser().parse_args(
            ["plugin", "todo", "buy milk before it's too late"])
        capture = {"command": None, "plugin": None, "plugin_command": None}
        cli._usage_args(capture, args)
        self.assertEqual(capture["command"], "plugin")
        self.assertEqual(capture["plugin"], "todo")
        self.assertIsNone(capture["plugin_command"])


class MainLevelSinkFailureTests(unittest.TestCase):
    """The load-bearing invariant, pinned at `main()`: logging never changes the result."""

    def test_a_raising_record_builder_does_not_change_the_exit_code(self):
        # `sb plugins` is retired and returns 2 before the store is even opened. Even if the
        # usage record blows up inside `main()`'s finally, that 2 must still come back.
        with mock.patch.object(cli.usage_mod, "build_record",
                               side_effect=RuntimeError("boom")):
            code = cli.main(["plugins"])
        self.assertEqual(code, 2)


class CountingStdoutTests(unittest.TestCase):
    def test_writes_through_unchanged_and_counts_encoded_bytes(self):
        destination = io.StringIO()
        counted = usage.CountingStdout(destination)

        self.assertEqual(counted.write("hi ☃"), 4)

        self.assertEqual(destination.getvalue(), "hi ☃")
        self.assertEqual(counted.chars, 4)
        self.assertEqual(counted.bytes, len("hi ☃".encode("utf-8")))

    def test_delegates_stream_attributes_and_flush(self):
        destination = io.StringIO()
        counted = usage.CountingStdout(destination)
        counted.flush()
        self.assertEqual(counted.isatty(), destination.isatty())


class RecordAndSinkTests(unittest.TestCase):
    def test_record_has_sizes_and_chars_over_four_estimate_but_no_body(self):
        record = usage.build_record(
            timestamp=10, repo="/r/.git", worktree="/r/w", caller="worker-x",
            caller_kind="agent", role="worker", command="tell", plugin=None,
            plugin_command=None, code=0, wall_ms=12.34567, stdout_bytes=9,
            stdout_chars=9,
        )
        self.assertEqual(record["outcome"], "ok")
        self.assertEqual(record["token_estimate"], 3)
        self.assertEqual(record["wall_ms"], 12.346)
        self.assertNotIn("output", record)
        self.assertNotIn("message", record)

    def test_append_serializes_one_compact_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "usage"
            record = {"timestamp": 1_725_235_200, "command": "status"}
            with mock.patch.object(usage, "usage_dir", return_value=directory), \
                    mock.patch.object(usage.config, "setting", return_value=30):
                usage.append(record)
            files = list(directory.glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text()), record)
            self.assertEqual(files[0].read_text().count("\n"), 1)

    def test_best_effort_swallows_sink_failure(self):
        with mock.patch.object(usage, "append", side_effect=PermissionError("no")):
            usage.record_best_effort({"timestamp": 1})


class RetentionTests(unittest.TestCase):
    def test_prune_keeps_exactly_thirty_daily_files_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            today = date(2026, 8, 30)
            old = directory / f"{today - timedelta(days=31)}.jsonl"
            boundary = directory / f"{today - timedelta(days=30)}.jsonl"
            new = directory / f"{today - timedelta(days=1)}.jsonl"
            unrelated = directory / "notes.jsonl"
            for path in (old, boundary, new, unrelated):
                path.write_text("\n")

            usage.prune(directory, retention_days=30, today=today)

            self.assertFalse(old.exists())
            self.assertFalse(boundary.exists())
            self.assertTrue(new.exists())
            self.assertTrue(unrelated.exists())


class AggregationTests(unittest.TestCase):
    def row(self, command: str, *, code: int = 0, ms: int = 10, role: str = "worker",
            caller_kind: str = "agent", plugin: str | None = None,
            plugin_command: str | None = None) -> dict:
        return {
            "command": command, "plugin": plugin, "plugin_command": plugin_command,
            "code": code, "outcome": "ok" if code == 0 else "error", "wall_ms": ms,
            "stdout_bytes": ms, "token_estimate": 2, "role": role,
            "caller_kind": caller_kind,
        }

    def test_aggregates_commands_percentiles_outputs_roles_and_callers(self):
        rows = [
            self.row("status", ms=10),
            self.row("status", code=1, ms=20),
            self.row("plugin", ms=100, role="lead", plugin="plans",
                     plugin_command="show"),
        ]

        report = usage.aggregate(rows, days=7)

        self.assertEqual(report["overall"]["calls"], 3)
        self.assertEqual(report["overall"]["latency_ms"],
                         {"p50": 20.0, "p95": 100.0, "max": 100.0})
        self.assertEqual(report["overall"]["output"]["stdout_bytes_total"], 130)
        self.assertEqual(report["commands"]["status"]["outcomes"]["error"], 1)
        self.assertIn("plugin:plans:show", report["commands"])
        self.assertEqual(report["roles"]["worker"]["calls"], 2)
        self.assertEqual(report["caller_kinds"]["agent"]["calls"], 3)

    def test_reader_skips_bad_lines_and_applies_repo_and_command_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            today = date(2026, 8, 30)
            rows = [
                {"repo": "a", "command": "status"},
                {"repo": "b", "command": "plugin", "plugin": "plans",
                 "plugin_command": "show"},
            ]
            path = directory / f"{today}.jsonl"
            path.write_text("\n".join([json.dumps(row) for row in rows] + ["broken"]) + "\n")

            got = usage.read_records(directory=directory, days=7, repo="b",
                                     command="plugin:plans:show", today=today)

            self.assertEqual(got, [rows[1]])


if __name__ == "__main__":
    unittest.main()
