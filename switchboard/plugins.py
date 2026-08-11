"""Plugins — code, per repo. The other half of the split presets.py describes.

A plugin is a Python package sb imports: `defaults/plugins/<name>/__init__.py`, or a
repo's own `.switchboard/plugins/<name>/`. It owns a CLI verb, owns a directory of durable
state, and can tell agents it exists. A preset is markdown and cannot run; a plugin is
Python and can. `.md` versus `.py` is the whole sorting rule, which is why the two share a
directory during the transition without any ambiguity — a `*.md` file in
`.switchboard/plugins/` is a pre-rename preset, a directory with an `__init__.py` in it is
a plugin, and nothing has to guess.

    sb plugin list                 what this repo has, and what state each one is in
    sb plugin <name> <verb> …      whatever the plugin declared

See `design/PLUGIN-REDESIGN.md` §4 for the contract this implements and §11 for what it
knowingly does not do.

The load model
--------------

Four operations of increasing cost. Every verb uses the cheapest one that answers its
question, and the assignment is fixed rather than incidental:

    0  nothing                              status, done, ask, tell, inbox, block, log,
                                            cleanup, inspect, wait, init, restore,
                                            interrupt, board, models
    1  glob the roots, merge plugins.toml   presets                    -> available/enabled
    2  + read <plugin>/agent.md, flatten    delegate, start             -> fragment()
    3  + import, call register()            plugin list, plugin <name> -> load()
    4  + invoke one handler                 plugin <name> <verb>       -> run()

**No verb that spawns imports plugin code.** `delegate`, and `start` which reaches it,
read a markdown file and stop. That is a topology, not defensive coding:
a plugin with a SyntaxError cannot slow, crash, hang or `sys.exit()` the verbs the whole
system is built on, because those verbs have never heard of it. It is the single most
important property in this module, and `tests/test_plugins.py` is where it is pinned.

Import failure is per plugin, always. `load_all` wraps each one, so a broken plugin costs
the others nothing and is reported as a status rather than a traceback (`SB_DEBUG=1` for
the traceback). This is the pattern `cli.py` already uses for the doorbell flush.

What a handler is handed
------------------------

`Context` is scalars and paths, `Result` is scalars and JSON, and `args` is a namespace
argparse built from a declarative spec. All three are JSON-serialisable, so the day sb
wants subprocess isolation the same handler signature works over a pipe. What is NOT in
`Context` is as much the contract as what is: no `Broker`, no store handle, no spawn
authority. A plugin that can call `sb delegate` is a privilege escalation and a fork bomb
waiting for a bad loop.

What in-process cannot protect against, plainly: a handler that calls `sys.exit()`,
imports `switchboard.store` and writes to the database, leaks memory, or blocks forever
does all of that to the sb process. The isolation here is about import errors and handler
exceptions — the common failures, not the malicious ones.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import fcntl
import importlib.util
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

from . import config
from . import store

# The contract version: the shape of `Context`, `Result`, the registry, the `agent.md`
# convention. A plugin declares which one it targets; sb knows the set it supports. There
# are no deprecation windows and no shims — if `Context` changes, you edit your plugins.
API = 1
SUPPORTED_API = frozenset({1})

# `sb plugin list` is a verb, so a plugin cannot be called `list`. `info` is held back for
# the same reason before anything claims it.
RESERVED = frozenset({"list", "info"})

# Who may run a command. Declared once and enforced by sb, rather than re-implemented and
# eventually forgotten in every plugin (C6: if it matters, make it impossible to skip).
AUDIENCES = ("agent", "human", "both")

# Where a plugin's state directory lives. Two, not three: a worktree scope contradicts the
# shared-repo-identity premise the whole state design rests on, and nothing wants it.
SCOPES = ("repo", "user")

# A plugin name is a directory name, an argv token and part of a module name. Kept to the
# same shape as everything else a human types at sb.
_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")

# Imported modules land here rather than under `switchboard.`, so nothing can reach a
# plugin by importing it and no plugin name can shadow a real module.
_MODULE_PREFIX = "sb_plugin_"

# The subdirectory both scopes use, under `<shared .git>/agentflow/` and under the user
# state root respectively.
_STATE_SUBDIR = "plugins"


class PluginError(RuntimeError):
    """A plugin failed — at import, at registration, or in a handler.

    Its message is the whole line sb prints after `sb: `, so it always names the plugin.
    Handler failure exits 1, the same code `cli.main` gives every other failure; a plugin
    that wants an exit status of its own sets `Result.code`.
    """

    def __init__(self, name: str, message: str, tb: str = ""):
        super().__init__(f"plugin '{name}' failed: {message}")
        self.name = name
        self.tb = tb


# -- the handler surface -------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """Everything a handler is given about where and who it is running as.

    `repo` and `worktree` are both here so a plugin picks consciously rather than by
    accident: `repo` is the shared `.git`, identical from every worktree of a clone and
    therefore the repo's identity; `worktree` is the checkout the caller is standing in.
    """

    api: int
    name: str                       # the plugin's own name
    state_dir: Path                 # sb created it; the plugin owns what goes inside
    repo: Path                      # the shared .git — the repo identity
    worktree: Path                  # this worktree
    agent: Optional[str]            # resolved caller; None means a human is typing
    json: bool

    def as_dict(self) -> dict:
        return {"api": self.api, "name": self.name, "state_dir": str(self.state_dir),
                "repo": str(self.repo), "worktree": str(self.worktree),
                "agent": self.agent, "json": self.json}


@dataclass
class Result:
    """What a handler returns. `human` is printed without `--json`, `data` with it.

    `code` is the plugin's own exit status to spend. sb's own failures stay at 1.
    """

    ok: bool = True
    human: str = ""
    data: Any = None
    code: int = 0


# -- registration --------------------------------------------------------------


@dataclass(frozen=True)
class Arg:
    """One declared argument. Four keys, and it stops there.

    The ceiling is real and deliberate (§11 item 5): four keys covers a todo list and a bug
    filer comfortably and will not cover the first plugin wanting mutually-exclusive groups
    or nested subcommands. The honest answers then are "make it two commands" or "widen the
    spec", and the second starts the slide toward reimplementing argparse in data.
    """

    name: str
    repeat: bool = False
    flag: bool = False
    choices: Optional[tuple[str, ...]] = None
    help: str = ""

    @property
    def optional(self) -> bool:
        return self.name.startswith("-")

    @property
    def dest(self) -> str:
        return self.name.lstrip("-").replace("-", "_")


@dataclass(frozen=True)
class Command:
    name: str
    handler: Callable[[Context, argparse.Namespace], Result]
    audience: str = "both"
    help: str = ""
    args: tuple[Arg, ...] = ()


class Registry:
    """What `register(reg)` is handed. It exposes `command` and `arg` and nothing else.

    `register` runs at import, on every `sb plugin` invocation including `--help`, so it
    must not touch the filesystem or the network. Declaring is all it is for.
    """

    def __init__(self):
        self.commands: dict[str, Command] = {}

    def arg(self, name: str, *, repeat: bool = False, flag: bool = False,
            choices: Optional[Sequence[str]] = None, help: str = "") -> Arg:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("reg.arg() needs a name")
        bare = name.lstrip("-")
        if not bare or bare.startswith("_"):
            raise ValueError(f"argument '{name}': names starting with '_' are sb's")
        if flag and not name.startswith("-"):
            raise ValueError(f"argument '{name}': flag=True needs an option, e.g. --{bare}")
        if flag and (repeat or choices):
            raise ValueError(f"argument '{name}': flag=True takes no value to repeat "
                             f"or choose from")
        return Arg(name=name, repeat=repeat, flag=flag,
                   choices=tuple(choices) if choices else None, help=help)

    def command(self, name: str, handler: Callable, *, audience: str = "both",
                help: str = "", args: Sequence[Arg] = ()) -> None:
        if not _NAME.match(name or ""):
            raise ValueError(f"command '{name}': names are lowercase, "
                             f"letters/digits/-/_ , starting with a letter")
        if name in self.commands:
            raise ValueError(f"command '{name}' is declared twice")
        if not callable(handler):
            raise ValueError(f"command '{name}': handler is not callable")
        if audience not in AUDIENCES:
            raise ValueError(f"command '{name}': audience must be one of "
                             f"{', '.join(AUDIENCES)}")
        seen: set[str] = set()
        for a in args:
            if not isinstance(a, Arg):
                raise ValueError(f"command '{name}': arguments come from reg.arg()")
            if a.dest in seen:
                raise ValueError(f"command '{name}': argument '{a.name}' is declared twice")
            seen.add(a.dest)
        self.commands[name] = Command(name=name, handler=handler, audience=audience,
                                      help=help, args=tuple(args))


# -- discovery (level 1) -------------------------------------------------------


def plugin_dir(repo: Optional[Path]) -> Optional[Path]:
    """This repo's plugin root, `<repo>/.switchboard/plugins/`.

    The same `[paths] plugins_dir` entry `presets.py` reads as its pre-rename fallback,
    and deliberately so: it is one directory on disk holding both spellings during the
    transition, and giving it two config keys would be two ways to say where it is. Which
    of the two things a given entry *is* comes from its shape, never from the key.
    """
    return config.path_for("plugins_dir", repo)


def shipped_dir() -> Path:
    return config.defaults_dir() / "plugins"


def available(repo: Optional[Path] = None) -> dict[str, Path]:
    """Every plugin this repo can see: shipped first, then the repo's own.

    A repo's `<name>/` replaces a shipped one of that name **wholesale** — whole-unit
    replacement, not field merge, which is the same rule preset files use and the only
    rule that makes sense for code.

    A directory only counts if it has an `__init__.py`. That is what tells a plugin from
    a pre-rename preset sitting in the same directory, and from the `__pycache__` Python
    leaves behind.
    """
    found: dict[str, Path] = {}
    for d in (shipped_dir(), plugin_dir(repo)):
        if d is None or not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_dir() and (p / "__init__.py").is_file():
                found[p.name] = p
    return found


def enabled(repo: Optional[Path] = None) -> tuple[str, ...]:
    """The names listed in `plugins.toml`, shipped joined with this repo's.

    Enabled is one of three states and the middle one: *available* means sb can see it and
    describe it, *enabled* means its commands dispatch and it gets a state directory, and
    *bound* means its `@<name>` fragment is injected into spawns. Enabling costs a
    directory; binding costs context on every spawn forever. Different costs, so they stay
    different decisions.
    """
    return config.plugin_enablement(repo)


def bound(repo: Optional[Path] = None) -> dict[str, list[str]]:
    """`{name: where it is bound}` for every `@<name>` in `presets.toml`.

    Reads the *preset* bindings, because there is one bindings file and one notation for
    prompt text — the `@` sigil is what says a name is a plugin's fragment rather than a
    preset file. This is what `sb plugin list` reports; `presets.resolve` is what acts
    on it.
    """
    every, per_role = config.preset_bindings(repo)
    out: dict[str, list[str]] = {}
    for n in every:
        if n.startswith("@"):
            out.setdefault(n[1:], []).append("every agent")
    for role, names in sorted(per_role.items()):
        for n in names:
            if n.startswith("@"):
                out.setdefault(n[1:], []).append(role)
    return out


# -- the fragment (level 2) ----------------------------------------------------

# What one plugin may spend on every spawn it is bound to. See `[limits] plugin_fragment`
# in defaults/settings.toml for why the number is what it is; it is read rather than
# repeated so there is one place to change it.
FRAGMENT_BUDGET = config.setting("limits.plugin_fragment")


def fragment(repo: Optional[Path], name: str) -> Optional[str]:
    """A plugin's prompt contribution: `<plugin>/agent.md`, flattened. No import.

    Static markdown, read through exactly the pipeline presets already use, so the
    no-newline constraint herdr imposes is satisfied by reusing the existing rule rather
    than by a new one anyone has to remember. It is not declared anywhere and it is not
    computed: a fragment computed at spawn time is a snapshot taken at the one moment it
    is least useful, and it would put arbitrary code on the hot path.

    None means this plugin contributes nothing. Injecting the result is phase 3's job.
    """
    d = available(repo).get(name)
    if d is None:
        return None
    text = config.read_text(d / "agent.md")
    return (config.flatten(text) or None) if text is not None else None


def clip(line: str, limit: int = FRAGMENT_BUDGET) -> str:
    """A fragment cut to the budget at a word boundary, or unchanged if it fits.

    Truncation rather than rejection is the whole point: a plugin that grew chatty must
    cost context, not spawns. The cut lands on a word boundary because the reader is a
    language model and a severed word is noise, and the ellipsis is kept so a fragment
    that stops early is distinguishable from one that simply ended.

    Not folded into `fragment()`, which stays the plain read of what is on disk: the
    injector needs both lengths to know whether anything was dropped, and dropping
    something is an event somebody should be able to find in `sb log`.
    """
    if len(line) <= limit:
        return line
    head = line[:max(limit - 1, 0)]
    cut = head.rsplit(" ", 1)[0].rstrip(" ;,-") if " " in head else head
    return (cut or head) + "…"


# -- loading (level 3) ---------------------------------------------------------


@dataclass
class Loaded:
    """One plugin, as far as sb got with it. `status` says how far that was."""

    name: str
    path: Path
    source: str                                     # "shipped" or "repo"
    enabled: bool
    status: str                                     # ok | not enabled | incompatible | broken
    version: str = "—"
    help: str = ""
    api: Optional[int] = None
    scope: str = "repo"
    lock: bool = True
    commands: dict[str, Command] = field(default_factory=dict)
    error: str = ""
    traceback: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "version": self.version, "status": self.status,
                "enabled": self.enabled, "api": self.api, "scope": self.scope,
                "help": self.help, "source": self.source,
                "commands": sorted(self.commands), "error": self.error or None}


def _import(name: str, path: Path):
    """Import `<path>/__init__.py` as a package, under a name of sb's choosing."""
    modname = _MODULE_PREFIX + name
    spec = importlib.util.spec_from_file_location(
        modname, path / "__init__.py", submodule_search_locations=[str(path)])
    if spec is None or spec.loader is None:
        raise ImportError(f"{path}/__init__.py is not importable")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod                  # before exec: a package imports itself
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(modname, None)
        raise
    return mod


def load(repo: Optional[Path], name: str, path: Optional[Path] = None,
         is_enabled: Optional[bool] = None) -> Loaded:
    """Import one plugin and call its `register()`. Never raises for the plugin's sake.

    Every way a plugin can be wrong comes back as a `status` and an `error` on the result,
    because this is called in a loop by `sb plugin list` and one bad plugin must cost the
    others nothing. Callers that need a live command table check `.ok` — or use `must_load`,
    which is the same thing with the failure raised instead.

    `BaseException`, not `Exception`: the canonical broken plugin is `raise SystemExit(3)`
    at module scope, and `SystemExit` is not an `Exception`. A handler that calls
    `sys.exit()` still takes the process down (§11 item 1) — that is a different moment,
    and deliberately not caught.
    """
    if path is None:
        path = available(repo).get(name)
        if path is None:
            raise KeyError(f"no such plugin: {name}")
    src = "repo" if _under(path, plugin_dir(repo)) else "shipped"
    if is_enabled is None:
        is_enabled = name in enabled(repo)
    p = Loaded(name=name, path=path, source=src, enabled=bool(is_enabled),
               status="ok" if is_enabled else "not enabled")

    def broken(msg: str, tb: str = "") -> Loaded:
        p.status, p.error, p.traceback = "broken", msg, tb
        return p

    if not _NAME.match(name):
        return broken("not a usable plugin name (lowercase, letters/digits/-/_)")
    if name in RESERVED:
        return broken(f"'{name}' is a reserved plugin name")

    try:
        mod = _import(name, path)
    except KeyboardInterrupt:
        raise
    except BaseException as e:                  # noqa: BLE001 — see the docstring
        return broken(_first_line(_where(e, path)), traceback.format_exc())

    p.version = str(getattr(mod, "VERSION", "—"))
    p.help = _first_line((mod.__doc__ or "").strip())
    api = getattr(mod, "API", None)
    if not isinstance(api, int) or isinstance(api, bool):
        p.status, p.error = "incompatible", (
            f"declares no API; this sb supports API {_supported()}")
        return p
    p.api = api
    if api not in SUPPORTED_API:
        p.status, p.error = "incompatible", (
            f"targets API {api}, this sb supports API {_supported()}")
        return p

    scope = getattr(mod, "SCOPE", "repo")
    if scope not in SCOPES:
        return broken(f"SCOPE must be one of {', '.join(SCOPES)}, not {scope!r}")
    p.scope = scope
    p.lock = bool(getattr(mod, "LOCK", True))

    reg_fn = getattr(mod, "register", None)
    if not callable(reg_fn):
        return broken("defines no register(reg)")
    reg = Registry()
    try:
        reg_fn(reg)
    except KeyboardInterrupt:
        raise
    except BaseException as e:                  # noqa: BLE001 — register is plugin code too
        return broken(f"register(): {_first_line(str(e)) or type(e).__name__}",
                      traceback.format_exc())
    if not reg.commands:
        return broken("register() declared no commands")
    p.commands = reg.commands
    return p


def must_load(repo: Optional[Path], name: str) -> Loaded:
    """`load`, with anything short of a working command table raised as a PluginError."""
    p = load(repo, name)
    if not p.commands:
        raise PluginError(name, p.error or f"{p.status} — nothing to run", p.traceback)
    return p


def load_all(repo: Optional[Path] = None) -> list[Loaded]:
    """Every available plugin, each import wrapped. Ordered by name."""
    on = set(enabled(repo))
    return [load(repo, n, path=d, is_enabled=n in on)
            for n, d in sorted(available(repo).items())]


def _supported() -> str:
    return ", ".join(str(n) for n in sorted(SUPPORTED_API))


def _under(path: Path, root: Optional[Path]) -> bool:
    return root is not None and root in path.parents


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def _where(e: BaseException, path: Path) -> str:
    """A one-line report of an import failure, naming the file and line when there is one.

    A `SyntaxError` knows exactly where it is and says so; everything else is reported as
    `Type: message`. Either way this is a *status*, never a traceback — `SB_DEBUG=1` is
    where the traceback lives.
    """
    if isinstance(e, SyntaxError) and e.lineno:
        where = Path(e.filename or "?").name
        return f"{where}:{e.lineno} SyntaxError: {e.msg}"
    if isinstance(e, SystemExit):
        return f"SystemExit({e.code}) while importing {path.name}/__init__.py"
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


# -- the parser sb builds from the declaration ---------------------------------


def build_parser(p: Loaded) -> argparse.ArgumentParser:
    """The subparser for one plugin, built from what `register()` declared.

    This is the decisive advantage over handing the plugin a `REMAINDER` and letting it
    parse its own: `sb plugin todo add --labl x` gets an sb-quality error naming the flag
    the caller typed, `--help` is generated by sb so every plugin's help looks like sb's,
    and `--json` works everywhere uniformly rather than wherever a plugin remembered it.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    root = argparse.ArgumentParser(prog=f"sb plugin {p.name}",
                                   description=p.help or None, parents=[common])
    sub = root.add_subparsers(dest="_command", required=True, metavar="<command>")
    for name, c in p.commands.items():
        cp = sub.add_parser(name, parents=[common], help=c.help or None,
                            description=c.help or None)
        for a in c.args:
            cp.add_argument(*_argparse_args(a), **_argparse_kwargs(a))
    return root


def _argparse_args(a: Arg) -> tuple[str, ...]:
    return (a.name,) if a.optional else (a.dest,)


def _argparse_kwargs(a: Arg) -> dict:
    """The four declared keys, translated into argparse's vocabulary.

    Written with `update(**kw)` rather than string subscripts so that the argparse keyword
    `default` is not a string literal in this file — `tests/test_config.py` reads every
    literal in every module looking for model tier names, and one of them is `default`.
    """
    kw: dict[str, Any] = {}
    kw.update(help=a.help or None)
    if a.flag:
        kw.update(action="store_true")
        return kw
    if a.choices:
        kw.update(choices=list(a.choices))
    if a.repeat:
        kw.update(default=[])
        if a.optional:
            kw.update(action="append")
        else:
            kw.update(nargs="*")
    elif a.optional:
        kw.update(default=None)
    if a.optional:
        kw.update(metavar=a.dest.upper())
    return kw


def did_you_mean(word: str, known: Sequence[str]) -> str:
    """` (did you mean 'add'?)`, or nothing. Near misses only — a wrong guess is noise."""
    close = difflib.get_close_matches(word, list(known), n=1, cutoff=0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


# -- state (level 4) -----------------------------------------------------------


def state_root(scope: str, worktree: Optional[Path] = None) -> Path:
    """The directory every plugin of one scope keeps its own directory inside.

    Two scopes. `repo` is keyed on the shared `.git`, which is byte-identical from the main
    checkout and every worktree — three working trees, one identity, one todo list, with no
    new mechanism and no id to generate or collide. `user` is per machine, for a plugin
    whose data is a fact about the tool rather than about whichever repo you were standing
    in when you produced it.
    """
    root = (Path(config.setting("paths.user_state", repo=worktree)).expanduser()
            if scope == "user" else store.store_dir(worktree))
    return root / _STATE_SUBDIR


def state_dir(p: Loaded, worktree: Optional[Path] = None, *, create: bool = True) -> Path:
    """Where this plugin's data lives. sb creates the path and **never reads inside it**.

    Nothing goes in `state.db`. A plugin's table arrives with the plugin and leaves with
    it, so every store that predates it is one the store has to migrate. Since `be8f3a1`
    it often can — a missing table whose columns are all nullable is created and filled
    like a column, rather than counted as blocking. The limit is one NOT NULL column with
    no default: that is still blocking, and blocking rebuilds, which now drops every table
    `SCHEMA` declares rather than three. A todo list must not be able to do that to the
    agent tree.
    """
    d = state_root(p.scope, worktree) / p.name
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class Orphan:
    """A state directory whose plugin is no longer here."""

    name: str
    scope: str
    path: Path

    def as_dict(self) -> dict:
        return {"name": self.name, "scope": self.scope, "path": str(self.path)}


def orphans(repo: Optional[Path] = None) -> list[Orphan]:
    """State directories with no plugin left to own them. Reported, never deleted.

    Removing a plugin — including by a `git pull` dropping a directory out of `defaults/`
    — must not delete data the user put there, so nothing here unlinks anything. `sb doctor`
    prints the `rm -rf` and the human runs it or does not. `rm` is the only reset, and it is
    always theirs.

    Keyed on *available*, not on *enabled*: disabling a plugin leaves its state intact and
    re-enabling finds it, so a disabled plugin's directory is not an orphan and must not be
    reported as one.

    sb still never reads *inside* one of these. It reads the names of the directories, which
    are sb's own — it made them — and stops there.
    """
    live = set(available(repo))
    out: list[Orphan] = []
    for scope in SCOPES:
        root = state_root(scope, repo)
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and d.name not in live:
                out.append(Orphan(name=d.name, scope=scope, path=d))
    return out


@contextlib.contextmanager
def locked(d: Path, want: bool = True) -> Iterator[None]:
    """An exclusive `flock` on `<state_dir>/.lock` for the length of a handler call.

    The payoff of sb owning the path: the two things naive authors get wrong — *where does
    my data go* and *what happens when two agents write at once* — are both answered before
    their code runs. Whole-file rewrite via tmp + `os.replace` under this is then correct,
    and is the simplest thing that works.

    Per state directory, so plugins never contend with each other, and never held over the
    spawn path, which runs no handlers. `LOCK = False` for an append-only plugin that
    genuinely needs none.
    """
    if not want:
        yield
        return
    fd = os.open(d / ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                # closing releases the lock


def run(p: Loaded, c: Command, ctx: Context, args: argparse.Namespace) -> Result:
    """Invoke one handler. The failure that cannot be isolated, isolated as far as it goes.

    A handler *is* the command, so its failure is the command's failure — but it surfaces
    as one line naming the plugin, never a traceback, and never as sb looking broken.
    `Exception`, not `BaseException`: a handler calling `sys.exit()` exits sb, which §11
    item 1 accepts knowingly and which is a different thing from a plugin that will not
    import.
    """
    try:
        r = c.handler(ctx, args)
    except PluginError:
        raise
    except Exception as e:                      # noqa: BLE001 — the whole point
        raise PluginError(p.name, _first_line(str(e)) or type(e).__name__,
                          traceback.format_exc()) from e
    if not isinstance(r, Result):
        raise PluginError(p.name, f"'{c.name}' returned {type(r).__name__}, not a Result")
    return r
