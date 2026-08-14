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
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import config, validate

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

# Our own ceiling on how long the `herdr` BINARY may take to hand control back. Distinct
# from every `--timeout` we pass herdr: those bound herdr's internal waiting, not the
# subprocess. Without this a stuck herdr process hangs `sb` forever — which is what a
# minute-plus `sb delegate` hang turned out to be. `[timeouts]`, same knob every other
# module bounds a `git`/`herdr` call with.
SUBPROCESS_TIMEOUT = config.setting("timeouts.subprocess")

# Spawn is genuinely flaky: `agent start` fails outright if the pane has not yet reached an
# interactive shell prompt. `[timeouts]` and `[retries]`.
SPAWN_TIMEOUT_MS = config.setting("timeouts.spawn_ms")
SPAWN_ATTEMPTS = config.setting("retries.spawn_attempts")
SPAWN_BACKOFF = config.setting("retries.spawn_backoff")

# Delivering an agent's first task. `agent prompt` can paste without submitting, or never
# reach the pane at all, and says nothing either way — so the delivery is confirmed by
# reading the agent back, and re-sent if it was not taken. `[timeouts]` and `[retries]`.
DELIVER_TIMEOUT_MS = config.setting("timeouts.deliver_ms")
DELIVER_POLL = config.setting("timeouts.deliver_poll")
DELIVER_ATTEMPTS = config.setting("retries.deliver_attempts")
# The extra window a send is given when the agent turns out to be running a turn — see
# `_took_prompt`, and the setting, which is where the measurement is written down.
DELIVER_WORKING_MS = config.setting("timeouts.deliver_working_ms")

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


class PromptFileError(RuntimeError):
    """This spawn's system prompt could not be put where the provider CLI will read it.

    Fatal on purpose, and raised before `agent start` is called: the alternative is an
    agent that comes up knowing none of the protocol and says nothing about it.
    """


# -- the prompt file -----------------------------------------------------
#
# Beside the report gate's settings file, under the shared `.git` (`store.store_dir`), for
# the reasons that put THAT file there: never in a worktree, never near `~/.claude`, and
# shared by every worktree of the repo. Keyed by agent name — one file per agent, rewritten
# on a respawn of the same name — and taken away with the rest of that agent's state when
# `sb cleanup` closes it.

PROMPT_DIRNAME = "prompts"


def prompt_file_path(name: str, cwd: Optional[Path] = None) -> Path:
    """Where `name`'s system prompt lives. Never joins an unchecked name onto a path."""
    if not validate.AGENT_NAME.fullmatch(name or ""):
        raise PromptFileError(f"refusing to write a prompt file for {name!r}: not an agent name")
    from . import store                       # see `start_agent` — the store stays off
    return store.store_dir(cwd) / PROMPT_DIRNAME / f"{name}.txt"    # this module's import


def write_prompt_file(name: str, text: str, cwd: Optional[Path] = None) -> Path:
    """Write it, prove it reads back, and return the path. Raises rather than half-do it.

    Tmp-then-rename, as the settings file does and for the same reason: spawns race here,
    and a half-written file is a `claude` that either refuses to start or starts on half a
    protocol. The read-back is not ceremony — the whole point of this file is that nothing
    downstream checks it, so this is the only place the prompt's arrival can be asserted
    at all. `agent start` will not tell us: a prompt file it cannot read is the provider's
    problem, and the provider's answer is to come up anyway.
    """
    p = prompt_file_path(name, cwd)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        got = p.read_text(encoding="utf-8")
    except OSError as e:
        raise PromptFileError(f"could not write {name}'s system prompt to {p}: {e}") from e
    if got != text:
        raise PromptFileError(
            f"{name}'s system prompt did not survive being written to {p}: "
            f"wrote {len(text)} characters, read back {len(got)}"
        )
    return p


def forget_prompt_file(name: str, cwd: Optional[Path] = None) -> None:
    """Take it away with the agent. Never raises — a close that half-happened is worse.

    Called where the pane is closed, not after `agent start` returns: the file is the
    agent's, for as long as the agent has a pane. Deleting it the moment the process was
    up would save nothing and would bet on a provider that never re-reads it.
    """
    try:
        prompt_file_path(name, cwd).unlink(missing_ok=True)
    except Exception:                # noqa: BLE001 — not in a repo, gone already, bad name
        pass


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
    # Whether `name` came from herdr's NAME BINDING or from the fallback below. They are
    # not the same fact and one caller depends on the difference: a bound row is
    # `{"agent": "claude", "name": "w2"}` and herdr answers `agent get w2`; an agent whose
    # binding has been evicted lists as `{"agent": "w2"}` with no name at all, and herdr
    # answers `agent_not_found` for it. Both yield `name="w2"` here, so a predicate asking
    # "does herdr still know this name?" off `name` alone reads the fallback as proof of
    # the very binding it is trying to detect the loss of (`Broker._finished_and_unreachable`).
    #
    # True by default because an Agent built by hand rather than parsed — every one of them
    # is constructed FROM a name — is bound by construction. Only `from_json` can find out
    # otherwise, and it is the only thing in the package that builds these from herdr.
    bound: bool = True
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, d: dict) -> "Agent":
        return cls(
            name=d.get("name") or d.get("agent") or "",
            bound=bool(d.get("name")),
            pane_id=d.get("pane_id", ""),
            terminal_id=d.get("terminal_id", ""),
            session_id=(d.get("agent_session") or {}).get("value", ""),
            workspace_id=d.get("workspace_id", ""),
            state=d.get("agent_status", UNKNOWN),
            change_seq=d.get("state_change_seq") or 0,
            raw=d,
        )


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str], *, timeout: float) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)


def _grace(timeout_ms: int) -> float:
    """Our ceiling for a call that carries its own `--timeout`.

    A call that is *supposed* to take ninety seconds must not be killed at ten, so the
    flat ceiling is wrong for `agent start` and `agent wait`: they get whatever deadline
    we already told herdr to honour, plus the ordinary allowance for it to return after
    honouring it. That margin is what distinguishes "herdr timed out and said so" — the
    error we want, since it names the agent and the phase — from "herdr never answered".
    No new knob: both numbers are already `[timeouts]` entries.
    """
    return timeout_ms / 1000 + SUBPROCESS_TIMEOUT


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

    def _spawn(self, argv: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
        """Run the binary under a deadline, and make blowing it a legible failure.

        Every call in this module goes through here, because the failure being prevented
        is not herdr saying no — it is herdr saying nothing, forever, while `sb` waits.
        `subprocess.run` kills the child on timeout, so the process is gone by the time
        this raises; what the caller loses is only whatever herdr had not yet reported.
        """
        try:
            return self._run(argv, timeout=timeout)
        except subprocess.TimeoutExpired:
            what = " ".join(argv[1:]) or self.binary
            if self._on_event:
                self._on_event(kind="herdr", argv=what, ms=int(timeout * 1000), rc=-1,
                               out="", err=f"timed out after {timeout:g}s")
            raise HerdrError(
                "timeout",
                f"`herdr {what}` did not return within {timeout:g}s — the herdr process "
                f"was stuck, not slow; killed it rather than wait for it",
                argv,
            ) from None

    def _call(self, *args: str, timeout: Optional[float] = None) -> dict:
        argv = [self.binary, *args]
        t0 = time.time()
        proc = self._spawn(argv, SUBPROCESS_TIMEOUT if timeout is None else timeout)
        ms = int((time.time() - t0) * 1000)

        payload: dict[str, Any] = {}
        text = (proc.stdout or "").strip()
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {}

        err_text = (proc.stderr or "").strip()
        if self._on_event:
            self._on_event(kind="herdr", argv=" ".join(args), ms=ms,
                           rc=proc.returncode, out=text[:LOG_CLIP],
                           err=err_text[:LOG_CLIP])

        # herdr reports a refusal as the same JSON envelope either way, but writes it to
        # STDERR — `tab create --workspace <gone>` returns rc=1, empty stdout and
        # `{"error":{"code":"workspace_not_found",...}}` on stderr. Reading only stdout
        # turned every such refusal into an opaque `cli_failure` carrying the real code
        # buried in its message, so nothing could branch on it.
        if proc.returncode != 0 and "error" not in payload and err_text:
            try:
                stderr_payload = json.loads(err_text)
            except json.JSONDecodeError:
                stderr_payload = {}
            if isinstance(stderr_payload, dict) and "error" in stderr_payload:
                payload = stderr_payload

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
        p = self._spawn([self.binary, "--version"], SUBPROCESS_TIMEOUT)
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
        p = self._spawn([self.binary, "integration", "status"], SUBPROCESS_TIMEOUT)
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
                   ratio: float = 0.66, cwd: Optional[str] = None,
                   focus: bool = False) -> str:
        """Split a pane and return the new pane's id.

        `ratio` is the share kept by the pane BEING SPLIT, not the share given to
        the new one — measured, not assumed: splitting a 43-row pane at 0.25 left
        the original with 10 rows and the new pane with 33. So a caller that wants
        the new pane small passes a ratio above a half.

        Called by `board.open_beside`, which every spawn reaches — this is not
        spare machinery.

        The ~4-split ceiling that stops `create_tab` using splits for fan-out does
        not bite here: one split per tab, once, and a fan-out is still tabs — each
        child gets its own tab and splits that tab's root pane a single time.
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
        # A git checkout is the other thing in here we do not get to bound: how long
        # `worktree create` takes is a property of the repo, not of herdr being stuck. The
        # flat ceiling would fail a spawn on a big repo, so it gets the same allowance as
        # the other slow setup step rather than a knob of its own.
        return self._call(*args, timeout=_grace(SPAWN_TIMEOUT_MS))

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
        return self._call(*args, timeout=_grace(SPAWN_TIMEOUT_MS))   # checkout, as above

    def rename_workspace(self, workspace_id: str, label: str) -> None:
        self._call("workspace", "rename", workspace_id, label)

    # -- agents ----------------------------------------------------------

    def _prompt_flags(self, name: str, prompts: Sequence[str]) -> list[str]:
        """The system prompt, handed over as a PATH rather than as 12KB of typed argument.

        WHY A FILE. `agent start` types the whole provider command line into the pane's
        shell, and that line used to carry the entire system prompt as one quoted
        argument. A shell that is still running its startup files leaves the tty in
        CANONICAL mode, where the line discipline keeps `MAX_CANON` bytes of a typed line
        and silently discards the rest — **1024 on this machine**, measured exactly:
        8 of 8 fresh panes handed a 12,143-byte line delivered a 1024-byte prefix, and 8
        of 8 handed the real quoted prompt were left sitting on `dquote>` with the quote
        cut open mid-argument. That is the failure Andrew hit starting switchboard in
        another repo.

        The limit is on the CHARACTERS TYPED, not on the argument that results. So the
        line naming a file is ~300 bytes and fits with two thirds to spare, while what
        the process receives is bounded by `ARG_MAX` — 1,048,576 here, about 86× the
        12KB prompt, against the 1024 that used to bound it.

        WHY THE PROVIDER'S OWN FLAG AND NOT `"$(cat …)"`. The neutral form would be
        better and does not survive the layer we spawn through: measured, `herdr agent
        start … -- --append-system-prompt '$(cat <path>)'` shell-QUOTES each agent
        argument, so the substitution never runs and the literal string `$(cat <path>)`
        becomes the agent's system prompt — an agent with no protocol that does not
        complain, which is the worst of the failures available. (Typed straight into a
        shell with `pane run` it expands fine; spawns do not go that way.) Everything
        else in `agent_args` is a Claude Code flag already, so this is no new coupling.

        LOUD, NOT BEST-EFFORT — unlike `stop_hook_args`, which returns [] rather than
        cost a spawn. An unwritable settings file costs enforcement; an unwritable prompt
        file costs the agent its entire protocol, and an agent that does not know what
        `sb done` is looks exactly like one that ignored it.
        """
        if not prompts:
            return []
        # Joined with a space and written whole. ONE source of the prompt, never one flag
        # per fragment: `claude` honours only the LAST `--append-system-prompt` it is
        # given and silently discards the rest — verified as `claude -p …
        # --append-system-prompt "…ALPHA." --append-system-prompt "…BRAVO."
        # --append-system-prompt "…CHARLIE."`, which answers "CHARLIE" and nothing else.
        # That bug made every prompt in `defaults/` a fiction for a while: what each agent
        # actually received was its last preset fragment, with no protocol and no role.
        text = " ".join(prompts)
        return ["--append-system-prompt-file", str(write_prompt_file(name, text))]

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
                # This was herdr's rule, not ours: a newline in an agent ARGUMENT is
                # invalid_agent_argument, "cannot be encoded safely for the target shell".
                # The prompt is no longer an argument — it is a file, and a file may hold
                # anything — so the constraint is now ours alone, and it stays until
                # somebody decides to lift it. Every prompt in `defaults/` is written
                # single-line to satisfy it, `sb presets` reads them back the same way,
                # and quietly allowing newlines here would let one arrive with no test and
                # no reader expecting it. Multi-line guidance still belongs in CLAUDE.md.
                raise ValueError(
                    "agent prompts must be single-line; put multi-line guidance in CLAUDE.md"
                )

        agent_args = ["--permission-mode", PERMISSION_MODE]  # manual: agents would stall
        # The Stop gate, on EVERY spawn and every restore, because this is the one place
        # they all pass through. Asking each call site to opt in would make the one thing
        # that must not be skippable exactly as skippable as the `sb done` it enforces (C6).
        # `--settings` merges into that session alone, so no session we did not start ever
        # sees it — and never `--bare`, which skips hooks outright. Both verified against
        # the CLI; see `hooks.py`. Returns [] rather than raising: a hook is not worth a
        # failed spawn.
        #
        # Imported HERE rather than at the top of the file: `hooks` reaches the store, and
        # `panel` imports this module — a renderer that pulls the store in gets a WAL
        # connection per panel process, which is the cost `test_panel` exists to keep out.
        # A renderer never spawns, so the dependency belongs to the call and not to the
        # module.
        from . import hooks

        agent_args += hooks.stop_hook_args()
        agent_args += list(model_args)
        if resume:
            agent_args += ["--resume", resume]
        # The prompt goes down as a PATH, so the line typed into the pane's shell is ~300
        # bytes rather than 12KB and cannot be cut by MAX_CANON. See `_prompt_flags` for
        # the measurement and for why this raises rather than degrading.
        agent_args += self._prompt_flags(name, prompts)

        last: Optional[HerdrError] = None
        for attempt in range(attempts):
            try:
                r = self._call(
                    "agent", "start", name,
                    "--kind", kind, "--pane", pane_id,
                    "--timeout", str(timeout_ms), "--", *agent_args,
                    # The slow call, legitimately: herdr waits up to `timeout_ms` for the
                    # session to become interactive. Its own timeout usually fires first and
                    # says why; ours only catches a herdr that never answers at all.
                    timeout=_grace(timeout_ms),
                )
                return Agent.from_json(r.get("agent", {}))
            except HerdrError as e:
                last = e
                self._sleep(SPAWN_BACKOFF * (attempt + 1))
        raise HerdrError("spawn_failed", f"after {attempts} attempts: {last}", [name, pane_id])

    def prompt(self, name: str, text: str) -> None:
        """The doorbell. Carries no payload — messages live in the store.

        **This QUEUES. It does not interleave, and it cancels nothing.** The text is
        handed to the model at the next point it can act — the instant the in-flight tool
        call returns — and the call itself runs to completion.

        Measured, three times, against the one test shape that can tell the two apart: a
        single 90-second `Bash` call, prompted ~10s in, watched from outside the agent.
        All three loops wrote all 90 of their lines; all three agents reported seeing the
        text attached to that call's result and
        having no awareness of it during. Literal keystrokes into the pane behaved
        identically, so there is no separate "human-typed" path to prefer.

        This note said the opposite for a while — "INTERLEAVES", on a poke handled at +13s
        inside a turn that ran to +63s. That is what delivery-at-the-next-boundary looks
        like when the turn is several short tool calls rather than one long one; the test
        could not distinguish them, and the conclusion drawn from it was wrong. It is why
        `Broker._ring` held every doorbell back until the target was fully idle, which cost
        one measured message five and a half minutes.

        Cancelling is `send_keys`'s job, not this one — see `tell`'s interrupt mode.

        Its return value reflects state BEFORE the prompt lands, so never infer "it
        started" from it.
        """
        self._call("agent", "prompt", name, text)

    def deliver(
        self,
        name: str,
        text: str,
        *,
        attempts: int = DELIVER_ATTEMPTS,
        timeout_ms: int = DELIVER_TIMEOUT_MS,
        working_ms: int = DELIVER_WORKING_MS,
        proof: Optional[Callable[[float], bool]] = None,
    ) -> None:
        """`prompt`, confirmed — the agent really took the text, or this raises.

        `agent prompt` returns nothing worth reading (see `prompt`), and it has two
        observed silent failure modes: the text is pasted into the prompt box and never
        submitted, or it never arrives at all. Both leave the caller holding a success it
        did not get, which is how a spawn reports a name for an agent that never ran.

        WHAT CONFIRMATION MAY BE. This used to be "herdr's `state_change_seq` for this
        agent moved after we prompted", and that is not a fact about the text: it is a
        fact about herdr's status record, which anything at all can move. Measured, in a
        fresh checkout: `agent start` returns with the pane already `interactive_ready`
        while Claude Code is still showing its *workspace trust* dialog. The prompt then
        types into a modal — the text is thrown away and the Enter answers the dialog —
        and dismissing it flips the agent to `blocked` or `done`, i.e. the seq moves, in
        under a second. Three of four spawns in one cold fan-out confirmed exactly that
        way and never ran, with `sb delegate` reporting success for all four. So the old
        test could not tell a delivered task from a swallowed one, and the failure it was
        written to end is the failure it passed on.

        `proof` is what replaces it: a callable given the moment the text was sent, which
        answers whether the AGENT'S OWN record now holds it (see
        `output.task_arrived` — Claude Code appends the submitted text to its session
        transcript about a second after it is entered, and writes nothing at all for a
        prompt eaten by a dialog). Nothing herdr says can fake that.

        With no proof available the fallback demands `state == working`: a turn, not a
        movement. It is weaker — herdr infers `working` from the terminal — but every
        false positive observed was a transition to `blocked`, `done` or `idle`, and none
        of those is a turn starting.

        WHAT A FAILURE HERE MEANS. Not "the agent has no task": only that no send could be
        confirmed. The proof is a file the agent flushes on its own schedule, and it has
        been seen 35 s late under load, so a running agent's task was reported lost —
        which is why `_took_prompt` stretches its window for an agent herdr says is
        working, and why the exception below is worded as a failure to confirm rather than
        as a verdict on the agent. `Broker._spawn` decides what it means.

        The baseline is re-read before EVERY attempt. It used to be snapshotted once,
        before the first, so by a third attempt any unrelated change in the intervening
        minute counted as confirmation of a prompt sent seconds ago.

        A prompt that was not taken is RE-SENT, which is the documented recovery for the
        paste-without-submit mode: the second prompt types and presses enter, carrying the
        stuck text in with it. The cost when the first prompt did land but we could not
        see it is the task arriving twice — a duplicate is recoverable and a silence is
        not. On a cold checkout the first send is lost far more often than not, so a spawn
        routinely pays a full `timeout_ms` before the send that works. That is the price
        of the guarantee, and it is the right way round.
        """
        last = "nothing in the agent's own record ever held the text"
        for attempt in range(attempts):
            before = self._peek(name)
            sent = time.time()
            try:
                self.prompt(name, text)
            except HerdrError as e:
                last = str(e)
            else:
                if self._took_prompt(name, before, timeout_ms, sent=sent, proof=proof,
                                     working_ms=working_ms):
                    return
            if attempt + 1 < attempts:
                self._sleep(SPAWN_BACKOFF)
        # WHAT THIS DOES AND DOES NOT SAY. Only that no send could be confirmed — which is
        # not the same as the agent having nothing, and this used to claim the second.
        # A proof that has not appeared can also be a transcript that has not been flushed,
        # and the caller (`Broker._spawn`) is the one that can go and look at what the
        # agent has done since. Wording it as a verdict is how a working agent came to be
        # recorded `failed` with an instruction to force-close it.
        raise HerdrError(
            "not_delivered",
            f"{name}: the text was sent {attempts} times and none of them could be "
            f"confirmed to have arrived — {last}. Its pane may hold the text unsubmitted, "
            f"be sitting on a dialog that ate it, or hold nothing at all",
            [name],
        )

    def _peek(self, name: str) -> Optional[Agent]:
        """The agent as herdr has it right now, or None if it cannot be asked.

        Never raises: this only ever informs a comparison, and a herdr that cannot answer
        must not turn a delivery that may well have landed into an exception of its own.
        """
        try:
            return self.get_agent(name)
        except HerdrError:
            return None

    def _took_prompt(
        self,
        name: str,
        before: Optional[Agent],
        timeout_ms: int,
        *,
        sent: float,
        proof: Optional[Callable[[float], bool]] = None,
        working_ms: int = DELIVER_WORKING_MS,
    ) -> bool:
        """Did the agent TAKE the prompt? Polled until `timeout_ms` runs out.

        Took it, not merely moved: see `deliver` for what moving turned out to prove.
        `proof` is the only thing that ever answers yes here when it is available; the
        status read is a fallback for an agent whose own record cannot be found, and it
        insists on `working` rather than on any change at all.

        WHY THE WINDOW STRETCHES. The proof is a file the agent writes, and Claude Code
        does not flush its transcript when the text is submitted — under a six-way
        fan-out one was measured 35 s late, against a 20 s window. So "no proof yet" and
        "no task" were the same answer, and a fan-out reported two working agents' tasks
        as lost. Herdr's status cannot confirm the text arrived, but a turn running does
        rule out the case this window is short for: an agent that took nothing does
        nothing. So when the window runs out on an agent herdr says is `working`, it is
        extended ONCE by `working_ms` — not to accept anything weaker, but to give the
        proof time to appear. It usually does, and then this returns for the right reason.

        Herdr is asked only when the window expires, never on the poll: this loop runs
        twice a second and every status read is a subprocess.
        """
        deadline = time.time() + timeout_ms / 1000
        seq = before.change_seq if before else 0
        was_working = before is not None and before.state == WORKING
        stretched = False
        while True:
            if proof is not None:
                if proof(sent):
                    return True
            elif self._running_turn(name, seq, was_working):
                return True
            if not self._nap(DELIVER_POLL, deadline):
                if (proof is None or stretched or working_ms <= 0
                        or not self._running_turn(name, seq, was_working)):
                    return False
                stretched = True
                deadline = time.time() + working_ms / 1000

    def _running_turn(self, name: str, seq: int, was_working: bool) -> bool:
        """Is herdr reporting a turn that started after we prompted?

        `working`, and either newly so or freshly moved. Not "the status changed": every
        false confirmation this path ever produced was a transition to `blocked`, `done`
        or `idle` — a startup dialog being dismissed — and none of those is a turn.
        """
        a = self._peek(name)
        return (a is not None and a.state == WORKING
                and (a.change_seq > seq or not was_working))

    def prompt_pane(self, pane_id: str, text: str) -> None:
        """Run a command in a pane. For FIXED commands only — `text` reaches a shell.

        Named `prompt_pane` because it was once used as a delivery path of last resort:
        herdr can lose an agent's name binding permanently (a `pane report-agent` on the
        pane evicts it — see `report_state`, which is the whole cause; not, as this note
        used to say, `sb` running in the pane and taking the foreground), after which
        `agent prompt` and even a pane-targeted `agent prompt` answer agent_not_found /
        agent_not_ready, and pane input does not go through that registry.
        That use is gone: `pane run` types into whatever shell is sitting in the pane, so a
        backtick or a `$(` in agent-authored text executed there. `Broker._ring` fails
        instead. The one remaining caller passes a literal `exec` line (`board.open_beside`).

        `pane run` types but does not reliably submit into a TUI prompt box, so the
        explicit `enter` is required.
        """
        self._call("pane", "run", pane_id, text)
        self._call("pane", "send-keys", pane_id, "enter")

    def wait_output(self, pane_id: str, match: str, *, timeout_ms: int) -> bool:
        """Did `match` appear in this pane's output within the deadline?

        The read half of `prompt_pane`: a fixed command is typed into a pane, and this is
        how the caller learns whether it did what it was supposed to. Without it a `pane
        run` is a write into the dark — herdr accepts the text whether or not the shell
        was at a prompt to receive it.

        `recent-unwrapped` rather than the default, because the thing being matched is
        usually a path and a wrapped line splits one in half at the terminal's width.

        Never raises. A miss is an answer, not a failure — herdr reports the deadline
        expiring as an error, and every caller here wants a yes/no.
        """
        try:
            self._call("pane", "wait-output", pane_id, "--match", match,
                       "--source", "recent-unwrapped", "--timeout", str(timeout_ms),
                       timeout=_grace(timeout_ms))
        except HerdrError:
            return False
        return True

    def send_keys(self, name: str, *keys: str) -> None:
        """Send raw keys to an agent. `esc` is the canonical spelling for escape.

        This is the only way to CANCEL an agent's turn. `agent prompt` does reach a
        working agent (see `prompt`), but it queues behind whatever is in flight, which
        still completes — and completing is exactly what `tell --interrupt` is trying to
        prevent, so it sends `esc` through here first and only then prompts.
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
        p = self._spawn(argv, SUBPROCESS_TIMEOUT)
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

        **This costs the agent its name, permanently. Call it only on an agent nobody
        needs to reach again.** `pane report-agent` does not annotate the pane's agent, it
        replaces it: the named agent registered by `agent start` is evicted and a
        source-reported record put in its place, and a reported record is not a target —
        `agent get`/`agent prompt <name>` answer agent_not_found, and a pane-targeted
        prompt answers agent_not_ready ("<pane> is not an active named agent"). Nothing
        undoes it: `release_agent` deletes the record instead of handing detection back
        (the pane then drops out of `agent list` altogether), and `agent start` on the
        live pane refuses agent_pane_busy.

        The state VALUE has nothing to do with it — `idle` evicts exactly as `blocked`
        does; making the call is what evicts. Measured on herdr 0.8.0 against a throwaway
        pane: `agent start` → resolvable, `report_session` → still resolvable, one
        `report_state(..., IDLE)` → agent_not_found for good. This is the mechanism behind
        the "lost name binding" the rest of this file talks about, and it is why nothing in
        the broker calls this any more — `block`, `_unblock_if_needed` and `done` all
        report nothing at all, `done` last, once the price of it turned out to be that a
        finished agent could never be asked a follow-up question. Kept because it is the
        measurement, and because the eviction is invisible without a written record of it;
        a new caller is a new instance of that bug, not a new feature.

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
            if got is None:
                # Gone by the time we read back. After an `idle` report that is the
                # ordinary end of a life — `idle` is what an agent sends moments before
                # it disappears, which is why the line above special-cases it — so a
                # vanish there says nothing and raising on it would fire on every exit.
                # After `working`/`blocked` it is the corruption signal this exception
                # exists for: nothing reaches gone from those without an intervening
                # idle/done, so the write we just made landed nowhere.
                if state != IDLE:
                    raise StateWriteDropped(
                        f"{name}: reported {state!r} (seq={seq}) and herdr no longer "
                        f"knows the agent. The write landed nowhere — the agent went "
                        f"away mid-turn, or an agent integration owns this pane's session."
                    )
            elif got.state not in equivalent:
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
                       "--timeout", str(remaining),
                       # Blocking by design, for as long as we asked it to block.
                       timeout=_grace(remaining))
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
            # six-second wait; a fifteen-minute one would have done it for fifteen
            # minutes. Sleeping here turns a spin back into a wait. Callers that can pick
            # the state the agent is NOT in should still do so — that makes every block a
            # real one and this backoff a formality.
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
