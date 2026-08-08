# defaults/ — the shipped configuration

Everything switchboard knows out of the box, in files rather than in Python. Roles, model
tiers, preset bindings, the agent protocol, the spawn prompts, and every number worth
tuning live here. `switchboard/config.py` is the only thing that reads them.

Not dot-prefixed on purpose. This is the reference copy: you are meant to open it, read it,
and copy pieces of it into your own repo. A hidden directory says "internal", and these
files are the opposite of internal.

## Layering

For any repo, two layers, most general first:

    defaults/                 (this directory — shipped, never edited per repo)
    <repo>/.switchboard/      (that repo's own)

`defaults/` alone is a complete, working configuration: switchboard runs in a repo with no
`.switchboard/` at all. A repo's own layer only says what differs.

| shipped                     | repo override                          |
| --------------------------- | -------------------------------------- |
| `defaults/roles/<name>.md`  | `.switchboard/roles/<name>.md`, `.switchboard/roles.toml` |
| `defaults/models.toml`      | `~/.config/switchboard/models.toml`, then `.switchboard/models.toml` |
| `defaults/presets.toml`     | `.switchboard/presets.toml`            |
| `defaults/presets/<name>.md`| `.switchboard/presets/<name>.md`       |
| `defaults/plugins.toml`     | `.switchboard/plugins.toml`            |
| `defaults/plugins/<name>/`  | `.switchboard/plugins/<name>/`         |
| `defaults/protocol.md`      | `.switchboard/protocol.md`             |
| `defaults/prompts.toml`     | `.switchboard/prompts.toml`            |
| `defaults/settings.toml`    | `.switchboard/settings.toml`           |

Preset *files* are layered too — `defaults/presets/<name>.md`, replaced by name by a repo's
`.switchboard/presets/<name>.md`. This reverses an earlier decision, and the reversal is
worth stating rather than quietly reflecting: preset files were originally *not* shipped, on
the grounds that what switchboard's own agents need has no bearing on another repo's. That
held until `defaults/presets.toml` started shipping bindings, at which point a fresh clone
had bindings pointing at files that existed only in an untracked directory.

What survives the reversal is the distinction it was protecting, now carried by binding
instead of by shipping: **shipping a preset makes it nameable; only a binding makes it
applied.** Six preset files ship and none of them is bound by default, so a repo that wants
none of them pays nothing for their presence.

Both were called "plugins" until the word was needed for code that runs. A preset is
markdown and cannot run; a plugin is Python and can. A repo still holding the pre-rename
`.switchboard/plugins/` and `.switchboard/plugins.toml` is read from there until it moves.

Plugin *packages* — `defaults/plugins/<name>/`, holding an `__init__.py` — are layered by
name, and a repo's directory replaces a shipped one of that name wholesale rather than
merging field by field, which is the only rule that makes sense for code. They share
`.switchboard/plugins/` with the pre-rename presets during the transition and are told
apart by shape: a `<name>.md` FILE is a preset, a `<name>/` DIRECTORY with an
`__init__.py` is a plugin. Nothing has to guess, and there is no flag day.

## Merge rules

The override layer **joins** the base; it does not replace it. Three rules, applied
recursively and identically to every file above:

1. **Tables merge, key by key.** Overriding one field of a role, or one field of a model
   tier, leaves the rest of that role or tier alone.
2. **Scalars replace.** A string, number or boolean in the override wins outright.
3. **Arrays join.** The base's items come first, then the override's, with duplicates
   dropped and order preserved. Adding a preset binding therefore cannot wipe a shipped
   one — which is the whole reason joining is the default.

To *replace* an array instead of joining it, make `"!reset"` its first element:

    all = ["!reset", "own-files"]     # exactly own-files, whatever was shipped

Everything about this is tested in `tests/test_config.py`.

## Pointing switchboard somewhere else

`SWITCHBOARD_DEFAULTS=/path/to/dir` replaces this directory wholesale. Used by the test
suite; also the escape hatch for shipping a different baseline to a team.

## File tour

| file                | what it holds                                                      |
| ------------------- | ------------------------------------------------------------------ |
| `roles/*.md`        | one role each: TOML front matter for the fields, markdown for the prompt |
| `models.toml`       | what `cheap`, `default`, `strong` mean — the only place model names appear |
| `presets.toml`      | which presets and plugin fragments apply to which role — a bare name is a preset file, `@name` is a plugin's fragment |
| `presets/*.md`      | one preset each: markdown, flattened to a line and appended to a spawn's prompt |
| `plugins.toml`      | which plugins are enabled — `sb plugin list` shows the rest          |
| `plugins/<name>/`   | one plugin each: `__init__.py` defines `register()`, `agent.md` is its prompt fragment |
| `protocol.md`       | the agent protocol, injected as a system prompt at every spawn      |
| `prompts.toml`      | the other spawn-time prompt fragments and the doorbell texts        |
| `settings.toml`     | paths, vocabulary, limits, timeouts, retries, display               |
