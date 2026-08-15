"""Role profiles.

A role is a spawn profile: which model tier, and the prompt that tells an agent who it
is. Vocabulary is data (C12) — there is no closed set, and a role
that isn't defined still works with defaults.

A role names a TIER only. What a tier maps to — provider, model, effort — is models.py's
job, so no model name appears here. And no role name, disposition or prompt appears here
either: the definitions are files, one markdown file per role, read by config.py.

    defaults/roles/<name>.md          shipped
    <repo>/.switchboard/roles.toml    this repo's overrides
    <repo>/.switchboard/roles/*.md    this repo's own roles, in the same form

Later layers override earlier ones FIELD BY FIELD, so changing a reviewer's tier keeps its
prompt. See config.py for the merge rules.
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
    prompt: str = ""
    delegate: bool = False          # may an agent of this role spawn other agents?
    tiers: Optional[models.Tiers] = field(default=None, repr=False, compare=False)

    # `delegate` is a FIELD, not a check against the literal role name. "Bare" is a
    # property of a kind of agent, and a role named `worker` is only today's spelling of
    # it — vocabulary is data (C12), there is no closed set, and a repo that adds its own
    # leaf role or renames this one would slip straight through `role == "worker"`. It
    # defaults to False for the same reason every other safety default points that way: a
    # role nobody thought about is a leaf, and being wrong that way costs a refusal a
    # person can lift, not a tree of agents nobody meant to exist.

    def __post_init__(self):
        # Defaulted here rather than in the signature, so that even a Role built by hand
        # gets its tier from `[vocabulary]` rather than from a literal in this file.
        self.model = self.model or _default_tier()

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

    Which behaviours get injected into it is a separate concern; see presets.py.
    """
    merged = config.roles(repo)
    tiers = models.load(repo)
    return {k: Role(name=k, tiers=tiers, **v) for k, v in merged.items()}


def get(roles: dict[str, Role], name: str, repo: Optional[Path] = None) -> Role:
    """Unknown roles are fine — they inherit the fallback role's fields but keep their own
    name, so `--as` and ad-hoc roles work without anyone editing a file first.

    Which role is the fallback is `[vocabulary] fallback_role`, not a literal here: what an
    undefined role behaves like is a decision a repo is allowed to make differently.

    `repo` is what makes "a repo is allowed to decide differently" true rather than merely
    stated. Both settings this reads are layered — shipped, then the repo's own — and both
    were being read with no repo at all, which resolves the shipped layer and stops. A repo
    that retired a role of its own and wrote the alias for it in `.switchboard/settings.toml`
    got silence: the name fell through to the fallback exactly as if the alias had never
    been written. Every caller in the broker has a repo and passes it; the default is for
    the ad-hoc call and for tests that only care about the shipped table.

    A RETIRED name is a different case from a name nobody ever defined, and the fallback is
    the wrong answer for it: `orchestrator` used to mean "an agent that owns this and splits
    it", and falling through to `worker` would spawn something that cannot delegate at all,
    silently, for a name that used to mean the opposite. So `[vocabulary] role_aliases` maps
    an old name onto the role that replaced it, and the alias resolves ALL the way — the
    returned Role carries the new name, so the board, the prompt and the stored row all say
    what the agent actually is rather than what it was typed as. Data, not a literal here,
    for the same reason every other name in this file is (C12).
    """
    if name in roles:
        return roles[name]
    alias = config.setting("vocabulary.role_aliases", repo=repo).get(name)
    if alias and alias in roles:
        return roles[alias]
    fallback = config.setting("vocabulary.fallback_role", repo=repo)
    base = roles.get(fallback) or Role(fallback)
    return Role(name=name, model=base.model, prompt=base.prompt,
                delegate=base.delegate, tiers=base.tiers)
