# defaults/ — the shipped configuration

Everything switchboard knows out of the box, in files rather than in Python. Roles, model
tiers, plugin bindings, the agent protocol, the spawn prompts, and every number worth
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
| `defaults/plugins.toml`     | `.switchboard/plugins.toml`            |
| `defaults/protocol.md`      | `.switchboard/protocol.md`             |
| `defaults/prompts.toml`     | `.switchboard/prompts.toml`            |
| `defaults/settings.toml`    | `.switchboard/settings.toml`           |

Plugin *files* (`.switchboard/plugins/<name>.md`) are deliberately NOT layered: the
protocol is what every agent needs, a plugin is what some agents need, and what
switchboard's own agents need has no bearing on another repo's. Only the *bindings* —
which plugin applies to which role — are shipped and layered.

## Merge rules

The override layer **joins** the base; it does not replace it. Three rules, applied
recursively and identically to every file above:

1. **Tables merge, key by key.** Overriding one field of a role, or one field of a model
   tier, leaves the rest of that role or tier alone.
2. **Scalars replace.** A string, number or boolean in the override wins outright.
3. **Arrays join.** The base's items come first, then the override's, with duplicates
   dropped and order preserved. Adding a plugin binding therefore cannot wipe a shipped
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
| `plugins.toml`      | which prompt plugins apply to which role                            |
| `protocol.md`       | the agent protocol, injected as a system prompt at every spawn      |
| `prompts.toml`      | the other spawn-time prompt fragments and the doorbell texts        |
| `settings.toml`     | paths, vocabulary, limits, timeouts, retries, display               |
