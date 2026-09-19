"""Configuration, layered — the only module that reads a config file.

Everything switchboard ships as its out-of-the-box behaviour lives in `defaults/` at the
repo root: role definitions, model tiers, preset bindings, the agent protocol, the spawn
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
repo that adds one preset binding must not silently lose the shipped ones, and neither
layer can tell whether it is the only one there. When replacing really is what you mean,
say so with a `"!reset"` sentinel as the array's first element.

There is deliberately no way to DELETE a key from the base layer. Removing something you
did not write is how a merge becomes unreadable; override it to something inert instead.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
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


def shared_dir(repo: Optional[Path]) -> Optional[Path]:
    """A repo's COMMITTED config directory, or None if there is no repo in play.

    The layer between the shipped one and `.switchboard/`. It exists because `.switchboard/`
    cannot travel: it is gitignored, and in a worktree it is a symlink git refuses to track
    through — so a repo's own rules for its own agents reached nobody who cloned it, least
    of all the throwaway clones our verification method runs in.

    Its name comes from the shipped layer only, for the same reason `repo_dir`'s does.
    """
    if repo is None:
        return None
    return Path(repo) / _shipped_settings()["paths"]["shared_dir"]


def path_for(key: str, repo: Optional[Path] = None) -> Optional[Path]:
    """A `[paths]` entry resolved inside the repo's config directory."""
    d = repo_dir(repo)
    return None if d is None else d / setting(f"paths.{key}", repo=repo)


def shared_path_for(key: str, repo: Optional[Path] = None) -> Optional[Path]:
    """`path_for(key)`, resolved inside the repo's committed config directory instead.

    Same key names, so `presets.toml` is `presets.toml` in whichever layer you are looking
    at. No legacy fallback and none is owed: this directory is new, so nothing in it can be
    on a pre-rename spelling.
    """
    d = shared_dir(repo)
    return None if d is None else d / setting(f"paths.{key}", repo=repo)


def path_for_legacy(key: str, old_key: str, repo: Optional[Path] = None) -> Optional[Path]:
    """`path_for(key)`, falling back to `path_for(old_key)` when only the old one exists.

    A `[paths]` entry that has been RENAMED. A repo written against the old name — either
    because it overrode the old key, or simply because it still has the file the old key
    pointed at — keeps working without being touched. There is no flag day: the moment the
    new path exists it wins outright, and the old one is never consulted again.

    Deliberately keyed on what is on disk rather than on which key the repo set. Most repos
    set neither: they inherit both from the shipped layer and just have a directory with
    the old name in it, which is exactly the case that has to keep working.
    """
    new = path_for(key, repo)
    if new is None or new.exists():
        return new
    old = path_for(old_key, repo)
    return old if old is not None and old.exists() else new


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


def prose(text: str) -> str:
    """The same file, for something that is going to READ it rather than be spawned with it.

    `flatten` drops the HTML comments on the way to one line. This drops them and stops:
    the comments are notes to whoever edits the file and are never part of what the prompt
    says, but the wrapping, the headings and the lists are how the prose is meant to be
    read. An agent told to go and read a procedure wants it in that form, not as an
    unbroken line — the one-line rule exists because herdr rejects newlines in a spawn
    ARGUMENT, and nothing about reading a file is subject to it.
    """
    body = _COMMENT.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"


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


def flag(dotted: str, repo: Optional[Path] = None) -> bool:
    """A setting that must really be a boolean, e.g. `display.show_archived`.

    Every other setting is a number or a string, where the wrong type raises on first use.
    A boolean does not: `show_archived = "no"` is a non-empty string, so `if show_archived`
    is TRUE and a person who wrote "no" gets the opposite of what they asked for, with
    nothing anywhere to say so. Refusing it names the key and the value instead.

    A key that is simply ABSENT never reaches this. `settings()` merges the repo's file
    over the shipped one, so an older `.switchboard/settings.toml` that predates a key
    keeps working and takes the shipped default — which is what makes adding a setting a
    safe thing to do.
    """
    value = setting(dotted, repo=repo)
    if not isinstance(value, bool):
        raise ConfigError(
            f"setting '{dotted}' must be true or false, got {value!r} — "
            f"a quoted \"true\"/\"no\" is a string, and every non-empty string is true"
        )
    return value


# -- roles ---------------------------------------------------------------------


def roles(repo: Optional[Path] = None) -> dict[str, dict]:
    """Every role, merged field by field. `{name: {model, prompt}}`.

    Four sources, most general first — shipped markdown, roles contributed by enabled
    plugins, the repo's single TOML file, then the repo's own markdown directory:

        defaults/roles/*.md
        <enabled plugin>/roles/*.md
        <repo>/.switchboard/roles.toml
        <repo>/.switchboard/roles/*.md

    Field by field is the point: a repo that says `[reviewer] model = "strong"` keeps the
    reviewer's prompt.

    Plugin roles are discovered without importing plugin code, on the same level-1 path as
    plugin availability. This is what makes a plugin-specific specialty first-class in
    `sb roles` while keeping deletion or disablement honest: the `plans` plugin contributes
    `planner`, and removing that plugin removes the role that points at its commands too.
    """
    out = _roles_from_dir(defaults_dir() / "roles")
    # Local import avoids config/plugins import recursion at module load. At call time both
    # modules are complete, and `available` only globs directories — no plugin is imported.
    from . import plugins
    visible = plugins.available(repo)
    for name in sorted(set(plugin_enablement(repo)) & set(visible)):
        out = merge(out, _roles_from_dir(visible[name] / "roles"))
    d = repo_dir(repo)
    if d is None:
        return out
    s = settings(repo)["paths"]
    for name, cfg in read_toml(d / s["roles_file"]).items():
        if not isinstance(cfg, dict):
            raise ConfigError(
                f"{d / s['roles_file']}: role '{name}' must be a table, e.g. [{name}]")
        out[name] = merge(out.get(name, {}), _bundled(cfg))
    return merge(out, _roles_from_dir(d / s["roles_dir"]))


def _bundled(cfg: dict) -> dict:
    """A role's fields with the retired `delegate` bool rewritten as the bundle it meant.

    PER LAYER, before merging, and that is the whole point of doing it here rather than
    once at the end: a repo that writes `[qa] delegate = true` over a shipped role whose
    file names `capabilities` is layering two spellings of ONE field, and only the layer
    boundary knows which came later. Translated at the end instead, the shipped list would
    win and the repo's line would be read as nothing at all.

    The translation emits `["!reset", ...]` because arrays JOIN (rule 3). A bundle that
    unioned with the shipped one would make `delegate = false` widen a role rather than
    narrow it — the bool's answer replaced, it never added to, whatever was underneath.
    """
    if "delegate" not in cfg:
        return cfg
    from . import roles      # local: `roles` imports this module at import time
    out = {k: v for k, v in cfg.items() if k != "delegate"}
    out["capabilities"] = [RESET, *sorted(roles.bundle_for_delegate(cfg["delegate"]))]
    return out


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
        cfg = _bundled(fields)
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


# -- operator skills -----------------------------------------------------------


@dataclass
class OperatorSkill:
    """One procedure a person can ask the dispatcher to run.

    `command` is the verb a human is told to run, `description` is what it does. Both are
    prose destined for a spawn prompt, so both are flattened by whoever renders them —
    see `Broker._operator_menu`.
    """
    command: str
    description: str


def operator_skills(repo: Optional[Path] = None) -> list[OperatorSkill]:
    """The operator procedures this repo offers, shipped joined with the repo's own.

    An array of tables, so rule 3 applies: a repo adding one entry in
    `<repo>/.switchboard/operator_skills.toml` keeps the shipped ones, and `["!reset"]`
    first is how you say "exactly these, or none at all". Joining dedupes by whole-record
    equality, so a same-command different-description entry is a SECOND row rather than an
    override — rewording a shipped entry means resetting.

    The list is what `spawn.operator_menu` is generated from, so that the dispatcher's menu
    cannot go stale the way a hardcoded one would.
    """
    shipped = read_toml(defaults_dir() / "operator_skills.toml").get("skill") or []
    p = path_for("operator_skills_file", repo)
    mine = (read_toml(p).get("skill") or []) if p is not None else []
    out = []
    for entry in join(list(shipped), list(mine)):
        if not isinstance(entry, dict):
            raise ConfigError(
                f"operator_skills.toml: each entry must be a [[skill]] table, got {entry!r}")
        try:
            out.append(OperatorSkill(**entry))
        except TypeError as e:
            raise ConfigError(f"operator_skills.toml: bad [[skill]] entry {entry!r}: {e}") from e
    return out


# -- preset bindings -----------------------------------------------------------


def preset_bindings(repo: Optional[Path] = None) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """`(applied to every agent, per-role additions)`, shipped joined with the repo's.

    Three layers, most general first: shipped, the repo's committed `shared_dir`, then the
    local `.switchboard/`. Joined, not replaced: a repo adding one binding must not wipe the
    shipped ones, and a machine-local binding must not wipe the repo's own. See `join` for
    the `"!reset"` escape hatch when replacing really is what you mean.

    A repo still holding the pre-rename `plugins.toml` is read from there — see
    `path_for_legacy`.
    """
    shipped = read_toml(defaults_dir() / "presets.toml")
    s = shared_path_for("presets_file", repo)
    p = path_for_legacy("presets_file", "plugins_file", repo)
    data = merge(shipped, read_toml(s) if s is not None else {})
    data = merge(data, read_toml(p) if p is not None else {})
    every = tuple(data.get("all") or ())
    per_role = {k: tuple(v) for k, v in (data.get("roles") or {}).items()}
    return every, per_role


# -- plugin enablement ---------------------------------------------------------


def plugin_enablement(repo: Optional[Path] = None) -> tuple[str, ...]:
    """Which plugins are enabled: `enabled = [...]` in `plugins.toml`, shipped then repo's.

    The same `merge` every other file gets, so a repo adding one plugin cannot wipe the
    shipped ones and `["!reset"]` is how you say "exactly this, or nothing".

    `plugins.toml` means two things during the transition and needs no disambiguation to
    read: a pre-rename file binds presets with top-level `all` and `[roles]`, and an
    enablement file lists `enabled`. The keys are disjoint, so a file holding both parses
    as both — this function ignores `all` and `roles`, and `preset_bindings` ignores
    `enabled`. There is no path-level fallback here and none is owed: unlike `presets_file`,
    `plugins_file` was never renamed, so the old spelling and the new one are the same path.
    """
    shipped = read_toml(defaults_dir() / "plugins.toml")
    p = path_for("plugins_file", repo)
    data = merge(shipped, read_toml(p) if p is not None else {})
    return tuple(data.get("enabled") or ())


# -- model tiers ---------------------------------------------------------------


def shipped_models() -> dict:
    """The shipped tier table, raw. models.py owns the layering above it — it has a global
    per-user layer this module knows nothing about."""
    return read_toml(defaults_dir() / "models.toml")


# -- the two levels, surfaced (spec §10) ---------------------------------------
#
#     Switchboard defaults -> repo-specific override -> effective value
#
# Everything above this line RESOLVES that chain and returns the answer. What it could not
# do is say where the answer came from, and that is the whole of what §10 asks for: "the UI
# distinguishes Switchboard default, repo override and effective value, and offers an easy
# reset to default". A browser cannot present a distinction the library will not tell it.
#
# So this section is the SUBSTRATE and not a second resolver: `Layered.effective` is read
# back out of `setting()` and the vocabulary rows out of the same layered readers the spawn
# path uses, so a readout that disagreed with a spawn would be a bug here rather than a
# second opinion. `sb configure --layers` renders it; the browser (wave 12) will edit it.
#
# THREE things are deliberately not here. Writing an override is not — resetting a key means
# editing the repo's TOML, comments and all, and the file is the editing surface today.
# Per-agent `sb configure` state is not — that is an agent tuning ITSELF inside its role's
# ceiling (`roles.effective_config`), a different subject with a different store. And no
# value is REFUSED here: see `_family` for how far validation goes and why.


class _Unset:
    """`override` when the repo's file says nothing about a key. Not `None`: `None` is a
    value a TOML file can hold, and conflating "unset" with it would make a repo that
    genuinely wrote one look like a repo that wrote nothing."""

    def __repr__(self) -> str:                                    # pragma: no cover
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


@dataclass(frozen=True)
class Layered:
    """One configuration key across the two levels.

    `override` is the repo's RAW value and `effective` the merged one, and for an array
    those are different on purpose: arrays JOIN (merge rule 3), so a repo that wrote one
    entry has an effective value holding the shipped ones too. Reporting the raw value as
    the effective one would tell a reader their list was shorter than it is; reporting only
    the effective one would hide which entry is theirs to delete.
    """

    key: str
    default: Any
    override: Any
    effective: Any
    note: str = ""

    @property
    def overridden(self) -> bool:
        return not isinstance(self.override, _Unset)

    @property
    def ships_default(self) -> bool:
        """False for a key only the repo defines — its own `[config.settings.<name>]`, or a
        table switchboard does not ship. There is nothing to reset such a key TO."""
        return not isinstance(self.default, _Unset)

    @property
    def joined(self) -> bool:
        """The effective value is the two layers concatenated rather than one of them."""
        return self.overridden and isinstance(self.effective, list) \
            and self.effective != self.override

    def reset(self) -> str:
        """How to put this key back to switchboard's default, in words that are the edit.

        There is no `--reset` flag and this is why: the repo's settings file is TOML with
        comments in it, the comments are most of its value, and a writer that preserved
        them is a TOML round-tripper this project does not have. Deleting a line is the
        whole operation, so the honest surface is to name the line.
        """
        if not self.overridden:
            return ""
        if not self.ships_default:
            return f"delete `{self.key.rsplit('.', 1)[-1]}` (switchboard ships no default)"
        if self.joined:
            return (f"drop your entry, or write `[\"{RESET}\", ...]` to replace the "
                    f"shipped list instead of adding to it")
        return f"delete `{self.key.rsplit('.', 1)[-1]}` from your settings file"

    def as_dict(self) -> dict:
        """The row as JSON — what `--json` emits and what the browser will read.

        `UNSET` is not JSON, so an absent layer is reported by the booleans rather than by a
        null that would be indistinguishable from a null somebody wrote.
        """
        out = {"key": self.key, "effective": self.effective,
               "overridden": self.overridden, "ships_default": self.ships_default,
               "joined": self.joined, "reset": self.reset(), "note": self.note}
        if self.ships_default:
            # `shipped` and not `default`: `test_config` forbids these modules a literal
            # that collides with a TIER name, and `default` is one. Same reason
            # `[config.settings]` spells its own starting value `initial` (`roles.INITIAL`).
            out["shipped"] = self.default
        if self.overridden:
            out["override"] = self.override
        return out


def override_path(repo: Optional[Path] = None) -> Optional[Path]:
    """The one file a repo's setting overrides live in — whether or not it exists yet.

    Named even when absent, because "where would I write one" is the question a readout of
    defaults raises, and answering it with nothing sends the reader to search the tree.
    """
    d = repo_dir(repo)
    return None if d is None else d / _shipped_settings()["paths"]["settings_file"]


def _repo_settings(repo: Optional[Path] = None) -> dict:
    """The repo's settings file, raw and unmerged. `{}` when there is none."""
    p = override_path(repo)
    return read_toml(p) if p is not None else {}


def _leaves(node: dict, path: tuple = ()) -> Iterable[tuple[str, Any]]:
    """Every `dotted.key -> value` in a settings tree.

    An EMPTY table is a leaf (`[codex.deepseek.options]`), because descending into it
    yields nothing and a repo filling it in is overriding that table. A non-empty one is
    descended, including an inline table like `role_aliases` — `vocabulary.role_aliases.qa`
    is exactly the granularity at which a repo overrides one alias and keeps the rest.
    """
    for key, value in node.items():
        if isinstance(value, dict) and value:
            yield from _leaves(value, (*path, key))
        else:
            yield ".".join((*path, key)), value


def _at(node: Any, dotted: str) -> Any:
    """One dotted key out of a tree, or `UNSET` if that tree does not reach it."""
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return UNSET
        node = node[part]
    return node


# The value families validation knows about, and the whole of how far it goes.
#
# Spec §10: "Validation catches obviously invalid values. Beyond that, configuration stays
# permissive: do not hard-code restrictions on combinations of roles, presets, models or
# Task structures." A number where a list belongs is obviously invalid and there is no repo
# for which it works. Which roles may run on which model is not: that is a combination, and
# a rule about it here would be exactly the hard-coded restriction §10 forbids.
#
# A NOTE AND NOT A REFUSAL, even so. The value that raises is the one that gets USED —
# `flag()` refuses a quoted "no", `setting()` names a key that is missing entirely — and
# that stays the enforcement point, because it fires for the caller who cares and knows
# which key it was reading. This is a readout; its job is to say the override looks wrong
# while still reporting what it is.
def _family(value: Any) -> str:
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__


def _note(default: Any, override: Any) -> str:
    if isinstance(default, _Unset) or isinstance(override, _Unset):
        return ""
    want, got = _family(default), _family(override)
    return "" if want == got else \
        f"a {got} where switchboard's default is a {want} — probably a mistake"


def setting_layers(repo: Optional[Path] = None, prefix: str = "") -> list[Layered]:
    """Every setting as `default -> override -> effective`, in shipped file order.

    `prefix` is a dotted path and matches a key or a whole table under it, so `timeouts`
    answers "what can I tune about timing" and `timeouts.stall_threshold` answers about
    one. Keys the repo added that switchboard does not ship come last, because they have no
    place in the shipped order to sit in.
    """
    shipped, over, live = _shipped_settings(), _repo_settings(repo), settings(repo)
    keys = dict.fromkeys(k for k, _ in _leaves(shipped))
    keys.update(dict.fromkeys(k for k, _ in _leaves(over)))
    rows = []
    for key in keys:
        if prefix and key != prefix and not key.startswith(f"{prefix}."):
            continue
        default, override = _at(shipped, key), _at(over, key)
        rows.append(Layered(key=key, default=default, override=override,
                            effective=_at(live, key), note=_note(default, override)))
    return rows


# -- the vocabularies, surfaced ------------------------------------------------
#
# "Repo-defined roles, presets and step kinds are repo configuration in the same two-level
# scheme" (§10). They already resolved that way; what follows says so out loud, one row per
# NAME rather than per key, because a name is what a repo adds and what a browser lists.
#
# Read off the same layered readers the spawn path uses wherever there is one, and off the
# DIRECTORIES where the layering is a file lookup. No plugin is imported: `plugins.available`
# globs, exactly as `roles()` above relies on.


# The plugin whose catalogue mints step kinds. Named here rather than discovered, because
# "step kinds" is a spec-level vocabulary (§4) and `plans` is the plugin that implements it —
# a repo that deletes that plugin has no step kinds, which is the honest answer and the one
# a listing should give. The catalogue's own layering is in the plugin; `step_library_dirs`
# below is the shared definition of WHERE, so the two cannot drift.
STEP_LIBRARY_PLUGIN = "plans"


# The two catalogues the step-library plugin keeps, and the `[paths]` entry each is layered
# under. A map rather than `f"step_{which}_dir"`, so the TOML key and the directory name stay
# independently editable and a typo in one is a KeyError here rather than a silent miss.
STEP_CATALOGUES = {"library": "step_library_dir", "templates": "step_templates_dir"}


def step_library_dirs(which: str = "library", repo: Optional[Path] = None) -> list[Path]:
    """One step catalogue's layers, most general first: shipped, committed, machine-local.

    The same three-layer shape as presets, and the same rule on top of it — keyed by
    filename, a later layer replacing the earlier one of that name. Shipped lives inside the
    plugin because the definitions are the plugin's own; the two repo layers are ordinary
    `[paths]` entries, so a repo mints a step kind by adding a JSON file and nothing else.
    """
    from . import plugins                          # see `roles()` — globs, imports nothing
    key = STEP_CATALOGUES[which]
    out = []
    plugin = plugins.available(repo).get(STEP_LIBRARY_PLUGIN)
    if plugin is not None:
        out.append(plugin / which)
    for d in (shared_path_for(key, repo), path_for(key, repo)):
        if d is not None:
            out.append(d)
    return out


@dataclass(frozen=True)
class Defined:
    """One name in a repo-extensible vocabulary, and which layer put it there."""

    name: str
    origin: str                 # "switchboard", "plugin:<name>", "repo", "repo (committed)"
    source: Optional[str]       # the file it came from, where it is a file
    overrides_default: bool     # a repo layer speaks about a name switchboard also ships

    def as_dict(self) -> dict:
        return {"name": self.name, "origin": self.origin, "source": self.source,
                "overrides_default": self.overrides_default}


def _stems(d: Optional[Path], pattern: str) -> dict[str, Path]:
    return {} if d is None or not d.is_dir() else \
        {f.stem: f for f in sorted(d.glob(pattern))}


def _defined(layers: Iterable[tuple[str, dict[str, Any]]]) -> list[Defined]:
    """Collapse `(origin, {name: source})` layers, most general first, into one row per name.

    The LAST layer to speak about a name owns the row, which is the resolution rule every
    one of these vocabularies already uses. `overrides_default` is true when an earlier
    layer also had the name — that is what a browser marks and what a reset would restore.
    """
    seen: dict[str, Defined] = {}
    for origin, found in layers:
        for name, source in found.items():
            seen[name] = Defined(name=name, origin=origin,
                                 source=None if source is None else str(source),
                                 overrides_default=name in seen)
    return [seen[n] for n in sorted(seen)]


def role_layers(repo: Optional[Path] = None) -> list[Defined]:
    """Which layer defines each role — `roles()`' four sources, one row per name."""
    from . import plugins
    layers = [("switchboard", _stems(defaults_dir() / "roles", "*.md"))]
    visible = plugins.available(repo)
    for name in sorted(set(plugin_enablement(repo)) & set(visible)):
        layers.append((f"plugin:{name}", _stems(visible[name] / "roles", "*.md")))
    d = repo_dir(repo)
    if d is not None:
        s = settings(repo)["paths"]
        f = d / s["roles_file"]
        layers.append(("repo", {k: f for k in read_toml(f)}))
        layers.append(("repo", _stems(d / s["roles_dir"], "*.md")))
    return _defined(layers)


def preset_layers(repo: Optional[Path] = None) -> list[Defined]:
    """Which layer defines each preset — the three directories `presets.available` reads."""
    from . import presets
    return _defined([
        ("switchboard", _stems(defaults_dir() / "presets", "*.md")),
        ("repo (committed)", _stems(presets.shared_preset_dir(repo), "*.md")),
        ("repo", _stems(presets.preset_dir(repo), "*.md")),
    ])


def model_layers(repo: Optional[Path] = None) -> list[Defined]:
    """Which layer defines each model tier.

    THREE layers here and two everywhere else, and the third is real: a per-user
    `~/.config/switchboard/models.toml` sits between shipped and repo (`models.load`). It is
    not a repo override — it is the same user's answer for every repo — so it is reported
    under its own origin rather than folded into one of the two.
    """
    d = repo_dir(repo)
    user = Path(setting("paths.global_models", repo=repo)).expanduser()
    layers = [("switchboard", {k: defaults_dir() / "models.toml"
                               for k in (shipped_models().get("tiers") or {})}),
              ("user", {k: user for k in (read_toml(user).get("tiers") or {})})]
    if d is not None:
        f = d / settings(repo)["paths"]["models_file"]
        layers.append(("repo", {k: f for k in (read_toml(f).get("tiers") or {})}))
    return _defined(layers)


def step_kind_layers(repo: Optional[Path] = None) -> list[Defined]:
    """Which layer defines each step-library definition — `step_library_dirs`, in order.

    A definition's FILENAME is the step kind it mints, which is why this listing answers
    the vocabulary question at all: `library/deploy.json` is how a repo gets a `deploy`
    kind. Four shipped filenames are spellings of a built-in kind rather than new ones
    (`create-pr` is `open_pr`); that mapping belongs to the plugin, so what is reported here
    is the definition, and the plugin's own refusal is what knows the difference.
    """
    origins = ["switchboard", "repo (committed)", "repo"]
    dirs = step_library_dirs("library", repo)
    # One plugin layer and up to two repo ones. When the plugin is gone the repo layers are
    # still there and still theirs, so the origins are zipped from the END.
    return _defined(list(zip(origins[len(origins) - len(dirs):],
                             (_stems(d, "*.json") for d in dirs))))


def vocabulary_layers(repo: Optional[Path] = None) -> dict[str, list[Defined]]:
    """Every repo-extensible vocabulary §10 names, keyed by what `sb` calls it."""
    return {"roles": role_layers(repo), "presets": preset_layers(repo),
            "models": model_layers(repo), "step-kinds": step_kind_layers(repo)}
