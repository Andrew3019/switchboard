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
agents sharing a checkout) and one directory per agent, rewritten per spawn. It does NOT
go away when `sb cleanup` closes the agent, and that is the one place it differs from the
prompt file — see `forget_home`, which explains what closing is contractually allowed to
cost.

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

# A private TMPDIR inside the home, used only when the home would otherwise sit under
# codex's own temp dir. See `private_tmp` for what that is for.
AGENT_TMP_DIRNAME = "agent-tmp"

# `[codex]` in defaults/settings.toml — facts about the binary on your PATH, so changing
# one is a claim about that binary rather than a preference.
AUTH_FILE = config.setting("codex.auth_file")
SANDBOX_MODE = config.setting("codex.sandbox_mode")
APPROVAL_POLICY = config.setting("codex.approval_policy")
HOOK_TIMEOUT = config.setting("codex.hook_timeout")
HERDR_CONFIG_DIR = config.setting("codex.herdr_config_dir")

# Claude's configured footer leads with model/context/cost, keeps both account windows,
# then identifies the checkout. Codex cannot run a status-line command or draw multiple
# footer rows, so use its native equivalents in that order; unavailable values (notably
# estimated cost on subscription auth) are omitted by Codex itself. The native renderer
# owns the separators, colours, truncation, and responsive layout.
STATUS_LINE = (
    "model-with-reasoning",
    "context-used",
    "estimated-thread-cost",
    "five-hour-limit",
    "weekly-limit",
    "current-dir",
    "git-branch",
)

# The slack between our clock and codex's own timestamps — two clocks not agreeing to the
# second. Written here rather than imported: `output` reaches `store`, and `store` reaches
# this module.
#
# There is deliberately no companion "how many records to read". An earlier version read
# the tail 500, ten times `output.py`'s 50 because codex writes one record per tool call,
# per reasoning step and per token count where Claude Code writes roughly one per message
# — one small task produced 132. But a tail is a window a busy agent can push its own
# submitted prompt out of between the send and the proof, and the cost of that is not a
# missing line: `deliver` re-sends a task it cannot confirm, so the agent does the work
# twice. Scanned whole instead, and streamed rather than buffered, which is also less work
# than the deque was doing — it read every line of the file too, and kept 500 of them.
_CLOCK_SLOP = 5.0


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


def private_tmp(home: Path) -> Optional[Path]:
    """A TMPDIR of the agent's own, or None when the inherited one is already fine.

    Codex REFUSES to extract its own helper binaries when `CODEX_HOME` sits under the
    directory `std::env::temp_dir()` returns — `$TMPDIR`, or `/tmp` when that is unset.
    It says so once, on stderr, and then carries on:

        WARNING: proceeding, even though we could not create PATH aliases:
        Refusing to create helper binaries under temporary dir "/tmp"

    Those aliases are the ONLY copy of `codex-linux-sandbox` there is. Codex ships one
    binary that changes behaviour by argv[0], and the sandbox helper is a symlink to it
    laid down in `$CODEX_HOME/tmp/arg0/codex-arg0XXXXXX/` and put on PATH. Without them
    every sandboxed command dies before it starts, with a message that reads like a
    broken install rather than a refusal:

        bwrap: execvp codex-linux-sandbox: No such file or directory

    That is EVERY command, `sb done` and `sb block` among them, so the agent cannot even
    say what happened. Found live, 2026-08-25, against codex-cli 0.149.1 (bug report
    `2026-08-25-134902`): a QA agent cloned this repo into its scratch directory under
    /tmp, which put the store — and so every per-agent home under it — inside /tmp.

    The switchboard side of that is not a choice we can drop: a codex home belongs beside
    the rest of the store, and where the store is is where the repo is. So give codex a
    temp dir that is NOT an ancestor of the home instead, and let it extract as usual.

    Returns None in the normal case, which is deliberate: a codex agent's TMPDIR is
    otherwise whatever the human's shell says, and pointing it into the store would put
    every temp file any tool writes on the repo's disk — under DrvFs on this machine,
    which is the slow one. Only the checkout that provokes the refusal pays for it.

    Both `/tmp` and an inherited `$TMPDIR` are checked, because the value codex reads is
    the pane shell's and this runs in switchboard's process — the two are normally the
    same, and when they are not, the cost of answering yes too often is one directory.
    """
    roots = {Path("/tmp")}
    if os.environ.get("TMPDIR"):
        roots.add(Path(os.environ["TMPDIR"]))
    try:
        resolved = home.resolve()
    except OSError:                      # a symlink loop; unresolvable is not under /tmp
        return None
    for root in roots:
        try:
            resolved.relative_to(Path(root).expanduser().resolve())
        except (ValueError, OSError):
            continue
        return home / AGENT_TMP_DIRNAME
    return None


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

    # Created here rather than left to first use, because codex adds `$TMPDIR` to the
    # sandbox's writable roots and bwrap refuses to bind a source that is not there —
    # which is the other way an agent loses every command (bug `2026-08-25-134851`).
    tmp = private_tmp(d)
    if tmp is not None:
        try:
            tmp.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise CodexHomeError(
                f"could not create {name}'s private TMPDIR at {tmp}: {e}") from e

    # NO prompts means "leave the standing instructions alone", which is what a RESTORE
    # is: it composes none, because Claude Code's `--resume` brings the whole session back
    # including its system prompt. Codex re-reads `AGENTS.md` every turn instead, so the
    # file has to survive — writing an empty one here would restore an agent into its own
    # context with no protocol at all, which is worse than not restoring it.
    if any(p and p.strip() for p in prompts):
        _write(d / "AGENTS.md", _agents_md(prompts), name)
    _write(d / "config.toml", _config_toml(worktree, model, effort, hooks, cwd), name)
    _link_auth(d)
    return d


def forget_home(name: str, cwd: Optional[Path] = None) -> None:
    """Take the agent's home away. Never raises — a close that half-happened is worse.

    NOT called from `sb cleanup`, and the reason is the whole of the closing contract:
    *closing costs only the pane — session, summary, messages and transcript survive, and
    `sb restore` brings an agent back*. For codex all three of those live in here. The
    rollouts ARE the transcript, and `AGENTS.md` is the standing instructions a resumed
    codex session re-reads every turn — `--resume` brings a Claude session's system prompt
    back with it, and codex's equivalent is this file still being on disk. Deleting it
    would make a cleaned-up codex agent unrestorable and unreadable, which is a different
    contract from the one everything above it is written against.

    So the cost is disk instead, and it is not small: codex writes its own caches and
    sqlite state in here, tens of megabytes per agent. This function is what a caller that
    genuinely means "this agent is gone for good" calls — `sb workspace close`, or a hand
    sweep — and there is deliberately nothing automatic on the other end of it yet.

    The other caller is `Broker._release_name`, and it is the same claim by a different
    route: the name is being handed to a new agent and the row that held the session id
    is going with it, so nothing in the directory is reachable under that name any more.
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


def _writable_roots(cwd: Optional[Path]) -> list[str]:
    """The directories outside its own worktree a codex agent must be able to write to.

    Four, and no more than four. Narrow on purpose: the sandbox is the only risk control
    codex has in this mode (there is no `--ask-for-approval` analogue), so every path
    here is one the agent genuinely cannot work without. The test of a root is the
    INJECTED PROTOCOL: each of these is somewhere that text tells every agent to write.

    * The shared `.git` — the whole of it, not just the `agentflow` store beneath it.
      Two things live there and an agent needs both. The STORE (`<shared .git>/agentflow`)
      holds the database, the prompt files and the hook settings, and an agent in a
      worktree is not standing anywhere near it. And GIT ITSELF: a forked worktree's own
      `.git` is a FILE pointing at `<shared .git>/worktrees/<name>/`, and objects and refs
      are written under `<shared .git>` too — so with only the store writable, `git
      commit` fails with exit 128 on `index.lock`, and so do `git push` and `gh pr
      create`. The protocol's closing instruction is *commit your work, then `sb done`*;
      without this the one thing every worker must do is the one thing it cannot. (Missed
      by the spike because that checkout was under /tmp, which `workspace-write` grants
      anyway.) The `agentflow` subdirectory is covered by this entry, so it is not listed
      separately.
    * The herdr SOCKET's directory. Every `sb` verb that reaches another agent or the
      board goes through the herdr binary, which talks to that socket; a denied write
      there is an agent that can do its work and tell nobody.

      Read from the environment where herdr itself put it, falling back to the documented
      default — the same reasoning as every other fact about the binary on your PATH.
    * The REAL `.switchboard` tree, resolved. In a worktree that name is a SYMLINK to the
      primary checkout's directory, and the sandbox resolves symlinks before it decides —
      so a write to `.switchboard/notes/<agent>-<topic>.md` lands outside the worktree and
      is denied even though the path an agent types is inside it. That is where notes and
      briefs live, and the protocol tells children to write both. Found live, 2026-08-23:
      `apply_patch` on a note failed until the human dropped the sandbox entirely.
      Computed from the worktree TOP rather than `cwd`, which may be a subdirectory; in the
      primary checkout the same computation finds the real directory it already is.
    * The switchboard USER-STATE root — `~/.local/state/switchboard` by default. Every
      user-scope plugin keeps its data under it, `report-bug` included, and the protocol
      tells every agent to file a bug when switchboard itself breaks. Found live in the
      same session: `sb plugin report-bug file` died with `[Errno 1] Operation not
      permitted`, which is an agent that cannot report the very thing stopping it. Granted
      as the whole root rather than one plugin's subdirectory, because the protocol names
      more than one plugin and each keeps its state beside the others.
    """
    roots: list[str] = []
    from . import store
    try:
        roots.append(str(store.repo_root(cwd)))
    except Exception:                    # noqa: BLE001 — not in a repo; codex will say so
        pass
    sock = os.environ.get("HERDR_SOCKET_PATH")
    roots.append(str(Path(sock).expanduser().parent if sock
                     else Path(HERDR_CONFIG_DIR).expanduser()))
    try:
        # Not `.exists()`-guarded: granting the intended location costs nothing and a tree
        # created after the spawn (a first note, a first brief) is still inside the grant.
        roots.append(str((store.worktree_root(cwd) / ".switchboard").resolve()))
    except Exception:                    # noqa: BLE001 — same as above: not in a repo
        pass
    try:
        roots.append(str(Path(config.setting("paths.user_state", repo=cwd))
                         .expanduser().resolve()))
    except Exception:                    # noqa: BLE001 — no config to read is not a spawn
        pass                             # failure; the agent loses report-bug, not its job
    # De-duplicated, order kept: the primary checkout can make two of these the same path,
    # and a repeated root in the TOML is noise in a file a human sometimes reads.
    return list(dict.fromkeys(roots))


def _config_toml(worktree: Optional[str], model: Optional[str], effort: Optional[str],
                 hooks: Mapping[str, str], cwd: Optional[Path]) -> str:
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
        # WHAT `workspace-write` DOES NOT COVER, and every gap here was found by running
        # a real codex agent rather than by reading (the spike, 2026-08-22; two bug
        # reports from a codex agent, 2026-08-23).
        #
        # `writable_roots` — an agent's own worktree is not where switchboard's state is,
        # and one path that looks like it is inside the worktree is not. The store, the
        # prompt files and the hook settings all live under the SHARED `.git`, which for a
        # worktree agent is a different directory entirely; the herdr socket is under the
        # human's config dir; `.switchboard` is a SYMLINK out to the primary checkout, and
        # the sandbox resolves it before deciding; and user-scope plugin state lives under
        # the user-state root. Without these, `sb done` cannot write the store and every
        # herdr call an agent makes fails `PermissionDenied` — observed live: the report
        # landed only because that spike's checkout happened to be under /tmp, and `pane
        # report-agent-session` and `notification show` failed anyway. So an agent can
        # neither be seen nor ring anyone. Nor, once those were fixed, write the note the
        # protocol asks it for or file the bug the protocol tells it to file. See
        # `_writable_roots` for what each of the four is and why it is not optional.
        #
        # `network_access` — off by default in this mode, which is not what
        # `--permission-mode auto` means for a claude agent: no `git fetch`, no `git
        # push`, no `gh pr create`. Work that ships has a default shape and it needs the
        # network.
        #
        # Both keys are inside the settled sandbox choice rather than a widening of it:
        # the decision was "workspace-write, no approval prompts, matching Claude's auto
        # posture", and without them an agent cannot do the job that posture assumes.
        "[sandbox_workspace_write]",
        "writable_roots = [" + ", ".join(_s(r) for r in _writable_roots(cwd)) + "]",
        "network_access = true",
        "",
    ]
    if worktree:
        # Absolute and resolved: trust is matched on the path codex itself computes for
        # its cwd, and a worktree reached through a symlinked /tmp is not the same string.
        lines += [f"[projects.{_s(str(Path(worktree).resolve()))}]",
                  'trust_level = "trusted"', ""]
    lines += ["[tui]",
              "status_line = [" + ", ".join(_s(item) for item in STATUS_LINE) + "]", ""]
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

    `TMPDIR` joins it only for a home that would otherwise sit inside codex's own temp
    dir, where codex silently declines to lay down the sandbox helper and every command
    the agent runs dies in bwrap. `private_tmp` is the whole of that story.
    """
    env = {"CODEX_HOME": str(home), "SB_AGENT": name}
    tmp = private_tmp(home)
    if tmp is not None:
        env["TMPDIR"] = str(tmp)
    return env


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


def task_arrived(name: str, text: str, *, since: float,
                 cwd: Optional[Path] = None) -> bool:
    """Has `text` actually been submitted to this agent? — the codex half of the proof.

    `output.task_arrived` answers this for a claude agent by scanning the transcript
    bucket for its cwd, and answers "no" forever for a codex one, whose transcripts are
    somewhere else entirely. Found by the spike: a task that landed on the first send and
    was done in seconds could not be confirmed, so it was re-sent the full three times and
    the agent did it three times over. Idempotent that time; a `git push` would not be.

    Simpler than the claude scan, because the ambiguity it guards against does not exist
    here: `delegate` shares one cwd between a parent and all its children, so THERE the
    only thing that tells siblings apart is the text. A codex agent's rollouts are under a
    home nothing else writes to, so anything found is this agent's — and the text is still
    what is matched, because a rollout exists from the moment the session starts, whether
    or not the prompt reached it.
    """
    d = sessions_dir(name, cwd)
    needle = (text or "").strip()
    if d is None or not needle:
        return False
    floor = since - _CLOCK_SLOP
    for p in d.rglob("rollout-*.jsonl"):
        try:
            if p.stat().st_mtime < floor:
                continue                 # untouched since the send: cheap to skip unread
        except OSError:
            continue
        if _submitted(p, needle):
            return True
    return False


def _submitted(path: Path, needle: str) -> bool:
    """Does this rollout record `needle` being PUT TO the agent?

    Three shapes, because codex records a submitted prompt differently depending on how it
    is being driven, and reading only one of them is a proof that answers "no" forever.
    Found the expensive way: the first version read only the `exec`-mode event, and
    switchboard only ever spawns the TUI, which does not write it.

      - TUI: `event_msg`/`item_completed` carrying an item of type `UserMessage`.
      - `exec`: `event_msg`/`user_message`.
      - the raw model stream underneath both: `response_item`/`message` with role `user`.

    The last of those also carries the injected `AGENTS.md` block, which is why the match
    is on the task TEXT and never on the record's mere existence. The same reasoning rules
    out the assistant's own messages and any shell command that echoes the text.
    """
    try:
        fh = path.open(errors="replace")
    except OSError:
        return False
    with fh:
        for line in fh:
            rec = _record(line)
            if rec is None:
                continue
            text = _submitted_text(rec)
            if text and needle in text:
                return True
    return False


def _record(line: str) -> Optional[dict]:
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None                      # a torn last line on a live session
    return rec if isinstance(rec, dict) else None


def _submitted_text(rec: dict) -> str:
    """The text this record puts TO the agent, or empty for every other record."""
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return ""
    kind, outer = payload.get("type"), rec.get("type")
    if outer == "event_msg" and kind == "user_message":
        return str(payload.get("message") or "")
    if outer == "event_msg" and kind == "item_completed":
        item = payload.get("item") or {}
        if isinstance(item, dict) and item.get("type") == "UserMessage":
            return content_text(item.get("content"))
        return ""
    if outer == "response_item" and kind == "message" and payload.get("role") == "user":
        return content_text(payload.get("content"))
    return ""


def content_text(content) -> str:
    """The text of a codex content list — `text`/`Text` in the item stream,
    `input_text`/`output_text` in the raw model items."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        str(p.get("text") or "") for p in content
        if isinstance(p, dict)
        and str(p.get("type", "")).lower() in ("text", "input_text", "output_text")
    )


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
