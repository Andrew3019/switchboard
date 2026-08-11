"""Micro-benchmark: wall-clock cost of one hook firing.

Each variant is run the way Claude Code runs a `type: command` hook: a shell command,
JSON payload on stdin. Reports median/mean/p90 over N runs.
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

CLONE = Path("/private/tmp/claude-501/-Users-andrew--herdr-worktrees-switchboard-measure-hook-cost/37363a75-26af-413c-8e12-1b3b87915e3a/scratchpad/clone")
DB = CLONE / ".git/agentflow/state.db"
STAMPS = Path("/private/tmp/claude-501/-Users-andrew--herdr-worktrees-switchboard-measure-hook-cost/37363a75-26af-413c-8e12-1b3b87915e3a/scratchpad/stamps")
STAMPS.mkdir(exist_ok=True)

PAYLOAD_TOOL = json.dumps({
    "session_id": "bench-session-0001",
    "transcript_path": "/tmp/x.jsonl",
    "cwd": str(CLONE),
    "hook_event_name": "PreToolUse",
    "tool_name": "Read",
    "tool_input": {"file_path": "/tmp/a.txt"},
})
PAYLOAD_STOP = json.dumps({
    "session_id": "bench-session-0001",
    "hook_event_name": "Stop",
    "stop_hook_active": False,
})

PY = "/opt/homebrew/bin/python3"

VARIANTS = [
    ("shell floor: /usr/bin/true", "/usr/bin/true", PAYLOAD_TOOL),
    ("cheap, no interpreter: touch a file", f"/usr/bin/touch {STAMPS}/pane.alive", PAYLOAD_TOOL),
    ("python floor: python3 -c pass", f"{PY} -c pass", PAYLOAD_TOOL),
    ("cheap, python: stamp mtime (no switchboard import)",
     f"{CLONE}/bin/sb-touch-hook {STAMPS}", PAYLOAD_TOOL),
    ("full: sb-activity-hook (import switchboard + store write)",
     f"{CLONE}/bin/sb-activity-hook --db {DB} --kind tool_activity", PAYLOAD_TOOL),
    ("existing Stop gate: sb-stop-hook (import switchboard + store reads)",
     f"{CLONE}/bin/sb-stop-hook --db {DB}", PAYLOAD_STOP),
]


def run(cmd, payload, n):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run(["/bin/sh", "-c", cmd], input=payload, text=True,
                       capture_output=True)
        ts.append((time.perf_counter() - t0) * 1000)
    return ts


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    print(f"n={n} per variant, ms\n")
    print(f"{'variant':<62} {'median':>8} {'mean':>8} {'p90':>8} {'min':>7}")
    for label, cmd, payload in VARIANTS:
        run(cmd, payload, 3)          # warm
        ts = sorted(run(cmd, payload, n))
        print(f"{label:<62} {statistics.median(ts):8.1f} {statistics.mean(ts):8.1f} "
              f"{ts[int(0.9 * len(ts))]:8.1f} {ts[0]:7.1f}")


main()
