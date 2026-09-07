"""Best-effort, cross-repository usage accounting for the ``sb`` CLI.

The sink stores measurements plus the full argument vector of each invocation.  It does
NOT store command OUTPUT, which is unbounded; ``argv`` is bounded by what a caller typed.
One append-only JSON line per process keeps writers independent across repositories and
worktrees; daily files make retention a cheap filename operation.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, TextIO

from . import config

# Points the sink at an explicit directory, overriding `paths.user_state`. It exists so a
# test run never writes into a developer's or CI box's real `~/.local/state/switchboard/usage/`
# (that pollutes the very cross-repo analytics this feature produces), and so an operator can
# relocate the sink. It names the usage directory itself, not the `user_state` base.
USAGE_DIR_ENV = "SWITCHBOARD_USAGE_DIR"


class CountingStdout:
    """A transparent text writer that counts successfully written characters and bytes."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.chars = 0
        self.bytes = 0

    def write(self, text: str) -> int:
        written = self.stream.write(text)
        # TextIO.write returns a character count.  A few compatible streams return None;
        # successful delegation still means all of the supplied text was accepted.
        count = len(text) if written is None else written
        accepted = text[:count]
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        errors = getattr(self.stream, "errors", None) or "strict"
        self.chars += len(accepted)
        self.bytes += len(accepted.encode(encoding, errors=errors))
        return written

    def flush(self) -> None:
        self.stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)


def usage_dir(repo: Optional[Path] = None) -> Path:
    """The user-scoped sink, optionally honoring this repository's settings layer.

    ``SWITCHBOARD_USAGE_DIR`` wins outright when set, so tests and operators can redirect the
    sink away from the real per-machine location.
    """
    override = os.environ.get(USAGE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    base = Path(config.setting("paths.user_state", repo=repo)).expanduser()
    return base / "usage"


def build_record(
    *, timestamp: int, repo: Optional[str], worktree: Optional[str],
    caller: Optional[str], caller_kind: str, role: Optional[str], tier: Optional[str],
    model: Optional[str], command: Optional[str],
    plugin: Optional[str], plugin_command: Optional[str], code: int, wall_ms: float,
    stdout_bytes: int, stdout_chars: int, argv: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Build the wire record written for one invocation.

    ``argv`` is the COMPLETE argument vector as typed, free-text bodies included — task
    descriptions, ``--tell`` messages, block reasons, plugin arguments. This deliberately
    reverses the earlier privacy bound (commit 10f7334, which kept bodies out of the
    record) on Andrew's direct instruction: the sink is local-only, and the argument text
    is the missing half of every "what was the fleet actually doing" question a
    vocabulary-only row could not answer. The raw vector rather than the parsed namespace:
    it is what was typed, it needs no per-subcommand schema, it is already JSON-
    serializable, and it exists even for a call argparse or validation rejected — which is
    precisely where a parsed namespace is absent.

    ``token_estimate`` is intentionally only the documented chars/4 heuristic; adding a
    tokenizer dependency for coarse fleet accounting would cost more than it measures.

    ``tier`` and ``model`` are BOTH kept, and neither substitutes for the other. A tier is
    open vocabulary whose meaning is edited (`defaults/models.toml`), so the tier name
    stored against a row does not say which model actually ran; a model id alone loses
    which choice put the agent there. Recording the pair is what lets a later report answer
    "how much of the fleet ran on which model" at all — the `agents` table drops its rows
    at cleanup, so this log is the only place that answer survives.
    """
    outcome = "ok" if code == 0 else ("usage" if code == 2 else "error")
    return {
        "timestamp": int(timestamp),
        "repo": repo,
        "worktree": worktree,
        "caller": caller,
        "caller_kind": caller_kind,
        "role": role,
        "tier": tier,
        "model": model,
        "command": command,
        "plugin": plugin,
        "plugin_command": plugin_command,
        "argv": [str(word) for word in (argv or ())],
        "code": int(code),
        "outcome": outcome,
        "wall_ms": round(max(0.0, float(wall_ms)), 3),
        "stdout_bytes": max(0, int(stdout_bytes)),
        "token_estimate": math.ceil(max(0, int(stdout_chars)) / 4),
    }


def prune(directory: Path, *, retention_days: int, today: Optional[date] = None) -> None:
    """Remove dated JSONL files outside the retention window; ignore unrelated files."""
    today = today or date.today()
    cutoff = today - timedelta(days=retention_days - 1)
    for path in directory.glob("*.jsonl"):
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink(missing_ok=True)


def append(record: dict[str, Any], *, repo: Optional[Path] = None) -> None:
    """Append one line and opportunistically prune on the first write of a new day."""
    directory = usage_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = int(record["timestamp"])
    day = datetime.fromtimestamp(timestamp).date()
    path = directory / f"{day.isoformat()}.jsonl"
    first_today = not path.exists()
    if first_today:
        retention = int(config.setting("limits.usage_retention_days", repo=repo))
        prune(directory, retention_days=retention, today=day)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")


def record_best_effort(record: dict[str, Any], *, repo: Optional[Path] = None) -> None:
    """The logging boundary: no sink/config/serialization failure may affect ``sb``."""
    try:
        append(record, repo=repo)
    except Exception:  # noqa: BLE001 - observability must never break the observed command
        pass


def read_records(
    *, directory: Optional[Path] = None, days: int = 30,
    repo: Optional[str] = None, command: Optional[str] = None,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Read valid retained rows, tolerating a partial or damaged append."""
    directory = directory or usage_dir()
    today = today or date.today()
    cutoff = today - timedelta(days=days - 1)
    rows: list[dict[str, Any]] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.jsonl")):
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not cutoff <= file_date <= today:
            continue
        try:
            lines = path.open(encoding="utf-8")
        except OSError:
            continue
        with lines:
            for line in lines:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(row, dict):
                    continue
                if repo is not None and row.get("repo") != repo:
                    continue
                if command is not None and command_key(row) != command:
                    continue
                rows.append(row)
    return rows


def command_key(row: dict[str, Any]) -> str:
    """A core verb, or a fully qualified plugin subcommand for useful grouping."""
    if row.get("command") == "plugin" and row.get("plugin"):
        tail = f":{row['plugin_command']}" if row.get("plugin_command") else ""
        return f"plugin:{row['plugin']}{tail}"
    return str(row.get("command") or "unknown")


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    # Nearest-rank is predictable for small operational samples and needs no dependency.
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    outcomes = {"ok": 0, "error": 0, "usage": 0}
    latencies: list[float] = []
    stdout_bytes = 0
    tokens = 0
    for row in rows:
        outcome = row.get("outcome")
        if outcome not in outcomes:
            outcome = "ok" if row.get("code") == 0 else "error"
        outcomes[outcome] += 1
        try:
            latencies.append(float(row.get("wall_ms", 0)))
            stdout_bytes += int(row.get("stdout_bytes", 0))
            tokens += int(row.get("token_estimate", 0))
        except (TypeError, ValueError):
            continue
    ok = outcomes["ok"]
    failures = total - ok
    return {
        "calls": total,
        "outcomes": outcomes,
        "success_rate": round(ok / total, 4) if total else 0.0,
        "error_rate": round(failures / total, 4) if total else 0.0,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "output": {
            "stdout_bytes_total": stdout_bytes,
            "stdout_bytes_avg": round(stdout_bytes / total, 2) if total else 0.0,
            "token_estimate_total": tokens,
            "token_estimate_avg": round(tokens / total, 2) if total else 0.0,
        },
    }


def aggregate(rows: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
    """Aggregate fleet, command, role, model, tier, and caller-type patterns.

    Rows written before models were recorded, and every row from a human caller, group
    under "unknown" — the same fail-open the role and caller-kind groups already use. A
    model split therefore reads as "of the calls that name one", never as a claim that the
    fleet ran unmodelled work.
    """
    commands: dict[str, list[dict[str, Any]]] = {}
    roles: dict[str, list[dict[str, Any]]] = {}
    models: dict[str, list[dict[str, Any]]] = {}
    tiers: dict[str, list[dict[str, Any]]] = {}
    caller_kinds: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        commands.setdefault(command_key(row), []).append(row)
        roles.setdefault(str(row.get("role") or "unknown"), []).append(row)
        models.setdefault(str(row.get("model") or "unknown"), []).append(row)
        tiers.setdefault(str(row.get("tier") or "unknown"), []).append(row)
        caller_kinds.setdefault(str(row.get("caller_kind") or "unknown"), []).append(row)
    return {
        "days": days,
        "overall": _metrics(rows),
        "commands": {key: _metrics(group) for key, group in sorted(commands.items())},
        "roles": {key: _metrics(group) for key, group in sorted(roles.items())},
        "models": {key: _metrics(group) for key, group in sorted(models.items())},
        "tiers": {key: _metrics(group) for key, group in sorted(tiers.items())},
        "caller_kinds": {
            key: _metrics(group) for key, group in sorted(caller_kinds.items())
        },
    }


def format_report(report: dict[str, Any]) -> str:
    """Compact terminal report; ``--json`` exposes the complete nested structure."""
    overall = report["overall"]
    latency = overall["latency_ms"]
    output = overall["output"]
    lines = [
        f"sb usage — last {report['days']} days, {overall['calls']} calls",
        f"overall: {overall['success_rate']:.1%} ok, {overall['error_rate']:.1%} error; "
        f"latency p50 {latency['p50']:g} ms, p95 {latency['p95']:g} ms, "
        f"max {latency['max']:g} ms",
        f"output: {output['stdout_bytes_total']} stdout bytes "
        f"({output['stdout_bytes_avg']:g}/call), ~{output['token_estimate_total']} tokens",
    ]
    if report["commands"]:
        lines.append("commands:")
        for name, metrics in sorted(
            report["commands"].items(), key=lambda item: (-item[1]["calls"], item[0])
        ):
            latency = metrics["latency_ms"]
            lines.append(
                f"  {name:24} {metrics['calls']:6}  {metrics['success_rate']:6.1%} ok  "
                f"p50 {latency['p50']:g} ms  p95 {latency['p95']:g} ms  "
                f"max {latency['max']:g} ms"
            )
    if report["roles"]:
        lines.append("roles:")
        for name, metrics in sorted(report["roles"].items()):
            lines.append(
                f"  {name:24} {metrics['calls']:6}  {metrics['success_rate']:6.1%} ok"
            )
    # `.get`, unlike the groups above: a report read back from an older `--json` dump has
    # no model or tier section, and the formatter is the one place that can meet one.
    for section, label in (("models", "models"), ("tiers", "tiers")):
        if report.get(section):
            lines.append(f"{label}:")
            for name, metrics in sorted(
                report[section].items(), key=lambda item: (-item[1]["calls"], item[0])
            ):
                share = metrics["calls"] / overall["calls"] if overall["calls"] else 0.0
                lines.append(
                    f"  {name:24} {metrics['calls']:6}  {share:6.1%} of calls  "
                    f"{metrics['success_rate']:6.1%} ok"
                )
    if report["caller_kinds"]:
        lines.append("callers:")
        for name, metrics in sorted(report["caller_kinds"].items()):
            lines.append(
                f"  {name:24} {metrics['calls']:6}  {metrics['success_rate']:6.1%} ok"
            )
    return "\n".join(lines)
