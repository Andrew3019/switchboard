"""What the hook would have cost on real switchboard agent sessions already on disk.

Counts tool calls, turns (Stop points ~= assistant messages that end without a tool_use),
and session duration for every transcript belonging to a switchboard worktree.
"""
import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/andrew/.claude/projects")
DIRS = [d for d in ROOT.iterdir()
        if d.is_dir() and "switchboard" in d.name and "scratchpad-clone" not in d.name]

PRE_MS, POST_MS, STOP_MS = 74.0, 74.0, 74.0   # measured in-situ, per firing
CHEAP_MS = 19.0                                # measured in-situ, PostToolUse touch


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


rows = []
for d in DIRS:
    for f in d.glob("*.jsonl"):
        calls = 0
        stops = 0
        times = []
        try:
            lines = f.read_text().splitlines()
        except Exception:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("timestamp"):
                try:
                    times.append(ts(r["timestamp"]))
                except Exception:
                    pass
            msg = r.get("message") or {}
            c = msg.get("content")
            if r.get("type") == "assistant" and isinstance(c, list):
                n = sum(1 for b in c if b.get("type") == "tool_use")
                calls += n
                if n == 0 and msg.get("stop_reason") in (None, "end_turn"):
                    stops += 1
        if calls < 5 or not times:
            continue
        rows.append({"session": f.name[:8], "repo": d.name[-28:], "calls": calls,
                     "stops": stops, "hours": (max(times) - min(times)) / 3600})

rows.sort(key=lambda r: -r["calls"])
print(f"{'session':<10} {'worktree':<30} {'tool calls':>10} {'turns':>6} {'hours':>6} "
      f"{'full s':>7} {'cheap s':>8}")
for r in rows[:15]:
    full = (r["calls"] * (PRE_MS + POST_MS) + r["stops"] * STOP_MS) / 1000
    cheap = r["calls"] * CHEAP_MS / 1000
    print(f"{r['session']:<10} {r['repo']:<30} {r['calls']:>10} {r['stops']:>6} "
          f"{r['hours']:>6.1f} {full:>7.1f} {cheap:>8.1f}")

tot = sum(r["calls"] for r in rows)
print(f"\n{len(rows)} sessions, {tot} tool calls total")
print(f"median tool calls/session: {statistics.median([r['calls'] for r in rows]):.0f}, "
      f"max {max(r['calls'] for r in rows)}")
print(f"full design over all of them:  {tot * 148 / 1000 / 60:.1f} min of added latency")
print(f"cheap design over all of them: {tot * 19 / 1000 / 60:.1f} min")
print(f"full design event rows written: {tot * 2 + sum(r['stops'] for r in rows)}")
