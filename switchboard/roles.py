"""Role profiles.

A role is a spawn profile: which model tier, and the prompt that tells an agent who it
is. Vocabulary is data (C12): repositories may add definitions, while callers still have
to select one of the effective roles or use the explicit ad-hoc prompt path.

A role names a TIER only. What a tier maps to — provider, model, effort — is models.py's
job, so no model name appears here. And no role name, disposition or prompt appears here
either: the definitions are files, one markdown file per role, read by config.py.

    defaults/roles/<name>.md          shipped
    <enabled plugin>/roles/<name>.md  plugin-specific specialists
    <repo>/.switchboard/roles.toml    this repo's overrides
    <repo>/.switchboard/roles/*.md    this repo's own roles, in the same form

Later layers override earlier ones FIELD BY FIELD, so changing a reviewer's tier keeps its
prompt. See config.py for the merge rules.
"""

from __future__ import annotations

import difflib
import re
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

# THE SIDE-EFFECT CLASS (spec §2.1, unit E4). `write-tracked` above is ONE INSTANCE of it,
# and this is the reader that makes the class a class: which capability strings name *an
# action that produces a side effect sb mediates, and that therefore wants review before it
# lands*, and which sb-mediated BOUNDARY each is checked at. It is DATA — a table in
# `[capabilities.side_effects]`, shipped with one row and extensible by any repo — for the
# same reason the capability vocabulary is open-ended: a deploy repo whose dangerous action
# is `terraform apply` mints `deploy` there and gets the same grant/seed/enforcement
# mechanics with no structural change and no second refusal function.
#
# NOT A SECURITY CONTROL, and the code that reads this must not be built as one. There is
# no filesystem chokepoint anywhere in sb (`hooks.py` installs `UserPromptSubmit` and
# `Stop`; there is no `PreToolUse`), so every instance of this class is a POST-HOC check on
# the sanctioned path, never a preventive per-write gate. This is substrate generality:
# the substrate is more general than the one instance shipped on it.
#
# `write-tracked`'s semantics are NOT stretched to cover cloud state. It would gate the
# `.tf` EDIT — the safe half — and be silent on the APPLY, and two agents in two isolated
# worktrees can each still apply against the same state file. The answer to that repo is
# its own string in this table, not a wider reading of this one.
def side_effect_capabilities(repo: Optional[Path] = None) -> dict[str, tuple[str, ...]]:
    """`{capability: the boundaries it is checked at}` for this repo.

    Read fresh rather than frozen at import: a repo's `.switchboard/settings.toml` is one
    of the layers, so freezing it would mean the shipped table was the only one that could
    ever be true.

    `start` is dropped whatever any file says, for the one reason it is dropped from
    `Broker.known_capabilities`: it is not a capability, it is a hardcoded human-only gate,
    and no path may make it grantable — including this one, which feeds that vocabulary.
    """
    table = config.setting("capabilities.side_effects", {}, repo=repo)
    if not isinstance(table, dict):
        raise config.ConfigError(
            "[capabilities.side_effects] must be a table of `capability = [boundary, ...]`, "
            f"got {table!r}")
    out: dict[str, tuple[str, ...]] = {}
    for cap, boundaries in table.items():
        if cap == "start":
            continue
        if isinstance(boundaries, str):     # one boundary, unbracketed — meant, not a typo
            boundaries = [boundaries]
        if not isinstance(boundaries, list) or any(not isinstance(b, str) for b in boundaries):
            raise config.ConfigError(
                f"side-effect capability '{cap}' must name the boundaries it is checked at "
                f"as a list of strings, got {boundaries!r}")
        out[cap] = tuple(b for b in boundaries if b != config.RESET)
    return out


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
    # How far an agent of this role may tune ITSELF with `sb configure` — the E3 ceiling,
    # `{setting: furthest permitted value}` for the settings this role wants bounded
    # differently from the shipped default. A role that names none inherits every ceiling
    # from `[config.settings]`, which is why the default is empty rather than the full
    # table: this field is the role's OVERRIDE, and `template_ceiling` is where the two
    # layers meet. Not a frozenset because a ceiling is a value per setting, not a
    # membership question.
    config_ceiling: dict = field(default_factory=dict)
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
        self.config_ceiling = dict(self.config_ceiling or {})

    def spec(self, override: Optional[str] = None) -> models.ModelSpec:
        """The resolved provider + model + effort for this role's tier.

        Everything the spawn layer needs is on the returned spec; see
        `ModelSpec.cli_args()`. Raw model ids require the explicit ``raw:<id>`` selector.

        `override` is a per-call tier name (`sb delegate --model strong`). It goes through
        the same table as the role's own, which is the whole point: a caller that names a
        tier gets that tier's effort too, and neither path can hand a raw tier name to a
        provider CLI. There is deliberately no `model_id()` shortcut any more — it existed,
        it dropped effort silently, and every caller of it was a bug.

        THE ROLE GATE LIVES HERE, and here is the only place it can: a tier that names
        `forbidden_roles`, or that hangs off a settings switch, is refused for THIS role,
        and this method is the one point in the tree where a tier and the role about to run
        on it are both in hand. Every spawn path funnels through it — `Broker.delegate`,
        `sb start`'s top, and the `sb instructions` preview — so the refusal lands before a
        pane exists rather than as an agent already running on a tier meant to be kept away
        from it. It applies to the role's OWN tier as much as to an override: "this role
        may never run on that tier" is a fact about the pair, not about who typed the name.
        """
        spec = (self.tiers or models.load()).resolve(override or self.model)
        spec.gate(self.name)
        return spec

    def stored_spec(self, override: Optional[str] = None) -> models.ModelSpec:
        """Resolve an override read from an existing agent row.

        NO GATE, unlike `spec()` above, and the difference is what the two are for. This
        reads a tier already recorded against an agent that exists — a restore, or the
        codex stickiness read in `Broker.delegate` — and a tier only got into that column
        by passing the gate on the way in. Re-checking it here would mean a settings switch
        flipped off, or a role added to `forbidden_roles`, made a live agent unrestorable;
        a restore should bring an agent back on the tier it was actually running. The
        stickiness read re-resolves through `spec()` before anything spawns, so nothing
        reaches a pane ungated.
        """
        tiers = self.tiers or models.load()
        return tiers.resolve_stored(override) if override else tiers.resolve(self.model)


def load(repo: Optional[Path] = None) -> dict[str, Role]:
    """Role definitions only — what an agent IS.

    Which behaviours get injected into it is a separate concern; see presets.py.
    """
    merged = config.roles(repo)
    tiers = models.load(repo)
    return {k: Role(name=k, tiers=tiers, capabilities=_bundle(v),
                    config_ceiling=_declared_ceiling(v),
                    **{f: x for f, x in v.items() if f not in _BUNDLE_FIELDS})
            for k, v in merged.items()}


# The two spellings `_bundle` reads. Kept OUT of the `Role(**v)` splat rather than absorbed
# by the dataclass: `delegate` is gone from the model, and a field the model still accepted
# would be a field somebody could still read.
_BUNDLE_FIELDS = ("capabilities", "delegate", "config_ceiling")


def get(roles: dict[str, Role], name: str, repo: Optional[Path] = None) -> Role:
    """Resolve a configured role or alias, accepting only unique spelling variants.

    Ad-hoc behaviour is explicit through ``sb delegate --as`` and still uses a configured
    role as its capability/model profile. An unknown ``--role`` is therefore a typo, not
    an implicit custom role with the fallback profile.

    `repo` is what makes "a repo is allowed to decide differently" true rather than merely
    stated. Both settings this reads are layered — shipped, then the repo's own — and both
    were being read with no repo at all, which resolves the shipped layer and stops. A repo
    that retired a role of its own and wrote the alias for it in `.switchboard/settings.toml`
    got silence: the name was refused exactly as if the alias had never been written.
    Every caller in the broker has a repo and passes it; the default is for tests that only
    care about the shipped table.

    A RETIRED name is a different case from a name nobody ever defined: `orchestrator` used
    to mean "an agent that owns this and splits it". So `[vocabulary] role_aliases` maps
    an old name onto the role that replaced it, and the alias resolves ALL the way — the
    returned Role carries the new name, so the board, the prompt and the stored row all say
    what the agent actually is rather than what it was typed as. Data, not a literal here,
    for the same reason every other name in this file is (C12).
    """
    if name in roles:
        return roles[name]
    aliases = config.setting("vocabulary.role_aliases", repo=repo)
    alias = aliases.get(name)
    if alias and alias in roles:
        return roles[alias]

    key = _lookup_key(name)
    pairs = [(n, n) for n in roles]
    pairs.extend((n, target) for n, target in aliases.items() if target in roles)
    resolved = {target for spelling, target in pairs if _lookup_key(spelling) == key}
    if len(resolved) == 1:
        return roles[resolved.pop()]
    if len(resolved) > 1:
        raise RoleConfigError(
            f"role {name!r} is ambiguous; use one of these exact names: "
            f"{', '.join(sorted(resolved))}")

    vocabulary = sorted(set(roles) | set(aliases))
    nearby = difflib.get_close_matches(name, vocabulary, n=4, cutoff=0.35)
    shown = ", ".join(nearby or vocabulary[:8]) or "(none configured)"
    raise RoleConfigError(
        f"no role {name!r}; nearby choices: {shown}. Run `sb roles` for the live table, "
        "or use `--as <prompt>` with a configured role for an explicit custom prompt")


class RoleConfigError(ValueError):
    """A caller named no unique role in the effective repository vocabulary."""


def _lookup_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def get_or_fallback(roles: dict[str, Role], name: str,
                    repo: Optional[Path] = None) -> Role:
    """Resolve live vocabulary, retaining old stored custom roles as worker-shaped rows.

    User-facing selection uses strict ``get``. This compatibility path is only for facts
    already in the store and internal template probes, where refusing an old row would
    make it unrestorable or unreadable after the vocabulary migration.
    """
    try:
        return get(roles, name, repo)
    except RoleConfigError:
        fallback = config.setting("vocabulary.fallback_role", repo=repo)
        base = roles.get(fallback) or Role(fallback)
        return Role(name=name, model=base.model, prompt=base.prompt,
                    capabilities=base.capabilities, config_ceiling=base.config_ceiling,
                    tiers=base.tiers)


def template_capabilities(roles: dict[str, Role], name: str, is_top: bool,
                          repo: Optional[Path] = None) -> frozenset:
    """THE BASELINE a live capability set is read against — what an agent of this role
    would be seeded with by a spawner that bounded it by nothing.

    One function because two callers must not disagree about it: `Broker.seed_for` writes
    the seed from it, and `status.collect` renders divergence against it. If the renderer
    kept its own copy of "what a lead normally gets", every row would drift from the truth
    the moment either side moved.

    It is the EFFECTIVE template rather than the raw bundle, and the top is the whole of
    the difference now: a stamped top takes its fixed set (§2.0) and nothing else, whatever
    its role template says.

    **`fork` USED TO BE SUBTRACTED HERE FROM EVERY NON-TOP ROW, and D2 removed that.** It
    was withheld because the fork decision read the caller's capability set, so a lead
    holding `fork` would have had EVERY one of its spawns silently minted a new workspace;
    the template naming it was a ceiling — "may be granted isolation" — with no request
    site to spend it at. Both halves are gone: `delegate(isolation="own")` is that site,
    and the decision reads the `is_top` STAMP again with `shared` as the default for
    everyone else (`Broker.mints_space`, `Broker.isolates`). So a lead now ARRIVES able to
    isolate a child that asks for it, and its ordinary spawns are unaffected — which is the
    point, because needing `sb grant fork` before every fan-out is the bureaucracy the
    capability set exists to remove. Only a role whose template names `fork` gains anything
    (of the shipped roles, `lead`); the rest are unchanged because their bundles never
    named it.

    What it deliberately does NOT include is the ∩ with the spawner's passable set. That
    narrowing is exactly what the marker exists to show: a "lead" seeded by a worker comes
    out short of this, and the row says so.
    """
    if is_top:
        return frozenset(TOP_CAPABILITIES)
    return get_or_fallback(roles, name, repo).capabilities


# ---------------------------------------------------------------------------
# The config ceiling — how far an agent may tune ITSELF (spec §2.4, unit E3)
# ---------------------------------------------------------------------------
#
# `sb configure` is the second thing a role template bounds, and it lives here beside the
# first for one reason: both are the template's answer to a question about an agent, and
# keeping "what may this role do" and "how far may this role tune itself" in one file is
# what stops them being read off two different things. They are NOT the same question,
# and the resolver answering both is a property rather than a contradiction (spec §2.4):
# capabilities are LIVE — seeded, then grown by `sb grant`, read fresh at every gate —
# while the ceiling is FIXED, because it is read off `role`, which is stamped at spawn and
# never rewritten (§6.10).
#
# THE CEILING IS THE TEMPLATE'S AND NOT THE PARENT'S, and that is the whole design
# decision. `parent` is mutable — `sb promote` re-homes an agent under somebody else — so
# a ceiling derived from the parent would mean a promote ABOVE an agent silently changed
# what that agent may do to its own reminders, with nothing in the log and nobody having
# asked for it. The role never moves, so neither does the ceiling.


# The key naming a setting's starting value in `[config.settings]`. A constant because
# `test_config` forbids these modules from carrying a literal that collides with a TIER
# name, and `default` is one — which is the same reason the TOML key is spelled this way.
INITIAL = "initial"


class ConfigRefused(ValueError):
    """A `sb configure` that was refused. `ValueError` so `cli.main` prints it as one line."""


def settings_spec(repo: Optional[Path] = None) -> dict:
    """The setting vocabulary: `{name: {kind, default, ceiling, ...}}`, from settings.toml.

    Data for the same reason the capability strings are a set rather than a field per rule:
    a new knob is a table in `[config.settings]`, not another branch in the CLI. A repo may
    add its own — the settings file merges table by table — and every path below is written
    against the spec rather than against the two names shipped today.
    """
    return config.setting("config.settings", repo=repo)


def _declared_ceiling(fields: dict) -> dict:
    """A merged role definition's own `[config_ceiling]`, or nothing."""
    raw = fields.get("config_ceiling") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def template_ceiling(roles: dict[str, "Role"], name: str,
                     repo: Optional[Path] = None) -> dict:
    """How far an agent of this role may tune each setting, ever.

    `template_capabilities`' twin, and deliberately the same shape of function: ONE place
    that answers what a template says, so the gate that refuses a value and the readout
    that prints the ceiling cannot come to disagree about it.

    A role that names no ceiling of its own inherits the one in `[config.settings]`. There
    is no `is_top` branch here and that is deliberate: the top's capability set is fixed
    because a second top would be a topology event (§2.0), while how loudly the dispatcher
    wants to be reminded of things is an ordinary preference with nothing structural in it.
    """
    spec = settings_spec(repo)
    mine = get_or_fallback(roles, name, repo).config_ceiling
    return {k: mine.get(k, v.get("ceiling")) for k, v in spec.items()}


def split_setting(setting: str) -> tuple[str, Optional[str]]:
    """`reminders.merge` -> `("reminders", "merge")`; `debounce` -> `("debounce", None)`.

    The dotted form is how a setting is addressed per reminder CATEGORY, and it is one
    name space rather than two so that the ceiling, the store row and the refusal all key
    on the same string an agent typed.
    """
    base, _, category = setting.partition(".")
    return base, category or None


def check_setting(setting: str, repo: Optional[Path] = None) -> tuple[str, Optional[str]]:
    """Refuse anything that is not a setting, before a value is even looked at.

    THE CLOSED VOCABULARY IS THE ANSWER TO "no self-widening by ANY path" (spec §2.1, plan
    E3 obj. 5). `sb configure` tunes config and never rights, and the way that is enforced
    is that a capability string is simply not a setting name — `sb configure spawn true`
    finds no `[config.settings.spawn]` table and is refused here, in the same breath as a
    typo, rather than by a special case that has to remember to name every capability.
    """
    spec = settings_spec(repo)
    base, category = split_setting(setting)
    if base not in spec:
        raise ConfigRefused(
            f"no such setting `{setting}` — `sb configure` tunes how loudly switchboard "
            f"talks to you, one of: {', '.join(sorted(spec))}. It never changes what an "
            f"agent may DO; that is a capability, and capabilities are granted from above "
            f"with `sb grant`, never set by the agent that wants one.")
    if category and not spec[base].get("per_category"):
        raise ConfigRefused(
            f"`{base}` is one value for this agent, not one per category — set it as "
            f"`sb configure {base} <value>`.")
    return base, category


def check_value(setting: str, raw: str, *, role: str, ceiling,
                repo: Optional[Path] = None):
    """The typed, ceiling-bounded value this setting may take, or a refusal saying why not.

    The refusal is written in the style of `Broker._capability_refusal` on purpose: an
    agent meets both of these the same way — it asked for something and was told no — and
    the two messages are the whole of what it can act on. So each says what was asked for,
    what bounds it, and what to do instead.
    """
    spec = settings_spec(repo)[split_setting(setting)[0]]
    kind = spec.get("kind", "enum")
    if kind == "int":
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise ConfigRefused(
                f"`{setting}` is a number of seconds, and `{raw}` is not one.") from None
        if value < 0:
            raise ConfigRefused(f"`{setting}` cannot be negative.")
        if ceiling is not None and value > int(ceiling):
            raise ConfigRefused(_ceiling_refusal(setting, raw, role, ceiling))
        return value
    values = list(spec.get("values") or [])
    value = str(raw).strip()
    if value not in values:
        raise ConfigRefused(
            f"`{setting}` is one of: {', '.join(values)} — not `{raw}`.")
    if ceiling is not None and ceiling in values and values.index(value) > values.index(ceiling):
        raise ConfigRefused(_ceiling_refusal(setting, value, role, ceiling))
    return value


def _ceiling_refusal(setting: str, asked, role: str, ceiling) -> str:
    """What an agent that asked to go past its ceiling is told.

    It names the ROLE, because that is the thing the ceiling is pinned to and the one fact
    that makes the refusal actionable: nothing above this agent can lift it, no grant
    exists for it, and being promoted under somebody more permissive will not move it
    either. The way past it is a person editing the role template — which is a decision
    about every agent of that role, made once, in a file, rather than per agent at
    run time.
    """
    return (f"a {role} may not set `{setting}` to `{asked}`: its role template allows at "
            f"most `{ceiling}`. That ceiling is the ROLE TEMPLATE'S, so nobody above you "
            f"can lift it and being re-homed under another agent does not move it — "
            f"`sb configure {setting} {ceiling}` is as far as this role goes.")


def effective_config(stored: dict, ceiling: dict, repo: Optional[Path] = None) -> dict:
    """What this agent's settings actually ARE: the defaults, overlaid by what it set,
    with anything now out of range pulled back to the ceiling.

    THE CLAMP IS ON THE READ, not only on the write, and that is what makes the ceiling a
    ceiling rather than a check somebody once passed: a role template narrowed after an
    agent configured itself would otherwise leave that agent running past the new bound
    for the rest of its life, with the stored row as the only evidence.

    Per-category keys ride through untouched — they are read against the same base
    setting's ceiling by the same clamp, one entry at a time.
    """
    spec = settings_spec(repo)
    out = {k: v.get(INITIAL) for k, v in spec.items()}
    for key, raw in stored.items():
        base, _ = split_setting(key)
        if base not in spec:
            continue                      # a setting this repo has since retired
        try:
            out[key] = check_value(key, raw, role="", ceiling=ceiling.get(base), repo=repo)
        except ConfigRefused:
            out[key] = _clamped(spec[base], ceiling.get(base))
    return out


def _clamped(spec: dict, ceiling):
    """The furthest value still allowed — what a stored value that is now too far reads as."""
    if ceiling is None:
        return spec.get(INITIAL)
    return int(ceiling) if spec.get("kind") == "int" else ceiling
