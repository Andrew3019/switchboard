"""What this plugin draws under its worktree on the board. The board's hook, plugin side.

`switchboard/board.py` looks for this file and for `board_lines` on it, and imports
neither unless both are there — which is what makes a board with no plugin drawing on it
cost nothing at all. A plugin that never wants to appear simply ships no `board.py`.

TWO RULES SHAPE EVERYTHING BELOW, and they are the same rule twice.

**Nothing here asks anybody anything.** `list` and `show` build a `_Live` and spend a
`_Budget` of seconds on `sb status`; a board redraws every couple of seconds, per group,
and cannot. It does not have to: the board hands over the `AgentStatus` rows of the very
worktree being drawn, and those rows already carry `state`, `gone` and `display_state` —
reconciled once per snapshot by the collector, which is the one process that asks. So
`_Rows` below is `_Live` with its single question already answered off what was handed in,
and every derivation on top of it — an owner's status, a plan's condition — is the shared
one, unchanged and unduplicated. The only thing this file touches is `plans.json` and one
`os.stat` of a checkout, both of which `_Live` already treats as free.

**Nothing here renders a plan its own way.** The plan line is `_line` and a step line is
`_step_lines`, the same two functions `list` and `show` draw with, so a change to how a
plan reads reaches the board without anybody remembering that the board exists.

What it chooses to show is the one editorial decision: every plan on the worktree, and
under each, its OPEN steps only. A board is a glance. A ticked step has nothing left to
say to somebody scanning for what is stuck, the plan's own line already carries the count
and the condition, and `sb plugin plans show p-1` is one command away for the rest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import (DONE, SKIPPED, _lib, _line, _read, _shown, _step_lines, _viewed, _Live)


def board_lines(state_dir: Path, workspace: str, rows: list) -> list[str]:
    """This worktree's plans, as lines, or nothing at all.

    Matched on the WORKSPACE NAME and not on the checkout path, which is the one place
    this differs from `list`: the board groups by the name the store holds, that name is
    what `create` filed the plan under, and the board has no checkout path to offer. A
    plan whose workspace is null — a plain clone, or an sb that was unreachable when it
    was made — is in no group and so is drawn by nobody, which is the honest answer.

    Every failure here is silence, enforced on the board's side as well as this one: a
    board is what a human looks at to find out that something has gone wrong, and a plugin
    is not allowed to be the reason it stopped drawing.
    """
    if not workspace:
        return []
    plans = [p for p in _read(Path(state_dir))[0]["plans"]
             if p.get("workspace") == workspace]
    if not plans:
        return []
    lib, bad = _lib(plans)
    if bad:
        # A catalogue with a bad definition in it is a real problem and `sb plugin plans
        # list` says so in full. Saying it here would put a refusal where a plan should be,
        # on a screen with no room to explain it and no way to act on it.
        return []
    live = _Rows(rows)
    out: list[str] = []
    for p in plans:
        v = _viewed(_shown(p, lib), live)
        out.append(_line(v, workspace=False))
        out.extend(
            # `[0]` is the step's own line — id, progress, name, owner and the owner's
            # status, deps, tries. What follows it in `_step_lines` is the why, the refs
            # and the notes, which is what `show` is for and what a board has no room for.
            "  " + _step_lines([s])[0] for s in v["steps"]
            if str(s.get("progress") or "") not in (DONE, SKIPPED))
    return out


class _Rows(_Live):
    """`_Live` with its one question already answered — off the rows the board handed in.

    `_Live.agents()` is the single place that costs a subprocess, and everything else in
    that class is derivation on top of it. Overriding it is therefore the whole of what
    this file has to do to be free: `owner()` and `condition()` are inherited unchanged,
    so the board reads a dead owner and an abandoned plan by exactly the rules `show`
    does, including the ones that matter most — a snapshot that did not arrive says
    nothing about anybody, and `unknown` is never `dead`.

    A dict per row, not the row itself, because `_Live` reads its rows as `sb status`
    JSON. Four keys, which is every field it looks at. `display_state` is the store's own
    reconciliation of the state column against what the pane is doing and is passed
    through rather than re-derived — the same contract `_Live.owner` relies on.

    Collapsed rows carry a workspace and a depth and no agent, so they are dropped: a row
    standing for an archived tail is not an agent whose state anything may read.
    """

    def __init__(self, rows: list) -> None:
        self._agents: Any = {
            str(r.name): {"state": getattr(r, "state", None),
                          "display_state": getattr(r, "display_state", None),
                          "gone": getattr(r, "gone", False),
                          "workspace": getattr(r, "workspace", None)}
            for r in rows if getattr(r, "name", None) and hasattr(r, "state")}

    def agents(self) -> dict:
        """The board's own rows, and never a question. See the class docstring.

        A dict and never None, which is a claim `_Live` reads as "sb answered": it did,
        and the collector is who it answered. The rows are scoped to ONE worktree, which
        is the group being drawn — and `condition` only ever counts agents whose
        `workspace` matches the plan's, so a plan on this worktree is judged against
        exactly the agents on it.
        """
        return self._agents
