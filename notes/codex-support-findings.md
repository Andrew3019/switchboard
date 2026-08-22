# Codex support in sb — investigation findings

Investigation only; no switchboard code changed. Synthesised from four probes, each of
which ran real commands against the installed `codex-cli 0.147.0` and `herdr 0.8.0`:

- `notes/codex-scout-sb-prompt-plumbing.md` — how sb composes and delivers a prompt today
- `notes/codex-scout-cli-behaviour.md` — how the codex CLI behaves
- `notes/codex-scout-herdr-kind.md` — whether herdr can drive a codex pane
- `notes/codex-probe-prompt-channel.md` — the per-agent prompt channel
- `notes/codex-probe-identity-and-turn.md` — identity and the `sb done` gate

## Verdict

Feasible, and smaller than expected. Nothing needs inventing: every Claude-Code
mechanism switchboard depends on has a verified codex counterpart, and herdr already
speaks codex. The work is a provider seam in `switchboard/herdr.py`, `hooks.py`,
`models.py` and `store.py` — not a redesign, and not a second set of prompts.

## The prompts do not need porting — only re-delivering

This was Andrew's actual question, so it goes first.

Prompt *composition* is already provider-agnostic. `Broker.delegate`
(`broker.py:3287-3308`) assembles protocol + identity + role list + workspace + role
disposition + preset/plugin bindings out of plain markdown on disk, and none of that
text is Claude-specific: a grep across `defaults/` for Claude/model vocabulary turns up
exactly two incidental mentions (`defaults/protocol.md:7`, a line of prose about the doc
itself, and an example inside `defaults/presets/verify.md`). One corpus already serves
both providers.

What is Claude-specific is the *delivery*: the composed text is flattened to one line
and passed as `--append-system-prompt-file <path>` (`herdr.py:473-515`). Codex has no
appended-system-prompt flag — verified by trying every plausible config key and getting
`unknown configuration field` from `--strict-config`. The replacement is
**`CODEX_HOME`**: a private per-agent directory whose `AGENTS.md` is read as global
standing instructions on every turn, in both the TUI and `exec` (verified). It is:

- **zero repo footprint** — no `AGENTS.md` in the worktree, so nothing leaks into a
  human's own codex sessions and nothing collides between agents sharing a checkout;
- **not truncated** — the 32KB `project_doc_max_bytes` cap applies to the repo-level doc
  only; a 35KB global doc came through whole (a real sb prompt is ~12KB);
- **multi-line** — the one-line flattening exists only because herdr refuses a newline in
  an *argument*; a file has no such limit, so codex can take the markdown unflattened;
- **additive** — if a repo `AGENTS.md` does exist, codex concatenates global-then-project
  rather than clobbering it.

The same `CODEX_HOME/config.toml` also carries model, reasoning effort, sandbox mode,
`notify`, hooks, and a pre-seeded `[projects."<worktree>"] trust_level = "trusted"` entry
that stops the TUI blocking on its trust prompt. So `CODEX_HOME` is one per-agent home
for everything sb sets per agent today — structurally the same move as the existing
per-agent prompt file, just a directory instead of a file.

One semantic difference worth stating plainly: codex injects the doc as a leading **user**
message each turn, not as a system prompt. The protocol arrives every turn rather than
once, but it arrives with user-level rather than system-level authority.

## Every other mechanism maps

| sb depends on | Claude Code today | Codex counterpart | Status |
|---|---|---|---|
| Pane spawn | `herdr agent start --kind claude` | `--kind codex` already in herdr's kind list | verified live: spawn, prompt, reply, teardown |
| Status (idle/working/blocked) | herdr detection manifest | per-kind `codex.toml` manifest, actively maintained | verified: trust-prompt `blocked` and working→done both fired correctly |
| Standing prompt | `--append-system-prompt-file` | `CODEX_HOME/AGENTS.md` | verified, incl. a 10KB multi-line prompt obeyed to its last line |
| Model / effort | `--model` / `--effort` | `model` / `model_reasoning_effort` in config.toml, or `-m` | verified via rollout log |
| Permission mode | `--permission-mode auto` | `-s/--sandbox` + `-a/--ask-for-approval` (TUI only; `exec` has no `-a`) | read + sandbox verified |
| Agent identity | `CLAUDE_CODE_SESSION_ID` env | `herdr pane split --env SB_AGENT=<name>`, plus herdr's own `HERDR_PANE_ID` | verified: survives into codex's shell-tool subprocess |
| Session id / restore | `--resume <session_id>` | `CODEX_THREAD_ID` env + rollout filename; `codex resume`/`codex exec resume` | verified, incl. TUI→exec resume |
| `sb done` gate | `Stop` hook `decision: block` | codex `hooks.Stop`, same output schema | verified live: a real turn blocked and re-opened 11× |
| Transcript | `~/.claude/projects/*.jsonl` | `$CODEX_HOME/sessions/**/rollout-*.jsonl`, different shape | located; parser not written |

The done-gate finding is the most surprising: codex's hook system is deliberately
Claude-Code-compatible — the binary's own embedded schema carries `Stop`,
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SessionStart/End`, `SubagentStop`,
`PreCompact/PostCompact`, `PermissionRequest`, the identical
`{continue, decision, reason, stopReason, suppressOutput, systemMessage}` output shape,
the `stop_hook_active` anti-loop flag, and a schema comment that names Claude directly.
`hooks.py`'s enforcement logic is largely portable; what changes is where the config is
written (a `CODEX_HOME/config.toml` block instead of a `--settings` JSON file).

## What actually has to be built

1. **A provider seam in `Herdr.start_agent`/`_prompt_flags`** (`herdr.py:473-598`). The
   flag names are currently hardcoded Claude flags; they need to branch on the tier's
   provider, and the codex branch writes a `CODEX_HOME` dir instead of a prompt file and
   exports `CODEX_HOME`/`SB_AGENT` at pane-split time.
2. **`--env` at pane creation.** `SB_AGENT` must be set by `herdr pane split --env` (or
   `workspace create --env`, untested), *before* `agent start` — so sb's spawn path has
   to own pane creation. This is the one place the change reaches beyond a flag swap.
3. **`hooks.py` gets a codex shape** — same events and semantics, written into
   `CODEX_HOME/config.toml`.
4. **Identity resolution in `broker.whoami`/`cli._agent_caller`** — accept `SB_AGENT`
   (and the already-present `HERDR_PANE_ID`) alongside `CLAUDE_CODE_SESSION_ID`.
5. **Session id capture** — poll for the new rollout file (or read the `notify` payload's
   `thread-id`) after the first prompt; codex allocates no thread id at spawn. Then
   `report-agent-session` as today, and `codex resume` on restore.
6. **`store.transcript_dir` / `output.py`** — a codex rollout reader, for `sb inspect` and
   for the `task_arrived` delivery proof. Until it exists, `Herdr.deliver` falls back to
   herdr's status polling, which already works for codex.
7. **`models.py`** — add `codex` to `wired = [...]` and give the codex tiers real slugs
   (`gpt-5.5`, `gpt-5.6-sol`, etc., from `codex debug models`).

## Open risks

- **Hook trust.** A `hooks.Stop` block is silently ignored — fail-open, no warning —
  unless hooks are trusted, and the only non-interactive path found is
  `--dangerously-bypass-hook-trust` on every spawn. Defensible (sb authors the hook
  script itself, exactly as it authors the Claude settings file today) but it is a
  deliberate call, and worth one more pass to see whether the content-hashed hook-trust
  store can be pre-seeded in a private `CODEX_HOME` the way directory trust can.
- **Auth.** A private `CODEX_HOME` 401s on every request without its own `auth.json`.
  Copy vs symlink vs `OPENAI_API_KEY` is unresolved; symlink is the obvious first try.
- **Approval semantics differ.** `codex exec` has no `--ask-for-approval` at all; risk is
  controlled purely by sandbox mode. There is no clean analogue of
  `--permission-mode auto`'s model-driven classifier.
- **User-message authority.** The protocol arriving as a per-turn user message rather
  than a system prompt may prove weaker in practice. Only real use will tell.
- **`UserPromptSubmit`** was read from the schema, not fired live — the activity signal
  is plausible, not verified.

## Recommended next step

A spike, not a design doc: wire the provider seam far enough to spawn one real codex
agent through `sb delegate --model <codex tier>`, with the `CODEX_HOME` prompt channel
and the `Stop` gate, and see whether it can complete a small task and call `sb done`.
Everything above says it should; nothing above proves the agent *behaves* once inside the
protocol, and that is the only remaining unknown that reading cannot settle.
