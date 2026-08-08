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


def store_dir(cwd: Optional[Path] = None) -> Path:
    """The shared directory under this repo's `.git` — the store's, and its neighbours'.

    Everything keyed on repo identity lands here: `state.db`, `config.json`, and each
    enabled plugin's state directory. Named once, rather than assembled from
    `_STORE_DIRNAME` at three call sites.
    """
    return repo_root(cwd) / _STORE_DIRNAME


def db_path(cwd: Optional[Path] = None) -> Path:
    return store_dir(cwd) / "state.db"


def config_path(cwd: Optional[Path] = None) -> Path:
    """Local config beside the store — shared by every worktree, never committed.

    Deliberately NOT in the store's `meta` table: the database is disposable by design
    and gets dropped on a schema change, whereas this must survive that.
    """
    return store_dir(cwd) / "config.json"


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
    workspace     TEXT,               -- the workspace NAME. A label, nothing more: it is
                                      -- not evidence of a checkout, and must never be
                                      -- read as one (see `branch`).
    branch        TEXT,               -- the git branch of the worktree this workspace
                                      -- sits on. NULL means BARE: a place to work with no
                                      -- checkout of its own. This is the fact "does this
                                      -- agent have a worktree?" — asked of the store, not
                                      -- inferred from the name, which is a branch for a
                                      -- worktree space and an agent-ish label for a bare
                                      -- one, with nothing to tell the two apart.
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

# A cache key, NOT a version. It covers the SCHEMA string verbatim, so editing a comment
# in it changes the hash — which is fine, and was not always: while this gated the store,
# a comment edit was enough to trigger a wipe-or-refuse. It now means only "the store was
# last stamped by different source text, go and look at its actual shape" (`_reconcile`).
# Compatibility is decided by `_deficit`, which asks whether the store CONTAINS what this
# code needs. That is the question that survives two checkouts sharing one store.
_SCHEMA_HASH = hashlib.sha256(SCHEMA.encode()).hexdigest()[:16]

LIVE_STATES = tuple(config.setting("states.live"))


class LiveAgentsError(RuntimeError):
    """A rebuild was asked for while agents are still running, and refused.

    Only ever surfaces to a caller who asked for a rebuild by name (`sb doctor
    --reset-store`). `_reconcile` catches it and keeps serving the old store instead,
    because a refusal that reaches `connect()` reaches every command there is.
    """


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def connect(cwd: Optional[Path] = None, *, path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the store, reconciling the schema as needed. NEVER raises over a schema change.

    Compatibility is judged structurally, not by version equality: a store is usable if it
    *contains* what this code needs. Extra columns are fine, missing ones are added where
    SQLite allows it, and a genuinely destructive difference defers a rebuild rather than
    forcing one — see `_reconcile`. `connect()` is what every `sb` command calls, including
    the `sb done` an agent needs to stop being live, so nothing decided here may be able to
    stop a fleet from draining itself.
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
        # The hash is a cache key, not a gate: an unequal one only means "look properly",
        # and `_reconcile` decides on the actual shape of the store. A comment edit, or a
        # column another checkout added, therefore costs one PRAGMA sweep and nothing else.
        # `cwd` goes along for the backfills, which need to know which checkout is asking.
        _reconcile(db, cwd)
    return db


def _reconcile(db: sqlite3.Connection, cwd: Optional[Path] = None) -> None:
    """Bring the store up to what this code needs — or defer, never deadlock.

    Three outcomes, in order of how much they cost:

    - nothing missing (only cosmetic drift, or columns a newer `sb` added): stamp and go;
    - everything missing can be ALTERed in: add the columns, stamp, and go;
    - something missing cannot be added to existing rows: the store has to be rebuilt, and
      a rebuild under a live fleet is exactly the deadlock this module exists to avoid. So
      it happens only when nothing is live, and otherwise the OLD store is left open and
      unstamped — degraded, still serving every command that fits inside it, and rebuilt
      by whichever `sb` runs first after the last agent finishes.

    Deliberately not stamped in the degraded case: the unstamped hash is what makes the
    next process retry, which is how the fleet's own draining clears this without anyone
    noticing it happened.

    A column that means something for the rows that predate it gets its `_BACKFILLS` entry
    run right after its own ALTER — inside the same "nothing is blocking" branch, so a
    deferred rebuild never half-fills anything.
    """
    addable, blocking = _deficit(db)
    if not blocking:
        for table, name, decl in addable:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            fill = _BACKFILLS.get((table, name))
            if fill:
                fill(db, cwd)
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', ?)",
                   (_SCHEMA_HASH,))
        db.commit()
        return
    try:
        _reset(db)
    except LiveAgentsError:
        pass                                   # degraded; see `schema_deficit`


def schema_deficit(db: sqlite3.Connection) -> list[str]:
    """What this code needs and this store cannot give it. Empty when all is well.

    Non-empty means `connect()` chose to keep a live fleet alive on an older store rather
    than rebuild underneath it. Callers use this to refuse the few commands that would
    write into what is missing — NOT to refuse everything, which is the whole bug.

    Every `sb` invocation asks this, so the stamp is the fast path: it is written only
    where the store has just been brought up to date, and the degraded case deliberately
    leaves it alone — so a matching stamp already means there is nothing to report.
    """
    row = db.execute("SELECT value FROM meta WHERE key='schema_hash'").fetchone()
    if row is not None and row["value"] == _SCHEMA_HASH:
        return []
    return _deficit(db)[1]


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


def _backfill_branch(db: sqlite3.Connection, cwd: Optional[Path]) -> None:
    """Give the rows that predate `agents.branch` the branch they have always been on.

    A row recorded a workspace name and the cwd it ran in, and that pair is enough: a
    worktree space runs in its OWN checkout, while the one bare space in the model — the
    root orchestrator's, over the main checkout — runs in the primary one. So every row in
    a named workspace outside the primary checkout was in a worktree, and its workspace
    name is its branch (the name is used verbatim as the branch when one is forked).

    Wrong in one direction only, and deliberately: an old `sb workspace new main`, which
    attaches to the primary checkout rather than forking, reads back as bare. A child of
    it then forks its own worktree instead of writing into the main checkout — the safe
    way to be wrong, and what the model wants anyway.

    Best effort. If we cannot say where the primary checkout is, leave every branch NULL:
    "no worktree" costs a fork, "a worktree that isn't there" costs somebody's main
    checkout.
    """
    try:
        primary = main_checkout(cwd).resolve()
    except Exception:                              # noqa: BLE001 — not a repo, no answer
        return
    rows = db.execute(
        "SELECT name, cwd, workspace FROM agents "
        "WHERE workspace IS NOT NULL AND cwd IS NOT NULL"
    ).fetchall()
    # Resolved, not string-compared: a recorded cwd and the main checkout routinely differ
    # by a symlink (`/var` vs `/private/var` on macOS) while naming one directory, and
    # that difference would read as "a worktree of its own".
    for r in rows:
        if Path(r["cwd"]).resolve() != primary:
            db.execute("UPDATE agents SET branch=? WHERE name=?",
                       (r["workspace"], r["name"]))


# Columns that mean something for rows written before they existed. Keyed by
# (table, column), run once, right after the ALTER that added them — see `_reconcile`.
_BACKFILLS = {("agents", "branch"): _backfill_branch}


def _deficit(db: sqlite3.Connection) -> tuple[list, list]:
    """What this code needs that the store lacks: `(addable, blocking)`.

    `addable` is a plan of `(table, column, decl)` triples that ALTER TABLE can apply in
    place. `blocking` is a list of human-readable gaps that it cannot — a table that does
    not exist at all, or a NOT NULL column with no literal default, which SQLite refuses to
    add to existing rows. Only a non-empty `blocking` can ever cost anyone their store.

    Nothing here compares the store to the schema for *equality*. It asks the narrower and
    much safer question — is everything this code reads and writes present? — because the
    store is shared by every worktree of the repo, so it is routinely met by code both
    older and newer than whatever last wrote it.
    """
    wanted = _wanted()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    plan, blocking = [], []
    for table, cols in wanted.items():
        if table not in tables:
            blocking.append(f"table {table} is missing")
            continue                           # its columns are the table's problem
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
                blocking.append(f"{table}.{name} cannot be added to existing rows")
            else:
                plan.append((table, name, decl))
    return plan, blocking


def _create(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
    db.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_hash', ?)", (_SCHEMA_HASH,)
    )
    db.commit()


def reset(db: sqlite3.Connection, *, force: bool = False) -> None:
    """Drop and recreate the schema, on purpose. `sb doctor --reset-store`.

    The public face of `_reset`, which `_reconcile` also reaches for. Named in the
    LiveAgentsError that refusal raises, because a way out that nothing offers is not a
    way out.
    """
    _reset(db, force=force)


def _reset(db: sqlite3.Connection, *, force: bool = False) -> None:
    """Recreate the schema.

    The live-agent guard exists so a schema change cannot pull the floor out from under a
    running workflow. Refusing is safe HERE and nowhere else: `_reconcile` catches the
    refusal and keeps serving the old store, so the only caller that ever surfaces it to a
    human is the one that asked for a reset by name. It used to escape into `connect()`,
    which every `sb` command calls — including the `sb done` an agent needs in order to
    stop being 'live' — and wedged a whole fleet.

    Three things keep the guard honest:
      - liveness is checked against **herdr**, not the store, because store state drifts
        (an agent that finished without reporting still reads as 'working' forever);
      - a store with no `agents` table has nothing to protect, so it never blocks;
      - `force` exists, and the error says so.
    """
    try:
        live = [r["name"] for r in db.execute(
            f"SELECT name FROM agents WHERE state IN {LIVE_STATES} AND ended_at IS NULL"
        ).fetchall()]
    except sqlite3.OperationalError:
        live = []                              # no agents table: nothing is running
    if live and not force:
        live = [n for n in live if n in _herdr_alive()]
    if live and not force:
        raise LiveAgentsError(
            "the store's schema changed under a running fleet: "
            + ", ".join(live)
            + "\nThey keep working on the old store, which is rebuilt automatically once"
              "\nthe last one finishes. To rebuild NOW and lose their state:"
              "\n  sb doctor --reset-store --force"
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
       (name, parent, role, task, state, session_id, cwd, workspace, branch,
        workspace_id, terminal_id, pane_id, cleanup, created_at)
       VALUES (?,?,?,?,'working',?,?,?,?,?,?,?,?,?)"""


def _agent_values(
    name: str, role: str, parent, task, session_id, cwd, workspace, branch, workspace_id,
    terminal_id, pane_id, cleanup,
) -> tuple:
    return (name, parent, role, task, session_id, cwd, workspace, branch, workspace_id,
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
    branch: Optional[str] = None,
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
        _agent_values(name, role, parent, task, session_id, cwd, workspace, branch,
                      workspace_id, terminal_id, pane_id, cleanup),
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
    branch: Optional[str] = None,
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
        _agent_values(name, role, parent, task, session_id, cwd, workspace, branch,
                      workspace_id, terminal_id, pane_id, cleanup),
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


def agent_branch(db: sqlite3.Connection, name: str) -> Optional[str]:
    """The branch of the worktree this agent works in. None = it has no worktree.

    THE question the fork rule asks ("does my parent have a worktree?"), answered as a
    fact rather than by reading the workspace name — which says branch for one kind of
    space and says nothing at all for the other.
    """
    row = get_agent(db, name)
    return row["branch"] if row is not None else None


def workspace_branch(db: sqlite3.Connection, workspace: str) -> Optional[str]:
    """The branch of the worktree a NAMED workspace sits on. None = bare, or unknown.

    A property of the workspace, not of any one agent in it: every agent in a worktree
    space shares its checkout, so the first row that recorded a branch answers for all of
    them. That is also how a child picks up the branch it inherits.
    """
    row = db.execute(
        "SELECT branch FROM agents WHERE workspace=? AND branch IS NOT NULL "
        "ORDER BY created_at LIMIT 1", (workspace,)
    ).fetchone()
    return row["branch"] if row else None


def known_workspace(db: sqlite3.Connection, workspace: str) -> bool:
    """Have we ever recorded an agent in this workspace?

    What tells "bare" apart from "never heard of it": `workspace_branch` returns None for
    both, and they deserve different answers — one is a place with no checkout, the other
    is a name we know nothing about.
    """
    return db.execute(
        "SELECT 1 FROM agents WHERE workspace=? LIMIT 1", (workspace,)
    ).fetchone() is not None


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
    allowed = {"session_id", "cwd", "workspace", "branch", "workspace_id", "terminal_id",
               "pane_id", "cleanup", "task"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {bad}")
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE agents SET {sets} WHERE name=?", (*fields.values(), name))
    db.commit()


def mark_spawned(db: sqlite3.Connection, name: str) -> None:
    """The claim became a real agent: it is `working`, and it has not ended.

    Separate from `update_agent` because `state` and `ended_at` are deliberately NOT in
    that allowlist — nothing should be able to rewrite an end as a side effect of
    recording a pane id. This is the one narrow exception, and it exists because the row
    can be closed UNDER a spawn that is still in flight: `delegate` claims the row before
    herdr is called, `agent start` retries a flaky first attempt for seconds, and any
    `status.collect` in that window sees a running row herdr does not know yet and reaps
    it (`status._record_gone`). The reaper now holds off for the spawn window too, so this
    is the second of two guards rather than the only one — but it is the one that repairs
    a row already wrongly closed, which no reaper grace can do after the fact.

    Only ever called on the success path of a spawn, where `working` is the truth by
    construction: herdr has just returned an agent.
    """
    db.execute(
        "UPDATE agents SET state='working', ended_at=NULL WHERE name=?", (name,)
    )
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
    caused one spawn failure during validation. What IS swallowed is the log's own failure
    to write: on a degraded store (see `schema_deficit`) this table may not exist yet, and
    an audit trail that can take down the `sb done` it was trying to record is worth less
    than no audit trail at all. Every herdr call routes through here.
    """
    try:
        db.execute(
            "INSERT INTO events (agent, kind, payload, created_at) VALUES (?,?,?,?)",
            (agent, kind, json.dumps(payload, default=str) if payload else None, now()),
        )
        db.commit()
    except sqlite3.OperationalError:
        pass


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
