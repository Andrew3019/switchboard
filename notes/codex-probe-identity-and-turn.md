# Can a codex agent identify itself to `sb`, and can `sb done` still be enforced?

**Headline answers:**
- **A. Self-identification: yes, verified live.** `herdr pane split --env KEY=VALUE`
  injects an environment variable into the pane's shell that survives through
  `herdr agent start --kind codex` and is visible to every shell command codex's
  own shell tool runs — including, critically, whatever process `sb done`/`sb tell`
  would run. Switchboard does not need to invent anything: the exact same knob it
  would use for `SB_AGENT=<name>` already exists in herdr's pane API. Codex also
  turned out to already expose herdr's own `HERDR_PANE_ID` (and workspace/tab id)
  into its process environment on its own, unprompted — a second, independent
  identity signal, matching the `hooks.py` fallback that `broker.py`/`hooks.py`
  already use for Claude Code (`HERDR_PANE_ID` fallback when no session id is
  present).
- **B. The `sb done` gate: yes, a real equivalent exists — codex has its own
  Claude-Code-compatible `Stop` hook that can genuinely block turn completion**,
  not just the fire-and-forget `notify` hook the earlier scout note found. Verified
  live: a `hooks.Stop` command hook returning `{"decision":"block","reason":"..."}`
  kept a real `codex exec` turn from ending, repeatedly, exactly like Claude Code's
  own Stop-hook gate. The catch: it only fires when hook execution is trusted, and
  the only non-interactive way found to grant that trust is the CLI flag
  `--dangerously-bypass-hook-trust` (no config.toml pre-seed equivalent to the
  directory-trust `[projects."path"] trust_level` was found in this pass).

All work below was done in a disposable herdr workspace/pane and disposable
`CODEX_HOME` directories under the scratchpad dir, never against the live fleet's
store. Full teardown performed at the end (see "Cleanup").

---

## Part A — Self-identification

### A1. What env vars does a process actually get inside a herdr-started codex pane?

**VERIFIED.** Started `herdr agent start identity-probe --kind codex --pane <id>`
in a throwaway repo, dismissed the (expected) trust prompt, then had codex run
`env | sort` via its own shell tool and read the output file back directly (not
through the model's paraphrase). Full list, redacted only where irrelevant
(`notes/` — not copied here in full to avoid bloating this file, but every
`HERDR_*`/`CODEX_*` var is exact):

```
CODEX_CI=1
CODEX_PERMISSION_PROFILE=:workspace
CODEX_SANDBOX=seatbelt
CODEX_SANDBOX_NETWORK_DISABLED=1
CODEX_THREAD_ID=01a00a25-51da-7c10-a21e-bd55e0c53c51
HERDR_ENV=1
HERDR_PANE_ID=w1HC:p1
HERDR_SOCKET_PATH=/Users/andrew/.config/herdr/herdr.sock
HERDR_TAB_ID=w1HC:t1
HERDR_WORKSPACE_ID=w1HC
... (ordinary shell/HOME/PATH/CONDA vars)
```

Two things worth calling out that neither prior scout note found:

- **`HERDR_PANE_ID`/`HERDR_TAB_ID`/`HERDR_WORKSPACE_ID`/`HERDR_ENV`** are already
  present in a herdr pane's environment, for any kind, unconditionally — herdr
  itself exports them into the pane shell before any agent is even started. This
  means the `HERDR_PANE_ID` fallback path already coded into `hooks._agent_row`
  (`hooks.py:181-200`, per the prompt-plumbing scout note) would already have a
  real value to fall back to for a codex agent, with zero new work — it's not
  Claude-Code-specific plumbing, it's a herdr-pane-level environment fact.
- **`CODEX_THREAD_ID`** is set by codex itself, inside the sandboxed shell
  environment it hands to its own shell tool, and its value is the exact same
  UUID as the rollout filename on disk (cross-checked directly, see A3). This
  means an agent *can* self-report its own thread id via a plain shell command
  (`echo $CODEX_THREAD_ID`) if switchboard ever wanted a self-report channel
  instead of / in addition to external file-watching.

### A2. Can switchboard inject its own identity variable at spawn time?

**VERIFIED — yes, and it's a documented herdr flag, not a workaround.**
`herdr pane split --help` advertises `--env KEY=VALUE`. Tested directly:

```
herdr pane split w1HC:p1 --direction down --env SB_AGENT=identity-probe2 --no-focus
herdr agent start identity-probe2 --kind codex --pane w1HC:p2
herdr agent prompt w1HC:p2 "Run: env | grep -E 'SB_AGENT|HERDR|CODEX_THREAD' | sort > /tmp/probe_env_dump2.txt" --wait --timeout 60000
```

Result, read directly from the dump file:

```
CODEX_THREAD_ID=01a00a26-5629-79b3-8f74-c04162ef6dfd
HERDR_ENV=1
HERDR_PANE_ID=w1HC:p2
HERDR_SOCKET_PATH=/Users/andrew/.config/herdr/herdr.sock
HERDR_TAB_ID=w1HC:t1
HERDR_WORKSPACE_ID=w1HC
SB_AGENT=identity-probe2
```

`SB_AGENT=identity-probe2` came through cleanly into a command codex ran inside
its own shell tool sandbox — i.e. it isn't just visible to the top-level `codex`
process, it survives into the sandboxed subprocess codex spawns for tool calls.
This is exactly the channel switchboard would need: every `sb` verb an agent
invokes runs as a shell command in that same pane, so it would inherit `SB_AGENT`
the same way `CLAUDE_CODE_SESSION_ID` is inherited today. This works identically
for `--kind claude` panes too (not separately re-verified here, but `--env` is a
`herdr pane split` flag, not a per-kind one).

One nuance: this env var has to be set at **pane-split time**, before
`herdr agent start` runs — it's a property of the pane's shell, not of the agent
start call itself (`herdr agent start --help` has no `--env`/equivalent flag).
Switchboard's spawn path would need to create the pane itself (`pane split` or
`workspace create`, both of which take `--env`) rather than being handed an
already-existing pane, if it wants this mechanism. Not checked here whether
`workspace create` also accepts `--env` — only `pane split` was tested directly,
though `herdr workspace create --help`/`herdr pane split --help` sharing the same
flag name is suggestive it would.

### A3. Is the codex thread id obtainable from outside the pane, at spawn or shortly after?

**VERIFIED — not at true spawn time, but yes shortly after, well before turn
completion.**

- Immediately after `herdr agent start ... --kind codex` returns (before any
  prompt is sent), no rollout file exists yet under `~/.codex/sessions/` (checked
  with `find ... -mmin -1`, empty). So the thread id is **not** discoverable
  purely from the spawn call — codex doesn't allocate/persist a thread id until a
  turn actually starts.
- The moment the **first prompt is sent**, a new rollout file appears — verified
  by sending a prompt with a deliberately slow command (`sleep 8`) and finding the
  new file mid-turn (status still `working`, spinner glyph visible in
  `terminal_title`), well before `turn.completed`:
  ```
  rollout-2026-08-16T03-38-40-01a00a26-f5cf-7b00-87ea-9a2d46251dcc.jsonl
  ```
  So "shortly after spawn" in practice means "shortly after the first prompt is
  delivered," not "at `agent start` time" — switchboard would need to watch for
  the new rollout file (or the `notify`/thread.started JSON event, if driving via
  `exec`) after sending the first prompt, not before.
- Cross-checked `CODEX_THREAD_ID` (env var, §A1) against the rollout filename for
  two different panes — exact match both times, confirming the env var and the
  on-disk file agree and either can serve as the source of truth.
- `herdr pane report-agent-session --agent-session-id <id>` **was called directly
  and returns exit 0** (accepted), but — matching the earlier herdr-kind scout
  note's finding for Claude-kind agents too — neither `herdr agent get`,
  `herdr agent list`, `herdr pane get`, nor `herdr agent explain --verbose`
  ever surfaced an `agent_session` field afterward, for this codex pane or
  before it was reported. This is consistent with switchboard being the party
  that's expected to *hold* the id (in its own store), with
  `report-agent-session` existing purely to inform herdr for herdr's own
  restore/bookkeeping — not a read-back channel. Confirms the earlier scout
  note's read-only assertion with a direct call, rather than leaving it as READ.

**Practical shape this implies:** switchboard would send the first prompt, then
either poll for a new file under the per-agent `CODEX_HOME/sessions/.../` (per
the `CODEX_HOME` probe note) or watch for the `notify` hook's `thread-id` field,
capture the thread id, then call `herdr pane report-agent-session` with it. This
mirrors `broker.py:839-849`'s existing `report_session` flow closely — just a
different source event (first-prompt-sent, not a Claude Code hook payload) and a
different id shape (codex UUID vs `CLAUDE_CODE_SESSION_ID`).

---

## Part B — Can the `sb done` gate be preserved for codex?

### B1. Does codex have anything beyond fire-and-forget `notify`? — yes: a real `hooks` config with `Stop`/`SubagentStop` block semantics

The earlier cli-behaviour scout note flagged an unexplored `hooks` config key and
moved on. This pass mapped it, first by reading, then by making it actually fire.

**Reading (via `strings` on the codex binary and `--strict-config` type-error
probing — READ/VERIFIED as marked):**

- `strings /Users/andrew/.local/bin/codex` contains a full embedded JSON Schema
  (used by the app-server wire protocol) naming these hook events, verbatim:
  `PreToolUse`, `PostToolUse`, `SessionStart`, `SessionEnd`, `Stop`,
  `SubagentStop`, `UserPromptSubmit`, `PreCompact`, `PostCompact`,
  `PermissionRequest` (**READ**, strings output).
- The `stop.command.output` schema is, field for field, Claude Code's own Stop
  hook output shape: `{"continue": bool, "decision": "block", "reason": string,
  "stopReason": string, "suppressOutput": bool, "systemMessage": string}`, and a
  schema comment literally says: *"Claude requires `reason` when `decision` is
  `block`; we enforce that semantic rule during output parsing rather than in the
  JSON schema."* (**READ**, verbatim string from the binary — codex's own authors
  are explicitly modeling Claude Code's Stop-hook contract, not inventing a new
  one.)
- Companion error strings confirm the enforcement is real, not just documented:
  `"Stop hook returned decision:block without a non-empty reason"`,
  `"Stop hook exited with code 2 but did not write a continuation prompt to
  stderr"`, `"stop_hook_active"` field on the hook's *input* payload (**READ**) —
  this is the same anti-infinite-loop flag Claude Code's own Stop hook input
  carries.
- `codex features list` shows `hooks  stable  true` — enabled by default, not
  gated behind an opt-in flag (**VERIFIED**, ran the command).
- `-c` type-error probing confirmed the TOML shape: `hooks.<EventName>` is an
  array of matcher-groups, each `{matcher: "<glob>", hooks: [{type: "command",
  command: "<path>", ...}]}` — same shape as Claude Code's `settings.json` hooks
  block (**VERIFIED** via deliberate type errors: `hooks.Stop=1` → "expected a
  sequence"; `hooks.Stop=[1]` → "expected struct MatcherGroup"; a hook entry
  missing `type` → "missing field `type`").

### B2. Live test: does a `Stop` hook actually block turn completion?

**VERIFIED, end to end, with a real live loop.**

Config used (in a private scratch `CODEX_HOME`):

```toml
hooks.Stop = [
  { matcher = "*", hooks = [ { type = "command", command = "<scratch>/stop_hook.sh" } ] }
]
```

`stop_hook.sh` unconditionally logged its stdin and printed
`{"decision":"block","reason":"switchboard: you must run sb done before finishing"}`.

Ran: `codex --strict-config --dangerously-bypass-hook-trust exec --json "Say the
single word: PONG4"`.

Result: the hook fired **11 times over ~2 minutes** before I killed the run. Its
captured stdin shows the exact mechanics:

- 1st call: `"stop_hook_active":false` — turn tried to end normally.
- Every subsequent call: `"stop_hook_active":true`, and the model kept generating
  new `last_assistant_message` text in response to the injected block reason
  (it didn't understand what `sb` was, so it hallucinated plausible-sounding
  excuses like *"sb done was run again but cannot write .git/agentflow because
  the workspace is read-only"* — expected, since no real `sb` binary was in that
  scratch sandbox; the point being tested was purely mechanical: does the turn
  re-open, not whether the model's response makes sense).
- The turn never reached `turn.completed` — it kept looping, exactly matching
  Claude Code's own Stop-hook gate behavior (`hooks.py:272-321`), until I
  force-stopped the background process.

**Without `--dangerously-bypass-hook-trust`, the same config silently did
nothing** — three separate runs produced zero hook-log entries, no error, no
warning; the turn just completed normally as if no `hooks.Stop` config existed at
all. This is a **fail-open, not fail-closed** default: an untrusted hook is
silently skipped rather than blocking or erroring loudly. This matters a lot for
switchboard's design — if it relies on this mechanism, it must either always pass
`--dangerously-bypass-hook-trust` for its own managed `CODEX_HOME`-scoped hook
(reasonable, since switchboard authors the hook script itself, symmetric to how
it already fully controls the Claude Code hook settings file) or find a
config.toml-level way to pre-seed hook trust the way directory trust is
pre-seeded (`[projects."path"] trust_level = "trusted"`). **I did not find such a
config key in this pass** — no `codex hooks` CLI subcommand exists in this build,
and I did not locate a TOML equivalent to project trust for hooks (the binary's
strings do reference `TrustHook`/`HookTrustStatus`/`current_hash`-keyed trust
records, suggesting the *interactive* TUI has a one-time "trust this hook" prompt
backed by some persisted, content-hashed trust store, but I did not chase down
where that's persisted or whether it's settable non-interactively). Flag this as
the one open item that would need resolving before this is production-usable
without `--dangerously-bypass-hook-trust` on every spawn.

### B3. Fallback substitute (notify + nudge) — not needed, not tested end-to-end

Because B2 confirms a real blocking mechanism exists, the task's fallback
question ("if nothing can block, does a notify-triggered nudge work as a
substitute") is moot for codex 0.147.0 — a genuine block is available and was
proven live. I did not additionally build and test the notify-fires→switchboard-
notices→pushes-follow-up-prompt loop, since the direct mechanism it exists to
approximate already works. If `--dangerously-bypass-hook-trust`-style trust
turns out to be unacceptable for switchboard's threat model for some reason, that
nudge loop is the fallback worth prototyping next — the `notify` hook itself was
already fully verified working (including in `exec` mode) by the earlier
cli-behaviour scout note, so the missing piece would purely be the "push a
follow-up prompt" half, which is just `herdr agent prompt <pane> <text>` again.

### B4. Turn/activity signal (switchboard's `UserPromptSubmit` equivalent)

**Not separately live-tested this pass** — `UserPromptSubmit` is confirmed to
exist as a hook event name in the same schema (§B1, READ), with the same
`hooks.UserPromptSubmit` config shape as `Stop`, so by direct analogy with B2 it
should work the same way (fires, can be trusted the same way, can return a
blocking decision per its own schema fragment). I did not run a live test of it
in this pass — treat "UserPromptSubmit hook fires and works exactly like Stop" as
**plausible, not verified**, unlike the Stop-hook finding above which I drove
live to a real observed effect.

---

## What this changes about the earlier notes

`notes/codex-scout-cli-behaviour.md` §3 said: *"There is also a `hooks` config key
... not investigated further."* This pass investigated it and found it is not a
minor addendum to `notify` — it is a essentially a **Claude-Code-hook-compatible
system**, deliberately modeled on Claude Code's own Stop-hook block semantics
(confirmed by the binary's own error-message/schema-comment text referencing
"Claude" directly). For the specific question of preserving `sb done`'s
enforcement, this means switchboard likely does **not** need to fall back to an
approximate nudge loop — the real mechanism Claude Code uses today has a
near-exact codex counterpart, gated by one additional concept (hook trust) that
Claude Code's `--settings`/`--bare` gate doesn't have.

## What's still open / unverified

- No non-interactive, config.toml-level way to pre-seed **hook** trust was found
  (only directory trust has that). `--dangerously-bypass-hook-trust` is the only
  confirmed non-interactive path; whether that's acceptable for switchboard to
  pass unconditionally on every codex spawn is a design call, not something this
  probe can answer.
- Whether `herdr workspace create` (not just `herdr pane split`) also accepts
  `--env` was not directly tested — only inferred from the shared flag name.
  Matters if switchboard's spawn path creates the workspace and pane together
  rather than splitting an existing one.
- `UserPromptSubmit` hook behavior was read from the schema, not fired live
  (§B4) — treat as plausible, not verified.
- Whether `PreToolUse`/`PermissionRequest` hooks (also in the same schema) could
  give switchboard a permission-mode-equivalent gate was not explored — out of
  scope for this probe's two questions, but worth a follow-up given how much of
  Claude Code's hook vocabulary codex apparently mirrors.
- The exact persisted form of interactive hook trust (`TrustHook`,
  `HookTrustStatus`, `current_hash` — strings only, not exercised) was not
  chased down; it might turn out to be a `CODEX_HOME`-local file that could be
  pre-seeded the same way directory trust was pre-seeded in the earlier
  `CODEX_HOME` probe note, but this pass didn't test that path directly, since
  `--dangerously-bypass-hook-trust` already gave a working non-interactive proof.

## Cleanup performed

- Deleted all 3 codex sessions created in the real `~/.codex/sessions/` (via
  panes started under herdr, which use the real `CODEX_HOME` by default):
  `01a00a25-51da-7c10-a21e-bd55e0c53c51`, `01a00a26-5629-79b3-8f74-c04162ef6dfd`,
  `01a00a26-f5cf-7b00-87ea-9a2d46251dcc` — each confirmed via `codex delete
  --force <id>` → `Deleted session <id>.`.
- Removed the one `[projects."<scratch repo path>"] trust_level = "trusted"`
  entry that got written to the real `~/.codex/config.toml` by accepting the
  trust prompt; every other line (Andrew's real project trust entries, model
  settings, `[tui]` block) left untouched — verified by reading the file before
  and after the edit.
- Closed the herdr workspace (`herdr workspace close w1HC`), confirmed via
  `pgrep -fl '^codex'` that no codex process was left running afterward (empty
  output).
- Deleted the entire scratch tree used for this probe (`.../scratchpad/
  probe-identity/`, including both private `CODEX_HOME` dirs, the copied
  `auth.json`s, the scratch repo, and the hook script/log files) — confirmed via
  a listing of the parent scratchpad dir afterward (empty).
- Did not touch any other file under the real `~/.codex/` beyond the one
  trust-entry removal above.
- No `pkill` was used anywhere in this probe — all teardown went through
  `herdr workspace close` and `codex delete --force <id>`.
