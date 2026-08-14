# Scout task: how switchboard names agents and workspaces

Read-only. Do NOT change any code.

Andrew asked two things:
1. Can the name of a top-level agent/workspace be custom (e.g. derived from the repo name) instead of the fixed `main` prefix?
2. Why does the number keep incrementing (`main-14`) instead of resetting when earlier agents are gone?

Find and report, with file:line references:

- Where the name `main` comes from for a top-level orchestrator started with `sb start`, and where child names like `worker-23` come from.
- The exact counter/allocation logic: what it counts, where the number is persisted, and why it never resets (monotonic counter in the store? derived from existing names? global vs per-repo?).
- What else depends on those names: workspace/worktree directory names, git branch names, herdr session/window names, store keys — anything that would break if names were customisable.
- Whether `sb start` (or `sb workspace`) already accepts any name argument, and whether any code assumes the top-level prefix is literally `main`.
- How hard a custom-name option would be, and the main risks: collisions, herdr's machine-global namespace across repos, restore/cleanup.

Return a tight report: the mechanism, the answer to "why doesn't it reset", and the shape of what a custom-name change would touch. Write it to `notes/scout-naming-report.md` and commit that file. Keep it readable by someone who has not opened the code.
