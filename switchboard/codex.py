"""M2b — the codex home.

The only module that knows what the `codex` CLI reads. `herdr.py` is the module that
knows herdr exists; this is its counterpart for the one provider whose per-agent settings
do not travel as command-line flags at all.

WHY A DIRECTORY AND NOT FLAGS. Claude Code takes everything switchboard sets per agent as
arguments — `--append-system-prompt-file`, `--model`, `--effort`, `--settings`,
`--permission-mode`. Codex has an equivalent for none of them: there is no
appended-system-prompt flag (every plausible config key answers `unknown configuration
field` under `--strict-config`), and hooks are config-only. What it does have is
`CODEX_HOME` — the directory it reads its own state out of — and pointing that at a
private per-agent directory gives one place for all of it:

    <store>/codex-homes/<agent>/
        AGENTS.md     the composed sb prompt, read as standing instructions EVERY turn
        config.toml   model, reasoning effort, sandbox, hooks, and directory trust
        auth.json     a SYMLINK to the real credential (see `_link_auth`)
        sessions/     where codex then writes this agent's rollout transcripts

This is the same move `herdr.write_prompt_file` already makes for Claude Code — compose
once per agent, write to a private file, point the CLI at it — with a directory in place
of a file. It has the same three properties that file was chosen for: nothing lands in
the repo (so nothing leaks into a human's own codex sessions and nothing collides between
agents sharing a checkout), one file per agent rewritten per spawn, and it goes away with
the agent when `sb cleanup` closes it.

Two differences from the Claude path are worth stating because they are semantic, not
cosmetic:

* **The prompt arrives as a USER message, once per turn** — not as a system prompt once
  per session. Codex injects `AGENTS.md` as a leading user-role message on every turn.
  The text is byte-identical to what a claude agent gets; the authority behind it is not.
* **Newlines are allowed here.** `Herdr.start_agent` refuses a newline in a prompt
  fragment because herdr refuses one in an agent ARGUMENT. Nothing is an argument on this
  path, so the fragments are joined with blank lines rather than spaces and the file reads
  like the markdown it came from.

Everything written here was verified against codex-cli 0.147.0 rather than read: the
config keys parse under `--strict-config`, the hooks fire with arguments, and the auth
symlink is enough to authenticate a turn. The comments say which.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Mapping, Optional, Sequence

from . import config, validate

# The provider name, as `defaults/models.toml` spells it. One place, because three
# modules ask "is this spec a codex one?" and a string typed three times is three
# chances to disagree.
PROVIDER = "codex"

# Beside `prompts/` and `hooks/` under the shared `.git` (`store.store_dir`), for the
# reasons that put those there: never in a worktree, never near the human's own
# `~/.codex`, and shared by every worktree of the repo.
HOMES_DIRNAME = "codex-homes"

# `[codex]` in defaults/settings.toml — facts about the binary on your PATH, so changing
# one is a claim about that binary rather than a preference.
AUTH_FILE = config.setting("codex.auth_file")
SANDBOX_MODE = config.setting("codex.sandbox_mode")
APPROVAL_POLICY = config.setting("codex.approval_policy")
HOOK_TIMEOUT = config.setting("codex.hook_timeout")


class CodexHomeError(RuntimeError):
    """The per-agent home could not be written. Loud, for `_prompt_flags`' reason: an
    agent that never received the protocol looks exactly like one that ignored it."""


def home_path(name: str, cwd: Optional[Path] = None) -> Path:
    """Where `name`'s private CODEX_HOME lives. Never joins an unchecked name onto a
    path — same guard, same reason, as `herdr.prompt_file_path`."""
    if not validate.AGENT_NAME.fullmatch(name or ""):
        raise CodexHomeError(f"refusing to build a codex home for {name!r}: not an agent name")
    from . import store                  # see `herdr.prompt_file_path` — the store stays
    return store.store_dir(cwd) / HOMES_DIRNAME / name      # off this module's import


def is_codex_agent(name: str, cwd: Optional[Path] = None) -> bool:
    """Was this agent spawned onto codex? Asked of the directory, not of the tier.

    The row records a TIER NAME, and a tier's provider is whatever the model table says
    it means TODAY — so re-resolving it later can answer for a tier that has since been
    edited to point somewhere else. The home directory is evidence instead: it exists
    only because a codex spawn wrote it, and it is removed with the agent.
    """
    try:
        return home_path(name, cwd).is_dir()
    except Exception:                    # noqa: BLE001 — bad name, no repo, no store
        return False


# -- writing the home ----------------------------------------------------


def write_home(
    name: str,
    *,
    prompts: Sequence[str],
    worktree: Optional[str],
    model: Optional[str] = None,
    effort: Optional[str] = None,
    hooks: Mapping[str, str] = (),      # event name -> shell command line
    cwd: Optional[Path] = None,
) -> Path:
    """Build (or rebuild) the agent's home and return it. Raises rather than half-do it.

    Everything is rewritten on every spawn, exactly as the prompt file is: the composed
    prompt changes with the role, the presets and the protocol, and a home carried over
    from a previous life of the same name would be a stale one nobody would suspect.

    `sessions/` is deliberately NOT cleared — that is where codex has already written
    this agent's transcripts, and they are what `sb inspect` and `sb restore` read.
    """
    d = home_path(name, cwd)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise CodexHomeError(f"could not create {name}'s codex home at {d}: {e}") from e

    # NO prompts means "leave the standing instructions alone", which is what a RESTORE
    # is: it composes none, because Claude Code's `--resume` brings the whole session back
    # including its system prompt. Codex re-reads `AGENTS.md` every turn instead, so the
    # file has to survive — writing an empty one here would restore an agent into its own
    # context with no protocol at all, which is worse than not restoring it.
    if any(p and p.strip() for p in prompts):
        _write(d / "AGENTS.md", _agents_md(prompts), name)
    _write(d / "config.toml", _config_toml(worktree, model, effort, hooks), name)
    _link_auth(d)
    return d


def forget_home(name: str, cwd: Optional[Path] = None) -> None:
    """Take it away with the agent. Never raises — a close that half-happened is worse.

    Called where the pane is closed, beside `herdr.forget_prompt_file`, and it takes the
    rollout transcripts with it. That is the honest cost of a per-agent home and it is the
    same cost the pane already has: `sb cleanup` is cheap because a closed agent's
    transcript outlives it, and for codex it does not. Anything worth keeping is in the
    agent's `sb done` summary, which is what a parent reads anyway.
    """
    try:
        shutil.rmtree(home_path(name, cwd), ignore_errors=True)
    except Exception:                    # noqa: BLE001 — not in a repo, gone already
        pass


def _write(path: Path, body: str, name: str) -> None:
    """Tmp-then-rename, then read back. Same shape and same reason as
    `herdr.write_prompt_file`: spawns race here, and a half-written file is a codex that
    either refuses to start or starts on half a protocol. Nothing downstream checks these
    files, so this is the only place their arrival can be asserted at all."""
    try:
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
        got = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CodexHomeError(f"could not write {name}'s {path.name} to {path}: {e}") from e
    if got != body:
        raise CodexHomeError(
            f"{name}'s {path.name} did not survive being written to {path}: "
            f"wrote {len(body)} characters, read back {len(got)}"
        )


def _agents_md(prompts: Sequence[str]) -> str:
    """The composed prompt, as the markdown file codex reads every turn.

    Joined with a BLANK LINE rather than a space, which is the one place this path is
    allowed to be nicer than the Claude one: the fragments are flattened to single lines
    upstream only because herdr refuses a newline in an argument, and nothing here is an
    argument. Verified live that a multi-line ~10KB home doc is read to its last line.
    """
    return "\n\n".join(p.strip() for p in prompts if p and p.strip()) + "\n"


def _config_toml(worktree: Optional[str], model: Optional[str], effort: Optional[str],
                 hooks: Mapping[str, str]) -> str:
    """The one file that carries everything switchboard sets per agent for Claude Code as
    flags. Every key here parses under `--strict-config` against codex-cli 0.147.0.

    `sandbox_mode` and `approval_policy` together are the closest thing codex has to
    `--permission-mode auto`, and they are not the same thing: Claude's flag runs a
    model-driven classifier that decides what still needs a human, while codex's risk
    control is the sandbox alone (`codex exec` has no `--ask-for-approval` at all). So
    this is workspace-write with approvals off — an agent that stops for a human who is
    not watching is not safer, it is stalled — and the sandbox is what bounds it.

    `[projects."<worktree>"] trust_level` pre-seeds the directory-trust answer. A private
    CODEX_HOME has never seen this checkout, so without it the TUI opens on its trust
    prompt and every spawn blocks on a question nobody is there to answer. The real
    `~/.codex/config.toml`'s trust entries do not apply — trust is keyed by absolute path
    inside whichever CODEX_HOME is in force.
    """
    lines = [
        "# Written by switchboard for one agent, rewritten on every spawn.",
        "# Not a file to edit: `switchboard/codex.py` is where these values come from.",
        "",
    ]
    if model:
        lines.append(f"model = {_s(model)}")
    if effort:
        lines.append(f"model_reasoning_effort = {_s(effort)}")
    lines += [
        f"sandbox_mode = {_s(SANDBOX_MODE)}",
        f"approval_policy = {_s(APPROVAL_POLICY)}",
        "",
    ]
    if worktree:
        # Absolute and resolved: trust is matched on the path codex itself computes for
        # its cwd, and a worktree reached through a symlinked /tmp is not the same string.
        lines += [f"[projects.{_s(str(Path(worktree).resolve()))}]",
                  'trust_level = "trusted"', ""]
    for event, command in dict(hooks).items():
        # The array-of-matcher-groups shape, same as Claude Code's settings.json hooks
        # block. `matcher = "*"` because every turn of an agent we spawned is ours.
        # Verified live: a `command` string carrying arguments is split and run, and both
        # `Stop` and `UserPromptSubmit` fired with the payload shape `hooks.py` expects.
        lines += [f"[[hooks.{event}]]", 'matcher = "*"', "",
                  f"  [[hooks.{event}.hooks]]",
                  '  type = "command"',
                  f"  command = {_s(command)}",
                  f"  timeout = {int(HOOK_TIMEOUT)}", ""]
    return "\n".join(lines)


def _s(value: str) -> str:
    """A TOML basic string. `json.dumps` is exactly right for this and is not a shortcut:
    TOML basic strings are JSON strings for every escape either format defines, and the
    values here are paths and shell command lines, which is precisely where hand-rolled
    quoting goes wrong."""
    return json.dumps(str(value))


def _link_auth(home: Path) -> None:
    """Point the private home at the real credential — a SYMLINK, never a copy.

    A private CODEX_HOME with no `auth.json` 401s on every request (verified: repeated
    `Missing bearer or basic authentication` on both the websocket and the HTTPS
    fallback). A COPY would be a second credential per agent, going stale the moment the
    human re-logs in and outliving the agent on disk if a teardown ever half-happens.
    The symlink has one owner, and re-login is picked up by every agent at once
    (Andrew, 2026-08-22).

    Best-effort: a missing source is not a reason to fail the spawn here, because the
    failure it would prevent is one codex reports far better itself. `os.symlink` cannot
    replace an existing link, so it is removed first — the target may have moved.
    """
    link = home / "auth.json"
    try:
        source = Path(AUTH_FILE).expanduser()
        link.unlink(missing_ok=True)
        os.symlink(source, link)
    except OSError:
        pass


# -- the spawn --------------------------------------------------------------


def agent_args(resume: Optional[str] = None) -> list[str]:
    """What `codex` itself is started with. Everything else is in the home.

    `--dangerously-bypass-hook-trust` on every spawn, which is a deliberate call and not
    a shortcut (Andrew, 2026-08-22). Codex fails OPEN on an untrusted hook — no error, no
    warning, the turn simply completes as if no `hooks.Stop` existed — and the only
    non-interactive way found to grant trust is this flag. Switchboard authors the hook
    script itself, exactly as it authors the Claude settings file today, so what is being
    bypassed is a prompt about our own code.

    `--strict-config` because the alternative is worse in the same direction: an
    unrecognised key in a file we wrote is a codex that has moved on, and a silently
    ignored `hooks` block is a `sb done` gate that is not there. Every key we write was
    verified to parse; a spawn that fails loudly on the day one is renamed is the
    behaviour to want.

    `resume` becomes the `resume <id>` SUBCOMMAND rather than a flag — codex has no
    `--resume`. Global options come before the subcommand, per its own usage line.
    """
    args = ["--strict-config", "--dangerously-bypass-hook-trust"]
    if resume:
        args += ["resume", resume]
    return args


def spawn_env(name: str, home: Path) -> dict[str, str]:
    """The environment a codex pane must be created with.

    `CODEX_HOME` is the whole mechanism above, and it has to be in the pane's SHELL: herdr
    types the provider's command line into that shell, so there is no point at which an
    env var could be prefixed onto it. `herdr tab create --env` / `pane split --env` /
    `workspace create --env` all take it, and it survives into the subprocesses codex's
    own shell tool runs — which is where every `sb` verb an agent types actually runs.
    """
    return {"CODEX_HOME": str(home), "SB_AGENT": name}


# -- reading back -------------------------------------------------------------


def sessions_dir(name: str, cwd: Optional[Path] = None) -> Optional[Path]:
    """Where codex writes this agent's rollout transcripts, or None if not a codex agent.

    `$CODEX_HOME/sessions/<yyyy>/<mm>/<dd>/rollout-<iso>-<session-id>.jsonl` — a date
    tree, not the flat `~/.claude/projects/<cwd>/<session-id>.jsonl` bucket, which is why
    `store.transcript_path` cannot simply be pointed at it.
    """
    if not is_codex_agent(name, cwd):
        return None
    d = home_path(name, cwd) / "sessions"
    return d if d.is_dir() else None


def rollout_path(name: str, session_id: str, cwd: Optional[Path] = None) -> Optional[Path]:
    """This agent's transcript for one session id.

    Matched on the id in the FILENAME rather than by reading each file: codex names every
    rollout for the session that wrote it, and the id is the same UUID `CODEX_THREAD_ID`
    and the hook payload's `session_id` carry (cross-checked live, three sessions).
    """
    d = sessions_dir(name, cwd)
    if d is None or not session_id:
        return None
    for p in d.rglob(f"rollout-*-{session_id}.jsonl"):
        return p
    return None


def newest_session_id(name: str, cwd: Optional[Path] = None,
                      *, since: float = 0.0) -> Optional[str]:
    """The id of the most recent rollout this agent has, or None if it has none yet.

    THE FALLBACK, not the primary route. Codex allocates no thread id at `agent start` —
    it writes nothing until the first prompt actually starts a turn — and the clean answer
    is the `session_id` the hook payload carries, which `hooks.claim_session` records the
    moment either hook first fires. This exists for the spawn that got no hooks at all
    (an untrusted hook is silently skipped), because an agent whose session id is never
    recorded cannot be restored for the whole of its life.

    Newest by MTIME rather than by name: the filename's timestamp is the session's start,
    and the interesting file is the one being written to now.
    """
    d = sessions_dir(name, cwd)
    if d is None:
        return None
    best, best_t = None, since
    for p in d.rglob("rollout-*.jsonl"):
        try:
            t = p.stat().st_mtime
        except OSError:
            continue
        if t >= best_t:
            best, best_t = p, t
    if best is None:
        return None
    # `rollout-2026-08-22T17-50-40-01a02c19-22e8-7641-b219-cae9025f4f06` — the id is the
    # last five dash-separated groups, which is the one part of the name that is a UUID.
    parts = best.stem.split("-")
    return "-".join(parts[-5:]) if len(parts) >= 5 else None
