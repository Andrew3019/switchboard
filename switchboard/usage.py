"""Best-effort, cross-repository usage accounting for the ``sb`` CLI.

The sink deliberately stores measurements rather than output bodies.  One append-only
JSON line per process keeps writers independent across repositories and worktrees; daily
files make retention a cheap filename operation.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, TextIO

from . import config


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
    """The user-scoped sink, optionally honoring this repository's settings layer."""
    base = Path(config.setting("paths.user_state", repo=repo)).expanduser()
    return base / "usage"


def build_record(
    *, timestamp: int, repo: Optional[str], worktree: Optional[str],
    caller: Optional[str], caller_kind: str, role: Optional[str], command: Optional[str],
    plugin: Optional[str], plugin_command: Optional[str], code: int, wall_ms: float,
    stdout_bytes: int, stdout_chars: int,
) -> dict[str, Any]:
    """Build the privacy-bounded wire record written for one invocation.

    ``token_estimate`` is intentionally only the documented chars/4 heuristic; adding a
    tokenizer dependency for coarse fleet accounting would cost more than it measures.
    """
    outcome = "ok" if code == 0 else ("usage" if code == 2 else "error")
    return {
        "timestamp": int(timestamp),
        "repo": repo,
        "worktree": worktree,
        "caller": caller,
        "caller_kind": caller_kind,
        "role": role,
        "command": command,
        "plugin": plugin,
        "plugin_command": plugin_command,
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
    """Aggregate fleet, command, role, and caller-type patterns."""
    commands: dict[str, list[dict[str, Any]]] = {}
    roles: dict[str, list[dict[str, Any]]] = {}
    caller_kinds: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        commands.setdefault(command_key(row), []).append(row)
        roles.setdefault(str(row.get("role") or "unknown"), []).append(row)
        caller_kinds.setdefault(str(row.get("caller_kind") or "unknown"), []).append(row)
    return {
        "days": days,
        "overall": _metrics(rows),
        "commands": {key: _metrics(group) for key, group in sorted(commands.items())},
        "roles": {key: _metrics(group) for key, group in sorted(roles.items())},
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
    if report["caller_kinds"]:
        lines.append("callers:")
        for name, metrics in sorted(report["caller_kinds"].items()):
            lines.append(
                f"  {name:24} {metrics['calls']:6}  {metrics['success_rate']:6.1%} ok"
            )
    return "\n".join(lines)
