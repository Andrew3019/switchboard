<!-- Injected into every spawn this plugin is bound to, flattened to one line and capped at
     [limits] plugin_fragment. It is written to fit under that cap rather than to be cut by
     it: a fragment that truncates on every spawn is a fragment whose last sentence nobody
     ever reads.

     The `report-bug` PRESET carries the same guidance, for spawns bound to it rather than
     to this plugin. The two are kept in step deliberately until the preset can be retired
     without an existing `--with report-bug` degrading into a one-word literal. -->
# report-bug

- Hit a bug in switchboard itself (`sb`, or anything under `switchboard/`)? File it: `sb plugin report-bug file "<what broke>" --command "..." --expected "..." --actual "<the exact error>"`.
- Then carry on with your task. Do not work around it silently — that hides the bug from everyone else and is worse than the bug.
- If it blocks you entirely, `sb block "..."` after filing.
