# Historical — superseded

Nothing in this directory is current. These are the inputs that `../PLUGIN-REDESIGN.md`
was built from and explicitly supersedes. They are kept because they record decisions and
roads-not-taken that exist nowhere else — not in the code, and not in git history, since
they were never committed until the redesign landed.

If you want to know how the plugin system works, read `../PLUGIN-REDESIGN.md`. Read these
only to answer "why is it shaped this way, and what else was on the table".

| file | what it is |
|---|---|
| `decisions.md` | The human's binding decisions. The design was reworked to fit these; where a proposal conflicted, these won. This is the one file here that still explains *why* rather than *what*. |
| `proposal-a.md` | The thin, minimum-machinery proposal. Won on shape. |
| `proposal-b.md` | The explicit-contract, layered proposal. Lost, but parts were taken; §12 of the design record says which and why. |
| `plugins-current-state.md` | A survey of the pre-redesign implementation. Describes code that no longer exists; its `file:line` citations are all stale. |
