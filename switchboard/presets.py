"""Presets — drop-in prompt text, per repo.

A preset is one markdown file in `<repo>/.switchboard/presets/<name>.md`. Adding a
behaviour means adding a file; nothing registers it, nothing imports it.

    sb delegate "review PR 42" --role reviewer --with adversarial --with report-bug

This was called a "plugin" until the word was needed for something else. A preset is
prompt text and cannot run; a plugin is Python and can. `.md` versus `.py` is the whole
sorting rule, and it is why the two now have separate names, separate directories, and
separate bindings files. See `.switchboard/design/PLUGIN-REDESIGN.md` §1.

Why files rather than lines in the protocol:

- The protocol is what EVERY agent needs. A preset is what SOME agents need, and paying
  for it on every spawn is exactly the context tax C0 warns about.
- Presets are per-repo, so what switchboard's agents need has no bearing on lore's.
- They are editable without touching code, which is the point of "customizable".

That last one is also why preset FILES are not layered out of `defaults/`, while almost
everything else here is: a shipped preset would arrive in every repo whether or not it
suited the work, and would then have to be argued back out. Only the BINDINGS — which
preset applies to which role — are shipped, in `defaults/presets.toml`, and a repo's
`.switchboard/presets.toml` joins them rather than replacing them.

Files are written multi-line for humans and flattened to a single line on the way out,
because herdr rejects newlines in agent arguments — the constraint that already forced
the protocol out of CLAUDE.md and into the system prompt.

An unrecognised `--with` value is passed through verbatim, so a one-off instruction still
works without creating a file for it.

One notation, two kinds of thing
--------------------------------

A preset and a plugin may share a name, so the `@` sigil says which is meant:

    all = ["own-files", "@todo"]

`own-files` is a preset file; `@todo` is the fragment shipped by the plugin `todo`. Three
rules, in this order (§3.3):

- `@<name>` that does not resolve to an enabled plugin with an `agent.md` FAILS. The `@`
  prefix is reserved and there is no literal passthrough for it.
- A **bare** name matching no preset file but matching an enabled plugin is an ERROR
  naming the sigil. Without this, `--with todo` ships the one-word string `"todo"` into a
  system prompt: it looks like success and is not.
- Every other bare name behaves exactly as before — preset file if one matches, otherwise
  literal passthrough.

Resolving `@<name>` reads one markdown file and stops. Nothing here imports a plugin, and
that is the property the whole load model of `plugins.py` rests on: `delegate` is the verb
the entire system runs on, and it has never heard of plugin code.

How a fragment fails depends on how it was asked for
----------------------------------------------------

`explicit` is the set of names the caller named by hand — `delegate`'s `extra`, which is
`--with`. A fragment in it that will not resolve raises; one that arrived from a binding in
`presets.toml` is skipped with a note, because delegation must not fail over somebody's
half-installed todo plugin. The default is the empty set, and that is the correct default
rather than merely a compatible one: a name nobody typed is a binding.

The bare-name rule is NOT asymmetric, and the difference is the point. `@todo` failing is
a statement about this machine — the plugin is not installed here yet — which is a
condition a spawn should survive. A bare `todo` is a statement about the file: there is no
reading under which shipping the literal word was intended, and it is wrong everywhere the
file is read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Collection, Iterable, Optional

from . import config
from . import plugins as plugins_mod
from . import validate

# What tells a plugin's fragment from a preset file wherever prompt text is named.
SIGIL = "@"

# Named in the error you get for a plugin that is available but off, because that error's
# whole job is to say where the fix goes. Assembled from `[paths]` so it cannot become a
# lie the day someone moves the file.
_ENABLEMENT_HINT = "{}/{}".format(config.setting("paths.repo_dir"),
                                  config.setting("paths.plugins_file"))

# Both of these are `[paths]` entries in settings.toml — see config.py. The functions stay
# because "where do presets live" is a question the rest of the code should ask rather than
# assemble for itself.
#
# Each reads the new key and falls back to the pre-rename one, so a repo still holding
# `.switchboard/plugins/` and `.switchboard/plugins.toml` keeps working untouched. There is
# no flag day: the fallback only applies when the new spelling is genuinely absent, so a
# repo that has moved never looks at the old path again.


def preset_dir(repo: Path) -> Optional[Path]:
    return config.path_for_legacy("presets_dir", "plugins_dir", repo)


def bindings_file(repo: Path) -> Optional[Path]:
    return config.path_for_legacy("presets_file", "plugins_file", repo)


def available(repo: Path) -> dict[str, Path]:
    """Every preset this repo can name — shipped ones, then the repo's own.

    Layered like everything else in `defaults/`: a repo's `<name>.md` replaces the shipped
    one of that name, and a repo with no preset directory still gets all the shipped ones.
    Without this the shipped `presets.toml` bound names to files that only existed in an
    untracked directory, so a fresh clone had bindings pointing at nothing.
    """
    found: dict[str, Path] = {}
    shipped = config.defaults_dir() / "presets"
    for d in (shipped, preset_dir(repo)):
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
    return config.preset_bindings(repo)


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


def resolve(
    names: Iterable[str],
    repo: Optional[Path] = None,
    *,
    explicit: Collection[str] = frozenset(),
    on_event: Optional[Callable[..., None]] = None,
) -> list[str]:
    """Turn `--with` values and bindings into prompt lines.

    `@<name>` becomes that plugin's `agent.md`, clipped to its budget. A name that matches
    a preset file becomes that file's contents. Anything else is a literal instruction, so
    throwaway customization needs no file at all.

    `explicit` is the names the caller named by hand; see the module docstring for why a
    fragment in it raises where one from a binding is skipped. `on_event` is how the two
    non-fatal outcomes — a skipped fragment and a truncated one — reach the store and,
    for the ones a person should see, stderr. It takes `store.log_event`'s keywords, so a
    caller holding a database handle passes one line. No callback means no reporting,
    which is what a test or a `--json` reader wants.
    """
    repo = Path(repo or Path.cwd())
    found = available(repo)
    out = []
    for n in names:
        if n.startswith(SIGIL):
            line = _fragment(repo, n[len(SIGIL):],
                             explicit=n in explicit, on_event=on_event)
        elif n in found:
            line = flatten(found[n].read_text())
        elif n in plugins_mod.enabled(repo):
            # The one-word-string failure, made loud. Not conditioned on `explicit`: a
            # bare plugin name is wrong however it arrived.
            raise validate.Invalid(
                f"'{n}' is a plugin fragment — write '{SIGIL}{n}'")
        else:
            line = n
        if line:
            out.append(line)
    return out


def _fragment(repo: Path, name: str, *, explicit: bool,
              on_event: Optional[Callable[..., None]]) -> Optional[str]:
    """One `@<name>`, resolved — or the failure, rendered per its provenance.

    An enabled plugin is required, not merely an available one: enabled is the state that
    says this repo runs the thing, and injecting instructions for verbs that will not
    dispatch tells an agent to run commands it cannot.
    """
    line = plugins_mod.fragment(repo, name) if name in plugins_mod.enabled(repo) else None
    if not line:
        why = _unresolved(repo, name)
        if explicit:
            raise validate.Invalid(why)
        _report(on_event, kind="fragment_skipped", plugin=name, reason=why)
        return None
    clipped = plugins_mod.clip(line)
    if clipped != line:
        # Logged rather than printed: the fragment still went out, the spawn was fine, and
        # the person who needs to know is whoever edits agent.md next — not whoever is
        # delegating right now.
        _report(on_event, kind="fragment_truncated", plugin=name,
                chars=len(line), limit=plugins_mod.FRAGMENT_BUDGET)
    return clipped


def _unresolved(repo: Path, name: str) -> str:
    """Why `@<name>` did not resolve, phrased for whoever has to fix it.

    Three distinct conditions with three distinct fixes, so they get three distinct
    sentences: one message covering all of them would send you to the wrong file twice
    before the right one.
    """
    at = f"{SIGIL}{name}"
    if name not in plugins_mod.available(repo):
        return f"'{at}' names no plugin — see `sb plugin list`"
    if name not in plugins_mod.enabled(repo):
        return (f"'{at}' is not enabled — add it to {_ENABLEMENT_HINT}: "
                f'enabled = ["{name}"]')
    return (f"'{at}' has no agent.md, so the plugin '{name}' contributes no prompt text")


def _report(on_event: Optional[Callable[..., None]], **payload: Any) -> None:
    if on_event is not None:
        on_event(**payload)


# -- the transition, reported rather than enforced (§8.2) ----------------------


def deprecations(repo: Path) -> list[str]:
    """Pre-rename spellings still on disk, each with the exact command that moves it.

    There is no flag day. `.switchboard/plugins/` holding `*.md` and `.switchboard/plugins.toml`
    holding `all`/`[roles]` both still work — a preset is a FILE and a plugin is a DIRECTORY
    with an `__init__.py`, and the two TOML vocabularies are disjoint, so nothing has to
    guess. What is missing without this is any signal that a repo is on the old spelling at
    all, and the whole job of `sb doctor` is to say so out loud before the fallback is
    someday retired.

    Notices, not problems: nothing here is broken and none of it changes the exit code. The
    `git mv` is exact so the fix is a paste, not a puzzle.
    """
    out: list[str] = []
    d = config.repo_dir(repo)
    if d is None:
        return out

    old_dir = config.path_for("plugins_dir", repo)
    new_dir = config.path_for("presets_dir", repo)
    stale = sorted(p for p in old_dir.glob("*.md")) if old_dir and old_dir.is_dir() else []
    for p in stale:
        note = (f"preset in the pre-rename directory: {_rel(p, repo)}\n"
                f"       git mv {_rel(p, repo)} {_rel(new_dir / p.name, repo)}")
        # Only when the new directory is genuinely absent is the old one still read
        # (`config.path_for_legacy`). Once it exists, the old one is dead weight that looks
        # live — a strictly worse state than being on the old spelling, and the one worth
        # shouting about.
        if new_dir is not None and new_dir.is_dir():
            note += (f"\n       (ignored — {_rel(new_dir, repo)}/ exists, so nothing "
                     f"reads this file)")
        out.append(note)

    old_file = config.path_for("plugins_file", repo)
    new_file = config.path_for("presets_file", repo)
    if old_file is not None and old_file.is_file():
        data = config.read_toml(old_file)
        binds = [k for k in ("all", "roles") if k in data]
        if binds:
            what = " and ".join(f"`{k}`" for k in binds)
            if "enabled" in data:
                # Both meanings in one file. It parses correctly — the keys are disjoint —
                # but `git mv` would carry the enablement away with the bindings, so the
                # fix is a split and saying "mv" here would be wrong.
                out.append(
                    f"{_rel(old_file, repo)} holds both meanings: {what} are preset "
                    f"bindings, `enabled` is plugin enablement\n"
                    f"       move {what} into {_rel(new_file, repo)} and leave "
                    f"`enabled` where it is")
            elif new_file is not None and new_file.is_file():
                out.append(
                    f"preset bindings in {_rel(old_file, repo)} are ignored — "
                    f"{_rel(new_file, repo)} exists and wins\n"
                    f"       merge {what} into {_rel(new_file, repo)} and delete the old file")
            else:
                out.append(
                    f"preset bindings in the pre-rename file: {_rel(old_file, repo)}\n"
                    f"       git mv {_rel(old_file, repo)} {_rel(new_file, repo)}")
    return out


def _rel(p: Path, repo: Path) -> str:
    """Relative to the worktree when it can be, so the `git mv` is runnable where you are.

    Deliberately not resolved: `.switchboard/` is frequently a symlink into the main
    checkout, and resolving it would take the path outside the worktree and turn a runnable
    `git mv` into an absolute one that git may refuse.
    """
    try:
        return str(Path(p).relative_to(Path(repo)))
    except ValueError:
        return str(p)
