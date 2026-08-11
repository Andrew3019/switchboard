"""M4 — the readouts: `sb status` (the board) and `sb inspect` (one agent).

The store says what an agent was *told* to be; the activity signal says whether it is
mid-turn; herdr says what its pane looks like. Read any one alone and you get a confident
answer that is regularly wrong, so this module exists to join them and to say so when they
disagree.

The disagreement that matters is one specific pair:

    state: working        turn: idle        →  STALLED

`turn` is `agents.turn`, switchboard's OWN signal, written by the two hooks in `hooks.py`
at the two edges of a turn (see that file for why the edges and not a heartbeat). It is
primary here. herdr's reading is the fallback for a row that has no signal yet, and the
corroboration for the one thing our signal cannot see — see `AgentStatus.signal_drift`.
That order is not a preference: herdr infers a running turn by matching Claude's spinner
glyphs in the terminal title, and when Claude Code 2.1.228 changed those glyphs every pane
on the machine read idle, so this file called every working agent STALLED and the
reconciler pinged them mid-tool-call (`audit/status-ground-truth.md`).

That agent finished its turn and never called `sb done`. It happens constantly and
silently — nothing errors, nothing logs, the pane just goes quiet — and every readout
that trusts the store alone reports it as busy for the rest of the day. Naming it is the
whole point of this file. We deliberately do NOT repair it: marking it done here would
fabricate a summary its parent never received, and the parent is still waiting on that
message (see broker.done). Surfacing beats guessing (C9).

One exception, and it is about what the label MEANS rather than what to do about it: an
agent that has never been given anything beyond its spawn placeholder — a workspace lead,
or a top-level orchestrator from a bare `sb start` — is idle because nobody has asked it
for anything. STALLED there is false, and a warning that is routinely false is a warning
nobody reads. So the flag is not computed for those rows at all until the first thing
arrives for them (`agents.awaiting_task`); nothing about what gets swept changes.

Two other joins fall out of the same table:

    store: working        herdr: not listed  →  GONE     (pane closed under it)
    store: anything       herdr: blocked     →  a human is being asked something in the TUI

Everything is computed from ONE `agent list` and one pass over the store. Per-agent herdr
calls are what make a status command too slow to run reflexively, and a status command you
hesitate to run is the same as not having one.

A third disagreement, in the mailbox rather than the pane:

    never announced AND never read            →  UNDELIVERED

A doorbell can be held back rather than rung: `sb tell --when-idle` waits for the target's
turn to end, and any message at all waits while the target is blocked. `broker.flush_pending`
rings those once the wait is over, and that introduces a way for mail to sit forever: if the
flush never runs, nothing is on the agent's screen and nothing is in its inbox count.
(The default mode rings straight away — `agent prompt` queues rather than interleaving, so
a working agent is reached at its next step without losing the one it is on.)

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
gets the same flags with none of the writes. It also takes more than one reading: an
absence is remembered (`agents.absent_since`) and has to last (`_confirmed_gone`), because
one short `agent list` is a hiccup and used to be enough to end a live agent.

Three commands live here because all three are the same join, at three widths:

    status   every agent, one line each
    inspect  ONE agent, everything — including the tail of its terminal (via output.py)
    wait     block until the join says an agent has reached a state
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Collection, Optional

from . import config
from .herdr import (
    BLOCKED, DELIVER_ATTEMPTS, DELIVER_TIMEOUT_MS, SPAWN_ATTEMPTS, SPAWN_BACKOFF,
    SPAWN_TIMEOUT_MS, UNKNOWN, Herdr, HerdrError,
)

# Which states count as what — `[states]` in defaults/settings.toml. The state NAMES are
# the store's schema; the groupings are policy, and policy is config.

# herdr derives a fifth *display* state, `done` = idle and not yet looked at (Herdr
# .report_state documents it). For drift it means exactly what idle means: no turn is
# running. Treating it as its own thing is how a stalled agent gets missed.
IDLE_LIKE = frozenset(config.setting("states.idle_like"))

# The two words OUR OWN signal writes into `agents.turn` (see `hooks.py`). Read from
# `[states]` rather than imported from `store`, and that is not a stylistic choice: this
# module is in the renderers' import graph (`panel`, `board`) and a renderer must never
# load the store — an invariant `test_panel` pins in a fresh interpreter. Two spellings of
# one word is what settings.toml exists to prevent, so both sides read the same key.
TURN_WORKING = config.setting("states.turn_working")
TURN_IDLE = config.setting("states.turn_idle")

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
# make, each running its full timeout, and every backoff sleep between them — including
# the sleep `start_agent` takes after its LAST failure, before it raises (`herdr.py:370`).
# The backoff is linear, so those sleeps are a triangular number, not one interval:
#
#     3 attempts x 90 s  +  2 s x (1 + 2 + 3)  =  282 s
#
# Derived from `[retries]` and `[timeouts]` rather than restated, because restating it is
# how it went stale: it read `timeout x attempts` = 270 s, which is 12 s SHORT of the spawn
# it guards, and the 12 s it dropped are exactly the backoff. `test_status` pins the
# relationship by running the real retry loop, so a change to herdr's policy fails a test
# instead of quietly shortening this.
_SPAWN_WORST_CASE = (
    SPAWN_ATTEMPTS * (SPAWN_TIMEOUT_MS / 1000)
    + SPAWN_BACKOFF * (SPAWN_ATTEMPTS * (SPAWN_ATTEMPTS + 1) / 2)
)

# The per-attempt timeout is enforced on herdr's side, and it overshoots: the slowest
# `agent start` in the store is 90 198 ms against a 90 000 ms bound, three of which puts
# the true worst case ~0.6 s past the derivation. The row is also claimed a moment before
# the first attempt begins, and `age` is measured from the claim. A few seconds cover both.
#
# Erring long is the cheap direction — a genuinely dead claim is reaped one window later,
# whereas erring short kills real agents during their own spawn.
SPAWN_SLACK = 5
SPAWN_GRACE = _SPAWN_WORST_CASE + SPAWN_SLACK

# How long an agent that has NEVER run an `sb` command is allowed to look idle before that
# idleness is read as a stall. A third question again, and the narrowest of the three: not
# "is this row a claim" (SPAWN_GRACE) nor "is it dead" (GONE_CONFIRM_GRACE), but "has this
# agent ever taken a turn at all?"
#
# It has to be a clock, and that is the honest thing to say about it. Nothing in the store
# records that herdr once saw an agent `working`: the collector is the only process that
# watches continuously and it is read-only by design, so the fact is never written down.
# The one durable trace an agent leaves of having run is its `session_id`, claimed on its
# first `sb` call — after which "idle" really does mean a turn that started and ended.
# Before it, `idle` and `not started yet` are the same reading, and the reconciler pinged a
# freshly delegated agent two seconds after its `delegate` event on the strength of it
# (`audit/phase3-integration.md`) — a nudge that says "your turn ended without a report" to
# an agent whose turn has not begun.
#
# Sized as the delivery's OWN worst case, and derived from it rather than restated for the
# reason `_SPAWN_WORST_CASE` is: nothing should be able to say "the agent never started"
# before the machinery that hands it the task has given up trying. `deliver` re-sends
# `deliver_attempts` times, each waiting `deliver_ms` for a turn to appear, with the same
# backoff between them as a spawn retry.
#
# Not the delivery window alone: measured in an isolated clone, an agent delegated at t
# read `idle` to herdr until t+26s and the one-window version of this constant (20 s) still
# left four seconds of it exposed. Measured from the last thing that happened to the row
# rather than from its creation — a slow `agent start` can put a minute between the claim
# and the task, and it is the task that starts the clock that matters.
#
# Erring long costs a genuinely silent agent one window before the reconciler speaks, which
# the stop hook has already spoken to and the board shows regardless; erring short is the
# false nudge this exists to end.
STALL_GRACE = (
    DELIVER_ATTEMPTS * (DELIVER_TIMEOUT_MS / 1000)
    + SPAWN_BACKOFF * (DELIVER_ATTEMPTS * (DELIVER_ATTEMPTS + 1) / 2)
)

# How long a row has to stay CONTINUOUSLY absent from herdr before that absence is written
# down as a death (see `_record_gone`).
#
# A different question from SPAWN_GRACE, and deliberately a different constant: that one
# asks how long a session-less row still looks like a spawn in progress, this one asks how
# many readings an absence has to survive before we believe it. One `agent list` that comes
# back short — a herdr hiccup, a restart mid-answer, a machine under load — used to be
# enough to end a live agent's turn, and the store's own history has three agents marked
# failed during one night's startups because of it.
#
# Wall-clock rather than a count of readings: `collect` has no loop of its own, so "three
# polls" means "three separate `sb` invocations", which could be three seconds or three
# hours apart and therefore means nothing.
#
# Erring long is the cheap direction here too — a genuinely dead agent reads `working` for
# one window longer, which the next reaping command fixes, whereas erring short reproduces
# the bug this exists for.
GONE_CONFIRM_GRACE = config.setting("timeouts.gone_confirm_grace")

# `sb done "<summary>"` reaches the parent as a message body with this prefix (see
# broker.done). Stripping it here keeps the prefix an implementation detail of the
# mailbox rather than something every reader has to know about.
DONE_PREFIX = config.setting("vocabulary.done_prefix")

# Long enough to say what an agent is doing, short enough not to wrap a terminal.
TASK_CLIP = config.setting("limits.task_clip")

# Whether whole archived subtrees are drawn row by row or collapsed to one line. Read here
# rather than in each renderer so `sb status` and the panel cannot end up on different
# defaults — `board.layout` takes this one too. `config.flag`, not `config.setting`,
# because a quoted "false" is a true string and would silently invert it.
SHOW_ARCHIVED = config.flag("display.show_archived")

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
    # Switchboard's OWN activity signal — `agents.turn`, written by the two hooks in
    # `hooks.py` at the two edges of a turn. `working` | `idle`, and None for a row no
    # hook has ever fired for: a row predating the column, an agent nobody spawned with
    # our settings file, or one freshly restored. Every reader below treats None as "fall
    # back to herdr" and behaves exactly as it did before this existed.
    #
    # Defaulted, and last, because it has to be: a hand-built row in a test or a panel
    # snapshot from an older `sb --json` has no such field, and this must not be the thing
    # that makes those constructors fail.
    turn: Optional[str] = None
    # Mail neither announced nor read — see `undelivered_age` and the module note.
    undelivered: int = 0
    undelivered_age: int = 0        # seconds since the OLDEST one was written; 0 = none
    # Whether any of that mail came from the human — the one thing that lifts a block.
    undelivered_answer: bool = False

    @property
    def blocked(self) -> bool:
        return self.state == "blocked"

    @property
    def display_state(self) -> str:
        """The one word a readout shows for this agent. Five of them, not four.

        The store's `state` column is a self-report about the TASK — "still open", or the
        terminal word the agent itself wrote. It is not an observation of the pane, and
        drawing it raw is what let a single row say `working` in its STATE column and
        `STALLED — idle 12m` beside it: two vocabularies, un-reconciled, on one line
        (`audit/status-model-audit.md` §1.3, and the contradiction Andrew reported). So
        the join this module already computes happens for the STATE column too, once,
        here, and every readout draws the result:

            task open  + herdr says a turn is running   →  working
            task open  + herdr says otherwise           →  idle
            anything else                               →  the store's word

        `idle` is not a new state and `stalled` is not a sixth one. Nothing is stored,
        no predicate is new: `state`, `alive` and `herdr_state` are all already on this
        row, and this reads the three together instead of one of them alone. `stalled`
        stays exactly what it is — idle with nothing to excuse it, no live child, no
        awaited first task, no startup grace — and it stays a QUALIFIER, drawn beside
        this word by `_flags` and `board.note`, never instead of it.

        Both halves must be known, the rule `stalled` and `gone` are already built on.
        With herdr unreachable (`alive is None`) nothing was observed, so the store's own
        word stands and `render` says at the top that ALIVE is unknown. With herdr
        answered and the agent absent from its list (`alive is False`) no turn can be
        running, so the word is `idle` and the GONE note beside it says why — until the
        absence is confirmed and `_record_gone` writes `failed` into `state` for real.

        Since the activity signal exists, the middle line of that table is OURS and herdr
        is the fallback: `agents.turn` is a fact Claude Code's own runtime wrote down at
        the two edges of the turn, and herdr's reading is a screen-scrape that one
        cosmetic change upstream was able to invalidate for every pane on the machine.
        So the order is: our signal if we have one, herdr's if we do not.

        One herdr reading still outranks ours, and only one: `alive is False`, the agent
        is not in herdr's list at all. No turn can be running in a pane that is not there,
        whatever our last edge said — and that is exactly the reading the crash case needs,
        since a session that dies mid-turn leaves `working` behind forever. GONE says why,
        beside it.

        Honest, too, when the pane signal is wrong in the other direction: with no signal
        of our own, herdr reading a working agent as idle (its busy detector is a known
        upstream weak point) shows `idle` here rather than `working`, which is what the row
        is entitled to claim from what it observed. It never shows two answers at once.
        """
        if self.state not in RUNNING:
            return self.state
        if self.alive is False:
            return "idle"
        if self.turn is not None:
            return self.state if self.turn == TURN_WORKING else "idle"
        if self.alive is None:
            return self.state
        return self.state if self.herdr_state not in IDLE_LIKE else "idle"

    @property
    def signal_drift(self) -> bool:
        """Our signal says a turn is running, and there is no agent in that pane at all.

        THE FAILURE MODE THE ACTIVITY SIGNAL INTRODUCES, named rather than left silent. A
        session that crashes, is killed, or is `/exit`ed mid-turn never fires `Stop`, so
        `agents.turn` says `working` for good: no doorbell will ever be released to it, the
        reconciler will never ping it, and `sb cleanup` cannot reach a row that is not
        finished. Nothing in the fleet moves it. That is a strictly worse silence than the
        one this signal fixed, unless something independent notices — so this is herdr
        earning its keep as the cross-check (requirement 2 of the brief): it watches the
        pane, which we cannot.

        `herdr_state == UNKNOWN` and deliberately NOT `in IDLE_LIKE`, which is the reading
        you would reach for first and is currently useless. herdr's `unknown` means "plain
        shell or unrecognised program" — no Claude rule matched anything — and it is
        produced by the ABSENCE of a match, so it survives the broken spinner regex that
        took its `working` rule out (`audit/status-ground-truth.md` §4). Its `idle`, by
        contrast, is what a live agent mid-tool-call reads as today, so drifting on that
        would light up every genuinely working agent in the fleet.

        `idle >= STALL_GRACE` is a debounce and not a timeout: a pane can read `unknown`
        for a moment during a spawn, or while a tool call has a full-screen program in it.
        No N is being asked to distinguish a long tool call from a finished turn — the
        edges already do that — so the constant here is only "long enough that a flicker
        is not a death", and the existing grace is the right size for that without
        inventing a new one.

        A flag, never a state: `stalled` is idle with no excuse, this is working with no
        pane to work in, and neither is a sixth word for the STATE column. Nothing is
        written back — surfacing beats guessing (C9) — and the row is left for a person,
        which is why `needs_human` counts it.
        """
        return (self.state in RUNNING and self.turn == TURN_WORKING
                and self.alive is True and self.herdr_state == UNKNOWN
                and self.idle >= STALL_GRACE)

    @property
    def stall_source(self) -> str:
        """Which signal said this agent's turn had ended. For the readouts, one phrase."""
        return ("its turn-end hook fired" if self.turn is not None
                else f"herdr says {self.herdr_state}")

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
    def ringable(self) -> bool:
        """Mail here that a doorbell could actually announce, right now.

        `waiting_to_be_rung` says mail is stuck; this says a ring would move it. The two
        differ in exactly one case and it is the expensive one: an agent that is BLOCKED
        is not idle, it is stopped waiting on a person, and `broker._ring` holds its mail
        back for as long as that lasts (`ring_held {"reason":"blocked"}`). Nothing about
        that changes on its own — the only thing that lifts a block is the human's answer,
        and that answer arrives as an `sb tell`, which flushes the doorbell in its own
        process before the collector's next tick could. So there is nothing here for a
        tick to discover, and a trigger that keeps looking pays a spawned process every
        ten seconds for as long as the person takes to answer: 85 of them for one block
        held thirteen minutes (`audit/phase1-acceptance-4.md` §4). Idle costs nothing —
        `PRINCIPLES.md` C10.

        The held mail itself is untouched and still `undelivered`: the board still says
        `<< UNDELIVERED 2, 13m`, `--needs-me` still lists the agent, `flush_pending` still
        re-derives it on every `sb` command, and it is delivered the moment the block is
        answered. What stops is only the rediscovering.

        A blocked agent whose backlog contains the human's own reply is ringable again,
        because that ring is the one `_ring` lets through — and if the agent happens to be
        mid-turn when it arrives, this is what keeps the doorbell chasing it afterwards.
        """
        if not self.undelivered:
            return False
        return self.undelivered_answer or not self.blocked

    @property
    def needs_human(self) -> bool:
        """Something is owed to this agent, and only a person can pay it.

        `stalled` belongs here for the same reason the other three do, even though the
        agent is not asking: its turn ended without `sb done` or `sb block`, so the store
        will say `working` about it forever, no doorbell will ever ring it again, and
        `sb cleanup` will not touch a row that is not finished. Nothing in the fleet moves
        it. Left out of this predicate it appeared only in the DRIFT block at the bottom
        of a full readout and in `--json`, so `sb status --needs-me` — the filter for
        "what wants me" — was the one view that dropped it.

        `signal_drift` belongs here for exactly the same reason, one step further along:
        its turn never ended as far as anything can tell, its pane is running no agent,
        and there is no mechanism at all that will ever touch that row again. See that
        property for why it is not simply reaped.
        """
        return (self.blocked or self.at_prompt or self.unread > 0
                or self.waiting_to_be_rung or self.stalled or self.signal_drift)

    @property
    def archived(self) -> bool:
        """Its pane is not on herdr, and it is old enough for that to mean something.

        A RENDERING FACT. Computed every tick and never written anywhere — no column, no
        state, no event. "Absent from herdr" is the same signal that, when it was
        *recorded*, ended live agents (`_record_gone` writing `failed` from a read path).
        Using it to decide what to DRAW is safe for one reason: a wrong guess costs one
        frame and the next tick corrects it. The moment anything stores this, that
        argument is gone and so is the safety.

        `alive is False`, not `if not self.alive`. `alive` is a tri-state and `None`
        means herdr could not be reached at all, so `is False` is reachable only when
        herdr *answered*. A herdr outage therefore archives nothing and the whole tree
        draws, with no branch anywhere having to remember to check for it — the type
        carries the rule, and a `None` cannot be forgotten the way an `if` can.

        `age >= SPAWN_GRACE` and deliberately not the exact `spawning` predicate, which
        also reads `session_id` (see `collect`) — not a field of this dataclass, so a
        renderer could not recompute it. Dropping that half makes the guard strictly
        WIDER, so this never archives anything the collector's own predicate would have
        spared; at worst a genuinely dead agent stays on screen for one grace window.
        That is the reversible direction: showing a dead row costs a line, hiding a live
        one costs the human an agent.

        It does not read `state`. Not `finished`, not `gone`, not `blocked`. Archived
        means one thing — herdr does not have this pane — and what the store believes
        about the agent is the STATE column's question, answered next to it.
        """
        return self.alive is False and self.age >= SPAWN_GRACE

    def as_dict(self) -> dict:
        d = {f: getattr(self, f) for f in (
            "name", "role", "parent", "depth", "state", "herdr_state", "alive", "turn",
            "stalled", "gone", "unread", "age", "idle", "last_activity",
            "workspace", "task", "blocked_why", "summary",
            "undelivered", "undelivered_age", "undelivered_answer",
        )}
        # Derived, but part of the contract: a consumer must not have to re-derive drift
        # from a rule that lives in this file.
        d.update(display_state=self.display_state,
                 blocked=self.blocked, at_prompt=self.at_prompt,
                 finished=self.finished, needs_human=self.needs_human,
                 waiting_to_be_rung=self.waiting_to_be_rung,
                 ringable=self.ringable,
                 signal_drift=self.signal_drift,
                 archived=self.archived)
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
    tree: Optional[Collection[str]] = None,
    reap: bool = True,
) -> Snapshot:
    """The whole readout: one herdr call, one pass over the store.

    The three filters narrow *which rows are shown*, never what is computed — everything
    is still joined first, so a hidden agent can never change what a visible one says.
    They AND together, and each reports what it dropped as `hidden`.

    `live_only` drops finished agents, but keeps any that still hold unread mail (mail on
    a finished agent is mail nobody will ever read unless it is visible).
    `needs_me` keeps only agents that are blocked, sitting at a prompt, holding unread
    mail, or stalled — the ones an action is owed to.
    `mine` scopes to one agent's own subtree (pass `human` for the roots and everything
    under them, which for a human is the whole tree).
    `tree` is THE BOUNDARY rather than a filter: the names the caller is allowed to see at
    all, computed by `Broker.tree_of`. `None` is the human, who is bounded by nothing.

    All four keep the ancestors of whatever survives, or the indentation would lie about
    who reports to whom. `mine` and `tree` bound that: neither re-adds anything from
    outside the caller's scope.

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
    # Whether this store can remember an absence at all. A store an older `sb` last stamped
    # has no `absent_since`, and a reader cannot add it (see `store.connect`); the debounce
    # then degrades to what this file did before it existed, which is documented at
    # `_record_gone`.
    tracks_absence = bool(rows) and "absent_since" in rows[0].keys()
    # Parents with work still out, by exactly the rule the stop gate asks it by
    # (`hooks._has_live_child`: a child row still `working` or `blocked` and not ended).
    # Computed from the rows already in hand rather than re-queried, so this costs nothing
    # and no reader needs a second connection.
    #
    # It joins `awaiting_task` and the two grace windows as an EXCUSE for being idle, and
    # for the same reason they are excuses: an orchestrator that ended its turn because the
    # protocol told it to and is waiting to be poked has done exactly what was asked of it.
    # Calling that STALLED — on the board, in `--needs-me`, in DRIFT — says something false
    # about the one agent shape the design most expects to see idle.
    #
    # The stop gate and the reconciler already exempt the same rows themselves
    # (`hooks.stop_gate`, `broker.reconcile`) and are deliberately left alone: their copies
    # of this test now agree with the flag instead of correcting it. One consequence worth
    # knowing — `reconcile`'s `reconcile_waived` event no longer fires, because the rows it
    # waived no longer arrive as stalled.
    live_parent = {row["parent"] for row in rows
                   if row["parent"] and row["state"] in ("working", "blocked")
                   and row["ended_at"] is None}
    absent_since: dict[str, Optional[int]] = {}
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
        #
        # Both halves, and the session half is the one to be careful with: it ends the
        # grace EARLY, so if anything could set a session id while herdr still did not
        # have the agent, the window would close mid-spawn and the guard would be a
        # formality. Nothing can, today — herdr's `agent start` reply carries no
        # `agent_session` at all (checked against every stored reply in the event log), so
        # `delegate`'s write lands NULL and the only real writer is `_claim_session`, which
        # needs the agent itself to have run an `sb` command. An agent that has run `sb` is
        # an agent herdr had. Should `agent start` ever start returning a session id, this
        # becomes a live hole and the condition has to go.
        spawning = row["session_id"] is None and (now - row["created_at"]) < SPAWN_GRACE
        # An agent nobody has asked for anything yet is idle for the only reason it could
        # be, and calling that STALLED says something false about it — a workspace lead or
        # a top-level orchestrator waiting for its first instruction has finished exactly
        # the work it was given. It is the label that changes here and nothing else: the
        # row is still `working`, still swept by the same rules, still shown. See
        # `agents.awaiting_task`, which `broker` sets at spawn and the first message clears.
        #
        # Read defensively because the readers that reach this first — the board, the
        # collector — hold a READ-ONLY connection and cannot migrate the store (see
        # `store.connect`). Missing the column reads as 0, which is the label the row
        # already had; the alternative is every tick raising until a writer runs.
        awaiting = "awaiting_task" in row.keys() and bool(row["awaiting_task"])
        # Read defensively for the same reason, and remembered per row rather than
        # re-queried: the write that uses it is in the reap path (`_record_gone`), which is
        # the only place that both can write and is running current code.
        if tracks_absence:
            absent_since[name] = row["absent_since"]
        last = max(row["created_at"], activity.get(name, 0))
        # An agent with no session id has never run an `sb` command, so nothing here has
        # ever seen it take a turn — and for `STALL_GRACE` after the last thing that
        # happened to it, "idle" is as likely to mean "has not started" as "ended without
        # saying anything". Calling that a stall is what pinged a two-second-old agent.
        # Once the session id is there the grace is over for good, whatever the clock says.
        starting = row["session_id"] is None and (now - last) < STALL_GRACE
        # OUR signal, read defensively for the reason `awaiting_task` is: the board and
        # the collector reach this on a READ-ONLY connection and cannot migrate a store
        # older than the column. Missing reads as None, which is exactly what None means
        # anyway — no turn edge has ever been recorded here — and every predicate below
        # falls back to herdr for it.
        turn = row["turn"] if "turn" in row.keys() else None
        # Whether this agent's turn is OVER. The one question `stalled` and the reconciler
        # actually ask, answered by our own signal where we have one and by herdr where we
        # do not. Before the signal existed this line WAS the whole of it, and it is the
        # line that broke: herdr infers a running turn from Claude's spinner glyphs in the
        # terminal title, Claude Code 2.1.228 changed them, and every pane on the machine
        # read idle — so every working agent was stalled, was pinged mid-tool-call, and
        # had its held mail delivered into the turn it was still running.
        turn_over = (turn == TURN_IDLE) if turn is not None else (
            bool(alive) and hstate in IDLE_LIKE)
        agents.append(AgentStatus(
            name=name,
            role=row["role"],
            parent=row["parent"],
            depth=depth,
            state=row["state"],
            herdr_state=hstate,
            alive=alive,
            turn=turn,
            # The join this file exists for, now with a signal of our own on one side of
            # it. Idle with no excuse left: its turn is over (`turn_over` above), it is
            # not awaiting a first task, not still starting, and has nothing of its own
            # still running. See `live_parent`.
            #
            # `alive is not False` rather than `alive`, and the change is deliberate. It
            # used to require herdr to be reachable AND to be listing the agent, because
            # herdr was the only thing that could say a turn had ended; with our own
            # signal, a herdr outage no longer hides a stall. What the guard still does is
            # keep STALLED and GONE mutually exclusive: an agent herdr answered about and
            # did not list has no pane to be pinged in, and that row is GONE's to report.
            stalled=bool(running and turn_over and alive is not False and not awaiting
                         and not starting and name not in live_parent),
            gone=bool(running and alive is False and not spawning),
            unread=unread.get(name, 0),
            age=max(0, now - row["created_at"]),
            idle=max(0, now - last),
            last_activity=last,
            workspace=row["workspace"],
            task=row["task"],
            blocked_why=why.get(name) if row["state"] == "blocked" else None,
            summary=summaries.get(name),
            undelivered=pending.get(name, (0, 0, False))[0],
            # Age of the OLDEST, not the newest: the question is how long this has been
            # sitting, and a fresh message arriving behind a stuck one must not reset it.
            undelivered_age=(max(0, now - pending[name][1]) if name in pending else 0),
            undelivered_answer=pending.get(name, (0, 0, False))[2],
        ))

    # Guarded on `consulted`, and that guard is the whole safety of it: without herdr's
    # side every row looks gone, and this would reap the table on a hiccup.
    #
    # Both writes live inside this one gate, and that is the point rather than tidiness:
    # the process that remembers an absence and the process that acts on it have to be the
    # same one, or the debounce has a writer with no reader. A `reap=False` caller — the
    # board, the collector — holds a read-only connection and cannot write either half.
    if consulted and reap:
        absent = [a.name for a in agents if a.gone]
        if tracks_absence:
            absent = _confirmed_gone(db, absent, absent_since, now)
        _record_gone(db, absent)

    kept = _filter(agents, live_only=live_only, needs_me=needs_me, mine=mine, tree=tree)
    hidden = len(agents) - len(kept)

    return Snapshot(now=now, agents=kept, herdr_error=herdr_error, hidden=hidden)


def _confirmed_gone(db: sqlite3.Connection, absent: list[str],
                    since: dict[str, Optional[int]], now: int) -> list[str]:
    """Of the rows herdr did not list, the ones that have been absent long enough to mean it.

    The debounce, and the whole of it. An absence is remembered in the store (`absent_since`)
    rather than in this process, because the process is gone a moment later: two readings a
    minute apart are two `sb` commands, and a column is the only thing they share.

    Three moves, and the third is the one worth being careful about:

    - absent, nothing remembered → remember it, write nothing. This is the reading that used
      to end an agent's turn on its own.
    - absent, remembered, and continuously so past GONE_CONFIRM_GRACE → hand it back to be
      recorded.
    - present again → FORGET the earlier absence. Continuously is the word that matters: an
      agent seen once in between has not been dying for a minute, it has been up and down,
      and accumulating those gaps would confirm a death that never happened.

    A confirmed row is cleared too. Its verdict is about to be written and the row is
    finished after that, so a stamp left behind would only say an absence is still being
    counted for an agent nothing will look at again.

    Every stamp is written and committed here rather than left for `_record_gone`, so a
    command that dies between the two still leaves the absence remembered. Callers MUST be
    in the reap path — this writes.
    """
    absent_set = set(absent)
    confirmed = [n for n in absent
                 if since.get(n) is not None and now - since[n] >= GONE_CONFIRM_GRACE]
    fresh = [n for n in absent if since.get(n) is None]
    back = [n for n, first in since.items()
            if first is not None and n not in absent_set] + confirmed
    if fresh:
        db.executemany("UPDATE agents SET absent_since=? WHERE name=?",
                       [(now, n) for n in fresh])
    if back:
        db.executemany("UPDATE agents SET absent_since=NULL WHERE name=?",
                       [(n,) for n in back])
    if fresh or back:
        db.commit()
    return confirmed


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

    It is not written off ONE absent reading any more: `_confirmed_gone` is what decides
    which names get here, and only a row that has been continuously absent past
    GONE_CONFIRM_GRACE does. The exception is a store too old to have `absent_since`, where
    there is nowhere to remember an absence and this falls back to recording it on sight —
    the behaviour that shipped before the column, and the reason it is that way round is
    that a row nothing can ever record as gone is a row `sb cleanup` can never reach.

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

    Mail written off as UNDELIVERABLE is not counted, and that is what stops the human's
    queue filling up with rows nothing can ever move. `needs_human` reads this count, so
    one message to an agent that later died kept that agent in NEEDS YOU for the life of
    the store, with no verb — not even for the human — that could clear it
    (`2026-08-09-233230`). The message is still unread and still there; what it has lost is
    any recipient who could read it, and `broker._clear_unreadable_mail` is the only thing
    that decides that. See `store.mark_undeliverable` for what survives.

    Read defensively for the reason `collect` reads `absent_since` defensively: the board
    and the collector reach this on a READ-ONLY connection and cannot migrate a store older
    than the column, and a viewer that raises every two seconds until some writer happens
    to run is worse than one that counts the way it always did.
    """
    where = "read_at IS NULL"
    if _has_column(db, "messages", "undeliverable_at"):
        where += " AND undeliverable_at IS NULL"
    return {r["to_agent"]: r["n"] for r in db.execute(
        f"SELECT to_agent, COUNT(*) n FROM messages WHERE {where} GROUP BY to_agent"
    )}


def _has_column(db: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in db.execute(f"PRAGMA table_info({table})"))


def _undelivered_counts(db: sqlite3.Connection) -> dict[str, tuple[int, int, bool]]:
    """Per agent: how much mail it cannot know about, when the oldest arrived, and
    whether any of it is the human's.

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

    The third field is there for one caller and one decision: `broker._ring` holds a
    blocked agent's mail back unless the human's answer is among it, so "is any of this
    from the human" is exactly what separates mail a doorbell can announce now from mail
    that cannot move until a person acts. `AgentStatus.ringable` is where that is read,
    and the collector's doorbell is why it has to be in the snapshot rather than a second
    query — see `collector.ring_doorbell`.
    """
    return {r["to_agent"]: (r["n"], r["oldest"], bool(r["answer"])) for r in db.execute(
        "SELECT to_agent, COUNT(*) n, MIN(created_at) oldest, "
        "       MAX(from_agent = ?) answer FROM messages "
        "WHERE delivered_at IS NULL AND read_at IS NULL AND to_agent <> ? "
        "GROUP BY to_agent", (HUMAN, HUMAN)
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
            mine: Optional[str], tree: Optional[Collection[str]] = None
            ) -> list[AgentStatus]:
    """Apply the filters, then put back the ancestors the tree needs to read straight."""
    if not (live_only or needs_me or mine is not None or tree is not None):
        return agents

    by_name = {a.name: a for a in agents}
    keep = {a.name for a in agents}

    scope: Optional[set[str]] = None
    if tree is not None:
        scope = set(tree)
        keep &= scope
    if mine is not None:
        sub = _subtree(agents, mine)
        scope = sub if scope is None else (scope & sub)
        keep &= sub
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


@dataclass
class Collapsed:
    """One row standing in for whole archived subtrees, at the depth they were drawn.

    Not an agent and deliberately not shaped like one: a renderer that maps a screen row
    back to an object must be made to notice the difference (`board.agent_at` returns
    whatever the row carries, and a click on this must not focus somebody).
    """

    depth: int
    count: int                      # every agent hidden here, the whole subtree
    needs_human: int = 0            # how many of them were still asking for a person


def collapsed_label(c: Collapsed) -> str:
    """The text of a collapsed row, indented to the level it stands in for.

    `· N need you` is what stops the collapse from being able to bury anything. Archived
    is archived and a blocked agent whose pane died still collapses — but a blocked agent
    is a question nobody can answer any more, so the row that replaced it says how many it
    is carrying. No per-row logic and nothing extra hidden: it labels a row that is
    already there. (Every one of them is still listed by name in NEEDS YOU below, which
    reads `snap.agents` and never sees this.)
    """
    out = ("  " * c.depth) + f"+ {c.count} archived"
    if c.needs_human:
        out += f" · {c.needs_human} need you"
    return out


def display_rows(agents: list[AgentStatus], *, show_archived: bool = False
                 ) -> list[Any]:
    """The tree with fully-archived subtrees replaced by one `+ N archived` row each.

    ONE function for every renderer. `sb status` and the panel are two drawings of one
    snapshot, and a tree rule written twice is a tree rule that ends up disagreeing with
    itself — which is the failure `summary_line`'s docstring already names.

        sealed(x)  ≡  archived(x)  ∧  ∀ c ∈ children(x): sealed(c)

    A *collapse root* is a sealed node whose parent is not sealed. Everything under a
    collapse root is hidden, and for each drawn parent its sealed children merge into a
    single row carrying the size of all their subtrees.

    Two properties do all the work, and both are consequences of the rule rather than
    cases handled in it:

    - **No row that is not archived is ever hidden**, because every hidden node lies in a
      sealed subtree and every node of a sealed subtree is archived.
    - **No row with a visible descendant is ever hidden.** If `x` has a drawn descendant
      then that descendant is not archived, so `x` is not sealed. So there is no such
      thing here as an archived parent whose live child must still be drawn — the rule
      simply declines to hide it, and draws it as an ordinary archived row.

    Collapse is per *whole subtree, at the highest level*: nested sealed levels give ONE
    row, never a chain of `+ 1 archived` at each depth, and `count` is the whole subtree
    rather than the number of direct children.

    The collapsed row goes AFTER its visible siblings so that a live row never changes
    position when an unrelated sibling archives. A group appearing, growing or vanishing
    then moves only the footer of that sibling block, and this is a thing people click.

    Computed over the rows it is GIVEN and nothing else — it never re-derives the tree
    from the store and never re-reads herdr. Under `--live` or `--mine` the filter has
    already dropped rows, so this counts only the archived rows that survived, which is
    the honest reading of "N archived, of what you asked to see"; the filter's own drop
    is `Snapshot.hidden` and stays a separate number.
    """
    rows = list(agents)
    if show_archived or not rows:
        return rows

    # From the rows PRESENT, the same way `_tree` and `_subtree` do it: a parent that was
    # filtered out, or an agent that is its own parent, is a root here. Re-deriving from
    # the store instead would collapse against a tree the caller is not looking at.
    names = {a.name for a in rows}
    kids: dict[Optional[str], list[AgentStatus]] = {}
    for a in rows:
        parent = a.parent if a.parent in names and a.parent != a.name else None
        kids.setdefault(parent, []).append(a)

    sealed: dict[str, bool] = {}
    walking: set[str] = set()

    def is_sealed(a: AgentStatus) -> bool:
        if a.name in sealed:
            return sealed[a.name]
        if a.name in walking:
            # A cycle, which `_tree` breaks rather than follows. Treat the way back round
            # as no obstacle: the cycle's members then stand or fall on being archived,
            # which is what makes a stranded loop one collapse group instead of a hang.
            return True
        walking.add(a.name)
        try:
            out = a.archived and all(is_sealed(c) for c in kids.get(a.name, ()))
        finally:
            walking.discard(a.name)
        sealed[a.name] = out
        return out

    def subtree(a: AgentStatus) -> list[AgentStatus]:
        out, frontier, seen_here = [], [a], set()
        while frontier:
            cur = frontier.pop()
            if cur.name in seen_here:
                continue                    # a cycle is broken, not followed (see _tree)
            seen_here.add(cur.name)
            out.append(cur)
            frontier.extend(kids.get(cur.name, ()))
        return out

    def collapsed(group: list[AgentStatus]) -> Collapsed:
        hidden = [a for g in group for a in subtree(g)]
        # The depth the hidden rows would have been drawn at — they are siblings, so they
        # share one. Taken from the rows themselves rather than from this walk, so the row
        # lands at the nest level of what it replaced even for a tree `_tree` had to
        # straighten out.
        return Collapsed(depth=min(g.depth for g in group), count=len(hidden),
                         needs_human=sum(1 for a in hidden if a.needs_human))

    out: list[Any] = []
    drawn: set[str] = set()

    def emit(siblings) -> list[AgentStatus]:
        """Draw the visible ones in order; hand back the sealed roots among them."""
        group = []
        for a in siblings:
            if a.name in drawn:
                continue
            if is_sealed(a):
                group.append(a)
                drawn.update(x.name for x in subtree(a))
                continue
            drawn.add(a.name)
            out.append(a)
            inner = emit(kids.get(a.name, ()))
            if inner:
                out.append(collapsed(inner))
        return group

    group = emit(kids.get(None, ()))
    # Anything a cycle kept out of the walk, exactly as `_tree` rescues it — at the left
    # margin, and into the SAME root-level group, because one level gets one row.
    group += emit([a for a in rows if a.name not in drawn])
    if group:
        out.append(collapsed(group))
    return out


def render(snap: Snapshot, *, show_archived: Optional[bool] = None) -> str:
    """Compact enough to run reflexively; loud enough that drift cannot be missed.

    `show_archived=None` means "whatever `display.show_archived` says", so a caller with
    no opinion cannot accidentally hard-code one. `sb status --archived` passes True.
    """
    if show_archived is None:
        show_archived = SHOW_ARCHIVED
    lines: list[str] = []
    if snap.herdr_error:
        lines.append(f"! herdr unreachable ({snap.herdr_error}) — "
                     f"showing the store alone, so ALIVE and STALLED are unknown")
    if not snap.agents:
        lines.append("(no agents)" + (f"  [{snap.hidden} hidden by filters]" if snap.hidden else ""))
        return "\n".join(lines)

    rows = display_rows(snap.agents, show_archived=show_archived)
    labels = [collapsed_label(r) if isinstance(r, Collapsed)
              else ("  " * r.depth) + r.name for r in rows]
    # Defaults rather than `max(x, *seq)`: with every root archived, `rows` is a single
    # collapsed row and there is no agent left to measure a ROLE or a WORKSPACE against.
    w_name = max([len("AGENT")] + [len(x) for x in labels])
    w_role = max([len("ROLE")] + [len(r.role) for r in rows if not isinstance(r, Collapsed)])
    w_ws = max([len("WORKSPACE")]
               + [len(r.workspace or "-") for r in rows if not isinstance(r, Collapsed)])

    lines.append(f"{'AGENT':<{w_name}}  {'ROLE':<{w_role}}  {'STATE':<8}  {'HERDR':<7}  "
                 f"{'MAIL':>4}  {'AGE':>6}  {'IDLE':>6}  {'WORKSPACE':<{w_ws}}")
    for label, a in zip(labels, rows):
        if isinstance(a, Collapsed):
            lines.append(label)     # no columns: it is not an agent and must not read as one
            continue
        lines.append(
            f"{label:<{w_name}}  {a.role:<{w_role}}  {a.display_state:<8}  {_herdr_cell(a):<7}  "
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
    if a.signal_drift:
        # Same class as the two above — the board looks fine and something is silently not
        # happening — and the one thing OUR signal cannot see for itself. See
        # `AgentStatus.signal_drift`.
        f.append("<< NO SESSION")
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
        # Not the human's inbox — `sb board` is what Andrew watches, and a blocked agent
        # is a marked row there (DESIGN-TRUTH.md: "`sb status` is not for Andrew — only
        # `sb board` is"). This list is for an agent reading its own cohort, which is why
        # the rows name the agent rather than addressing the reader as the one who answers.
        w = max(len(a.name) for a in needs)
        out.append("")
        out.append("NEEDS YOU")
        for a in needs:
            if a.blocked:
                # Says whose answer counts: only the human's `tell` clears a block
                # (`Broker.tell` passes `answer=(me == HUMAN)`). Another agent's mail is
                # written and then held, so telling one without that caveat sends an agent
                # off to unblock something it cannot unblock.
                why = a.blocked_why or "no reason recorded"
                out.append(f"  {a.name:<{w}}  blocked: {why[:70]}"
                           f"  →  the human answers it: sb tell {a.name} \"...\"")
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
            elif a.stalled:
                # After the mail branches, which are the more actionable read of the same
                # agent: mail nobody announced is fixed by ringing it, and this is not.
                # Before the unread one, because a stalled agent has already been rung and
                # did not move — reporting it as "not picked up" blames it for being stuck.
                out.append(f"  {a.name:<{w}}  stalled {fmt_age(a.idle)} — its turn ended "
                           f"without sb done  →  sb tell {a.name} "
                           f"\"wrap up and run sb done\"")
            elif a.signal_drift:
                # A different sentence from STALLED on purpose: that agent is there and
                # not answering, this one's session is gone from a pane that is still
                # open, so telling it anything reaches nobody. See `signal_drift`.
                out.append(f"  {a.name:<{w}}  its session is gone but its turn never "
                           f"ended — no hook can end it now"
                           f"  →  sb inspect {a.name}, then sb restore {a.name}")
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
        # A blocked agent is the one case where "when it goes idle" is not merely late but
        # wrong: `_ring`/`flush_pending` hold its mail on `_is_blocked`, and only the
        # human's own `tell` lifts that. Said here rather than left to the reader, because
        # a row that reads "waiting, blocked" under the sentence above looks like something
        # that will resolve itself.
        blocked = [a for a in pending if a.blocked]
        if blocked:
            out.append("A blocked agent is the exception: its mail is held until the human")
            out.append("answers the block, not until it goes idle. Answering releases it.")
        for a in pending:
            out.append(f"  {a.name:<{w}}  {a.undelivered} waiting, "
                       f"oldest {fmt_age(a.undelivered_age)}, "
                       f"{'still working' if a.state in RUNNING and not a.stalled else a.state}")
        out.append(f"  {'':<{w}}  →  sb inspect <name> to read it; the doorbell rings when "
                   f"the agent next goes idle")
        if blocked:
            out.append(f"  {'':<{w}}  →  for a blocked one, when the human answers: "
                       f"sb tell <name> \"...\"")

    drift = [a for a in snap.agents if a.stalled or a.gone or a.signal_drift]
    if drift:
        w = max(len(a.name) for a in drift)
        out.append("")
        out.append("DRIFT — the store still has these open; their panes are running nothing,")
        out.append("which is why STATE reads idle above. A GONE one is recorded as failed once it")
        out.append(f"has stayed gone ({GONE_STATE} after {fmt_age(int(GONE_CONFIRM_GRACE))} "
                   f"of it, so a herdr hiccup")
        out.append("does not end a live agent) — its pane is gone, so nothing will ever")
        out.append("move that row again. A STALLED one is left alone:")
        out.append("its pane is still there, and marking it done here would invent a")
        out.append("summary its parent never received.")
        for a in drift:
            if a.gone:
                what = "GONE     no longer in herdr — its pane closed under it"
            elif a.signal_drift:
                # The one row here our own signal did NOT find: it still says the turn is
                # running, and herdr's independent look at the pane is what contradicts it.
                what = ("NO SESSION  our signal still says working, but herdr sees no "
                        "agent in that pane — the session died mid-turn")
            else:
                what = (f"STALLED  {a.stall_source} — turn ended, "
                        f"`sb done` never called")
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
    # Both signals, side by side and labelled, because this is the one readout where the
    # question "which of them said that?" is worth a column: `turn` is ours (the hooks in
    # `hooks.py`), `herdr` is the pane's screen. `-` for a row no hook has fired for.
    out.append(f"  state      {a.state}   turn: {a.turn or '-'}   "
               f"herdr: {_herdr_cell(a)}{_flags(a)}")
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
        if a.blocked:
            # This agent is blocked, so the generic sentence below is false for it: its
            # mail is held on `_is_blocked` in `_ring`/`flush_pending` and nothing but the
            # human's `tell` releases it. Going idle is not a state it passes through —
            # `block` stopped reporting herdr state at all.
            out.append("  This agent is blocked, so its mail is held until the human")
            out.append("  answers the block — not until it goes idle. Until then it does")
            out.append("  not know these exist. Anything it has already read is excluded —")
            out.append("  every row below has `read: false`.")
        else:
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
