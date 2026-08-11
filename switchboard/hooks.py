"""The Stop gate, and the activity signal — both of them turn edges.

`sb done` is asked for by the protocol and, until this file existed, enforced by nothing:
an agent could end its turn silently and its work stayed invisible until a person noticed.
That happened four times on 2026-08-11. This is the mechanical half — a `Stop` hook that
refuses the end of a turn nobody reported.

The second thing this file does is answer "is this agent working right now?" from the same
two edges. Switchboard had no signal of its own for that: it asked herdr, which infers it
by matching Claude's spinner glyphs in the terminal title, and Claude Code 2.1.228 changed
those glyphs — so herdr reported idle for every pane on this machine, including agents
provably mid-tool-call (`audit/status-ground-truth.md`). One cosmetic change upstream took
out hold-until-free delivery, made the reconciler ping working agents, and made the board
lie. So we record the fact ourselves:

    UserPromptSubmit  ->  agents.turn = 'working'      a turn began
    Stop              ->  agents.turn = 'idle'         a turn ended

Chosen over the two obvious alternatives on measured evidence (`audit/hook-signal-cost.md`):
per-tool-call hooks cost 148 ms per tool call, a `PostToolUse` timestamp cost 19 ms, and
neither cost was the decider. The timestamp lost on correctness — it cannot tell a long
tool call from a finished turn, 2.18 % of 15,000 real tool calls in this repo ran longer
than the existing 72-second grace and the longest ran 18 minutes, so no timeout works. The
edges cost nothing per tool call, about 74 ms once per turn, and need no timeout at all: a
long tool call is inside a turn that began and has not ended, however long it runs.

Three pieces:

* `settings_file()` writes the per-repo settings JSON that carries BOTH hooks, and
  `stop_hook_args()` turns it into the `--settings <path>` every spawn passes. Only agents
  we spawn are handed the file, which is the whole of the isolation — an ordinary `claude`
  session never sees it, and no file of the human's is ever written to or read.
* `stop_gate()` is the decision, run once per turn end by `bin/sb-stop-hook`.
* `mark_turn()` is the signal, written by `bin/sb-activity-hook` at the start of a turn
  and by `run()` at the end of one — AFTER the gate has decided, and only if the turn is
  actually being allowed to end. See `run()`.

Verified against the real CLI rather than the docs (2026-08-11): with `--settings <file>`
and **no** `--bare`, the hook fires; `--bare` skips hooks entirely and would have produced
a gate that never ran. Printing `{"decision": "block", "reason": …}` on stdout with exit 0
blocks the stop and gives the model another turn. On that next turn the payload carries
`stop_hook_active: true`, which is the loop cap below.

Everything here fails OPEN. A gate that cannot tell who is calling, or that cannot open the
store, must let the turn end: the cost of a missed nudge is a stalled row that `status`
already names, and the cost of a false block is an agent that can never stop.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sqlite3
from pathlib import Path
from typing import Any, Optional

from . import store

# The states that mean "this agent reported". `blocked` is a report — it is the one way an
# agent reaches a person — and `failed` is a turn that ended on purpose too.
REPORTED = ("done", "blocked", "failed")

# What the agent is told when it tries to finish without one. It names the cap on purpose:
# an agent that believes it will be nagged forever starts inventing reports to escape.
BLOCK_REASON = (
    "switchboard: your turn cannot end without a report. Call "
    '`sb done "<summary>"` if the work is finished — your summary is the only thing '
    "your parent ever sees — or "
    '`sb block "<why>"` if you need a human. Nothing you write in this pane reaches '
    "anyone. You will only be stopped once; if neither verb applies, say why and stop."
)

_SETTINGS_DIRNAME = "hooks"


# -- the settings file ---------------------------------------------------


def _entry_point(script: str = "sb-stop-hook") -> Path:
    """A hook script belonging to THIS checkout of switchboard.

    Absolute on purpose. The hook runs in the agent's own worktree with the agent's own
    PATH, and the code that should decide is the code that spawned it — resolving `sb` at
    hook time would pick up whatever that pane happens to have.
    """
    return Path(__file__).resolve().parent.parent / "bin" / script


def settings_file(cwd: Optional[Path] = None) -> Path:
    """Write (idempotently) the settings JSON that carries both hooks, and return it.

    Under the store directory, which is the shared `.git` — never in a worktree, never
    anywhere near `~/.claude`. Keyed by a hash of the gate's absolute path because that
    directory is shared by every worktree of the repo and each has its own `bin/`: one
    file per checkout, so a worktree that goes away cannot leave the others pointing at a
    script that no longer exists.

    Written tmp-then-rename: several spawns race here, and a half-written settings file is
    a session that will not start.
    """
    gate = _entry_point()
    activity = _entry_point("sb-activity-hook")
    tag = hashlib.sha256(str(gate).encode()).hexdigest()[:8]
    d = store.store_dir(cwd) / _SETTINGS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"stop-{tag}.json"
    # The store is named explicitly rather than resolved from the hook's cwd. An agent may
    # be standing anywhere — including inside another repo entirely — and a gate that
    # re-derived the store from where it happens to run would consult the wrong one, and
    # `connect()` would helpfully create it.
    db = shlex.quote(str(store.db_path(cwd)))
    body = json.dumps(
        {
            "hooks": {
                # The turn-STARTED edge. One firing per turn, ~74 ms, nothing per tool
                # call. No matcher: every prompt an agent is given starts a turn, whether
                # it came from a doorbell, a `tell`, the reconciler or a person typing.
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    f"{shlex.quote(str(activity))} --db {db}"
                                ),
                                "timeout": 10,
                                "statusMessage": "marking working…",
                            }
                        ]
                    }
                ],
                # The turn-ENDED edge, and the gate, in one process — which is why the
                # idle half is effectively free: this hook already ran on every turn end
                # of every agent we spawn, and the signal is one extra UPDATE inside it.
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    f"{shlex.quote(str(gate))} --db {db}"
                                ),
                                # Well over the gate's cost (one sqlite read); a timeout
                                # is a non-blocking failure, so this only ever fails open.
                                "timeout": 10,
                                "statusMessage": "checking for a report…",
                            }
                        ]
                    }
                ],
            }
        },
        indent=2,
    )
    if p.exists() and p.read_text() == body:
        return p
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(body)
    tmp.replace(p)
    return p


def stop_hook_args(cwd: Optional[Path] = None) -> list[str]:
    """`--settings <file>`, or nothing at all if it could not be written.

    NEVER raises. Enforcement is worth a lot, but not a spawn: `start_agent` calls this,
    and an agent that fails to start because a hook file could not be written is a strictly
    worse system than one that reports by goodwill.
    """
    try:
        return ["--settings", str(settings_file(cwd))]
    except Exception:                            # noqa: BLE001 — not in a repo, unwritable
        return []


# -- the gate ------------------------------------------------------------


def _agent_row(db: sqlite3.Connection, payload: dict) -> Optional[sqlite3.Row]:
    """Who is stopping, resolved the way `Broker.whoami` resolves it.

    Session id first, and then `HERDR_PANE_ID` — which the hook inherits from the pane the
    session was started in. The fallback is load-bearing rather than decorative: the store
    learns an agent's session id on its FIRST `sb` call, so an agent that has run none has
    no `session_id` row to match, and that is precisely the agent this gate exists for.
    """
    sid = payload.get("session_id")
    if sid:
        row = store.agent_by_session(db, str(sid))
        if row is not None:
            return row
    pane = os.environ.get("HERDR_PANE_ID")
    if pane:
        return db.execute(
            "SELECT * FROM agents WHERE pane_id=? ORDER BY created_at DESC LIMIT 1",
            (pane,),
        ).fetchone()
    return None


def _has_live_child(db: sqlite3.Connection, name: str) -> bool:
    return db.execute(
        "SELECT 1 FROM agents WHERE parent=? AND state IN ('working', 'blocked') "
        "AND ended_at IS NULL LIMIT 1",
        (name,),
    ).fetchone() is not None


def _already_nudged(db: sqlite3.Connection, name: str) -> bool:
    """Has this agent been stopped once already, with nothing reported since?

    THE CAP, and the reason it lives here rather than in `stop_hook_active`. That flag is
    real and it arrives — measured twice, on the second stop of a chain the gate itself
    caused — but it is scoped to ONE stop-chain, and a chain is one user prompt. Anything
    that pokes the agent starts a new one: a doorbell ring, a `tell`, the reconciler's own
    nudge. Reproduced in an isolated clone: an agent was blocked, allowed through on its
    second stop with `stop_hook_active: true`, then told one thing and blocked again on the
    next stop with the flag false and a new `prompt_id`. Two blocks, one agent, nothing
    wrong with the flag — the cap was simply never the property the design claimed.

    So the cap is asked of the store, which outlives every chain: the newest of this
    agent's block/report events. `stop_gate_blocked` on top means we nudged it and it has
    said nothing since, so it is nudged no further — the reconciler is what carries a
    silent agent from there, and `BLOCK_REASON` promises exactly this ("you will only be
    stopped once"), which until now it could not keep.

    A report resets it, and that is the intended re-arm rather than a leak: an agent that
    called `sb done` and is then spoken to in its pane is `working` again, and its next
    silent turn-end is a new silence worth one nudge.
    """
    row = db.execute(
        "SELECT kind FROM events WHERE agent=? AND kind IN "
        "('stop_gate_blocked', 'done', 'blocked') ORDER BY id DESC LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None and row["kind"] == "stop_gate_blocked"


def mark_turn(payload: dict, db: sqlite3.Connection, turn: str) -> Optional[str]:
    """Record a turn edge for whoever is calling. -> the agent named, or None.

    The whole of the activity signal. `_agent_row` resolves the caller exactly as the gate
    does — session id, then `HERDR_PANE_ID` — and the fallback matters more here than
    there: this fires on the very FIRST prompt an agent is given, before it has run a
    single `sb` command, so there is usually no `session_id` row to match yet.

    An unresolvable caller writes nothing. That is not a failure to handle: it is a
    `claude` session that is not one of ours, and the point of hanging both hooks off the
    per-spawn settings file is that no session of the human's is ever touched.

    The event is logged against NO agent, with the target in its payload, and that is the
    same deliberate choice `Broker._nudge` and `stop_gate`'s cap make for the same reason:
    `status._last_activity` counts every event that NAMES an agent, so logging a turn edge
    against the agent would reset its idle clock. It would do it on the reconciler's own
    ping, too — the ping is a prompt, the prompt starts a turn, the turn logs an event —
    which is exactly how a "ping once per stall" rule comes to read its own footprint as
    the agent having done something and nags forever. The STATE lives in the column; the
    log is history.
    """
    a = _agent_row(db, payload)
    if a is None:
        return None
    name = a["name"]
    store.set_turn(db, name, turn)
    store.log_event(db, kind=("turn_start" if turn == store.TURN_WORKING else "turn_end"),
                    target=name)
    return name


def stop_gate(payload: dict, db: sqlite3.Connection) -> Optional[str]:
    """The reason to refuse this turn's end, or None to let it end.

    The order of the checks is the design, so it is worth reading as a list.

    **`stop_hook_active` first, and unconditionally.** It is true only on a turn that this
    gate itself caused: block a turn, the agent takes another, it ends, and this lets that
    second end through. At most one stop per stop-chain.

    **`_already_nudged` last, and it is the real cap.** A stop-chain is one user prompt,
    so the flag above caps nothing an agent is poked through — a ring, a `tell`, the
    reconciler's own nudge each start a fresh chain with the flag false, which is how one
    agent came to be blocked twice twelve seconds apart. The store remembers instead: one
    block per agent until it reports something. A nudged agent that still will not report
    is then 3.5's problem — the reconciler names a stalled agent afterwards, which is the
    right division: the hook prevents the ordinary case, it does not fight the pathological
    one.

    **An unresolvable caller ends its turn.** Not one of ours, or one we cannot name yet.

    **Three legitimate ends without a report**, and only three: an agent still holding its
    placeholder task (`awaiting_task`) was told to wait for one; a parent with a live child
    was told to delegate and end its turn, and blocking that would push it to report `done`
    over work still running; and an agent that already reported has nothing to add.

    Anything else is the silent finish this exists to stop.
    """
    if payload.get("stop_hook_active"):
        return None
    a = _agent_row(db, payload)
    if a is None:
        return None
    if a["state"] in REPORTED:
        return None
    if a["awaiting_task"]:
        return None
    if _has_live_child(db, a["name"]):
        # Logged rather than silent: this is the one exemption that could hide a real
        # silent finish, so it should be visible on the board that it was used.
        store.log_event(db, kind="stop_gate_waived", agent=a["name"], reason="live_children")
        return None
    if _already_nudged(db, a["name"]):
        # Logged against NO agent, with the target in the payload, for the reconciler's
        # reason (`Broker._nudge`): `status._last_activity` counts every event that names
        # an agent, so writing this against the target would reset the idle clock on the
        # silent agent this hand-off exists to pass on.
        store.log_event(db, kind="stop_gate_capped", target=a["name"])
        return None
    store.log_event(db, kind="stop_gate_blocked", agent=a["name"])
    return BLOCK_REASON


def _open(stdin_text: str, db_path: Optional[Path]) -> tuple[dict, Optional[sqlite3.Connection]]:
    """Payload and store, or `(…, None)` if either is unusable. Shared by both hooks.

    Fails open in every direction, for the reason at the top of this file: a hook that
    cannot read its payload or its store must let the turn proceed.
    """
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return {}, None
    if db_path is None or not Path(db_path).exists():
        return payload, None
    try:
        return payload, store.connect(path=Path(db_path))
    except Exception:                            # noqa: BLE001 — no store, no enforcement
        return payload, None


def run(stdin_text: str, db_path: Optional[Path] = None) -> dict[str, Any]:
    """The `Stop` hook: payload in, hook response out. Never raises, never blocks on error.

    The response shape is the one the CLI honours, verified by running it: a `block`
    decision on stdout with exit 0. An empty object lets the turn end.

    `db_path` is the store the spawn named in the settings file. Falling back to resolving
    it from the cwd would be resolving it from wherever the agent happens to stand.

    **The gate decides first, and the idle mark is written only if it is letting the turn
    end.** That order is the whole of the composition and it is the likeliest bug in the
    activity signal, so it is worth stating why: a blocked stop is not the end of a turn.
    The agent is handed `BLOCK_REASON` and keeps going — same session, same turn, more
    tool calls — and `UserPromptSubmit` does NOT fire again for it, because nothing new was
    submitted. Marking idle there would say a working agent is free, which is precisely the
    lie this signal was built to stop telling: its mail would be delivered mid-turn, the
    reconciler would ping it to ask why its turn ended, and the board would show it idle
    while it worked. When that continued turn finally does end, this runs again with
    `stop_hook_active` set, the gate returns None, and the mark is written then.

    A hook that cannot open the store writes nothing and blocks nothing. The signal then
    keeps whatever it last said, which for a turn that is ending means it says `working`
    for longer than it should — the same shape as the crash case, and covered by the same
    cross-check (`status.AgentStatus.signal_drift`).
    """
    payload, db = _open(stdin_text, db_path)
    if db is None:
        return {}
    try:
        reason = stop_gate(payload, db)
        if reason is None:
            # The turn really is ending. See the docstring: order is load-bearing.
            mark_turn(payload, db, store.TURN_IDLE)
    except Exception:                            # noqa: BLE001 — never trap an agent
        return {}
    finally:
        db.close()
    return {"decision": "block", "reason": reason} if reason else {}


def run_activity(stdin_text: str, db_path: Optional[Path] = None) -> None:
    """The `UserPromptSubmit` hook: a turn is beginning. Returns nothing, on purpose.

    Nothing is printed by its entry point either, and that is not tidiness: on
    `UserPromptSubmit` the CLI adds a hook's stdout to the agent's CONTEXT. Anything this
    said would be read by the agent as an instruction arriving with its task.
    """
    payload, db = _open(stdin_text, db_path)
    if db is None:
        return
    try:
        mark_turn(payload, db, store.TURN_WORKING)
    except Exception:                            # noqa: BLE001 — never trap an agent
        return
    finally:
        db.close()
