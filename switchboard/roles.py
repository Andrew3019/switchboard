"""Role profiles.

A role is a spawn profile: which model tier, what cleanup disposition, and the prompt that
tells an agent who it is. Vocabulary is data (C12) — there is no closed set, and a role
that isn't defined still works with defaults.

A role names a TIER only. What a tier maps to — provider, model, effort — is models.py's
job, so no model name appears here. And no role name, disposition or prompt appears here
either: the definitions are files, one markdown file per role, read by config.py.

    defaults/roles/<name>.md          shipped
    <repo>/.switchboard/roles.toml    this repo's overrides
    <repo>/.switchboard/roles/*.md    this repo's own roles, in the same form

Later layers override earlier ones FIELD BY FIELD, so changing a reviewer's tier keeps its
disposition and its prompt. See config.py for the merge rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config, models

# Agents ask for a tier, never a model id. Keeps model names out of prompts and templates,
# survives model churn, and ports to another backend unchanged (P0).


def _default_tier() -> str:
    """The tier a role gets when its own file does not name one."""
    return config.setting("vocabulary.default_tier")


@dataclass
class Role:
    name: str
    model: str = ""                 # a TIER name, not a model id
    cleanup: str = ""
    prompt: str = ""
    tiers: Optional[models.Tiers] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        # Defaulted here rather than in the signature, so that even a Role built by hand
        # gets its tier and disposition from `[vocabulary]` rather than from a literal in
        # this file. Every shipped role sets both; this only bites a three-line role
        # somebody wrote, which is exactly the case that should not need to know what the
        # default tier is called.
        self.model = self.model or _default_tier()
        self.cleanup = self.cleanup or config.setting("vocabulary.default_cleanup")

    def spec(self, override: Optional[str] = None) -> models.ModelSpec:
        """The resolved provider + model + effort for this role's tier.

        Everything the spawn layer needs is on the returned spec; see
        `ModelSpec.cli_args()`. An unknown tier name passes through as a model id.

        `override` is a per-call tier name (`sb delegate --model strong`). It goes through
        the same table as the role's own, which is the whole point: a caller that names a
        tier gets that tier's effort too, and neither path can hand a raw tier name to a
        provider CLI. There is deliberately no `model_id()` shortcut any more — it existed,
        it dropped effort silently, and every caller of it was a bug.
        """
        return (self.tiers or models.load()).resolve(override or self.model)


def load(repo: Optional[Path] = None) -> dict[str, Role]:
    """Role definitions only — what an agent IS.

    Which behaviours get injected into it is a separate concern; see plugins.py.
    """
    merged = config.roles(repo)
    tiers = models.load(repo)
    return {k: Role(name=k, tiers=tiers, **v) for k, v in merged.items()}


def get(roles: dict[str, Role], name: str) -> Role:
    """Unknown roles are fine — they inherit the fallback role's fields but keep their own
    name, so `--as` and ad-hoc roles work without anyone editing a file first.

    Which role is the fallback is `[vocabulary] fallback_role`, not a literal here: what an
    undefined role behaves like is a decision a repo is allowed to make differently.
    """
    if name in roles:
        return roles[name]
    fallback = config.setting("vocabulary.fallback_role")
    base = roles.get(fallback) or Role(fallback)
    return Role(name=name, model=base.model, cleanup=base.cleanup, prompt=base.prompt,
                tiers=base.tiers)
