# defaults/ — the shipped configuration

Everything switchboard knows out of the box, in files rather than in Python. Roles, model
tiers, presets and their bindings, the plugins that ship, the agent protocol, the spawn
prompts, and every number worth tuning live here. `switchboard/config.py` is the only
thing that reads them.

Not dot-prefixed on purpose. This is the reference copy: you are meant to open it, read it,
and copy pieces of it into your own repo. A hidden directory says "internal", and these
files are the opposite of internal.

## Layering

For any repo, three layers, most general first:

    defaults/                    (this directory — shipped, never edited per repo)
    <repo>/.switchboard-shared/  (that repo's own, committed — presets and step definitions)
    <repo>/.switchboard/         (that checkout's own, never committed)

`defaults/` alone is a complete, working configuration: switchboard runs in a repo with
neither of the other two. A repo's own layers only say what differs.

The middle layer covers **presets and step definitions** — `presets.toml`,
`presets/<name>.md`, `plans/library/<name>.json` and `plans/templates/<name>.json`, under
the same key names as the local layer. It exists because `.switchboard/` cannot travel: it
is gitignored in switchboard's own repo, and in a fleet worktree it is a symlink git refuses
to track through, so a repo's house rules for its own agents reached nobody who cloned it.
Since cloning is how a verification run is isolated, the clones doing the riskiest work were
precisely the ones with no rules in them. Step definitions joined it for the same reason
under a different heading: a repo-defined step kind is repo configuration, and before it had
a layer the only way to mint one was to add a JSON file inside switchboard's own plugin
directory, which is not an override of anything. Nothing else is layered there because
nothing else needed to travel; a small layer that is complete for what it covers beats a
wide one that is half wired up.

Which of the two a file goes in is one question: is this true of the REPO, or of this
checkout on this machine? House rules, committed. Your own scratch preset, local.

| shipped                     | repo override                          |
| --------------------------- | -------------------------------------- |
| `defaults/roles/<name>.md`  | `.switchboard/roles/<name>.md`, `.switchboard/roles.toml` |
| `defaults/models.toml`      | `~/.config/switchboard/models.toml`, then `.switchboard/models.toml` |
| `defaults/presets.toml`     | `.switchboard-shared/presets.toml`, then `.switchboard/presets.toml` |
| `defaults/presets/<name>.md`| `.switchboard-shared/presets/<name>.md`, then `.switchboard/presets/<name>.md` |
| `defaults/plugins/plans/library/<name>.json` | `.switchboard-shared/plans/library/<name>.json`, then `.switchboard/plans/library/<name>.json` |
| `defaults/plugins/plans/templates/<name>.json` | `.switchboard-shared/plans/templates/<name>.json`, then `.switchboard/plans/templates/<name>.json` |
| `defaults/plugins.toml`     | `.switchboard/plugins.toml`            |
| `defaults/plugins/<name>/`  | `.switchboard/plugins/<name>/`         |
| `defaults/protocol.md`      | `.switchboard/protocol.md`             |
| `defaults/prompts.toml`     | `.switchboard/prompts.toml`            |
| `defaults/settings.toml`    | `.switchboard/settings.toml`           |

Preset *files* are layered too — `defaults/presets/<name>.md`, replaced by name by a repo's
`.switchboard-shared/presets/<name>.md` and then by its `.switchboard/presets/<name>.md`.
This reverses an earlier decision, and the reversal is
worth stating rather than quietly reflecting: preset files were originally *not* shipped, on
the grounds that what switchboard's own agents need has no bearing on another repo's. That
held until `defaults/presets.toml` started shipping bindings, at which point a fresh clone
had bindings pointing at files that existed only in an untracked directory.

What survives the reversal is the distinction it was protecting, now carried by binding
instead of by shipping: **shipping a preset makes it nameable; only a binding makes it
applied.** Three files ship. `evidence` and `verify` are bound to roles, which is precisely
why their bodies must ship; `adversarial` is bound to nothing at all and is read on demand
with `sb presets adversarial`.

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
   one — which is the whole reason joining is the default, and it matters now that the
   shipped bindings are not empty: `all = ["@report-bug"]`, plus `evidence` and `verify`
   on the roles whose whole output is a claim about something they read or ran.

To *replace* an array instead of joining it, make `"!reset"` its first element:

    all = ["!reset"]                  # nothing at all, whatever was shipped

Everything about this is tested in `tests/test_config.py`.

## Reading which layer answered

    sb configure --layers              what this repo has CHANGED, and what to delete to undo it
    sb configure --layers timeouts     every setting under a prefix, defaults included
    sb configure --layers --json       the same as data

Every row is `switchboard default -> repo override -> effective`, with the exact line to
delete to reset it and the file it is in; the vocabularies below the settings say which layer
defines each role, preset, model tier and step kind. Read-only — an override is a line in
`.switchboard/settings.toml`, and this tells you which line. It is the substrate the browser
(wave 12) will present and edit.

For an ARRAY the override and the effective value differ on purpose: arrays join, so a repo
that wrote one entry has an effective value holding the shipped ones too, and the readout
shows both rather than making you guess which entry is yours.

`sb configure` with no `--layers` is a different subject: an agent tuning its own reminders
inside its role's ceiling. Nothing there touches repo configuration.

## Pointing switchboard somewhere else

`SWITCHBOARD_DEFAULTS=/path/to/dir` replaces this directory wholesale. Used by the test
suite; also the escape hatch for shipping a different baseline to a team.

## File tour

| file                | what it holds                                                      |
| ------------------- | ------------------------------------------------------------------ |
| `roles/*.md`        | one role each — `dispatcher`, `lead`, `worker`, `researcher`, `reviewer`, `qa`: TOML front matter for the fields, markdown for the prompt |
| `models.toml`       | what `cheap`, `careful`, `strong`, `prose` and `default` mean — the only place model names appear |
| `presets.toml`      | which presets and plugin fragments apply to which role — a bare name is a preset file, `@name` is a plugin's fragment |
| `presets/*.md`      | one preset each: markdown flattened to a line and appended to a spawn's prompt, or a procedure read by name with `sb presets <name>` |
| `plugins.toml`      | which plugins are enabled — `sb plugin list` shows the rest          |
| `plugins/<name>/`   | one plugin each: `__init__.py` defines `register()`, `agent.md` is its prompt fragment |
| `protocol.md`       | the agent protocol, injected as a system prompt at every spawn      |
| `prompts.toml`      | the other spawn-time prompt fragments and the doorbell texts        |
| `settings.toml`     | paths, vocabulary, limits, timeouts, retries, display               |
| `plugins/plans/library/*.json`   | one step definition each — the filename is the step kind it mints |
| `plugins/plans/templates/*.json` | one plan template each                                |
