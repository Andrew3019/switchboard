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
import os
import subprocess
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
# Every git we shell out to. A fork waits on `git fetch`, which is a network call and the
# one command here that can hang for as long as a bad connection wants it to.
SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")
# How much of a summary or a reason reaches the event log and a desktop notification.
EVENT_CLIP = config.setting("limits.event_clip")
NOTIFY_CLIP = config.setting("limits.notify_clip")

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
        focus: bool = True, new: bool = False, board: bool = True,
        confirm: Optional[Callable[[list[str]], bool]] = None,
    ) -> str:
        """The one command worth remembering. Everything else, an agent does for you.

        Running more than one top-level orchestrator is legitimate — separate lines of
        work, separate contexts. But re-running `sb start` usually means "take me back",
        so an existing one is reused unless you say otherwise: `--new`, an explicit
        `--name`, or answering yes when asked.

        Each top-level orchestrator gets its OWN herdr workspace, laid over the main
        checkout — see `_top`. Everything it delegates then lands in that workspace, so a
        line of work stays in one findable place. `--new` and `--name` make another
        *workspace over the same checkout*, never another checkout.
        """
        if name:
            return self._top(name, task, focus, board)

        # Two different questions, and conflating them is what made `sb start` say
        # "already running: main, main-2, main-3, main-4, main-5" with only main-6 up.
        # Which name slots are taken is every root ever created — `_next_top_name` reads
        # that off the store itself, and says why. Which orchestrators are actually going
        # is a much smaller set, and that is what the human is shown and taken back to.
        tops = [r["name"] for r in self.db.execute(
            "SELECT name FROM agents WHERE parent IS NULL AND role=? ORDER BY created_at",
            (MAIN,)
        ).fetchall()]
        running = self._running_tops() if tops else []   # no rows, nothing to ask herdr

        if tops and not new:
            # Only worth asking when something really is up. With nothing running there
            # is no "another" to start, and `sb start` means what it usually means: take
            # me back to where I was — restoring it if its pane closed (see `_top`).
            if confirm is not None and running and confirm(running):
                new = True
            elif not new:
                return self._top((running or tops)[-1], task, focus, board)

        return self._top(self._next_top_name(tops), task, focus, board)

    def _running_tops(self) -> list[str]:
        """Top-level orchestrators that could still be going, oldest first.

        Two filters, and the second is why this is not just a query. `live_roots` drops
        the ones that ended; herdr drops the ones that ended without saying so, which
        nothing else can — a row only leaves `working` when the agent itself reports it,
        so a crash, an externally closed pane or a herdr restart leaves one claiming to
        work forever.

        Fails OPEN. An unreachable herdr proves nothing, and here the cost of guessing
        death is the worst one available: a second orchestrator spawned on top of a live
        one. Same rule as `_is_registered` and `status.collect`.
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
        a = store.get_agent(self.db, name)
        if a is not None:
            if not self._alive(name):
                if a["session_id"]:
                    self.restore(name)
                else:
                    # A row with no pane and no session is a husk; replace it rather than
                    # orphan it. Same rule as `_spawn_lead`'s.
                    store.drop_agent(self.db, name)
                    return self._top(name, task, focus, board)
            elif task:
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

        self.delegate(task or self._say("spawn.start_task"), role=MAIN, name=name,
                      cleanup="keep", me=HUMAN, pane=pane,
                      workspace=name, workspace_id=wsid, cwd=str(self.repo))
        store.log_event(self.db, kind="start", agent=name, created=True, workspace=wsid)
        if board:
            # Read the pane back: when create_workspace failed, `pane` here is None
            # and `delegate` fell back to a tab, whose pane only the row knows.
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

    def _next_top_name(self, tops: Sequence[str]) -> str:
        """The next free top-level name.

        Free means *never used*, not merely not-running. `tops` holds the ones that are
        live, which is the right list to offer the human but the wrong one to name
        against: reusing a finished orchestrator's name would file two unrelated agents,
        with two unrelated histories, under one name in the store.
        """
        if not store.get_agent(self.db, MAIN_NAME):
            return MAIN_NAME
        n = 2
        while store.get_agent(self.db, f"{MAIN_NAME}-{n}"):
            n += 1
        return f"{MAIN_NAME}-{n}"

    def _open_board(self, name: str, pane: Optional[str], *,
                    cwd: Optional[str] = None) -> None:
        """Open the human's board beside this orchestrator, unless one is up already.

        The pane id is remembered so re-running `sb start` returns you to a
        workspace with one board rather than stacking a new one every time. If we
        cannot ask herdr what is open we do nothing: a missing board is a minor
        annoyance, two boards is a mess someone has to close by hand.

        `cwd` is where the board's shell lands: the main checkout for `sb start`, and the
        workspace's own checkout for `sb workspace new`. A board that reads the wrong
        checkout's `.switchboard` is worse than no board, because it looks right.

        Never raises. `sb start` must not fail because a view would not open.
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

        A board opens beside the lead only when the lead is an orchestrator. The board is
        the human's window onto agents somebody is running; a worker forked into its own
        worktree runs nobody, so a panel there would be an empty view taking half the
        screen. `board=False` declines it either way, as `sb start --no-board` does.
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

        created = self._spawn_lead(lead, ws, role=role, task=task, me=me, prior=row)
        store.log_event(self.db, kind="workspace_open", agent=lead,
                        workspace=name, created=created)
        if board and role == MAIN:
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
                    me: str, prior) -> bool:
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
        pane = fresh_root or self._tab_for(ws["workspace_id"], ws["path"] or self.repo)
        try:
            self.delegate(task or self._say("spawn.workspace_task"), role=role,
                          name=lead, cleanup="keep", me=me,
                          workspace=ws["workspace"], branch=ws.get("branch"),
                          workspace_id=ws["workspace_id"],
                          cwd=ws["path"] or None, pane=pane)
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

    def _parent_workspace_id(self, me: str, ws: Optional[str]) -> str:
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
        """
        row = store.get_agent(self.db, me) if me != HUMAN else None
        if row is not None and _column(row, "workspace_id"):
            return _column(row, "workspace_id")

        if me != HUMAN:
            try:
                live = self.h.get_agent(me)
            except (HerdrError, AttributeError):
                live = None
            if live is not None and getattr(live, "workspace_id", ""):
                return live.workspace_id

        return os.environ.get("HERDR_WORKSPACE_ID", "") or self._workspace_id(ws)

    def _tab_for(self, workspace_id: str, cwd) -> str:
        """A child belongs in its parent's workspace, not in whatever tab has focus."""
        if workspace_id and _accepts(self.h.create_tab, "workspace"):
            return self.h.create_tab(cwd=str(cwd), workspace=workspace_id)
        return self.h.create_tab(cwd=str(cwd))

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
        """
        names = presets_mod.for_role(self.repo, role, extra)
        return [validate.line(p, "preset text", max_len=validate.MAX_PROMPT)
                for p in presets_mod.resolve(names, self.repo)]

    def _fork_for(self, name: str, *, parent: str) -> Optional[dict]:
        """Give this child a worktree of its own. The branch is the agent's NAME.

        No prefix and no suffix: the name is already unique (`agents.name` is the primary
        key), already legal as a branch, and already short. Anything else would be a
        second identity for the same agent, and two names for one thing is how a workspace
        stops being findable by the one everybody uses.

        An existing branch of that name is REFUSED, not attached to — see `BranchTaken`.

        Everything else that can go wrong is not fatal. A herdr with no `worktree create`,
        a repo that is not a repo, a disk that is full: the child still spawns, in its
        parent's space, and the event log says a fork was wanted and did not happen.
        Refusing to spawn at all would take the whole delegation down with it, and the
        collision refusal above is deliberately the ONE case worth that — because there
        the failure is somebody's existing branch, and reusing it is unrecoverable in a
        way that sharing a checkout is not.
        """
        if self._branch_exists(name):
            raise BranchTaken(name)
        try:
            ws = self._attach_workspace(name)
        except HerdrError as e:
            store.log_event(self.db, kind="fork_failed", agent=name, parent=parent,
                            error=str(e))
            return None
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
        workspace_id: str = "",
        cwd: Optional[str] = None,
        pane: Optional[str] = None,
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
        forked = None
        if inherited and not self.has_worktree(me):
            forked = self._fork_for(name, parent=me)
        if forked:
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
        wsid = workspace_id or self._parent_workspace_id(me, ws)
        pane = pane or self._tab_for(wsid, where)

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
        if not store.claim_agent(
            self.db, name=name, role=role, parent=(None if me == HUMAN else me), task=task,
            cwd=str(where), workspace=ws, branch=branch,
            # Recorded, not re-derived later: this is the id its own children inherit.
            workspace_id=wsid or None, pane_id=pane, cleanup=cleanup or r.cleanup,
        ):
            raise AgentNameTaken(name)

        # `model` is a TIER name (`sb delegate --model strong`), not a model id, and it
        # only overrides which tier — the table still decides what that tier means. The
        # spec goes down as flags, so nothing below here has to know either.
        try:
            agent = self.h.start_agent(
                name, pane, prompts=prompts, model_args=r.spec(model).cli_args()
            )
        except Exception:
            # Give the name back. A claim whose spawn failed would otherwise hold it
            # against every later attempt, and the pane is ours to take away too.
            store.drop_agent(self.db, name)
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
        self.h.prompt(name, task)
        return name

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
                self._ring(t, self._say("notify.mail"))
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

    def done(self, summary: str, *, me: Optional[str] = None) -> None:
        """Report finished. The summary goes to the parent, if there is one.

        A ROOT agent has no parent and the human has no mailbox, so its summary is not
        mail — it is a record. The event log carries it, and that is what the readouts
        show: `sb status` puts it on the done row, `sb inspect` prints it in full, `sb
        log` has it. Nothing is lost by not addressing anybody; a row in a mailbox nobody
        reads was only ever a second copy of this.
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
        if parent:
            # The parent's turn ended while this ran; the poke is what restarts it, so a
            # lazy parent never has to poll (C4, C10).
            self._ring(parent, self._say("notify.child_done"))

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
        a = store.get_agent(self.db, me)
        store.set_state(self.db, me, "blocked")
        # NOT herdr's `blocked`. Reporting it makes the agent permanently un-targetable:
        # the name drops out of `agent list`, `agent get`/`agent prompt` answer
        # agent_not_found, and a pane-targeted prompt answers agent_not_ready. The binding
        # does not come back — herdr has recorded the agent leaving the foreground (`sb`
        # itself ran there), so no later report re-registers it.
        #
        # That badge would cost us the only way back in to the one verb whose entire
        # purpose is "stop and get a human". `idle` is honest — the agent IS idle, waiting
        # — and keeps it reachable. Blocked-ness lives in our store, which is the truth
        # anyway (C5), and reaches you through the notification below.
        self._push_state(a, IDLE, why)
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
                me: Optional[str] = None) -> list[str]:
        """Close agents. With no names, every finished one in the caller's scope.

        Safe to be aggressive: closing costs only the pane. Session, summary, messages
        and the on-disk transcript all survive, and `sb restore` brings the agent back.

        Three gates, and which of them a caller may lift is the whole design:

        - **finished, and no unread mail.** A sweep never lifts these. Closing an agent
          mid-turn would strand whatever it was doing, and discarding unread mail loses a
          message somebody is blocked on.
        - **the role's `cleanup` disposition.** `include_kept` lifts this one, and only
          this one: it says "I mean the keepers too", not "close anything".
        - **everything.** `force` lifts all of it, and is only legal for agents named
          outright — it is the escape hatch for an agent that is genuinely stuck (its
          state never advanced, its name was lost by herdr, it holds mail it can never
          read) and that no sweep can therefore ever reach. Naming it IS the confirmation.
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

        closed = []
        for a in candidates:
            if a["name"] == me:
                continue                      # never close the caller
            if a["ended_at"] and not a["pane_id"]:
                continue                      # already gone
            if not force:
                if a["state"] not in FINISHED:
                    continue                  # only finished agents; --all-idle too
                if store.unread_for(self.db, a["name"], mark=False):
                    continue                  # unread mail would be lost
                # Naming an agent is itself the instruction to close it, so an explicit
                # name lifts the role's disposition exactly as `include_kept` does.
                if a["cleanup"] != "close" and not (include_kept or names):
                    continue
            if dry_run:
                closed.append(a["name"]); continue
            try:
                if a["pane_id"]:
                    self.h.release_agent(a["pane_id"], a["name"], store.next_seq(self.db, a["name"]))
                    self.h.close_pane(a["pane_id"])
            except HerdrError as e:
                store.log_event(self.db, kind="cleanup_failed", agent=a["name"], error=str(e))
                if not force:
                    continue
            store.set_state(self.db, a["name"], "done")
            # The pane is gone, so the row must stop claiming one: the "already gone"
            # guard above is `ended_at and not pane_id`, and a stale id defeated it — a
            # second sweep then retried release/close against a dead pane every time.
            store.update_agent(self.db, a["name"], pane_id=None)
            store.log_event(self.db, kind="cleanup", agent=a["name"], forced=force)
            closed.append(a["name"])
        return closed

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
        # Come back into the workspace it belongs to, not into whichever one has focus.
        ws = workspace or {}
        # What we recorded when it was spawned, before the ambiguous name lookup: a
        # workspace NAME resolves to a checkout, and one checkout can be open in several
        # workspaces, so deriving it would bring the agent back somewhere else.
        wsid = (ws.get("workspace_id") or _column(a, "workspace_id")
                or self._workspace_id(a["workspace"]))
        pane = self._tab_for(wsid, ws.get("path") or a["cwd"] or str(self.repo))
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

        The message still goes in the store, delivered and read, so the instruction is
        durable and shows up in `sb inspect` alongside everything else the agent was told.
        It travelled inline, so there is nothing left to announce.
        """
        me = me or self.whoami()
        # Always lands now — deferring an interrupt would defeat it entirely.
        if stop:
            try:
                self.h.send_keys(name, "esc")
                time.sleep(INTERRUPT_SETTLE)   # let the cancel land before the new one
            except HerdrError as e:
                store.log_event(self.db, kind="interrupt_stop_failed", agent=name, error=str(e))
        mid = store.put_message(self.db, from_agent=me, to_agent=name, kind="tell",
                                body=self._say("notify.interrupt", text=text))
        store.mark_collected(self.db, mid)
        self._ring(name, self._say("notify.interrupt", text=text), force=True)
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

    def _busy(self, who: str) -> bool:
        """Is this agent mid-turn right now, per herdr?

        Unknown reads as not busy: the doorbell this gates is held back for a busy agent,
        and holding it back on a hunch is how mail sits forever with nothing on screen.
        """
        return (self._agent_states() or {}).get(who) == WORKING

    def flush_pending(self, *, refresh: bool = False) -> list[str]:
        """Ring the doorbell for anyone who has mail and is no longer mid-turn.

        Called at the start of every `sb` command (see `cli.main`) and on every pass of
        `ask`'s wait loop, so a deferred message lands as soon as anything at all touches
        the store — which, in a live session, is constantly. The store query is free when
        there is nothing pending; only then do we ask herdr.

        `refresh` discards the per-process view of who is busy. `sb` invocations are short
        enough that the cache cannot go stale inside one, but a blocked `ask` holds the
        same process open for up to fifteen minutes, and there the whole point is to
        notice that the target has since finished its turn.

        This is the stand-in for an events daemon. When one exists it replaces this
        trigger, not the model: deferred-then-delivered stays exactly the same.
        """
        # The human is excluded because they are not an agent and have no doorbell. Nothing
        # is addressed to them any more, but a store written before the human mailbox was
        # removed still holds rows that would otherwise be retried on every command.
        pending = store.undelivered(self.db, exclude=(HUMAN,))
        if not pending:
            return []
        if refresh:
            self._alive_cache = None
            self._alive_unknown = False
        rung = []
        for who in dict.fromkeys(m["to_agent"] for m in pending):
            if self._busy(who):
                continue
            if self._ring(who, self._say("notify.mail")):
                rung.append(who)
        return rung

    def _ring(self, who: str, text: str, *, force: bool = False) -> bool:
        """The doorbell. Carries no payload — the message is in the store.

        Held back while the target is mid-turn: `agent prompt` INTERLEAVES, injecting into
        the current turn rather than queueing after it, so ringing a working agent
        interrupts whatever it was doing. `force` is for interrupt, whose whole purpose is
        to land now.
        """
        if who == HUMAN:
            return False
        if not force and self._busy(who):
            store.log_event(self.db, kind="ring_deferred", agent=who)
            return False
        self._unblock_if_needed(who)
        try:
            self.h.prompt(who, text)
            store.mark_delivered(self.db, who)
            return True
        except HerdrError as e:
            first = e
        # herdr can permanently lose an agent's name binding; pane input still lands.
        a = store.get_agent(self.db, who)
        if a and a["pane_id"]:
            try:
                self.h.prompt_pane(a["pane_id"], text)
                store.mark_delivered(self.db, who)
                store.log_event(self.db, kind="ring_via_pane", agent=who,
                                after=str(first)[:NOTIFY_CLIP])
                return True
            except HerdrError as e2:
                first = e2
        store.log_event(self.db, kind="ring_failed", agent=who, error=str(first))
        return False

    def _unblock_if_needed(self, who: str) -> None:
        """A blocked agent is un-targetable in herdr, by herdr's design.

        Reporting `blocked` drops the name binding: `agent get`/`agent prompt` answer
        `agent_not_found`, and a pane-targeted prompt answers `agent_not_ready`. Sensible
        from herdr's side — a blocked agent is waiting on a human, so nothing should poke
        it programmatically. But it would leave the one verb whose purpose is "stop and
        get a human" with no way back in.

        Pushing `working` re-registers the name, and it is what is actually happening:
        answering a blocked agent IS unblocking it.
        """
        a = store.get_agent(self.db, who)
        if not a or a["state"] != "blocked" or not a["pane_id"]:
            return
        try:
            self.h.report_state(a["pane_id"], who, WORKING,
                                store.next_seq(self.db, who), verify=False)
            store.set_state(self.db, who, "working")
            store.log_event(self.db, kind="unblocked", agent=who)
        except HerdrError as e:
            store.log_event(self.db, kind="unblock_failed", agent=who, error=str(e))

    def _surface(self, who: str, text: str) -> None:
        try:
            self.h.notify(f"{who}: {text[:NOTIFY_CLIP]}")
        except HerdrError as e:
            store.log_event(self.db, kind="notify_failed", agent=who, error=str(e))

    def _push_state(self, a, state: str, message: str = "") -> None:
        if not a or not a["pane_id"]:
            return
        try:
            self.h.report_state(a["pane_id"], a["name"], state,
                                store.next_seq(self.db, a["name"]), message=message[:NOTIFY_CLIP])
        except StateWriteDropped as e:
            # Loud, because both causes return ok and this is how the board goes stale.
            store.log_event(self.db, kind="state_dropped", agent=a["name"], error=str(e))
        except HerdrError as e:
            store.log_event(self.db, kind="state_failed", agent=a["name"], error=str(e))
