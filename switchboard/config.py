"""Configuration, layered — the only module that reads a config file.

Everything switchboard ships as its out-of-the-box behaviour lives in `defaults/` at the
repo root: role definitions, model tiers, plugin bindings, the agent protocol, the spawn
prompts, and every number worth tuning. None of it is in Python any more. A repo adds its
own layer in `<repo>/.switchboard/`, and this module is what joins the two.

    defaults/                 shipped; complete on its own, works with no repo layer at all
    <repo>/.switchboard/      that repo's differences, and only its differences

`defaults/` is not dot-prefixed on purpose: it is the reference copy, meant to be opened
and read and copied from. See `defaults/README.md`.

TOML for structure, markdown for prose. `tomllib` is stdlib, there is no yaml module here,
and a prompt written as a quoted Python string is a prompt nobody wants to edit.

The merge rules
---------------

Three, applied recursively and identically to every file:

1. **Tables merge, key by key.** Overriding one field of a role or a tier leaves the rest
   of that role or tier alone.
2. **Scalars replace.** The override's string, number or boolean wins outright.
3. **Arrays JOIN** — base first, then the override's new items, duplicates dropped, order
   preserved.

Joining is the interesting one, and it is the default because the alternative is a trap: a
repo that adds one plugin binding must not silently lose the shipped ones, and neither
layer can tell whether it is the only one there. When replacing really is what you mean,
say so with a `"!reset"` sentinel as the array's first element.

There is deliberately no way to DELETE a key from the base layer. Removing something you
did not write is how a merge becomes unreadable; override it to something inert instead.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Iterable, Optional

# Point this at another directory to replace the shipped baseline wholesale. The test suite
# uses it; so would anyone shipping a different out-of-the-box configuration to a team.
ENV_DEFAULTS = "SWITCHBOARD_DEFAULTS"

# `defaults/` sits beside the package, at the repo root — see the module docstring for why
# it is not `.defaults`.
_PACKAGE_DEFAULTS = Path(__file__).resolve().parent.parent / "defaults"

# First element of an array in the override layer, meaning "discard what the base had".
# The escape hatch from rule 3; spelled loudly because it is the rule that surprises.
RESET = "!reset"

# Front matter for a markdown config file: TOML between two `+++` fences, then prose. `+++`
# rather than `---`, which is a horizontal rule in markdown and so cannot be told apart
# from content by anything that has not already decided the file has front matter.
_FENCE = "+++"

_COMMENT = re.compile(r"<!--.*?-->", re.S)


class ConfigError(ValueError):
    """A config file says something switchboard cannot use. The message names the file."""


# -- locating ------------------------------------------------------------------


def defaults_dir() -> Path:
    """Where the shipped configuration is."""
    env = os.environ.get(ENV_DEFAULTS)
    return Path(env).expanduser() if env else _PACKAGE_DEFAULTS


def repo_dir(repo: Optional[Path]) -> Optional[Path]:
    """A repo's own config directory, or None if there is no repo in play.

    Its NAME comes from the shipped layer only. It is the directory the repo's settings are
    read from, so letting a repo rename it there would be a file asking to be looked for
    somewhere else.
    """
    if repo is None:
        return None
    return Path(repo) / _shipped_settings()["paths"]["repo_dir"]


def path_for(key: str, repo: Optional[Path] = None) -> Optional[Path]:
    """A `[paths]` entry resolved inside the repo's config directory."""
    d = repo_dir(repo)
    return None if d is None else d / setting(f"paths.{key}", repo=repo)


# -- reading -------------------------------------------------------------------


_toml_cache: dict[tuple, dict] = {}


def read_toml(path: Path) -> dict:
    """Parse a TOML file, or `{}` if it is not there.

    Absence is the normal case — most repos define none of these files — so it is not an
    error. A file that IS there and does not parse is: silently ignoring it would mean the
    repo's settings quietly stop applying, which is worse than a traceback.
    """
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _toml_cache.get(key)
    if hit is None:
        try:
            hit = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e
        except OSError:
            return {}
        _toml_cache[key] = hit
    return hit


_text_cache: dict[tuple, str] = {}


def read_text(path: Path) -> Optional[str]:
    """A config file's raw text, or None if it is not there.

    Cached on the same (path, mtime, size) key as `read_toml`. Config is read on a path a
    lot hotter than it looks — every `Broker` reads the protocol and every role — and none
    of it changes under a process that is not itself editing it. The key means an edit is
    still picked up, which is what keeps the cache invisible to the test suite.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _text_cache.get(key)
    if hit is None:
        try:
            hit = path.read_text()
        except OSError:
            return None
        _text_cache[key] = hit
    return hit


def _signature(d: Path, pattern: str) -> Optional[tuple]:
    """A cache key for a directory of config files: every match, with its mtime and size.

    Stat only, no reads. Cheap enough to do on every lookup, and specific enough that
    adding, editing or deleting one file invalidates the entry.
    """
    if not d.is_dir():
        return None
    try:
        return tuple((f.name, s.st_mtime_ns, s.st_size)
                     for f in sorted(d.glob(pattern)) for s in (f.stat(),))
    except OSError:
        return None


# -- merging -------------------------------------------------------------------


def merge(base: Any, over: Any) -> Any:
    """`over` layered onto `base`, by the three rules in the module docstring.

    Neither argument is mutated: every container on the way down is copied, so a cached
    shipped table can be merged into a hundred times and stay pristine.
    """
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base[k], v) if k in base else _copy(v)
        return out
    if isinstance(base, list) and isinstance(over, list):
        return join(base, over)
    return _copy(over)


def join(base: list, over: list) -> list:
    """Rule 3: arrays join, base first, duplicates dropped, order preserved.

    `["!reset", ...]` in the override discards the base — the one way to say "exactly
    this", which is otherwise unsayable once joining is the default.
    """
    if over and over[0] == RESET:
        return _dedupe(over[1:])
    return _dedupe([*base, *over])


def _dedupe(items: Iterable) -> list:
    out: list = []
    for x in items:
        if x not in out:        # `not in`, not a set: TOML values are not all hashable
            out.append(x)
    return out


def _copy(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _copy(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_copy(x) for x in v]
    return v


# -- markdown ------------------------------------------------------------------


def flatten(text: str) -> str:
    """Markdown on disk, one line on the wire.

    herdr refuses any agent argument containing a newline, which is what forced prompts out
    of files an agent reads and into the system prompt in the first place. So config prose
    is authored wrapped and arrives unwrapped.

    HTML comments go first and go entirely: that is where the notes to whoever edits the
    file live, and those must not be paid for on every spawn. Headings are dropped for the
    same reason. Bullets become `; ` separators rather than running together — an agent
    reading "- do this - do that" as prose has lost the list.
    """
    body = _COMMENT.sub(" ", text)
    body = re.sub(r"^#.*$", "", body, flags=re.M)          # drop headings
    body = re.sub(r"^\s*[-*]\s+", "; ", body, flags=re.M)  # bullets -> separators
    body = re.sub(r"\s+", " ", body).strip()
    return re.sub(r"^;\s*", "", body)


def front_matter(text: str) -> tuple[dict, str]:
    """Split `+++ TOML +++ prose` into its two halves.

    A file with no fence is all prose, which is what makes the shortest possible role — one
    line of prompt, no fields — a legal file.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            head = "\n".join(lines[1:i])
            try:
                return tomllib.loads(head), "\n".join(lines[i + 1:])
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"bad front matter: {e}") from e
    raise ConfigError(f"front matter opened with {_FENCE} and was never closed")


# -- settings ------------------------------------------------------------------


def _shipped_settings() -> dict:
    return read_toml(defaults_dir() / "settings.toml")


def settings(repo: Optional[Path] = None) -> dict:
    """The merged settings table: shipped, then this repo's."""
    shipped = _shipped_settings()
    d = repo_dir(repo)
    if d is None:
        return shipped
    return merge(shipped, read_toml(d / shipped["paths"]["settings_file"]))


_MISSING = object()


def setting(dotted: str, default: Any = _MISSING, repo: Optional[Path] = None) -> Any:
    """One setting by dotted path, e.g. `limits.text`.

    With no `default`, a missing key is a ConfigError naming the key, which is what almost
    every caller wants. Passing a default is for a setting that genuinely may be absent, and
    it must never be used to keep a spare copy of a shipped value in Python: a duplicated
    default is a second place to update, which is the exact thing moving configuration into
    files was meant to end.
    """
    node: Any = settings(repo)
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is _MISSING:
                raise ConfigError(
                    f"no setting '{dotted}' — it should be in "
                    f"{defaults_dir() / 'settings.toml'}, which switchboard cannot run "
                    f"without"
                )
            return default
        node = node[part]
    return node


# -- roles ---------------------------------------------------------------------


def roles(repo: Optional[Path] = None) -> dict[str, dict]:
    """Every role, merged field by field. `{name: {model, cleanup, prompt}}`.

    Three sources, most general first — the shipped markdown, the repo's single TOML file,
    then the repo's own markdown directory:

        defaults/roles/*.md
        <repo>/.switchboard/roles.toml
        <repo>/.switchboard/roles/*.md

    Field by field is the point: a repo that says `[reviewer] model = "strong"` keeps the
    reviewer's cleanup disposition and its prompt.
    """
    out = _roles_from_dir(defaults_dir() / "roles")
    d = repo_dir(repo)
    if d is None:
        return out
    s = settings(repo)["paths"]
    for name, cfg in read_toml(d / s["roles_file"]).items():
        if not isinstance(cfg, dict):
            raise ConfigError(
                f"{d / s['roles_file']}: role '{name}' must be a table, e.g. [{name}]")
        out[name] = merge(out.get(name, {}), cfg)
    return merge(out, _roles_from_dir(d / s["roles_dir"]))


_roles_cache: dict[tuple, dict] = {}


def _roles_from_dir(d: Path) -> dict[str, dict]:
    """One markdown file per role: TOML front matter for the fields, the body is the prompt.

    A prompt wants to be prose in a file. Written as a quoted string in a dict it is
    unreadable, unreviewable in a diff, and nobody edits it.
    """
    sig = _signature(d, "*.md")
    if sig is None:
        return {}
    key = (str(d), sig)
    if key in _roles_cache:
        return _copy(_roles_cache[key])       # a copy: callers merge into what they get
    out: dict[str, dict] = {}
    for f in sorted(d.glob("*.md")):
        try:
            fields, body = front_matter(f.read_text())
        except ConfigError as e:
            raise ConfigError(f"{f}: {e}") from e
        cfg = dict(fields)
        prompt = flatten(body)
        # Only when there is one: an override file that is front matter alone adjusts the
        # fields and leaves the shipped prompt in place, rather than blanking it.
        if prompt:
            cfg["prompt"] = prompt
        out[f.stem] = cfg
    _roles_cache[key] = out
    return _copy(out)


# -- protocol and prompts ------------------------------------------------------


def protocol(repo: Optional[Path] = None) -> str:
    """The agent protocol, flattened to the single line herdr will accept.

    A repo's own `protocol.md` REPLACES this rather than merging into it. Every other file
    here joins; this one cannot, because a protocol assembled from two halves is a protocol
    nobody can read — and it is the one text every agent is judged against.
    """
    return flatten(protocol_override(repo) or _shipped_protocol())


def _shipped_protocol() -> str:
    text = read_text(defaults_dir() / "protocol.md")
    if text is None:
        raise ConfigError(f"no protocol.md in {defaults_dir()}")
    return text


def protocol_override(repo: Optional[Path] = None) -> Optional[str]:
    """This repo's replacement protocol, if it wrote one. Raw, not flattened."""
    p = path_for("protocol_file", repo)
    return None if p is None else read_text(p)


def prompts(repo: Optional[Path] = None) -> dict[str, dict[str, str]]:
    """The spawn fragments and doorbell texts, flattened, merged entry by entry."""
    shipped = read_toml(defaults_dir() / "prompts.toml")
    p = path_for("prompts_file", repo)
    raw = merge(shipped, read_toml(p) if p is not None else {})
    return {section: {k: flatten(v) if isinstance(v, str) else v
                      for k, v in table.items()}
            for section, table in raw.items() if isinstance(table, dict)}


def prompt(dotted: str, repo: Optional[Path] = None, **fields: Any) -> str:
    """One prompt by `section.name`, with its `{placeholders}` filled in.

    A placeholder nothing fills is a KeyError at spawn rather than a `{name}` reaching an
    agent's system prompt, because the second failure is invisible until someone reads a
    transcript.
    """
    section, _, name = dotted.partition(".")
    try:
        text = prompts(repo)[section][name]
    except KeyError as e:
        raise ConfigError(f"no prompt '{dotted}' in prompts.toml") from e
    try:
        return text.format(**fields) if fields else text
    except (KeyError, IndexError) as e:
        raise ConfigError(f"prompt '{dotted}' uses a placeholder nothing fills: {e}") from e


# -- plugin bindings -----------------------------------------------------------


def plugin_bindings(repo: Optional[Path] = None) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """`(applied to every agent, per-role additions)`, shipped joined with the repo's.

    Joined, not replaced: a repo adding one binding must not wipe the shipped ones. See
    `join` for the `"!reset"` escape hatch when replacing really is what you mean.
    """
    shipped = read_toml(defaults_dir() / "plugins.toml")
    p = path_for("plugins_file", repo)
    data = merge(shipped, read_toml(p) if p is not None else {})
    every = tuple(data.get("all") or ())
    per_role = {k: tuple(v) for k, v in (data.get("roles") or {}).items()}
    return every, per_role


# -- model tiers ---------------------------------------------------------------


def shipped_models() -> dict:
    """The shipped tier table, raw. models.py owns the layering above it — it has a global
    per-user layer this module knows nothing about."""
    return read_toml(defaults_dir() / "models.toml")
