"""M2 — the herdr adapter.

The only module that knows herdr exists. Everything above it speaks in agents and
messages; everything below is herdr's CLI.

It is also the insurance policy: herdr has one dominant maintainer, so if it goes away
this file is what gets replaced, not the system.

Pinned to **herdr 0.8.0 / protocol 19**. Behaviour here was verified against a live
binary; the comments cite what was learned so the reasoning survives.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import config

# `[herdr]` in defaults/settings.toml — facts about the binary on your PATH, so changing one
# is a claim about that binary rather than a preference.
MIN_VERSION = config.setting("herdr.min_version")

# One source id, forever. Authority is per-source and NOT exclusive — any other source
# can take over — so two ids in our own code would silently fight each other.
SOURCE = config.setting("herdr.source")

# What kind of agent `agent start` starts, and under which permission mode. The CLI's own
# default is manual, under which every agent stalls on its first tool call waiting for a
# human who is not watching.
AGENT_KIND = config.setting("herdr.agent_kind")
PERMISSION_MODE = config.setting("herdr.permission_mode")

# What a worktree is forked from when the caller names no base. `[vocabulary]`, because it
# is the same branch every other layer means by "where work starts".
BASE_BRANCH = config.setting("vocabulary.base_branch")

# Spawn is genuinely flaky: `agent start` fails outright if the pane has not yet reached an
# interactive shell prompt. `[timeouts]` and `[retries]`.
SPAWN_TIMEOUT_MS = config.setting("timeouts.spawn_ms")
SPAWN_ATTEMPTS = config.setting("retries.spawn_attempts")
SPAWN_BACKOFF = config.setting("retries.spawn_backoff")

# The adapter's own ceiling on `agent wait`, and how long it pauses before re-issuing one
# that came straight back without the agent having moved. `agent wait` returns instantly
# when the agent is already in the state asked for, so without the pause the stale-seq
# guard becomes a busy loop over two subprocesses. See `Herdr.wait`.
AGENT_WAIT_MS = config.setting("timeouts.agent_wait_ms")
WAIT_BACKOFF = config.setting("timeouts.agent_wait_backoff")

# Default terminal tail.
READ_LINES = config.setting("display.output_lines")

# How much of a call's stdout/stderr is copied into the event log — this is what a spawn
# failure is diagnosed from, so it is roomier than the rest.
LOG_CLIP = config.setting("limits.herdr_log_clip")
EVENT_CLIP = config.setting("limits.event_clip")

# herdr's four. We do not own a status vocabulary; anything worth surfacing is `blocked`.
IDLE, WORKING, BLOCKED, UNKNOWN = "idle", "working", "blocked", "unknown"
STATES = (IDLE, WORKING, BLOCKED, UNKNOWN)


class StateWriteDropped(RuntimeError):
    """herdr accepted a state write and then ignored it.

    Both known causes return `ok`: a stale/missing --seq, or the bundled agent
    integration owning the pane session. Only a read-after-write catches either.
    """


class HerdrError(RuntimeError):
    """A herdr call failed. Never swallowed — a discarded stderr once cost us the cause
    of a spawn failure, and let an orchestrator quietly do its child's work instead."""

    def __init__(self, code: str, message: str, argv: Sequence[str] | None = None):
        self.code, self.message, self.argv = code, message, list(argv or [])
        super().__init__(f"[{code}] {message}")


@dataclass
class Agent:
    """What herdr hands back when an agent starts."""
    name: str
    pane_id: str
    terminal_id: str = ""        # stable; pane_id is NOT (changes on cross-workspace move)
    session_id: str = ""         # the agent's own session id — identity, restore, transcripts
    workspace_id: str = ""       # where the pane actually IS, straight from herdr
    state: str = UNKNOWN
    change_seq: int = 0          # herdr's global counter. Guards READS, unlike our --seq.
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, d: dict) -> "Agent":
        return cls(
            name=d.get("name") or d.get("agent") or "",
            pane_id=d.get("pane_id", ""),
            terminal_id=d.get("terminal_id", ""),
            session_id=(d.get("agent_session") or {}).get("value", ""),
            workspace_id=d.get("workspace_id", ""),
            state=d.get("agent_status", UNKNOWN),
            change_seq=d.get("state_change_seq") or 0,
            raw=d,
        )


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True)


class Herdr:
    def __init__(
        self,
        binary: Optional[str] = None,
        *,
        runner: Runner = _run,
        on_event: Optional[Callable[..., None]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.binary = binary or shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
        self._run = runner
        self._on_event = on_event  # e.g. store.log_event — every call is recorded
        self._sleep = sleep       # injectable so retry backoff doesn't slow the tests

    # -- plumbing --------------------------------------------------------

    def _call(self, *args: str) -> dict:
        argv = [self.binary, *args]
        t0 = time.time()
        proc = self._run(argv)
        ms = int((time.time() - t0) * 1000)

        payload: dict[str, Any] = {}
        text = (proc.stdout or "").strip()
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {}

        if self._on_event:
            self._on_event(kind="herdr", argv=" ".join(args), ms=ms,
                           rc=proc.returncode, out=text[:LOG_CLIP],
                           err=(proc.stderr or "").strip()[:LOG_CLIP])

        if "error" in payload:
            e = payload["error"]
            raise HerdrError(e.get("code", "unknown"), e.get("message", ""), argv)
        if proc.returncode != 0:
            raise HerdrError(
                "cli_failure",
                (proc.stderr or proc.stdout or "no output").strip()[:300],
                argv,
            )
        # Some commands succeed silently (report-agent, release-agent). Empty output with
        # rc=0 is success, not failure; callers that need data validate it themselves.
        return payload.get("result", payload)

    # -- health ----------------------------------------------------------

    def version(self) -> str:
        p = self._run([self.binary, "--version"])
        return (p.stdout or "").strip().split()[-1] if p.stdout else ""

    def check(self, *, kinds: Sequence[str] = ("claude",)) -> None:
        """Fail loudly at startup rather than mysteriously mid-run."""
        v = self.version()
        if not v:
            raise HerdrError("not_installed", f"herdr not found at {self.binary}")
        if tuple(int(x) for x in v.split(".")) < tuple(int(x) for x in MIN_VERSION.split(".")):
            raise HerdrError("version_too_old", f"herdr {v} < {MIN_VERSION}")
        conflicting = [k for k in kinds if self.integration_installed(k)]
        if conflicting:
            raise HerdrError(
                "integration_conflict",
                "herdr integration(s) installed: " + ", ".join(conflicting) + ". "
                "They claim pane session ownership, which makes herdr SILENTLY reject our "
                "state writes (report-agent still returns ok). Run: "
                + "; ".join(f"herdr integration uninstall {k}" for k in conflicting),
            )

    def integration_installed(self, kind: str) -> bool:
        p = self._run([self.binary, "integration", "status"])
        for line in (p.stdout or "").splitlines():
            if line.strip().startswith(f"{kind}:"):
                return "not installed" not in line
        return False

    # -- topology --------------------------------------------------------

    def create_tab(self, *, cwd: Optional[str] = None, workspace: Optional[str] = None,
                   focus: bool = False) -> str:
        """A tab per agent, in a named workspace.

        NOT a pane split: splits exhaust after ~4 and then return no pane id at all,
        which silently breaks a fan-out mid-round (observed during validation).

        `--workspace` matters more than it looks: without it a tab lands in whatever
        workspace happens to be FOCUSED, so a child can appear in a stranger's workspace
        purely because something called focus recently. (The zsh completion omits this
        flag; the CLI reference documents it.)
        """
        args = ["tab", "create", "--focus" if focus else "--no-focus"]
        if workspace:
            args += ["--workspace", workspace]
        if cwd:
            args += ["--cwd", cwd]
        r = self._call(*args)
        # verified shape: {"root_pane": {"pane_id": ...}, "tab": {...}} — the tab object
        # itself carries no pane_id, only pane_count.
        pane = ((r.get("root_pane") or {}).get("pane_id")
                or (r.get("tab") or {}).get("pane_id")
                or (r.get("pane") or {}).get("pane_id"))
        if not pane:
            raise HerdrError("no_pane", f"tab create returned no pane id: {r}")
        return pane

    def create_workspace(self, label: str, *, cwd: Optional[str] = None,
                         focus: bool = False) -> dict:
        """A fresh workspace with its own root pane.

        No worktree: a top-level orchestrator does no writes, so it needs somewhere to
        live, not a checkout of its own.
        """
        args = ["workspace", "create", "--label", label,
                "--focus" if focus else "--no-focus"]
        if cwd:
            args += ["--cwd", str(cwd)]
        return self._call(*args)

    def split_pane(self, pane_id: str, *, direction: str = "right",
                   ratio: float = 0.38, cwd: Optional[str] = None,
                   focus: bool = False) -> str:
        """Split a pane and return the new pane's id.

        Called by `board.open_beside`, which `_top` calls on every `sb start` —
        this is not spare machinery.

        The ~4-split ceiling that stops `create_tab` using splits for fan-out does
        not bite here: one split, once, in a workspace that never asks for another.
        Anything that fans out still gets a tab.
        """
        args = ["pane", "split", pane_id, "--direction", direction,
                "--ratio", str(ratio), "--focus" if focus else "--no-focus"]
        if cwd:
            args += ["--cwd", str(cwd)]
        r = self._call(*args)
        pane = ((r.get("pane") or {}).get("pane_id")
                or r.get("pane_id")
                or ((r.get("new_pane") or {}).get("pane_id")))
        if not pane:
            raise HerdrError("no_pane", f"pane split returned no pane id: {r}")
        return pane

    def pane_ids(self) -> set[str]:
        """Every live pane id. Lets `_open_board` tell a closed board pane from a
        live one, so `sb start` returns you to one board rather than stacking a new
        one on every run."""
        r = self._call("pane", "list")
        return {p["pane_id"] for p in r.get("panes", []) if p.get("pane_id")}

    def close_pane(self, pane_id: str) -> None:
        self._call("pane", "close", pane_id)

    def create_worktree(self, branch: str, *, base: str = BASE_BRANCH,
                        cwd: Optional[str] = None, label: Optional[str] = None) -> dict:
        """Create a git worktree and open it as a herdr workspace.

        `--cwd` says WHICH REPO. Without it herdr uses the currently focused workspace's
        repo, so a worktree requested from a pane sitting in another project silently
        targets that project instead — surfacing as "fatal: invalid reference: main".

        Note this already opens the checkout as a workspace and groups it with the parent
        repo, so a separate `workspace create` is unnecessary.
        """
        args = ["worktree", "create", "--branch", branch, "--base", base, "--no-focus"]
        if cwd:
            args += ["--cwd", str(cwd)]
        if label:
            args += ["--label", label]
        return self._call(*args)

    def open_worktree(self, *, path: Optional[str] = None, branch: Optional[str] = None,
                      cwd: Optional[str] = None, label: Optional[str] = None) -> dict:
        """Attach to a checkout that already exists, by path or by branch.

        By path is the only way to reach a repo's PRIMARY checkout — git never lets a
        second worktree hold an already-checked-out branch, so `--branch main` cannot
        reach the main checkout itself.
        """
        args = ["worktree", "open", "--no-focus"]
        if path:
            args += ["--path", str(path)]
        elif branch:
            args += ["--branch", branch]
        else:
            raise ValueError("open_worktree needs a path or a branch")
        if cwd:
            args += ["--cwd", str(cwd)]
        if label:
            args += ["--label", label]
        return self._call(*args)

    def rename_workspace(self, workspace_id: str, label: str) -> None:
        self._call("workspace", "rename", workspace_id, label)

    # -- agents ----------------------------------------------------------

    def start_agent(
        self,
        name: str,
        pane_id: str,
        *,
        prompts: Sequence[str] = (),
        kind: str = AGENT_KIND,
        model_args: Sequence[str] = (),
        resume: Optional[str] = None,
        timeout_ms: int = SPAWN_TIMEOUT_MS,
        attempts: int = SPAWN_ATTEMPTS,
    ) -> Agent:
        """Start an agent in an existing pane.

        `agent start` never creates topology, and it fails outright if the pane has not
        yet reached an interactive shell prompt — so we retry with backoff rather than
        return an empty handle. Spawn is genuinely flaky; a silent failure here is what
        makes an orchestrator quietly do its child's work.

        `model_args` arrives already resolved — `ModelSpec.cli_args()` from models.py,
        e.g. `["--model", "opus", "--effort", "high"]`. This module takes flags, never a
        tier name: it used to take `model=` and splice it straight into `--model`, which
        handed the provider CLI the literal string "strong" and dropped effort entirely.
        Resolution belongs to the one file that is allowed to know model names, and the
        adapter stays ignorant of both tiers and providers.
        """
        for p in prompts:
            if "\n" in p:
                # herdr rejects these outright: invalid_agent_argument, "agent arguments
                # cannot be encoded safely for the target shell". Multi-line guidance
                # belongs in CLAUDE.md, which costs nothing per agent anyway (C0).
                raise ValueError(
                    "agent prompts must be single-line; put multi-line guidance in CLAUDE.md"
                )

        agent_args = ["--permission-mode", PERMISSION_MODE]  # manual: agents would stall
        agent_args += list(model_args)
        if resume:
            agent_args += ["--resume", resume]
        for p in prompts:
            agent_args += ["--append-system-prompt", p]

        last: Optional[HerdrError] = None
        for attempt in range(attempts):
            try:
                r = self._call(
                    "agent", "start", name,
                    "--kind", kind, "--pane", pane_id,
                    "--timeout", str(timeout_ms), "--", *agent_args,
                )
                return Agent.from_json(r.get("agent", {}))
            except HerdrError as e:
                last = e
                self._sleep(SPAWN_BACKOFF * (attempt + 1))
        raise HerdrError("spawn_failed", f"after {attempts} attempts: {last}", [name, pane_id])

    def prompt(self, name: str, text: str) -> None:
        """The doorbell. Carries no payload — messages live in the store.

        **This INTERLEAVES. It does not queue.** An earlier note here said the opposite,
        on the strength of a poke that a supposedly-busy agent handled after finishing —
        the agent had in fact already finished. Re-verified against a genuine 60-second
        multi-step turn: the poke was handled at +13s while the running task did not
        complete until +63s. So prompting a working agent injects into the turn it is in
        the middle of, which is why `Broker._ring` holds the doorbell back until the
        target is idle and `sb interrupt` exists as the deliberate exception.

        Its return value reflects state BEFORE the prompt lands, so never infer "it
        started" from it.
        """
        self._call("agent", "prompt", name, text)

    def prompt_pane(self, pane_id: str, text: str) -> None:
        """Deliver to a pane directly, bypassing agent-name resolution.

        herdr can lose an agent's name binding permanently — once it has seen the agent
        leave the foreground (which `sb` running in that pane causes), `agent prompt` and
        even a pane-targeted `agent prompt` answer agent_not_found / agent_not_ready, and
        no later report re-registers it. Pane input does not go through that registry.

        `pane run` types but does not reliably submit into a TUI prompt box, so the
        explicit `enter` is required.
        """
        self._call("pane", "run", pane_id, text)
        self._call("pane", "send-keys", pane_id, "enter")

    def send_keys(self, name: str, *keys: str) -> None:
        """Send raw keys to an agent. `esc` is the canonical spelling for escape.

        This is the only way to CANCEL an agent's turn. `agent prompt` does reach a
        working agent (see `prompt`), but it lands inside the turn rather than replacing
        it, so whatever was already in flight still completes — which is exactly what
        `sb interrupt` is trying to prevent.
        """
        self._call("agent", "send-keys", name, *keys)

    def list_agents(self) -> list[Agent]:
        r = self._call("agent", "list")
        return [Agent.from_json(a) for a in r.get("agents", [])]

    def get_agent(self, name: str) -> Optional[Agent]:
        return next((a for a in self.list_agents() if a.name == name), None)

    def focus(self, name: str) -> None:
        """How a human jumps to a leaf. C14's exemption, already built."""
        self._call("agent", "focus", name)

    def read_pane(self, pane_id: str, *, lines: int = READ_LINES) -> str:
        """`--source recent` is required: the default read of an alt-screen agent shows
        only the empty prompt frame, which looks exactly like 'it did nothing'.

        Raises rather than returning the failure as text. A gone pane is the common case
        — by the time anyone reads a pane to debug it, it has often been closed — and it
        comes back as an error payload on stdout with rc=0, so returning stdout blind
        hands the reader herdr's own error message dressed up as the agent's last words.
        Callers fall back to the transcript on this (see output.py).
        """
        argv = [self.binary, "pane", "read", pane_id, "--source", "recent",
                "--lines", str(lines)]
        t0 = time.time()
        p = self._run(argv)
        text = p.stdout or ""

        if self._on_event:
            self._on_event(kind="herdr", argv=f"pane read {pane_id}",
                           ms=int((time.time() - t0) * 1000), rc=p.returncode,
                           out=text[:EVENT_CLIP], err=(p.stderr or "").strip()[:LOG_CLIP])

        # Only an object that parses AND carries `error` is a failure; real pane output
        # may well start with a brace and must survive unchanged.
        stripped = text.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = {}
            e = payload.get("error") if isinstance(payload, dict) else None
            if e:
                raise HerdrError(e.get("code", "unknown"), e.get("message", ""), argv)
        if p.returncode != 0:
            raise HerdrError(
                "cli_failure", (p.stderr or text or "no output").strip()[:300], argv
            )
        return text

    # -- state authority -------------------------------------------------

    def report_state(
        self,
        pane_id: str,
        name: str,
        state: str,
        seq: int,
        *,
        message: Optional[str] = None,
        session_id: Optional[str] = None,
        verify: bool = True,
    ) -> None:
        """Push authoritative state IN. Never read state out and trust it.

        Two ways to lose a write, both returning success: reusing a seq, or omitting it.
        `seq` therefore comes from the store's strictly-increasing per-agent counter.

        `--agent` is required on EVERY call, not just the first.

        Note `done` cannot be reported — the enum is idle|working|blocked|unknown, and
        herdr derives "done" itself (idle + unfocused). Our store holds the real state.
        """
        if state not in STATES:
            raise ValueError(f"herdr has no state {state!r}; one of {STATES}")
        args = ["pane", "report-agent", pane_id, "--source", SOURCE,
                "--agent", name, "--state", state, "--seq", str(seq)]
        if message:
            args += ["--message", message]
        if session_id:
            args += ["--agent-session-id", session_id]
        self._call(*args)

        if verify:
            # The API lies: both a stale seq and a session-owner conflict return ok.
            # Reading back is the only way to know the write landed.
            got = self.get_agent(name)
            # herdr derives a fifth display state, "done" (= idle and not yet viewed;
            # focusing the pane flips it back to idle). Reporting `idle` and reading back
            # `done` is success, not a dropped write.
            equivalent = {state, "done"} if state == IDLE else {state}
            if got is not None and got.state not in equivalent:
                raise StateWriteDropped(
                    f"{name}: reported {state!r} (seq={seq}) but herdr still says "
                    f"{got.state!r}. Causes: stale/reused seq, or an agent integration "
                    f"owning this pane's session."
                )

    def report_session(
        self, pane_id: str, name: str, session_id: str, seq: int, *, path: Optional[str] = None
    ) -> None:
        """Register an agent's session id under OUR source.

        Needed because the bundled `claude` integration must stay uninstalled: it claims
        pane session ownership, which makes herdr reject our state reports outright
        (silently — report-agent still returns ok). We therefore own both halves.
        The session id comes from the agent itself (`CLAUDE_CODE_SESSION_ID`).
        """
        args = ["pane", "report-agent-session", pane_id, "--source", SOURCE,
                "--agent", name, "--agent-session-id", session_id, "--seq", str(seq)]
        if path:
            args += ["--agent-session-path", path]
        self._call(*args)

    def release_agent(self, pane_id: str, name: str, seq: int) -> None:
        """Hand state authority back to herdr's detector.

        Releases authority ONLY — the agent stays registered and falls back to whatever
        the detector says. Use close_pane() to actually remove it.
        """
        self._call("pane", "release-agent", pane_id, "--source", SOURCE,
                   "--agent", name, "--seq", str(seq))

    # -- waiting ---------------------------------------------------------

    def wait(
        self,
        name: str,
        *,
        until: str = IDLE,
        since_seq: Optional[int] = None,
        timeout_ms: int = AGENT_WAIT_MS,
    ) -> Agent:
        """Block until an agent reaches `until`.

        ONE state, not a set. `agent wait --until` takes a single status: verified against
        0.8.0, `--until idle,blocked` is refused outright ("invalid agent status:
        idle,blocked"), and repeating the flag is accepted but with no sign it means
        "either" rather than last-one-wins. This method used to comma-join a sequence and
        default to `(IDLE, BLOCKED)`, which made its own default argument unusable — every
        call failed instantly, so nothing ever waited. Offering a choice the CLI underneath
        cannot honour is worse than not offering it.

        `agent wait` is also NOT turn-scoped: a previous turn's transition can satisfy it
        instantly. Pass `since_seq` (herdr's `state_change_seq`, snapshotted *before*
        prompting) and we re-wait until the counter has actually advanced past it.
        """
        if until not in STATES:
            raise ValueError(f"herdr has no state {until!r}; one of {STATES}")
        deadline = time.time() + timeout_ms / 1000
        while True:
            remaining = max(1, int((deadline - time.time()) * 1000))
            started = time.time()
            self._call("agent", "wait", name, "--until", until,
                       "--timeout", str(remaining))
            a = self.get_agent(name)
            if a is None:
                raise HerdrError("agent_gone", f"{name} vanished while waiting")
            if since_seq is None or a.change_seq > since_seq:
                return a
            if time.time() >= deadline:
                raise HerdrError("wait_timeout", f"{name} never advanced past {since_seq}")
            # `agent wait --until <state>` returns INSTANTLY when the agent is ALREADY in
            # that state, so the stale-seq guard above can reject the answer as fast as
            # herdr can produce it — two subprocesses per turn of this loop, as fast as
            # they will spawn, for the whole timeout. Measured at 77% of a core for a
            # six-second wait; a default `sb wait` would have done it for fifteen minutes.
            # Sleeping here turns a spin back into a wait. Callers that can pick the state
            # the agent is NOT in should still do so (see status._next_transition) — that
            # makes every block a real one and this backoff a formality.
            if not self._nap(WAIT_BACKOFF, deadline):
                raise HerdrError("wait_timeout", f"{name} never advanced past {since_seq}")

    def _nap(self, seconds: float, deadline: float) -> bool:
        """Sleep, but never past the deadline. -> was there any time left to sleep?"""
        left = deadline - time.time()
        if left <= 0:
            return False
        self._sleep(min(seconds, left))
        return True

    # -- human-facing ----------------------------------------------------

    def notify(self, text: str) -> None:
        """The blocked-leaf shortcut in v0: a leaf surfaces straight to the human,
        bypassing its parent so parent context never grows with blocks (C14, C4)."""
        self._call("notification", "show", text)
