# Probe task — can a codex agent identify itself to `sb`, and can `sb done` still be enforced?

INVESTIGATION + EXPERIMENT. Change no switchboard code; write only your own notes file.

Read first (all already established, don't redo them):
`notes/codex-scout-sb-prompt-plumbing.md`, `notes/codex-scout-cli-behaviour.md`,
`notes/codex-scout-herdr-kind.md`, `notes/codex-probe-prompt-channel.md`.

Settled so far: herdr's `--kind codex` works; a per-agent `CODEX_HOME` carries the
composed prompt (`AGENTS.md`), trust, model/effort/sandbox and a `notify` hook. Two
things are still unanswered, and they decide how big this job is.

**A. Self-identification.** Every `sb` verb an agent runs (`sb done`, `sb tell`,
`sb inbox`, `sb delegate`) has to resolve "which agent am I?". Today that comes from
`CLAUDE_CODE_SESSION_ID` / `CLAUDECODE`, set by Claude Code itself (`broker.py` whoami
and `_claim_session`, `cli.py` `_agent_caller`). Codex sets no such variable. Find out:

- What environment does a process actually inherit inside a herdr-started pane? Start a
  throwaway `--kind codex` agent under herdr, get codex to run `env` (or run a command in
  that pane) and capture the real variables — is `HERDR_PANE_ID` (or anything else
  identifying the pane/agent) present? Report the actual list.
- Can switchboard set its own variable at spawn time — i.e. does the herdr spawn path let
  you export something like `SB_AGENT=<name>` into the agent's environment (env prefix on
  the command, a wrapper script, `CODEX_HOME`-adjacent config, anything)? Verify a value
  set at spawn is visible to a command the agent later runs.
- Is the codex thread id obtainable at spawn or shortly after, from outside the pane
  (rollout file under `$CODEX_HOME/sessions/`, or the `notify` payload's `thread-id`)?
  Enough to hand to herdr's `report-agent-session` and to `codex resume` later.

**B. The `sb done` gate.** Claude Code's `Stop` hook lets switchboard *block* an agent
from finishing a turn until it has reported (`hooks.py` Stop gate). Codex's `notify` hook
fires after a turn completes. Determine, by testing:

- Can `notify` (or the broader, unexplored `hooks` config struct in codex) refuse/block a
  turn end, or is it strictly fire-and-forget? If `hooks` can do more, map its shape.
- If nothing can block: what is the closest workable substitute — e.g. notify fires,
  switchboard notices the agent stopped without reporting and pushes a follow-up prompt
  into the pane. Test that loop end-to-end once by hand and say whether it behaves
  acceptably (does the nudge arrive, does codex act on it).
- Same question for the activity/turn signal switchboard's `UserPromptSubmit` hook
  provides today: does `notify` plus herdr's own codex status manifest cover it?

Do everything in scratch directories / a scratch herdr workspace — never against the live
fleet store, never in this repo's working files. Tear down every pane, session and file
you create (`codex delete --force <id>`, `herdr workspace close`), no unscoped `pkill`,
and do not modify the real `~/.codex/config.toml`.

Deliverable: write findings to `notes/codex-probe-identity-and-turn.md`. You own that
file and only that file. Exact commands and real output; separate verified from assumed.
Commit on the current branch, then `sb done` with a two-line summary leading with the two
direct answers: can a codex agent identify itself to sb, and can the done-gate be
preserved or only approximated.
