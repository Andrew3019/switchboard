"""Prompt plugins — drop-in behaviour, per repo.

A plugin is one markdown file in `<repo>/.switchboard/plugins/<name>.md`. Adding a
behaviour means adding a file; nothing registers it, nothing imports it.

    sb delegate "review PR 42" --role reviewer --with adversarial --with report-bug

Why files rather than lines in the protocol:

- The protocol is what EVERY agent needs. A plugin is what SOME agents need, and paying
  for it on every spawn is exactly the context tax C0 warns about.
- Plugins are per-repo, so what switchboard's agents need has no bearing on lore's.
- They are editable without touching code, which is the point of "customizable".

That last one is also why plugin FILES are not layered out of `defaults/`, while almost
everything else here is: a shipped plugin would arrive in every repo whether or not it
suited the work, and would then have to be argued back out. Only the BINDINGS — which
plugin applies to which role — are shipped, in `defaults/plugins.toml`, and a repo's
`.switchboard/plugins.toml` joins them rather than replacing them.

Files are written multi-line for humans and flattened to a single line on the way out,
because herdr rejects newlines in agent arguments — the constraint that already forced
the protocol out of CLAUDE.md and into the system prompt.

An unrecognised `--with` value is passed through verbatim, so a one-off instruction still
works without creating a file for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from . import config

# Both of these are `[paths]` entries in settings.toml — see config.py. The functions stay
# because "where do plugins live" is a question the rest of the code should ask rather than
# assemble for itself.


def plugin_dir(repo: Path) -> Path:
    return config.path_for("plugins_dir", repo)


def bindings_file(repo: Path) -> Path:
    return config.path_for("plugins_file", repo)


def available(repo: Path) -> dict[str, Path]:
    """Every plugin this repo can name — shipped ones, then the repo's own.

    Layered like everything else in `defaults/`: a repo's `<name>.md` replaces the shipped
    one of that name, and a repo with no plugin directory still gets all the shipped ones.
    Without this the shipped `plugins.toml` bound names to files that only existed in an
    untracked directory, so a fresh clone had bindings pointing at nothing.
    """
    found: dict[str, Path] = {}
    shipped = config.defaults_dir() / "plugins"
    for d in (shipped, plugin_dir(repo)):
        if d is None or not d.is_dir():
            continue
        found.update({f.stem: f for f in sorted(d.glob("*.md"))})
    return found


def flatten(text: str) -> str:
    """Markdown on disk, one line on the wire. See `config.flatten` — the same rule applies
    to the protocol, to role prompts, and to these, so it lives in one place."""
    return config.flatten(text)


def bindings(repo: Path) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Returns (applied to every agent, per-role additions).

    Shipped bindings joined with this repo's: a repo adding one must not wipe the others.
    """
    return config.plugin_bindings(repo)


def for_role(repo: Path, role: str, extra: Iterable[str] = ()) -> list[str]:
    """Layered, most general first: every-agent -> this role -> the caller's `--with`.

    Each layer APPENDS. A role adds to the repo baseline and a caller adds to both, so
    neither can silently drop something the repo decided every agent should have.
    """
    every, per_role = bindings(repo)
    out = list(every)
    for n in (*per_role.get(role, ()), *extra):
        if n not in out:
            out.append(n)
    return out


def resolve(names: Iterable[str], repo: Optional[Path] = None) -> list[str]:
    """Turn `--with` values into prompt lines.

    A name that matches a file becomes that file's contents. Anything else is treated as
    a literal instruction, so throwaway customization needs no file at all.
    """
    repo = Path(repo or Path.cwd())
    found = available(repo)
    out = []
    for n in names:
        if n in found:
            line = flatten(found[n].read_text())
            if line:
                out.append(line)
        else:
            out.append(n)
    return out
