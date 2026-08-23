"""The guidance ledger: situational rules, resolved and delivered at the turn they apply to.

Guidance used to be bought at spawn. Every rule that might ever matter to any agent was
flattened into one system prompt (`config.flatten`, `broker._say`) and paid for by every
agent, forever, at the one moment none of it is true yet — so the rule about folding in a
finished isolated child was read by leaf workers that will never spawn anything, hundreds
of turns before the one agent it was written for could act on it, if ever.

This is the other half of that: a table of rules keyed by who / when / what is true, read
fresh on every turn, and delivered through the channel that already exists. Three pieces:

* **The ledger** is DATA — `defaults/guidance.toml`, joined with a repo's own rows the way
  `operator_skills.toml` joins. Not code, so a rule can be added, reworded or deleted
  without a release, and it is re-read every turn, so that edit reaches agents that are
  already running on their next turn.
* **The resolver** (`resolve`) asks which rules match one agent right now. Conditions are
  DETERMINISTIC predicates over observable store facts — counts of children, worktrees,
  unread mail, and the agent's LIVE capability set. There is deliberately no free-text
  condition and nothing that asks a model to judge whether a situation applies: a rule
  either turns on something the store can be asked about, or it does not belong here.
* **The cursor** (`deliver`, and `store.guidance`) is the per-`(agent, rule)` repeat-policy
  state. `hooks._already_nudged` is this same fact for exactly one hardcoded rule, read off
  the event log because it had nowhere else to live; the moment there are two rules, "has
  this one been said?" needs a key, and the key is the pair.

**The channel is the shipped `UserPromptSubmit` hook** (`hooks.run_activity`), which fires
at every turn start and whose stdout the CLI adds to the agent's context. No new hook infra
enters the tree for this. Turn start is not a compromise, it is the right moment: guidance
is "before your next action, remember X", and that is the sentence turn start is. It also
reaches an agent whether or not it ever talks to `sb` — an agent running `git` and tests
directly touches no command, and a dispatch-time hook would miss exactly it.

**When nothing matches, nothing is printed** — the hook stays as silent as it was before
this file existed, which is what makes the whole mechanism free on the turns it has nothing
to say.

**The subtractive rule.** A rule that moves here is DELETED from the spawn prompt. A rule
in both places is paid for twice and drifts, and the only win being claimed is the one that
comes from the prompt getting SHORTER. Reminder-shaped rules move; identity and orientation
prose does not — it has no later turn to wait for and must be true from turn one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from . import config
from . import roles as roles_mod
from . import store

# What an agent sees in front of a delivered rule. The protocol promises that everything sb
# puts in front of an agent is marked, so that a message is never mistaken for the human
# typing — and this arrives in the same context window as the human's own prompt, which
# makes it the one injection where that promise matters most.
MARK = "[sb: guidance]"

# The repeat policies (spec §2.4). `once-until-clear` is the default because it is the one
# that fits a situation: say it when the state arrives, stay quiet while it lasts, say it
# again if it goes away and comes back.
EVERY_TIME = "every-time"
ONCE = "once"
ONCE_UNTIL_CLEAR = "once-until-clear"
REPEATS = (EVERY_TIME, ONCE, ONCE_UNTIL_CLEAR)

# Specificity, most specific first. Precedence decides the ORDER rules are said in, not
# which of them are said: every matching rule is delivered, because a rule that matched and
# was suppressed by a more specific one is a rule nobody can reason about from the ledger.
LIVE_STATE = 3
COMMAND_CONTEXT = 2
ROLE = 1
GLOBAL = 0

# The comparisons a `when` clause may use. A closed set of operators over a closed set of
# facts is the whole of "deterministic and observable": there is no expression to evaluate,
# nothing to `eval`, and a rule cannot ask a question the store cannot answer.
OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


# ---------------------------------------------------------------------------
# The facts a rule may turn on
# ---------------------------------------------------------------------------


class Facts:
    """One agent's observable state, computed lazily and once per resolve.

    LAZY because the ledger is asked about every rule on every turn of every agent, and
    most rules will not need most facts: a fact nothing asks for costs no query. CACHED
    because two rules asking the same question inside one turn must get the same answer —
    a resolver that could contradict itself mid-turn would deliver a rule and clear its own
    cursor in the same breath.

    Every fact here is something the store already records. Nothing is inferred from prose,
    nothing is asked of a model, and nothing is timed: "the Nth child in a turn" is not a
    fact this system has, so the rules that want it turn on the standing state underneath
    it instead (see `shared_write_tracked_children`).
    """

    def __init__(self, db: sqlite3.Connection, row: sqlite3.Row):
        self.db = db
        self.row = row
        self.name = row["name"]
        self._cache: dict[str, Any] = {}

    def get(self, fact: str) -> Any:
        if fact not in self._cache:
            self._cache[fact] = FACTS[fact](self)
        return self._cache[fact]

    # -- the raw material, shared by several facts ---------------------------

    @property
    def children(self) -> list[sqlite3.Row]:
        if "_children" not in self._cache:
            self._cache["_children"] = store.children_of(self.db, self.name)
        return self._cache["_children"]

    @property
    def branch(self) -> Optional[str]:
        if "_branch" not in self._cache:
            self._cache["_branch"] = store.agent_branch(self.db, self.name)
        return self._cache["_branch"]

    def capabilities(self) -> set:
        """What this agent may do NOW — grants included, never the role template.

        Obj. 7, and the reason it is stated as its own rule: a ledger matched against the
        template would go on nagging a worker to "ask your lead to spawn" for the whole
        life of the agent after its lead granted it `spawn`, which is the exact shape of
        nag that makes agents stop reading nudges.
        """
        if "_caps" not in self._cache:
            self._cache["_caps"] = store.held_capabilities(self.db, self.name)
        return self._cache["_caps"]


_FINISHED = tuple(config.setting("states.finished"))
_LIVE = tuple(config.setting("states.live"))


def _children(f: Facts) -> int:
    return len(f.children)


def _live_children(f: Facts) -> int:
    return sum(1 for c in f.children if c["state"] in _LIVE and c["ended_at"] is None)


def _finished_children(f: Facts) -> int:
    return sum(1 for c in f.children if c["state"] in _FINISHED)


def _mergeable_children(f: Facts) -> int:
    """Finished children sitting on a branch that is not the caller's own.

    Exactly what `sb merge` will accept and no more: a `shared` child has no branch of its
    own and its work is already here, so counting it would nudge a lead to merge something
    that would refuse. `store.agent_branch` resolves through the workspace, which is where
    the branch now lives.
    """
    mine = f.branch
    n = 0
    for c in f.children:
        if c["state"] not in _FINISHED:
            continue
        b = store.agent_branch(f.db, c["name"])
        if b and b != mine:
            n += 1
    return n


def _shared_write_tracked_children(f: Facts) -> int:
    """Live children writing tracked files in the CALLER'S OWN checkout.

    The observable underneath D2's "Nth `write-tracked` child in a turn without
    `isolation=own`". Switchboard counts no turns and this file will not invent a counter
    to fake one; what it can see is how many children are, right now, holding the
    side-effect capability while sharing the caller's branch — which is the state the nudge
    is actually about.
    """
    mine = f.branch
    n = 0
    for c in f.children:
        if c["state"] not in _LIVE or c["ended_at"] is not None:
            continue
        b = store.agent_branch(f.db, c["name"])
        if b and b != mine:
            continue                          # its own worktree: not sharing anything
        if roles_mod.CAP_WRITE_TRACKED in store.held_capabilities(f.db, c["name"]):
            n += 1
    return n


def _worktrees(f: Facts) -> int:
    """Open worktrees this agent has minted — `store.open_worktree_counts`, one scan."""
    return store.open_worktree_counts(f.db).get(f.name, 0)


def _unread(f: Facts) -> int:
    """Unread messages. `mark=False`, or reading the fact would consume the mail."""
    return len(store.unread_for(f.db, f.name, mark=False))


def _awaiting_task(f: Facts) -> bool:
    return bool(store._value(f.row, "awaiting_task"))


def _is_top(f: Facts) -> bool:
    return bool(store._value(f.row, "is_top"))


def _state(f: Facts) -> str:
    return f.row["state"]


# The closed set. A `when` clause naming anything else is a ConfigError at load, not a rule
# that silently never fires — a nudge nobody wrote wrong and nobody ever sees is the worst
# of the three outcomes.
FACTS: dict[str, Callable[[Facts], Any]] = {
    "children": _children,
    "live_children": _live_children,
    "finished_children": _finished_children,
    "mergeable_children": _mergeable_children,
    "shared_write_tracked_children": _shared_write_tracked_children,
    "worktrees": _worktrees,
    "unread": _unread,
    "awaiting_task": _awaiting_task,
    "is_top": _is_top,
    "state": _state,
}


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One ledger row. See the header of `defaults/guidance.toml` for the authored form."""

    id: str
    text: str
    repeat: str = ONCE_UNTIL_CLEAR
    role: Optional[str] = None
    command: Optional[str] = None
    when: tuple = ()
    holds: tuple = ()
    lacks: tuple = ()
    order: int = 0

    @property
    def specificity(self) -> int:
        """Which key of the four this rule is keyed on, most specific first (obj. 6).

        Derived from the rule rather than declared by it: a row that says `live-state` and
        carries no live condition would be a lie the ledger could not detect, and the shape
        of the row is the honest answer to "how specific is this?".
        """
        if self.when or self.holds or self.lacks:
            return LIVE_STATE
        if self.command:
            return COMMAND_CONTEXT
        if self.role:
            return ROLE
        return GLOBAL

    def matches(self, facts: Facts, command: Optional[str]) -> bool:
        """Does this rule apply to this agent right now? Every key ANDs."""
        if self.role and facts.row["role"] != self.role:
            return False
        if self.command and self.command != command:
            return False
        if self.holds or self.lacks:
            caps = facts.capabilities()
            if any(c not in caps for c in self.holds):
                return False
            if any(c in caps for c in self.lacks):
                return False
        for clause in self.when:
            fact, op, value = clause
            if not OPS[op](facts.get(fact), value):
                return False
        return True


def _clause(rule_id: str, raw: Any) -> tuple:
    if not isinstance(raw, dict):
        raise config.ConfigError(
            f"guidance.toml: rule {rule_id!r}: each `when` entry must be a "
            f"{{fact, op, value}} table, got {raw!r}")
    missing = {"fact", "op", "value"} - set(raw)
    if missing:
        raise config.ConfigError(
            f"guidance.toml: rule {rule_id!r}: `when` entry missing {sorted(missing)}")
    if raw["fact"] not in FACTS:
        raise config.ConfigError(
            f"guidance.toml: rule {rule_id!r}: no such fact {raw['fact']!r}. "
            f"The facts a condition may turn on are: {', '.join(sorted(FACTS))}.")
    if raw["op"] not in OPS:
        raise config.ConfigError(
            f"guidance.toml: rule {rule_id!r}: no such operator {raw['op']!r}. "
            f"One of: {' '.join(OPS)}.")
    return (raw["fact"], raw["op"], raw["value"])


def _rule(raw: Any, order: int) -> Rule:
    if not isinstance(raw, dict):
        raise config.ConfigError(
            f"guidance.toml: each entry must be a [[rule]] table, got {raw!r}")
    rid = raw.get("id")
    if not rid or not raw.get("text"):
        raise config.ConfigError(
            f"guidance.toml: every rule needs an `id` and a `text`, got {raw!r}")
    repeat = raw.get("repeat", ONCE_UNTIL_CLEAR)
    if repeat not in REPEATS:
        raise config.ConfigError(
            f"guidance.toml: rule {rid!r}: no such repeat policy {repeat!r}. "
            f"One of: {' '.join(REPEATS)}.")
    unknown = set(raw) - {"id", "text", "repeat", "role", "command", "when", "holds", "lacks"}
    if unknown:
        raise config.ConfigError(
            f"guidance.toml: rule {rid!r}: unknown key(s) {sorted(unknown)}")
    return Rule(
        id=rid,
        # Flattened like every other authored prompt text: a rule is written wrapped and
        # readable in the TOML and arrives as one line, because it lands in a context
        # window beside the human's own prompt.
        text=config.flatten(str(raw["text"])),
        repeat=repeat,
        role=raw.get("role"),
        command=raw.get("command"),
        when=tuple(_clause(rid, c) for c in raw.get("when", [])),
        holds=tuple(raw.get("holds", [])),
        lacks=tuple(raw.get("lacks", [])),
        order=order,
    )


def ledger(repo: Optional[Path] = None) -> list[Rule]:
    """The rules this repo has: shipped, joined with `<repo>/.switchboard/guidance.toml`.

    Joined rather than replaced, exactly like `config.operator_skills`: a repo adding one
    rule must not silently lose the shipped ones, and `"!reset"` first is how a repo that
    really does want only its own says so.

    Read through `config.read_toml`, which caches on the file's mtime — so this is a cheap
    call per turn and an EDIT IS LIVE: the next turn of every already-running agent resolves
    against the new text. That property is the whole reason the ledger is a file rather
    than a table of rows or a constant in this module.
    """
    shipped = config.read_toml(config.defaults_dir() / "guidance.toml").get("rule") or []
    p = config.path_for("guidance_file", repo)
    mine = (config.read_toml(p).get("rule") or []) if p is not None else []
    return [_rule(raw, i)
            for i, raw in enumerate(config.join(list(shipped), list(mine)))]


# ---------------------------------------------------------------------------
# Resolving and delivering
# ---------------------------------------------------------------------------


def resolve(db: sqlite3.Connection, name: str, *, command: Optional[str] = None,
            repo: Optional[Path] = None,
            rules: Optional[list[Rule]] = None) -> list[Rule]:
    """Every rule that matches this agent right now, most specific first.

    Ties inside one specificity level keep ledger order, which is why `Rule.order` is
    recorded at load: the author's order is the only tie-break that stays stable as rules
    are added, and sorting by id or text would reshuffle a fleet's guidance on a reword.

    `command` is the command-context key. Nothing passes one yet — surfacing state in
    command output is E2 — so today it is only ever None, and a `command` rule therefore
    never matches at turn start. That is the intended reading of "and/or command output":
    the resolver takes the key, and the second call site is E2's to add.
    """
    row = store.get_agent(db, name)
    if row is None:
        return []
    facts = Facts(db, row)
    matched = [r for r in (ledger(repo) if rules is None else rules)
               if r.matches(facts, command)]
    return sorted(matched, key=lambda r: (-r.specificity, r.order))


def deliver(db: sqlite3.Connection, name: str, *, command: Optional[str] = None,
            repo: Optional[Path] = None,
            rules: Optional[list[Rule]] = None) -> str:
    """What to say to this agent now — the empty string when there is nothing.

    `resolve` says what applies; this says what is worth REPEATING, and writes the cursor
    that makes the answer different next time:

    * `every-time` fires whenever it matches. For a fact so load-bearing that being told it
      twice is cheaper than missing it once — and for nothing else.
    * `once` fires once per agent, ever. The cursor row is the memory, and it outlives the
      stop-chain, the pane and the session, which is precisely what `_already_nudged` had
      to reach into the event log to approximate.
    * `once-until-clear` fires when the state arrives, stays quiet while it lasts, and
      re-arms when it goes away — the clear is written by the same pass, on the turn the
      condition stops holding. So a lead folding in a five-way fan-out is told once, and
      told again the next time a cohort finishes.

    The write happens here, after the decision, and only for what is actually being said:
    a rule suppressed by its cursor must not refresh that cursor, or `once-until-clear`
    would never clear.
    """
    row = store.get_agent(db, name)
    if row is None:
        return ""
    facts = Facts(db, row)
    cursors = store.guidance_cursors(db, name)
    firing = []
    for rule in (ledger(repo) if rules is None else rules):
        cursor = cursors.get(rule.id)
        standing = cursor is not None and cursor["cleared_at"] is None
        if rule.matches(facts, command):
            if rule.repeat == ONCE and cursor is not None:
                continue
            if rule.repeat == ONCE_UNTIL_CLEAR and standing:
                continue
            firing.append(rule)
        elif rule.repeat == ONCE_UNTIL_CLEAR and standing:
            # The state went away. Re-arm, so the next time it comes back the agent hears
            # about it — this is the half that makes the policy "until clear" rather than
            # "once", and it is the only write this function makes for a rule it is not
            # saying anything about.
            store.clear_guidance(db, name, rule.id)
    firing.sort(key=lambda r: (-r.specificity, r.order))
    for rule in firing:
        store.record_guidance(db, name, rule.id)
    return "\n".join(f"{MARK} {r.text}" for r in firing)
