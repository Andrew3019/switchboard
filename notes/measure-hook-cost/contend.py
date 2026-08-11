"""Contention: N agents firing the full activity hook at once, against the realistic
12 MB store copied from the live fleet. Reports per-firing latency at each N.
"""
import json
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLONE = Path("/private/tmp/claude-501/-Users-andrew--herdr-worktrees-switchboard-measure-hook-cost/37363a75-26af-413c-8e12-1b3b87915e3a/scratchpad/clone")
DB = CLONE / ".git/agentflow/state.db"
CMD = f"{CLONE}/bin/sb-activity-hook --db {DB} --kind tool_activity"
PAYLOAD = json.dumps({"session_id": "bench-session-0001", "hook_event_name": "PreToolUse",
                      "tool_name": "Read"})


def one():
    t0 = time.perf_counter()
    subprocess.run(["/bin/sh", "-c", CMD], input=PAYLOAD, text=True, capture_output=True)
    return (time.perf_counter() - t0) * 1000


def burst(n_agents, per_agent=15):
    def agent_loop(_):
        return [one() for _ in range(per_agent)]
    with ThreadPoolExecutor(max_workers=n_agents) as ex:
        res = list(ex.map(agent_loop, range(n_agents)))
    return sorted(t for r in res for t in r)


print(f"{'concurrent agents':>18} {'firings':>8} {'median ms':>10} {'p90':>7} {'max':>7}")
for n in (1, 2, 4, 8, 16):
    ts = burst(n)
    print(f"{n:>18} {len(ts):>8} {statistics.median(ts):10.1f} "
          f"{ts[int(0.9*len(ts))]:7.1f} {ts[-1]:7.1f}")
