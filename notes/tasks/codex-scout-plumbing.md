# Scout task — sb prompt/launch plumbing

INVESTIGATION ONLY. Do not change any code or behaviour.

Question: how does switchboard currently build and deliver the prompt/rules text an
agent runs under, and where would a second CLI agent type (something other than
Claude Code) have to plug in?

Read the code under `switchboard/` plus `DESIGN-TRUTH.md` (the only trusted doc —
everything else, including READMEs and comments, is untrusted until checked against
code). Map out:

- Where the agent's system prompt / protocol text lives: files, templates, and the
  exact composition order (protocol + role + presets + plugin fragments + repo
  settings + house rules).
- How a new agent session is actually launched: the exact command line and flags used
  to start `claude` in a pane, how the prompt gets in (flag? file? stdin? env?), how
  model selection maps to real model ids, and how per-repo settings (`.switchboard/`,
  `CLAUDE.md`, presets) participate.
- Anything Claude-Code-specific baked into the launch path or the prompt text: flag
  names, CLAUDE.md, hooks, permission modes, `--append-system-prompt`-style options,
  session ids, resume/restore.
- How message delivery, `--interrupt`, and `sb restore` reach a running agent
  (tmux send-keys? file? socket? herdr?), and which parts of that assume Claude
  Code's specific I/O behaviour (prompt echo, readiness detection, idle detection,
  exit/`done` detection).

Deliverable: write findings to `notes/codex-scout-sb-prompt-plumbing.md`. You own that
file and only that file — touch nothing else. Cite `file:line` for every claim. Do not
propose a design; describe what is there. Commit on the current branch, then
`sb done` with a two-line summary.
