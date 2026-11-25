"""The memory gate — a spawn is refused when starting it would leave the machine too little.

THE FAILURE THIS EXISTS FOR. A fleet on a 16 GB Mac (or a WSL VM) grows one agent at a
time, every agent is a provider CLI plus whatever tests and builds it runs, and nothing
asked whether the next one fit. Past a dozen or so the machine swaps itself to a halt, and
the only way out is to kill everything — losing the work in flight in every pane. A
refused spawn costs one retry; a frozen machine costs the fleet.

THIS IS A GATE, NOT A QUEUE, deliberately, as the better-than-nothing first step. A refusal
says why and what to do instead (end the turn, retry when a child reports), so the parent
loses nothing and the protocol's "nothing blocks" still holds: the call returns at once,
it just returns no. A queue that the collector drains when memory frees up is the obvious
next step and would replace the refusal, not the check.

UNKNOWN IS ALLOWED. `stats._available_memory` answers None when the OS will not say, and
a gate that refused on None would stop every spawn on a platform it does not understand —
the opposite of the point. Only a reading that is really low refuses.

Not applied to `sb start` (`is_top`): that is a human at a keyboard, who can see the
machine and decide for themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import config
from . import stats as stats_mod

MB = 1024 * 1024


def available_bytes() -> Optional[int]:
    """What the OS says a new allocation could get. The one seam tests replace."""
    return stats_mod._available_memory()


def refusal(repo: Optional[Path] = None) -> Optional[str]:
    """Why a new agent may not start right now, or None if it may.

    Refuses when `available - per_agent_mb < reserve_mb`: starting one more agent would
    eat into the reserve the machine needs to stay responsive.
    """
    if not config.setting("capacity.enabled", repo=repo):
        return None
    avail = available_bytes()
    if avail is None:
        return None
    reserve = int(config.setting("capacity.reserve_mb", repo=repo)) * MB
    per_agent = int(config.setting("capacity.per_agent_mb", repo=repo)) * MB
    if avail - per_agent >= reserve:
        return None
    return (
        f"not enough memory to start another agent: {avail // MB} MB available, a new "
        f"agent is budgeted at {per_agent // MB} MB and {reserve // MB} MB is kept in "
        f"reserve ([capacity] in settings.toml). Nothing was spawned. Do NOT do the work "
        f"yourself: end your turn (`sb waiting` if children are out) and retry this "
        f"delegate after one of them reports, or close finished agents/workspaces first.")
