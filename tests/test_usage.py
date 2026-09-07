"""Usage logging: transparent counting, bounded JSONL, retention, and aggregation."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from switchboard import cli, models, roles, usage


class ArgumentCaptureTests(unittest.TestCase):
    """Full argument capture, and the grouping keys that stay narrow around it."""

    def test_body_text_in_the_remainder_is_still_not_a_grouping_key(self):
        # `sb plugin todo "buy milk before it's too late"`: the body sits in the argparse
        # REMAINDER (`rest`). It is now logged verbatim in `argv`, but `plugin_command` is
        # still taken only from a RESOLVED subcommand — a report groups by that key, and a
        # key made of body text gives every distinct message a row of its own.
        args = cli.build_parser().parse_args(
            ["plugin", "todo", "buy milk before it's too late"])
        capture = {"command": None, "plugin": None, "plugin_command": None}
        cli._usage_args(capture, args)
        self.assertEqual(capture["command"], "plugin")
        self.assertEqual(capture["plugin"], "todo")
        self.assertIsNone(capture["plugin_command"])

    def test_a_rejected_call_still_logs_the_argv_it_was_rejected_for(self):
        # The case a parsed namespace cannot serve at all: argparse rejects this outright
        # and raises SystemExit, so no namespace ever exists. `argv` is captured before
        # parsing, so the row is still written and still carries the free text as typed.
        with self.assertRaises(SystemExit):
            cli.main(["plugins", "why did this stop working"])

        sink = usage.usage_dir()
        rows = [json.loads(line)
                for path in sorted(sink.glob("*.jsonl"))
                for line in path.read_text().splitlines()]
        self.assertEqual([row["argv"] for row in rows],
                         [["plugins", "why did this stop working"]])


class ModelCaptureTests(unittest.TestCase):
    """What a row has to carry so a Luna-vs-Claude split is answerable later."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / ".switchboard").mkdir()
        # Point the global model config at nothing: tier resolution layers ~/.config over
        # the shipped table, so without this a developer's own models.toml decides what a
        # tier means here and the test passes or fails per machine.
        env = mock.patch.dict(
            os.environ, {"SWITCHBOARD_MODELS_CONFIG": str(self.repo / "none.toml")})
        env.start()
        self.addCleanup(env.stop)
        self.broker = SimpleNamespace(roles=roles.load(self.repo), repo=self.repo)

    def capture_for(self, row) -> dict:
        capture: dict = {"tier": None, "model": None}
        cli._usage_model(capture, self.broker, row)
        return capture

    def test_a_pinned_tier_is_recorded_with_the_model_id_it_resolves_to(self):
        # `sb delegate --model cheap` writes `agents.tier`; the row has to say both which
        # tier that was and what it meant on the day, because the table is editable config.
        capture = self.capture_for({"role": "worker", "tier": "cheap"})
        self.assertEqual(capture["tier"], "cheap")
        self.assertEqual(capture["model"], models.resolve("cheap", self.repo).model)

    def test_an_unpinned_agent_records_its_role_s_own_tier_and_model(self):
        # NULL `agents.tier` is most of the fleet. Recording nothing for them would leave
        # the split answerable only for the minority somebody pinned by hand.
        role = self.broker.roles["worker"]
        capture = self.capture_for({"role": "worker", "tier": None})
        self.assertEqual(capture["tier"], role.model)
        self.assertEqual(capture["model"], models.resolve(role.model, self.repo).model)


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
    def test_record_has_sizes_the_chars_over_four_estimate_and_the_full_argv(self):
        record = usage.build_record(
            timestamp=10, repo="/r/.git", worktree="/r/w", caller="worker-x",
            caller_kind="agent", role="worker", tier="strong",
            model="a-model-id", command="tell", plugin=None,
            plugin_command=None, code=0, wall_ms=12.34567, stdout_bytes=9,
            stdout_chars=9, argv=["tell", "parent", "the roof is on fire"],
        )
        self.assertEqual(record["outcome"], "ok")
        # The pair, because neither answers the other's question later: the tier table is
        # config and gets edited, so the name alone does not say what ran.
        self.assertEqual((record["tier"], record["model"]), ("strong", "a-model-id"))
        self.assertEqual(record["token_estimate"], 3)
        self.assertEqual(record["wall_ms"], 12.346)
        # The reversal of 10f7334: the message body IS kept now, verbatim, as typed.
        self.assertEqual(record["argv"], ["tell", "parent", "the roof is on fire"])
        # Command OUTPUT still is not — that is unbounded, and only its size is recorded.
        self.assertNotIn("output", record)

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
            plugin_command: str | None = None, tier: str | None = "default",
            model: str | None = "model-a") -> dict:
        return {
            "command": command, "plugin": plugin, "plugin_command": plugin_command,
            "code": code, "outcome": "ok" if code == 0 else "error", "wall_ms": ms,
            "stdout_bytes": ms, "token_estimate": 2, "role": role,
            "caller_kind": caller_kind, "tier": tier, "model": model,
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

    def test_model_split_counts_each_model_and_leaves_old_rows_unknown(self):
        # The question this feature exists for: what share of the fleet's calls ran on
        # which model. A row from before the field was recorded — and every human call,
        # which has no model at all — must land in "unknown" rather than be attributed.
        rows = [
            self.row("status", model="model-a", tier="default"),
            self.row("status", model="model-b", tier="luna"),
            self.row("status", model="model-b", tier="luna"),
            {"command": "status", "code": 0, "outcome": "ok", "wall_ms": 1},
        ]

        report = usage.aggregate(rows, days=7)

        self.assertEqual(report["models"]["model-b"]["calls"], 2)
        self.assertEqual(report["models"]["model-a"]["calls"], 1)
        self.assertEqual(report["models"]["unknown"]["calls"], 1)
        self.assertEqual(report["tiers"]["luna"]["calls"], 2)
        self.assertIn("model-b                       2   50.0% of calls",
                      usage.format_report(report))

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
