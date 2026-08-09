"""M1 — the store.

The single source of truth. Every other module is a view over this; modules never call
each other, they meet here (C7).

Four tables, all *operational* state. The only durable data (learnings) lives in JSON
files, so this database is disposable by construction — see `connect()` for what that
buys us.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
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
    awaiting_task INTEGER NOT NULL DEFAULT 0,   -- 1 = spawned with a placeholder task and
                                      -- given nothing since. Such an agent is idle because
                                      -- nobody has asked it for anything, which is not the
                                      -- same fact as STALLED, so the join in `status` does
                                      -- not compute that flag for it. Cleared by the first
                                      -- message it receives (`put_message`). The default is
                                      -- 0, which is also what rows predating the column
                                      -- read as: an ordinary agent, stalled-eligible.
    absent_since  INTEGER,            -- epoch of the FIRST reading that found herdr no
                                      -- longer listing this agent, cleared the moment it
                                      -- is listed again. One absent reading is a hiccup;
                                      -- staying absent is a death, and this is the only
                                      -- place that memory can live between two short-lived
                                      -- `sb` processes (see `status._record_gone`). NULL
                                      -- means "present, as far as anyone has looked",
                                      -- which is also what rows predating the column read
                                      -- as — their absence simply starts being counted the
                                      -- first time a reaping command looks at them.
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

CREATE TABLE workspaces (
    name          TEXT PRIMARY KEY,   -- the workspace NAME, and identity is nothing else.
                                      -- Not `workspace_id`: one id spans two checkouts on
                                      -- this machine and a live workspace can have none.
                                      -- Not the checkout path: every bare workspace over
                                      -- one clone shares it, so four live orchestrators
                                      -- would be one row and retiring any of them would
                                      -- retire the rest.
    checkout      TEXT,               -- where this workspace's own checkout is, or NULL.
                                      -- NULL is not "unknown": it is exactly how a BARE
                                      -- workspace — one with no checkout of its own — is
                                      -- represented, the same fact `agents.branch` says
                                      -- by being NULL. A recorded path is never trusted
                                      -- as a live one; see `checkout_verdict`.
    retired_at    INTEGER,            -- epoch the workspace was retired. Not a tombstone
                                      -- on the name: reopening one clears this.
    retiring      TEXT,               -- who holds the retiring mark — an agent name, not a
                                      -- boolean. Claimed by conditional write (see
                                      -- `claim_retiring`), so a losing invocation cannot
                                      -- release a mark it never held. Not a lock, and no
                                      -- lock primitive enters the tree for it.
    retiring_at   INTEGER,            -- epoch the mark was claimed, so a refusal can say
                                      -- how long a crashed one has been sitting there.
    created_at    INTEGER
);
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


def connect(
    cwd: Optional[Path] = None,
    *,
    path: Optional[Path] = None,
    readonly: bool = False,
) -> sqlite3.Connection:
    """Open the store, reconciling the schema as needed. NEVER raises over a schema change.

    Compatibility is judged structurally, not by version equality: a store is usable if it
    *contains* what this code needs. Extra columns are fine, missing ones are added where
    SQLite allows it, and a genuinely destructive difference defers a rebuild rather than
    forcing one — see `_reconcile`. `connect()` is what every `sb` command calls, including
    the `sb done` an agent needs to stop being live, so nothing decided here may be able to
    stop a fleet from draining itself.

    `readonly=True` is a different connection entirely — see `_connect_readonly`. Reconciling
    a schema is a WRITER's job, and this default path is where it happens.
    """
    if readonly:
        return _connect_readonly(path or db_path(cwd))
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


def _connect_readonly(p: Path) -> sqlite3.Connection:
    """A connection that CANNOT change the store, and never reconciles its schema.

    `connect()` is not a reader. It stamps `meta`, it CREATEs and ALTERs tables and
    backfills every agent row, and — when something missing can be given to no existing row
    — it rebuilds the store (`_reconcile` -> `_reset`). All three are correct for a
    short-lived `sb` running current code, and all three are wrong for something that merely
    wants to look: a process that connects every two seconds for hours is the likeliest
    migrator in the tree, running whatever `SCHEMA` string it happened to import at startup.
    Two checkouts on different branches sharing one store is the normal case here, and the
    SCHEMA text differing between them — a comment edit is enough — is what arms all of it.

    So a reader gets `mode=ro`, where sqlite itself is the guarantee rather than our
    discipline: every write, DDL included, raises `sqlite3.OperationalError: attempt to
    write a readonly database`. Loudly, not silently — a reader that quietly no-ops its
    way past a migration would be a worse bug than the one this fixes.

    A store this code is genuinely too old or too new for therefore surfaces as an
    OperationalError out of the query, which is the right answer for a viewer: say "I
    cannot read this" on screen and let a writer running current code fix the schema.

    Two things `mode=ro` does NOT mean, both deliberate:

    - sqlite may still create the `-shm`/`-wal` sidecars, because that is how a WAL reader
      coordinates with writers. It needs the *directory* to be writable, not the database.
      Nothing in the store's content can change.
    - it will not create a missing database, and we do not either — see below.
    """
    # `mode=ro` on a path that does not exist fails with a bare "unable to open database
    # file", which tells a reader nothing about which of the several possible reasons it
    # was. Answer the question the reader actually has. Creating it is not on the table:
    # an empty store created by a viewer would be indistinguishable from a real one and
    # would make the NEXT writer think the schema was current. Nothing has run here yet is
    # a true and useful thing to display, and a writer creates the store on its first `sb`.
    if not p.exists():
        raise FileNotFoundError(
            f"no store yet at {p} — nothing has been recorded in this repo. "
            f"A store is created by the first `sb` command that runs here, never by a reader."
        )
    # Percent-encoded: a URI filename is parsed, so a '?' or '#' anywhere in the path would
    # otherwise be read as the start of the query part and silently open the wrong file.
    uri = f"file:{urllib.parse.quote(str(p))}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=_DB_TIMEOUT)
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA busy_timeout={int(_DB_TIMEOUT * 1000)}")
    # No `journal_mode`, no `CREATE TABLE IF NOT EXISTS meta`, no hash check and no
    # `_reconcile`. The absence of those four lines is the whole fix.
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
    deferred rebuild never half-fills anything. A whole missing table is the same shape one
    level up: create it, then run its `_TABLE_BACKFILLS` entry.

    Two processes that both computed the deficit before either acted is the ordinary state
    of this machine, so every statement here is idempotent and the loser's "already exists"
    is caught rather than let out of `connect()`.

    The stamp is last, and it is last for a reason rather than for tidiness: every table
    backfill has been *recorded* by the time it is written. `CREATE TABLE` autocommits, so
    a second process sees the new table the instant it exists and none of the backfilled
    rows until commit; stamping on the shape alone would let that process declare the store
    current over an empty table, and the one-time backfill would then never run again for
    anyone. There is no conditional here doing that work — `_fill_table` runs for every
    declared table and either performs the fill and records it or finds it already
    recorded, so reaching the stamp at all IS every backfill being accounted for. Which is
    what makes moving the stamp earlier a bug the tests would have to catch rather than one
    a reader can see.
    """
    tables, columns, blocking = _deficit(db)
    if not blocking:
        for table in tables:
            _create_table(db, table)
        # Every declared table, not only the ones we just created: finding the table
        # already there says nothing about whether anybody finished filling it.
        for table in _TABLE_BACKFILLS:
            _fill_table(db, table, cwd)
        for table, name, decl in columns:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
                # Another process added it between our deficit and our ALTER. Its backfill
                # still runs: ours may be the one that gets there first, and they are
                # written to be safe to run twice.
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
    return _deficit(db)[2]


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

# The bare-versus-worktree selector, written down once. A row means a worktree workspace
# and that `cwd` is its checkout; no row means bare and the path is NULL — the rule reads
# the PRESENCE of a branch rather than the absence of one, and the difference is not
# academic. Two names on the reference machine have rows that disagree about `branch`
# (fourteen with and three without; eleven and one), which is the shape `delegate` writes
# when `branch is None` and the workspace was named rather than inherited. Read as "any
# NULL-branch row means bare", both are permanently recorded as having no checkout — which
# destroys nothing today and routes them to the bare teardown path forever: no gate, no
# live observation, worktree and branch left standing with nothing that can ever remove
# them. The fill runs once, so the wrong answer is the permanent one.
_WORKSPACE_CHECKOUT = """SELECT cwd FROM agents
 WHERE workspace = ? AND cwd IS NOT NULL AND branch IS NOT NULL
 ORDER BY created_at LIMIT 1"""


def _backfill_workspaces(db: sqlite3.Connection, cwd: Optional[Path]) -> None:
    """Give the workspaces that predate the table the rows they have always deserved.

    One row per workspace NAME, so the four bare orchestrators over the primary clone
    become four rows rather than one — which is the whole reason the key is the name.
    The checkout comes from the agent rows under that name, by the selector above, and
    NULL is a real answer rather than a missing one.

    This is deliberately the same lookup this design forbids for deciding *membership*:
    asking at every call which rows belong to a workspace by matching a name is an
    invitation to the failure mode `agents.branch` exists to end, whereas populating a
    column once, at a known moment, from the only evidence there is, is an ordinary
    migration. What makes it safe is the other half of the rule: a filled-in path is never
    trusted as a live fact — `checkout_verdict` re-validates it at every use.

    Safe to run twice and against a table somebody else created, as every table fill must
    be: it adds the rows that are missing and touches no row that is already there.
    """
    for r in db.execute(
        "SELECT workspace, MIN(created_at) AS first_seen FROM agents "
        "WHERE workspace IS NOT NULL GROUP BY workspace"
    ).fetchall():
        name = r["workspace"]
        found = db.execute(_WORKSPACE_CHECKOUT, (name,)).fetchone()
        db.execute(
            "INSERT OR IGNORE INTO workspaces(name, checkout, created_at) VALUES(?,?,?)",
            (name, found["cwd"] if found else None, r["first_seen"]),
        )


# The same thing for a whole table that arrives after the store did: keyed by table name,
# handed the store the moment the table exists. The capability is what `_reconcile` needs
# in order to add a table at all, and a table whose rows are derived from the ones already
# here is the reason it exists — `workspaces` is exactly that table.
#
# These are held to a stricter rule than the column fills above, because a table's create
# and its fill are two transactions (see `_fill_table`): they must be safe to run twice,
# and they must be safe to run against a table somebody else created.
_TABLE_BACKFILLS: dict = {"workspaces": _backfill_workspaces}


def _backfill_recorded(db: sqlite3.Connection, table: str) -> bool:
    """Has this table's one-time fill been recorded as done? A fact, never an inference.

    The tempting inference — "the schema hash is current, so everything ran" — is exactly
    the bug. `CREATE TABLE` autocommits, so the table exists for every other connection
    before a single backfilled row does; a process that read the shape and stamped the hash
    would suppress the fill permanently for the whole machine.
    """
    key = f"backfill:{table}"
    return db.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone() is not None


def _record_backfill(db: sqlite3.Connection, table: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
               (f"backfill:{table}", str(now())))


def _fill_table(db: sqlite3.Connection, table: str, cwd: Optional[Path]) -> None:
    """Run a table's one-time fill, unless it is already recorded as done.

    The rows and the record of having written them commit together, so the only two states
    anybody else can observe are "not done, run it" and "done". A process killed mid-fill
    rolls both back and the next `sb` picks it up, which is the failure this shape exists
    for: the alternative loses the fill silently and forever.
    """
    fill = _TABLE_BACKFILLS.get(table)
    if fill is None or _backfill_recorded(db, table):
        return
    fill(db, cwd)
    _record_backfill(db, table)
    db.commit()


def _table_ddl(table: str) -> list[str]:
    """Every statement SCHEMA declares for one table — its CREATE TABLE and its indexes.

    Taken from the SCHEMA text verbatim rather than rebuilt from `_wanted`'s parse, so the
    table a migration creates is the same one `_create` would have. `IF NOT EXISTS` is
    added on the way past: the loser of a concurrent create must find nothing to do, not a
    reason to raise inside `connect()`.
    """
    out = []
    m = re.search(rf"CREATE TABLE {table} \(.*?\n\);", SCHEMA, re.S)
    if m:
        out.append(m.group(0).replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
    for i in re.finditer(rf"CREATE INDEX \w+\s+ON {table}\(.*?\);", SCHEMA):
        out.append(i.group(0).replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
    return out


def _create_table(db: sqlite3.Connection, table: str) -> None:
    """Add one table to a store that predates it. Never destructive, never fatal."""
    for stmt in _table_ddl(table):
        try:
            db.execute(stmt)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e).lower():
                raise


def _addable_column(decl: str) -> bool:
    """Can this column be given to rows that already exist? NOT NULL with no default cannot."""
    return not ("NOT NULL" in decl.upper() and "DEFAULT" not in decl.upper())


def _deficit(db: sqlite3.Connection) -> tuple[list, list, list]:
    """What this code needs that the store lacks: `(tables, columns, blocking)`.

    `tables` names whole tables to create; `columns` is a plan of `(table, column, decl)`
    triples that ALTER TABLE can apply in place. `blocking` is a list of human-readable gaps
    that neither can cover, and only a non-empty `blocking` can ever cost anyone their
    store.

    A missing table is addable when every column it declares is addable — the same test,
    applied one level up, for the same reason. A table this code would create with a NOT
    NULL column is a table whose existing-world rows it cannot invent, and inventing them is
    precisely what adding a table to a store full of history means. Two rules would be two
    chances to get it wrong; there is one rule, and `_addable_column` is it.

    Nothing here compares the store to the schema for *equality*. It asks the narrower and
    much safer question — is everything this code reads and writes present? — because the
    store is shared by every worktree of the repo, so it is routinely met by code both
    older and newer than whatever last wrote it.
    """
    wanted = _wanted()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing, plan, blocking = [], [], []
    for table, cols in wanted.items():
        if table not in tables:
            if all(_addable_column(d) for d in cols.values()):
                missing.append(table)
            else:
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
            if not _addable_column(decl):
                blocking.append(f"{table}.{name} cannot be added to existing rows")
            else:
                plan.append((table, name, decl))
    return missing, plan, blocking


def _create(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
    # A store built from scratch has no history for a one-time fill to derive anything
    # from, so its fills are done by definition. Recording that keeps the rule simple —
    # unrecorded means run it — rather than leaving a fresh store looking half-migrated.
    for table in _TABLE_BACKFILLS:
        _record_backfill(db, table)
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
    unknown = False
    if live and not force:
        known = _herdr_alive()
        if known is None:
            # Could not ask. The store's own list is then the only evidence there is, and
            # it stays — narrowing it here would be narrowing it on a guess, in the one
            # branch where guessing wrong is unrecoverable.
            unknown = True
        else:
            live = [n for n in live if n in known]
    if live and not force:
        raise LiveAgentsError(
            "the store's schema changed under a running fleet: "
            + ", ".join(live)
            + ("\n(herdr could not be reached, so this is what the store says is live"
               "\nrather than what is confirmed running — refusing on that.)" if unknown else "")
            + "\nThey keep working on the old store, which is rebuilt automatically once"
              "\nthe last one finishes. To rebuild NOW and lose their state:"
              "\n  sb doctor --reset-store --force"
        )
    # Derived from SCHEMA, never a hardcoded list. `_create` re-runs the WHOLE schema, so a
    # table this misses is a table `CREATE TABLE` then trips over — and where that lands is
    # decided by declaration order: a table declared after `agents` leaves the three
    # recreated and empty with the error escaping `connect()`, one declared before it leaves
    # the store holding nothing but that table and every later `sb` failing identically.
    # Nobody adding a table should have to notice which half of that they are in.
    for t in _wanted():
        db.execute(f"DROP TABLE IF EXISTS {t}")
    _create(db)


def _herdr_alive() -> Optional[set]:
    """Agent names herdr currently knows about, or **None** when we could not tell.

    None is not an empty set, and that distinction is the whole function. Its only caller
    is the guard on dropping `agents`, `messages` and `events` (`_reset`), where an empty
    set reads as "nobody is running, safe to wipe". So every failure here used to fail
    toward the wipe: herdr installed anywhere other than `~/.local/bin`, a non-zero exit,
    a slow answer that timed out, output that did not parse — any of them was enough to
    turn a schema mismatch into an unrecoverable, unlogged loss under a live fleet.

    Wrong direction for an irreversible branch. Unknown now means unknown, and the guard
    refuses; the cost of refusing is a store that stays degraded a while longer, which is
    the same cost `_reconcile` already pays deliberately everywhere else.

    Resolved the way the adapter resolves it (`herdr.Herdr.__init__`) rather than by a
    hardcoded path — but not by importing it: `store` is the bottom of the stack and
    `herdr` is a view over it, so the two-line duplication is the price of the layering.
    """
    binary = shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
    try:
        p = subprocess.run(
            [binary, "agent", "list"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
    except Exception:                          # noqa: BLE001 — missing, unrunnable, hung
        return None
    if p.returncode != 0:
        return None
    try:
        agents = json.loads(p.stdout)["result"]["agents"]
        return {a.get("name") for a in agents if a.get("name")}
    except Exception:                          # noqa: BLE001 — not the answer we asked for
        return None


def now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


_INSERT_AGENT = """INSERT {or_ignore} INTO agents
       (name, parent, role, task, state, session_id, cwd, workspace, branch,
        workspace_id, terminal_id, pane_id, cleanup, awaiting_task, created_at)
       VALUES (?,?,?,?,'working',?,?,?,?,?,?,?,?,?,?)"""


def _agent_values(
    name: str, role: str, parent, task, session_id, cwd, workspace, branch, workspace_id,
    terminal_id, pane_id, cleanup, awaiting_task,
) -> tuple:
    return (name, parent, role, task, session_id, cwd, workspace, branch, workspace_id,
            terminal_id, pane_id, cleanup, int(awaiting_task), now())


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
    awaiting_task: bool = False,
) -> sqlite3.Row:
    """Insert an agent row. Raises `sqlite3.IntegrityError` if the name is taken.

    Anything that might be racing another opener for the same name wants `claim_agent`
    instead — this one is for the case where the caller already knows the name is free.
    """
    db.execute(
        _INSERT_AGENT.format(or_ignore=""),
        _agent_values(name, role, parent, task, session_id, cwd, workspace, branch,
                      workspace_id, terminal_id, pane_id, cleanup, awaiting_task),
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
    awaiting_task: bool = False,
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
                      workspace_id, terminal_id, pane_id, cleanup, awaiting_task),
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
    herdr (see `Broker.running_tops`).
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
# Workspaces
# ---------------------------------------------------------------------------
#
# The first first-class workspace entity in the store. Everything before it derived "the
# workspace" by grouping `agents` rows (`workspace_branch`, `known_workspace`), which
# cannot represent a workspace with no rows — a retired one, or a worktree nobody ever
# worked in — and has nowhere to put a fact about the workspace itself.


def get_workspace(db: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return db.execute("SELECT * FROM workspaces WHERE name=?", (name,)).fetchone()


def all_workspaces(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace the table knows about, retired ones included.

    One of the three sources a workspace enumeration has to hold, and the only one that
    knows about a workspace with no worktree and no agent rows. Git knows the orphan
    worktree nobody was ever recorded in; `agents` knows the workspace that escaped this
    table. None of the three is a superset of the others.
    """
    return db.execute("SELECT * FROM workspaces ORDER BY name").fetchall()


def record_workspace(
    db: sqlite3.Connection, name: str, checkout: Optional[str] = None
) -> None:
    """Write down where a workspace's checkout is — on creation, and on every attach.

    A record of where the checkout *is*, not of where it once was, which is why attaching
    re-writes it rather than leaving the first answer standing. NULL is a value here like
    any other: passing it says "this workspace has no checkout of its own", which is what
    bare means.
    """
    db.execute(
        "INSERT INTO workspaces(name, checkout, created_at) VALUES(?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET checkout=excluded.checkout",
        (name, checkout, now()),
    )
    db.commit()


def retire_workspace(db: sqlite3.Connection, name: str) -> None:
    """Stamp a workspace retired, clear its path, and drop the retiring mark.

    The path goes because it is a record of where the checkout is, and after a retirement
    there is no checkout: leaving the old one behind would hand the next reader a path
    that re-validates as absent and reads as something still to clean up.
    """
    db.execute(
        "UPDATE workspaces SET retired_at=?, checkout=NULL, retiring=NULL, "
        "retiring_at=NULL WHERE name=?",
        (now(), name),
    )
    db.commit()


def reopen_workspace(
    db: sqlite3.Connection, name: str, checkout: Optional[str] = None
) -> None:
    """Make a retired workspace live again, at wherever its checkout is now.

    Retirement is not a tombstone on the name — the name is identity, and a person who
    types it again means the workspace they are naming.
    """
    db.execute(
        "INSERT INTO workspaces(name, checkout, created_at) VALUES(?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET checkout=excluded.checkout, retired_at=NULL",
        (name, checkout, now()),
    )
    db.commit()


def claim_retiring(db: sqlite3.Connection, name: str, owner: str) -> bool:
    """Take the retiring mark, or find out somebody else already holds it. -> did we?

    The same shape as `claim_agent`, for the same reason: a `get_workspace(...) is None`
    check followed by an `UPDATE` is two statements with a race between them, and this one
    guards a destructive command. The claim IS the write — `WHERE retiring IS NULL` — and
    `rowcount` is the arbiter, so of two invocations arriving together exactly one gets 1.

    The mark records its OWNER rather than being a flag, so a losing invocation cannot
    release a mark it never held (see `release_retiring`). It is still not a lock and no
    lock verb enters the tree for it: `workspace_new`'s docstring advertises
    non-exclusivity as deliberate policy, and one path is no reason to teach the rest of
    the codebase a rule it does not otherwise follow.

    False for a workspace with no row at all, which is a caller that skipped
    `record_workspace` — nothing here invents a row for a workspace nobody has recorded.
    """
    cur = db.execute(
        "UPDATE workspaces SET retiring=?, retiring_at=? WHERE name=? AND retiring IS NULL",
        (owner, now(), name),
    )
    db.commit()
    return cur.rowcount == 1


def release_retiring(db: sqlite3.Connection, name: str, owner: str) -> bool:
    """Clear a retiring mark we hold. -> was it ours to clear?

    Only ever clears, and never restores an earlier value: there is one mark, its rollback
    is the owner's, and a mark held by somebody else is left exactly where it is.
    """
    cur = db.execute(
        "UPDATE workspaces SET retiring=NULL, retiring_at=NULL WHERE name=? AND retiring=?",
        (name, owner),
    )
    db.commit()
    return cur.rowcount == 1


# What re-validating a recorded checkout can conclude. Three answers, not a boolean: a
# path that is simply GONE is a resolved answer — nothing is there, so nothing can be lost
# — while a path that resolves to something unintelligible is not an answer at all. One
# boolean collapses those, and collapsing them makes the cheapest safe path refuse on
# precisely the workspaces it was written for: every path in the store is a filled-in one,
# and six of them point at directories that no longer exist.
CHECKOUT_OK = "ok"
CHECKOUT_ABSENT = "absent"
CHECKOUT_UNUSABLE = "unusable"


def checkout_verdict(path: Optional[str], cwd: Optional[Path] = None) -> str:
    """Re-validate a recorded checkout path against git. The record proposes; git decides.

    A path on a workspace row was derived once, at migration time, from rows that had no
    idea they were describing a checkout — so it is a candidate and never a live fact.
    This is what every use of it goes through first:

    - `CHECKOUT_OK` — the directory is there and `git worktree list` reports it as a
      worktree of this repo.
    - `CHECKOUT_ABSENT` — nothing is at that path. A *resolved* answer: the workspace's
      checkout is already gone, which is a route (deregister the worktree, delete the
      branch) rather than a refusal.
    - `CHECKOUT_UNUSABLE` — anything else. A path that is not a worktree of this repo, a
      directory that cannot be read, a path that is not a directory, no path at all on a
      workspace that is not bare, or a git that would not answer. This is where "unknown
      is not empty" keeps its full force, and a caller that cannot tell refuses.

    "A git that would not answer" includes one that never answers: this call is bounded
    like every other subprocess in this command, because the alternative to a refusal here
    is not a wrong verdict but no verdict at all — a hung git hanging the whole command,
    which for the destructive caller means hanging it before it has decided anything.

    `cwd` is where git is asked from, and it is deliberately not the path being validated:
    a directory that turns out to be a checkout of some OTHER repo would happily report
    itself as a worktree of itself.

    A bare workspace never reaches here. Its NULL path is read off the row as the fact it
    is, before any of this; a NULL arriving here is a workspace with nothing recorded,
    which is the third verdict.
    """
    if not path:
        return CHECKOUT_UNUSABLE
    p = Path(path)
    if not p.exists():
        return CHECKOUT_ABSENT
    if not p.is_dir():
        return CHECKOUT_UNUSABLE
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):            # unreadable, or a symlink loop
        return CHECKOUT_UNUSABLE
    try:
        out = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return CHECKOUT_UNUSABLE               # unrunnable or hung is not the answer "no"
    if out.returncode != 0:
        return CHECKOUT_UNUSABLE               # no answer is not the answer "no"
    for line in out.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        try:
            if Path(line[len("worktree "):]).resolve() == resolved:
                return CHECKOUT_OK
        except (OSError, RuntimeError):
            continue
    return CHECKOUT_UNUSABLE


def workspace_fill_gap(db: sqlite3.Connection) -> Optional[str]:
    """Why this store cannot be asked about workspaces yet, or None when it can.

    The `workspaces` table is filled exactly once, from `agents.cwd`, and that input is
    not durable: anything that empties or rebuilds the store between this code shipping
    and the first `sb` that runs the fill leaves the fill permanently unperformed, and
    every workspace that predates the table unrecorded forever. Nothing recovers that
    except running it again by hand.

    What makes it *legible* is that the fill records its own completion. Without asking,
    an unfilled store and a store with genuinely no workspaces are the same empty query —
    so a destructive command that inferred "unrecorded" from an empty table would refuse
    every real workspace while reporting nothing wrong. Anything about to act on the
    absence of a workspace row asks this first and refuses with what it says.
    """
    if _backfill_recorded(db, "workspaces"):
        return None
    return (
        "the workspaces table has never been filled in from the agent rows, so this store"
        "\ncannot say which workspaces predate it — and an empty answer here is not the"
        "\nsame as no workspaces. Run any `sb` command that opens the store for writing"
        "\n(`sb status` will do) to fill it, and if that does not, the agent rows it"
        "\nderives from are gone and the workspaces have to be re-recorded by hand."
    )


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
    # Somebody has now given this agent something, which is the whole of what
    # `agents.awaiting_task` records. Cleared HERE rather than in `Broker.tell`, because
    # `ask` and `interrupt` write their rows themselves and would each have to remember;
    # a bit three call sites clear by hand is a bit that goes stale at the fourth.
    db.execute("UPDATE agents SET awaiting_task=0 WHERE name=?", (to_agent,))
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
    """Messages written but never announced, oldest first. Says nothing about read.

    A message is only 'delivered' once we have rung the target's doorbell. We hold the
    ring back while the target is mid-turn, because `agent prompt` INTERLEAVES — it is
    injected into the current turn rather than queued after it — so ringing a working
    agent interrupts whatever it was doing.

    This answers "did our doorbell ring?", which is a question about US and is the right
    one for a sender checking its own send (`sb tell`'s report): a message written a
    moment ago cannot have been read yet, so there the two predicates coincide. It is the
    WRONG one for anything asking whether the target knows — use `unseen` for that.

    `exclude` is for addresses that are not agents and have no doorbell. The human is the
    only one: nothing is addressed to them any more (they have no mailbox — see
    broker.block), but a store written before that still holds such rows, and no ring was
    ever going to come for them. Passed in rather than written here because what the human
    is CALLED is `[vocabulary]`.
    """
    return _pending(db, exclude=exclude)


def unseen(db: sqlite3.Connection, *, exclude: Iterable[str] = ()) -> list[sqlite3.Row]:
    """Messages the target has no way of knowing about: never announced AND never read.

    The two come apart the moment an agent runs `sb inbox` of its own accord instead of
    waiting to be rung. It is mid-turn, so the doorbell is held back; it reads the mail
    anyway; `read_at` is set and `delivered_at` stays NULL — forever, because the ring
    those rows were owed is the ring that would have cleared it. Every one of them is
    still `undelivered`, and not one of them is news to the agent.

    So this is the predicate for anyone acting on the agent's behalf. Ringing on
    `delivered_at` alone costs the agent a whole turn to discover an empty inbox, and
    `Broker._ring` unblocks before it prompts — so a ring for mail already read puts an
    agent that stopped to ask a person back to `working` and drops it off
    `sb status --needs-me`, with the question never reaching anyone.
    """
    return _pending(db, exclude=exclude, unread_only=True)


def _pending(
    db: sqlite3.Connection, *, exclude: Iterable[str], unread_only: bool = False
) -> list[sqlite3.Row]:
    """Shared body of `undelivered`/`unseen` — one predicate apart, oldest first."""
    names = list(exclude)
    holes = ",".join("?" * len(names))
    return db.execute(
        "SELECT * FROM messages WHERE delivered_at IS NULL"
        + (" AND read_at IS NULL" if unread_only else "")
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
    # A debugging window onto a store that is usually somebody else's and usually live.
    # Looking at it must not migrate it: `connect()` would stamp, ALTER, backfill or drop
    # to suit whichever checkout this module was imported from. `reset` is a write by
    # definition and is the only subcommand that gets a writable connection.
    try:
        db = connect(readonly=args.cmd != "reset")
    except FileNotFoundError as e:
        print(f"  {e}")
        return 1

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
