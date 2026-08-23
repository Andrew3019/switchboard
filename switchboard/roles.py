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


# THE CAPABILITY STRINGS. A gated action is one of these, checked through
# `Broker.require_capability`; adding a rule means adding a string here, not another
# refusal function beside the gate. The vocabulary is OPEN-ENDED on purpose — `merge`,
# `self-configure` and whatever comes next are each one string plus one gate, not a
# subsystem — and it lives here rather than in the broker because a role's default bundle
# is written in terms of it and `roles` is the lower module.
#
# There is deliberately no `start`. `sb start` is a hardcoded, fail-closed, human-only gate
# in the CLI (`cli.py`, the `start` branch) and it stays there: a grantable version of it is
# how a top would come to mint another top, so the string does not exist to be granted.
CAP_SPAWN = "spawn"                    # may this caller spawn an agent at all?
CAP_FORK = "fork"                      # does this caller's spawn mint a space of its own?
CAP_DISPATCH = "dispatch"              # may it hand work to an agent it did not spawn?
CAP_WRITE_TRACKED = "write-tracked"    # may it write files git tracks?

# THE WHOLE VOCABULARY, as one set. `sb grant` checks against it and refuses anything else,
# and that refusal is the fail-CLOSED half of the grant path: a grant is durable, silent and
# irrevocable, so a typo (`--delegable wrte-tracked`) must be an error rather than a row
# nothing will ever read and nobody will ever notice is dead.
#
# Open-ended still means what it said — a new gated action is a new string here plus one
# gate, not a subsystem — but "open-ended" is about how the set GROWS, not about accepting
# whatever a caller types. `start` is not in it and never will be.
CAPABILITIES = frozenset({CAP_SPAWN, CAP_FORK, CAP_DISPATCH, CAP_WRITE_TRACKED})

# What a role gets when its own definition names no bundle. A role nobody thought about is
# a LEAF that may write — the same answer the retired `delegate = false` default gave, for
# the same reason: being wrong this way costs a refusal a person can lift, and being wrong
# the other way costs a tree of agents nobody meant to exist.
DEFAULT_CAPABILITIES = frozenset({CAP_WRITE_TRACKED})

# The top dispatcher's bundle, and the one bundle that is NOT data (§2.0). A top is a
# placement plus a stamp plus a FIXED set: it is not editable, not layerable by a repo's
# roles file, and not derived from any mutable row. `write-tracked` is absent and that is
# the whole invariant — the top works over a person's own checkout, so the rule is "no
# tracked-file WRITE", not "no fork". It holds `fork` because forking is what a top is FOR:
# it has no space to lend, and holding `fork` gives it no write, no second top and no way
# to leave its position.
TOP_CAPABILITIES = frozenset({CAP_SPAWN, CAP_DISPATCH, CAP_FORK})


def bundle_for_delegate(delegate: bool) -> frozenset:
    """THE BACK-COMPAT READ. What a role's retired `delegate = true/false` meant, as a set.

    A role used to carry that bool, and `.switchboard/roles.toml` and `roles/*.md` files in
    the wild still say so. Rather than break them, the bool maps onto the bundle it always
    meant: `true` is the delegating bundle a lead has below the top, `false` is a leaf that
    may write — which is what every non-delegating role could do, since writing was gated
    nowhere.

    `fork` is not reachable from the bool in either direction: forking was never a role
    property (it read the `is_top` stamp on the caller), so inferring it from `delegate`
    would hand a capability to rows that never had it.

    Applied per config LAYER, in `config._bundled`, so a repo's `delegate` line and a
    shipped `capabilities` line are two spellings of one field and the later one wins.
    """
    if delegate:
        return frozenset({CAP_SPAWN, CAP_DISPATCH, CAP_WRITE_TRACKED})
    return DEFAULT_CAPABILITIES


def _bundle(fields: dict) -> frozenset:
    """A merged role definition's bundle, or a leaf's if it names none.

    `delegate` is already gone by here — `config._bundled` rewrites it a layer at a time —
    except on a dict handed straight to `load()` by a test or a caller, which is why the
    bool is still understood and still cannot reach the `Role` model.
    """
    if "capabilities" in fields:
        caps = fields["capabilities"]
        return frozenset(c for c in caps if c != config.RESET)
    if "delegate" in fields:
        return bundle_for_delegate(fields["delegate"])
    return DEFAULT_CAPABILITIES


@dataclass
class Role:
    name: str
    model: str = ""                 # a TIER name, not a model id
    prompt: str = ""
    capabilities: frozenset = DEFAULT_CAPABILITIES   # the role's DEFAULT bundle
    tiers: Optional[models.Tiers] = field(default=None, repr=False, compare=False)

    # The bundle is a FIELD, not a check against the literal role name. "Bare" is a
    # property of a kind of agent, and a role named `worker` is only today's spelling of
    # it — vocabulary is data (C12), there is no closed set, and a repo that adds its own
    # leaf role or renames this one would slip straight through `role == "worker"`. It
    # defaults to a leaf's bundle for the same reason every other safety default points
    # that way: a role nobody thought about is a leaf, and being wrong that way costs a
    # refusal a person can lift, not a tree of agents nobody meant to exist.
    #
    # It replaces `delegate: bool`, which answered exactly one question — may this agent
    # spawn — and had to grow a second field for every rule after it. A SET answers the
    # next question by holding another string. A repo file that still says `delegate` maps
    # onto a bundle on the way in (`_bundle`), so nothing on disk breaks.
    #
    # It is a CEILING, not a guarantee: a child is seeded from its template narrowed by
    # what its spawner may pass (the ∩-rule; the broker's `seed_for` is where it lands),
    # so an agent never exceeds either its template or its spawner.

    def __post_init__(self):
        # Defaulted here rather than in the signature, so that even a Role built by hand
        # gets its tier from `[vocabulary]` rather than from a literal in this file.
        self.model = self.model or _default_tier()
        # A list from TOML, a set from a caller: one type past this point, so membership
        # reads the same everywhere and nothing mutates a role's ceiling in place.
        self.capabilities = frozenset(self.capabilities)

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
    return {k: Role(name=k, tiers=tiers, capabilities=_bundle(v),
                    **{f: x for f, x in v.items() if f not in _BUNDLE_FIELDS})
            for k, v in merged.items()}


# The two spellings `_bundle` reads. Kept OUT of the `Role(**v)` splat rather than absorbed
# by the dataclass: `delegate` is gone from the model, and a field the model still accepted
# would be a field somebody could still read.
_BUNDLE_FIELDS = ("capabilities", "delegate")


def get(roles: dict[str, Role], name: str, repo: Optional[Path] = None) -> Role:
    """Unknown roles are fine — they inherit the fallback role's fields but keep their own
    name, so `--as` and ad-hoc roles work without anyone editing a file first.

    Which role is the fallback is `[vocabulary] fallback_role`, not a literal here: what an
    undefined role behaves like is a decision a repo is allowed to make differently.

    An ad-hoc name (`sb delegate --as ...`, `--role archaeologist`) TYPES a role and takes
    the fallback's bundle with everything else. That is not a grant and is no precedent for
    one: it is static, resolved at spawn, and it can only ever hand out a ceiling that
    already exists — nobody gains a capability by inventing a role name for themselves.

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
                capabilities=base.capabilities, tiers=base.tiers)


def template_capabilities(roles: dict[str, Role], name: str, is_top: bool,
                          repo: Optional[Path] = None) -> frozenset:
    """THE BASELINE a live capability set is read against — what an agent of this role
    would be seeded with by a spawner that bounded it by nothing.

    One function because two callers must not disagree about it: `Broker.seed_for` writes
    the seed from it, and `status.collect` renders divergence against it. If the renderer
    kept its own copy of "what a lead normally gets", every row would drift from the truth
    the moment either side moved.

    It is the EFFECTIVE template, not the raw bundle, and the difference is the whole
    reason this is not `Role.capabilities`: `fork` is withheld from every non-top row
    (`seed_for` says why), so reading divergence against the raw bundle would draw `lead−`
    on every lead in the fleet — a marker that fires on everything says nothing. The top
    takes its fixed set (§2.0) and nothing else.

    What it deliberately does NOT include is the ∩ with the spawner's passable set. That
    narrowing is exactly what the marker exists to show: a "lead" seeded by a worker comes
    out short of this, and the row says so.
    """
    if is_top:
        return frozenset(TOP_CAPABILITIES)
    return get(roles, name, repo).capabilities - {CAP_FORK}
