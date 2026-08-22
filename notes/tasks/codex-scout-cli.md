# Scout task — how the codex CLI actually works

INVESTIGATION ONLY. Do not change any switchboard code.

`codex` (OpenAI's Codex CLI) is installed on this machine. Find out, by reading
`codex --help`, its subcommand help, its config docs, and by actually running it, how
it would have to be driven if switchboard were to launch and steer a codex agent in a
tmux pane the same way it drives Claude Code today.

Answer concretely, with the commands you ran and their real output as evidence:

1. **Launch + prompt injection.** How do you start an interactive codex session in a
   terminal with (a) an initial task prompt and (b) extra system-level instructions?
   Is there anything equivalent to an appended system prompt, or is `AGENTS.md` /
   config the only channel? What precedence do the instruction sources have, and are
   any of them per-repo vs per-user vs per-invocation?
2. **Rules files.** What files does codex read for standing instructions (`AGENTS.md`
   and any others), where do they have to live, can a path be pointed at explicitly,
   and is there a size or count limit? Does it read `CLAUDE.md` at all?
3. **Turns and idleness.** Does codex have a discernible notion of a turn ending?
   Can you tell from outside the pane whether it is working or idle — exit codes,
   files it writes, a session/rollout file, notify hooks, anything machine-readable?
4. **Sending more input mid-session.** Does typing into the pane (tmux send-keys
   style) work while it is running and while it is idle? Is there an interrupt
   (Esc/Ctrl-C) that stops the current turn without killing the session?
5. **Resume.** Can a session be resumed by id after the pane dies, and where is
   session state stored?
6. **Non-interactive mode.** What `exec`-style mode exists, what does it give you
   (streamed JSON? exit codes?), and would it be a better fit than driving the TUI?
7. **Tooling/permissions.** Sandbox/approval modes, and the flags to run it in a way
   comparable to how switchboard runs Claude Code.
8. **Model selection.** How a model is chosen, and what names are valid.

Prove things by running them in a scratch directory (e.g. under /tmp), not in this
repo, and tear down anything you start. Do not spawn switchboard agents.

Deliverable: write findings to `notes/codex-scout-cli-behaviour.md`. You own that file
and only that file — touch nothing else. Distinguish clearly between what you
verified by running and what you only read in help text. Commit on the current
branch, then `sb done` with a two-line summary.
