"""The Stop gate — C6 applied to reporting.

`sb done` is asked for by the protocol and, until this file existed, enforced by nothing:
an agent could end its turn silently and its work stayed invisible until a person noticed.
That happened four times on 2026-08-11. This is the mechanical half — a `Stop` hook that
refuses the end of a turn nobody reported.

Two pieces:

* `settings_file()` writes the per-repo settings JSON that carries the hook, and
  `stop_hook_args()` turns it into the `--settings <path>` every spawn passes. Only agents
  we spawn are handed the file, which is the whole of the isolation — an ordinary `claude`
  session never sees it, and no file of the human's is ever written to or read.
* `stop_gate()` is the decision, run once per turn end by `bin/sb-stop-hook`.

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


def _entry_point() -> Path:
    """The gate script belonging to THIS checkout of switchboard.

    Absolute on purpose. The hook runs in the agent's own worktree with the agent's own
    PATH, and the code that should decide is the code that spawned it — resolving `sb` at
    hook time would pick up whatever that pane happens to have.
    """
    return Path(__file__).resolve().parent.parent / "bin" / "sb-stop-hook"


def settings_file(cwd: Optional[Path] = None) -> Path:
    """Write (idempotently) the settings JSON that carries the Stop hook, and return it.

    Under the store directory, which is the shared `.git` — never in a worktree, never
    anywhere near `~/.claude`. Keyed by a hash of the gate's absolute path because that
    directory is shared by every worktree of the repo and each has its own `bin/`: one
    file per checkout, so a worktree that goes away cannot leave the others pointing at a
    script that no longer exists.

    Written tmp-then-rename: several spawns race here, and a half-written settings file is
    a session that will not start.
    """
    gate = _entry_point()
    tag = hashlib.sha256(str(gate).encode()).hexdigest()[:8]
    d = store.store_dir(cwd) / _SETTINGS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"stop-{tag}.json"
    # The store is named explicitly rather than resolved from the hook's cwd. An agent may
    # be standing anywhere — including inside another repo entirely — and a gate that
    # re-derived the store from where it happens to run would consult the wrong one, and
    # `connect()` would helpfully create it.
    body = json.dumps(
        {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    f"{shlex.quote(str(gate))} "
                                    f"--db {shlex.quote(str(store.db_path(cwd)))}"
                                ),
                                # Well over the gate's cost (one sqlite read); a timeout
                                # is a non-blocking failure, so this only ever fails open.
                                "timeout": 10,
                                "statusMessage": "checking for a report…",
                            }
                        ]
                    }
                ]
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


def stop_gate(payload: dict, db: sqlite3.Connection) -> Optional[str]:
    """The reason to refuse this turn's end, or None to let it end.

    The order of the checks is the design, so it is worth reading as a list.

    **`stop_hook_active` first, and unconditionally.** It is true only on a turn that this
    gate itself caused, which makes it the cap on the loop the gate could otherwise become:
    block a turn, the agent takes another, it ends, block again. At most ONE stop per
    stop-chain. A nudged agent that still will not report is then 3.5's problem — the
    reconciler names a stalled agent afterwards, which is the right division: the hook
    prevents the ordinary case, it does not fight the pathological one.

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
    store.log_event(db, kind="stop_gate_blocked", agent=a["name"])
    return BLOCK_REASON


def run(stdin_text: str, db_path: Optional[Path] = None) -> dict[str, Any]:
    """The whole hook: payload in, hook response out. Never raises, never blocks on error.

    The response shape is the one the CLI honours, verified by running it: a `block`
    decision on stdout with exit 0. An empty object lets the turn end.

    `db_path` is the store the spawn named in the settings file. Falling back to resolving
    it from the cwd would be resolving it from wherever the agent happens to stand.
    """
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return {}
    if db_path is None or not Path(db_path).exists():
        return {}
    try:
        db = store.connect(path=Path(db_path))
    except Exception:                            # noqa: BLE001 — no store, no enforcement
        return {}
    try:
        reason = stop_gate(payload, db)
    except Exception:                            # noqa: BLE001 — never trap an agent
        return {}
    finally:
        db.close()
    return {"decision": "block", "reason": reason} if reason else {}
