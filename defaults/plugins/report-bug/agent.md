<!-- Injected into every spawn this plugin is bound to, flattened to one line and capped at
     [limits] plugin_fragment. It is written to fit under that cap rather than to be cut by
     it: a fragment that truncates on every spawn is a fragment whose last sentence nobody
     ever reads.

     There was a `report-bug` PRESET saying the same thing, kept in step with this file for
     spawns bound to it rather than to the plugin. It is deleted: this fragment is bound to
     every agent through `defaults/presets.toml`, so the preset was pure duplication. Note
     the consequence — `--with report-bug` now fails rather than silently shipping the
     one-word string "report-bug", which is the sigil rule doing its job. It is
     `@report-bug` or nothing. -->
# report-bug

- Hit a bug in switchboard itself (`sb`, or anything under `switchboard/`)? File it: `sb plugin report-bug file "<what broke>" --command "..." --expected "..." --actual "<the exact error>"`.
- Then carry on with your task. Do not work around it silently — that hides the bug from everyone else and is worse than the bug.
- If it blocks you entirely, `sb block "..."` after filing.
