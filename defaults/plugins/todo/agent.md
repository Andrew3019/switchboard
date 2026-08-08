<!-- Injected into every spawn this plugin is bound to, flattened to one line and capped at
     [limits] plugin_fragment. Everything outside this comment is paid for on every spawn,
     forever, so it says what an agent has to be TOLD and nothing it could look up.

     What it deliberately does not say: work from the list. Reading a shared list and
     deciding what to do next is an orchestrator's job. An agent told to pull from a queue
     is an agent taking a decision that belonged in its task string. -->
# todo

- This repo has one shared todo list, the same from every worktree. Run `sb plugin todo list` before you start so you do not redo something already filed.
- Work you notice but were not asked to do: `sb plugin todo add "..." --label found` rather than doing it or dropping it.
- `sb plugin todo done <id> --note "..."` when you finish something that was on it.
