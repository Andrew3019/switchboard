"""The seam that asks a plugin what its agents own and await — sb's side.

WHY A SEAM AND NOT A READ. Steps are a plugin's objects and live in a plugin's state
directory, which sb makes and **never reads inside** (`plugins.state_dir`). But `collect`
cannot derive `awaiting external` — "idle owning ≥1 `blocked` Step and no `active` Step",
migration_sb_v2.md Appendix A — without knowing what an agent owns, and it is the only
place that holds the other half of the join: herdr, the store, and wave 4's three-valued
liveness. So the shape is the board's, which DESIGN-TRUTH already blessed for exactly this
problem: "Rendering plans under the tree is the one thing the plugin cannot do from
outside, so the board grows an extension point — a seam that reads a `board.py` beside the
plugin, hands it the rows of each worktree group, and draws what it returns." This is that
sentence with `derive.py`, `agent_obligations` and a state directory in it. sb hands over
the path and gets back plain data; the plugin is still the only thing that opens a file.

WHAT A PLUGIN CONTRIBUTES, and the whole of the contract:

    derive.agent_obligations(state_dir) -> {
        "steps":  [{"plan", "step", "name", "kind", "state", "owner"}, ...],
        "plans":  {plan_id: condition},
        "owners": {plan_id: [names]},
    }

`state` is one of the five Appendix A Step words; `condition` is one of the three Plan
words. Everything is plain JSON-ish data, because it crosses back into `status.py`, which
must not grow a dependency on a plugin's types.

NOTHING HERE CAN FAIL LOUDLY, for `board.board_hooks`' reason: `sb status` is what a person
runs to find out that something has gone wrong, and a plugin that will not import, a repo
that is not a repo, or a state directory holding a half-written file must cost its own
obligations and nothing else. Every failure path returns an empty `Facts`, and `collect`
then derives exactly what it derived before this module existed.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# The file beside a plugin's `__init__.py` that sb looks for, and the name on it. Two
# constants for one contract, spelled the way `board.BOARD_FILE`/`BOARD_HOOK` are, so a
# plugin author reads the same shape twice rather than two conventions.
DERIVE_FILE = "derive.py"
_STEM = "derive"                                # `DERIVE_FILE` without its extension
DERIVE_HOOK = "agent_obligations"

# The name a plugin package is imported under — `plugins._MODULE_PREFIX`, the same string
# deliberately, so a plugin already imported by an `sb plugin` call in this process (or by
# the board's own seam) is found rather than executed a second time under a second name.
_MODULE_PREFIX = "sb_plugin_"

# `{repo: [(name, hook, state_dir)]}`. Discovered once per process, like the board's, and
# for the same reason: importing is the expensive half, and the collector calls `collect`
# twice a second. What is cached is the PLUGIN and its path, never its state — whether
# there is anything in that directory is asked on every call.
_HOOKS: dict[str, list[tuple[str, Any, Path]]] = {}


@dataclass
class Facts:
    """What every plugin said, flattened — one object `collect` joins its rows against.

    `steps` is every step of every plan in the repo, owned or not: "owns ≥1 `blocked` Step"
    is a statement about one agent, and "the plan's only incomplete Steps are owned by OTHER
    agents" is a statement about the rest of them, so a per-agent shape could not answer the
    second question.
    """

    steps: list[dict] = field(default_factory=list)
    plans: dict[str, str] = field(default_factory=dict)
    owners: dict[str, list[str]] = field(default_factory=dict)

    def owned_by(self, who: str) -> list[dict]:
        return [s for s in self.steps if s.get("owner") == who]

    @property
    def empty(self) -> bool:
        return not self.steps and not self.plans


EMPTY = Facts()


def collect_facts(repo: Optional[Any] = None) -> Facts:
    """Ask every plugin that derives, and flatten the answers. Never raises.

    `repo` is the checkout whose plugin enablement and state directories are read. `None`
    is a caller with no checkout — a test, or a reader outside a repo — and contributes
    nothing, which is exactly the degradation the module note describes: the derived rows
    that need Steps simply do not apply, and every other reading is untouched.
    """
    if repo is None:
        return EMPTY
    out = Facts()
    for _name, hook, state in hooks(Path(repo)):
        try:
            got = hook(state)
        except KeyboardInterrupt:
            raise
        except BaseException:                   # noqa: BLE001 — see the module note
            continue
        if not isinstance(got, dict):
            continue
        steps = got.get("steps")
        if isinstance(steps, list):
            out.steps.extend(s for s in steps if isinstance(s, dict))
        plans = got.get("plans")
        if isinstance(plans, dict):
            out.plans.update({str(k): str(v) for k, v in plans.items()})
        owners = got.get("owners")
        if isinstance(owners, dict):
            for k, v in owners.items():
                if isinstance(v, list):
                    out.owners[str(k)] = [str(x) for x in v if x]
    return out


def hooks(repo: Path) -> list[tuple[str, Any, Path]]:
    """Every enabled plugin that derives obligations, resolved and cached per repo."""
    key = str(repo)
    if key not in _HOOKS:
        try:
            _HOOKS[key] = _discover(repo)
        except KeyboardInterrupt:
            raise
        except BaseException:                   # noqa: BLE001 — see the module note
            _HOOKS[key] = []
    return _HOOKS[key]


def _discover(repo: Path) -> list[tuple[str, Any, Path]]:
    """Import the `derive.py` of every enabled plugin that has one.

    `plugins` is imported HERE and not at the top of the file. This module is reached from
    `status.collect`, which `panel.py` and both boards import, and the import graph a
    renderer is allowed is what `tests/test_panel.py::RendererImports` exists to keep.
    `plugins.state_root` goes through `store.store_dir`, so the resolution stays on the
    command path where a store already exists — and a caller with no repo never gets here
    at all (`collect_facts` returns before this).
    """
    from . import plugins as plugins_mod

    out: list[tuple[str, Any, Path]] = []
    available = plugins_mod.available(repo)
    for name in plugins_mod.enabled(repo):
        d = available.get(name)
        # THE WHOLE COST OF A PLUGIN THAT DERIVES NOTHING: one `is_file`. Nothing is
        # imported, so a fleet whose plugins all derive nothing pays for this seam exactly
        # what it paid before the seam existed.
        if d is None or not (d / DERIVE_FILE).is_file():
            continue
        try:
            mod, hook = _load(name, d)
        except KeyboardInterrupt:
            raise
        except BaseException:                   # noqa: BLE001 — a broken plugin costs the
            continue                            # readout nothing; `sb plugin list` reports it
        if not callable(hook):
            continue
        # `state_root` rather than `state_dir`, because a status readout INITIALISES
        # NOTHING: `state_dir` makes the directory, and a plugin's directory is made by its
        # first command. A plugin whose first command has not run yet is handed the path
        # anyway, so that IT says "nothing to derive" rather than this deciding for it —
        # the same rule `board._state_dir` states, for the same first-use case.
        state = plugins_mod.state_root(str(getattr(mod, "SCOPE", "repo")), repo) / name
        out.append((name, hook, state))
    return out


def _load(name: str, d: Path) -> tuple[object, object]:
    """The plugin package, then its `derive.py`, then the hook on it.

    The PACKAGE first and under the same module name `plugins._import` gives it
    (`sb_plugin_<name>`), so that `derive.py`'s own `from . import …` reaches the plugin it
    is part of and so that a plugin already imported by an `sb plugin` call — or by the
    board's drawer seam, which uses this same prefix — is not imported a second time under
    a second name.
    """
    modname = _MODULE_PREFIX + name
    mod = sys.modules.get(modname)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            modname, d / "__init__.py", submodule_search_locations=[str(d)])
        if spec is None or spec.loader is None:
            raise ImportError(f"{d}/__init__.py is not importable")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod              # before exec: a package imports itself
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(modname, None)
            raise
    derived = importlib.import_module(f"{modname}.{_STEM}")
    return mod, getattr(derived, DERIVE_HOOK, None)
