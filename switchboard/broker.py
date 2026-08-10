"""M3 — the broker.

The whole agent-facing contract. The handful of verbs an agent ever needs; a few more for
the human.

Everything here obeys one rule: the agent states an intent, the tooling does the work
(P0). Correlation, retries, seq counters, pane ids, and model names never surface.

Three pairs of verbs look like duplicates and are not. The distinctions are load-bearing,
so they are written down where the code is rather than argued about again:

- **`tell` vs `interrupt`.** `tell` writes a message and rings a doorbell that carries no
  payload — and is held back while the target is mid-turn, because a prompt INTERLEAVES
  rather than queues. `interrupt` cancels the turn with `esc` and puts the instruction
  itself on the wire. Deferring an interrupt would defeat it; interrupting on every `tell`
  is what the deferral exists to stop.
- **`block` vs `ask human`.** There is no `ask human`, and that pair no longer exists:
  the human has NO mailbox, so needing a person is always a block. `block` ends the turn
  and the doorbell restarts it, which for an answer that may take hours is the only shape
  that is not a trap. `ask` is agent-to-agent, where waiting is seconds and the answer is
  used inline.
- **`wait` vs deferred delivery.** `wait` is not `ask --when-idle`; see status.py. Deferred
  delivery is already the default for every message, and `wait` serves callers that are
  not agents.
"""

from __future__ import annotations

import inspect
import json
import os
import shlex
import subprocess
import sys
import time
import re
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from . import config
from . import presets as presets_mod
from . import roles as roles_mod
from . import store
from . import validate
from .herdr import BLOCKED, IDLE, WORKING, Herdr, HerdrError, StateWriteDropped
from .status import GONE_STATE, fmt_age
from . import live

# Vocabulary, read from `defaults/settings.toml` rather than written here. The two
# addresses that are not agents, and the role a top-level orchestrator has (which is also
# its default agent name — `sb start` with no arguments should land somewhere obvious).
HUMAN = config.setting("vocabulary.human")
PARENT = config.setting("vocabulary.parent")
MAIN = config.setting("vocabulary.main_role")
# The agent NAME `sb start` uses, which is not the same thing as its role: there is one
# orchestrator role at every scope, but the top-level agent still wants an obvious name.
MAIN_NAME = config.setting("vocabulary.main_name")

# Config that must follow work into a worktree. Deliberately NOT committed: it is local
# setup, not source. Worktrees get symlinks to the main checkout's copies, so there is
# exactly one true file and no per-worktree `sb init`.
LINKED_CONFIG = tuple(config.setting("paths.linked_config"))

# A workspace is a *named place to work*: one git worktree, one herdr workspace, one lead
# orchestrator. The name is the whole identity — `sb workspace new <name>` run twice, by
# two agents, or by an agent and a human at the same moment, all land in the SAME place.
#
# There is deliberately no lock, no owner, no "in use" flag, and no name suffixing. A
# workspace that only one party may hold is just a checkout; being shareable is the point.
# So reuse is the normal path, not an error path: we try to open, and only create when
# there is nothing to open (or the other way round, when the store already knows it).
#
# The workspace name IS the branch name — no prefix. An earlier draft namespaced branches
# as `sb/<name>`, which meant `workspace new main` forked main into `sb/main` instead of
# attaching to the checkout you were standing in. Attaching is the whole point: a branch
# that already exists is somewhere to go, not a collision to route around. herdr agrees —
# `worktree create --branch` checks out an existing branch and only creates a new one when
# there is nothing to check out.
WORKSPACE_NAME = re.compile(r"^[^\s/-][^\s]*$")   # a branch name; git rejects the rest
# <slug> + this must still fit herdr's 32-char agent name, which is why the slug is
# truncated by exactly this much before it is appended.
LEAD_SUFFIX = config.setting("vocabulary.lead_suffix")
BASE_BRANCH = config.setting("vocabulary.base_branch")
WORKSPACE_ROLE = config.setting("vocabulary.workspace_role")
DEFAULT_ROLE = config.setting("vocabulary.default_role")
# States an agent will never move out of on its own — the same `[states]` grouping the
# readouts use, so "finished" cannot come to mean two different things in two files.
FINISHED = tuple(config.setting("states.finished"))
_NOT_IN_NAME = re.compile(r"[^a-z0-9_-]+")

# The protocol travels as a system prompt, NOT a file.
#   - ~/.claude/CLAUDE.md would leak into every ordinary Claude session
#   - a repo CLAUDE.md would leak into every ordinary session in that repo, and in most
#     repos it is a tracked file we must not touch
# herdr rejects newlines in agent args, not length, so one long line is fine — and being
# generated at every spawn it can never go stale.
#
# The text itself is `defaults/protocol.md`, not a quoted string here: it is prose, it gets
# edited, and it belongs in a file where a diff of it is readable. A repo replaces it with
# its own `.switchboard/protocol.md` — see `Broker._protocol`.
PROTOCOL_LINE = config.protocol()

# How long `sb ask` blocks, and how often it re-reads the store while blocked.
ASK_TIMEOUT = config.setting("timeouts.ask")
ASK_POLL = config.setting("timeouts.ask_poll")
GONE_GRACE = config.setting("timeouts.gone_grace")
# What `sb interrupt` waits for the escape keypress to land before sending the new
# instruction. Without the pause the interrupt races the cancel it depends on.
INTERRUPT_SETTLE = config.setting("timeouts.interrupt_settle")
# How long `sb workspace close`'s re-confirmation waits for the panes it just closed to
# leave the process table before it is allowed to refuse on them. See `_gate`.
TEARDOWN_SETTLE = config.setting("timeouts.teardown_settle")
TEARDOWN_SETTLE_POLL = config.setting("timeouts.teardown_settle_poll")
# Every git we shell out to. A fork waits on `git fetch`, which is a network call and the
# one command here that can hang for as long as a bad connection wants it to.
SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")
# Pointing a spawning pane's `sb` at its own checkout, and confirming it took. See `_pin_sb`.
PIN_MS = config.setting("timeouts.pin_ms")
PIN_ATTEMPTS = config.setting("retries.pin_attempts")
PIN_BACKOFF = config.setting("retries.spawn_backoff")
# How much of a summary or a reason reaches the event log and a desktop notification.
EVENT_CLIP = config.setting("limits.event_clip")
NOTIFY_CLIP = config.setting("limits.notify_clip")
# How far back `unreachable` reads an agent's events to find the last doorbell. Only the
# newest ring matters, and rings are rare next to the herdr call logged on every command.
EVENT_SCAN = 200

class AgentNameTaken(ValueError):
    """Somebody else holds this agent name.

    A ValueError so `sb` already reports it as a caller mistake rather than a traceback —
    which is what `sb delegate --name <existing>` used to produce, because the collision
    only surfaced as a raw `sqlite3.IntegrityError` from the middle of a spawn.

    Not always a mistake, though: two openers of one workspace both try for the same lead
    name by design, and the loser is supposed to join rather than fail. See `_spawn_lead`.
    """

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"the agent name {name!r} is already taken")


class BranchTaken(ValueError):
    """A fork would have to reuse a branch that already exists.

    A ValueError so `sb` reports it as a caller mistake rather than a traceback, and
    refused BEFORE anything is claimed or spawned.

    Never silently attached to, which is the difference between this and
    `workspace_new`: opening a NAMED workspace means "take me to that branch", so an
    existing one is somewhere to go. A fork means "give this agent a tree of its own", and
    an existing branch of that name is somebody else's work, with somebody else's commits
    on it. Both ways forward are in the message because they are genuinely different
    intents — a different agent, or joining the workspace this branch already has.
    """

    def __init__(self, name: str):
        # One argument, because the branch IS the agent's name — that is the rule, and
        # two parameters holding the same string would only invite them to drift apart.
        self.branch = self.agent = name
        super().__init__(
            f"the branch {name!r} already exists, so {name!r} cannot be forked a worktree "
            f"of its own — that branch is somebody else's work, and switchboard will not "
            f"reuse it. Either spawn under a different name (--name <other>), or join the "
            f"workspace that branch already has (--workspace {name})"
        )


class ForkFailed(HerdrError):
    """A child was owed a worktree of its own and could not be given one.

    The spawn is REFUSED rather than degraded. It used to fall through to the parent's own
    cwd with nothing but a `fork_failed` row to say so — and for a top-level orchestrator
    that cwd is the human's main checkout, so a child that was supposed to write on a
    branch of its own wrote in the one place everybody else's uncommitted work lives.
    Sharing a checkout is not a smaller version of forking one; it is a different and
    unrecoverable outcome, and nobody asked for it. See DESIGN-TRUTH: "A fork that fails
    refuses the spawn and tells the parent. It never falls back to Andrew's own checkout."

    A HerdrError so the parent is TOLD — `sb delegate` prints it and exits 1, in the same
    shape as every other spawn failure — rather than reading a name and believing the
    child is off working somewhere safe.
    """

    def __init__(self, name: str, where: Path, cause: HerdrError):
        self.name, self.where, self.cause = name, where, cause
        super().__init__(
            "fork_failed",
            f"{name} could not be given a worktree of its own, so it was not spawned — "
            f"{cause.message}. It is not being put in {where} instead: that checkout is "
            f"somebody else's working copy. Fix the fork, or place the child deliberately "
            f"with `sb delegate --workspace <name>`",
            [name],
        )


class TaskUndelivered(HerdrError):
    """An agent started, and its first task could not be got into it.

    A HerdrError so `sb` reports it as a failed herdr call rather than a traceback, on the
    same path every other spawn failure takes. It is raised in place of returning the
    agent's name, because a name printed for an agent that never received its task is the
    failure this whole spawn path exists to prevent: the caller believes it delegated, and
    the work is never done by anyone.

    The agent it names is recorded `failed` but still has its pane — it is up, it just has
    nothing to do. `sb inspect <name>` shows what is in it and `sb cleanup <name> --force`
    closes it.
    """

    def __init__(self, name: str, cause: HerdrError):
        self.name, self.cause = name, cause
        super().__init__(
            "task_undelivered",
            f"{name} started but never took its task, so nothing was delegated — "
            f"{cause.message}. Nothing is running that work; respawn it. The pane is "
            f"still open: `sb inspect {name}`, then `sb cleanup {name} --force`",
            [name],
        )


class Undeliverable(HerdrError):
    """A ring that had to land in the target's current turn could not be delivered.

    A HerdrError so `sb` already reports it as a failed herdr call rather than a
    traceback, and so nothing that catches herdr failures around a ring stops catching
    this one.

    It exists because the alternative used to be typing the text into the pane's shell
    (`pane run`), where a backtick or a `$(` in an agent-authored interrupt executes as a
    command. That fallback is gone; what replaces it for `sb interrupt` is this — the
    caller is a human reacting to something urgent, and they are owed the news that their
    instruction did not arrive, immediately, rather than a message in the store that looks
    exactly like one the agent already read.
    """

    def __init__(self, who: str, cause: HerdrError):
        self.who, self.cause = who, cause
        super().__init__(
            "undeliverable",
            f"{who}: nothing can be injected into its current turn — herdr answered "
            f"[{cause.code}] {cause.message}, which is what a lost name binding looks "
            f"like, and no later report re-registers it. The message is queued, so it "
            f"will reach {who} on its next `sb inbox`; if it has to land now, that needs "
            f"a human in that pane.",
        )


class SbUnpinned(HerdrError):
    """A pane's `sb` could not be pointed at the checkout the agent is about to work in.

    Refuses the spawn rather than starting the agent anyway, and the reason is the whole
    point of the check: an agent that falls back to the installed `sb` runs the MAIN
    checkout's code no matter which branch its own worktree is on. That is not a
    degradation anybody notices — every command still works, it is simply the wrong build
    — so a whole phase of fixes was acceptance-tested against code that was never running.
    Silence is what made that possible; this is the noise instead.
    """

    def __init__(self, name: str, pane_id: str, bin_dir: str):
        super().__init__(
            "sb_unpinned",
            f"{name}: the pane never confirmed `sb` resolving to {bin_dir}/sb, so it "
            f"would have run whichever build is on PATH — usually the main checkout's, "
            f"not this checkout's. Refused rather than spawned against the wrong code. "
            f"The pane is {pane_id}; `herdr pane read {pane_id}` shows what it did with "
            f"the command.",
            [name, pane_id],
        )


def _own_sb_bin(cwd) -> Optional[Path]:
    """The `bin/` of the checkout at `cwd`, if that checkout ships an `sb` of its own.

    Every worktree and every clone of this repo has a real `bin/sb` — only the installed
    entrypoint is a symlink — and `bin/sb` puts its OWN parent's parent on `sys.path`. So
    naming this directory is the whole of "run the code you are standing in".

    None for anything that is not a checkout of a repo shipping `sb`: an agent sent into
    some other project keeps the installed build, which is the only one it could mean.
    """
    try:
        root = store.worktree_root(Path(cwd))
    except (RuntimeError, OSError):
        return None
    sb = root / "bin" / "sb"
    return sb.parent if os.access(sb, os.X_OK) else None


def _slug(name: str) -> str:
    """A branch name reduced to something herdr will accept as an agent name.

    herdr enforces `[a-z][a-z0-9_-]{0,31}`, so `feature/api-v2` cannot be an agent name
    even though it is a perfectly good branch — and therefore a perfectly good workspace.

    Truncated with room for LEAD_SUFFIX held back, because trimming AFTER appending is how
    a name loses the part that made it unique.
    """
    s = _NOT_IN_NAME.sub("-", name.lower()).strip("-")
    if not s or not s[0].isalpha():
        s = "w-" + s
    return s[:validate.MAX_AGENT_NAME - len(LEAD_SUFFIX)].strip("-")


def _accepts(fn: Callable, param: str) -> bool:
    """Whether the adapter supports an argument yet.

    Placing a tab *in* a workspace needs `create_tab(workspace=...)`, which is an M2
    concern on its own release schedule. Rather than crash a spawn when it is absent, we
    ask — the child then lands in the focused workspace instead of the right one, which is
    cosmetic and self-corrects the moment the adapter grows the argument.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return param in sig.parameters or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )


def _column(row, name: str) -> str:
    """A column that may predate this row.

    The store drops and recreates on a schema change rather than migrating, so a row
    missing `workspace_id` only happens in-process (a hand-built row, a stub). Asking a
    sqlite3.Row for a column it does not have raises IndexError, and a spawn is too
    expensive to lose to that.
    """
    try:
        return row[name] or ""
    except (IndexError, KeyError, TypeError):
        return ""


def _names(found: Sequence[str]) -> str:
    """A list of agent names as a phrase, with the verb that goes with it."""
    return f"{', '.join(sorted(found))} {'is' if len(found) == 1 else 'are'}"


class CleanupResult(list):
    """The names `cleanup` closed, and — the point of it — why it closed nothing else.

    A `list` of the closed names, because that is what every caller has always read out
    of `cleanup` and the refusals are the new half, not the replacement. `refused` carries
    one `(name, reason)` per candidate that a gate held back, in the order the candidates
    were considered.

    It exists because `closed: (nothing)` is not a report. Every gate in `cleanup` used to
    `continue` in silence except the live-descendants one, so an agent that named an agent
    outright and got a blank line back had no way at all to learn which of five rules had
    fired — and `--force`, the documented way through, is exactly the wrong thing to reach
    for before you know that.
    """

    def __init__(self, closed: Sequence[str] = (),
                 refused: Optional[list[tuple[str, str]]] = None):
        super().__init__(closed)
        self.refused: list[tuple[str, str]] = [] if refused is None else refused


def _resolved(path: str) -> Optional[Path]:
    """One directory's identity — its resolved path — or None when it will not resolve.

    The single notion of "the same directory" this command has, and it has to be single.
    It was not: re-validation matched a recorded checkout by resolving it while the
    deregistration matched it as a string, so a path that was equivalent but spelled
    differently — a symlinked parent, which is what `/tmp` and `/var` are on macOS —
    passed the gate as a good worktree, took the whole destructive route, deregistered
    nothing, and still reported success and deleted the branch. Two notions of identity in
    one command is one of them being wrong somewhere.

    `store.checkout_verdict` answers by resolving both sides too, which is what makes the
    two ends of that route agree about which directory is being talked about.

    `RuntimeError` alongside `OSError` because `pathlib` catches the loop's `ELOOP` itself
    and re-raises it as one — so the case this comment names was the case it let through,
    as a traceback out of the middle of the destructive window.
    """
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):            # unreadable, or a symlink loop
        return None


def _same_dir(a: str, b: str) -> bool:
    """One directory, compared as resolved path components rather than as strings.

    Two paths we cannot resolve are treated as the SAME, because the only caller is asking
    "is this the one directory I must never touch" and the answer to that question is never
    allowed to be a guess.
    """
    ra, rb = _resolved(a), _resolved(b)
    return ra is None or rb is None or ra == rb


def _ancestry(pid: int, parents: dict) -> set:
    """A pid, its parent, its parent's parent, up to the top of the tree.

    Cycle-safe rather than trusting the process table to be a tree: this decides which
    processes do not count against a destructive gate, and a loop in it would hang the
    command instead of refusing.
    """
    chain: set = set()
    while pid and pid not in chain:
        chain.add(pid)
        pid = parents.get(pid, 0)
    return chain


class Broker:
    def __init__(self, db, herdr: Herdr, repo: Optional[Path] = None):
        self.db = db
        self.h = herdr
        self.repo = repo or Path.cwd()
        self.roles = roles_mod.load(self.repo)
        self._alive_cache: Optional[dict] = None
        # Set once herdr has been asked and refused to answer. Distinct from an empty
        # cache, which means herdr answered and is running nothing — see `_agent_states`.
        self._alive_unknown = False
        self._ws_ids: dict[str, str] = {}   # workspace name -> herdr id, this call only
        # Whether `_check_integration` has run in THIS process. Not a result, just "asked
        # already": the answer cannot change under us often enough to be worth re-asking,
        # and the cost it saves is a subprocess spawn per state write.
        self._integration_checked = False
        # Only if this repo wrote one. Absent — the normal case — leaves the module-level
        # PROTOCOL_LINE in charge, which is also what makes it patchable in a test.
        self._protocol_override = config.protocol_override(self.repo)

    def _protocol(self) -> str:
        return config.flatten(self._protocol_override) if self._protocol_override \
            else PROTOCOL_LINE

    def _say(self, key: str, /, **fields) -> str:
        """One of the shipped prompt fragments, filled in. See defaults/prompts.toml.

        Positional-only, because `**fields` carries the template's placeholders and one of
        them is called `name`.
        """
        return config.prompt(key, repo=self.repo, **fields)

    def _first_task(self, key: str, task: Optional[str]) -> tuple[str, bool]:
        """What a new agent is told to do, and whether that is anything at all.

        Some agents are spawned before anyone has work for them — a workspace lead, a
        top-level orchestrator from a bare `sb start` — and are handed a placeholder that
        says to wait. The second half of the answer is the bit `agents.awaiting_task`
        holds, and `status` reads it to keep those rows out of STALLED.

        Derived from whether a caller supplied a task at all, never by comparing the text
        back against the placeholder. The placeholder lives in `prompts.toml` and a repo
        may override it; a copy of the string here, or a comparison against it, would go
        stale the moment a prompt was edited — and go stale SILENTLY, which is the
        failure worth designing out: the agent would read STALLED for the rest of its
        life with nothing to say why.
        """
        return (task, False) if task else (self._say(key), True)

    # -- identity --------------------------------------------------------

    def whoami(self) -> str:
        """Who is calling.

        `HERDR_PANE_ID` is injected into every pane, so it works before the agent has done
        anything and for agents we did not spawn.

        **An agent that has reported done is still itself.** Matching only on
        `ended_at IS NULL` made a finished agent resolve to HUMAN, at which point it sent
        messages attributed to the human, could not call `sb done` at all, and — before
        the human mailbox was removed — silently ate the human's mail. Reporting done ends a *turn*, not an existence (C3) — the pane is
        still there and something in it is running `sb` right now, which is proof enough.
        So a finished row still resolves, and is revived on the spot.

        Session id is preferred over pane id because it is unambiguous: pane ids are
        recycled once a pane closes, and a stale row could otherwise capture a new agent.
        """
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if sid:
            row = self.db.execute(
                "SELECT name, ended_at FROM agents WHERE session_id=? "
                "ORDER BY created_at DESC LIMIT 1", (sid,)
            ).fetchone()
            if row:
                return self._revive(row)

        pane = os.environ.get("HERDR_PANE_ID")
        if pane:
            row = self.db.execute(
                "SELECT name, ended_at FROM agents WHERE pane_id=? AND ended_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1", (pane,)
            ).fetchone() or self.db.execute(
                "SELECT name, ended_at FROM agents WHERE pane_id=? "
                "ORDER BY created_at DESC LIMIT 1", (pane,)
            ).fetchone()
            if row:
                name = self._revive(row)
                self._claim_session(name)
                return name
        return HUMAN

    def _revive(self, row) -> str:
        """A finished agent that is calling `sb` again is working again."""
        name = row["name"]
        if row["ended_at"] is not None:
            self.db.execute(
                "UPDATE agents SET ended_at=NULL, state='working' WHERE name=?", (name,))
            self.db.commit()
            store.log_event(self.db, kind="revived", agent=name)
        return name

    def _claim_session(self, name: str) -> None:
        """Register this agent's own session id, once.

        The bundled claude integration would do this for us, but it must stay uninstalled
        — it claims pane session ownership and then herdr silently rejects our state
        writes. So we claim it ourselves, under our own source.
        """
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if not sid:
            return
        a = store.get_agent(self.db, name)
        if not a or a["session_id"] == sid or not a["pane_id"]:
            return
        store.update_agent(self.db, name, session_id=sid, cwd=str(Path.cwd()))
        try:
            self.h.report_session(a["pane_id"], name, sid, store.next_seq(self.db, name))
        except HerdrError as e:
            store.log_event(self.db, kind="claim_session_failed", agent=name, error=str(e))

    def _resolve(self, who: str, me: str) -> str:
        if who == PARENT:
            a = store.get_agent(self.db, me)
            return (a["parent"] if a and a["parent"] else HUMAN)
        return who

    # -- setup -----------------------------------------------------------

    def link_config(self, worktree: Optional[Path] = None) -> list[str]:
        """Point a worktree's config at the main checkout's, if it isn't already.

        Called before anything spawns into a worktree. Idempotent, and it never
        overwrites a real file that is already there.
        """
        wt = Path(worktree or self.repo).resolve()
        try:
            main = store.main_checkout(wt).resolve()      # recorded by `sb init`
        except RuntimeError:
            return []                                     # not a git repo: nothing to link
        if wt == main:
            return []

        linked = []
        for name in LINKED_CONFIG:
            src, dst = main / name, wt / name
            if not src.exists() or dst.exists() or dst.is_symlink():
                continue
            try:
                dst.symlink_to(src)
                linked.append(name)
            except OSError as e:
                store.log_event(self.db, kind="link_failed", error=f"{name}: {e}")
        if linked:
            self._exclude(main, LINKED_CONFIG)
            store.log_event(self.db, kind="link_config", linked=linked, worktree=str(wt))
        return linked

    @staticmethod
    def _exclude(main: Path, names: Sequence[str]) -> None:
        """Keep the symlinks out of `git status`.

        `.git/info/exclude` is shared by every worktree and is not committed — the right
        home for local-only ignores.
        """
        f = store.repo_root(main) / "info" / "exclude"
        f.parent.mkdir(parents=True, exist_ok=True)
        have = f.read_text().splitlines() if f.exists() else []
        add = [n for n in names if n not in have]
        if add:
            with f.open("a") as fh:
                if have and have[-1].strip():
                    fh.write("\n")
                fh.write("# switchboard (local config, not committed)\n")
                fh.write("\n".join(add) + "\n")

    def init(self) -> Path:
        """Pin this repo. Writes no protocol file anywhere.

        The protocol is a system prompt (see PROTOCOL_LINE), so only agents we spawn ever
        see it — ordinary Claude sessions, in this repo or elsewhere, are unaffected.
        """
        try:
            store.write_config({"main_checkout": str(self.repo)}, self.repo)
            self._exclude(self.repo, LINKED_CONFIG)   # keep local config out of git status
        except RuntimeError:
            pass                                      # not a git repo
        return self.repo

    def start(
        self, *, name: Optional[str] = None, task: Optional[str] = None,
        focus: bool = True, board: bool = True,
    ) -> str:
        """The one command worth remembering. Everything else, an agent does for you.

        Always a NEW orchestrator, in a new workspace of its own — a bare one, laid over
        the main checkout rather than a checkout of its own, because a top-level
        orchestrator does no writes (see `_top`). Everything it delegates lands in that
        workspace, so a line of work stays in one findable place.

        It used to mean "take me back", reusing or restoring the last orchestrator unless
        told otherwise. That is a different intent and now has a different spelling: name
        the one you want, `sb start --name main`, which still reuses, restores and hands
        it a task. Unnamed, `sb start` is only ever the start of something.

        Refused from inside a worktree — see `_refuse_outside_main_checkout`.
        """
        self._refuse_outside_main_checkout()
        if name:
            return self._top(name, task, focus, board)
        return self._top(self._next_top_name(), task, focus, board)

    def _refuse_outside_main_checkout(self) -> None:
        """`sb start` belongs in the main checkout, and nowhere else.

        A top-level orchestrator's space is laid over the checkout `sb` was run in
        (`_top` passes `self.repo` as the cwd), and `self.repo` is THIS worktree. Typed
        inside somebody's worktree, `sb start` therefore quietly puts a new top — and,
        through the fork rule, everything it delegates that cannot fork — over an agent's
        working copy, on that agent's branch. Nothing about the command says so.

        The check is skipped, never guessed, when the main checkout cannot be established:
        a repo that `sb init` has not pinned and whose layout defeats the inference is a
        reason not to answer, not a reason to refuse. See DESIGN-TRUTH: "`sb start` run
        inside a worktree is refused too, naming the main checkout to run it from."
        """
        try:
            main = Path(store.main_checkout(self.repo)).resolve()
        except Exception:                       # noqa: BLE001 — not a repo, no config
            return
        if self.repo.resolve() == main:
            return
        raise ValueError(
            f"`sb start` starts a top-level orchestrator over the checkout it is run in, "
            f"and this is a worktree ({self.repo}) — starting one here would lay it over "
            f"somebody's working copy and their branch. Run it from the main checkout "
            f"instead: cd {main} && sb start. To get an agent working in THIS tree, "
            f"delegate to one from the orchestrator that owns it."
        )

    def running_tops(self) -> list[str]:
        """Top-level orchestrators that could still be going, oldest first.

        Two filters, and the second is why this is not just a query. `live_roots` drops
        the ones that ended; herdr drops the ones that ended without saying so, which
        nothing else can — a row only leaves `working` when the agent itself reports it,
        so a crash, an externally closed pane or a herdr restart leaves one claiming to
        work forever.

        Fails OPEN: an unreachable herdr proves nothing, so a row claiming to work is
        left claiming it. Same rule as `_is_registered` and `status.collect`. Nothing
        branches on this any more — `sb start` reads it only to tell the human which
        orchestrators they already have, and naming a dead one there costs a line of
        text, while omitting a live one costs them the way back to it.
        """
        tops = [r["name"] for r in store.live_roots(self.db, MAIN)]
        known = self._agent_states()
        return tops if known is None else [n for n in tops if n in known]

    def _top(self, name: str, task: Optional[str], focus: bool,
             board: bool = True) -> str:
        """Each top-level orchestrator gets its OWN herdr workspace.

        Not a worktree, and not the repo's main workspace: a top-level orchestrator does
        no writes, so it needs somewhere to live, not a checkout. Its own workspace is
        what makes several of them navigable — switching workspaces is one keystroke,
        while hunting the right tab among everyone else's is not.
        """
        held = self._name_held_by(name)
        if held == "worktree":
            # One namespace, one kind of workspace per name. Silently sharing it is how a
            # bare space and a worktree space come to be one row describing two places in
            # two directories — the exact confusion `agents.branch` exists to end.
            raise ValueError(
                f"the name {name!r} already belongs to a workspace with a checkout of its "
                f"own, and a top-level orchestrator's space has none — one name is one "
                f"workspace. Go to that one with `sb workspace new {name}`, or start this "
                f"orchestrator under another name."
            )
        # A bare space is closeable too, and `sb start --name X` is the other door into
        # one: without this the refusal would guard `sb workspace new` and leave a
        # top-level orchestrator free to reopen the name a teardown is mid-way through.
        self._refuse_retiring(name)
        self._record_workspace(name, None)

        a = store.get_agent(self.db, name)
        if a is not None:
            if not a["pane_id"] and not a["session_id"]:
                # A row with no pane AND no session is a husk; replace it rather than
                # orphan it. Same rule as `_spawn_lead`'s (`session id → restore; pane,
                # no session → join; neither → husk`) — this used to claim that rule and
                # test only the session id, which made "pane, no session" a husk too.
                #
                # That shape is not exotic, it is every agent's first turn. herdr's
                # `agent list` carries no session id at all (`herdr.py:104`), so the only
                # writer of the column is `_claim_session`, which needs the agent itself
                # to have run an `sb` command. Until it does, an ordinary `sb start`
                # DELETED its row: the session id went with it, so `restore` had nothing
                # to restore, and `whoami` resolved the still-running agent to HUMAN.
                store.drop_agent(self.db, name)
                return self._top(name, task, focus, board)
            if a["session_id"] and not self._alive_or_unknown(name):
                self.restore(name)
            elif task:
                # Alive, or a pane we cannot see an agent in yet — a claim somebody made
                # moments ago and is still spawning into. Either way the name is somebody
                # else's; hand it the work, as `_joined_lead` does.
                self.tell([name], task, me=HUMAN)
            store.log_event(self.db, kind="start", agent=name, created=False)
            if board:
                self._open_board(name, a["pane_id"])
            self._focus(name, focus)
            return name

        pane, wsid = None, ""
        try:
            r = self.h.create_workspace(name, cwd=str(self.repo))
            wsid = ((r.get("workspace") or {}).get("workspace_id")
                    or r.get("workspace_id") or "")
            pane = ((r.get("root_pane") or {}).get("pane_id")
                    or (r.get("pane") or {}).get("pane_id"))
        except HerdrError as e:
            # Fall through to a tab in the current workspace rather than not starting.
            store.log_event(self.db, kind="workspace_create_failed", agent=name,
                            error=str(e))

        first, awaiting = self._first_task("spawn.start_task", task)
        self.delegate(first, role=MAIN, name=name,
                      cleanup="keep", me=HUMAN, pane=pane,
                      workspace=name, workspace_id=wsid, cwd=str(self.repo),
                      board=board, awaiting_task=awaiting)
        store.log_event(self.db, kind="start", agent=name, created=True, workspace=wsid)
        if board:
            # `delegate` has opened it already; this is the second, idempotent ask that
            # covers a spawn whose split failed there. Read the pane back: when
            # create_workspace failed, `pane` here is None and `delegate` fell back to
            # a tab, whose pane only the row knows.
            row = store.get_agent(self.db, name)
            self._open_board(name, row["pane_id"] if row else pane)
        self._focus(name, focus)
        return name

    def _here(self) -> Optional[str]:
        """The branch this checkout is on — the natural name for a workspace laid over it.

        None on a detached HEAD, where there is no name to infer and the caller must say
        which workspace they mean.
        """
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(self.repo), capture_output=True, text=True,
        )
        branch = (out.stdout or "").strip()
        return branch if out.returncode == 0 and branch and branch != "HEAD" else None

    def _next_top_name(self) -> str:
        """The next free top-level name.

        Free means *never used*, not merely not-running — asked of the store, which keeps
        every root ever created, and never of what is live. Reusing a finished
        orchestrator's name would file two unrelated agents, with two unrelated
        histories, under one name.

        And "used" is a question about WORKSPACES, not only about agent rows. This used to
        ask `get_agent` alone, which is blind to the other minter of names: `sb workspace
        new main-3` installs an agent called `main-3-lead`, not `main-3`, so nothing here
        saw the name was taken and the two mints handed one name to two workspaces in two
        different directories. Both tables are asked now.
        """
        if self._name_free(MAIN_NAME):
            return MAIN_NAME
        n = 2
        while not self._name_free(f"{MAIN_NAME}-{n}"):
            n += 1
        return f"{MAIN_NAME}-{n}"

    def _name_free(self, name: str) -> bool:
        """Has this name ever been used — by an agent, or by a workspace of either kind?"""
        return (store.get_agent(self.db, name) is None
                and self._name_held_by(name) is None)

    def _name_held_by(self, name: str) -> Optional[str]:
        """Which kind of workspace already holds this name: `bare`, `worktree`, or None.

        The name is the identity of a workspace, and it is only unique because this asks:
        two places mint into one namespace — the auto-minter behind a bare `sb start`, and
        a human typing `sb workspace new <name>` — and neither used to consult the other.
        A name is one kind of workspace or the other and never both.

        The record first, and the agent rows only for a workspace that predates or escaped
        it. A RETIRED name holds nothing: retirement is a record of end-of-life, not a
        tombstone on the name, and typing it again reopens it.
        """
        row = store.get_workspace(self.db, name)
        if row is not None:
            if row["retired_at"]:
                return None
            return "bare" if row["checkout"] is None else "worktree"
        if store.known_workspace(self.db, name):
            return "bare" if store.workspace_branch(self.db, name) is None else "worktree"
        return None

    def _record_workspace(self, name: str, path: Optional[str]) -> None:
        """Write down where this workspace's checkout is — on every attach, not just the first.

        A record of where the checkout *is* rather than of where it once was, which is the
        whole reason an attach re-writes it: a row left pointing at a directory that has
        moved (or one that a teardown deleted) makes every later question about the
        workspace start from an answer the code already knows is wrong.

        NULL is a value, not a gap: it says this workspace has no checkout of its own,
        which is what bare means. It is never written over a live worktree workspace's
        path, and reopening a retired name is what typing it again means.
        """
        row = store.get_workspace(self.db, name)
        if path is None and row is not None and row["checkout"] and not row["retired_at"]:
            return
        if row is not None and row["retired_at"]:
            store.reopen_workspace(self.db, name, path)
            store.log_event(self.db, kind="workspace_reopen", workspace=name)
        else:
            store.record_workspace(self.db, name, path)

    def _open_board(self, name: str, pane: Optional[str], *,
                    cwd: Optional[str] = None) -> None:
        """Open the board beside this agent, unless one is up already.

        Every agent, not only an orchestrator: `delegate` calls this, and every spawn
        goes through `delegate`. Called a second time by `_top` and `workspace_new`,
        which is safe by design — the recorded pane makes it a no-op when the board is
        already up, and the retry is what covers the paths that never reach `delegate`
        (a restore) or whose split failed inside it.

        The pane id is remembered so re-running `sb start` returns you to a
        workspace with one board rather than stacking a new one every time. If we
        cannot ask herdr what is open we do nothing: a missing board is a minor
        annoyance, two boards is a mess someone has to close by hand. It is also what
        `_close_board` closes when the agent is closed — a pane opened here is a pane
        this file has to take away again.

        `cwd` is where the board's shell lands: the main checkout for `sb start`, and the
        workspace's own checkout for a workspace lead or a forked child. A board that
        reads the wrong checkout's `.switchboard` is worse than no board, because it
        looks right.

        Never raises. A spawn must not fail because a view would not open.
        """
        if not pane:
            return
        from . import board as board_mod

        key = f"board_pane:{name}"
        try:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if row and row["value"] in self.h.pane_ids():
                return
        except Exception:
            # Deliberately everything: herdr errors, a missing `meta` table, a locked
            # store. None of them is a reason for `sb start` to fail, and all of them
            # mean the same thing here — we cannot prove a board is absent, so we do
            # not open one.
            return

        try:
            new = board_mod.open_beside(self.h, pane, cwd=cwd or str(self.repo))
        except Exception as e:
            # This method promises `sb start` cannot fail because of the board, and
            # a promise enforced only for the errors we predicted is not one. An
            # adapter without `split_pane` raises AttributeError straight through
            # `open_beside`'s own handlers, which is exactly how this was found.
            store.log_event(self.db, kind="board_open_failed", agent=name, error=str(e))
            return
        if new:
            self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                            (key, new))
            self.db.commit()
            store.log_event(self.db, kind="board_open", agent=name, pane=new)
        else:
            # `open_beside` answers a herdr refusal with None so the spawn survives it.
            # Surviving quietly is a different thing: now that every agent asks for a
            # split, a terminal that starts refusing them is a fact somebody has to be
            # able to find, so it goes in the log rather than nowhere.
            store.log_event(self.db, kind="board_open_failed", agent=name,
                            error="herdr would not split the pane")

    def _close_board(self, name: str) -> None:
        """Close the board pane opened beside `name`, and forget it.

        The other half of `_open_board`, and it has to exist for the same reason that
        one records the pane at all: the board is a pane switchboard opened, so it is a
        pane switchboard has to take away. Now that EVERY agent opens with one, a close
        that took only the agent's own pane left an empty tab behind once per agent, and
        a session slowly filled with them.

        Only ever the pane recorded under this agent's own name, and never one another
        live agent is reading: two rows pointing at one pane is not a shape anything
        creates today, but a pane id outliving the pane that had it is, and closing a
        board somebody is still using is not undoable by the person watching it vanish.

        Tolerates a board that is already gone — closed by hand, crashed, never opened —
        because all three are ordinary. The meta row is dropped either way: it is a
        record of a pane we no longer own, and leaving it would make the next
        `_open_board` for this name believe a board is up.

        Never raises. A close that half-happened is worse than a board left behind.
        """
        key = f"board_pane:{name}"
        try:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        except Exception:
            return
        pane = row["value"] if row else None
        if not pane:
            return
        if not self._board_is_only_for(name, pane):
            self._forget_board(key)
            return
        try:
            self.h.close_pane(pane)
        except Exception as e:
            # Including a pane herdr no longer has: "already closed" and "would not
            # close" arrive the same way, and neither is worth failing a cleanup over.
            store.log_event(self.db, kind="board_close_failed", agent=name,
                            pane=pane, error=str(e))
        else:
            store.log_event(self.db, kind="board_close", agent=name, pane=pane)
        self._forget_board(key)

    def _board_is_only_for(self, name: str, pane: str) -> bool:
        """Is `pane` this agent's board alone, or is a still-live agent also on it?"""
        try:
            rows = self.db.execute(
                "SELECT key FROM meta WHERE key LIKE 'board_pane:%' AND value=?",
                (pane,)).fetchall()
        except Exception:
            return False        # cannot prove it is ours; leaving a pane is the safe way
        others = [r["key"].split(":", 1)[1] for r in rows
                  if r["key"] != f"board_pane:{name}"]
        return not any(self._is_live(o) for o in others)

    def _is_live(self, name: str) -> bool:
        a = store.get_agent(self.db, name)
        return bool(a and a["state"] in store.LIVE_STATES and not a["ended_at"])

    def _forget_board(self, key: str) -> None:
        try:
            self.db.execute("DELETE FROM meta WHERE key=?", (key,))
            self.db.commit()
        except Exception:
            pass

    def _focus(self, name: str, focus: bool) -> None:
        if not focus:
            return
        try:
            self.h.focus(name)
        except HerdrError as e:
            store.log_event(self.db, kind="focus_failed", agent=name, error=str(e))

    # -- workspaces ------------------------------------------------------

    def workspace_new(
        self,
        name: Optional[str] = None,
        *,
        task: Optional[str] = None,
        role: str = WORKSPACE_ROLE,
        agent: Optional[str] = None,
        base: str = BASE_BRANCH,
        focus: bool = False,
        board: bool = True,
        me: Optional[str] = None,
    ) -> dict:
        """Open the workspace called `name`, creating it only if it isn't there.

        "new" is what the caller *wants* (P0: verbs are named after wants), not a promise
        that something is created. Same name always means the same worktree, the same
        herdr workspace and the same lead agent — so this is safe to call repeatedly and
        safe to call concurrently. Nothing here is exclusive: another agent or a human may
        be in this workspace already, and that is a normal state, not a conflict.

        With no name, it means the checkout you ran it in — opening a workspace over where
        you already are, which is how you get a visual boundary around a line of work
        without moving anywhere.

        A board opens beside the lead whatever its role — every spawned agent gets one
        now, and it is the small pane rather than half the screen, so a worker that runs
        nobody pays a third of its width for a view of the tree it is part of.
        `board=False` declines it, as `sb start --no-board` does.
        """
        me = me or self.whoami()
        name = name or self._here()
        if not name:
            raise ValueError(
                "no workspace name given, and this is not a git checkout on a branch — "
                "say which workspace you want: sb workspace new <name>"
            )
        if not WORKSPACE_NAME.match(name) or ".." in name:
            raise ValueError(
                f"bad workspace name {name!r}: it is used verbatim as the git branch "
                "name, so no whitespace, no '..', and it may not start with '-' or '/'"
            )
        if self._name_held_by(name) == "bare":
            # The other half of the single namespace (see `_name_held_by`). Forking a
            # worktree under a name a top-level orchestrator is already living under would
            # give one record two checkouts — and this one is worth refusing loudly, since
            # the person can see the name is theirs.
            raise ValueError(
                f"the name {name!r} already belongs to a top-level orchestrator's space "
                f"over the main checkout, which has no checkout of its own — one name is "
                f"one workspace. Open this workspace under another name, or go back to "
                f"that orchestrator with `sb start --name {name}`."
            )
        self._refuse_retiring(name)

        ws = self._attach_workspace(name, base=base)
        self.link_config(Path(ws["path"]) if ws["path"] else None)

        lead = agent or f"{_slug(name)}{LEAD_SUFFIX}"
        row = store.get_agent(self.db, lead) or self._adopt(lead, ws, role=role, me=me)
        if row is not None and self._alive(lead):
            # Somebody is already leading this workspace. Join them; do not start a rival.
            if task:
                self.tell([lead], task, me=me)
            store.log_event(self.db, kind="workspace_open", agent=lead,
                            workspace=name, created=False)
            self._focus(lead, focus)
            return self._result(ws, lead, created=False)

        created = self._spawn_lead(lead, ws, role=role, task=task, me=me, prior=row,
                                   board=board)
        store.log_event(self.db, kind="workspace_open", agent=lead,
                        workspace=name, created=created)
        if board:
            # A fresh lead already has its board from `delegate`; this idempotent second
            # ask is what covers the leads that never reach it — one restored from a
            # session, or one whose split failed there.
            #
            # Read the pane back rather than trusting `ws["pane_id"]`: `_spawn_lead` uses
            # the workspace's root pane only when it is fresh, and opens a tab otherwise —
            # so which pane the lead ended up in is a fact only the row has.
            row = store.get_agent(self.db, lead)
            self._open_board(lead, row["pane_id"] if row else ws["pane_id"],
                             cwd=ws["path"] or None)
        self._focus(lead, focus)
        return self._result(ws, lead, created=created)

    def join_workspace(self, name: str) -> dict:
        """Where a child has to be placed to JOIN the existing workspace `name`.

        What `sb delegate --workspace <name>` resolves: the answer is the placement
        keywords `delegate` already takes, so the CLI is `delegate(..., **join)` and no
        second spawn path exists to drift from the first.

        Shared by name, exactly as `sb workspace new` is — one name is one branch, one
        worktree, one herdr workspace, however many agents work in it. The one difference
        is that this never CREATES. `--workspace` is what somebody types *because* a fork
        was refused (the branch is already checked out); quietly forking them another one
        is the single outcome they did not ask for. So a name nobody has opened is an
        error naming the verb that opens it, not a new worktree.
        """
        self._refuse_retiring(name)
        if store.known_workspace(self.db, name) \
                and store.workspace_branch(self.db, name) is None:
            # A bare space — a top-level orchestrator's, laid over the main checkout.
            # It has no checkout of its own to share, and asking herdr to open one by
            # this name would fork the branch that `create=False` exists to prevent.
            raise ValueError(
                f"workspace {name!r} is a bare space with no checkout of its own, so "
                f"there is no worktree to join — leave --workspace off to work where "
                f"you are"
            )
        try:
            ws = self._attach_workspace(name, create=False)
        except HerdrError as e:
            raise ValueError(
                f"no workspace called {name!r} to join: --workspace joins one that "
                f"already exists and never forks. Open it with `sb workspace new "
                f"{name}`, or leave --workspace off to work where you are ({e.message})"
            ) from e
        store.log_event(self.db, kind="workspace_join", workspace=name,
                        workspace_id=ws["workspace_id"])
        return {"workspace": ws["workspace"], "branch": ws.get("branch"),
                "workspace_id": ws["workspace_id"], "cwd": ws["path"] or None}

    # -- the workspaces themselves, as things rather than as groups of agent rows ------

    def workspace_list(self) -> dict:
        """Every workspace this repo has, from the UNION of three sources.

        `git worktree list`, the `workspaces` table, and the distinct workspace names in
        `agents`. None of the three is a superset of the others, and a listing built on any
        one of them is a listing that lies:

          - only git knows a checkout no agent was ever recorded in — one is on disk right
            now with zero rows, and reporting exactly that orphan is much of the point;
          - only the table knows a workspace with no checkout and no rows, which is every
            retired one;
          - only `agents` knows a workspace that predates or escaped the table.

        And bare workspaces are why "start from git and join the table" is not enough:
        `git worktree list` shows the primary checkout once, so four orchestrators over it
        cannot appear as four things from that side at all.

        Read-only, and deliberately so: it runs the two signals a teardown will later be
        built on — whether anything is live under the checkout, and what ignored content
        would go with it — where being wrong costs a wrong line of text rather than
        somebody's `.env`. Until that command exists this is also what the person pruning
        by hand should be told.
        """
        names: dict[str, set] = {}
        for r in self.db.execute(
            "SELECT DISTINCT workspace FROM agents WHERE workspace IS NOT NULL"
        ).fetchall():
            names.setdefault(r["workspace"], set()).add("agents")
        for row in store.all_workspaces(self.db):
            names.setdefault(row["name"], set()).add("table")
        worktrees = self._worktrees()
        for wt in worktrees:
            # A worktree's workspace name IS its branch name (`_attach_workspace`), so that
            # is what an orphan checkout is filed under; a detached one has only its
            # directory to be known by.
            names.setdefault(wt["branch"] or Path(wt["path"]).name, set()).add("git")

        by_path = {wt["path"]: wt for wt in worktrees}
        merged, existing = self._branch_facts()
        # One scan for the whole listing rather than one per workspace: the answer is a
        # snapshot of the machine, and asking twenty times would be twenty snapshots.
        seen = live.scan()

        out = []
        for name in sorted(names):
            out.append(self._listed_workspace(
                name, sorted(names[name]), by_path, merged, existing, seen))
        return {"workspaces": out, "gap": store.workspace_fill_gap(self.db)}

    def _listed_workspace(self, name, sources, by_path, merged, existing, seen) -> dict:
        """One workspace's row in the listing: where it is, what state it is in, what is in
        the way of it ever going away."""
        row = store.get_workspace(self.db, name)
        checkout = row["checkout"] if row is not None else None
        if row is None:
            # Not in the table: an agent row's own answer, or — for a checkout nobody was
            # ever recorded in — git's. `_recorded_path` answers None for a bare space,
            # which is the same fact the table's NULL states.
            checkout = self._recorded_path(name) or next(
                (p for p, wt in by_path.items()
                 if (wt["branch"] or Path(p).name) == name), None)
        retired = bool(row is not None and row["retired_at"])
        bare = checkout is None and not retired and (
            row is not None or store.known_workspace(self.db, name))

        if retired:
            verdict = "retired"
        elif bare:
            verdict = "bare"                       # no checkout of its own; nothing to lose
        else:
            verdict = store.checkout_verdict(checkout, cwd=self.repo)

        facts = {
            "name": name, "sources": sources, "checkout": checkout, "verdict": verdict,
            "retired_at": row["retired_at"] if row is not None else None,
            "retiring": row["retiring"] if row is not None else None,
            "retiring_at": row["retiring_at"] if row is not None else None,
            "rows": self._row_counts(name),
            # The branch a safe delete would have to get past. `git branch -d` refuses an
            # unmerged one on its own and that refusal is permanent by design, so it is
            # worth seeing before anyone plans a cleanup around it. A bare workspace has no
            # branch of its own — it is laid over somebody else's checkout — so a branch
            # that happens to share its name is not something it left behind.
            "branch": name if name in existing and not bare else None,
            "unmerged": name in existing and not bare and name not in merged,
            "prunable": bool(checkout and (by_path.get(checkout) or {}).get("prunable")),
            "ignored": None, "live": [], "live_verdict": "skipped",
        }
        if verdict == store.CHECKOUT_OK:
            facts["ignored"] = self._ignored_weight(checkout)
            found = None if seen is None else [
                p for p in seen if live.is_under(p.cwd, checkout)]
            # Unknown is not empty, here as everywhere: a scan that could not be made is
            # not the answer "nobody is in there", and this readout is where that
            # distinction gets exercised before a destructive command depends on it.
            facts["live_verdict"] = ("unknown" if found is None
                                     else "live" if found else "clear")
            facts["live"] = [p._asdict() for p in (found or [])]
        return facts

    def _row_counts(self, name: str) -> dict:
        """How many agent rows this workspace has, and how many of them are not finished."""
        r = self.db.execute(
            f"SELECT COUNT(*) AS n, SUM(state NOT IN {FINISHED}) AS busy "
            "FROM agents WHERE workspace=?", (name,)
        ).fetchone()
        return {"total": r["n"], "unfinished": r["busy"] or 0}

    def _worktrees(self) -> list[dict]:
        """What git says is checked out where. Empty when git will not answer.

        `prunable` is git's own word for a registration whose directory is no longer there
        — the state the already-gone path exists for.
        """
        found: list[dict] = []
        for line in (self._git("worktree", "list", "--porcelain") or "").splitlines():
            if line.startswith("worktree "):
                found.append({"path": line[len("worktree "):], "branch": None,
                              "prunable": False})
            elif not found:
                continue
            elif line.startswith("branch refs/heads/"):
                found[-1]["branch"] = line[len("branch refs/heads/"):]
            elif line.startswith("prunable"):
                found[-1]["prunable"] = True
        return found

    def _branch_facts(self) -> tuple[set, set]:
        """(branches already merged into the base, every local branch).

        The first is what `git branch -d` will agree to delete; the difference between the
        two is what stays forever unless somebody decides otherwise by hand.
        """
        # The remote-tracking base when we have it, the local branch of the same name when
        # we do not — a repo with no `origin` has exactly one `main`, and it is that one.
        base = BASE_BRANCH if self._git("rev-parse", "--verify", "--quiet",
                                        f"{BASE_BRANCH}^{{commit}}", check=True) \
            else BASE_BRANCH.partition("/")[2] or BASE_BRANCH

        def names(*args: str) -> set:
            out = self._git("branch", "--format=%(refname:short)", *args) or ""
            return {ln.strip() for ln in out.splitlines() if ln.strip()}

        return names("--merged", base), names()

    def _ignored_weight(self, path: str) -> dict:
        """What is in this checkout that git does not track and would go with it.

        Plain `git status --porcelain` is the wrong question: it does not list ignored
        files, and a worktree removal deletes them anyway — so a real `.env`, a
        `.claude/settings.local.json`, a local override made in a worktree precisely
        because it was never meant to be committed, are all invisible to the obvious check
        and all destroyed.

        Switchboard's own furniture is told apart from the human's rather than shown
        beside it, and it can be because switchboard planted it: the `LINKED_CONFIG`
        symlinks are ours, unlinking one leaves the target standing in the main checkout,
        and a prompt that lists them every time is a prompt people learn to dismiss.
        """
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain", "--ignored"],
                cwd=path, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            out = None                             # the directory went while we looked
        if out is None or out.returncode != 0:
            # Unknown, and said so rather than counted as nothing: this is one of the two
            # facts a person deciding whether to delete a checkout is deciding on.
            return {"dirty": None, "mine": 0, "unknown": None, "sample": []}
        dirty, mine, unknown = 0, 0, []
        for line in out.stdout.splitlines():
            code, _, entry = line.partition(" ")
            entry = entry.strip().strip('"')
            if code != "!!":
                dirty += 1                         # tracked-dirty or untracked: git sees it
            elif entry.rstrip("/") in LINKED_CONFIG and Path(path, entry).is_symlink():
                mine += 1
            else:
                unknown.append(entry)
        return {"dirty": dirty, "mine": mine, "unknown": len(unknown),
                "sample": unknown[:3]}

    def workspace_close(self, name: str, *, me: Optional[str] = None,
                        resume: bool = False, confirm: bool = False) -> dict:
        """End a workspace's life, and destroy its checkout when it has one.

        The design goal is not "delete the workspace once the records say it is empty" but
        "make sure a person has seen everything that is about to stop existing", and how
        much guarding that takes depends entirely on how much there is to lose. Three
        routes, chosen by what the recorded path resolves to rather than by a flag:

        - **bare** (`_close_bare`) — no checkout of its own, so nothing to destroy;
        - **already gone** (`_close_gone`) — the checkout is not there any more, so nothing
          there can be lost;
        - **a checkout that is still there** (`_close_checkout`) — the destructive one,
          and the only one that carries the gate, the inventory and the ordering.

        The first two are separate paths rather than the third with steps skipped, and
        that is not tidiness — see each of them for the bug the shared version had.

        A name with no row but a checkout git knows about is recorded first
        (`_adopt_orphan`) and then takes whichever of the three routes its path earns.

        An unresolvable path is a refusal and never a fallback: there is no `or self.repo`
        anywhere in this command, because that fallback aims a removal at the human's own
        clone whenever a path is unrecorded.
        """
        me = me or self.whoami()
        gap = store.workspace_fill_gap(self.db)
        if gap:
            raise ValueError(f"cannot close {name!r}: {gap}")
        row = store.get_workspace(self.db, name)
        if row is None:
            row = self._adopt_orphan(name)
        if row is None:
            raise ValueError(
                f"no workspace called {name!r} is recorded, so there is nothing here to "
                f"close — `sb workspace list` shows every one this repo knows about"
            )
        if row["retired_at"] and not row["checkout"]:
            return self._closed(name, None, already=True, kind="retired",
                                worktree="gone")
        if row["retiring"]:
            self._take_over(name, row, me=me, resume=resume)

        checkout = row["checkout"]
        if checkout is None:
            return self._close_bare(name, me=me)
        verdict = store.checkout_verdict(checkout, cwd=self.repo)
        if verdict == store.CHECKOUT_ABSENT:
            return self._close_gone(name, checkout, me=me)
        if verdict != store.CHECKOUT_OK:
            raise ValueError(
                f"cannot tell what {name!r}'s recorded checkout is: {checkout} is not a "
                f"worktree of this repo. Unknown is not empty, so nothing is deregistered "
                f"and nothing is deleted."
            )
        return self._close_checkout(name, checkout, me=me, confirm=confirm)

    def _adopt_orphan(self, name: str):
        """Record a checkout only git knows about, so it can be closed like any other.

        The `workspaces` table is backfilled from `agents` alone, so a registered checkout
        that never had an agent row in it never gets a row — and that is precisely the
        case `sb workspace list`'s three-source union was built to surface. Listed and
        unclosable is half a feature: the orphan and the already-gone are the cheapest
        real wins in this whole change, and they are cheap because there is nothing in
        them to lose.

        Nothing is trusted that was not checked. Recording the path only gets the name as
        far as the front door; the route is still chosen by re-validating that path, and
        the gate, the inventory and the confirmation all run exactly as they would for a
        workspace that had a row all along — including the primary-checkout refusal, which
        is how `sb workspace close main` typed in the clone still gets nowhere.

        Matched by the same rule the listing files it under: a worktree's workspace name IS
        its branch name, and a detached one has only its directory to be known by.
        """
        found = next((wt for wt in self._worktrees()
                      if (wt["branch"] or Path(wt["path"]).name) == name), None)
        if found is None:
            return None
        store.record_workspace(self.db, name, found["path"])
        store.log_event(self.db, kind="workspace_adopted", workspace=name,
                        checkout=found["path"])
        return store.get_workspace(self.db, name)

    # -- the three routes -------------------------------------------------------------

    def _close_bare(self, name: str, *, me: str) -> dict:
        """Retire a workspace with no checkout of its own: its own rows, its own panes.

        A separate path, and sharing the general one's gate was a real bug rather than an
        untidiness. That gate is scoped to a checkout path, and a bare workspace's path is
        the primary clone — where the human sits, where every other bare orchestrator
        sits, and where the agent running the command usually sits. Shared, it would
        refuse `main-2` because `main-3` is live in a directory nobody is deleting, and
        refuse forever: there is essentially always another orchestrator, namely the one
        that typed the command. A guard protecting a directory from deletion, applied to
        an operation that deletes nothing, refuses the only operation available.

        So the gate here is the one the first draft had, scoped to the case it was right
        for: this workspace's own agent rows, finished. Nothing else. No path gate, no
        live observation, no ignored-content inventory, no confirmation, and no git at
        all — run in the primary checkout that inventory would print the human's own
        `.claude/` as material about to be destroyed, for an operation that could not
        destroy it if it tried.

        Retiring is the entire operation, and it is still worth having: "this orchestrator
        is finished" is a fact worth recording whether or not a directory goes with it.
        """
        busy = [r["name"] for r in self._unfinished_in(name, exclude=me)]
        if busy:
            raise ValueError(
                f"cannot close {name!r}: {_names(busy)} still working in it — close "
                f"{'it' if len(busy) == 1 else 'them'} first (`sb cleanup <name>`)"
            )
        self._claim(name, me)
        try:
            closed = self._stop_panes(name, me=me)
        except BaseException:
            store.release_retiring(self.db, name, me)
            raise
        store.retire_workspace(self.db, name)
        store.log_event(self.db, kind="workspace_retired", workspace=name, bare=True,
                        closed=",".join(closed) or None)
        return self._closed(name, None, kind="bare", worktree="none", closed=closed)

    def _close_gone(self, name: str, checkout: str, *, me: str) -> dict:
        """Close a workspace whose checkout is already gone: deregister it, drop its branch.

        The cheapest real win available, and the safest case rather than an unknown one:
        nothing is at that path, so nothing there can be lost. That is what the second of
        `checkout_verdict`'s three answers is for — *absent* is a resolved answer, and this
        is the path it resolves to. A boolean "is the recorded path still good" would have
        made this refuse on precisely the workspaces it was written for.

        It needs none of the machinery a live checkout needs: no cleanliness check, no
        inventory of what would be destroyed, no confirmation, and no live observation
        either — a directory that is not there has nothing in it. It keeps the two rules
        that do apply. The gate is that no unfinished agent row sits under the path —
        compared component-wise, never as a string prefix, because sibling checkout names
        nest as strings here. And the deregistration NAMES the one path: `git worktree
        prune` is repo-global, and one bare prune deregisters every prunable checkout in
        the repository, including ones other agents are relying on.
        """
        self._records_gate(name, checkout, me=me)
        # Before the deregistration, because git's registry is one of the two things that
        # can name the branch and the deregistration takes the entry out of it.
        branch = self._branch_for(name, checkout)
        self._claim(name, me)
        try:
            removed = self._deregister(checkout)
        except BaseException:
            store.release_retiring(self.db, name, me)
            raise
        return self._finish(name, checkout, removed, kind="gone", branch=branch)

    def _close_checkout(self, name: str, checkout: str, *, me: str,
                        confirm: bool) -> dict:
        """The destructive one: check, then stop, then re-confirm, then delete.

        The ordering is a rule, not an implementation detail. An earlier design read
        "stop, then check", and that closed the workspace's panes BEFORE evaluating the
        gate — so a refusal left the panes closed, the command reporting failure and
        nothing retired: the person loses their panes and gets nothing for them. The gate
        is cheap and read-only, so it goes first and a refusal costs only the message.

        The second evaluation is what actually authorises the destruction. It catches
        whatever arrived while the panes were coming down, and deleting a directory around
        a process still running in it is not an exotic state here. The first evaluation
        does not make it redundant; it makes the cheap answer available before anything
        irreversible has happened.

        The retiring mark is claimed before any of the destruction and released by any
        failure after it, because a mark left behind locks a live workspace's name out of
        itself over a command that did nothing. `except BaseException` and not
        `except ValueError`: a review left a permanent mark through this window three
        ways, none of them a refusal — Ctrl-C while the panes come down, a
        `subprocess.TimeoutExpired` out of `_deregister`, and a `RuntimeError` out of
        `Path.resolve` on a symlink loop. "Only our own refusals release it" was a rule
        about the shape of the exception, and the mark does not care what shape the
        failure had. The release is still owner-conditional and still only clears; it
        never restores an earlier value, so a loser cannot take a winner's mark off it.
        """
        primary = self._primary_checkout()
        if primary is None:
            raise ValueError(
                f"cannot close {name!r}: git would not say where this repository's own "
                f"checkout is, and the one directory this must never be aimed at is that "
                f"one — nothing is deleted"
            )
        if _same_dir(checkout, primary):
            raise ValueError(
                f"cannot close {name!r}: its recorded checkout {checkout} IS this "
                f"repository's primary working tree, which this command never removes. A "
                f"record can legitimately point there — `sb workspace new` typed in the "
                f"main clone records exactly that — so this is a rule of the gate rather "
                f"than something git is left to catch after the panes are closed."
            )
        self._gate(name, checkout, me=me)
        self._inventory_gate(name, checkout, confirm=confirm)
        # Before the deregistration, because git's registry is one of the two things that
        # can name the branch and the deregistration takes the entry out of it.
        branch = self._branch_for(name, checkout)
        self._claim(name, me)
        try:
            closed = self._stop_panes(name, me=me)
            # What authorises the deletion: the panes are down, so this is the answer for
            # the directory as it is about to be destroyed rather than as it was. The
            # settle is the one difference from the first evaluation, and it buys the
            # panes we just closed a bounded moment to actually leave — see `_gate`.
            self._gate(name, checkout, me=me, settle=TEARDOWN_SETTLE)
            removed = self._deregister(checkout)
        except BaseException:
            store.release_retiring(self.db, name, me)
            raise
        return self._finish(name, checkout, removed, kind="worktree", branch=branch,
                            closed=closed)

    def _branch_for(self, name: str, checkout: str) -> Optional[str]:
        """The branch this workspace's checkout is on, or None when nothing names one.

        Asked BEFORE the destruction, by both routes that delete, because git's registry
        is one of the two things that can answer and `_deregister` is about to take the
        entry out of it. Matched by `_resolved`, the same one notion of directory identity
        the deregistration uses — two ways of spelling a path is how the last bug here got
        in.

        What it will not do is fall back to the workspace's own NAME. That fallback read
        as harmless because `sb workspace new` makes the two strings equal, but they are
        different facts: a workspace with no row carrying a branch would aim `git branch
        -d` at whatever unrelated branch happened to share its name. `-d` bounds the
        damage to a merged branch and the reflog keeps the tip, so it was small — but it
        was a guess, at the one step in this command where a guess is aimed at something
        that is not the thing being closed.

        None is not a refusal. A refusal here would have to fire before the panes come
        down to be worth anything, and the state it fires in — a workspace whose checkout
        git no longer registers and whose rows never carried a branch — is one where
        retiring destroys nothing and refusing strands the name in a row no verb can ever
        retire. That is the failure this branch spent a commit removing. So: delete the
        branch we can name, delete nothing when we cannot, and say which happened.
        """
        recorded = store.workspace_branch(self.db, name)
        if recorded:
            return recorded
        mine = _resolved(checkout)
        found = None if mine is None else next(
            (wt for wt in self._worktrees() if _resolved(wt["path"]) == mine), None)
        return found["branch"] if found else None

    def _finish(self, name: str, checkout: str, removed: str, *, kind: str,
                branch: Optional[str], closed: Sequence[str] = ()) -> dict:
        """The last two steps, shared by both routes that delete something.

        `git branch -d` and never `-D`: an unmerged branch simply stays, which is a far
        cheaper failure than losing commits — and cheaper still than it sounds, since a
        deleted branch's tip survives in the reflog. Then the retired mark, which clears
        the recorded path with it: the command has just deleted that directory, and a row
        left pointing at it starts every later question from a path we know is gone.

        `branch` arrives established rather than being worked out here — see `_branch_for`
        for why it is looked up before anything is destroyed, and why None means no branch
        is deleted rather than a name being guessed at.
        """
        deleted = bool(branch) and self._git("branch", "-d", branch, check=True)
        store.retire_workspace(self.db, name)
        store.log_event(self.db, kind="workspace_retired", workspace=name,
                        checkout=checkout, branch=branch if deleted else None,
                        worktree=removed, closed=",".join(closed) or None)
        return self._closed(name, checkout, kind=kind, worktree=removed, branch=branch,
                            branch_deleted=deleted, closed=closed)

    @staticmethod
    def _closed(name: str, checkout: Optional[str], *, kind: str, worktree: str,
                already: bool = False, branch: Optional[str] = None,
                branch_deleted: bool = False, closed: Sequence[str] = ()) -> dict:
        """What the caller gets. `kind` is which of the three routes this workspace took."""
        return {"workspace": name, "checkout": checkout, "already": already, "kind": kind,
                "worktree": worktree, "branch": branch, "branch_deleted": branch_deleted,
                "closed": list(closed)}

    # -- the gate ---------------------------------------------------------------------

    def _gate(self, name: str, checkout: str, *, me: str, settle: float = 0.0) -> None:
        """Is anything still in that directory, or still filed under that name? Asked of
        our records AND of the machine.

        Two halves, because each is blind to what the other sees.

        The records half misses a human with an editor open, who has no `agents` row to be
        finished — and the ignored-content inventory and this observation are the two
        places where a person who never appears in the store gets to say no.

        That half is asked twice, of two different sets of rows, because this command acts
        on two different scopes and every step has to be authorised by a check with the
        same reach as the step: the deletion is scoped to the directory and `_records_gate`
        covers it, the pane-closing is scoped to the name and `_filed_gate` covers that.

        The live half is the only signal that can be right about a herdr that has
        RESTARTED. `agent list` has no failure branch at all, so a restarted herdr answers
        *successfully* with a smaller world: every row in the workspace reads `failed`,
        which is finished, and nothing was ever "unknown". An empty success there is not
        weak evidence of an empty workspace, it is no evidence either way — which is why a
        scan that cannot be MADE is a refusal rather than a shrug. Unknown is not empty.

        `settle` is for the second evaluation only, and it is a delay rather than an
        exemption. `close_pane` returning is not the pane's shell having left the process
        table, and that shell's cwd is under the checkout — it is nobody's descendant of
        ours, so no exclusion covers it, and the re-confirmation runs AFTER the panes are
        down, which makes a refusal on it the one refusal that costs the person something.
        Measured rather than assumed (`design/close-review.md`, F4):
        an idle shell and a shell with an ordinary child are already gone when the scan
        lands, so the ordinary success path never hit this; a process that catches the
        hangup and takes half a second to wind down is still there at the first look every
        time, and that is the shape of an agent shutting down cleanly.

        What it does NOT do is exclude those pids. A process still in the directory when
        the wait expires is live, whoever started it, and the deletion is refused on it —
        excluding the panes we closed would delete a directory around a process that is
        demonstrably still in it, which is the one thing this whole gate is for.
        """
        self._records_gate(name, checkout, me=me)
        self._filed_gate(name, me=me)
        found = self._live_under(checkout)
        if found and settle:
            deadline = time.monotonic() + settle
            while found and time.monotonic() < deadline:
                time.sleep(TEARDOWN_SETTLE_POLL)
                found = self._live_under(checkout)
        if found is None:
            raise ValueError(
                f"cannot close {name!r}: this machine could not be asked what is running "
                f"in {checkout}, and unknown is not empty — nothing is closed and nothing "
                f"is deleted"
            )
        if found:
            who = ", ".join(sorted({f"{p.command} ({p.pid})" for p in found})[:5])
            raise ValueError(
                f"cannot close {name!r}: {who} {'is' if len(found) == 1 else 'are'} "
                f"still running in {checkout} — close them first, and note that nothing "
                f"here has to be an agent of ours to count"
            )

    def _records_gate(self, name: str, checkout: str, *, me: str) -> None:
        busy = [r["name"] for r in self._unfinished_under(checkout, exclude=me)]
        if busy:
            raise ValueError(
                f"cannot close {name!r}: {_names(busy)} still recorded as working under "
                f"{checkout} — close {'it' if len(busy) == 1 else 'them'} first "
                f"(`sb cleanup <name>`)"
            )

    def _filed_gate(self, name: str, *, me: str) -> None:
        """The rows the STOP step will act on: this workspace's own, by name.

        `_records_gate` is scoped to the checkout because the deletion is, and that is
        right — but `_stop_panes` is scoped to the name, and the two sets are not the same
        set. A row filed under the workspace whose `cwd` is somewhere else is invisible to
        a gate that only looks under the checkout, and `delegate` makes exactly that row:
        a delegate into a named workspace whose recorded path comes back empty is filed
        under the name with its `cwd` in the primary clone. Unchecked, a live agent's pane
        was taken by step 2, no refusal ever saw it, and the row was left reading `working`
        with no pane — drift no sweep reaches, in the destructive window.

        Widened rather than narrowing the stop step, because the alternative leaves that
        agent its pane and still deletes the checkout out from under a row that claims to
        belong to the workspace. This command's posture everywhere else is to refuse and
        say what it found; and the argument that scopes the gate to the path is that one
        `workspace_id` cannot enumerate who is in a directory — a reason for the gate to
        cover MORE than the record's own rows, never less. `_close_bare`, which closes the
        same panes and deletes nothing, has gated on exactly this set all along.
        """
        busy = [r["name"] for r in self._unfinished_in(name, exclude=me)]
        if busy:
            raise ValueError(
                f"cannot close {name!r}: {_names(busy)} still recorded as working in "
                f"{name!r} — close {'it' if len(busy) == 1 else 'them'} first "
                f"(`sb cleanup <name>`), and note that closing this workspace would take "
                f"{'its' if len(busy) == 1 else 'their'} pane wherever "
                f"{'it is' if len(busy) == 1 else 'they are'} working"
            )

    def _inventory_gate(self, name: str, checkout: str, *, confirm: bool) -> None:
        """What is in that directory that git will not miss, and who gets to say goodbye.

        Two tiers, because "refuse if dirty" is a rule nobody keeps in a repo where most
        worktrees are ignored-dirty always. Work git can see — tracked modifications,
        untracked files — is a plain refusal: a person can commit or stash it and ask
        again. Ignored content is classified instead, and it can be because switchboard
        planted its own furniture: unlinking one of its symlinks leaves the target
        standing in the main checkout. Anything else ignored is somebody's belongings, and
        it is shown and confirmed rather than listed every time — a prompt that fires when
        there is nothing to lose is a prompt people learn to answer without reading, which
        spends the one moment of attention this command gets.

        The confirmation echoes what the command line does not already contain. Typing the
        branch name back would not: workspace name IS branch name here, so that asks the
        human to retype the string they typed one argument earlier.
        """
        weight = self._ignored_weight(checkout)
        if weight["dirty"] is None:
            raise ValueError(
                f"cannot close {name!r}: git would not say what is in {checkout}, so "
                f"nothing here can be told from anything else — nothing is deleted"
            )
        if weight["dirty"]:
            raise ValueError(
                f"cannot close {name!r}: {weight['dirty']} file(s) in {checkout} are "
                f"modified or untracked. That is work git can see, so commit or stash it "
                f"and ask again."
            )
        if weight["unknown"] and not confirm:
            more = "" if weight["unknown"] <= len(weight["sample"]) else ", ..."
            raise ValueError(
                f"{checkout} holds {weight['unknown']} ignored file(s) that git will not "
                f"miss and the removal WILL delete: {', '.join(weight['sample'])}{more}. "
                f"Nothing has been touched. `sb workspace close {name} --yes` deletes "
                f"them with the checkout."
            )

    def _unfinished_under(self, path: str, *, exclude: Optional[str] = None) -> list:
        """Agent rows that are not finished and whose cwd sits under `path`.

        Whatever their `workspace_id` — the column is not consulted, because two workspace
        ids can sit over one checkout and enumerating one of them says nothing about who
        else is in the directory.

        `exclude` is the caller's own row, and leaving it in would refuse the most obvious
        way anyone invokes this: an agent told to close the workspace it works in is
        recorded under that checkout and is not finished, because it is running this
        command. Nothing else is excluded.
        """
        return [r for r in self.db.execute(
            f"SELECT * FROM agents WHERE cwd IS NOT NULL AND state NOT IN {FINISHED}"
        ).fetchall() if r["name"] != exclude and live.is_under(r["cwd"], path)]

    def _unfinished_in(self, name: str, *, exclude: Optional[str] = None) -> list:
        """This workspace's OWN rows, by name: the bare path's whole gate, and the half of
        the general one that covers the panes.

        Deliberately not `_unfinished_under` — see `_close_bare` for why a bare workspace
        must never be gated on the directory it was laid over, and `_filed_gate` for why
        the general path needs both and not either.
        """
        return [r for r in self.db.execute(
            f"SELECT * FROM agents WHERE workspace=? AND state NOT IN {FINISHED}",
            (name,),
        ).fetchall() if r["name"] != exclude]

    def _live_under(self, checkout: str) -> Optional[list]:
        """What is running in that directory that is not us. **None** is "could not tell".

        The caller is excluded and has to be: an agent told to close the workspace it
        works in runs the command from a shell whose cwd is under the checkout, so both
        halves of the gate would otherwise see it and refuse.

        Exclusion is by pid on the parsed output rather than by narrowing the scan — a
        `-p` list that matches nothing exits 1 with empty output, which is
        indistinguishable from a real failure, and this is the one gate that must not have
        an ambiguous shape in it (see `live.CWD_SCAN`).

        "Us" is this process, everything above it and everything below it, and the process
        table is read AFTER the scan for the sake of the last of those: `lsof` is our own
        child and reports ITSELF, sitting in our cwd, so a caller standing in the checkout
        would find one live process every time and refuse forever. A pid the process table
        no longer knows has exited, and a process that has exited is not in the directory.
        """
        found = live.processes_in(checkout)
        if not found:
            return found                       # None, or an empty answer nobody is in
        mine = os.getpid()
        parents = self._parents()
        if parents is None:
            # `ps` would not answer, so the only pids we can prove are ours are the two
            # the kernel hands us directly. Costs a refusal, which is the safe direction.
            return [p for p in found if p.pid not in (mine, os.getppid())]
        ours = _ancestry(mine, parents)
        return [p for p in found if p.pid in parents and p.pid not in ours
                and mine not in _ancestry(p.pid, parents)]

    def _parents(self) -> Optional[dict]:
        """Every process on this machine and its parent, or None if `ps` would not say.

        Strict about the shape for the same reason `live._parse` is: this is half of how
        the caller's own tree stops counting against the gate, and a line it did not
        understand is not a line to skip.
        """
        try:
            out = subprocess.run(["ps", "-Ao", "pid=,ppid="], capture_output=True,
                                 text=True, timeout=SUBPROCESS_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        found = {}
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) != 2:
                return None
            try:
                found[int(parts[0])] = int(parts[1])
            except ValueError:
                return None
        return found or None

    def _primary_checkout(self) -> Optional[str]:
        """This repository's own working tree — the first entry `git worktree list` gives.

        The one directory this command may never be aimed at, and refusing it is a rule of
        the gate rather than something git happens to catch at the end. A record can point
        here without any fallback being involved: `git worktree list` reports the primary
        checkout alongside the linked ones, which is what makes `sb workspace new main`
        attach to the repo you are standing in, and those rows re-validate as a perfectly
        good worktree of this repo. Git does refuse the removal — at the very last step,
        by which time the inventory has listed the human's own `.env` as material about to
        be destroyed and the workspace's panes are closed.
        """
        found = self._worktrees()
        return found[0]["path"] if found else None

    # -- the retiring mark ------------------------------------------------------------

    def _claim(self, name: str, me: str) -> None:
        """Take the retiring mark, or refuse and say who has it.

        Claimed before any destructive step so a command that dies midway is resumable,
        and claimed by conditional write so two invocations arriving together resolve —
        `claim_retiring`'s `rowcount` is the arbiter, and there is no separate read to
        race against.
        """
        if store.claim_retiring(self.db, name, me):
            return
        held = store.get_workspace(self.db, name)
        if held is None or not held["retiring"]:
            raise ValueError(
                f"{name!r} changed underneath this command before it could claim it — "
                f"nothing was closed and nothing was deleted. Look again with "
                f"`sb workspace list`."
            )
        raise ValueError(
            self._retiring_refusal(name, held, self._owner_gone(held["retiring"])))

    def _refuse_retiring(self, name: Optional[str]) -> None:
        """Nobody walks into a workspace that is being taken apart. -> or raises.

        The whole reason the mark is committed before the first destructive step is that
        this refusal can exist: it is the exclusion `sb workspace close` is built out of,
        and without it the mark is written, read only by the command that wrote it, and
        keeps nobody out. It is still not a lock and there is no lock verb —
        `workspace_new` keeps its non-exclusive posture everywhere else, and this reads
        one column the record carries anyway.

        Refused whether or not the mark's owner is still alive, and that is where this
        parts company with `sb workspace close`. A dead owner means a teardown died
        partway through, which makes the checkout a half-taken-apart one rather than a
        free one; the way back is `--resume` on the command that set the mark, which
        discloses the dead owner and runs the whole teardown again from the start.
        Joining the name is not an escape hatch, it is a way to be standing in the
        wreckage when somebody resumes.

        The refusal says what it found, because a bare one leaves the person unable to
        tell whether to wait, to retry, or to go and look.
        """
        row = store.get_workspace(self.db, name) if name else None
        if row is None or not row["retiring"]:
            return
        who, when = row["retiring"], row["retiring_at"]
        held = f" by {who}" if who else ""
        since = f", claimed {fmt_age(store.now() - when)} ago" if when else ""
        raise ValueError(
            f"workspace {name!r} is being taken apart{held}{since} — nothing joins a "
            f"workspace mid-teardown, because its checkout may be gone by the time you "
            f"get there. `sb workspace close {name}` says where that teardown stands, "
            f"and is the only thing that ends one whose owner died holding it."
        )

    def _take_over(self, name: str, row, *, me: str, resume: bool) -> None:
        """What to do about a retiring mark that is already set. Refuse, or take it over.

        A mark is never stolen and never expires. Only a crash may leave one behind, and
        the way back from a crash is a person: the refusal says who holds the mark and
        when they claimed it, and it offers `--resume` unless the owner is confirmed
        LIVE. That flag repairs nothing — it re-runs the whole command from the beginning,
        because a crashed invocation's own findings are exactly what nobody should
        inherit.

        Not confirmed live, rather than confirmed gone, and the difference is the whole
        bug: an owner nobody can adjudicate is the ordinary case, not the exotic one. A
        human holds no `agents` row, so `_owner_gone` can only ever answer None for one —
        and a human is the likeliest caller of a destructive command. Under
        "unknown reads as live" a mark a human left behind was reachable by no flag, no
        caller and no amount of waiting, with `workspace_new`, `start --name` and
        `--workspace` all refusing the name as well: a review reproduced that permanent
        brick. What must never happen is a live mark being taken AUTOMATICALLY, and
        `--resume` is the opposite of automatic — it is a person who can see the machine
        saying they know what they are doing. So an unadjudicable owner offers the flag
        and a live one still refuses it.

        Without a way back the three rules that are each right on their own — only a crash
        leaves a mark, `close` refuses a marked workspace, only the owner may clear one —
        compose into a name no verb can ever reach again.
        """
        gone = self._owner_gone(row["retiring"])
        if resume and gone is not False:
            store.release_retiring(self.db, name, row["retiring"])
            store.log_event(self.db, kind="workspace_resumed", workspace=name, agent=me,
                            previous=row["retiring"])
            return
        raise ValueError(self._retiring_refusal(name, row, gone, resume=resume))

    def _retiring_refusal(self, name: str, held, gone: Optional[bool], *,
                          resume: bool = False) -> str:
        """The refusal, which says what it found rather than only that it found something.

        Always the owner and always when they claimed it: whether to wait, to retry or to
        go and look is the reader's decision and those are what it turns on. What differs
        is the third fact and what follows from it — a live owner is the one case with no
        way round it, and both a dead owner and an owner nobody can adjudicate name
        `--resume`, worded so the reader knows which of the two they are being told.
        """
        who, when = held["retiring"], held["retiring_at"]
        since = f"{fmt_age(store.now() - when)} ago" if when else "at some point"
        if gone is False:
            flag = (" `--resume` takes a mark over from an owner who is not confirmed "
                    "live, and never from one who is." if resume else "")
            return (f"{name!r} is already being closed by {who}, claimed {since}, and "
                    f"{who} is still going — one teardown at a time.{flag}")
        state = (f"{who} is confirmed gone — that teardown died partway through" if gone
                 else f"whether {who} is still going cannot be confirmed either way — a "
                      f"human holds no row to be asked about, so a mark a person left "
                      f"behind always lands here")
        return (f"{name!r} is marked as being closed by {who}, claimed {since}, and "
                f"{state}. `sb workspace close {name} --resume` takes the mark over and "
                f"runs the whole command again from the start.")

    def _owner_gone(self, owner: str) -> Optional[bool]:
        """Is the agent holding a retiring mark confirmed gone? **None** is "cannot tell".

        Asked of the trust layer rather than re-derived here: "is this agent really
        finished" is the question that layer exists to make trustworthy, and this is the
        first place the destructive command spends it. A `failed` row is not one absent
        reading any more — it is an absence that lasted — and a `done` row is the agent's
        own word for its end.

        Herdr still gets a veto in the one direction it can be trusted in: a name it lists
        right now is running, whatever our row says. It gets no vote the other way, and a
        herdr that cannot be asked leaves the answer unknown — which is a real third
        answer here rather than a quieter "still going". Only `False`, an owner positively
        confirmed live, closes off `--resume`; see `_take_over` for why treating unknown
        as live bricked the name instead.
        """
        if owner == HUMAN:
            return None                        # a person has no row and no verdict here
        row = store.get_agent(self.db, owner)
        if row is None or row["state"] not in FINISHED:
            return False if row is not None else None
        known = self._agent_states()           # None is "cannot tell", as ever
        return None if known is None else owner not in known

    def _stop_panes(self, name: str, *, me: str) -> list[str]:
        """Close the panes of this workspace's agents, and confirm they are stopped.

        Step 2, and the reason step 3 exists: closing the panes is what the re-confirmation
        is checking the effect of. Every row here is finished — `_filed_gate` is scoped to
        exactly this set of rows and said so, and `_close_bare` asks the same thing of the
        same set before it closes the same panes — so this
        takes away a pane nobody is working in, which costs only the pane: session,
        summary, messages and transcript all survive, and `sb restore` brings the agent
        back.

        A pane herdr no longer has is this close having HAPPENED, not having failed. A
        pane herdr will not close is neither, and it is a refusal: an unconfirmed pane in
        a directory about to be deleted is the whole reason "confirm them stopped" is a
        step rather than a hope. The caller's own pane is never closed, here as in
        `cleanup`.
        """
        closed = []
        for a in self.db.execute(
            "SELECT * FROM agents WHERE workspace=? AND pane_id IS NOT NULL", (name,)
        ).fetchall():
            if a["name"] == me:
                continue
            try:
                self.h.release_agent(a["pane_id"], a["name"],
                                     store.next_seq(self.db, a["name"]))
                self.h.close_pane(a["pane_id"])
            except HerdrError as e:
                if e.code != "pane_not_found":
                    store.log_event(self.db, kind="cleanup_failed", agent=a["name"],
                                    error=str(e))
                    raise ValueError(
                        f"cannot close {name!r}: {a['name']}'s pane would not close "
                        f"({e}), so nothing here is confirmed stopped — nothing is "
                        f"deleted"
                    ) from None
                store.log_event(self.db, kind="cleanup_pane_gone", agent=a["name"])
            self._close_board(a["name"])
            # The pane is gone, so the row must stop claiming one — a stale id has every
            # later sweep retrying release/close against a pane that is not there.
            store.update_agent(self.db, a["name"], pane_id=None)
            store.log_event(self.db, kind="cleanup", agent=a["name"], forced=False)
            closed.append(a["name"])
        return closed

    def _deregister(self, checkout: str) -> str:
        """Take one gone checkout out of git's registry, by name. Never a bare prune.

        Already absent from the registry is success, not an error: a command that died
        halfway through must be resumable, and a directory that is already gone is a
        resumable state.

        The registry is matched by `_resolved`, never by string equality, and git is then
        handed back its OWN string for the entry rather than the recorded path. A recorded
        path that resolves to a registered worktree without being git's spelling of it
        used to match nothing here, which read as "already deregistered" — success — for a
        checkout still on disk and still registered. A path that will not resolve at all
        matches nothing rather than everything: the first entry `git worktree list` gives
        is the primary checkout.

        The removal is the one subprocess in this command that used to run with no `try`
        of its own, and it is the worst place for that: it runs inside the destructive
        window, so a git that would not start or would not finish came out as an `OSError`
        or a `TimeoutExpired` rather than as a refusal — a traceback where the command's
        whole voice is "cannot tell, so nothing is deleted". Nothing is deleted either
        way; what changes is whether the person is told why.
        """
        mine = _resolved(checkout)
        found = None if mine is None else next(
            (wt for wt in self._worktrees() if _resolved(wt["path"]) == mine), None)
        if found is None:
            return "unregistered"
        try:
            out = subprocess.run(
                ["git", "worktree", "remove", found["path"]],
                cwd=str(self.repo), capture_output=True, text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise ValueError(
                f"git would not deregister {checkout}: {e} — the checkout is still there "
                f"and still registered, and nothing else has been deleted"
            ) from None
        if out.returncode != 0:
            raise ValueError(
                f"git would not deregister {checkout}: {(out.stderr or '').strip()}"
            )
        return "removed"

    @staticmethod
    def _result(ws: dict, lead: str, *, created: bool) -> dict:
        """What the caller gets. `created` is the only signal of newness — `fresh` stays
        internal, because two near-synonyms in one payload is how a caller picks wrong."""
        return {"workspace": ws["workspace"], "branch": ws.get("branch"),
                "workspace_id": ws["workspace_id"],
                "path": ws["path"], "pane_id": ws["pane_id"],
                # What this worktree was actually forked from, and why that is not what
                # was asked for when it is not. A stale fork is invisible otherwise: the
                # branch is there, the checkout works, and the commits it is missing only
                # surface as a conflict much later.
                "base": ws.get("base"), "base_fallback": ws.get("base_fallback"),
                "agent": lead, "created": created}

    def _attach_workspace(self, name: str, *, base: str = BASE_BRANCH,
                          create: bool = True) -> dict:
        """Resolve `name` to one herdr workspace over one git worktree.

        Open-or-create, and create-or-open, depending on whether the branch is already
        checked out somewhere — the two orders differ only in which call is expected to
        succeed first, never in the outcome. Whichever wins, both callers of a concurrent
        race end up holding the same workspace id, because the loser's failure is exactly
        "it already exists".

        `create=False` is for callers that only want to LOOK a workspace up. Creating is a
        side effect nobody asks for by accident: `worktree create --branch <name>` forks a
        git branch and a checkout, so a lookup that falls through to it turns a question
        into a commitment (see `_workspace_id`).
        """
        branch = name
        known = self._recorded_path(name) or self._checkout_of(branch)
        steps = ("open", "create") if known else ("create", "open")
        if not create:
            steps = ("open",)

        first: Optional[HerdrError] = None
        for step in steps:
            try:
                if step == "create":
                    # Fetched HERE rather than once at startup: this is the moment the
                    # base is read, and a fork from a base fetched ten minutes ago is a
                    # fork from a stale base.
                    forked_from, fallback = self._fork_base(base)
                    # --cwd names WHICH REPO. Without it herdr uses the focused
                    # workspace's repo, so a worktree asked for from a pane sitting in
                    # another project silently targets that one.
                    r = self._call_adapter("create_worktree", branch, base=forked_from,
                                           cwd=str(self.repo))
                else:
                    r = self._open_worktree(name, path=known, branch=branch)
                    forked_from, fallback = None, None
                facts = self._workspace_facts(name, r or {}, fresh=(step == "create"))
                facts["base"], facts["base_fallback"] = forked_from, fallback
                self._ws_ids[name] = facts["workspace_id"]
                # Every attach, not only the first: this is the one place that knows where
                # the checkout actually is, and a record that is only written at creation
                # is a memory rather than a fact. It is also what reopens a name somebody
                # retired — the attach is what makes it live again.
                self._record_workspace(name, facts["path"] or None)
                return facts
            except HerdrError as e:
                first = first or e
        raise HerdrError(
            "workspace_unavailable",
            f"could not open or create workspace {name!r} (branch {branch}): {first}",
        )

    def _fork_base(self, base: str) -> tuple[str, Optional[str]]:
        """Bring `base` up to date, and say what we ended up forking from.

        The base is a REMOTE-tracking ref (`origin/main`), because the local branch of the
        same name is however stale the human's last pull left it. Fetching it on the spot
        is the difference between a fork that starts at today's main and one that starts
        wherever this checkout happened to be.

        Nothing here is fatal, and that is deliberate: a spawn that dies because a laptop
        is on a train is a worse failure than a fork from a base an hour old. Two
        fallbacks, in order of how much they cost:

          - the fetch failed, but we still have `origin/main` locally: fork from that,
            just older than it could have been;
          - no remote at all, or nothing under that remote to fork from: fork from the
            LOCAL branch (`main`), which in a repo with no remote is the only real one.

        Returns `(what to fork from, what went wrong)` — the second is None on the happy
        path, and is carried into the event log and the workspace result so a stale fork
        is something the caller can see rather than something they discover in a merge.
        """
        remote, _, ref = base.partition("/")
        if not ref:
            return base, None                    # a plain local branch: nothing to fetch
        if remote not in self._remotes():
            # Not an error and not worth a warning: a repo with no `origin` has exactly
            # one `main`, and it is the local one.
            return ref, "no_remote"

        why = None
        if not self._git("fetch", remote, ref, check=True):
            why = "fetch_failed"
            store.log_event(self.db, kind="fetch_failed", base=base,
                            note="forking from the local copy instead")
        if self._git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=True):
            return base, why
        # The fetch failed AND we have never had this ref. Nothing remote to fork from.
        store.log_event(self.db, kind="base_fallback", base=base, fallback=ref)
        return ref, "no_remote_base"

    def _remotes(self) -> set[str]:
        out = self._git("remote")
        return {ln.strip() for ln in (out or "").splitlines() if ln.strip()}

    def _git(self, *args: str, check: bool = False):
        """Run git in this repo. Returns its stdout, or "" — never raises.

        `check=True` asks the yes/no form instead: whether it succeeded. Every caller here
        is asking git a question it may legitimately have no answer to (no remote, no such
        ref, not a repo at all), and a timeout because the network hung is one of those
        answers too.
        """
        try:
            out = subprocess.run(
                ["git", *args], cwd=str(self.repo), capture_output=True, text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            return False if check else ""
        if check:
            return out.returncode == 0
        return out.stdout if out.returncode == 0 else ""

    def _open_worktree(self, name: str, *, path: Optional[str], branch: str) -> dict:
        """Attach to a checkout that already exists.

        By path when we know it — that is the only way to reach the repo's *primary*
        checkout, which git will never let a second worktree hold. `label` is what herdr
        shows, so it carries our workspace name rather than whatever the directory is
        called.
        """
        # --cwd is REQUIRED, not optional: herdr resolves --path relative to the repo it
        # names, and without it uses the focused workspace's repo — so any path, primary
        # or linked, comes back "worktree path not found".
        # Label only what we actually opened. herdr RENAMES an already-open workspace to
        # whatever label you pass, so labelling unconditionally clobbers the name the user
        # gave their own workspace — observed: opening `main` renamed "switchboard" to
        # "main". `already_open` tells us which case we are in.
        if path:
            r = self._call_adapter("open_worktree", path=path, cwd=str(self.repo))
        else:
            r = self._call_adapter("open_worktree", branch=branch, cwd=str(self.repo))
        if r and not r.get("already_open"):
            wsid = (r.get("workspace") or {}).get("workspace_id") or r.get("workspace_id")
            if wsid:
                try:
                    self._call_adapter("rename_workspace", wsid, name)
                except HerdrError as e:
                    store.log_event(self.db, kind="label_failed", workspace=name, error=str(e))
        return r

    def _call_adapter(self, method: str, *args, **kw):
        """Call an M2 method, reporting its absence as a herdr error rather than an
        AttributeError — so a caller that can degrade (see `_top`) gets the chance to."""
        fn = getattr(self.h, method, None)
        if fn is None:
            raise HerdrError(f"no_{method}",
                             f"the herdr adapter has no {method}(); see `herdr worktree`")
        return fn(*args, **kw)

    @staticmethod
    def _workspace_facts(name: str, r: dict, *, fresh: bool) -> dict:
        """Flatten herdr's `{workspace, tab, root_pane, worktree}` into what we need.

        Only `workspace_id` is load-bearing: it is how a child's tab is placed *in* this
        workspace rather than in whichever one the human happens to be looking at.

        The response carries TWO worktree objects under different key names, and they are
        not interchangeable: top-level `worktree` is a `WorktreeInfo`, whose path key is
        `path`; `workspace.worktree` is a `WorkspaceWorktreeInfo`, whose path key is
        `checkout_path`. Read the workspace-scoped one first — it is the checkout this
        workspace actually sits in — and accept either key, because the top-level object is
        always present and would otherwise win an `or` chain while carrying no
        `checkout_path` at all, yielding "".
        """
        ws = r.get("workspace") or {}
        wt = ws.get("worktree") or r.get("worktree") or {}
        path = wt.get("checkout_path") or wt.get("path") or ""
        if not path:
            # An empty path is worse than an error: it silently degrades to the main
            # checkout everywhere downstream — `link_config` symlinks the wrong tree, the
            # lead is *told* it works in the main checkout, and the bad path is recorded,
            # so the next open attaches the workspace to the primary checkout for good.
            raise HerdrError(
                "workspace_no_path",
                f"herdr returned no worktree path for workspace {name!r}; "
                f"got worktree keys {sorted(wt)!r}",
            )
        return {
            "workspace": name,
            # This IS a worktree space, and `branch` is what says so downstream — the name
            # alone cannot, because a bare space has one of those too. herdr's own answer
            # first; the name is what we asked for and what a fork uses verbatim.
            "branch": wt.get("branch") or name,
            "workspace_id": ws.get("workspace_id", ""),
            "path": path,
            "pane_id": (r.get("root_pane") or {}).get("pane_id", ""),
            "fresh": fresh,
        }

    def _spawn_lead(self, lead: str, ws: dict, *, role: str, task: Optional[str],
                    me: str, prior, board: bool = True) -> bool:
        """Put a lead agent in the workspace. Returns whether we actually made one.

        Three shapes of `prior`, and they mean different things:

          session id      an agent that ran and was closed — restore it, context and all;
          pane, no session  a claim another opener made moments ago and is still spawning
                          into — join it, because same name means the same lead;
          neither         a husk from a run that died before it spawned — replace it.
        """
        if prior is not None and prior["session_id"]:
            self.restore(lead, workspace=ws)          # brings its context back with it
            if task:
                self.tell([lead], task, me=me)
            return False
        if prior is not None and prior["pane_id"]:
            return self._joined_lead(lead, ws, task=task, me=me)
        if prior is not None:
            # A row with no pane and no session is a husk; replace it rather than orphan it.
            store.drop_agent(self.db, lead)

        # The freshly-created workspace's root pane is already an idle shell; a
        # re-attached one may not be, so give that case its own tab.
        fresh_root = ws["pane_id"] if ws.get("fresh") and ws["pane_id"] else ""
        pane, wsid = fresh_root, ws["workspace_id"]
        if not pane:
            # `wsid` comes back corrected: if herdr has forgotten this workspace, the tab
            # call says so and the lead is recorded with no id rather than the dead one.
            pane, wsid = self._tab_for(wsid, ws["path"] or self.repo)
        first, awaiting = self._first_task("spawn.workspace_task", task)
        try:
            self.delegate(first, role=role,
                          name=lead, cleanup="keep", me=me,
                          workspace=ws["workspace"], branch=ws.get("branch"),
                          workspace_id=wsid,
                          cwd=ws["path"] or None, pane=pane, board=board,
                          awaiting_task=awaiting)
        except (AgentNameTaken, HerdrError) as e:
            # Two openers, one instant: the other won the name. Same name means the same
            # lead, so join theirs instead of erroring or suffixing — and take the empty
            # tab back out, or a contested workspace slowly fills with dead shells.
            if isinstance(e, HerdrError) and "agent_name_taken" not in str(e):
                raise
            if not fresh_root:
                try:
                    self.h.close_pane(pane)
                except HerdrError as ce:
                    store.log_event(self.db, kind="orphan_pane", agent=lead, error=str(ce))
            return self._joined_lead(lead, ws, task=task, me=me)
        return True

    def _joined_lead(self, lead: str, ws: dict, *, task: Optional[str], me: str) -> bool:
        """We lost the race for this workspace's lead. Hand our work to the winner."""
        if task:
            self.tell([lead], task, me=me)
        store.log_event(self.db, kind="workspace_lead_race", agent=lead,
                        workspace=ws["workspace"])
        return False

    def _adopt(self, name: str, ws: Optional[dict], *, role: str, me: str):
        """Take over an agent herdr is running that our store has no row for.

        This is a *normal* state, not corruption. The store is disposable by construction
        — a schema change drops every row — while herdr's agents keep running in their
        panes. Without this, the next `sb start` tries to spawn a second agent under a
        name herdr still holds and dies on `agent_name_taken`. Same principle as a branch
        that already exists: what is already there is somewhere to go, not an obstacle.

        Races with every other opener of the same workspace, so the write is a claim
        rather than an insert: losing it means somebody else wrote the row we were about
        to write, and re-reading theirs is the whole recovery.
        """
        try:
            live = next((a for a in self.h.list_agents() if a.name == name), None)
        except HerdrError:
            return None
        if live is None:
            return None
        ws = ws or {}
        if store.claim_agent(
            self.db, name=name, role=role, parent=(None if me == HUMAN else me),
            session_id=live.session_id or None,
            cwd=(live.raw.get("cwd") or ws.get("path") or str(self.repo)),
            workspace=ws.get("workspace"), branch=ws.get("branch"),
            terminal_id=live.terminal_id,
            pane_id=live.pane_id, cleanup="keep",
        ):
            store.log_event(self.db, kind="adopt", agent=name,
                            workspace=ws.get("workspace"), pane=live.pane_id)
        return store.get_agent(self.db, name)

    def _alive(self, name: str) -> bool:
        a = store.get_agent(self.db, name)
        if not a or not a["pane_id"]:
            return False
        try:
            return any(x.name == name for x in self.h.list_agents())
        except HerdrError:
            return False

    def _alive_or_unknown(self, name: str) -> bool:
        """`_alive`, except an unreachable herdr answers "still going".

        Asked on one path only: `sb start --name <existing>`, where `_top` found a row
        carrying a session id and is choosing between re-focusing that orchestrator and
        restoring it. A bare `sb start` never arrives here — it always spawns, under a name
        `_next_top_name` proves was never used, so there is no row to ask about.

        On that path the two mistakes cost very different things, so take the reversible
        one, which is what `design-c.md` asks of an unknown. Guessing alive costs an
        `sb start --name` that only re-focuses, and the human types it again. Guessing dead
        means `restore`, which spawns: a live agent's session resumed in a second pane, and
        no command undoes that.

        No pane is not an unknown — that is our own row, not herdr's answer.

        `_alive` itself is deliberately untouched: `restore` and `workspace` pay a
        different price for doubt, and flipping it is its own landing.
        """
        a = store.get_agent(self.db, name)
        if not a or not a["pane_id"]:
            return False
        known = self._agent_states()      # None is "cannot tell", not "nobody is running"
        return known is None or name in known

    def _recorded_path(self, name: str) -> Optional[str]:
        """Where this workspace's CHECKOUT is, according to our own rows.

        The store is the truth (C7): agent rows carry the workspace name and the cwd they
        ran in, so a workspace is still resolvable after a herdr server restart has
        forgotten every live workspace.

        Only rows that have a branch answer. A bare space records a cwd too — the main
        checkout it was laid over — and taking that as "the workspace's checkout" is how a
        bare name came to look like a worktree: the path is real, it just belongs to
        somebody else's tree. No branch, no checkout of its own, no answer.
        """
        row = self.db.execute(
            "SELECT cwd FROM agents WHERE workspace=? AND cwd IS NOT NULL "
            "AND branch IS NOT NULL ORDER BY created_at LIMIT 1", (name,)
        ).fetchone()
        return row["cwd"] if row else None

    def has_worktree(self, agent: str) -> bool:
        """Does this agent work in a checkout of its own?

        The fork rule's question, and the reason `agents.branch` exists. Read from the
        store, never inferred from the workspace name: the human and an agent we have no
        row for both answer False, which forks rather than assuming somebody else's tree.
        """
        return self.worktree_branch(agent) is not None

    def worktree_branch(self, agent: str) -> Optional[str]:
        """The branch of that agent's worktree, or None if it has no worktree."""
        if agent == HUMAN:
            return None
        row = store.get_agent(self.db, agent)
        return (_column(row, "branch") or None) if row is not None else None

    def _checkout_of(self, branch: str) -> Optional[str]:
        """Where this branch is already checked out, if it is.

        `git worktree list` reports the PRIMARY checkout alongside the linked ones, which
        is what makes `sb workspace new main` attach to the repo you are standing in
        rather than fail (git refuses a second checkout of one branch) or fork it.
        """
        out = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo), capture_output=True, text=True,
        )
        if out.returncode != 0:
            return None                       # not a git repo; the herdr calls will say so
        path = None
        for line in out.stdout.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line == f"branch refs/heads/{branch}":
                return path
        return None

    def _workspace_of(self, me: str) -> Optional[str]:
        a = store.get_agent(self.db, me) if me != HUMAN else None
        return a["workspace"] if a else None

    def _workspace_id(self, name: Optional[str]) -> str:
        """herdr's id for a workspace we already know by name.

        Cached per process because each `sb` invocation is a fresh one; a stale id can
        therefore never outlive the call that fetched it. Failure is not fatal — the child
        still spawns, just not inside the workspace — so it is logged, not raised.

        **Looks, never creates.** This used to fall through to a plain
        `_attach_workspace`, whose create step runs `worktree create --branch <name>` — so
        asking for the id of a space that was never a checkout forked a branch for it.
        A bare space now says so in the store, and is answered from there; an unrecorded
        name gets an open-only attach, which fails harmlessly if there is nothing to open.
        """
        if not name:
            return ""
        if name in self._ws_ids:
            return self._ws_ids[name]

        wsid = ""
        if store.known_workspace(self.db, name) \
                and store.workspace_branch(self.db, name) is None:
            # A bare space: there is no worktree to attach to, and asking herdr for one
            # would be asking it to make one.
            store.log_event(self.db, kind="workspace_bare", workspace=name)
        else:
            try:
                wsid = self._attach_workspace(name, create=False)["workspace_id"]
            except HerdrError as e:
                store.log_event(self.db, kind="workspace_resolve_failed",
                                workspace=name, error=str(e))
        self._ws_ids[name] = wsid
        return wsid

    def _parent_workspace_id(self, me: str, ws: Optional[str]) -> tuple[str, bool]:
        """Where a child of `me` belongs: the herdr workspace the PARENT is in.

        An empty id means "wherever herdr is focused", which is whatever the last --focus
        touched — so a child would land in a stranger's workspace. Four answers, in
        descending order of authority:

        1. what we recorded when the parent was spawned;
        2. what herdr says about the parent's live pane;
        3. `HERDR_WORKSPACE_ID`, injected into every pane — for the human that is the
           terminal they typed in, for an agent it is where it is running;
        4. last, and only last, deriving an id from the workspace NAME.

        The first three are statements of fact about where the parent actually is. The
        fourth resolves the name as a git branch/checkout and asks herdr which workspace
        holds it — a one-to-many lookup with nothing to validate the answer, which is how
        a child of `main` (workspace w7, over the main checkout) landed in w1, the OTHER
        workspace over that same checkout. It stays only as a fallback.

        Which is why the answer comes with a second half: whether it is CONFIRMED. The
        first three tiers are statements of fact and are worth recording; tier 4 is a
        guess, good enough to aim a tab at and never good enough to write down as where
        this agent is — recorded, it would be inherited by every later child as though
        somebody had checked.
        """
        row = store.get_agent(self.db, me) if me != HUMAN else None
        if row is not None and _column(row, "workspace_id"):
            return _column(row, "workspace_id"), True

        if me != HUMAN:
            try:
                live = self.h.get_agent(me)
            except (HerdrError, AttributeError):
                live = None
            if live is not None and getattr(live, "workspace_id", ""):
                return live.workspace_id, True

        env = os.environ.get("HERDR_WORKSPACE_ID", "")
        if env:
            return env, True
        return self._workspace_id(ws), False

    def _tab_for(self, workspace_id: str, cwd) -> tuple[str, str]:
        """A child belongs in its parent's workspace, not in whatever tab has focus.

        A RECORDED id, though, outlives the herdr that issued it: ids are handed out per
        herdr run, so a row written before a restart names a workspace that is simply
        gone. That is what killed `sb start` outright — the stored `main` row still said
        `wG`, and `tab create --workspace wG` fails, taking the whole spawn with it.

        Where the tab goes is a preference; that the agent starts is not. A vanished
        workspace therefore degrades to a plain tab rather than an error, and says so in
        the log so the misplacement is explainable.

        Returns the pane AND the id still worth believing — the one it was given, or ""
        once herdr has disowned it. Callers record THAT rather than the value they were
        holding before the call: clearing the id from every row and then letting the
        caller re-plant it on the row it is spawning is how a dead id survived its own
        purge and got inherited all over again.
        """
        if workspace_id and _accepts(self.h.create_tab, "workspace"):
            try:
                return self.h.create_tab(cwd=str(cwd), workspace=workspace_id), workspace_id
            except HerdrError as e:
                if e.code != "workspace_not_found":
                    raise
                # Forget it everywhere, not just here. herdr ids are unique within a run,
                # so an id it disowns is dead for every row holding it — leaving them be
                # would make each later spawn pay the same failed call and go on claiming
                # a placement that has not been true since the restart. Cleared to NULL,
                # they fall through to the live-pane and env tiers, which are facts.
                self.db.execute(
                    "UPDATE agents SET workspace_id=NULL WHERE workspace_id=?",
                    (workspace_id,))
                self.db.commit()
                # And out of this process's own cache, for the same reason: a second
                # lookup of that workspace name would otherwise hand back the id we just
                # watched herdr disown, and pay the failed call again.
                self._ws_ids = {n: i for n, i in self._ws_ids.items() if i != workspace_id}
                store.log_event(self.db, kind="workspace_gone", workspace=workspace_id)
                workspace_id = ""
        return self.h.create_tab(cwd=str(cwd)), workspace_id

    def _pin_sb(self, name: str, pane: str, cwd) -> None:
        """Make `sb` in this pane mean the checkout this agent is standing in.

        THE PROBLEM. `sb` on PATH is one symlink per machine, pointing into the main
        checkout, and `bin/sb` resolves its own real path to decide what to import. So
        every agent in every worktree ran the main checkout's code, whatever branch it had
        checked out — an agent could not exercise its own work, and a branch's fixes were
        acceptance-tested against a build that did not contain them. Measured, not feared:
        a phase of merged fixes was found to be entirely out of force for this reason.

        THE SHAPE OF THE FIX. Nothing is installed and nothing outside this pane moves.
        The pane's shell is handed its own checkout's `bin/` at the front of PATH, once,
        before `agent start` runs the provider CLI in that same shell — so the agent, and
        every shell it spawns, inherits it. C6: the agent is not told to type `./bin/sb`,
        because an agent told that will type `sb`.

        WHY IT IS CONFIRMED. `pane run` is a write into the dark — herdr accepts the text
        whether or not the shell was at a prompt to take it — and the failure it hides is
        exactly the silent one above. So the command prints where `sb` actually resolved
        and the answer is read back; a pane that will not say costs the spawn (`SbUnpinned`)
        rather than producing an agent quietly running the wrong build.

        The marker cannot be matched off the echoed command line: what is typed contains
        the bin directory, and what comes back is `sb=<bin>/sb`, which the typed line does
        not contain.

        WHERE IT SITS. Before the name is claimed, so the seconds it can cost stay out of
        the window `status.SPAWN_GRACE` covers, and a refusal leaves no row behind.

        A checkout with no `bin/sb` — any other project — is left alone entirely: no
        herdr calls, PATH untouched, exactly as before.
        """
        bin_dir = _own_sb_bin(cwd)
        if bin_dir is None:
            return
        quoted = shlex.quote(str(bin_dir))
        # `command -v`, not `which`: it is the shell's own resolution, which is the thing
        # being asserted. `"$PATH"` quoted, so a PATH with a space in it survives.
        command = f'export PATH={quoted}:"$PATH"; echo "sb=$(command -v sb)"'
        marker = f"sb={bin_dir}/sb"
        for attempt in range(PIN_ATTEMPTS):
            try:
                self.h.prompt_pane(pane, command)
                if self.h.wait_output(pane, marker, timeout_ms=PIN_MS):
                    store.log_event(self.db, kind="sb_pinned", agent=name,
                                    pane_id=pane, path=str(bin_dir))
                    return
            except HerdrError as e:
                store.log_event(self.db, kind="sb_pin_error", agent=name,
                                pane_id=pane, error=str(e))
            if attempt + 1 < PIN_ATTEMPTS:
                # The one failure worth retrying is a shell that had not reached its
                # prompt when the text arrived, and waiting is the whole of that fix.
                time.sleep(PIN_BACKOFF)
        store.log_event(self.db, kind="sb_unpinned", agent=name, pane_id=pane,
                        path=str(bin_dir))
        raise SbUnpinned(name, pane, str(bin_dir))

    # -- spawning --------------------------------------------------------

    def _resolve_bindings(self, role: str, extra: Sequence[str] = ()) -> list[str]:
        """The prompt lines this spawn's bindings contribute.

        Named for what it does rather than for what the bound things are currently called:
        the vocabulary above it is being reworked, and a spawn resolving its bindings is
        the part that stays true either way.

        Layered, most general first: repo defaults -> the role's own -> the caller's
        `--with`. Each layer appends (see `presets.for_role`).

        Resolved HERE rather than in the CLI, because `delegate` is the one place every
        spawn passes through. While the CLI's `delegate` branch owned this, `sb workspace
        new` and `sb start` reached `delegate` without it and their leads silently got no
        presets at all — not even the repo's every-agent bindings.

        Validated after resolution because THIS is what becomes an agent argument: a preset
        file is flattened to one line on the way out, but a repo's presets.toml can also
        name a preset that no longer flattens cleanly, and that failure should name the
        preset rather than arrive as invalid_agent_argument.

        `extra` is `explicit`: it is exactly the names a caller handed in by hand, which is
        the property the explicit-vs-bound asymmetry is about (§6). A fragment named there
        that will not load is fatal; the same fragment arriving from a binding is skipped
        with a warning, because a repo's `presets.toml` must not be able to stop every
        spawn. Threaded from `extra` rather than from the CLI's `--with` flag, so the rule
        keeps holding for any other caller that reaches delegation with names of its own.
        """
        names = presets_mod.for_role(self.repo, role, extra)
        return [validate.line(p, "preset text", max_len=validate.MAX_PROMPT)
                for p in presets_mod.resolve(names, self.repo,
                                             explicit=frozenset(extra),
                                             on_event=self._fragment_note())]

    def _fragment_note(self) -> Callable[..., None]:
        """What `presets.resolve` does with a fragment it dropped or cut.

        Everything is logged; only the skip is printed. A skipped fragment means an agent
        was spawned without an instruction somebody's `presets.toml` says it should have
        had, and the one line naming the plugin is the only signal that happened — the
        spawn itself succeeds, which is the whole point of skipping. A truncation is a
        note for whoever edits `agent.md` next, and printing it on every spawn would train
        the reader to ignore both.
        """
        def note(*, kind: str, plugin: str, **payload) -> None:
            store.log_event(self.db, kind=kind, plugin=plugin, **payload)
            if kind == "fragment_skipped":
                print(f"sb: {payload['reason']} — skipped, so this agent is spawning "
                      f"without it", file=sys.stderr)
        return note

    def _fork_for(self, name: str, *, parent: str) -> dict:
        """Give this child a worktree of its own. The branch is the agent's NAME.

        No prefix and no suffix: the name is already unique (`agents.name` is the primary
        key), already legal as a branch, and already short. Anything else would be a
        second identity for the same agent, and two names for one thing is how a workspace
        stops being findable by the one everybody uses.

        An existing branch of that name is REFUSED, not attached to — see `BranchTaken`.

        EVERY other failure refuses the spawn too, and this used to be the opposite: a
        herdr with no `worktree create`, a repo that is not a repo, a disk that is full
        all returned None, and the child spawned in its parent's space with only a
        `fork_failed` row to say a fork had been wanted. For a child of a top-level
        orchestrator that space is the human's own checkout, so the degraded outcome was
        an agent writing where somebody else's uncommitted work lives — which is not a
        smaller version of what was asked for, and is exactly as unrecoverable as reusing
        a branch. The caller is told instead; see `ForkFailed`, and DESIGN-TRUTH's "A fork
        that fails refuses the spawn and tells the parent."
        """
        if self._branch_exists(name):
            raise BranchTaken(name)
        try:
            ws = self._attach_workspace(name)
        except HerdrError as e:
            store.log_event(self.db, kind="fork_failed", agent=name, parent=parent,
                            error=str(e))
            raise ForkFailed(name, self.repo, e) from None
        store.log_event(self.db, kind="fork", agent=name, parent=parent,
                        workspace=ws["workspace"], branch=ws.get("branch"),
                        path=ws["path"], base=ws.get("base"),
                        base_fallback=ws.get("base_fallback"))
        return ws                # `delegate` links this worktree's config on its way past

    def _branch_exists(self, branch: str) -> bool:
        """Is there already a branch of this name?

        Local heads only, and on purpose: a remote-tracking `origin/<name>` is not a
        branch in this repo, and `git worktree add` would fork a fresh local branch from
        the base regardless — refusing on it would block a name whose only claim is that
        somebody once pushed it.

        A repo git cannot answer for answers False, which lets the fork proceed to herdr
        and fail there with a message about the real problem.
        """
        return bool(self._git(
            "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=True))

    def delegate(
        self,
        task: str,
        *,
        role: str = DEFAULT_ROLE,
        as_prompt: Optional[str] = None,
        name: Optional[str] = None,
        model: Optional[str] = None,
        with_: Sequence[str] = (),      # NAMES to bind (or literal lines) — see below
        cleanup: Optional[str] = None,
        me: Optional[str] = None,
        workspace: Optional[str] = None,
        branch: Optional[str] = None,
        workspace_id: Optional[str] = None,     # "" is "there is none", not "work it out"
        cwd: Optional[str] = None,
        pane: Optional[str] = None,
        board: bool = True,
        awaiting_task: bool = False,    # `task` is a placeholder; nobody has asked yet
    ) -> str:
        me = me or self.whoami()
        r = roles_mod.get(self.roles, role)
        name = name or self._unique_name(role)

        # A child inherits its parent's workspace unless told otherwise, so a whole
        # delegation subtree stays inside one worktree without anyone passing it down.
        inherited = workspace is None
        ws = self._workspace_of(me) if inherited else workspace
        # The parent's branch comes with the parent's workspace, and only with it: an
        # agent placed in a workspace by NAME is told which branch that is (or told
        # nothing, and is bare). Reading the branch off the name instead would hand a bare
        # space the checkout of a worktree space that shares its name — which is the
        # confusion `agents.branch` exists to end.
        if branch is None and inherited:
            branch = self.worktree_branch(me)

        # THE FORK RULE. A worktree is forked when your parent does not have one;
        # otherwise you inherit your parent's and share it as a tab. Role-agnostic: a
        # researcher that only reads gets its own tree too, because "it will not write"
        # is a claim about the future, and the one bare space in the model — the root
        # orchestrator's, over the human's main checkout — is the one place a wrong claim
        # costs somebody's uncommitted work.
        #
        # `has_worktree` is a fact READ FROM THE STORE (`agents.branch`), never inferred
        # from the workspace name: the name says branch for a worktree space and an
        # agent-ish label for a bare one, with nothing to tell them apart. The human
        # answers False and so forks, which is the same rule and not an exception to it —
        # a child of a person is a child of somebody with no tree to lend.
        #
        # Only on the INHERITED path. A caller that named a workspace — `sb start`, a
        # workspace lead, `sb delegate --workspace <name>` — has already said where this
        # agent goes, and forking over that would ignore the instruction.
        #
        # A fork that fails RAISES (`ForkFailed`) rather than returning nothing, so there
        # is no path from here to "spawned in the parent's checkout after all".
        if inherited and not self.has_worktree(me):
            forked = self._fork_for(name, parent=me)
            ws, branch = forked["workspace"], forked["branch"]
            workspace_id = workspace_id or forked["workspace_id"]
            cwd = cwd or forked["path"]
            # A freshly forked workspace already has an idle shell; spending a tab on top
            # of it leaves an empty pane behind forever. Same trade as `_spawn_lead`'s.
            pane = pane or forked["pane_id"]

        if cwd:
            where = Path(cwd)
        elif ws:
            where = Path(self._recorded_path(ws) or self.repo)
        else:
            where = self.repo

        prompts = [
            self._protocol(),
            self._say("spawn.identity", name=name, role=role, parent=me),
        ]
        if ws:
            prompts.append(self._say("spawn.workspace", workspace=ws, path=where))
        if as_prompt:
            prompts.append(as_prompt)
        elif r.prompt:
            prompts.append(r.prompt)
        prompts.extend(self._resolve_bindings(role, with_))

        self.link_config(where)     # a worktree must see repo-local config (roles.toml)
        # `confirmed` is what decides whether this id gets WRITTEN DOWN below. A caller
        # that named one is stating a fact (it just opened that workspace); a derived one
        # is only a fact for the first three tiers.
        if workspace_id is None:
            wsid, confirmed = self._parent_workspace_id(me, ws)
        else:
            wsid, confirmed = workspace_id, True
        if not pane:
            pane, wsid = self._tab_for(wsid, where)

        # Before the claim, so a pane that cannot be pinned costs no row and no name, and
        # so the wait stays outside the window `status.SPAWN_GRACE` covers.
        self._pin_sb(name, pane, where)

        # Claim the name BEFORE herdr is asked to start anything. `agents.name` is a
        # PRIMARY KEY, and that index is the only arbiter two concurrent spawners share —
        # so the insert has to come first and be the thing that decides who wins. Doing it
        # afterwards (spawn, then record) is what raced: both openers spawned, both wrote,
        # and one of them lost with a bare IntegrityError out of the middle of a spawn.
        #
        # `state='working'` with no session id yet: the row is a claim, and it is filled in
        # below. `pane_id` is set from the start so the claim can be told apart from a husk
        # — a row with neither pane nor session is a dead run's leftovers and is safe to
        # replace, whereas this one belongs to a spawn that is happening right now.
        claim = dict(
            name=name, role=role, parent=(None if me == HUMAN else me), task=task,
            cwd=str(where), workspace=ws, branch=branch,
            # Recorded, not re-derived later: this is the id its own children inherit —
            # which is exactly why only a confirmed one goes down. A guess written here
            # is indistinguishable from a fact by every reader after it.
            workspace_id=(wsid if confirmed else None) or None,
            pane_id=pane, cleanup=cleanup or r.cleanup, awaiting_task=awaiting_task,
        )
        claimed = store.claim_agent(self.db, **claim)
        if not claimed and self._spawn_husk(name):
            # THE NAME-REUSE CARVE-OUT. The one row that may hold this name and not be
            # somebody is the husk a previous spawn's failure left below — evidence, not
            # an owner, and `claim_agent`'s `INSERT OR IGNORE` cannot tell the two apart.
            # Drop it and claim again, the same replacement `_top` and `_spawn_lead` make
            # for a husk of their own. Check-then-act, so two spawners can both find the
            # husk — but the second claim is still the arbiter, and the loser is refused
            # below exactly as before.
            store.drop_agent(self.db, name)
            claimed = store.claim_agent(self.db, **claim)
        if not claimed:
            raise AgentNameTaken(name)

        # `model` is a TIER name (`sb delegate --model strong`), not a model id, and it
        # only overrides which tier — the table still decides what that tier means. The
        # spec goes down as flags, so nothing below here has to know either.
        try:
            agent = self.h.start_agent(
                name, pane, prompts=prompts, model_args=r.spec(model).cli_args()
            )
        except Exception as e:
            # Leave a HUSK, not nothing. Deleting the row gave the name back and threw
            # the attempt away with it: herdr spent real effort over `SPAWN_ATTEMPTS`
            # tries and failed loudly, and afterwards nothing on the board, in the store
            # or in the log said this agent had ever been asked for — which is no answer
            # at all for a caller who backgrounded the spawn and came looking later.
            #
            # `failed` with no pane and no session is the shape `_top` and `_spawn_lead`
            # already read as "a dead run's leftovers, safe to replace", and the claim
            # above carves the same rule out for this name — so the name is no more held
            # against a later attempt than it was, and the failure survives as a fact.
            store.update_agent(self.db, name, pane_id=None)
            store.set_state(self.db, name, GONE_STATE)
            store.log_event(self.db, kind="spawn_failed", agent=name, parent=me,
                            role=role, pane_id=pane, error=str(e))
            raise
        store.update_agent(self.db, name, session_id=agent.session_id or None,
                           terminal_id=agent.terminal_id, pane_id=agent.pane_id or pane)
        # The spawn is real now — and it may have taken long enough (a retried `agent
        # start`) that a `status.collect` in the gap reaped the claim out from under it.
        # Say so unconditionally rather than checking first: `working, not ended` is what
        # this row is, whoever wrote what to it while we were waiting on herdr.
        store.mark_spawned(self.db, name)
        store.log_event(self.db, kind="delegate", agent=name, parent=me, role=role,
                        workspace=ws)
        if board:
            # EVERY agent opens with the tree beside it, not just the top-level
            # orchestrator `sb start` makes: `delegate` is the one place every spawn
            # passes through, so this is the one place the board can be opened without
            # a second path to drift from the first. Split before the task is delivered,
            # so the agent's first draw is already at its final width.
            #
            # The pane herdr actually put the agent in, not the one we asked for — the
            # same value the row above was updated with.
            self._open_board(name, agent.pane_id or pane, cwd=str(where))
        # THE SPAWN IS NOT DONE UNTIL THE TASK IS IN. `agent start` retries and raises
        # loudly, but the first task used to go down as a bare `agent prompt` — one
        # unverified call that can paste without submitting or never arrive, after which
        # `delegate` returned the name as if all of it had worked. That is how a fan-out
        # reports six agents and starts two, and it cost this project roughly eight agents
        # in one session. `deliver` re-sends until herdr says the agent took it.
        try:
            self.h.deliver(name, task)
        except HerdrError as e:
            # A started agent with no task is not a success, so it is not recorded as one.
            # `failed` and NOT a husk — the pane and the session stay on the row, because
            # something is genuinely sitting in that pane and whoever reads this needs to
            # be able to look at it, close it, or restore it. The husk carve-out above
            # tests for neither being present, so this row is never silently replaced.
            store.set_state(self.db, name, GONE_STATE)
            store.log_event(self.db, kind="task_undelivered", agent=name, parent=me,
                            role=role, pane_id=agent.pane_id or pane, error=str(e))
            raise TaskUndelivered(name, e) from None
        return name

    def _spawn_husk(self, name: str) -> bool:
        """Is the row under this name the leftovers of a spawn that failed?

        `failed`, no pane, no session — what `delegate`'s except path writes, and the
        same shape `_top` and `_spawn_lead` replace. Every other row under a name is
        somebody: a claim mid-spawn carries a pane, an agent that ran carries a session,
        and a `failed` row with either of those is a real agent `status` reaped, whose
        pane may still be open and whose session `sb restore` can still bring back.
        """
        a = store.get_agent(self.db, name)
        return (a is not None and a["state"] == GONE_STATE
                and not a["pane_id"] and not a["session_id"])

    def _unique_name(self, role: str) -> str:
        n = 1
        while store.get_agent(self.db, f"{role}-{n}"):
            n += 1
        return f"{role}-{n}"

    # -- messaging -------------------------------------------------------

    def tell(
        self, targets: Iterable[str], message: str, *, me: Optional[str] = None,
        reply_to: Optional[int] = None, kind: str = "tell",
    ) -> list[int]:
        me = me or self.whoami()
        ids = []
        for who in targets:
            t = self._resolve(who, me)
            if t == HUMAN:
                # The human has no mailbox, so this row would be written and never read by
                # anybody. Refusing is the honest answer: a person is reached by STOPPING,
                # which puts you in `sb status --needs-me` until they deal with you.
                raise ValueError(
                    "the human has no mailbox — a message to them would never be read. "
                    "Use `sb block \"<why>\"` if you need an answer, or `sb done "
                    "\"<summary>\"` to report what you did."
                )
            # A plain `tell` answers a pending `ask` — correlation is the tool's job,
            # which is why there is no `reply` verb.
            rt = reply_to
            if rt is None and kind == "tell":
                pending = store.pending_ask(self.db, asker=t, target=me)
                rt = pending["id"] if pending else None
            mid = store.put_message(
                self.db, from_agent=me, to_agent=t, kind=kind, body=message, reply_to=rt
            )
            ids.append(mid)
            if rt is not None:
                # An answer needs no doorbell: whoever asked is blocked inside `sb ask`
                # collecting it already, and it comes back as that call's return value.
                # Ringing anyway delivered every answer three times — as the return value,
                # as an unread inbox row, and as a prompt injected into the asker's turn —
                # which cost the asker a turn per ask, one per target on a fan-out. That is
                # exactly the per-message loop C0 exists to prevent.
                #
                # The cost of this: an asker whose `ask` had already timed out gets the
                # answer with no announcement. It is still in the store, and `sb log` still
                # shows it; the alternative is paying a turn on every answer forever.
                store.mark_collected(self.db, mid)
            else:
                # Only the human answers a block, so only the human's `tell` clears one.
                # Anyone else's mail is held until they have (see `_ring`).
                self._ring(t, self._say("notify.mail"), answer=(me == HUMAN))
        return ids

    def ask(
        self, targets: Sequence[str], question: str, *,
        me: Optional[str] = None, timeout: int = ASK_TIMEOUT, poll: float = ASK_POLL,
    ) -> dict[str, Optional[str]]:
        """Send and block until every target answers.

        For AGENTS only, and it is the only blocking verb. Multi-target because "ask three
        researchers and wait" is the common fan-out; looping would cost the caller a turn
        per child. Waiting on another agent is legitimate: it is usually seconds, and the
        answer is this call's return value, used inline.

        Asking the HUMAN is refused outright — `sb block` is the one and only way to reach
        a person, and this is not a second one. Holding a turn open for a human is a trap:
        the answer can take hours, and all that time the agent shows as working, a live
        process sits there, and the tool call may time out on top of it. `block` ends the
        turn, costs nothing while it waits (C10), and the doorbell restarts it — so for a
        human target it is strictly better and there is nothing to choose between.

        An error rather than a silent alias, because the two verbs do not merely differ in
        mechanism, they differ in what the CALLER does next: `ask` returns an answer to use
        inline, `block` means stop. Quietly turning one into the other would leave an agent
        marked blocked while its turn ran on, waiting for a return value that never comes.
        Told plainly, it runs `sb block` and stops, which is the whole point.
        """
        me = me or self.whoami()
        resolved = [self._resolve(w, me) for w in targets]
        if any(t == HUMAN for t in resolved):
            # Before anything is written: a refused ask must leave no half-sent fan-out.
            raise ValueError(
                "there is no way to ask the human and wait — they have no mailbox, and "
                "an answer can take hours. Use `sb block \"<why>\"`: it ends your turn "
                "and you are poked the moment they answer."
            )
        missing = [t for t in resolved if store.get_agent(self.db, t) is None]
        if missing:
            # Otherwise the caller blocks for the whole timeout waiting on nobody.
            raise KeyError(f"no such agent: {', '.join(missing)}")
        ids = {}
        for t in resolved:
            ids[t] = store.put_message(
                self.db, from_agent=me, to_agent=t, kind="ask", body=question
            )
            self._ring(t, self._say("notify.mail_question"))

        answers: dict[str, Optional[str]] = {t: None for t in resolved}
        deadline = time.time() + timeout
        # A child can die recording NOTHING — no done, no failed — and the store then has
        # no reason to stop waiting. herdr knows it is gone, but a single absent reading
        # is indistinguishable from a hiccup, so require it to stay gone.
        vanished: dict[str, int] = {t: 0 for t in resolved}
        gone_for = max(3, int(GONE_GRACE / max(poll, 0.01)))
        while time.time() < deadline:
            waiting = False
            for t, mid in ids.items():
                if answers[t] is not None:
                    continue
                r = store.reply_to_ask(self.db, mid)
                if r:
                    answers[t] = r["body"]
                    continue
                if self._will_never_answer(t):
                    continue
                vanished[t] = 0 if self._is_registered(t) else vanished[t] + 1
                if vanished[t] >= gone_for:
                    store.log_event(self.db, kind="ask_target_vanished", agent=t,
                                    waited=round(time.time() - (deadline - timeout), 1))
                    continue                  # gone long enough to not be a hiccup
                waiting = True
            if not waiting:
                # Either everyone answered, or whoever has not is finished and never
                # will. Sitting out the remaining fourteen minutes would be a lie about
                # what this call is doing.
                return answers
            time.sleep(poll)
            # The doorbell above may have been held back because the target was mid-turn
            # (see `_ring`). Nothing else is running in this process while we block, so if
            # we did not retry it here an `ask` to a busy agent would wait out its whole
            # timeout for a question that was never announced.
            self.flush_pending(refresh=True)
        return answers  # unanswered stay None; the caller decides (C9)

    def _is_registered(self, who: str) -> bool:
        """Does herdr still know this agent? Refreshed each poll, unlike `_busy`."""
        try:
            self._alive_cache = {a.name: a.state for a in self.h.list_agents()}
        except HerdrError:
            return True                       # cannot tell: assume alive, never kill on doubt
        return who in self._alive_cache

    def _will_never_answer(self, who: str) -> bool:
        """Whether waiting on this target is waiting forever.

        The STORE only — deliberately not herdr. An agent missing from `agent list` looks
        identical whether it died or herdr hiccupped, and treating a hiccup as death would
        make `ask` return nothing at all the moment herdr coughed. A `done` or `failed`
        row, by contrast, is something the agent itself recorded: it has ended its turn
        for good, and the answer is not coming.

        Only ever called for agent targets: the human is never waited on (see `ask`).
        """
        a = store.get_agent(self.db, who)
        return a is not None and a["state"] in FINISHED

    def inbox(self, *, me: Optional[str] = None, peek: bool = False) -> list:
        """All unread at once — a per-message loop would cost a turn each (C0).

        Reading marks messages read, so polling with `inbox` consumes them. Use
        `peek=True` to look without consuming.

        For agents only. The human is not a mailbox holder — nothing is ever addressed to
        them — so `sb inbox` typed by a person is answered by the CLI with where to look
        instead (`sb status --needs-me`), rather than by an empty list here.
        """
        return store.unread_for(self.db, me or self.whoami(), mark=not peek)

    # -- status ----------------------------------------------------------

    def done(self, summary: str, *, me: Optional[str] = None) -> list[str]:
        """Report finished. The summary goes to the parent, if there is one.

        A ROOT agent has no parent and the human has no mailbox, so its summary is not
        mail — it is a record. The event log carries it, and that is what the readouts
        show: `sb status` puts it on the done row, `sb inspect` prints it in full, `sb
        log` has it. Nothing is lost by not addressing anybody; a row in a mailbox nobody
        reads was only ever a second copy of this.

        **Reporting done with children still working stays legal**, and the returned list
        of their names is the whole change here. Refusing it would be a protocol change —
        a parent that delegated and then hit its own end would have no legal move, and
        the one it would reach for is closing its children, which ends work nobody asked
        to end. It is also not where the harm is: `cleanup` is what closes the pane, and
        `cleanup` now refuses (see `live_descendants`), so a done parent with live
        children stays reachable and still collects their summaries.

        So it is surfaced, not blocked: the names come back for the CLI to print, and
        `done_with_live_children` goes in the log.
        """
        me = me or self.whoami()
        if me == HUMAN:
            raise ValueError("`sb done` is for agents")
        a = store.get_agent(self.db, me)
        parent = a["parent"] if a else None
        if parent:
            store.put_message(self.db, from_agent=me, to_agent=parent, kind="done",
                              body=f"[done] {summary}")
        store.set_state(self.db, me, "done")
        self._push_state(a, IDLE, summary)   # herdr has no `done`; it derives it from idle
        store.log_event(self.db, kind="done", agent=me, summary=summary[:EVENT_CLIP])
        still_working = self.live_descendants(me)
        if still_working:
            store.log_event(self.db, kind="done_with_live_children", agent=me,
                            children=",".join(still_working))
        if parent:
            # The parent's turn ended while this ran; the poke is what restarts it, so a
            # lazy parent never has to poll (C4, C10).
            self._ring(parent, self._say("notify.child_done"))
        return still_working

    def block(self, why: str, *, me: Optional[str] = None) -> None:
        """Stop and surface to the human — never to the parent.

        Routing blocks around the parent is what keeps parent context from growing with
        every problem (C14, C4).

        This is the ONE way an agent reaches a person, and `sb ask human` is a spelling of
        it (see `ask`). There is no human mailbox to leave the reason in, and it does not
        need one: the block is durable in the agent's own state and in the event log, and
        both readouts are driven from there — `sb status --needs-me` lists this agent with
        `why` for as long as it stays blocked. A dismissed desktop notification therefore
        loses nothing, which was the only reason a mailbox row was ever written here.

        The human answers with `sb tell <agent> "..."`, which rings the doorbell and
        unblocks it (see `_unblock_if_needed`).
        """
        me = me or self.whoami()
        if me == HUMAN:
            raise ValueError("`sb block` is for agents")
        store.set_state(self.db, me, "blocked")
        # NOTHING is reported to herdr here, and that silence is the whole of what makes a
        # block answerable (see `_binding_lost` for what it costs when it is not).
        #
        # `pane report-agent` does not annotate a pane's agent, it REPLACES it. The named
        # agent `agent start` registered is evicted and a source-reported record put in its
        # place, and a reported record is not a target: `agent get`/`agent prompt <name>`
        # answer agent_not_found, and a pane-targeted prompt answers agent_not_ready
        # ("<pane> is not an active named agent"). It is one-way — `pane release-agent`
        # deletes the record rather than handing detection back (the pane then drops out of
        # `agent list` entirely), and `agent start` on the still-live pane refuses
        # agent_pane_busy. So the doorbell can never ring that agent again, on the one verb
        # whose entire purpose is "stop and get a human".
        #
        # This used to push `idle`, on the reading that herdr's `blocked` badge is what
        # costs the binding. That reading was half right and the wrong half was load-
        # bearing: `blocked` does cost it, and so does `idle`, and so does every other
        # value. The state is not what evicts the name — making the call is. Measured on
        # herdr 0.8.0 against a throwaway pane: `agent start` → bound; `pane
        # report-agent-session` → still bound; one `pane report-agent --state idle` →
        # agent_not_found, and nothing brings it back.
        #
        # Nothing is lost by staying quiet. Blocked-ness has always lived in our store
        # (`_is_blocked`), which is what `sb status --needs-me` and the board read (C5), and
        # herdr's own detector reads a waiting agent as idle unprompted — the very value we
        # were paying the binding to tell it. The notification below is what reaches you.
        self._surface(me, why)
        store.log_event(self.db, kind="blocked", agent=me, why=why[:EVENT_CLIP])

    # `sb status` is deliberately NOT here. It is a join of the store against herdr — what
    # an agent was told to be, against what its pane is doing — and belongs to neither, so
    # it lives in status.py and the CLI calls it directly. This module once carried a
    # `status()` that returned store rows alone, which is exactly the readout that reports
    # a stalled agent as busy for the rest of the day.

    # -- lifecycle -------------------------------------------------------

    def cleanup(self, names: Sequence[str] = (), *, include_kept: bool = False,
                force: bool = False, dry_run: bool = False,
                leave_children: bool = False,
                me: Optional[str] = None) -> "CleanupResult":
        """Close agents. With no names, every finished one in the caller's scope.

        Safe to be aggressive: closing costs only the pane. Session, summary, messages
        and the on-disk transcript all survive, and `sb restore` brings the agent back.

        Five gates, and which of them a caller may lift is the whole design:

        - **finished, and no unread mail it could still read.** A sweep never lifts these.
          Closing an agent mid-turn would strand whatever it was doing, and taking away
          the pane while a message sits unread loses somebody the answer they are blocked
          on. Mail for an agent that has finished AND lost its name binding is the one
          exception, because it is not mail anybody is going to read either way — see the
          gate itself.
        - **an end nobody reported is re-checked against herdr.** `done` is the agent's
          own word; `failed` is `status._record_gone`'s inference from one `agent list`,
          and that call can be taken mid-spawn or against a herdr that hiccupped. So for
          a `failed` row we ask again, and a sweep never lifts it either.
        - **the role's `cleanup` disposition.** `include_kept` lifts this one, and only
          this one: it says "I mean the keepers too", not "close anything".
        - **everything.** `force` lifts all of it, and is only legal for agents named
          outright — it is the escape hatch for an agent that is genuinely stuck (its
          state never advanced, its name was lost by herdr, it holds mail it can never
          read) and that no sweep can therefore ever reach. Naming it IS the confirmation.

        - **live descendants**, and `force` does NOT lift this one. See
          `live_descendants` for the invariant. Every other gate is a fact about the
          agent you named — its state, its mail, its role — and `--force` is you saying
          you know that fact and mean it anyway. Live children are facts about agents you
          did NOT name, and no flag about this agent gets to decide their fate. So the
          gate takes its own flag, `leave_children`, which says the thing it does: close
          the parent's pane, leave the children running. The other way out is to close
          the subtree from the leaves up, which never breaks the invariant at all.

          Named agents get a refusal before anything is closed, rather than a skip: you
          asked for this agent by name, so silence would be a lie. A sweep skips it the
          way it skips every other gate, and logs `cleanup_held` so the log can answer
          "why is that one still here".

        Every gate that holds a candidate back records its reason on the returned
        `CleanupResult.refused`, and logs `cleanup_refused`. A gate firing in silence is
        the bug this closes: `closed: (nothing)` told you the outcome and never the rule,
        and the only remaining move was `--force`, which lifts all five at once.
        """
        me = me or self.whoami()
        if me == HUMAN:
            scope = self.db.execute("SELECT * FROM agents").fetchall()
        else:
            # An agent may only clean up its OWN subtree — never a sibling's agents.
            scope = self._descendants(me)
        by_name = {a["name"]: a for a in scope}

        if names:
            missing = [n for n in names if n not in by_name]
            if missing:
                raise KeyError("not yours to clean up, or no such agent: "
                               + ", ".join(missing))
            candidates = [by_name[n] for n in names]
        else:
            if force:
                raise ValueError("--force needs the name of the agent to close: "
                                 "it lifts every safety gate, so it is never a sweep")
            candidates = scope

        # Computed for every candidate up front, so a named agent is refused before
        # anything at all has been closed: half a `sb cleanup a b` is worse than none.
        held = {} if leave_children else {
            a["name"]: kids for a in candidates
            if a["name"] != me and (kids := self.live_descendants(a["name"]))
        }
        if held and names:
            raise ValueError(
                "still working underneath: "
                + "; ".join(f"{p} → {', '.join(kids)}" for p, kids in held.items())
                + ". Close them first (the subtree closes from the leaves up), or "
                  "--leave-children to close the parent and leave them running."
            )

        closed = CleanupResult()

        def refuse(a, reason: str, *, log: bool = True) -> None:
            """Say why this candidate stays. The one exit every gate now takes.

            A dry run reads and never writes, so it records the reason and logs nothing —
            the same rule the live-descendants gate already followed. That gate keeps its
            own `cleanup_held` event rather than logging twice; only its reason comes
            through here.
            """
            closed.refused.append((a["name"], reason))
            if log and not dry_run:
                store.log_event(self.db, kind="cleanup_refused", agent=a["name"],
                                reason=reason[:EVENT_CLIP])

        for a in candidates:
            if a["name"] == me:
                # Named, this is somebody asking to close the pane they are typing in.
                refuse(a, "that is you — an agent cannot close its own pane")
                continue
            if a["ended_at"] and not a["pane_id"]:
                refuse(a, "already closed")
                continue
            if a["name"] in held:
                if not dry_run:               # a dry run reads; it never writes
                    store.log_event(self.db, kind="cleanup_held", agent=a["name"],
                                    live_children=",".join(held[a["name"]]))
                refuse(a, "still working underneath: " + ", ".join(held[a["name"]]),
                       log=False)
                continue                      # the invariant; see the docstring
            if not force:
                if a["state"] not in FINISHED:
                    # only finished agents; --all-idle too
                    refuse(a, f"{a['state']}, not finished — it has not reported an end")
                    continue
                if a["state"] == GONE_STATE and not self._end_still_holds(a["name"]):
                    refuse(a, f"recorded {GONE_STATE}, but herdr still has its pane — "
                              f"nobody reported this end")
                    continue
                if (store.unread_for(self.db, a["name"], mark=False)
                        and not self._finished_and_unreachable(a["name"])):
                    # Unread mail it could still read holds the row, as it always has.
                    # Mail for an agent whose turn ended and whose name no longer binds is
                    # a different thing: nothing announces it, nothing reads it, and
                    # holding the row open does not make it any more readable — it only
                    # jams that row forever, closable by neither a sweep nor `--force`
                    # having been meant. Closing loses nothing; the message survives, and
                    # `sb restore` brings back an inbox that still holds it.
                    refuse(a, "unread mail it could still read")
                    continue
                # Naming an agent is itself the instruction to close it, so an explicit
                # name lifts the role's disposition exactly as `include_kept` does.
                if a["cleanup"] != "close" and not (include_kept or names):
                    refuse(a, f"role {a['role']} is kept, not closed (--include-kept)")
                    continue
            if dry_run:
                closed.append(a["name"]); continue
            if force and a["state"] == WORKING:
                # Force cannot tell stuck from busy — every gate above is skipped, so an
                # agent mid-turn is closed exactly like a wedged one and the only trace
                # was `cleanup(forced=True)`, which says nothing about what was taken
                # away. Say it, in the shape `cleanup_held` already uses for "why is that
                # one still here". Nothing is sent first and nothing is refused: this is
                # the escape hatch, and naming the agent is the confirmation.
                store.log_event(self.db, kind="cleanup_forced_live", agent=a["name"],
                                state=a["state"])
            try:
                if a["pane_id"]:
                    self.h.release_agent(a["pane_id"], a["name"], store.next_seq(self.db, a["name"]))
                    self.h.close_pane(a["pane_id"])
            except HerdrError as e:
                if e.code == "pane_not_found":
                    # The pane is already gone — a human closed it by hand, or herdr lost
                    # it. That is this close having happened, not having failed, and
                    # treating it as a failure left `pane_id` set on the row so every
                    # later sweep repeated the same doomed call, forever.
                    store.log_event(self.db, kind="cleanup_pane_gone", agent=a["name"])
                else:
                    store.log_event(self.db, kind="cleanup_failed", agent=a["name"],
                                    error=str(e))
                    if not force:
                        refuse(a, f"herdr could not close its pane: {e}", log=False)
                        continue
                    # Under force we fall straight on into the bookkeeping below and mark
                    # this row `done` with no pane, having just failed to close its pane.
                    # That is deliberate — `--force` is documented as the override that
                    # always ends done, and making the commit conditional would leave
                    # somebody's genuinely stuck agent still stuck after a herdr blip —
                    # but committing it silently is the row asserting a pane is gone that
                    # nobody confirmed is gone. So say so, by name, and carry the pane id
                    # into the event: the next line discards the only reference to it, and
                    # a still-live pane is then unreachable through the store forever.
                    store.log_event(self.db, kind="cleanup_forced_unconfirmed",
                                    agent=a["name"], pane_id=a["pane_id"], error=str(e))
                    print(f"sb: {a['name']}: pane {a['pane_id']} could not be closed "
                          f"({e}) — forcing it done anyway, so the pane may still be "
                          f"open with nothing left pointing at it", file=sys.stderr)
            # The board went up beside this agent, so it comes down with it — otherwise
            # closing an agent leaves an empty tab behind, once per agent. After the
            # skip above, so a close we abandoned leaves the board with its live pane.
            self._close_board(a["name"])
            store.set_state(self.db, a["name"], "done")
            # The pane is gone, so the row must stop claiming one: the "already gone"
            # guard above is `ended_at and not pane_id`, and a stale id defeated it — a
            # second sweep then retried release/close against a dead pane every time.
            store.update_agent(self.db, a["name"], pane_id=None)
            store.log_event(self.db, kind="cleanup", agent=a["name"], forced=force)
            closed.append(a["name"])
        return closed

    def live_descendants(self, name: str) -> list[str]:
        """Descendants of `name` whose work is still going. The invariant's one predicate.

        > **INVARIANT: an agent whose pane is closed has no descendant whose pane is
        > still working.**

        Before this it was true by luck: `children_of` existed in exactly one place, to
        scope a sweep to the caller's subtree, and nothing anywhere asked "does this
        agent have live children?" before ending it. Everything that closes a pane on
        purpose asks here now, so the invariant holds by construction rather than by
        nobody having tried yet.

        Why it matters is not tidiness: a child of a closed parent reports with `sb
        done`, which writes the summary to the parent and rings it. The parent has no
        pane, so the ring fails (`ring_failed`) and the summary sits unread in the store
        forever, which is precisely the "the board looks fine and something is silently
        not happening" class.

        **The STORE only, deliberately not herdr** — the same call `_will_never_answer`
        makes, for the same reason. An agent missing from `agent list` looks identical
        whether it died or herdr hiccupped, and a hiccup that read as "no live children"
        would wave through exactly the close this exists to stop. A row that says
        `working` when the pane is long dead costs a refusal, which the human undoes by
        closing that row; the other way round costs live work.

        A row is born `working`, so a child mid-spawn counts as live. That is the safe
        direction: it is also the child that would be hardest to notice missing.

        **What this cannot cover, and nothing can: a parent's pane that simply dies** — a
        crash, a closed tab, a herdr restart (route A1). There is no caller there to
        refuse, so the invariant is a property of what switchboard *does*, not of what
        the world does to it. What the model says about that shape is: it is not a state
        anything here creates, it is already recorded when it bites (`ring_failed` on the
        child's `done`), and it is nameable — this method, asked of the dead parent,
        answers it. The board draws it as an ordinary archived row with its live children
        under it, which is the honest picture and not a special case.
        """
        return [a["name"] for a in self._descendants(name)
                if a["state"] in store.LIVE_STATES and not a["ended_at"]]

    def _descendants(self, name: str) -> list:
        out, frontier = [], [name]
        while frontier:
            kids = store.children_of(self.db, frontier.pop())
            out.extend(kids)
            frontier.extend(k["name"] for k in kids)
        return out

    def restore(self, name: str, *, workspace: Optional[dict] = None) -> str:
        """Bring a closed agent back with its full context.

        Verified: `--resume` in a fresh pane restores the conversation and replays the
        transcript, so closing really is free.
        """
        a = store.get_agent(self.db, name)
        if not a:
            raise KeyError(f"no such agent: {name}")
        if not a["session_id"]:
            raise ValueError(f"{name} has no session id; nothing to restore")
        if self._alive(name):
            # Checked BEFORE a tab is made. herdr refuses `agent start` under a name it is
            # already running, all three attempts, and the tab created ahead of that was
            # left behind — one orphan empty pane per attempt to restore something that
            # never went away.
            raise ValueError(
                f"{name} is already running — nothing to restore. "
                f"To reach it: sb inspect {name}, or sb tell {name} \"...\""
            )
        # And never back into a workspace that is being taken apart. Restoring is the
        # third door into one — the agent comes back into the checkout it was recorded
        # in, which is the directory the teardown is about to remove — and a door that
        # only `sb workspace new` guards is not guarded.
        self._refuse_retiring(a["workspace"])
        # Come back into the workspace it belongs to, not into whichever one has focus.
        ws = workspace or {}
        # What we recorded when it was spawned, before the ambiguous name lookup: a
        # workspace NAME resolves to a checkout, and one checkout can be open in several
        # workspaces, so deriving it would bring the agent back somewhere else.
        wsid = (ws.get("workspace_id") or _column(a, "workspace_id")
                or self._workspace_id(a["workspace"]))
        where = ws.get("path") or a["cwd"] or str(self.repo)
        # A worktree that has been deleted is the end of this agent, and saying so is the
        # whole of the fix: herdr silently substitutes `$HOME` for a `--cwd` that does not
        # exist, so restoring into a removed checkout reported `restored <name>` and put a
        # live agent in Andrew's home directory with none of its context and every
        # intention of writing there. DESIGN-TRUTH is explicit that restore is gone once
        # the worktree is — the push is the recovery path for the work — so this refuses
        # and names the branch the work is still on.
        #
        # Checked here rather than in `_tab_for`, which `delegate` and the workspace spawn
        # also call: this is the one caller whose directory was recorded long ago and can
        # have been removed since.
        if not Path(where).is_dir():
            branch = store.agent_branch(self.db, name)
            raise ValueError(
                f"{name} cannot be restored: its checkout is gone ({where}). "
                + (f"Its work is on branch {branch} — that branch is the recovery path, "
                   f"not restore."
                   if branch else
                   "No branch was recorded for it, so there is nothing to bring back.")
            )
        # The corrected id is deliberately dropped: restore rewrites pane and state, never
        # `workspace_id`, so a row `_tab_for` just cleared keeps the NULL it was given.
        pane, _ = self._tab_for(wsid, where)
        # A restored agent gets the same pinning a fresh one does — it comes back into the
        # same checkout and would otherwise come back on the installed build. The tab is
        # ours, so a refusal closes it rather than leaving an empty shell behind, exactly
        # as a failed `agent start` does below.
        try:
            self._pin_sb(name, pane, where)
        except SbUnpinned:
            try:
                self.h.close_pane(pane)
            except HerdrError as e:
                store.log_event(self.db, kind="orphan_pane", agent=name, error=str(e))
            raise
        # Same tier it was spawned on. The role is what we recorded, and the tier table is
        # what turns that back into flags — without this a restored agent silently comes
        # back on the provider CLI's default model, which is the one thing "restored with
        # its full context" must not quietly mean.
        spec = roles_mod.get(self.roles, a["role"]).spec()
        try:
            agent = self.h.start_agent(name, pane, resume=a["session_id"],
                                       model_args=spec.cli_args())
        except Exception:
            # The tab is ours; a failed restore must not leave an empty shell behind.
            try:
                self.h.close_pane(pane)
            except HerdrError as e:
                store.log_event(self.db, kind="orphan_pane", agent=name, error=str(e))
            raise
        store.update_agent(self.db, name, pane_id=agent.pane_id or pane,
                           terminal_id=agent.terminal_id)
        # Bring it back to life, not just back on screen. whoami() matches on
        # `pane_id AND ended_at IS NULL`, so leaving ended_at set makes a restored agent
        # resolve to HUMAN — everything it sends is then attributed to the human, and it
        # cannot report done. Verified end to end by QA.
        self.db.execute(
            "UPDATE agents SET ended_at=NULL, state='working' WHERE name=?", (name,))
        self.db.commit()
        store.log_event(self.db, kind="restore", agent=name)
        return name

    def interrupt(self, name: str, text: str, *, me: Optional[str] = None,
                  stop: bool = True) -> None:
        """Change course mid-flight. Human-facing; emergencies only.

        Not a variant of `tell`, though the two look alike. `tell` rings a doorbell that
        carries no payload and is held back while the target is mid-turn; this one cancels
        the turn with `esc` and puts the instruction itself on the wire, because a queued
        interrupt is not an interrupt — the work you are trying to stop would finish first.

        The message still goes in the store, and once delivery is confirmed it is marked
        read: the instruction is durable and shows up in `sb inspect` alongside everything
        else the agent was told, and having travelled inline there is nothing left to
        announce. Marked only THEN, though — marking it up front made a failed interrupt
        indistinguishable from one the agent had already read, which is the worst possible
        record of "this never arrived". If it does not arrive it stays queued, and
        `Undeliverable` tells the caller so.
        """
        me = me or self.whoami()
        if self._finished_and_unreachable(name):
            # Refused outright, before the `esc` and before the row is written. There is no
            # turn here to change course: the agent reported done and its name no longer
            # binds. Saying so plainly beats the `Undeliverable` this used to raise, which
            # dressed an ordinary "it already finished" up as a herdr failure — and it
            # leaves no half-sent interrupt behind for `sb inspect` to show.
            raise ValueError(
                f"{name} has already finished — there is no turn to interrupt. "
                f"Use `sb tell {name} \"...\"` to leave it a message, or "
                f"`sb restore {name}` to bring it back first."
            )
        # Always lands now — deferring an interrupt would defeat it entirely.
        if stop:
            try:
                self.h.send_keys(name, "esc")
                time.sleep(INTERRUPT_SETTLE)   # let the cancel land before the new one
            except HerdrError as e:
                store.log_event(self.db, kind="interrupt_stop_failed", agent=name, error=str(e))
        body = self._say("notify.interrupt", text=text)
        mid = store.put_message(self.db, from_agent=me, to_agent=name, kind="tell", body=body)
        # Raises Undeliverable if it cannot land — deliberately not caught here. The store
        # row survives it, undelivered, which is exactly the state a queued `tell` is in.
        self._ring(name, body, force=True)
        store.mark_collected(self.db, mid)
        store.log_event(self.db, kind="interrupt", agent=name, stopped=stop, text=text[:EVENT_CLIP])

    # -- internals -------------------------------------------------------

    def _agent_states(self) -> Optional[dict]:
        """Every agent herdr knows and what it is doing, or None if it could not be asked.

        One probe per `sb` process, failure included — each invocation is short, so a
        stale answer cannot outlive the call that fetched it, and re-asking a herdr that
        is down once per lookup would only spend the same failure again.

        None is emphatically NOT "nobody is running": it is "we cannot tell". Callers
        that would otherwise conclude an agent is dead must fail open on it.
        """
        if self._alive_cache is None and not self._alive_unknown:
            try:
                self._alive_cache = {a.name: a.state for a in self.h.list_agents()}
            except HerdrError:
                self._alive_unknown = True
        return self._alive_cache

    def _end_still_holds(self, name: str) -> bool:
        """Does herdr STILL agree that this agent's turn ended?

        Only ever asked about a row whose end was inferred rather than reported —
        `GONE_STATE`, written by `status._record_gone` and, for a spawn that exhausted
        herdr's retries, by `delegate`'s own except path. That row is a cached
        observation of a single `agent list`, and the readout that took it may have been
        looking during the agent's own spawn, or running old code with a shorter grace, or
        racing another reader. Re-taking it here is the whole protection: `cleanup` is the
        one caller that acts on the row irreversibly.

        Fails CLOSED, and this is the one place in the file that does. `_agent_states()`
        returns None for "cannot tell", and `_busy`/`running_tops` read that as "carry
        on" because the cost of their doubt is a doorbell or a name in a list that has
        already finished — both a line of noise, and neither irreversible. Here the
        costs are reversed: a wrong close takes a live agent's pane, and for a row that
        never reached a session id it takes the work with it — `restore` needs a session
        id, so there is nothing to come back to. A wrong SKIP costs one `--force <name>`.
        """
        states = self._agent_states()
        return states is not None and name not in states

    def _finished_and_unreachable(self, who: str) -> bool:
        """Has this agent ended its turn for good, with no pane left to ring?

        `sb done` ends a turn, and a real Claude Code process stops answering to its name
        the moment that turn ends — herdr says `agent_not_found` from then on. The row,
        though, keeps its `pane_id` and stays a perfectly good target, so every doorbell
        aimed at it fails, and `flush_pending` re-aims it on every `sb` command anybody
        runs, forever. This is the predicate that stops that.

        Two ways to be sure, and both are needed. A row with no `pane_id` has nothing to
        ring by construction — `cleanup` cleared it, or it never got one. A row that still
        holds a pane id is only unreachable if herdr, asked and answering, does not list
        the name: unknown is NOT gone (`_agent_states` returns None for "cannot tell"), and
        reading a herdr outage as death would silence the doorbell for a whole live fleet.

        That positive answer is also what makes this safe against `_revive`. An agent that
        reports done and then runs `sb` again is mid-turn while it does so, so herdr knows
        the name, and the guard does not fire on the one row that is about to come back.
        """
        a = store.get_agent(self.db, who)
        if a is None or a["state"] not in FINISHED:
            return False
        if not a["pane_id"]:
            return True
        states = self._agent_states()
        return states is not None and who not in states

    def _busy(self, who: str) -> bool:
        """Is this agent mid-turn right now, per herdr?

        Unknown reads as not busy: the doorbell this gates is held back for a busy agent,
        and holding it back on a hunch is how mail sits forever with nothing on screen.
        """
        return (self._agent_states() or {}).get(who) == WORKING

    def flush_pending(self, *, refresh: bool = False) -> list[str]:
        """Ring the doorbell for anyone who has mail they cannot know about, and is idle.

        Called at the start of every `sb` command (see `cli.main`) and on every pass of
        `ask`'s wait loop, so a deferred message lands as soon as anything at all touches
        the store — which, in a live session, is constantly. The store query is free when
        there is nothing pending; only then do we ask herdr.

        `store.unseen`, NOT `store.undelivered`: the doorbell exists to tell an agent
        something it does not already know, and an agent that read its inbox proactively
        already knows. Ringing on un-announced alone burns that agent a turn to find an
        empty inbox — and it used to be worse than a wasted turn: `_ring` unblocked before
        every delivery, so a stale doorbell put an agent that had stopped to ask a person
        back to `working` with its question never surfaced. Only the human's answer clears
        a block now. `status._undelivered_counts` reads the same pair, so what the
        board calls outstanding and what this chases can never drift apart.

        `refresh` discards the per-process view of who is busy. `sb` invocations are short
        enough that the cache cannot go stale inside one, but a blocked `ask` holds the
        same process open for up to fifteen minutes, and there the whole point is to
        notice that the target has since finished its turn.

        This is the stand-in for an events daemon. When one exists it replaces this
        trigger, not the model: deferred-then-delivered stays exactly the same.

        It is also where the backlog for agents that will never read again gets cleared —
        see `_clear_unreadable_mail`. Those rows are already in this work list, so the
        sweep is this loop rather than a migration: it costs nothing when there is none,
        and it happens once per message rather than on every command like the ring it
        replaces.
        """
        # The human is excluded because they are not an agent and have no doorbell. Nothing
        # is addressed to them any more, but a store written before the human mailbox was
        # removed still holds rows that would otherwise be retried on every command.
        pending = store.unseen(self.db, exclude=(HUMAN,))
        if not pending:
            return []
        if refresh:
            self._alive_cache = None
            self._alive_unknown = False
        rung = []
        for who in dict.fromkeys(m["to_agent"] for m in pending):
            mine = [m for m in pending if m["to_agent"] == who]
            if self._finished_and_unreachable(who):
                self._clear_unreadable_mail(who, mine)
                continue
            if self._busy(who):
                continue
            # A blocked agent is not idle. Its mail waits, exactly as a busy agent's does,
            # unless the human's answer is among it — that one both clears the block and
            # is the news worth announcing.
            answer = any(m["from_agent"] == HUMAN for m in mine)
            if not answer and self._is_blocked(who):
                continue
            if self._ring(who, self._say("notify.mail"), answer=answer):
                rung.append(who)
        return rung

    def _clear_unreadable_mail(self, who: str, messages: Sequence) -> None:
        """Stop chasing mail for an agent that has finished and has no pane.

        The doorbell is never going to ring for these (`_ring` guards it), and left alone
        they are worse than merely undelivered: `store.unread_for` keeps reporting them, so
        `cleanup`'s "unread mail would be lost" gate refuses to close the row — for mail
        nobody can ever read. That row is then closable by neither a sweep nor
        `cleanup`'s `pane_not_found` branch, which it never reaches: the unread gate
        `continue`s before any close is attempted. Marking the mail here, and lifting that
        gate for exactly these rows, is what lets them sweep normally again.

        Nothing is destroyed. The message keeps its body, its sender and its place in the
        log, so `sb inspect` and `sb log` still show it, and the event written here says
        plainly that it was cleared rather than read. What it loses is its claim on an
        inbox that is not going to be opened — and the narrow cost of that is an agent
        brought back later by `sb restore` finding those messages already read.

        Only for a row whose pane is GONE. A finished agent that still holds a pane is a
        different animal: a person can put a turn back into that pane, and `done` is
        explicit that a done parent with live children stays reachable and still collects
        their summaries. It loses the doorbell here (see `_ring`) and nothing else. Its
        mail is cleared once `cleanup` closes it, which is now something `cleanup` can
        actually do — see the unread gate there.
        """
        a = store.get_agent(self.db, who)
        if a and a["pane_id"]:
            return
        for m in messages:
            store.mark_collected(self.db, m["id"])
            store.log_event(self.db, kind="mail_cleared", agent=who,
                            sender=m["from_agent"], body=m["body"][:EVENT_CLIP])

    def _ring(self, who: str, text: str, *, force: bool = False,
              answer: bool = False) -> bool:
        """The doorbell. Carries no payload — the message is in the store.

        Held back while the target is mid-turn: `agent prompt` INTERLEAVES, injecting into
        the current turn rather than queueing after it, so ringing a working agent
        interrupts whatever it was doing. `force` is for interrupt, whose whole purpose is
        to land now.

        Held back while the target is BLOCKED, too, and for the same reason turned inside
        out: a blocked agent is not idle, it is waiting on a person. This used to unblock
        unconditionally before every delivery, so a sibling's unrelated `tell` — or a
        child's `done` — put the agent back to `working`, dropped it out of `sb status
        --needs-me`, and buried the human's eventual answer under mail it never asked for.
        `answer=True` is the one ring that is the human's reply, and it is the only thing
        that clears a block. Everything else waits its turn: the message stays queued and
        `flush_pending` rings it once the block is answered.

        There is no fallback when `agent prompt` fails. There used to be one — type the
        text into the agent's pane with `pane run` — and it was a shell: any backtick or
        `$(` in an agent-authored interrupt ran as a command in that pane (confirmed live).
        It was never a recovery path either, only a lookalike: a lost name binding is a
        `pane report-agent` we made (`Herdr.report_state`), and an agent whose TUI is not
        there to read a prompt is not there to read typed-in text either.

        So a failed ring is a failed ring. For the doorbell that costs nothing — the
        message is already durable with `delivered_at` NULL, and `flush_pending` re-rings
        it from `undelivered()` on the next `sb` command anyone runs. A `force` ring has no
        such retry worth waiting for, because "later" is precisely what it was refusing, so
        that one raises instead of quietly returning False.
        """
        if who == HUMAN:
            return False
        if self._finished_and_unreachable(who):
            # Nobody is there to hear it: the turn ended and the name no longer binds, so
            # the call can only fail. The guard lives HERE and not at `tell`/`interrupt`
            # because `flush_pending` reaches this method through neither — it re-derives
            # its own work list — and a write-time guard would leave every message already
            # on disk being re-attempted on every `sb` command anyone runs, forever.
            #
            # The message itself is untouched: written, queued, and still there to be
            # found. This skips the announcement, not the mail.
            store.log_event(self.db, kind="ring_skipped", agent=who, reason="finished")
            if force:
                # `interrupt` refuses this in plainer words before it gets here, so this
                # is the backstop for any future forced ring: force must never quietly
                # return False, because "later" is exactly what it was refusing.
                raise Undeliverable(who, HerdrError(
                    "agent_finished", "it reported done and holds no live pane"))
            return False
        if not force and not answer and self._is_blocked(who):
            # Not idle — waiting on a person. Announcing anything else would cancel the
            # block (see `_unblock_if_needed`) and bury the answer it is waiting for.
            store.log_event(self.db, kind="ring_held", agent=who, reason="blocked")
            return False
        if not force and self._busy(who):
            store.log_event(self.db, kind="ring_deferred", agent=who)
            return False
        if answer:
            self._unblock_if_needed(who)
        try:
            self.h.prompt(who, text)
        except HerdrError as e:
            store.log_event(self.db, kind="ring_failed", agent=who, error=str(e),
                            reason=("name_binding_lost" if self._binding_lost(who, e)
                                    else None))
            if force:
                raise Undeliverable(who, e) from e
            return False
        store.mark_delivered(self.db, who)
        return True

    def _binding_lost(self, who: str, e: HerdrError) -> bool:
        """Did that ring fail because herdr has lost the agent's NAME, not the agent?

        The distinct failure this exists to name: herdr can stop answering to a live
        agent's name — `agent prompt` says `agent_not_found`, a pane-targeted one says
        `agent_not_ready` — while the agent itself is still sitting in its pane with real
        work in it, and nothing re-registers the name. Filed as `2026-08-09-004626`.
        Nothing can ring it again, so its mail queues forever.

        The cause is ours and is now known: a `pane report-agent` on the pane evicts the
        named agent (`Herdr.report_state` measures it). `block` and `_unblock_if_needed`
        used to make that call, which is what made blocking a one-way door; they no longer
        report anything. `Broker.done` still does, so this remains reachable — for an agent
        that has just said it is finished, which is the case `_finished_and_unreachable`
        already covers.

        Told apart from an agent that has simply died by asking herdr twice, in two
        different ways: `agent prompt` refuses the name, and `agent list` — asked fresh,
        after the failure, not from the cache this process may have filled minutes of
        subprocess time ago — still HAS the name. Both at once is the signature, and it is
        the one the bug report recorded (`sb status still shows the row as alive/idle`).
        An agent whose process really has gone drops out of the list, and one herdr cannot
        be asked about at all (`None`) is not evidence of anything.

        This only names it. It cannot fix it: the binding lives in herdr, which is a
        separate binary. What it buys is that a sender is told the doorbell will never
        ring rather than "mid-turn, will be rung when free" — see `unreachable`.
        """
        if e.code not in ("agent_not_found", "agent_not_ready"):
            return False
        a = store.get_agent(self.db, who)
        if a is None or a["state"] in FINISHED:
            return False
        self._alive_cache = None            # ask again, now: the failure is the news
        self._alive_unknown = False
        states = self._agent_states()
        return states is not None and who in states

    def unreachable(self, who: str) -> Optional[str]:
        """The doorbell's last word on this agent, if it was "this will never ring".

        Read from the event log rather than a column on the row, because it is an
        observation and not a state — and disproved by a later DELIVERY rather than by an
        event of its own. A successful ring deliberately writes nothing to the log: those
        rows are `status._last_activity`'s idea of an agent having done something, and a
        doorbell is somebody else acting, so logging one would reset the idle clock on
        exactly the silent agent a person is trying to spot.

        `sb tell` uses it to stop promising delivery it cannot make.
        """
        failed = None
        for row in store.recent_events(self.db, agent=who, limit=EVENT_SCAN):
            if row["kind"] != "ring_failed":
                continue
            payload = json.loads(row["payload"]) if row["payload"] else {}
            if payload.get("reason") != "name_binding_lost":
                return None                        # the newest failure was something else
            failed = (row["created_at"], payload)
            break
        if failed is None:
            return None
        landed = self.db.execute(
            "SELECT MAX(delivered_at) t FROM messages WHERE to_agent=?", (who,)
        ).fetchone()["t"]
        if landed is not None and landed >= failed[0]:
            return None                            # a later ring got through after all
        return failed[1].get("error") or "herdr no longer answers to its name"

    def _is_blocked(self, who: str) -> bool:
        """Is this agent stopped waiting on a person, per our own store?

        Our store and not herdr, because `block` reports nothing to herdr at all (see
        there — a report would cost the agent its name), so herdr cannot tell a blocked
        agent from an idle one and this is the only place the difference is recorded.
        """
        a = store.get_agent(self.db, who)
        return bool(a and a["state"] == "blocked")

    def _unblock_if_needed(self, who: str) -> None:
        """Clear a block, because the human has answered it. Only that.

        Called from `_ring` for an `answer=True` ring and nowhere else. It used to run
        before EVERY delivery, which is what let a sibling's ordinary mail cancel a block.

        Store-only, and deliberately: this runs one line before the doorbell, on an agent
        whose name MUST still bind. It used to push herdr `working` here, on the reading
        that a report re-registers the name — it does the opposite, and this was the second
        of the two calls that made blocking a one-way door. Any `pane report-agent` evicts
        the pane's named agent for good; see `block` for the measurement. Pushed here it
        evicted the name in the same breath as the ring that needed it, so the human's
        answer failed with `agent_not_found` on the line below while the block cleared
        anyway — the block row went away and the answer never arrived.

        Nothing needs the report. herdr's detector marks the pane working of its own accord
        the moment the prompt lands, and our store is where "no longer blocked" is read
        from (`_is_blocked`, `sb status --needs-me`).
        """
        a = store.get_agent(self.db, who)
        if not a or a["state"] != "blocked" or not a["pane_id"]:
            return
        store.set_state(self.db, who, "working")
        store.log_event(self.db, kind="unblocked", agent=who)

    def _surface(self, who: str, text: str) -> None:
        try:
            self.h.notify(f"{who}: {text[:NOTIFY_CLIP]}")
        except HerdrError as e:
            store.log_event(self.db, kind="notify_failed", agent=who, error=str(e))

    def _check_integration(self) -> None:
        """Is a conflicting `claude` integration silently eating our state writes?

        `Herdr.check` says it fails "at startup", and nothing calls it at startup: `sb
        doctor` is its only caller, so an installed integration makes every state write
        in every session look successful and be dropped, for as long as it is installed.

        Asked HERE rather than in `main()`, and logged rather than raised. The blast
        radius is `_push_state`, the one place a state write is made, so a process that
        never writes state — `sb status`, `sb log` — should neither pay for a subprocess
        nor be hard-failed by a fault that cannot reach it. Once per process, the way `_alive_cache` and
        `_ws_ids` are once per process, and the flag is set before the call so a herdr
        that is slow or broken costs that price exactly once either way.

        `doctor` keeps `check()` as the loud, deliberate diagnosis it reads as.
        """
        if self._integration_checked:
            return
        self._integration_checked = True
        try:
            self.h.check()
        except HerdrError as e:
            store.log_event(self.db, kind="herdr_check_failed", code=e.code, error=str(e))

    def _push_state(self, a, state: str, message: str = "") -> None:
        if not a or not a["pane_id"]:
            return
        self._check_integration()   # a write is actually about to be attempted
        try:
            self.h.report_state(a["pane_id"], a["name"], state,
                                store.next_seq(self.db, a["name"]), message=message[:NOTIFY_CLIP])
        except StateWriteDropped as e:
            # Loud, because both causes return ok and this is how the board goes stale.
            store.log_event(self.db, kind="state_dropped", agent=a["name"], error=str(e))
        except HerdrError as e:
            store.log_event(self.db, kind="state_failed", agent=a["name"], error=str(e))
