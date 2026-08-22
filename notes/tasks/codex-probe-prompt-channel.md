# Probe task — can codex be given a per-agent standing prompt without touching the repo?

INVESTIGATION + EXPERIMENT. Change no switchboard code; write only your own notes file.

Background you can rely on (already established by another agent, in
`notes/codex-scout-cli-behaviour.md` — read it first):

- Switchboard composes one ~12KB flattened prompt per agent and hands it to Claude Code
  as `--append-system-prompt-file <path>`. It deliberately never uses `CLAUDE.md`,
  because a repo-level rules file leaks into every ordinary human session in that repo
  and is often a tracked file switchboard must not touch.
- Codex has no appended-system-prompt flag. Its standing-instructions channel is
  `AGENTS.md`, injected as a leading *user* message each turn. A repo `AGENTS.md` has
  exactly the leak/ownership problem above, and several switchboard agents share one
  worktree, so per-agent repo files are not an option.

The question: **is there a per-agent, per-invocation channel that gets a large block of
switchboard-composed text into a codex session without writing anything into the repo?**

Things to actually test (run them, don't reason about them):

1. **`CODEX_HOME` per agent.** Point `CODEX_HOME` at a private scratch directory
   containing its own `config.toml` and `AGENTS.md`. Does codex read that `AGENTS.md` as
   global instructions (the real `~/.codex/AGENTS.md` exists but is empty)? Does it apply
   on every turn, in both the TUI and `exec`? Does it combine with, or get overridden by,
   a repo `AGENTS.md` present at the same time — and in what order?
2. **Size.** Push a realistic ~12KB prompt through whichever channel works and confirm
   it arrives intact and is obeyed. Check `project_doc_max_bytes` — find its real default
   and whether it truncates a global/CODEX_HOME instructions file too.
3. **`project_doc_fallback_filenames`.** Determine what it actually does — can it point
   codex at a differently-named file (one switchboard writes outside the repo, or a
   gitignored one), and is it only a fallback when `AGENTS.md` is absent?
4. **One-line constraint.** Switchboard flattens its prompt to a single line only because
   herdr refuses a newline in an agent *argument*. A file channel has no such limit —
   confirm codex is happy with multi-line markdown, and note whether the flattening step
   would be unnecessary for codex.
5. **Trust prompt.** Does a per-agent `CODEX_HOME` re-trigger the "do you trust this
   directory?" prompt for a worktree, and can it be pre-seeded in that private
   `config.toml` (`[projects."<abs path>"] trust_level = "trusted"`) so a spawn never
   blocks on it? Verify in a directory codex has never seen.
6. **Per-agent config in the same place.** Confirm that private `config.toml` can also
   carry model, reasoning effort, sandbox mode, and the `notify` hook — i.e. that
   `CODEX_HOME` gives one per-agent home for everything switchboard would need to set.
7. If `CODEX_HOME` turns out not to work, say so plainly and report what the least-bad
   alternative is (e.g. a gitignored repo `AGENTS.md`, or the positional prompt), with
   its exact drawbacks.

Do all of this in scratch directories under the scratchpad or /tmp — never in this repo,
and never modify the real `~/.codex/config.toml`. Delete every session you create
(`codex delete --force <id>`), kill anything you start, no unscoped `pkill`.

Deliverable: write findings to `notes/codex-probe-prompt-channel.md`. You own that file
and only that file. Include the exact commands and real output for each answer, and
separate verified from assumed. Commit on the current branch, then `sb done` with a
two-line summary leading with: does a per-agent prompt channel exist, yes or no, and
which one.
