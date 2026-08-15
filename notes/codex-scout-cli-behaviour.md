# How the `codex` CLI actually works (for driving it like switchboard drives Claude Code)

Investigated by running `codex-cli 0.147.0` (`which codex` → `/Users/andrew/.local/bin/codex`)
against a scratch git repo under the scratchpad directory, plus reading `--help` output for
every relevant subcommand. All test sessions and config entries created during this probe were
deleted afterward (see "Cleanup" at the end). Nothing in this repo or in switchboard code was
touched.

Legend: **VERIFIED** = I ran the command and observed the behavior directly. **READ** = from
`--help` text only, not exercised.

## 1. Launch + prompt injection

- `codex [OPTIONS] [PROMPT]` starts the interactive TUI with an initial prompt as a plain
  positional argument. **VERIFIED** via `codex -s read-only` then typing a prompt into the pane
  (see turn/idle section) — typing text and hitting Enter is equivalent to passing it as
  `[PROMPT]`.
- `codex exec [OPTIONS] [PROMPT]` runs non-interactively; if no PROMPT arg is given (or `-` is
  passed) it reads the prompt from stdin, and if stdin is piped *and* a prompt arg is given, stdin
  is appended as a `<stdin>` block (READ, from `codex exec --help`).
- There is **no flag for an appended/extra system prompt**. I searched for one directly:
  `-c experimental_instructions_file=...`, `developer_instructions_file`, `system_prompt_file`,
  `base_instructions_file`, `instructions_file`, `additional_instructions`, `custom_instructions`
  — every one of these was rejected by `--strict-config` with
  `unknown configuration field '<name>' in -c/--config override` (**VERIFIED**, see
  `notes/` probe transcript below). So the two real channels for standing/extra instructions are:
  1. **`AGENTS.md`** files (see §2), which get folded into the conversation as a *user message*,
     not a system message.
  2. **`config.toml` / `-c key=value` overrides / `-p/--profile <name>`**, which only affect
     structured settings (model, sandbox, personality, etc.), not free-text instructions.
- Precedence I could verify directly: `-c` CLI overrides > `$CODEX_HOME/<profile>.config.toml`
  (layered on top of base config via `-p/--profile`, READ only) > `~/.codex/config.toml`. This is
  documented in the `-c`/`-p` help text; I did not independently stack multiple layers to prove
  override order beyond what codex's own error messages imply.
- The actual system prompt (`base_instructions`) is a large baked-in personality/values text
  compiled into the binary per model (confirmed by dumping it from the session rollout file and
  from `codex debug models`, which embeds a full `instructions_template` per model slug) — it is
  **not** user-editable through any documented flag or config key I could find.
- **Per-repo trust** is a separate, additional gate: the first time you point codex at a new
  directory it shows an interactive "Do you trust the contents of this directory?" prompt before
  loading AGENTS.md/hooks/exec-policies from that directory (**VERIFIED** — hit this prompt when
  starting the TUI in the scratch repo). Accepted trust is persisted as
  `[projects."<abs-path>"] trust_level = "trusted"` in `~/.codex/config.toml` — this is real,
  per-user, per-repo state that already existed for several of Andrew's real projects, including
  `/Users/andrew/Code/switchboard` (**VERIFIED**, read from the real `~/.codex/config.toml`
  before touching it). For switchboard-driven automation this matters: a repo/worktree codex has
  never seen will block on this trust prompt unless pre-seeded in config.toml or run with a flag
  that bypasses it (I did not find a documented flag to skip trust; `exec` mode did not seem to
  hit the prompt in my tests, only the interactive TUI did — worth re-checking explicitly if this
  becomes load-bearing).

## 2. Rules files

- **`AGENTS.md`** is the standing-instructions file, confirmed two ways:
  - `codex exec --json` in a repo whose root `AGENTS.md` said "always prepend LOL: to every
    answer" produced replies literally prefixed `LOL:` (**VERIFIED**).
  - Dumping the raw session rollout JSONL (`~/.codex/sessions/...jsonl`) showed the exact
    injection: a `user`-role `response_item` whose text begins
    `# AGENTS.md instructions for <abs path>\n\n<INSTRUCTIONS>\n<file contents>\n</INSTRUCTIONS>`,
    inserted **before** the actual user prompt, in the same turn. So it is not a system message —
    it's synthesized as a leading user message, every turn (**VERIFIED**, read directly from the
    rollout file).
  - The TUI's `/status` panel explicitly reports which file it loaded: `Agents.md: AGENTS.md`
    (**VERIFIED**).
- **`CLAUDE.md` is NOT read.** I put a `CLAUDE.md` (no `AGENTS.md`) with an equally strong
  instruction ("always prepend CLAUDEMD:") in a second scratch repo and ran `codex exec`; the
  reply had no such prefix — it was ignored entirely (**VERIFIED**).
- Config keys exist that govern this file family beyond the plain name:
  - `project_doc_max_bytes` — a `usize` (accepted by `--strict-config`, confirmed by triggering a
    *type* error, not an *unknown field* error, when passed a string) — so there **is** a size
    limit on how much of AGENTS.md gets read, and it's configurable (**VERIFIED** the key exists;
    did not verify the default numeric value or exact truncation behavior).
  - `project_doc_fallback_filenames` — a sequence-typed key (same evidence pattern) — implies
    codex supports alternate/fallback filenames for the rules file, though I did not determine
    what the built-in fallback list is or whether it includes anything besides `AGENTS.md`
    (**VERIFIED** key exists; fallback list contents NOT verified).
  - Keys I tried that do **not** exist: `project_doc_search_max_depth`, `agents_md_max_bytes`
    (**VERIFIED** rejected as unknown fields).
- I did not verify whether nested `AGENTS.md` files (e.g. a `sub/AGENTS.md`) get merged in when
  the invocation's cwd is the repo root — I created `sub/AGENTS.md` for this purpose but the
  prompt in that test only exercised the root file, and I did not follow up with a `-C sub` run.
  Treat "does it merge multiple AGENTS.md up the tree" as **unverified**.

## 3. Turns and idleness

Two different observability channels, both real and usable by an external driver:

- **`codex exec --json`** streams newline-delimited JSON events to stdout and exits when the turn
  is done. Verified event shapes from actual runs:
  ```
  {"type":"thread.started","thread_id":"<uuid>"}
  {"type":"turn.started"}
  {"type":"item.completed","item":{"id":"...","type":"agent_message","text":"..."}}
  {"type":"turn.completed","usage":{"input_tokens":...,"output_tokens":...,...}}
  ```
  Process exit code was `0` in every successful run I did, including one where the model's shell
  command itself failed (sandbox blocked a `touch`) — the tool failure is surfaced *inside* the
  JSON stream to the model, not as a nonzero process exit (**VERIFIED**). This is a clean
  machine-readable turn boundary if you drive codex via `exec` instead of the TUI.
- **The interactive TUI** shows a literal working/idle indicator in the pane text:
  `• Working (Ns • esc to interrupt) · 1 background terminal running · /ps to view · /stop to
  close` while a turn (including a running shell command) is in progress, and no such line, just
  the input prompt, when idle (**VERIFIED** by capturing the tmux pane mid-task and after
  completion). This is scrapeable but fragile (exact text, spinner state) compared to `--json`.
- **`notify` config hook** — a config key that takes a program to invoke on turn completion,
  *including in `codex exec` mode*, not just the TUI. Verified by setting
  `-c 'notify=["<path to script>"]'` and running `codex exec`; the script was invoked with a
  single JSON-string argument:
  ```json
  {"type":"agent-turn-complete","thread-id":"<uuid>","turn-id":"<uuid>","cwd":"<path>",
   "client":"codex_exec","input-messages":["Say hi."],"last-assistant-message":"LOL: Hi."}
  ```
  (**VERIFIED** — exact payload captured from a real invocation.) This is the closest codex
  equivalent to a Claude Code "Stop" hook and is probably the best out-of-pane, machine-readable
  turn-boundary signal if switchboard keeps driving the TUI directly rather than switching to
  `exec`.
- There is also a `hooks` config key (a struct, not further explored — passing a list to it
  produced a type error, confirming it exists but I did not map its shape) that looks like a
  broader hook system beyond `notify`. Not investigated further — flagging it as something to dig
  into if `notify` alone isn't enough.
- Every turn is also durably logged to a per-session JSONL rollout file on disk as it happens (see
  §5) — tailing that file is a third way to observe turn boundaries, but `--json`/`notify` are
  more direct.

## 4. Sending more input mid-session

- **VERIFIED**, using `tmux send-keys` against a live interactive `codex` pane:
  - Typing while codex is *idle* just fills the input box; you must send Enter as a **separate**
    `send-keys` call — sending text and `Enter`/`C-m` in the same batch sometimes lands before the
    TUI has finished rendering the keystrokes and the Enter doesn't register (I hit this twice; a
    ~1s sleep between typing and Enter fixed it reliably). Switchboard should budget a small delay
    between typing and submitting, same caution as with any TUI.
  - Typing while codex is **mid-turn** does *not* interrupt or get lost — the pane shows a
    distinct banner: `• Messages to be submitted after next tool call (press esc to interrupt and
    send immediately)` followed by the queued text. The message is not silently dropped and not
    immediately injected; it's held and applied once the current tool call finishes (**VERIFIED**
    directly).
  - **Esc interrupts.** Sending `Escape` while a turn is running (or while a message is queued)
    stops the flow and the pane shows `■ Conversation interrupted - tell the model what to do
    differently.` The session and process stayed alive after this — it's a turn-level interrupt,
    not a session kill (**VERIFIED**). Note: in my test, the in-flight shell command
    (`sleep 20`) had already completed by the time I pressed Esc; I did not manage to interrupt a
    command that was still actively running mid-execution, only the turn that came after it. So
    "Esc kills an in-progress shell command instantly" is **not verified** — only "Esc aborts the
    turn/response cycle" is.
  - `Ctrl-C` pressed twice at the idle prompt exits the TUI cleanly and prints its own resume
    hint: `To continue this session, run codex resume <uuid>` (**VERIFIED**).

## 5. Resume

- **VERIFIED, end to end, including across TUI → exec.** Every session (TUI or `exec`) is
  persisted to `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-<timestamp>-<thread-id>.jsonl` the
  moment it starts (confirmed by grepping the exact thread_id printed by `codex exec --json`'s
  `thread.started` event and finding a freshly-written file with that id in its name within the
  same second).
- `codex exec resume <SESSION_ID> [PROMPT]` and `codex exec resume --last [PROMPT]` both work
  non-interactively. I resumed a plain `exec` thread and separately resumed a session that was
  *started in the interactive TUI* purely from `codex exec resume <uuid>`, and the model correctly
  recalled facts from the earlier turns in both cases (**VERIFIED** — asked it to recall an
  AGENTS.md-injected word and a sleep duration mentioned only in the prior turn; got correct
  answers both times).
- `codex resume [SESSION_ID]` (interactive) and `codex resume --last` also exist for resuming into
  the TUI (READ from `--help`, not separately exercised beyond confirming the exit hint points at
  this exact command).
- Session state — the full turn-by-turn transcript, including the injected AGENTS.md content, the
  base system instructions, tool calls, and usage — lives in that same rollout JSONL. There's also
  a `~/.codex/thread_history_1.sqlite` (with `thread_items`/`thread_turns` tables) that looked like
  a secondary index, but a fresh `exec` run's thread id did not show up there in my check — I did
  not chase down why (possibly indexed asynchronously, or only for TUI/app-server originated
  threads). Treat the sqlite file as unconfirmed/secondary; the JSONL rollout file under
  `sessions/` is the verified source of truth.
- `codex fork`, `codex archive`, `codex delete`, `codex unarchive` all operate on the same
  session-id/session-name space (READ from `--help`; `delete` was actually exercised during
  cleanup — see below — and worked as documented, requiring `--force` when not run from a TTY).

## 6. Non-interactive mode (`codex exec`)

- This is very likely the better fit for switchboard than driving the TUI, if the goal is
  reliable turn boundaries and prompt injection without scraping ANSI panes:
  - Deterministic start/end via `--json` events, not textual pane state.
  - Clean process exit (exit 0 in all my successful runs) — the model's own tool failures don't
    propagate to the exec process's exit code, they're just reported back to the model in-band, so
    exit code alone is not a reliable "did the agent's task succeed" signal, only "did codex itself
    run cleanly."
  - `--output-last-message <FILE>` writes just the final agent text to a file (READ, not
    exercised).
  - `--output-schema <FILE>` constrains the final response to a JSON Schema (READ, not exercised).
  - `codex exec resume` supports continuing a thread non-interactively (**VERIFIED**, §5), so a
    switchboard-style "spawn, wait for turn.completed, then push another prompt" loop is entirely
    achievable through `exec` alone, without a persistent TUI pane at all, IF switchboard doesn't
    need the human-visible pane content Claude Code's TUI currently provides.
  - Caveat: `exec` mode has **no `-a/--ask-for-approval` flag** — only `-s/--sandbox`. Passing
    `-a` to `codex exec` is a hard CLI error (**VERIFIED**). So approval-policy-style behavior
    (interactively asking a human) doesn't apply to `exec`; you control risk purely via sandbox
    mode (`read-only` / `workspace-write` / `danger-full-access`) and the
    `--dangerously-bypass-approvals-and-sandbox` escape hatch. This is a meaningful difference
    from how switchboard drives Claude Code's approval flow today, if that mapping matters.
  - `--ephemeral` skips writing session files at all — useful if switchboard doesn't want probe
    runs cluttering the real session store (READ, not exercised, but would have simplified my
    cleanup below had I used it from the start).

## 7. Tooling / permissions

- **Sandbox modes** (`-s/--sandbox`): `read-only`, `workspace-write`, `danger-full-access`.
  Verified `read-only` actually blocks writes at the OS level: asked codex to `touch` a file in
  `/tmp` under `-s read-only`, and it got back `touch: ... Operation not permitted` (exit code 1
  from the *shell command*, surfaced to the model — the outer `codex exec` process itself still
  exited 0) (**VERIFIED**).
- **Approval modes** (`-a/--ask-for-approval`, TUI/interactive/`resume`/`fork`/`archive` only, not
  `exec`): `untrusted` (only pre-approved "trusted" commands like `ls`/`cat`/`sed` run without
  asking), `on-request` (model decides when to ask), `never` (never ask; failures go straight back
  to the model) (READ from `--help`; not separately exercised beyond confirming `-a` is rejected
  by `exec`).
- `--approve-for-me` routes approval requests through automatic review using the workspace-write
  sandbox (READ).
- `--dangerously-bypass-approvals-and-sandbox` is the closest equivalent to Claude Code's
  "dangerously skip permissions" — no sandbox, no prompts at all (READ, explicitly not exercised;
  it's flagged EXTREMELY DANGEROUS in the CLI's own help text).
- `-C/--cd <DIR>` sets the working root; `--add-dir <DIR>` adds extra writable directories
  alongside it (READ) — this is the equivalent of switchboard's worktree-scoping needs.
- `codex sandbox` subcommand exists to run arbitrary commands inside just the sandbox machinery,
  independent of an agent turn (READ, not explored).

## 8. Model selection

- `-m/--model <MODEL>` (or `/model` inside the TUI, or `model = "..."` in config.toml) selects the
  model. Current default model in Andrew's real config.toml is `gpt-5.5` with
  `model_reasoning_effort = "medium"` (**VERIFIED**, read directly, not modified).
  `-c model="o3"` is the example given in the CLI's own `-c` help text (READ).
- Valid model slugs, pulled directly from `codex debug models` (a command that dumps the full
  model catalog as JSON, including per-model default/available reasoning efforts and a full
  per-model system-instructions template): `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.5`, `gpt-5.6-luna`,
  `gpt-5.6-sol`, `gpt-5.6-terra`, plus a special `codex-auto-review` slug used by the `codex
  review` command (**VERIFIED** — these are the exact slugs present in the live catalog dump).
  Each model additionally supports multiple `--reasoning-effort`-style levels (`low`, `medium`,
  `high`, `xhigh`, `max`, and for `gpt-5.6-sol` an `ultra` level described as "maximum reasoning
  with automatic task delegation").
- `--oss` / `--local-provider <lmstudio|ollama>` switch to a local/open-source provider instead of
  OpenAI's hosted models (READ, not exercised).

## Cleanup performed

- Deleted all 5 test session ids created during this probe via `codex delete --force <uuid>`
  (**VERIFIED** — CLI confirmed `Deleted session <uuid>.` for each).
- Removed the `[projects."<scratch-repo-path>"] trust_level = "trusted"` entry that got added to
  the real `~/.codex/config.toml` when I accepted the trust prompt in the scratch repo; left every
  other line of that file (including Andrew's pre-existing real project trust entries) untouched.
- Deleted both scratch repos under the scratchpad directory.
- Killed the tmux probe session (`codexprobe`) and confirmed via `ps` that no `codex` process was
  left running afterward.
- Did not touch `~/.codex/AGENTS.md` (found empty, 0 bytes, pre-existing) or any other real file
  under `~/.codex`.

## What's still open / unverified

- Whether nested `AGENTS.md` files up the directory tree get merged, and in what order relative to
  the root one.
- The actual default value of `project_doc_max_bytes` and the built-in
  `project_doc_fallback_filenames` list.
- Whether `Esc` can interrupt a shell command that is still actively executing (only observed
  interrupting the turn/response cycle after a command had already finished).
- The shape of the `hooks` config struct beyond confirming the key exists.
- Why the `exec`-originated thread id didn't show up in `~/.codex/thread_history_1.sqlite` when I
  spot-checked it.
- Whether the "trust this directory" prompt can be bypassed non-interactively other than
  pre-seeding `~/.codex/config.toml` (I did not find a `--trust`/`--yes`-style flag in `--help`,
  but did not exhaustively search for one either).
