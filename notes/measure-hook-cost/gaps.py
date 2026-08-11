"""Per-tool-call latency straight out of the real transcripts.

For each session: the wall-clock gap between the assistant message carrying a tool_use
and the user message carrying its tool_result. That interval contains the tool itself
plus whatever hooks Claude Code runs around it, and NOT the model round trip — which is
what makes it the low-noise way to see the hook cost.
"""
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

D = Path("/Users/andrew/.claude/projects/-private-tmp-claude-501--Users-andrew--herdr-worktrees-switchboard-measure-hook-cost-37363a75-26af-413c-8e12-1b3b87915e3a-scratchpad-clone")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def gaps(path):
    use, out = {}, []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        c = (r.get("message") or {}).get("content")
        if not isinstance(c, list) or not r.get("timestamp"):
            continue
        for b in c:
            if b.get("type") == "tool_use":
                use[b["id"]] = ts(r["timestamp"])
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in use:
                out.append((ts(r["timestamp"]) - use.pop(b["tool_use_id"])) * 1000)
    return out


buckets = {}
for f in sorted(D.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
    g = gaps(f)
    if len(g) < 10:
        continue
    label = f.stat().st_mtime
    buckets[f.name] = g

# label each session by which run produced it, using the hook logs' timestamps
runs = []
S = Path("/private/tmp/claude-501/-Users-andrew--herdr-worktrees-switchboard-measure-hook-cost/37363a75-26af-413c-8e12-1b3b87915e3a/scratchpad/insitu")
print(f"{'session':<40} {'calls':>5} {'median ms':>10} {'mean':>7} {'p90':>7}")
for name, g in buckets.items():
    g = sorted(g)
    print(f"{name[:36]:<40} {len(g):>5} {statistics.median(g):10.1f} "
          f"{statistics.mean(g):7.1f} {g[int(0.9*len(g))]:7.1f}")
    runs.append((name, g))
json.dump({k: v for k, v in runs}, open("/tmp/gaps.json", "w"))
