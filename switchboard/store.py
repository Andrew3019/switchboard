"""M1 — the store.

The single source of truth. Every other module is a view over this; modules never call
each other, they meet here (C7).

Three tables, all *operational* state. The only durable data (learnings) lives in JSON
files, so this database is disposable by construction — see `connect()` for what that
buys us.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config

# How long sqlite waits on a busy database, and how long any git call gets before it is
# treated as hung. Many short-lived `sb` processes write to one file, so contention is the
# normal case and waiting is the right response to it. `[timeouts]` in settings.toml.
_DB_TIMEOUT = config.setting("timeouts.database")
_SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

# `.git` is already shared across every worktree of a repo, so a store placed here is
# automatically visible from all workspaces. That is required, not a convenience: the
# top-level orchestrator lives on `main` while its children live in worktrees, and they
# must share a store for parent links to survive.
#
# Resolved by the tool, never by an agent (P0).

_STORE_DIRNAME = config.setting("paths.store_dirname")


def repo_root(cwd: Optional[Path] = None) -> Path:
    """The shared `.git` directory for this repo, valid from any worktree."""
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"not inside a git repo: {out.stderr.strip()}")
    # git returns this RELATIVE to the directory it ran in (often just ".git").
    # Path.resolve() would anchor it to the *process* cwd instead, silently handing back
    # a different repo's store — so anchor it explicitly.
    base = Path(cwd) if cwd else Path.cwd()
    common = Path(out.stdout.strip())
    return (common if common.is_absolute() else base / common).resolve()


def worktree_root(cwd: Optional[Path] = None) -> Path:
    """The working tree we are actually standing in.

    Distinct from `repo_root()`: that returns the shared `.git`, so every worktree finds
    the SAME store. This returns THIS worktree. Agents and roles must use this one, or
    work done in a worktree would land in the main checkout.
    """
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd) if cwd else None, capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"not inside a git repo: {out.stderr.strip()}")
    return Path(out.stdout.strip()).resolve()


def db_path(cwd: Optional[Path] = None) -> Path:
    return repo_root(cwd) / _STORE_DIRNAME / "state.db"


def config_path(cwd: Optional[Path] = None) -> Path:
    """Local config beside the store — shared by every worktree, never committed.

    Deliberately NOT in the store's `meta` table: the database is disposable by design
    and gets dropped on a schema change, whereas this must survive that.
    """
    return repo_root(cwd) / _STORE_DIRNAME / "config.json"


def read_config(cwd: Optional[Path] = None) -> dict:
    p = config_path(cwd)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def write_config(values: dict, cwd: Optional[Path] = None) -> Path:
    p = config_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = read_config(cwd)
    cfg.update(values)
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    return p


def main_checkout(cwd: Optional[Path] = None) -> Path:
    """Where the true config files live.

    Recorded by `sb init` rather than inferred: `.git`'s parent is only the main checkout
    for an ordinary layout, and is wrong under --separate-git-dir or a relocated .git.
    Falls back to the inference so an un-inited repo still works.
    """
    recorded = read_config(cwd).get("main_checkout")
    if recorded and Path(recorded).exists():
        return Path(recorded)
    return repo_root(cwd).parent


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE agents (
    name          TEXT PRIMARY KEY,   -- how everything addresses an agent (never an opaque id)
    parent        TEXT,               -- NULL = root. Tree, not graph (C1). No edges table.
    role          TEXT NOT NULL,
    task          TEXT,
    state         TEXT NOT NULL,      -- working | blocked | done | failed
    session_id    TEXT,               -- the agent's OWN session id; how `sb` knows who is calling
    cwd           TEXT,               -- needed to resolve the on-disk transcript
    workspace     TEXT,
    workspace_id  TEXT,               -- herdr's id for that workspace. Authoritative:
                                      -- resolving a name to an id is one-to-many, so a
                                      -- child spawned from a re-derived id lands in the
                                      -- wrong workspace. May be NULL for older rows.
    terminal_id   TEXT,               -- STABLE herdr handle
    pane_id       TEXT,               -- NOT stable across pane move; debugging only
    seq           INTEGER NOT NULL DEFAULT 0,  -- our monotonic --seq for herdr writes
    cleanup       TEXT NOT NULL DEFAULT 'close',
    created_at    INTEGER NOT NULL,
    ended_at      INTEGER
);
CREATE INDEX idx_agents_session ON agents(session_id);
CREATE INDEX idx_agents_parent  ON agents(parent);

CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent    TEXT NOT NULL,
    to_agent      TEXT NOT NULL,
    kind          TEXT NOT NULL,      -- ask | tell | done
    body          TEXT NOT NULL,
    reply_to      INTEGER REFERENCES messages(id),
    created_at    INTEGER NOT NULL,
    read_at       INTEGER,
    delivered_at  INTEGER
);
CREATE INDEX idx_msgs_inbox ON messages(to_agent, read_at);
CREATE INDEX idx_msgs_undelivered ON messages(to_agent, delivered_at);
CREATE INDEX idx_msgs_reply ON messages(reply_to);

CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent         TEXT,
    kind          TEXT NOT NULL,
    payload       TEXT,               -- JSON
    created_at    INTEGER NOT NULL
);
CREATE INDEX idx_events_agent ON events(agent, id);
"""

_SCHEMA_HASH = hashlib.sha256(SCHEMA.encode()).hexdigest()[:16]

LIVE_STATES = tuple(config.setting("states.live"))


class LiveAgentsError(RuntimeError):
    """Schema changed while agents are still running."""


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def connect(cwd: Optional[Path] = None, *, path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the store, creating or resetting the schema as needed.

    There are no migrations. Everything in here is operational state, so on a schema
    change we simply drop and recreate — unless agents are live, in which case we refuse
    rather than pull the floor out from under a running workflow.
    """
    p = path or db_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(p), timeout=_DB_TIMEOUT)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")       # many short-lived `sb` processes writing
    db.execute(f"PRAGMA busy_timeout={int(_DB_TIMEOUT * 1000)}")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    row = db.execute("SELECT value FROM meta WHERE key='schema_hash'").fetchone()
    if row is None:
        _create(db)
    elif row["value"] != _SCHEMA_HASH:
        # Additive changes migrate in place. Only a destructive change falls through to a
        # reset — and a reset while agents are running is a deadlock, because `connect()`
        # is what every `sb` command calls, including the `sb done` an agent would need to
        # stop being 'live'. Observed exactly that: one agent added a column and wedged
        # every other agent on the machine.
        if not _migrate_additive(db):
            _reset(db)
    return db


def _columns(db: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def _wanted() -> dict:
    out = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", SCHEMA, re.S):
        cols = {}
        for line in m.group(2).splitlines():
            # strip the comment BEFORE the trailing comma, or the comma survives into
            # the column declaration and ALTER TABLE fails on it
            line = line.split("--")[0].strip().rstrip(",").strip()
            if not line:
                continue
            parts = line.split()
            if parts:
                cols[parts[0]] = " ".join(parts[1:])
        out[m.group(1)] = cols
    return out


def _migrate_additive(db: sqlite3.Connection) -> bool:
    """Add missing columns. Returns False if anything non-additive differs.

    SQLite cannot ADD COLUMN with a non-constant default, so a NOT NULL column without a
    literal default is treated as non-additive and falls through to a reset.
    """
    wanted = _wanted()
    plan = []
    for table, cols in wanted.items():
        if table not in {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}:
            return False                       # a whole new table: rebuild
        have = _columns(db, table)
        # Columns in the store that this code does not know about are LEFT ALONE. They are
        # not evidence of a removal — far more often they are a newer `sb`, run from another
        # checkout against the same store, that added one. Two checkouts share one store, so
        # migrations have to survive being met by older code; treating an unknown column as
        # destructive is what wedged the whole machine once already (see `connect`). Nothing
        # here reads by position — every INSERT names its columns and rows are read by name
        # — so an extra column costs us nothing. A genuine removal is the newer code's to
        # handle, on the side that knows the column is gone.
        for name, decl in cols.items():
            if name in have:
                continue
            if "NOT NULL" in decl.upper() and "DEFAULT" not in decl.upper():
                return False                   # cannot be added to existing rows
            plan.append((table, name, decl))
    for table, name, decl in plan:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', ?)",
               (_SCHEMA_HASH,))
    db.commit()
    return True


def _create(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
    db.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', ?)", (_SCHEMA_HASH,)
    )
    db.commit()


def reset(db: sqlite3.Connection, *, force: bool = False) -> None:
    """Drop and recreate the schema, on purpose. `sb doctor --reset-store`.

    The public face of `_reset`, which `connect()` also reaches for when a schema change
    is not additive. Named in the LiveAgentsError that refusal raises, because a way out
    that nothing offers is not a way out.
    """
    _reset(db, force=force)


def _reset(db: sqlite3.Connection, *, force: bool = False) -> None:
    """Recreate the schema.

    The live-agent guard exists so a schema change cannot pull the floor out from under a
    running workflow. But it must never become a deadlock: `connect()` is what every `sb`
    command calls, so refusing here brakes *every* agent — including the ones that would
    have to run `sb done` to stop being 'live'. Observed exactly that.

    Two things keep the guard honest:
      - liveness is checked against **herdr**, not the store, because store state drifts
        (an agent that finished without reporting still reads as 'working' forever);
      - `force` exists, and the error says so.
    """
    live = [r["name"] for r in db.execute(
        f"SELECT name FROM agents WHERE state IN {LIVE_STATES} AND ended_at IS NULL"
    ).fetchall()]
    if live and not force:
        live = [n for n in live if n in _herdr_alive()]
    if live and not force:
        raise LiveAgentsError(
            "the schema changed but these agents are still running: "
            + ", ".join(live)
            + "\nLet them finish, or: sb doctor --reset-store --force"
        )
    for t in ("agents", "messages", "events"):
        db.execute(f"DROP TABLE IF EXISTS {t}")
    _create(db)


def _herdr_alive() -> set:
    """Agent names herdr currently knows about. Empty on any failure — an unreachable
    herdr must not be able to wedge the store."""
    try:
        p = subprocess.run(
            [str(Path.home() / ".local/bin/herdr"), "agent", "list"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        return {a.get("name") for a in json.loads(p.stdout)["result"]["agents"]
                if a.get("name")}
    except Exception:
        return set()


def now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


_INSERT_AGENT = """INSERT {or_ignore} INTO agents
       (name, parent, role, task, state, session_id, cwd, workspace, workspace_id,
        terminal_id, pane_id, cleanup, created_at)
       VALUES (?,?,?,?,'working',?,?,?,?,?,?,?,?)"""


def _agent_values(
    name: str, role: str, parent, task, session_id, cwd, workspace, workspace_id,
    terminal_id, pane_id, cleanup,
) -> tuple:
    return (name, parent, role, task, session_id, cwd, workspace, workspace_id,
            terminal_id, pane_id, cleanup, now())


def create_agent(
    db: sqlite3.Connection,
    *,
    name: str,
    role: str,
    parent: Optional[str] = None,
    task: Optional[str] = None,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    workspace: Optional[str] = None,
    workspace_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
    pane_id: Optional[str] = None,
    cleanup: str = "close",
) -> sqlite3.Row:
    """Insert an agent row. Raises `sqlite3.IntegrityError` if the name is taken.

    Anything that might be racing another opener for the same name wants `claim_agent`
    instead — this one is for the case where the caller already knows the name is free.
    """
    db.execute(
        _INSERT_AGENT.format(or_ignore=""),
        _agent_values(name, role, parent, task, session_id, cwd, workspace, workspace_id,
                      terminal_id, pane_id, cleanup),
    )
    db.commit()
    return get_agent(db, name)


def claim_agent(
    db: sqlite3.Connection,
    *,
    name: str,
    role: str,
    parent: Optional[str] = None,
    task: Optional[str] = None,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    workspace: Optional[str] = None,
    workspace_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
    pane_id: Optional[str] = None,
    cleanup: str = "close",
) -> bool:
    """Take the name, or find out somebody else already has it. -> did we get it?

    `agents.name` is a PRIMARY KEY, and that index is the only arbiter two concurrent
    openers of one workspace share. So the claim has to BE the insert: a
    `get_agent(...) or create_agent(...)` check-then-act is two statements with a race
    between them, and it lost that race about once in twenty-five workspace opens (both
    faces — an IntegrityError and a lost `created` count — are written up in BUGS.md).

    False means join the winner rather than start a rival, which is the same "what is
    already there is somewhere to go" rule the rest of the workspace code follows.
    """
    cur = db.execute(
        _INSERT_AGENT.format(or_ignore="OR IGNORE"),
        _agent_values(name, role, parent, task, session_id, cwd, workspace, workspace_id,
                      terminal_id, pane_id, cleanup),
    )
    db.commit()
    return cur.rowcount == 1


def drop_agent(db: sqlite3.Connection, name: str) -> None:
    """Remove a row. Only ever used to undo a claim whose spawn then failed — otherwise
    an agent that never started would hold its name against every later attempt."""
    db.execute("DELETE FROM agents WHERE name=?", (name,))
    db.commit()


def get_agent(db: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return db.execute("SELECT * FROM agents WHERE name=?", (name,)).fetchone()


def agent_by_session(db: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    """The agent that owns a Claude session id.

    NOT how identity is resolved — `Broker.whoami` matches on `HERDR_PANE_ID`, which is
    injected into every pane and therefore works before an agent has done anything and for
    agents we did not spawn. Session id is what `restore` resumes and what locates the
    on-disk transcript; it is recorded by `Broker._claim_session` on first call, so it is
    absent for exactly as long as it would take an identity lookup to need it.

    Kept as the reverse of that recording (a transcript path in hand, which agent is it?),
    and indexed for it. Nothing in the tree calls it today.
    """
    return db.execute(
        "SELECT * FROM agents WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()


def children_of(db: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM agents WHERE parent=? ORDER BY created_at", (name,)
    ).fetchall()


def live_agents(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        f"SELECT * FROM agents WHERE state IN {LIVE_STATES} AND ended_at IS NULL"
    ).fetchall()


def live_roots(db: sqlite3.Connection, role: str) -> list[sqlite3.Row]:
    """`live_agents`, narrowed to roots of one role and ordered oldest first.

    The store keeps every root ever created, so the same query without the state and
    `ended_at` filters is a *history* — which is how `sb start` came to announce five
    finished orchestrators as already running.

    Still only the store's word. A row leaves `working` when the agent itself reports it,
    so a crashed one reads as live here forever; the caller is the one who has to ask
    herdr (see `Broker._running_tops`).
    """
    return db.execute(
        f"SELECT * FROM agents WHERE parent IS NULL AND role=? "
        f"AND state IN {LIVE_STATES} AND ended_at IS NULL ORDER BY created_at",
        (role,),
    ).fetchall()


def set_state(db: sqlite3.Connection, name: str, state: str) -> None:
    ended = now() if state in ("done", "failed") else None
    db.execute(
        "UPDATE agents SET state=?, ended_at=COALESCE(?, ended_at) WHERE name=?",
        (state, ended, name),
    )
    db.commit()


def update_agent(db: sqlite3.Connection, name: str, **fields: Any) -> None:
    allowed = {"session_id", "cwd", "workspace", "workspace_id", "terminal_id",
               "pane_id", "cleanup", "task"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {bad}")
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE agents SET {sets} WHERE name=?", (*fields.values(), name))
    db.commit()


def next_seq(db: sqlite3.Connection, name: str) -> int:
    """The `--seq` for our next herdr state write.

    Must be strictly increasing per agent. herdr silently DROPS a stale or missing seq
    while still returning ok, so a mistake here shows up as a stale badge rather than an
    error. Scoped per (source, pane), so a plain per-agent counter is sufficient.
    """
    cur = db.execute(
        "UPDATE agents SET seq = seq + 1 WHERE name=? RETURNING seq", (name,)
    ).fetchone()
    db.commit()
    if cur is None:
        raise KeyError(f"no such agent: {name}")
    return cur["seq"]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def put_message(
    db: sqlite3.Connection,
    *,
    from_agent: str,
    to_agent: str,
    kind: str,
    body: str,
    reply_to: Optional[int] = None,
) -> int:
    if kind not in ("ask", "tell", "done"):
        raise ValueError(f"bad message kind: {kind}")
    cur = db.execute(
        """INSERT INTO messages (from_agent, to_agent, kind, body, reply_to, created_at)
           VALUES (?,?,?,?,?,?)""",
        (from_agent, to_agent, kind, body, reply_to, now()),
    )
    db.commit()
    return int(cur.lastrowid)


def unread_for(db: sqlite3.Connection, name: str, *, mark: bool = True) -> list[sqlite3.Row]:
    """All unread messages, marked read in one shot.

    Returning everything at once rather than one-at-a-time is deliberate: a per-message
    loop costs the agent a turn each, and turns are the expensive thing (C0).
    """
    rows = db.execute(
        "SELECT * FROM messages WHERE to_agent=? AND read_at IS NULL ORDER BY id", (name,)
    ).fetchall()
    if rows and mark:
        db.execute(
            "UPDATE messages SET read_at=? WHERE to_agent=? AND read_at IS NULL",
            (now(), name),
        )
        db.commit()
    return rows


def undelivered(db: sqlite3.Connection, *, exclude: Iterable[str] = ()) -> list[sqlite3.Row]:
    """Messages written but never announced, oldest first.

    A message is only 'delivered' once we have rung the target's doorbell. We hold the
    ring back while the target is mid-turn, because `agent prompt` INTERLEAVES — it is
    injected into the current turn rather than queued after it — so ringing a working
    agent interrupts whatever it was doing.

    `exclude` is for addresses that are not agents and have no doorbell. The human is the
    only one: nothing is addressed to them any more (they have no mailbox — see
    broker.block), but a store written before that still holds such rows, and no ring was
    ever going to come for them. Passed in rather than written here because what the human
    is CALLED is `[vocabulary]`.
    """
    names = list(exclude)
    holes = ",".join("?" * len(names))
    return db.execute(
        "SELECT * FROM messages WHERE delivered_at IS NULL"
        + (f" AND to_agent NOT IN ({holes})" if names else "")
        + " ORDER BY id",
        names,
    ).fetchall()


def mark_collected(db: sqlite3.Connection, mid: int) -> None:
    """One message, both read and announced — because it is neither, and never will be.

    An answer to a pending `ask` is collected by the blocked caller as that call's return
    value. There is no doorbell to ring and no inbox visit to wait for, so leaving the row
    unread would pin the asker (`cleanup` refuses to close an agent holding unread mail)
    and leaving it undelivered would have `flush_pending` ring for it later.
    """
    db.execute(
        "UPDATE messages SET read_at=COALESCE(read_at, ?), "
        "delivered_at=COALESCE(delivered_at, ?) WHERE id=?",
        (now(), now(), mid),
    )
    db.commit()


def mark_delivered(db: sqlite3.Connection, to_agent: str) -> int:
    cur = db.execute(
        "UPDATE messages SET delivered_at=? WHERE to_agent=? AND delivered_at IS NULL",
        (now(), to_agent),
    )
    db.commit()
    return cur.rowcount


def get_message(db: sqlite3.Connection, mid: int) -> Optional[sqlite3.Row]:
    return db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()


def pending_ask(db: sqlite3.Connection, *, asker: str, target: str) -> Optional[sqlite3.Row]:
    """The most recent unanswered `ask` from `asker` to `target`.

    This is what lets a plain `tell` satisfy a blocking `ask` — correlation is the tool's
    job, never the agent's (P0), which is why there is no `reply` verb.
    """
    return db.execute(
        """SELECT m.* FROM messages m
           WHERE m.from_agent=? AND m.to_agent=? AND m.kind='ask'
             AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.reply_to = m.id)
           ORDER BY m.id DESC LIMIT 1""",
        (asker, target),
    ).fetchone()


def reply_to_ask(db: sqlite3.Connection, ask_id: int) -> Optional[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM messages WHERE reply_to=? ORDER BY id LIMIT 1", (ask_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Events  (the debug log)
# ---------------------------------------------------------------------------


def log_event(
    db: sqlite3.Connection, *, kind: str, agent: Optional[str] = None, **payload: Any
) -> None:
    """Append-only. Every `sb` invocation lands here, including failures.

    Never swallow an adapter error — a discarded stderr is why we still cannot say what
    caused one spawn failure during validation.
    """
    db.execute(
        "INSERT INTO events (agent, kind, payload, created_at) VALUES (?,?,?,?)",
        (agent, kind, json.dumps(payload, default=str) if payload else None, now()),
    )
    db.commit()


def recent_events(
    db: sqlite3.Connection, *, agent: Optional[str] = None, limit: int = 50
) -> list[sqlite3.Row]:
    if agent:
        return db.execute(
            "SELECT * FROM events WHERE agent=? ORDER BY id DESC LIMIT ?", (agent, limit)
        ).fetchall()
    return db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------


def transcript_path(agent: sqlite3.Row) -> Optional[Path]:
    """Where Claude Code already wrote this agent's full transcript.

    Free debuggability: nothing is captured by us, and it survives pane close. Bucketed
    by cwd, which is why cwd is stored alongside the session id.
    """
    if not agent["session_id"] or not agent["cwd"]:
        return None
    slug = re.sub(r"[^a-zA-Z0-9]", "-", agent["cwd"])
    p = Path.home() / ".claude" / "projects" / slug / f"{agent['session_id']}.jsonl"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _main(argv: Optional[list[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m switchboard.store")
    ap.add_argument("cmd", nargs="?", default="info",
                    choices=["info", "agents", "messages", "events", "reset"])
    args = ap.parse_args(argv)

    p = db_path()
    print(f"store: {p}  ({'exists' if p.exists() else 'not created yet'})")
    db = connect()

    if args.cmd == "info":
        for t in ("agents", "messages", "events"):
            n = db.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            print(f"  {t:9} {n}")
        live = live_agents(db)
        print(f"  live      {len(live)}" + (f"  ({', '.join(r['name'] for r in live)})" if live else ""))
    elif args.cmd == "agents":
        for r in db.execute("SELECT * FROM agents ORDER BY created_at"):
            print(f"  {r['name']:20} role={r['role']:12} parent={r['parent'] or '-':12} {r['state']}")
    elif args.cmd == "messages":
        for r in db.execute("SELECT * FROM messages ORDER BY id"):
            flag = " " if r["read_at"] else "*"
            print(f" {flag}{r['id']:4} {r['from_agent']} -> {r['to_agent']} [{r['kind']}] {r['body'][:60]}")
    elif args.cmd == "events":
        for r in recent_events(db, limit=100)[::-1]:
            print(f"  {r['id']:4} {r['agent'] or '-':16} {r['kind']:16} {(r['payload'] or '')[:70]}")
    elif args.cmd == "reset":
        if live_agents(db):
            print("refusing: agents are live")
            return 1
        _reset(db)
        print("reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
