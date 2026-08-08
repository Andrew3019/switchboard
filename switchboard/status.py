"""M4 — the readouts: `sb status` (the board), `sb inspect` (one agent), `sb wait`.

The store says what an agent was *told* to be; herdr says what its pane is *doing*. Read
either one alone and you get a confident answer that is regularly wrong, so this module
exists to join them and to say so when they disagree.

The disagreement that matters is one specific pair:

    store: working        herdr: idle        →  STALLED

That agent finished its turn and never called `sb done`. It happens constantly and
silently — nothing errors, nothing logs, the pane just goes quiet — and every readout
that trusts the store alone reports it as busy for the rest of the day. Naming it is the
whole point of this file. We deliberately do NOT repair it: marking it done here would
fabricate a summary its parent never received, and the parent is still waiting on that
message (see broker.done). Surfacing beats guessing (C9).

Two other joins fall out of the same table:

    store: working        herdr: not listed  →  GONE     (pane closed under it)
    store: anything       herdr: blocked     →  a human is being asked something in the TUI

Everything is computed from ONE `agent list` and one pass over the store. Per-agent herdr
calls are what make a status command too slow to run reflexively, and a status command you
hesitate to run is the same as not having one.

A third disagreement, in the mailbox rather than the pane:

    never announced AND never read            →  UNDELIVERED

`agent prompt` INTERLEAVES — it is injected into the current turn rather than queued after
it — so ringing a working agent interrupts whatever it is doing. `sb tell` therefore holds
the ring back while the target is mid-turn, and `broker.flush_pending` rings once it goes
idle. That is right, and it introduces a way for mail to sit forever: if the flush never
runs, nothing is on the agent's screen and nothing is in its inbox count.

Both halves of that predicate carry weight. Announcement alone says only whether WE rang;
it does not say whether the agent knows. An agent that runs `sb inbox` of its own accord
while mid-turn reads mail the doorbell was still holding back, and those rows stay
un-announced for good — so counting announcement alone warns that an agent is in the dark
about messages already in its context, on the same row where MAIL says `-`. Counting what
is BOTH un-announced and unread keeps UNDELIVERED a strict subset of MAIL: unread means we
rang and it has not looked, undelivered means it has no way to know yet. Only one of those
is the agent's fault, and only one of them is invisible from inside the agent.
`broker.flush_pending` rings on the same predicate, so the doorbell and this board cannot
disagree about what is still outstanding.

Reading status never mutates: mail is counted, never consumed (`mark=False` semantics),
and counting an undelivered message never delivers it. With one exception, and it is worth
knowing about — GONE is written back (`_record_gone`), because this is the only place that
ever learns it. That write ends an agent's turn, so it belongs only to a process that lives
for one command: a caller that outlives the code it started with passes `reap=False` and
gets the same flags with none of the writes.

Three commands live here because all three are the same join, at three widths:

    status   every agent, one line each
    inspect  ONE agent, everything — including the tail of its terminal (via output.py)
    wait     block until the join says an agent has reached a state
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import config
from .herdr import (
    BLOCKED, IDLE, SPAWN_ATTEMPTS, SPAWN_TIMEOUT_MS, WORKING, Herdr, HerdrError,
)

# Which states count as what — `[states]` in defaults/settings.toml. The state NAMES are
# the store's schema; the groupings are policy, and policy is config.

# herdr derives a fifth *display* state, `done` = idle and not yet looked at (Herdr
# .report_state documents it). For drift it means exactly what idle means: no turn is
# running. Treating it as its own thing is how a stalled agent gets missed.
IDLE_LIKE = frozenset(config.setting("states.idle_like"))

# Store states that claim the agent is still going, and so can be contradicted.
RUNNING = tuple(config.setting("states.running"))
FINISHED = tuple(config.setting("states.finished"))

# What a row becomes when herdr no longer has the agent (see `_record_gone`).
#
# `failed` rather than a new `lost` state, and the choice is deliberate. The store's state
# column is a four-word closed vocabulary — working | blocked | done | failed — that `sb
# wait --for` accepts verbatim, that `[states]` groups into policy, and that every readout
# renders; a fifth word costs all of those, and buys a distinction the state column is the
# wrong place for. `failed` already means exactly what happened: the agent's turn ended
# without it ever reporting success. HOW we learned that is not state, it is history, so
# it goes where the rest of the history goes — an event, which `sb log` and `sb inspect`
# already show. And `failed` is in `finished`, which is what lets `sb cleanup` reach these
# rows at all; a new state would have to be added to that list to work, at which point it
# is `failed` with extra steps.
GONE_STATE = "failed"

# How long a row with no session id is read as a *claim* rather than as a live agent.
#
# `delegate` inserts the row before herdr is asked to start anything (the name is the lock
# — see broker.delegate), and `agent start` is flaky enough to be retried with a backoff.
# For that whole window there is a `working` row that herdr has never heard of, which is
# indistinguishable from a pane that closed — and the board refreshes every 2 s, as does
# every `sb` invocation, so something WILL look. Reaping there marks a live agent failed
# during its own spawn.
#
# The window is herdr's own worst case, not a number of our own: every attempt it will
# make, each running its full timeout. Erring long is the cheap direction — a genuinely
# dead claim is reaped one window later, whereas erring short kills real agents.
SPAWN_GRACE = (SPAWN_TIMEOUT_MS / 1000) * SPAWN_ATTEMPTS

# `sb done "<summary>"` reaches the parent as a message body with this prefix (see
# broker.done). Stripping it here keeps the prefix an implementation detail of the
# mailbox rather than something every reader has to know about.
DONE_PREFIX = config.setting("vocabulary.done_prefix")

# Long enough to say what an agent is doing, short enough not to wrap a terminal.
TASK_CLIP = config.setting("limits.task_clip")

# Not an agent, and not a mailbox holder: nothing is ever addressed to the human. The name
# is still needed here because `--mine` accepts it — for a person, "my subtree" is every
# root and everything under it.
HUMAN = config.setting("vocabulary.human")


@dataclass
class AgentStatus:
    """One agent, as the store and herdr *jointly* describe it."""

    name: str
    role: str
    parent: Optional[str]
    depth: int                      # tree depth; 0 is a root (parent IS NULL)
    state: str                      # the store's state, never rewritten
    herdr_state: Optional[str]      # None = herdr has never heard of it
    alive: Optional[bool]           # None = we could not reach herdr at all
    stalled: bool
    gone: bool
    unread: int
    age: int                        # seconds since created
    idle: int                       # seconds since it last did anything
    last_activity: int              # epoch
    workspace: Optional[str]
    task: Optional[str]
    blocked_why: Optional[str]
    summary: Optional[str] = None   # what it said when it last called `sb done`
    # Mail neither announced nor read — see `undelivered_age` and the module note.
    undelivered: int = 0
    undelivered_age: int = 0        # seconds since the OLDEST one was written; 0 = none

    @property
    def blocked(self) -> bool:
        return self.state == "blocked"

    @property
    def at_prompt(self) -> bool:
        """herdr's own detector says the TUI is waiting on a person.

        We never report `blocked` to herdr ourselves (broker.block explains why), so this
        only ever comes from herdr, and it means a permission prompt or similar is sitting
        unanswered on screen.
        """
        return self.herdr_state == BLOCKED

    @property
    def finished(self) -> bool:
        return self.state in FINISHED

    @property
    def waiting_to_be_rung(self) -> bool:
        """Mail is sitting here that this agent has no way of knowing about.

        Distinct from unread, and the distinction is the whole point (see the module
        note): unread means we rang and it has not looked, so the agent knows. This is the
        subset it was never told about AND has not read of its own accord either — nothing
        on its screen, nothing in its context. If the ring never comes, this mail sits
        forever with nothing to say so.
        """
        return self.undelivered > 0

    @property
    def needs_human(self) -> bool:
        return (self.blocked or self.at_prompt or self.unread > 0
                or self.waiting_to_be_rung)

    def as_dict(self) -> dict:
        d = {f: getattr(self, f) for f in (
            "name", "role", "parent", "depth", "state", "herdr_state", "alive",
            "stalled", "gone", "unread", "age", "idle", "last_activity",
            "workspace", "task", "blocked_why", "summary",
            "undelivered", "undelivered_age",
        )}
        # Derived, but part of the contract: a consumer must not have to re-derive drift
        # from a rule that lives in this file.
        d.update(blocked=self.blocked, at_prompt=self.at_prompt,
                 finished=self.finished, needs_human=self.needs_human,
                 waiting_to_be_rung=self.waiting_to_be_rung)
        return d


@dataclass
class Snapshot:
    now: int
    agents: list[AgentStatus]       # tree order: a parent immediately precedes its children
    herdr_error: Optional[str] = None    # set when `agent list` failed; alive is then None
    hidden: int = 0                      # finished agents dropped by live_only

    @property
    def counts(self) -> dict:
        return {
            "agents": len(self.agents),
            "alive": sum(1 for a in self.agents if a.alive),
            "stalled": sum(1 for a in self.agents if a.stalled),
            "gone": sum(1 for a in self.agents if a.gone),
            "blocked": sum(1 for a in self.agents if a.blocked),
            "at_prompt": sum(1 for a in self.agents if a.at_prompt),
            "unread": sum(a.unread for a in self.agents),
            "undelivered": sum(a.undelivered for a in self.agents),
            "waiting_to_be_rung": sum(1 for a in self.agents if a.waiting_to_be_rung),
            "hidden": self.hidden,
        }

    @property
    def needs_human(self) -> list[AgentStatus]:
        return [a for a in self.agents if a.needs_human]

    def as_dict(self) -> dict:
        return {
            "now": self.now,
            "herdr": "unavailable" if self.herdr_error else "ok",
            "herdr_error": self.herdr_error,
            "counts": self.counts,
            "agents": [a.as_dict() for a in self.agents],
        }


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect(
    db: sqlite3.Connection,
    h: Optional[Herdr] = None,
    *,
    now: Optional[int] = None,
    live_only: bool = False,
    needs_me: bool = False,
    mine: Optional[str] = None,
    reap: bool = True,
) -> Snapshot:
    """The whole readout: one herdr call, one pass over the store.

    The three filters narrow *which rows are shown*, never what is computed — everything
    is still joined first, so a hidden agent can never change what a visible one says.
    They AND together, and each reports what it dropped as `hidden`.

    `live_only` drops finished agents, but keeps any that still hold unread mail (mail on
    a finished agent is mail nobody will ever read unless it is visible).
    `needs_me` keeps only agents that are blocked, sitting at a prompt, or holding unread
    mail — the ones an action is owed to.
    `mine` scopes to one agent's own subtree (pass `human` for the roots and everything
    under them, which for a human is the whole tree).

    All three keep the ancestors of whatever survives, or the indentation would lie about
    who reports to whom. `mine` bounds that: it never re-adds anything above the caller.

    `reap=False` computes every flag exactly as before but writes nothing: the drift is
    still rendered, it is just not recorded (see `_record_gone`). It is for a caller that
    is not a short-lived `sb` process. A `sb board` runs for hours on the `status.py`
    Python imported at startup, so it re-collects every two seconds with whatever grace
    window and heuristics were current when the human opened it — three of them, still
    reaping on code from before `SPAWN_GRACE` existed, is how every spawn in one night
    came to be marked `failed` during its own startup. A readout should not be able to
    end an agent's life on the strength of code nobody is running any more.
    """
    from . import store                      # local: keeps this module importable alone

    now = store.now() if now is None else now

    live: dict[str, Any] = {}
    herdr_error: Optional[str] = None
    if h is not None:
        try:
            live = {a.name: a for a in h.list_agents()}
        except HerdrError as e:
            # Never fatal. A status command that dies when herdr hiccups is a status
            # command you stop trusting; we degrade to store-only and SAY so.
            herdr_error = str(e)
        except OSError as e:                 # herdr binary missing entirely
            herdr_error = str(e)
    # Whether we actually have herdr's side. Absent it, "not in the list" means nothing —
    # so aliveness is unknown rather than False, and no drift can be claimed either way.
    consulted = h is not None and herdr_error is None

    rows = db.execute("SELECT * FROM agents ORDER BY created_at, name").fetchall()
    unread = _unread_counts(db)
    pending = _undelivered_counts(db)
    activity = _last_activity(db)
    why = _block_reasons(db)
    summaries = _last_summaries(db)

    ordered = _tree(rows)
    agents = []
    for row, depth in ordered:
        name = row["name"]
        agent = live.get(name)
        hstate = agent.state if agent else None
        alive = (agent is not None) if consulted else None
        running = row["state"] in RUNNING and row["ended_at"] is None
        # A row with no session id that is younger than the spawn window is a CLAIM, not a
        # live agent: `delegate` writes it before herdr is called, and herdr will not list
        # the name until `agent start` finally succeeds. Absence proves nothing yet, so it
        # is neither gone nor stalled. See SPAWN_GRACE.
        spawning = row["session_id"] is None and (now - row["created_at"]) < SPAWN_GRACE
        last = max(row["created_at"], activity.get(name, 0))
        agents.append(AgentStatus(
            name=name,
            role=row["role"],
            parent=row["parent"],
            depth=depth,
            state=row["state"],
            herdr_state=hstate,
            alive=alive,
            # The join this file exists for. Both halves must be known: an unreachable
            # herdr proves nothing, and neither does herdr's `unknown`.
            stalled=bool(running and alive and hstate in IDLE_LIKE),
            gone=bool(running and alive is False and not spawning),
            unread=unread.get(name, 0),
            age=max(0, now - row["created_at"]),
            idle=max(0, now - last),
            last_activity=last,
            workspace=row["workspace"],
            task=row["task"],
            blocked_why=why.get(name) if row["state"] == "blocked" else None,
            summary=summaries.get(name),
            undelivered=pending.get(name, (0, 0))[0],
            # Age of the OLDEST, not the newest: the question is how long this has been
            # sitting, and a fresh message arriving behind a stuck one must not reset it.
            undelivered_age=(max(0, now - pending[name][1]) if name in pending else 0),
        ))

    # Guarded on `consulted`, and that guard is the whole safety of it: without herdr's
    # side every row looks gone, and this would reap the table on a hiccup.
    if consulted and reap:
        _record_gone(db, [a.name for a in agents if a.gone])

    kept = _filter(agents, live_only=live_only, needs_me=needs_me, mine=mine)
    hidden = len(agents) - len(kept)

    return Snapshot(now=now, agents=kept, herdr_error=herdr_error, hidden=hidden)


def _record_gone(db: sqlite3.Connection, names: list[str]) -> None:
    """Write the drift back: an agent herdr no longer has is not working any more.

    The one write on the read path, and it is here because this is the only place that
    ever learns it. Nothing else closes a row that died abnormally — a crash, a pane
    closed from the outside, a herdr restart, a reboot — because the only writers of an
    end are the agent's own `sb done` and a `sb cleanup` that already gates on the row
    being finished. So the row claims `working` forever, `sb cleanup` cannot reach it,
    and `sb start` counts it as an orchestrator that is still up. Recording it here is
    what unsticks all three.

    Invents nothing. A summary its parent never received would be a lie; "its turn ended
    and it never reported success" is what we actually observed. `sb restore`, and
    `Broker._revive` for an agent that simply calls `sb` again, both bring it back — this
    ends a turn, not an existence.

    Callers MUST have consulted herdr. See `collect`.
    """
    if not names:
        return
    from . import store                      # local: keeps this module importable alone

    ts = store.now()
    db.executemany(
        f"UPDATE agents SET state='{GONE_STATE}', ended_at=COALESCE(ended_at, ?) "
        f"WHERE name=?", [(ts, n) for n in names])
    db.commit()
    for name in names:
        # The distinction the state column does not carry: this end was observed, not
        # reported. See GONE_STATE.
        store.log_event(db, kind="gone", agent=name, state=GONE_STATE)


def _unread_counts(db: sqlite3.Connection) -> dict[str, int]:
    """`store.unread_for(..., mark=False)` for everyone at once.

    Aggregated rather than looped so status stays one pass, and read-only for the same
    reason `--peek` exists: looking at the board must never eat somebody's mail.
    """
    return {r["to_agent"]: r["n"] for r in db.execute(
        "SELECT to_agent, COUNT(*) n FROM messages WHERE read_at IS NULL GROUP BY to_agent"
    )}


def _undelivered_counts(db: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """Per agent: how much mail it cannot know about, and when the oldest of it arrived.

    Aggregated for the same reason as `_unread_counts` — one pass, and strictly read-only.
    `store.unseen()` is the per-message reader and takes exactly this view; this is the
    counting version, so a board with fifty agents does not become fifty queries.

    `read_at IS NULL` is half the predicate and it is not optional. A message an agent read
    proactively, before the ring it was owed, is un-announced and already in that agent's
    context at the same time; counting it here is what let one row read `MAIL -` and
    `<< UNDELIVERED 8` about the same mailbox. `broker.flush_pending` rings on the same
    pair, so what this counts and what the doorbell chases are one set.

    The human is excluded because they are not an agent and have no doorbell. Nothing is
    addressed to them any more, but a store written before the human mailbox was removed
    still holds such rows, and reporting them as undelivered would put a permanent warning
    on a board about mail that was never going to be announced to anybody.
    """
    return {r["to_agent"]: (r["n"], r["oldest"]) for r in db.execute(
        "SELECT to_agent, COUNT(*) n, MIN(created_at) oldest FROM messages "
        "WHERE delivered_at IS NULL AND read_at IS NULL AND to_agent <> ? "
        "GROUP BY to_agent", (HUMAN,)
    )}


def _last_activity(db: sqlite3.Connection) -> dict[str, int]:
    """When each agent last *did* something.

    Three signals, because no single one covers a working agent: events (every `sb` call
    it makes lands there), messages it sent, and messages it read. Mail *arriving* is
    pointedly not activity — that is somebody else acting, and counting it would reset the
    idle clock on exactly the silent agent you are trying to spot.
    """
    seen: dict[str, int] = {}
    for sql in (
        "SELECT agent a, MAX(created_at) t FROM events "
        "  WHERE agent IS NOT NULL GROUP BY agent",
        "SELECT from_agent a, MAX(created_at) t FROM messages GROUP BY from_agent",
        "SELECT to_agent a, MAX(read_at) t FROM messages "
        "  WHERE read_at IS NOT NULL GROUP BY to_agent",
    ):
        for r in db.execute(sql):
            if r["t"] and r["t"] > seen.get(r["a"], 0):
                seen[r["a"]] = r["t"]
    return seen


def _block_reasons(db: sqlite3.Connection) -> dict[str, str]:
    """Why each blocked agent stopped — the thing the human actually needs.

    SQLite's min/max aggregate hands back the rest of the row it came from, so this is one
    specific block per agent rather than an arbitrary one. Maxing on `id`, not
    `created_at`: timestamps are whole seconds, and two blocks in the same second would
    make "the latest" a coin toss.
    """
    out = {}
    for r in db.execute(
        "SELECT agent, payload, MAX(id) FROM events "
        "WHERE kind='blocked' AND agent IS NOT NULL GROUP BY agent"
    ):
        try:
            out[r["agent"]] = (json.loads(r["payload"] or "{}") or {}).get("why") or ""
        except json.JSONDecodeError:
            continue
    return {k: v for k, v in out.items() if v}


def _last_summaries(db: sqlite3.Connection) -> dict[str, str]:
    """What each agent said when it last called `sb done`.

    Two sources, and the mailbox wins where it has one: the message is the summary the
    parent actually received, whereas the event is clipped for debugging. Maxing on `id`
    for the same reason as `_block_reasons` — one-second timestamps cannot order two
    summaries.

    A ROOT agent has no parent and the human has no mailbox, so its `done` writes no
    message at all (see broker.done) and the event log is the only record of what it said.
    That record is the point — this is where a root agent's summary reaches you, on its
    row here and in full in `sb inspect`.
    """
    out = {}
    for r in db.execute(
        "SELECT agent, payload, MAX(id) FROM events "
        "WHERE kind='done' AND agent IS NOT NULL GROUP BY agent"
    ):
        try:
            body = ((json.loads(r["payload"] or "{}") or {}).get("summary") or "").strip()
        except json.JSONDecodeError:
            continue
        if body:
            out[r["agent"]] = body
    for r in db.execute(
        "SELECT from_agent, body, MAX(id) FROM messages WHERE kind='done' GROUP BY from_agent"
    ):
        body = (r["body"] or "").strip()
        if body.startswith(DONE_PREFIX):
            body = body[len(DONE_PREFIX):].strip()
        if body:
            out[r["from_agent"]] = body
    return out


def _tree(rows) -> list[tuple[Any, int]]:
    """Parent-before-children order, with a depth for each.

    Robust to a store that has lost rows, which is a normal state and not corruption: the
    database is disposable by construction (see store.connect), so an agent whose parent
    was dropped, or adopted rows with no parent at all, must still appear. An unknown
    parent is treated as a root; a cycle is broken rather than followed.
    """
    names = {r["name"] for r in rows}
    kids: dict[Optional[str], list] = {}
    for r in rows:
        parent = r["parent"] if r["parent"] in names and r["parent"] != r["name"] else None
        kids.setdefault(parent, []).append(r)

    out: list[tuple[Any, int]] = []
    seen: set[str] = set()

    def walk(parent: Optional[str], depth: int) -> None:
        for r in kids.get(parent, []):
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            out.append((r, depth))
            walk(r["name"], depth + 1)

    walk(None, 0)
    for r in rows:                      # anything stranded in a cycle: show it, at the left
        if r["name"] not in seen:
            seen.add(r["name"])
            out.append((r, 0))
    return out


def _filter(agents: list[AgentStatus], *, live_only: bool, needs_me: bool,
            mine: Optional[str]) -> list[AgentStatus]:
    """Apply the filters, then put back the ancestors the tree needs to read straight."""
    if not (live_only or needs_me or mine is not None):
        return agents

    by_name = {a.name: a for a in agents}
    keep = {a.name for a in agents}

    scope: Optional[set[str]] = None
    if mine is not None:
        scope = _subtree(agents, mine)
        keep &= scope
    if live_only:
        keep &= {a.name for a in agents if not a.finished or a.unread}
    if needs_me:
        keep &= {a.name for a in agents if a.needs_human}

    for name in list(keep):                 # ancestors, or the indentation lies
        cur, seen = by_name.get(name), {name}
        while cur is not None and cur.parent and cur.parent not in seen:
            if scope is not None and cur.parent not in scope:
                break                       # never climb back out of the caller's subtree
            keep.add(cur.parent)
            seen.add(cur.parent)            # a cycle is broken, not followed (see _tree)
            cur = by_name.get(cur.parent)
    return [a for a in agents if a.name in keep]


def _subtree(agents: list[AgentStatus], root: str) -> set[str]:
    """`root` and everything below it.

    `human` is not an agent and owns no row, so it means the roots — every agent a person
    started directly, and their descendants. That is the whole tree, which is correct: a
    human's agents are all of them.
    """
    kids: dict[Optional[str], list[str]] = {}
    for a in agents:
        kids.setdefault(a.parent, []).append(a.name)

    # Module-level HUMAN, not `from .broker import HUMAN`: the deferred import was here to
    # keep this module importable on its own, and it stopped being needed the moment the
    # name was read from `[vocabulary]` at the top of the file. Two ways to spell one
    # constant is how the two of them come to disagree.
    start = kids.get(None, []) if root == HUMAN else (
        [root] if root in {a.name for a in agents} else [])

    out: set[str] = set()
    frontier = list(start)
    while frontier:
        name = frontier.pop()
        if name in out:
            continue                        # a cycle is broken, not followed (see _tree)
        out.add(name)
        frontier.extend(kids.get(name, []))
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def fmt_age(seconds: int) -> str:
    """Two significant units, never more — this is scanned, not measured."""
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}"
    d, h = divmod(h, 24)
    return f"{d}d{h:02d}h"


def render(snap: Snapshot) -> str:
    """Compact enough to run reflexively; loud enough that drift cannot be missed."""
    lines: list[str] = []
    if snap.herdr_error:
        lines.append(f"! herdr unreachable ({snap.herdr_error}) — "
                     f"showing the store alone, so ALIVE and STALLED are unknown")
    if not snap.agents:
        lines.append("(no agents)" + (f"  [{snap.hidden} hidden by filters]" if snap.hidden else ""))
        return "\n".join(lines)

    labels = [("  " * a.depth) + a.name for a in snap.agents]
    w_name = max(len("AGENT"), *(len(x) for x in labels))
    w_role = max(len("ROLE"), *(len(a.role) for a in snap.agents))
    w_ws = max(len("WORKSPACE"), *(len(a.workspace or "-") for a in snap.agents))

    lines.append(f"{'AGENT':<{w_name}}  {'ROLE':<{w_role}}  {'STATE':<8}  {'HERDR':<7}  "
                 f"{'MAIL':>4}  {'AGE':>6}  {'IDLE':>6}  {'WORKSPACE':<{w_ws}}")
    for label, a in zip(labels, snap.agents):
        lines.append(
            f"{label:<{w_name}}  {a.role:<{w_role}}  {a.state:<8}  {_herdr_cell(a):<7}  "
            f"{(str(a.unread) if a.unread else '-'):>4}  {fmt_age(a.age):>6}  "
            f"{fmt_age(a.idle):>6}  {(a.workspace or '-'):<{w_ws}}{_flags(a)}"
        )
        lines.extend(_what(a))

    lines.append("")
    lines.append(summary_line(snap))
    lines.extend(_attention(snap))
    return "\n".join(l.rstrip() for l in lines)


def _what(a: AgentStatus) -> list[str]:
    """What this agent is actually doing, under its row.

    A second line rather than a column: "who is doing what" is the question people open
    this readout to answer, and a task wide enough to answer it would push every other
    column off a terminal. On a finished agent the summary comes too — the row says `done`
    and the next thing anyone wants is *done with what*.
    """
    pad = "  " * a.depth + "    "
    out = []
    if a.task:
        out.append(f"{pad}↳ {clip(a.task)}")
    if a.finished and a.summary:
        out.append(f"{pad}✓ {clip(a.summary)}")
    return out


def clip(text: str, width: int = TASK_CLIP) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= width else flat[:width - 1] + "…"


def _herdr_cell(a: AgentStatus) -> str:
    if a.alive is None:
        return "?"
    return (a.herdr_state or "-") if a.alive else "-"


def _flags(a: AgentStatus) -> str:
    f = []
    if a.stalled:
        f.append("<< STALLED")
    if a.gone:
        f.append("<< GONE")
    if a.waiting_to_be_rung:
        # Flagged beside STALLED and GONE because it is the same class of problem: the
        # board looks fine and something is silently not happening.
        f.append(f"<< UNDELIVERED {a.undelivered}, {fmt_age(a.undelivered_age)}")
    if a.at_prompt:
        f.append("<< AT PROMPT")
    elif a.blocked:
        f.append("<< BLOCKED")
    return ("  " + " ".join(f)) if f else ""


def summary_line(snap: Snapshot) -> str:
    """The one-line count. Public because the board shows the same line, and two
    hand-maintained copies of "how many agents, and how many of them are trouble" is how
    two readouts of one store come to disagree in front of you."""
    c = snap.counts
    bits = [f"{c['agents']} agents", f"{c['alive']} alive"]
    for key, word in (("stalled", "stalled"), ("gone", "gone"),
                      ("blocked", "blocked"), ("at_prompt", "at a prompt")):
        if c[key]:
            bits.append(f"{c[key]} {word}")
    if c["unread"]:
        bits.append(f"{c['unread']} unread")
    if c["undelivered"]:
        bits.append(f"{c['undelivered']} undelivered")
    if c["hidden"]:
        bits.append(f"{c['hidden']} hidden")
    return " · ".join(bits)


def _attention(snap: Snapshot) -> list[str]:
    """The two lists worth acting on, each with the command that acts on it.

    Kept to one line per agent. A status readout that needs scrolling to reach the part
    that matters is one whose warnings get skimmed past.
    """
    out: list[str] = []

    needs = snap.needs_human
    if needs:
        # This IS the human's inbox. There is no other one: an agent that needs a person
        # blocks, and a block is a row here until somebody answers it.
        w = max(len(a.name) for a in needs)
        out.append("")
        out.append("NEEDS YOU")
        for a in needs:
            if a.blocked:
                why = a.blocked_why or "no reason recorded"
                out.append(f"  {a.name:<{w}}  blocked: {why[:70]}"
                           f"  →  sb tell {a.name} \"...\"")
            elif a.at_prompt:
                out.append(f"  {a.name:<{w}}  waiting at a prompt in its own TUI"
                           f"  →  sb inspect {a.name}")
            elif a.waiting_to_be_rung:
                # BEFORE the unread branch, because undelivered mail is unread by
                # definition — nobody told the agent it exists. Reporting it as "not
                # picked up" would blame the agent for silence that is ours.
                #
                # Plain subtraction, no clamp: undelivered is `unread AND un-announced`,
                # so it is a subset of unread and this cannot go negative. It used to be
                # clamped, which is how the impossible case printed a fluent wrong
                # sentence instead of an obviously broken one.
                told = a.unread - a.undelivered
                extra = f", plus {told} unread it WAS told about" if told else ""
                out.append(f"  {a.name:<{w}}  {a.undelivered} never announced to it, "
                           f"oldest {fmt_age(a.undelivered_age)}{extra}"
                           f"  →  sb inspect {a.name}")
            else:
                out.append(f"  {a.name:<{w}}  {a.unread} unread, not picked up"
                           f"  →  sb inspect {a.name}")

    pending = [a for a in snap.agents if a.waiting_to_be_rung]
    if pending:
        w = max(len(a.name) for a in pending)
        out.append("")
        out.append("UNDELIVERED — written, never announced, and unread, so the agent has no")
        out.append("way to know it exists. The doorbell is held back while an agent is")
        out.append("mid-turn (`agent prompt` interleaves), and released when it goes idle.")
        out.append("Mail an agent read of its own accord is never counted here, however we")
        out.append("came to ring — it is already in front of it.")
        for a in pending:
            out.append(f"  {a.name:<{w}}  {a.undelivered} waiting, "
                       f"oldest {fmt_age(a.undelivered_age)}, "
                       f"{'still working' if a.state in RUNNING and not a.stalled else a.state}")
        out.append(f"  {'':<{w}}  →  sb inspect <name> to read it; the doorbell rings when "
                   f"the agent next goes idle")

    drift = [a for a in snap.agents if a.stalled or a.gone]
    if drift:
        w = max(len(a.name) for a in drift)
        out.append("")
        out.append("DRIFT — the store called these 'working'; their panes disagree, so the")
        out.append("STATE column above is a guess. A GONE one is recorded as failed on")
        out.append(f"sight ({GONE_STATE} from the next readout on) — its pane is gone, so")
        out.append("nothing will ever move that row again. A STALLED one is left alone:")
        out.append("its pane is still there, and marking it done here would invent a")
        out.append("summary its parent never received.")
        for a in drift:
            what = (f"GONE     no longer in herdr — its pane closed under it"
                    if a.gone else
                    f"STALLED  herdr says {a.herdr_state} — turn ended, `sb done` never called")
            out.append(f"  {a.name:<{w}}  {what}, quiet {fmt_age(a.idle)}")
        out.append(f"  {'':<{w}}  →  sb inspect <name>, then: "
                   f"sb tell <name> \"wrap up and run sb done\"")
    return out


# ---------------------------------------------------------------------------
# `sb inspect` — one agent, everything
# ---------------------------------------------------------------------------
#
# `sb status` answers "what is the board doing". This answers the next question, the one
# that used to need hand-written python against the store: "what is going on with THIS
# agent". It is the same join, plus the four things that only matter once you have picked
# an agent — where it lives (workspace, pane, cwd, session, transcript), what is owed to
# it or by it (mail, and any ask nobody has answered), what it last said, and what its
# terminal actually printed.
#
# The terminal tail comes from output.py unchanged — the reader that falls back from a
# live pane to the on-disk transcript. That fallback is why this stays useful on an agent
# whose pane was closed hours ago, which is exactly when it is asked for.

DEFAULT_EVENTS = config.setting("display.events")

# Lines of terminal tail. Same setting output.py reads — imported there rather than from
# there because output.py is imported lazily inside `inspect` to keep the two decoupled.
DEFAULT_LINES = config.setting("display.output_lines")


@dataclass
class Detail:
    """One agent, at full width."""

    agent: AgentStatus
    pane_id: Optional[str] = None
    terminal_id: Optional[str] = None
    cwd: Optional[str] = None
    session_id: Optional[str] = None
    transcript: Optional[str] = None
    unread: list[dict] = field(default_factory=list)
    # Never announced and never read. A subset of `unread`, kept apart for the reason the
    # module note gives: this agent has no way to know these exist, so they are not mail
    # it ignored.
    undelivered: list[dict] = field(default_factory=list)
    # Asks with no reply, in both directions. Kept apart because they mean opposite
    # things: one is somebody stuck on this agent, the other is this agent stuck on
    # somebody. A single "pending" list would need the reader to work out which.
    owed: list[dict] = field(default_factory=list)      # asks TO it, unanswered
    waiting_on: list[dict] = field(default_factory=list)  # asks BY it, unanswered
    events: list[dict] = field(default_factory=list)
    output: Any = None                                  # output.Output, or None

    def as_dict(self) -> dict:
        # The message LISTS get their own keys rather than overwriting the counts they
        # came from. `unread` means a number in `sb status --json`, and one key that is a
        # number in one command and a list in another is a trap for anything consuming
        # both — so the counts stay exactly what they are on the board, and the bodies
        # arrive alongside them.
        d = self.agent.as_dict()
        d.update(
            pane_id=self.pane_id, terminal_id=self.terminal_id, cwd=self.cwd,
            session_id=self.session_id, transcript=self.transcript,
            unread_mail=self.unread, undelivered_mail=self.undelivered,
            owed=self.owed, waiting_on=self.waiting_on,
            events=self.events,
            output=({"source": self.output.source, "detail": self.output.detail,
                     "path": self.output.path, "text": self.output.text}
                    if self.output is not None else None),
        )
        return d


def inspect(
    db: sqlite3.Connection,
    h: Optional[Herdr],
    name: str,
    *,
    lines: int = DEFAULT_LINES,
    events: int = DEFAULT_EVENTS,
    now: Optional[int] = None,
) -> Detail:
    """Everything about one agent. Raises KeyError if there is no such agent."""
    from . import output as output_mod
    from . import store

    row = store.get_agent(db, name)
    if row is None:
        raise KeyError(f"no such agent: {name}")

    snap = collect(db, h, now=now)
    agent = next((a for a in snap.agents if a.name == name), None)
    if agent is None:                       # _tree drops nothing, so this cannot normally happen
        raise KeyError(f"no such agent: {name}")

    path = store.transcript_path(row)
    d = Detail(
        agent=agent,
        pane_id=row["pane_id"] or None,
        terminal_id=row["terminal_id"] or None,
        cwd=row["cwd"] or None,
        session_id=row["session_id"] or None,
        transcript=str(path) if path else None,
        unread=[_msg(m) for m in db.execute(
            "SELECT * FROM messages WHERE to_agent=? AND read_at IS NULL ORDER BY id",
            (name,))],
        # Same predicate as `_undelivered_counts`, and it must stay the same or the count
        # in the header and the bodies underneath it would be about different sets.
        undelivered=[_msg(m) for m in db.execute(
            "SELECT * FROM messages WHERE to_agent=? AND delivered_at IS NULL "
            "AND read_at IS NULL ORDER BY id",
            (name,))],
        owed=[_msg(m) for m in _unanswered(db, name, mine=False)],
        waiting_on=[_msg(m) for m in _unanswered(db, name, mine=True)],
        # Read BEFORE the output, so this call's own `read_output` event is not the first
        # thing an inspect reports back to you.
        events=[{"id": r["id"], "kind": r["kind"], "at": r["created_at"],
                 "payload": r["payload"]} for r in store.recent_events(
                     db, agent=name, limit=events)[::-1]],
    )
    if h is not None and lines:
        d.output = output_mod.read_output(db, h, name, lines=lines)
    return d


def _unanswered(db: sqlite3.Connection, name: str, *, mine: bool) -> list:
    """Asks with nothing pointing back at them.

    Deliberately not restricted to *unread* asks: the one worth surfacing is the ask the
    agent has already read and still not answered, because that is the one that looks
    handled and is not. Same NOT EXISTS correlation `store.pending_ask` uses — a plain
    `tell` answers an ask, so a reply is a row whose `reply_to` names it.
    """
    col = "from_agent" if mine else "to_agent"
    return db.execute(
        f"""SELECT m.* FROM messages m
            WHERE m.{col}=? AND m.kind='ask'
              AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.reply_to = m.id)
            ORDER BY m.id""",
        (name,),
    ).fetchall()


def _msg(m) -> dict:
    return {"id": m["id"], "from": m["from_agent"], "to": m["to_agent"],
            "kind": m["kind"], "body": m["body"], "at": m["created_at"],
            "read": m["read_at"] is not None}


def render_detail(d: Detail, *, now: Optional[int] = None) -> str:
    """One screen, most-urgent first: what it is, then what is owed, then what it said."""
    from . import store

    now = store.now() if now is None else now
    a = d.agent
    out: list[str] = []

    head = f"{a.name}  ({a.role})"
    head += f"  child of {a.parent}" if a.parent else "  (top level)"
    out.append(head)
    out.append(f"  task       {clip(a.task, 200) if a.task else '(none recorded)'}")
    out.append(f"  state      {a.state}   herdr: {_herdr_cell(a)}{_flags(a)}")
    if a.blocked and a.blocked_why:
        out.append(f"  blocked    {a.blocked_why}")
    out.append(f"  age        {fmt_age(a.age)}   idle {fmt_age(a.idle)}")
    out.append(f"  workspace  {a.workspace or '-'}")
    out.append(f"  cwd        {d.cwd or '-'}")
    out.append(f"  pane       {d.pane_id or '-'}   session {d.session_id or '-'}")
    out.append(f"  transcript {d.transcript or '-'}")

    for m in d.owed:
        out.append("")
        out.append(f"UNANSWERED ASK from {m['from']} "
                   f"({fmt_age(max(0, now - m['at']))} ago, "
                   f"{'read' if m['read'] else 'not even read'})")
        out.append(f"  {clip(m['body'], 200)}")
        # Not `sb tell <asker>`: a reply only answers an ask when it runs the other way
        # (see store.pending_ask), so answering on this agent's behalf is not a thing a
        # third party can do. The action is to get THIS agent moving.
        out.append(f"  →  {m['from']} is blocked until {a.name} answers: "
                   f"sb tell {a.name} \"answer {m['from']}: ...\"")

    if d.waiting_on:
        out.append("")
        out.append("IT IS WAITING ON")
        for m in d.waiting_on:
            out.append(f"  {m['to']:<12} {clip(m['body'], 90)}  "
                       f"({fmt_age(max(0, now - m['at']))} ago)")

    if d.undelivered:
        out.append("")
        out.append(f"UNDELIVERED — {len(d.undelivered)} written, never announced to it, "
                   f"never read (oldest {fmt_age(a.undelivered_age)})")
        out.append("  The doorbell is held while an agent is mid-turn and released when it")
        out.append("  goes idle; until then this agent does not know these exist. Anything")
        out.append("  it has already read is excluded — every row below has `read: false`.")
        for m in d.undelivered:
            out.append(f"  [{m['id']}] from {m['from']}: {clip(m['body'], 90)}")

    # Undelivered mail is unread too, and it was just listed above under a heading that
    # explains WHY it is unread. Repeating it here under "not picked up" would both
    # duplicate it and contradict that explanation, so this section is the remainder:
    # mail the agent was actually told about and has still not looked at.
    silent = {m["id"] for m in d.undelivered}
    ignored = [m for m in d.unread if m["id"] not in silent]
    if ignored:
        out.append("")
        out.append(f"MAIL — {len(ignored)} unread, announced and not picked up")
        for m in ignored:
            out.append(f"  [{m['id']}] from {m['from']}: {clip(m['body'], 90)}")

    if a.summary:
        out.append("")
        out.append("LAST SUMMARY")
        out.append(f"  {clip(a.summary, 200)}")

    if d.events:
        out.append("")
        out.append("RECENT EVENTS")
        for e in d.events:
            out.append(f"  {fmt_age(max(0, now - e['at'])):>6} ago  {e['kind']:<18} "
                       f"{clip(e['payload'] or '', 60)}")

    out.append("")
    if d.output is None:
        out.append("OUTPUT  (not read)")
    else:
        head = f"OUTPUT  ({d.output.source}"
        head += f": {d.output.path}" if d.output.path else ""
        head += ")"
        out.append(head)
        if d.output.detail:
            out.append(f"  ({d.output.detail})")
        body = d.output.text.rstrip("\n")
        if body:
            out.extend(f"  {l}" for l in body.splitlines())
        else:
            out.append("  (nothing)")
    return "\n".join(l.rstrip() for l in out)


# ---------------------------------------------------------------------------
# `sb wait` — block until an agent gets somewhere
# ---------------------------------------------------------------------------
#
# FOR HUMANS AND SHELL SCRIPTS. An agent must never call this: agents end their turn and
# get poked when a child reports (see broker.done), so a waiting agent is one burning a
# turn to do what the doorbell already does for free.
#
# It is NOT a deferred `ask`, and the two are deliberately not merged. Deferred delivery
# already exists and is the default: `Broker._ring` holds a doorbell back while the target
# is mid-turn and `flush_pending` rings once it is free, so "when you are idle" is what
# `tell` and `ask` already do, with nobody blocking. What this waits for is a STATE, on
# behalf of a caller that is not an agent — it has no turn to end and no doorbell to be
# rung on, and `sb wait w1 && deploy` in a shell script has no other shape available.
#
# It does NOT poll the store. herdr blocks server-side in `agent wait --until`, and we
# read the store once each time that returns — because the two can disagree, and `done` is
# a STORE state that herdr has no vocabulary for (herdr's enum is idle|working|blocked|
# unknown; broker.done reports `idle` and records `done` with us).
#
# Herdr.wait handles the other half: `agent wait` is not turn-scoped, so a previous turn's
# transition satisfies it instantly. Passing `since_seq` makes it re-wait until herdr's
# state_change_seq has actually advanced past the value we snapshotted.

# A ceiling on one server-side block, not a poll interval. herdr's report can be dropped
# silently (see StateWriteDropped: a stale seq or a session-owner conflict both return
# ok), and then no state change is ever announced for a `done` that really happened. This
# bounds how long that costs us, without turning a blocking wait into a busy one.
WAIT_SLICE_MS = config.setting("timeouts.wait_slice_ms")

# What `--for` accepts. The first four are store states; `idle` is the honest name for
# "its turn ended", however it ended — which is the one an agent that stalls still reaches.
WAIT_STATES = tuple(config.setting("states.wait"))

# How long `sb wait` blocks by default. `--timeout` overrides it per call.
WAIT_TIMEOUT = config.setting("timeouts.wait")


@dataclass
class WaitResult:
    name: str
    ok: bool
    until: str
    state: str                       # the store's state when we stopped
    herdr_state: Optional[str]
    waited: int                      # seconds
    reason: str = ""                 # why not, when not ok

    def as_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "until": self.until,
                "state": self.state, "herdr_state": self.herdr_state,
                "waited": self.waited, "reason": self.reason}

    def render(self) -> str:
        if self.ok:
            return f"{self.name} is {self.state} (waited {fmt_age(self.waited)})"
        return (f"{self.name} did not reach {self.until} — {self.reason} "
                f"(state {self.state}, waited {fmt_age(self.waited)})")


def wait_for(
    db: sqlite3.Connection,
    h: Herdr,
    name: str,
    *,
    until: str = "done",
    timeout: int = WAIT_TIMEOUT,
    clock: Callable[[], float] = time.time,
) -> WaitResult:
    """Block until `name` reaches `until`, or the timeout runs out.

    Returns rather than raises on failure: a timeout is an ordinary outcome of waiting,
    and the caller wants the state it stopped at, not a traceback.
    """
    from . import store

    if until not in WAIT_STATES:
        raise ValueError(f"cannot wait for {until!r}; one of {', '.join(WAIT_STATES)}")
    if store.get_agent(db, name) is None:
        raise KeyError(f"no such agent: {name}")

    started = clock()
    deadline = started + timeout
    seq: Optional[int] = None
    hstate: Optional[str] = None

    def result(ok: bool, state: str, reason: str = "") -> WaitResult:
        return WaitResult(name=name, ok=ok, until=until, state=state,
                          herdr_state=hstate, waited=int(clock() - started), reason=reason)

    while True:
        row = store.get_agent(db, name)
        if row is None:
            return result(False, "-", "its row disappeared from the store")
        state = row["state"]
        if _reached(state, hstate, until):
            return result(True, state)
        if state in FINISHED:
            # It will never move again, so waiting the rest of the timeout out would be a
            # lie about what we are doing.
            return result(False, state, f"it finished as {state} instead")

        remaining = deadline - clock()
        if remaining <= 0:
            return result(False, state, f"timed out after {timeout}s")

        # herdr's own view first: it is where the seq comes from, and an agent herdr has
        # never heard of cannot be waited on at all.
        slice_ms = min(WAIT_SLICE_MS, max(1, int(remaining * 1000)))
        t0 = clock()
        try:
            if seq is None:
                cur = h.get_agent(name)
                if cur is None:
                    return result(False, state,
                                  "herdr does not know this agent (its pane is gone) — "
                                  "nothing will ever announce a change")
                seq, hstate = cur.change_seq, cur.state
                if _reached(state, hstate, until):
                    return result(True, state)

            got = h.wait(name, until=_next_transition(hstate, until), since_seq=seq,
                         timeout_ms=slice_ms)
            seq, hstate = got.change_seq, got.state
        except HerdrError as e:
            # A slice that ran its course tells us nothing except "still nothing"; loop and
            # read the store again. One that fails immediately is a real failure — the
            # agent is gone, or herdr is down — and looping on it would spin.
            if clock() - t0 < min(1.0, slice_ms / 2000):
                return result(False, state, f"herdr: {e}")
        except OSError as e:
            return result(False, state, f"herdr unreachable: {e}")


def _reached(state: str, herdr_state: Optional[str], until: str) -> bool:
    if until == "idle":
        # Finished counts: an agent that called `sb done` is not running a turn either, and
        # herdr may not have caught up (or may have dropped the report entirely).
        return state in FINISHED or herdr_state in IDLE_LIKE
    return state == until


def _next_transition(herdr_state: Optional[str], until: str) -> str:
    """The herdr state to block on: always the one the agent is NOT currently in.

    `agent wait --until <state>` returns INSTANTLY when the agent is already in that state
    (verified against a live 0.8.0 binary). Asking an idle agent to wait until idle
    therefore returns at once, `since_seq` correctly refuses to accept it as progress, and
    the adapter has to back off and ask again — which turns a wait into a series of naps.
    Waiting for the state it is *not* in blocks properly instead: an idle agent is waited
    toward `working`, and the turn-ending `idle` is picked up on the next pass through
    `wait_for`'s own loop.

    Only `idle` and `working` are ever asked for. `blocked` is not, and that costs nothing
    an agent does — broker.block reports `idle` and records the block with us, and it
    explains why — only herdr's own detector spotting an unanswered permission prompt,
    which `wait_for` reads off the next status pass anyway.
    """
    target = WORKING if until == "working" else IDLE
    at_target = (herdr_state in IDLE_LIKE) if target == IDLE else (herdr_state == WORKING)
    if at_target:
        return IDLE if target == WORKING else WORKING
    return target
