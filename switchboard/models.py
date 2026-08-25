"""Model tier resolution.

A tier is a human-readable name — `cheap`, `default`, `strong`, or anything you invent —
that maps to a PROVIDER, a MODEL and an EFFORT level. Tier names are user vocabulary (C12):
the set is open, and the mapping is config, not code. Nothing outside this file should know
the name of a model.

TOML, not YAML, so this stays dependency-free (`tomllib` is stdlib).

Layering, most general first — each level overrides the last:

    defaults/models.toml  →  ~/.config/switchboard/models.toml  →  <repo>/.switchboard/models.toml

The first of those is a shipped FILE, not a dict in this module. No model name appears in
Python anywhere, including in this docstring — `defaults/models.toml` is where you find out
what `strong` means, the file format, and why it is aliases rather than pinned ids. That is
the point of moving it there: one answer, in the place someone would edit it.

Effort is set with the verified `--effort <level>` flag rather than the CLAUDE_EFFORT
environment variable. A flag is per-spawn and explicit; an inherited env var would silently
give every child its parent's effort.

Resolution returns everything the spawn layer needs, and for one provider that is CLI
flags. It is not universal: `--model`/`--effort` are Claude Code's flag names, and codex
has no equivalent for either — its model and effort are keys in a private per-agent
`CODEX_HOME/config.toml` instead (`switchboard/codex.py`). So `cli_args()` answers [] for
it, and exactly one place in the system branches on `provider`: `Herdr.start_agent`, which
is the layer that types a provider's command line.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config


def _shipped() -> dict:
    """The shipped tier table, read from `defaults/models.toml` every time.

    Not cached into a module constant: `SWITCHBOARD_DEFAULTS` can point somewhere else, and
    a value frozen at import would ignore it.
    """
    return config.shipped_models()


class _Shipped:
    """`SHIPPED["tiers"]` kept working, backed by the file rather than by a dict here.

    A view, not a copy — the file is where the answer lives, and anything that snapshots it
    at import time is a second place the tiers can be wrong.
    """

    def __getitem__(self, key: str):
        return _shipped()[key]

    def get(self, key: str, default=None):
        return _shipped().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in _shipped()

    def __iter__(self):
        return iter(_shipped())

    def __repr__(self) -> str:
        return repr(_shipped())


SHIPPED = _Shipped()


def wired_providers() -> tuple[str, ...]:
    """Providers with a backend behind them. A fact about this codebase, not a preference,
    so it is shipped-only: a repo claiming `codex` works would fail at spawn time instead
    of at resolution time, where the message can still say what is wrong."""
    return tuple(_shipped().get("providers", {}).get("wired") or ())


def effort_levels() -> tuple[str, ...]:
    """What the provider CLI accepts for `--effort`. Shipped-only for the same reason."""
    return tuple(_shipped().get("providers", {}).get("effort_levels") or ())


# Module-level snapshots for callers that only want the names. The functions above are what
# resolution uses, so pointing SWITCHBOARD_DEFAULTS elsewhere still takes effect.
WIRED_PROVIDERS = wired_providers()
EFFORT_LEVELS = effort_levels()


def _default_provider() -> str:
    """The provider a tier gets when it names none, and the one the passthrough escape
    hatch hands an unknown tier name to."""
    return (_shipped().get("defaults") or {}).get("provider", "")


# The fields a tier table may set. Anything else is a typo, and saying so beats resolving
# to a spec that quietly ignores it.
TIER_KEYS = frozenset({"provider", "model", "effort", "extra_args", "codex_provider"})

# Per-user, between the shipped tiers and the repo's — what `strong` means on YOUR machine.
ENV_GLOBAL_CONFIG = "SWITCHBOARD_MODELS_CONFIG"


def _global_config() -> Path:
    return Path(config.setting("paths.global_models"))


def _repo_config(repo: Path) -> Optional[Path]:
    return config.path_for("models_file", repo)


GLOBAL_CONFIG = _global_config()


class ModelConfigError(ValueError):
    """Config names something switchboard cannot turn into a spawn."""


@dataclass(frozen=True)
class ModelSpec:
    """A resolved tier: everything the spawn layer needs, and nothing it must interpret."""

    tier: str
    # Every construction site passes one; the fallback exists so a hand-built spec in a
    # test or a REPL is not the one place a provider name is written in Python.
    provider: str = field(default_factory=lambda: _default_provider())
    model: Optional[str] = None      # None = let the provider CLI pick its own default
    effort: Optional[str] = None     # None = inherit whatever the provider CLI defaults to
    extra_args: tuple[str, ...] = ()

    # An optional SUB-provider, for a binary that speaks to more than one API. `provider`
    # stays the binary switchboard starts — a deepseek tier is still `codex`, and still
    # goes down the codex path — and this names a `[codex.<name>]` section of the settings
    # file holding the endpoint, the wire protocol and the environment variable with the
    # key. `switchboard/codex.py` is the only reader; it turns that section into the
    # `[model_providers.<name>]` block of the agent's private config.toml. None means the
    # binary's own API, which is every tier that predates the field.
    #
    # Named for the one provider it applies to rather than something general like
    # `endpoint`, because it IS codex-specific: it is the name of a codex config key, and
    # a claude tier that set it would be silently ignored. `defaults/models.toml` is where
    # a person meets it.
    codex_provider: Optional[str] = None

    # The providers whose per-agent settings travel as CLI FLAGS. Everything else delivers
    # them some other way and must get an empty list here rather than Claude Code's flag
    # names — see `cli_args`. A tuple in Python rather than a config key because it is a
    # fact about which code path exists, not a preference: adding a provider to it without
    # writing that path would produce flags no binary accepts.
    _FLAG_PROVIDERS = ("claude",)

    def cli_args(self) -> list[str]:
        """The provider's CLI flags for this tier — which for one provider is none at all.

        This was the whole point of the module and it is now half of it: the caller
        appends these and never asks which provider it is talking to. What changed is that
        `--model`/`--effort` are Claude Code's flag NAMES, not a universal vocabulary.
        Codex has neither; its model and reasoning effort are keys in a private per-agent
        `CODEX_HOME/config.toml` that `switchboard/codex.py` writes and
        `Herdr.start_agent` triggers. Emitting the claude flags for it would hand `codex`
        an argument it rejects outright, so this returns [] and the SPEC goes down beside
        the flags for the one caller that needs to know (`Broker.delegate`).

        The unwired check stays first and stays here. It is the one refusal that can still
        name what is wrong — by spawn time the message would be a provider CLI's complaint
        about an unknown flag.
        """
        wired = wired_providers()
        if self.provider not in wired:
            raise ModelConfigError(
                f"tier '{self.tier}' asks for provider '{self.provider}', which has no "
                f"backend yet (wired: {', '.join(wired)})"
            )
        if self.provider not in self._FLAG_PROVIDERS:
            return []
        args: list[str] = []
        if self.model:
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        args += list(self.extra_args)
        return args


@dataclass
class Tiers:
    """The resolved tier table for one repo."""

    tiers: dict[str, ModelSpec] = field(default_factory=dict)
    default_provider: str = ""

    def __post_init__(self):
        self.default_provider = self.default_provider or _default_provider()

    def __contains__(self, name: str) -> bool:
        return name in self.tiers

    def resolve(self, name: Optional[str]) -> ModelSpec:
        """Tier name → spec.

        An unknown name is passed through verbatim as a model id. That escape hatch lets
        anyone pin a specific model without editing config first, and it is why an
        undefined tier is not an error.
        """
        if not name:
            fallback = config.setting("vocabulary.default_tier")
            return self.tiers.get(fallback) or ModelSpec(
                tier=fallback, provider=self.default_provider)
        if name in self.tiers:
            return self.tiers[name]
        return ModelSpec(tier=name, provider=self.default_provider, model=name)

    def names(self) -> list[str]:
        return sorted(self.tiers)


def _spec(name: str, cfg: dict, default_provider: str) -> ModelSpec:
    unknown = set(cfg) - TIER_KEYS
    if unknown:
        raise ModelConfigError(
            f"tier '{name}' has unknown key(s): {', '.join(sorted(unknown))}")
    effort = cfg.get("effort")
    levels = effort_levels()
    if effort is not None and effort not in levels:
        raise ModelConfigError(
            f"tier '{name}' has effort '{effort}'; valid levels are "
            f"{', '.join(levels)}"
        )
    return ModelSpec(
        tier=name,
        provider=cfg.get("provider") or default_provider,
        model=cfg.get("model"),
        effort=effort,
        extra_args=tuple(cfg.get("extra_args") or ()),
        codex_provider=cfg.get("codex_provider"),
    )


def _read(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
    except OSError:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ModelConfigError(f"{path}: {e}") from e


def _layer(into: dict, raw: dict) -> None:
    """Merge one config file over the accumulated table, per tier rather than wholesale.

    Per-tier merge is what lets a repo override just the effort of `strong` without
    restating its provider and model.
    """
    for name, cfg in (raw.get("tiers") or {}).items():
        if not isinstance(cfg, dict):
            raise ModelConfigError(f"tier '{name}' must be a table, e.g. [tiers.{name}]")
        into.setdefault(name, {}).update(cfg)


def load(repo: Optional[Path] = None, *, global_config: Optional[Path] = None) -> Tiers:
    """`defaults/models.toml`, then the global file, then the repo file."""
    shipped = _shipped()
    merged = {k: dict(v) for k, v in (shipped.get("tiers") or {}).items()}
    provider = _default_provider()

    gpath = Path(global_config) if global_config is not None else Path(
        os.environ.get(ENV_GLOBAL_CONFIG) or _global_config()).expanduser()
    repo_paths = [p for p in ([_repo_config(repo)] if repo else []) if p is not None]
    for path in [gpath, *repo_paths]:
        raw = _read(path)
        provider = (raw.get("defaults") or {}).get("provider") or provider
        _layer(merged, raw)

    return Tiers(
        tiers={n: _spec(n, cfg, provider) for n, cfg in merged.items()},
        default_provider=provider,
    )


def resolve(name: Optional[str], repo: Optional[Path] = None) -> ModelSpec:
    """Convenience for callers that resolve one tier and do not hold a Tiers around."""
    return load(repo).resolve(name)
