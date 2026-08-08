# 06 — Agent Communication, Plugin Substrates, and Programmatic Control

Research date: 2026-08-06. Sources are primary docs (Anthropic `code.claude.com/docs`,
OpenAI `learn.chatgpt.com/docs`, `modelcontextprotocol.io`, `agentclientprotocol.com`,
`a2a-protocol.org`, `docs.langchain.com`, `docs.ag-ui.com`) plus community write-ups where
noted. Everything marked **(verified)** was read from a primary doc during this pass.

---

# PART 0 — RECOMMENDATIONS (read this, skip the rest)

## 0.1 What a graph EDGE should physically be

> **An edge is a routing permission enforced by a local broker daemon. The physical
> carrier is: outbound = an MCP tool call; inbound = an MCP notification pushed into
> the live session (Claude Code `channels`) or a steer injected into the live turn
> (Codex `turn/steer`). The edge itself is a row in SQLite.**

Do **not** make an edge a shared file, a shared context, or a socket between two agent
processes. Make it a **capability check inside one broker**.

Concretely — the **`wf-bus`** design:

```
                        ┌──────────────────────────────────────┐
                        │  wfd (broker daemon, single process)  │
                        │  • SQLite (WAL) : nodes, edges,       │
                        │    mailbox, events, status            │
                        │  • unix socket: ~/.wf/wfd.sock        │
                        └───▲───────────────▲──────────────▲────┘
             stdio MCP      │               │              │
        ┌───────────────────┴──┐   ┌────────┴─────┐  ┌─────┴────────┐
        │ wf-bus --agent A1    │   │ wf-bus --A2  │  │ controller   │
        │ (MCP server subproc) │   │              │  │ (SQL reader) │
        └───────▲──────────────┘   └──────▲───────┘  └──────────────┘
                │ stdio                    │
        ┌───────┴──────────────┐   ┌───────┴──────┐
        │ claude (CC session)  │   │ codex app-srv │
        └──────────────────────┘   └───────────────┘
```

* Every agent process gets exactly **one** extra MCP server on its stdio: `wf-bus`,
  launched with `--agent-id <node-id>`. It is a thin client of `wfd` over a unix socket.
* **Outbound** (agent → anything) is a **tool call**, never a file write:
  * `wf__send(to, kind, payload)` — message another node
  * `wf__report(status, payload)` — structured status (see 0.2)
  * `wf__ask(question, schema?)` — escalate to human/controller, blocks
  * `wf__inbox_wait(timeout_s)` — blocking receive (the Codex fallback, see below)
  * plus your tooling plugins: `todo__*`, `learnings__*`
* **Edge enforcement lives in `wfd`.** `wf__send(to="A7")` returns
  `{"error":"no edge A1→A7"}` if the graph has no edge. The graph is therefore *load
  bearing*, not a visualization. This is the single most important design decision: it
  is the only way "a graph of who can talk to whom" means anything at runtime.
* **Inbound** (anything → agent) is asymmetric between backends, and this is where the
  abstraction has to work:

  | Backend | Inbound mechanism | Wakes an idle session? | Interrupts a busy turn? |
  |---|---|---|---|
  | Claude Code | MCP **channel** notification `notifications/claude/channel` from `wf-bus` | **Yes** | No — queues, delivered together on next turn **(verified)** |
  | Claude Code (alt) | `--input-format stream-json` user message on stdin | Yes | Queues as its own turn **(verified)** |
  | Codex | app-server `turn/steer` (append input to in-flight turn) | n/a (start `turn/start`) | **Yes** — that's its purpose **(verified)** |
  | Either (fallback) | agent calls `wf__inbox_wait()`, tool blocks until a message arrives | n/a | n/a — cooperative |

  So: `wfd` holds one inbound strategy per backend behind `deliver(node_id, msg)`.
  Claude Code gets a channel push; Codex gets `turn/steer`. `wf__inbox_wait` is the
  portable floor that works even with plain `codex exec`.

**Why an MCP server and not A2A/ACP/a socket between agents:** because MCP is the *only*
thing both Claude Code and Codex already speak as first-class config, it costs one
subprocess, the agent-facing surface is tool calls (your principle #1 and #5), and the
Claude Code channel extension gives you **push into a running session** — which nothing
else on this list gives you.

## 0.2 How the controller reads agent state cheaply

> **The controller reads SQLite. It never touches a transcript, never parses stdout,
> and never talks to an LLM unless a status is ambiguous. Agents write status through a
> forced tool call, and a `Stop` hook refuses to let them finish without one.**

Three layers, in reliability order:

**Layer 1 — the `wf__report` tool (primary).**
Agent calls `wf__report({status, summary, artifacts, blocked_on})`. `status` is a
closed enum: `running | done | blocked | needs_review | failed`. `wfd` writes it to
`node_status` and appends to `events`. Cost to controller: one `SELECT`. Zero tokens.

**Layer 2 — the Stop-hook gate (the enforcement daemon).** This is the crux, and it is
the concrete answer to "abstract away from skills". Both CLIs have a `Stop` hook that
can **block the agent from finishing**:

* Claude Code `Stop` hook, exit 2 → "Prevents stop, continues conversation"; or exit 0
  with `{"decision":"block","reason":"..."}` **(verified, hooks reference)**
* Codex `Stop` / `SubagentStop` hooks: "Return `decision: "block"` to continue
  processing", exit code 2 blocks **(verified, Codex hooks doc)**

So the hook is a 20-line script:

```jsonc
// .claude/settings.json  AND  .codex/hooks.json — near-identical shape
{ "hooks": { "Stop": [ { "hooks": [
  { "type": "command", "command": "wf-stop-gate" } ] } ] } }
```

```python
# wf-stop-gate: reads hook JSON on stdin, asks wfd "did node N report this turn?"
if not reported(session_id):
    print(json.dumps({"decision": "block",
      "reason": "You must call wf__report with your final status before finishing."}))
```

You now have a *mechanically enforced* protocol. No prompt text, no skill, no hoping.
An agent literally cannot end a turn without emitting structured state. This is the
single highest-leverage thing in this document.

**Layer 3 — schema-validated final result (belt and braces, one-shot agents only).**
* Claude Code: `claude -p --output-format json --json-schema '<JSON Schema>'` →
  result object carries `structured_output`. Invalid schema is now a hard error
  (v2.1.205+); before that it silently degraded to text **(verified, CLI reference)**.
  SDK equivalent: `ClaudeAgentOptions(output_format={"type":"json_schema","schema":…})`,
  surfaced on `ResultMessage.structured_output` and **not streamed as deltas**.
* Codex: `codex exec --output-schema <file>`. Two live caveats: it **requires a gpt-5
  family model**, and it **cannot be combined with `codex exec resume`**
  (openai/codex#14343). There is also an open bug where `--json` and `--output-schema`
  are "silently ignored when tools/MCP servers are active" (openai/codex#15451) — which
  is exactly your configuration. **Do not depend on Codex structured output.** Depend on
  the tool call + Stop gate, which works regardless.

**Also emit events from hooks, for free, into the same log.** `PostToolUse`,
`SessionStart`, `SubagentStart/Stop`, `Notification`, `PreCompact` all deliver JSON on
stdin with `session_id`, `cwd`, `transcript_path`. Pipe them to `wfd` with
`"async": true` (Claude Code) so they never block the agent. The controller now has a
*derived* liveness signal (last tool call at T) separate from the *declared* status —
which is how you detect a wedged agent that never reported.

**Controller shape:** deterministic scheduler over SQL, escalating to an LLM only on
`status = blocked` with an unrecognized `blocked_on`. The PR example from the braindump
is a pure state machine: `WHEN node(a1).status='done' AND edge(a1→a2) THEN
deliver(a2, {kind:'unblock', payload:{...}})`. That costs zero tokens.

## 0.3 Protocols: adopt vs. ignore

| Protocol | Verdict | Why |
|---|---|---|
| **MCP (tools)** | **ADOPT** — the tooling-plugin substrate | Only thing both CLIs natively load. `mcp__<server>__<tool>` naming, `allowedTools` wildcards, stdio subprocess. |
| **MCP `notifications/claude/channel`** (Claude Code channel extension) | **ADOPT** — this is your inbound edge on Claude Code | Push into a *running* session. Nothing else does this. Research preview; needs `--dangerously-load-development-channels server:wf-bus` today. |
| **Codex app-server JSON-RPC** | **ADOPT** — this is your Codex driver | `thread/start`, `turn/start`, `turn/steer`, `turn/interrupt`, `thread/fork`, bidirectional approval requests. Far better than scraping `codex exec`. |
| **Claude Code Agent SDK / `stream-json`** | **ADOPT** — this is your Claude driver | Typed messages, `interrupt()`, `can_use_tool`, in-process MCP, hooks-in-SDK. |
| **MCP elicitation** | **Adopt lightly** | Good mid-tool-call human prompt. But in MCP 2026-07-28 it moved to Multi Round-Trip Requests, and Claude Code intercepts it via `Elicitation`/`ElicitationResult` hooks. Use it for `wf__ask`; don't build the architecture on it. |
| **MCP sampling / roots / logging** | **IGNORE** | **Deprecated as of MCP 2026-07-28** with a 12-month sunset. Do not build on sampling. |
| **ACP — Zed's Agent Client Protocol** | **STEAL, DON'T ADOPT** | Genuinely the closest thing to "one interface for both CLIs" (`@zed-industries/claude-code-acp` and `zed-industries/codex-acp` both exist). But it is *editor-shaped*: it hands you a streaming transcript + permission prompts, i.e. exactly the thing you said you don't want to consume. Adds a third process per agent and loses backend-specific power (Codex `thread/fork`, CC channels). **Steal its vocabulary** — `tool_call`/`tool_call_update` status enum, `StopReason` set (`end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, `cancelled`), `session/request_permission` shape. Revisit only if you add a third backend. |
| **A2A (Agent2Agent)** | **IGNORE** | v1.0.0, JSON-RPC/gRPC/REST over HTTP, Agent Cards, OAuth2/mTLS, webhook push configs, multi-tenancy. Designed for *opaque agents across organizational boundaries*. You are spawning subprocesses on one laptop and you already know their capabilities. **Steal one thing: the task state enum** — `submitted / working / input_required / auth_required / completed / failed / canceled / rejected`. That maps almost 1:1 onto your `running/blocked/needs_review/done/failed`; use theirs so you're not inventing vocabulary. |
| **ACP (BeeAI/IBM, the *other* ACP)** | **IGNORE** | Effectively superseded — the agent-comms ACP folded toward A2A under Linux Foundation. Note the name collision with Zed's ACP; they are unrelated. |
| **AGNTCY (Cisco)** | **IGNORE** | OASF schemas, Agent Directory, SLIM transport. Enterprise "Internet of Agents" discovery. Zero relevance to a local single-user tool. |
| **AG-UI (CopilotKit)** | **IGNORE the protocol, STEAL the state model** | Its `STATE_SNAPSHOT` + `STATE_DELTA` (JSON Patch RFC 6902) pattern is exactly right for your web/TUI views over `wfd`: send a snapshot on connect, JSON Patch deltas after. Implement that idea over a plain SSE/websocket from `wfd`. Don't take the dependency. |
| **LangChain Agent Protocol / Agent Inbox** | **IGNORE the protocol, STEAL the UX** | The "inbox of things that need me right now" is precisely your workflow status board. But LangGraph's runtime assumes *you* own the agent loop; you don't, the CLIs do. |
| **LangGraph `interrupt()`** | **STEAL ONE WARNING** | On resume, **the entire node re-executes from the top** — `interrupt()` is not a coroutine suspend. Hence "make pre-interrupt side effects idempotent". Your equivalent: a blocking `wf__ask` tool call *does* suspend properly (the tool just doesn't return), which is strictly better. Note it as an advantage of the tool-call design. |
| **Temporal / Restate / DBOS / Inngest** | **IGNORE for v1** | Durable execution is the correct mental model for "supervisor must not lose state", and Temporal signals are the textbook version of your human-injection channel. But a durable-execution server for a local dev tool is absurd. SQLite + an append-only `events` table gives you 90% of it. Revisit only if workflows must survive across days and machines. |
| **Actor model (Erlang/OTP, Akka, Ray)** | **STEAL THE SUPERVISION TREE** | Answers your open question "what happens to a sub-controller's children when a parent abandons?" Answer: OTP's `shutdown` strategy. Each node has `restart: permanent|transient|temporary` and parents kill children on abandon (`one_for_all`). Implement as: `wfd` owns the process tree, abandoning a node SIGTERMs its subtree. Note Claude Code handles SIGTERM well — aborts the turn, kills the Bash process tree, runs `SessionEnd` hooks, exits 143 **(verified)**. |
| **NATS / Redis / ZeroMQ** | **IGNORE** | You have ≤ 30 local processes. SQLite in WAL mode plus a unix socket is lighter, has zero daemons to install, and is *inspectable with `sqlite3`* — which matters enormously for a debuggable local tool. |

## 0.4 The one-paragraph architecture

`wfd` is a single Rust/Go/Python daemon owning `~/.wf/state.db` (SQLite WAL) and
`~/.wf/wfd.sock`. It spawns agents: Claude Code via the Agent SDK (or `claude -p
--output-format stream-json --input-format stream-json`), Codex via `codex app-server`
JSON-RPC. Every agent is launched with (a) the `wf-bus` MCP server on stdio, (b) a
`Stop` hook pointing at `wf-stop-gate`, (c) a `PostToolUse`/`SessionStart`/`SubagentStop`
hook firing `wf-event` asynchronously. Agents talk outward by calling tools; the graph
edge is a permission check in `wfd`. `wfd` talks inward via channel notifications (CC) or
`turn/steer` (Codex). The controller is a SQL-driven state machine in `wfd` that only
invokes an LLM on ambiguity. The web UI and TUI are both SSE clients of `wfd` receiving
a state snapshot then JSON Patch deltas. Skills exist, but only as the payload of a
template step — the *protocol* is enforced by hooks and tools.

---

# PART 1 — Programmatically driving Claude Code

## 1.1 The three control planes

1. **CLI headless (`-p`)** — good for one-shot, bad for long-lived.
2. **`-p` + `--output-format stream-json --input-format stream-json`** — the documented
   "only CLI mechanism for programmatic bidirectional communication". Full duplex NDJSON.
3. **Agent SDK (Python `claude-agent-sdk`, TS `@anthropic-ai/claude-agent-sdk`)** — same
   engine, typed objects, plus control methods the CLI can't express (`interrupt()`,
   `set_permission_mode()`, `can_use_tool` callback, in-process MCP servers).

**Recommendation: drive Claude Code through the SDK, not the CLI.** The SDK is a
superset and gives you `ClaudeSDKClient` as a long-lived object.

## 1.2 Getting STRUCTURED STATE out — the concrete answer

Five independent channels, all of which avoid scraping a terminal:

### (a) The `stream-json` event stream (the transcript, structured)

`claude -p --output-format stream-json --verbose` emits one JSON object per line.
Message types **(verified)**:

* `system` / `subtype: "init"` — first event. Carries `session_id`, `model`, `tools[]`,
  `mcp_servers[]` (each `{name, status}` where status ∈ `pending|connected|failed|
  needs-auth|disabled`), `mcp_server_errors[]`, `plugins[]`, `plugin_errors[]`,
  `capabilities[]` (feature-detect strings like `interrupt_receipt_v1`).
* `system` / `subtype: "api_retry"` — `{attempt, max_retries, retry_delay_ms,
  error_status, error}` where `error` ∈ `rate_limit | overloaded |
  authentication_failed | oauth_org_not_allowed | billing_error | invalid_request |
  model_not_found | server_error | max_output_tokens | unknown`.
* `system` / `subtype: "plugin_install"` — `{status: started|installed|failed|completed, name, error}`.
* `assistant` / `user` — content blocks (`text`, `thinking`, `tool_use`,
  `tool_result`). **`parent_tool_use_id`** is the subagent tracer: `null` for the main
  thread, else the Agent-tool call ID that spawned it. Nested subagents chain, so you can
  rebuild the full tree. By default only subagent `tool_use`/`tool_result` are forwarded;
  `--forward-subagent-text` (v2.1.211+) adds text and thinking.
* `stream_event` — raw API deltas, only with `--include-partial-messages`.
* `hook_event` — only with `--include-hook-events` (also `hook_started`,
  `hook_progress`, `hook_response` around `SessionStart`/`Setup`).
* `result` — final. `{subtype: success|error|interrupted, result, structured_output,
  session_id, total_cost_usd, usage, terminal_reason, tool_use_count, tool_error_count}`.
  `terminal_reason` includes `aborted_streaming`, `aborted_tools`.

This is a real event stream, not terminal scraping. **But it is still a transcript**, and
your controller is not supposed to read transcripts. Use it in `wfd` for the *derived*
signals only (tool counts, cost, errors) — never hand it to the controller LLM.

### (b) Schema-constrained final output

`--json-schema '<schema>'` with `--output-format json` → `.structured_output`.
SDK: `output_format={"type":"json_schema","schema":{…}}` → `ResultMessage.structured_output`.
Not streamed. Invalid schemas now hard-error (v2.1.205+). `format` keyword accepted as an
annotation but **not enforced**.

### (c) Hooks as an event bus (the "daemon" mechanism) — see Part 7

30 hook events. Common stdin envelope on every one: `session_id`, `prompt_id`,
`transcript_path`, `cwd`, `permission_mode`, `effort.level`, `hook_event_name`, plus
`agent_id` / `agent_type` inside subagents. Handler types: `command`, `http`,
`mcp_tool`, `prompt`, `agent`. `"async": true` runs it without blocking; `"asyncRewake":
true` runs it in background and **wakes Claude when it exits 2** — a genuine
out-of-band interrupt primitive.

### (d) MCP tool calls (the primary, intentional channel)

Your `wf__report` tool. Agent-authored, schema-validated by the tool's `inputSchema`,
delivered directly to `wfd`. Nothing to parse.

### (e) Session store / session inspection API

`list_sessions()`, `get_session_info()`, `get_session_messages()`, `rename_session()`,
`tag_session()` — the SDK exposes the on-disk session index programmatically.
`SDKSessionInfo` has `{session_id, summary, last_modified, custom_title, first_prompt,
git_branch, cwd, tag, created_at}`. **`tag_session()` is a cheap out-of-band status
channel** the controller can read without opening anything. And `session_store` +
`session_store_flush: "eager"|"batched"` lets you mirror transcripts to your own backend.

## 1.3 Session lifecycle

* `--session-id <uuid>` — you choose the ID. **Do this**: `wfd` mints node IDs as UUIDs
  and uses them as session IDs, so the mapping is trivial.
* `--resume <id>` / `--continue` — resumes. Since v2.1.223, `--resume <id>` finds the
  session in *any* project on the machine, not just cwd.
* `--fork-session` — branch a new session ID from a checkpoint instead of mutating the
  original. Use this for speculative/parallel work (mirrors Codex `thread/fork`).
* `SessionStart` hook re-fires on resume with `source: "resume"` or `"fork"` — so your
  event log records the branch.
* `--no-session-persistence` for ephemeral scratch agents.
* SIGTERM → aborts turn, kills Bash process tree, runs `SessionEnd` hooks, exit 143.

## 1.4 Permissions & interception

* `permission_mode`: `default | acceptEdits | plan | auto | dontAsk | bypassPermissions`.
  `auto` uses a model classifier. `dontAsk` denies anything not pre-approved — the right
  mode for unattended workers.
* `can_use_tool` callback (SDK) — called *only when the permission flow reaches a
  prompt*. Return `PermissionResultAllow(updated_input=…)` (you can **rewrite tool
  input**) or `PermissionResultDeny(message, interrupt=True)`. `ToolPermissionContext`
  carries `tool_use_id`, `agent_id`, `blocked_path`, `decision_reason`, `title`.
* `--permission-prompt-tool <mcp tool>` — CLI equivalent; route prompts to `wf-bus`.
* Channel **permission relay**: `notifications/claude/channel/permission_request`
  `{request_id, tool_name, description, input_preview}` → your server answers with
  `notifications/claude/channel/permission` `{request_id, behavior: allow|deny}`. Both
  the terminal dialog and the remote stay live; first answer wins. **(verified)**

## 1.5 MCP config specifics

* `mcp_servers`: `stdio` (`command`/`args`/`env`), `sse`, `http` (alias
  `streamable-http` in JSON only), and `McpSdkServerConfig` (in-process, via
  `create_sdk_mcp_server()` + `@tool` decorator — never delays first turn).
* `--strict-mcp-config` / `strict_mcp_config=True` — ignore `.mcp.json`, user settings,
  plugins, connectors. **Use this for worker agents** so a teammate's config can't leak in.
* Connection timing: stdio servers block the first turn up to `MCP_TIMEOUT` (30s default).
  `MCP_CONNECTION_NONBLOCKING=0` + `MCP_CONNECT_TIMEOUT_MS` control the earlier batch wait.
  `alwaysLoad: true` exempts a server from tool-search deferral.
* Tool output > 25,000 tokens is spilled to a file and replaced with an error naming the
  path. Raise with `MAX_MCP_OUTPUT_TOKENS`, or per-tool `anthropic/maxResultSizeChars`.
* `--bare` skips auto-discovery of hooks/skills/plugins/MCP/CLAUDE.md — **the correct
  base for reproducible worker agents**, then add exactly what you want with
  `--mcp-config`, `--settings`, `--agents`, `--plugin-dir`.

## 1.6 Subagents

`AgentDefinition` (SDK) / `--agents '<json>'` (CLI) fields: `description`, `prompt`,
`tools`, `disallowedTools`, `model` (incl. `"inherit"`), `skills`, `memory`,
`mcpServers`, `initialPrompt`, `maxTurns`, `background`, `effort`, `permissionMode`.
`background: true` makes a non-blocking task; `stop_task(task_id)` cancels it and
`TaskNotificationMessage {task_id, status}` reports it.

**Design note:** Claude Code's own subagent tree is a *tree*, controlled by the parent
model's decisions, and its messages are only observable as transcript. Your graph must
be *outside* it. Use `Task`/subagents for intra-node parallelism; use `wfd` nodes for the
graph. Don't try to make Claude's subagent tree be your graph.

---

# PART 2 — Programmatically driving Codex

## 2.1 Three control planes, same as Claude — but the good one is different

1. **`codex exec`** — one-shot headless. Flags: `--json` (aliased `--experimental-json`)
   for JSONL, `--output-schema <file>`, `-o <path>` (write final message),
   `--full-auto` (workspace-write + on-request approvals), `--yolo` (bypass all),
   `--ephemeral` (don't persist rollout), `--skip-git-repo-check`, `-C <path>`, `-m
   <model>`, `--include-plan-tool`, `codex exec resume <id> | --last`.
   JSONL events: `thread.started` (session id), `item.completed` (messages, tool
   results), `turn.completed` (usage summary).
2. **`codex mcp-server`** — Codex *as* an MCP server, exposing `codex` and `codex_reply`
   tools. Useful if you want Claude to delegate to Codex as a tool. Not useful as your
   driver: OpenAI themselves said MCP's request/response shape "could not accommodate
   streaming diffs, approval workflows, thread persistence, or server-initiated
   requests" — which is why they built the app-server.
3. **`codex app-server`** — **use this.** Long-lived bidirectional JSON-RPC 2.0 process
   that powers every Codex surface (web, desktop, VS Code, CLI).

## 2.2 The app-server (the Codex answer to "structured state")

Transport: stdio NDJSON (default), experimental WebSocket (`--listen ws://127.0.0.1:PORT`)
and unix sockets. `"jsonrpc":"2.0"` is omitted on the wire. Mandatory `initialize` →
`initialized` handshake.

**Primitives:** Threads (conversations) → Turns (a user request + agent work) → Items
(messages, commands, file changes, tool calls).

**Methods (client → server):**

| Method | Purpose |
|---|---|
| `thread/start` | new session; per-thread model, effort, sandbox, **output schema**, MCP overrides |
| `thread/resume` | reopen persisted thread |
| `thread/fork` | branch without affecting original |
| `thread/read`, `thread/list` | read history / paginated index |
| `thread/rollback` | drop last N turns |
| `thread/compact`, `thread/archive`, `thread/name/set` | housekeeping |
| `turn/start` | submit input (text, images, **`skill_inputs`**); per-turn overrides for model, effort, personality, sandbox policy, output schema, dynamic tools |
| `turn/steer` | **append input to an in-flight turn** ← your inbound edge |
| `turn/interrupt` | abort cleanly |
| `review/start` | run the code reviewer against a diff/branch/commit range |
| `mcpServer/tool/call` | invoke a configured MCP server's tool directly |
| `account/read`, `config/read`, `model/list` | introspection |

**Notifications (server → client):** `turn/started`, `turn/completed`, `item/started`,
`item/completed`, and delta streams `item/agentMessage/delta`,
`item/reasoning/textDelta`, `item/reasoning/summaryTextDelta`,
`item/reasoning/summaryPartAdded`. **For a controller you subscribe to the lifecycle
four and ignore the deltas entirely.**

**Server → client *requests* (bidirectional):** `execCommandApproval` and
`applyPatchApproval`; you answer `accept` / `decline` / `cancel`. This is Codex's
`can_use_tool`. Set `approvals_reviewer = "user"` to route every approval to you.

**Error `-32001` = busy/overloaded.** Back off and retry; the Python SDK ships
`retry_on_overload`.

**SDKs:** official `openai-codex-app-server-sdk` (Python) with `Codex()`/`AsyncCodex()`,
`Thread` (start/resume/fork/run/compact), `TurnHandle` (streaming/steer/interrupt).
Not exposed by the high-level API (use the `request(...)` escape hatch): WebSocket,
`thread/list`, `thread/rollback`, `thread/fork`, `mcpServer/tool/call`, `review/start`,
`account/read`, `config/read`, dynamic tools, and **approval callbacks** (only modes).

**On-disk state** (`~/.codex/`): `sessions/YYYY/MM/DD/rollout-<ISO>-<id>.jsonl` — NDJSON
starting with a `session_meta` record `{id, cwd, model, cli_version}` then turn/item
events; `session_index.jsonl`; `state_5.sqlite`; `logs_2.sqlite`; `history.jsonl`.
The rollout files are a durable, replayable thread representation — a legitimate
recovery/audit source, equivalent to Claude Code's `transcript_path`.

## 2.3 Codex hooks — closer parity than expected

Codex has hooks. Events **(verified)**: `SessionStart`, `SessionEnd`, `SubagentStart`,
`SubagentStop`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`,
`PreCompact`, `PostCompact`, `Stop`.

Config: `~/.codex/hooks.json` or `[hooks]` in `~/.codex/config.toml`; repo-level
`.codex/hooks.json` or `.codex/config.toml`; plugin-bundled `hooks/hooks.json`. Layers
*merge*, they don't override. The JSON shape is deliberately Claude-Code-shaped:

```json
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[
  {"type":"command","command":"./x.sh","timeout":600,
   "statusMessage":"…","additionalContextLimit":2500}]}]}}
```

Stdin envelope: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`,
`permission_mode`, plus `turn_id` on turn-scoped events. Stdout JSON: `continue`,
`stopReason`, `systemMessage`, `suppressOutput`; per-event `permissionDecision: "deny"`,
`updatedInput`, `decision: "block"`, `additionalContext`, `decision.behavior`.
Exit 0 = ok (parse stdout JSON), **exit 2 = block**, other = non-fatal failure.
Default timeout 600s (`SessionEnd` is 1s, max 3s). Output over
`additionalContextLimit` (~2500 tokens) spills to
`<temp_dir>/hook_outputs/<session_id>/<uuid>.txt`.
Matchers are regex; `PreToolUse`/`PostToolUse` match tool name (`Bash`, `apply_patch`,
MCP names); `SessionStart` matches `startup|resume|clear|compact`; `UserPromptSubmit`
and `Stop` take no matcher.

**Consequence: your `wf-stop-gate` script is portable across both backends with only a
key-name shim.** That is a much better parity story than the braindump assumed.

## 2.4 Codex skills, subagents, AGENTS.md

* **Skills**: `SKILL.md` + YAML frontmatter, with `scripts/`, `references/`, `assets/`,
  `agents/openai.yaml`. Discovery order: System → Admin `/etc/codex/skills` → User
  `$HOME/.agents/skills` → Repo `.agents/skills`. Invocable explicitly, and passed
  programmatically as `skill_inputs` on `turn/start`.
* **Subagents**: TOML at `~/.codex/agents/*.toml` or `.codex/agents/*.toml` with `name`,
  `description`, `developer_instructions`, `model`, `reasoning_effort`, `sandbox_mode`,
  MCP servers, skills. Spawned only on explicit user request or `/agent`.
* **AGENTS.md** ≡ `CLAUDE.md`.
* **MCP servers** in `config.toml`: stdio (`command`, `args`, `env`, `cwd`, startup/tool
  timeouts) and Streamable HTTP (URL, bearer token, optional OAuth).

## 2.5 Where Codex falls short, and how to paper over it

| Gap | Impact | Papering-over |
|---|---|---|
| **No channel equivalent** — nothing pushes an unsolicited event into an idle Codex thread | This is the big one | Use `turn/steer` for in-flight; for idle, `wfd` just calls `turn/start` with the message. Portable floor: a blocking `wf__inbox_wait` tool. |
| `--output-schema` needs gpt-5 family, can't combine with `exec resume`, and is reportedly ignored when MCP servers are active (#15451) | Structured output unreliable | **Don't rely on it.** Use `wf__report` + Stop gate. |
| No `--json-schema` on the persistent app-server path in the high-level SDK | Same | `output_schema` *is* accepted on `thread/start` / `turn/start` params; go through `request(...)`. |
| Approval callbacks not in the high-level Python SDK | Can't intercept per-call | Use the low-level `request(...)`/notification handler; the bidirectional `execCommandApproval` / `applyPatchApproval` requests are in the protocol. |
| App-server + WebSocket are marked **experimental**, "not supported for production" | Churn risk | Pin the CLI version; regenerate schemas with `generate-ts` / `generate-json-schema` on upgrade. Keep `codex exec --json` as a degraded fallback backend. |
| One process per session/workspace; not multi-tenant | Process count | Fine — you're spawning per-node anyway. |
| No permission relay / remote control | No phone approvals for Codex | Route Codex approvals through `wfd` → your own UI. |

**The unified `AgentBackend` interface** that covers both:

```
start(node_id, cwd, prompt, tools, hooks) -> session_id
send(session_id, message)          # CC: channel notify | stream-json stdin
                                   # Codex: turn/steer (busy) | turn/start (idle)
interrupt(session_id)              # CC: SDK interrupt() | Codex: turn/interrupt
fork(session_id) -> new_id         # CC: --fork-session | Codex: thread/fork
approve(request_id, allow: bool)   # CC: can_use_tool / channel permission relay
                                   # Codex: execCommandApproval response
kill(session_id)                   # SIGTERM; both run SessionEnd hooks
events(session_id) -> Iterator     # CC: stream-json | Codex: app-server notifications
```

Six verbs. Everything else is `wfd`'s job.

---

# PART 3 — Interoperability protocols (detail)

## 3.1 MCP, as of 2026-07-28

The **2026-07-28 spec is a significant break** and you should design to it:

* **Stateless core.** The `initialize`/`initialized` handshake and `Mcp-Session-Id`
  header are gone. Every request self-describes via `_meta`:
  `io.modelcontextprotocol/protocolVersion`, `.../clientInfo`, `.../clientCapabilities`.
  Optional `server/discover` returns `{supportedVersions, capabilities, ttlMs, cacheScope}`.
* **Multi Round-Trip Requests (MRTR, SEP-2322)** replaces server→client requests. A tool
  needing input returns `resultType: "input_required"` with the requests it needs; the
  client retries with `inputResponses`. **Elicitation now rides on MRTR**, not a held-open
  bidirectional stream.
* **Deprecated with a 12-month sunset: sampling, roots, logging.** Also the legacy
  HTTP+SSE transport. New code should call LLM APIs directly and log to stderr / OTel.
* **Notifications are opt-in subscriptions**: client opens `subscriptions/listen` with a
  `notifications` filter; server acks with
  `notifications/subscriptions/acknowledged` and tags every subsequent notification with
  `io.modelcontextprotocol/subscriptionId` in `_meta`. Explicitly **best-effort** — "no
  guarantees that every notification will be sent or received, particularly across
  transport reconnects. Clients should also rely on polling."
* **Tasks extension** (`io.modelcontextprotocol/tasks`): durable handle for long-running
  requests, `tasks/get` polling and `tasks/update`. States: working, input_required,
  completed, failed, cancelled.
* **Cacheable lists**: `tools/list`, `prompts/list`, `resources/list`, `resources/read`
  return `ttlMs` + `cacheScope`.
* Header-based routing: `Mcp-Method`, `Mcp-Name`.
* Auth: RFC 9207 issuer validation required; DCR deprecated in favour of CIMD.
* Tier-1 SDKs (TS, Python, Go, C#) support it now; Rust in beta.

**Design consequences for you:** (1) don't build on sampling; (2) treat notification
delivery as unreliable and back it with a `wf__inbox_wait` poll — the spec literally
tells you to; (3) the Tasks extension state machine is a decent model for long
background jobs, and its state names line up with A2A's.

**Claude Code's channel notifications (`notifications/claude/channel`) are a
Claude-Code-specific extension, not MCP core.** They sit under
`capabilities.experimental['claude/channel']`. Codex does not implement them.

## 3.2 Zed's Agent Client Protocol (the near-miss)

JSON-RPC 2.0, camelCase keys, snake_case discriminators, absolute paths, 1-based lines.
Custom extensions go in `_meta`; custom methods are `_`-prefixed.

Agent methods: `initialize`, `authenticate`, `session/new`, `session/prompt`,
`session/load` (cap `loadSession`), `session/set_mode`, `logout`; notification
`session/cancel`.
Client methods: `session/request_permission` (baseline), `fs/read_text_file`,
`fs/write_text_file`, `terminal/create|output|release|wait_for_exit|kill`,
`elicitation/create`; notifications `session/update`, `elicitation/complete`.

`SessionUpdate` variants: `content_chunk`, `tool_call`, `tool_call_update`, `plan`,
`available_commands`, `config_option_update`, `current_mode_update`.
`ToolCall`: `toolCallId`, `kind`, `title`, `content`, `locations`.
`ToolCallUpdate`: `toolCallId`, `status`, `rawInput`, `rawOutput`.
`StopReason`: `end_turn | max_tokens | max_turn_requests | refusal | cancelled`.
ContentBlock: `text | image | audio | resource_link | resource`.

Adapters: `@zed-industries/claude-code-acp` (Apache-2.0, wraps the Claude Agent SDK) and
`zed-industries/codex-acp` (wraps Codex CLI). Both first-party to Zed.

**Verdict again: steal the vocabulary, skip the runtime.** ACP's job is to feed an
*editor* a live view. Your controller wants the opposite: as little as possible. Going
through ACP would (a) add a process, (b) normalize away `thread/fork`, channel push, and
`turn/steer`, (c) hand you a transcript to parse. The one scenario where you'd adopt it:
if you want third-party agents (Gemini CLI, opencode, Amp) as backends cheaply — several
ship ACP adapters. Keep `AgentBackend` narrow enough that an `ACPBackend` is a later
option.

## 3.3 A2A

v1.0.0. Bindings: JSON-RPC 2.0, gRPC, HTTP+JSON/REST. Agent Card = signed JSON with
identity, capabilities (`streaming`, `pushNotifications`, `extendedCards`), skills,
security schemes (API key, OAuth2, mTLS), endpoints. Ops: `SendMessage`,
`SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`,
`GetExtendedAgentCard`, and four `TaskPushNotificationConfig` CRUD ops. Task states:
`SUBMITTED, WORKING, COMPLETED, FAILED, CANCELED, REJECTED, INPUT_REQUIRED,
AUTH_REQUIRED`. Update delivery: polling, streaming, or webhook push. Version negotiated
via `A2A-Version` header.

Every design assumption (opaque agents, cross-org, HTTP, OAuth, multi-tenancy, webhooks,
tracing) is wrong for a laptop. **Ignore.** Take the state enum.

## 3.4 The rest, briefly

* **ACP / BeeAI / IBM** — the agent-comms ACP consolidated toward A2A; not a live
  independent choice in 2026. Beware the name collision with Zed's ACP.
* **AGNTCY** — OASF + Agent Directory + SLIM transport. Discovery infrastructure for an
  "Internet of Agents". Irrelevant locally.
* **AG-UI** — event categories: Lifecycle, Text Messages, Tool Calls, State Management,
  Activity, Special, Reasoning. Patterns: Start-Content-End for streams,
  Snapshot-Delta for state (`StateSnapshot` / `StateDelta` using JSON Patch RFC 6902).
  Interrupts: `RunFinished` carries `{type:"interrupt", interrupts:[…]}`. Core events
  stable; meta events draft; Thinking events deprecated for Reasoning events.
  **Steal Snapshot+JSON-Patch for your UI feed.**
* **LangGraph** — `interrupt(payload)` suspends via a raised exception, persists via
  checkpointer, surfaces on `stream.interrupts` / `result["__interrupt__"]`, resumes with
  `Command(resume=value)` on the same `thread_id`. **The node re-runs from the top.**
  Parallel interrupts need a `{interrupt.id: value}` resume map. Don't wrap `interrupt()`
  in try/except. The lesson to carry: your `wf__ask` blocking tool call is *strictly
  better* than `interrupt()` because the agent process genuinely suspends inside the tool
  and nothing re-executes.
* **Actor model** — supervision trees answer your abandon-semantics question. `restart:
  permanent | transient | temporary`, `one_for_one | one_for_all | rest_for_one`.
  Implement `one_for_all` shutdown on parent abandon.

## 3.5 The recurring insight, confirmed

**Almost every "agent-to-agent message" in every major framework is a tool call.**
OpenAI Agents SDK handoffs are tool calls that return an `Agent`. Google ADK's
`transfer_to_agent` is a tool. CrewAI delegation is a tool. Claude Code's `Task`/subagent
is a tool. LangGraph is the exception — it's channel updates in a shared state object,
with `Send` for fan-out — and AutoGen core is the other exception (topic/subscription
runtime, in-proc single-threaded or gRPC-distributed). Codex `mcp-server` exposes itself
as the `codex` and `codex_reply` **tools**.

The one place tool calls are insufficient is **unsolicited inbound while the agent is
busy** — which is exactly why Claude Code invented channels and Codex invented
`turn/steer`. Your architecture should mirror that split: outbound = tools, inbound =
push.

---

# PART 4 — Message passing / mailbox, locally

## 4.1 Recommendation

**SQLite (WAL) + a unix-socket daemon. Nothing else.**

* `~/.wf/state.db` with tables `nodes`, `edges`, `mailbox`, `events`, `status`,
  `workflows`, `steps`. WAL mode gives one writer + many concurrent readers, which is
  exactly your topology (one `wfd` writer; controller, TUI, web UI, CLI all readers).
* `~/.wf/wfd.sock` for RPC (`wf-bus` clients, UI subscriptions).
* `events` is **append-only**. It is the single source of truth; `status` and `nodes`
  are derived projections you can rebuild. This gets you event-sourcing's benefit —
  a human injection and a controller decision are the same kind of record — without a
  framework.

Why not the alternatives:

| Option | Why not |
|---|---|
| NATS / JetStream | Excellent, single binary, but it's a service to install and a second source of truth. Overkill at ≤30 local processes. |
| Redis Streams | Same, plus you'd want persistence config. |
| ZeroMQ | No broker means no queryable state — you'd rebuild SQLite anyway. |
| Named pipes / FIFOs | No fanout, no persistence, blocks on no reader. |
| File-watching (fsevents/watchdog) | The classic trap: partial writes, coalesced events, missed events under load, and NFS/Docker-mount inconsistency. If you must, atomic `write-tmp + rename(2)` only. But you don't must. |
| Plain JSONL append log alone | Fine for `events`, bad for `status` queries and for mailbox claim-and-delete. Use SQLite; keep the JSONL export for debugging. |
| Blackboard / shared markdown scratchpad | Directly violates your principle #5, and the known failure modes are write contention and context pollution: every agent pays tokens for every other agent's writes. The `learnings` tool is precisely the right correction. |

## 4.2 Mailbox semantics

Keep them boring:

* `mailbox(id, to_node, from_node, kind, payload_json, created_at, delivered_at,
  acked_at, seq)`.
* Delivery is at-least-once with an idempotency key; agents may see a duplicate.
* Ordering per (from, to) pair via `seq`. Note Claude Code explicitly batches: "If
  several notifications arrive while Claude is busy, they're delivered together on the
  next turn and Claude handles them as a group." Design payloads to survive coalescing.
* Backpressure: cap per-node undelivered depth; `wf__send` returns an error when full.
  That's better than silently ballooning a peer's context.
* **The controller never reads `mailbox` bodies.** It reads `status` and `events`.

## 4.3 The three edge kinds you actually need

1. **`report` edge (child → parent).** Status only, structured. Cheap.
2. **`unblock` edge (parent → child).** A small directive + payload. Cheap.
3. **`peer` edge (sibling ↔ sibling).** Free-form `wf__send`. Expensive — every message
   is context in the receiver. Rate-limit and size-limit these in `wfd`, and make the
   UI render peer edges differently so the cost is visible.

Human attachment is a fourth, special edge: `human → any node`, always permitted,
always logged (see Part 6).

---

# PART 5 — Structured status reporting

## 5.1 Reliability ranking (most → least reliable, in practice)

1. **Forced tool call + Stop-hook gate.** ~100%. The agent cannot end the turn without
   it. Works identically on Claude Code and Codex. **This is the recommendation.**
2. **Exit code / process death.** Trivially reliable but carries almost no payload.
   Use it as the "failed" fallback: `wfd` marks a node `failed` if the process exits
   without a terminal report. Claude Code: 0 = success, non-zero = failure, 143 =
   SIGTERM. `--max-turns` exceeded exits with an error.
3. **Schema-constrained final output.** Reliable on Claude Code (`--json-schema` →
   `structured_output`, hard error on bad schema since v2.1.205). Unreliable on Codex
   (gpt-5-only, incompatible with `exec resume`, reportedly ignored with MCP active —
   openai/codex#15451). Only usable for one-shot agents, since it's per-invocation.
4. **Sentinel files.** Works but violates principle #5, and you get partial-write and
   staleness bugs. Only as a last-ditch crash breadcrumb.
5. **Parsing prose / a fenced JSON block from the final message.** Don't. This is what
   everyone does first and what everyone reports breaking: the model wraps JSON in prose,
   emits ```` ```json ```` fences inconsistently, truncates on token limits, or just
   forgets when the conversation is long.

## 5.2 Known failure modes and the mitigations

| Failure | Mitigation |
|---|---|
| Agent forgets to call `wf__report` | Stop-hook gate blocks the stop with `reason` naming the tool. |
| Agent calls `wf__report` then keeps working | Report is idempotent per turn; last write wins; `events` keeps all of them. |
| Agent reports `done` but the work isn't done | Controller does a *cheap deterministic check* (git status, CI, `gh pr view --json`) before acting. This is your PR-merge example, and it's why the controller needs a tool belt, not a bigger context. |
| Agent wedges (no tool calls for N minutes) | `PostToolUse` hook heartbeats into `events`; `wfd` watchdog flips to `stalled`. Also `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`, `CLAUDE_ENABLE_STREAM_WATCHDOG`, `CLAUDE_STREAM_IDLE_TIMEOUT_MS`. |
| Codex `--output-schema` silently ignored with MCP servers active | Don't use it. Tool call only. |
| Claude Code `format` keyword not enforced | Validate server-side in `wf__report`'s handler; reject and return an error the model can act on. |
| MCP tool result > 25k tokens spills to a file | Keep `wf__report` payloads small by construction; enforce a size cap in the tool schema. |
| Compaction loses the instruction to report | Doesn't matter — the hook re-asserts it at Stop time, and `PreCompact`/`PostCompact` hooks can re-inject `additionalContext`. **This is the whole argument for hooks over skills.** |

## 5.3 The status enum

Use A2A's, trimmed:

```
running        # working, nothing needed
blocked        # needs something: {blocked_on: {kind, ref, question?}}
needs_review   # produced an artifact awaiting human/agent review
done           # terminal success, {artifacts: [...]}
failed         # terminal failure, {error, retriable: bool}
stalled        # derived by wfd, never self-reported
```

Payload budget: hard-cap at ~2KB. If an agent wants to say more, it writes an artifact
and reports the artifact ref. The controller reads refs, not contents.

---

# PART 6 — Human-in-the-loop without corrupting the controller

## 6.1 The mechanism (per backend)

**Claude Code, idle or busy:**
* Best: `wf-bus` emits `notifications/claude/channel` with
  `{content: "<the human's message>", meta: {from: "human", node: "A3", turn: "…"}}`.
  It arrives in-context as `<channel source="wf-bus" from="human" node="A3">…</channel>`.
  Queues if busy; delivered on the next turn.
* Also: an SDK client can push a user message onto the streaming input at any time;
  `--max-turns` docs confirm "a message sent while Claude is working stays queued and
  runs as its own turn". `--replay-user-messages` echoes them back for ack.
* Hard interrupt: `client.interrupt()` (SDK), or `session/cancel` semantics.

**Codex:** `turn/steer` appends to the in-flight turn (that's the designed use);
`turn/start` if idle; `turn/interrupt` to abort.

**Do not** attach a second process to a live session. `--resume` on a session that's
currently running is not a supported concurrency model, and Remote Control explicitly
notes "one remote session per interactive process". Route *everything* through `wfd`.

## 6.2 Keeping the controller's world model consistent — the actual answer

The failure you're worried about is: controller believes node A3 is `running` on task X;
human tells A3 to do Y instead; controller later acts on a stale belief.

Four rules fix it:

1. **All human input flows through `wfd`.** There is no side channel. The UI, the TUI,
   the CLI (`wf say A3 "..."`) all hit the same socket. This is only possible because
   `wfd` owns the process handles — which is the strongest argument for `wfd` spawning
   agents rather than you attaching to ones you started by hand.
2. **Human injection is an event, and it invalidates status.** On
   `human_message{node}`, `wfd` atomically sets `nodes.status = 'running'` and
   `nodes.status_stale = true`, and appends to `events`. The controller's scheduler
   treats `status_stale` as "I know nothing about this node" and simply waits for a fresh
   `wf__report`. It doesn't need to understand *what* the human said — it just knows its
   belief expired. **This is the whole trick: the controller doesn't need to read the
   message, only to know a message happened.** Cost: zero tokens.
3. **The Stop gate closes the loop.** After the human's turn, the agent can't finish
   without reporting. So `status_stale` is guaranteed to clear with a fresh, structured
   status within one turn.
4. **The event log is the shared truth.** Append-only `events` with
   `(seq, ts, node, actor ∈ {human, controller, agent, system}, kind, payload)`.
   Every view (graph, board, timeline) is a projection. When something goes wrong you
   replay, you don't guess. Serve it to UIs as a state snapshot + JSON Patch deltas
   (AG-UI's pattern).

Optional fifth: **optimistic concurrency on directives.** When the controller sends an
`unblock`, it stamps `expects_status_seq = N`. If the node's status has advanced past N
when the message is delivered, `wfd` rejects the directive and re-queues the controller's
decision. Cheap insurance against exactly the race in your PR example.

## 6.3 Notification / approval channels (for the human, not the controller)

* Claude Code `Notification` hook, matchers: `permission_prompt`, `idle_prompt`,
  `auth_success`, `elicitation_dialog`, `elicitation_complete`, `elicitation_response`,
  `agent_needs_input`, `agent_completed`. Feed these straight into `events` — you get a
  populated inbox/status board with no prompt engineering at all.
* `PermissionRequest` hook (`permissionDecision: allow|deny|ask|defer`) and
  `PermissionDenied` (`retry: true`) give the controller a policy hook on every tool call.
* Channel permission relay (§1.4) means `wfd` can render approvals in your web UI and
  answer them, for Claude Code, today.
* Claude Code **Remote Control** (`claude remote-control`, `--rc`, `/rc`) already does
  much of your "talk to any node from anywhere": outbound-HTTPS only, no inbound ports,
  `--spawn worktree`, `--capacity N`, transcript synced across devices. It is worth
  understanding as prior art — and as a reason *not* to build phone support yourself.
* Also relevant prior art in the same doc: Dispatch, Slack, Scheduled tasks, and
  `claude agents` / agent-view for background sessions.

---

# PART 7 — Hooks and daemons as the anti-skill mechanism

## 7.1 Why this is the principle-#1 payoff

A skill is prompt text: it costs context every turn, it can be ignored, it degrades
after compaction, and it can't be validated. A hook is a process: it costs zero context,
it *cannot* be ignored, it survives compaction, it returns exit codes you can test, and
it can be unit-tested in CI. **Anywhere you were going to write "always remember to X",
write a hook instead.**

## 7.2 Claude Code hook surface (30 events)

Full list **(verified)**: `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `Elicitation`,
`ElicitationResult`, `FileChanged`, `InstructionsLoaded`, `MessageDisplay`,
`Notification`, `PermissionDenied`, `PermissionRequest`, `PostCompact`, `PostToolBatch`,
`PostToolUse`, `PostToolUseFailure`, `PreCompact`, `PreToolUse`, `SessionEnd`,
`SessionStart`, `Setup`, `Stop`, `StopFailure`, `SubagentStart`, `SubagentStop`,
`TaskCompleted`, `TaskCreated`, `TeammateIdle`, `UserPromptExpansion`,
`UserPromptSubmit`, `WorktreeCreate`, `WorktreeRemove`.

Handler types: `command` (with `args` for exec-form, `async`, `asyncRewake`, `shell`),
`http` (with `allowedHttpHookUrls` / `httpHookAllowedEnvVars` gating), `mcp_tool`
(`server`/`tool`/`input` with `${path}` substitution), `prompt` (fast model), `agent`
(experimental). `if:` gives per-handler permission-rule scoping (`"Bash(git *)"`,
`"Edit(*.ts)"`). Placeholders `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}`,
`${CLAUDE_PLUGIN_DATA}`.

Universal JSON output: `continue`, `stopReason`, `suppressOutput`, `systemMessage`,
`additionalContext`, `terminalSequence`; plus `hookSpecificOutput` with
`permissionDecision`, `permissionDecisionReason`, `updatedInput`, `updatedToolOutput`,
`retry`, `action`, `content`, `worktreePath`, `initialUserMessage`, `watchPaths`,
`sessionTitle`, `reloadSkills`. 10,000-char output cap.

Blocking events (exit 2 or `decision:"block"`): `PreToolUse`, `PermissionRequest`,
`UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `SubagentStop`, `TeammateIdle`,
`TaskCreated`, `TaskCompleted`, `ConfigChange`, `PreCompact`, `Elicitation`,
`ElicitationResult`, `PostToolBatch`, `WorktreeCreate`.

## 7.3 Concrete substitutions — skill text → hook + daemon

| You would have written a skill saying… | Do this instead |
|---|---|
| "Always report your status when you finish" | `Stop` hook → `wf-stop-gate` blocks with a reason until `wf__report` is called. **The flagship example.** |
| "Record what you learned at the end" | `Stop` (async) hook → `wf-learn` runs a cheap `type: "prompt"` hook on the fast model to extract labeled learnings and POST them to `wfd`. Zero main-context cost. Kills the `autosave-learnings` skill. |
| "Run the tests / lint after editing a file" | `PostToolUse` matcher `Edit\|Write` → run it; on failure `{"decision":"block","reason": <output>}` so the model sees and fixes it. |
| "Never touch `.env` / never push to main" | `PreToolUse` with `if: "Bash(git push *)"` → `permissionDecision: "deny"`. Also `FileChanged` matcher `.env\|.envrc` for detection. |
| "Load the workflow step's instructions" | `SessionStart` hook returns `additionalContext` (and `initialUserMessage`) fetched from `wfd` for this node's current step. **This is how templates bind per-step behavior without a mega-skill.** |
| "Re-read the plan after compaction" | `PreCompact` / `PostCompact` hooks re-inject `additionalContext`. Skills can't survive compaction; hooks can. |
| "Check the todo list before starting a task" | `UserPromptSubmit` hook → `additionalContext` with the node's open todos from the `todo` plugin. |
| "Tell the orchestrator when a subagent finishes" | `SubagentStart` / `SubagentStop` hooks (matcher = agent type) → `wf-event`, async. Free tree topology. |
| "Wake me if CI goes red" | `wf-bus` channel: CI POSTs to the local port, `wf-bus` emits `notifications/claude/channel`. No polling, no skill. |
| "Pause for human approval before merging" | Template step marked human-owned → `PreToolUse` on `Bash(gh pr merge *)` returns `permissionDecision: "ask"`, `wfd` renders it in the board, channel permission relay answers it. |
| "Set a nice session title" | `SessionStart` → `hookSpecificOutput.sessionTitle`. |
| "Set up the worktree" | `WorktreeCreate` hook returns the path on stdout. |
| "Retry on rate limit" | `StopFailure` matcher `rate_limit|overloaded` → `wfd` schedules a retry. No prompt involved. |

Three Claude-Code-specific tricks worth calling out:

* **`asyncRewake: true`** — a background hook process that, on exit code 2, *wakes
  Claude*. That is a genuine "daemon interrupts the agent" primitive. Use it for
  long-running verification (full test suite) that should re-engage the agent when it
  fails, without blocking the turn.
* **`type: "mcp_tool"` hooks** — a hook that calls an MCP tool directly. Your `wf-bus`
  tools can therefore be invoked by lifecycle events with no shell script at all.
* **`type: "prompt"` hooks** — run a small prompt on the fast model against the hook
  payload. This is how you get "judgment" (summarize, classify, extract) at hook time
  without spending main-context tokens. This is the correct home for most of what people
  currently write as skills.

## 7.4 Codex equivalents

11 events (§2.3) covering the ones that matter: `SessionStart`, `UserPromptSubmit`,
`PreToolUse`, `PermissionRequest`, `PostToolUse`, `Pre/PostCompact`,
`SubagentStart/Stop`, `Stop`, `SessionEnd`. Same stdin/stdout/exit-2 contract, same
`decision: "block"`, same `additionalContext`, same regex matchers.

Missing vs Claude Code: `asyncRewake`, `mcp_tool`/`prompt`/`agent` handler types, HTTP
hooks, `PostToolBatch`, `Notification`, `FileChanged`, `WorktreeCreate/Remove`,
`TaskCreated/Completed`, `StopFailure`, `MessageDisplay`.

**Portable subset for your `wf` hook pack** — write these once, ship both configs:
`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`,
`SubagentStop`, `Stop`, `SessionEnd`, `PreCompact`. That's everything you need for
status enforcement, event logging, step binding, and policy. Use Claude-Code-only hooks
purely for enhancement, never for correctness.

Codex `config.toml` also has a `notify` key (an external program invoked on notable
events) — a coarser, older sibling of hooks; use hooks.

## 7.5 Plugins

* **Tooling plugins → MCP servers.** Universal. Both CLIs load stdio and HTTP servers.
  Claude Code additionally supports in-process SDK servers (`create_sdk_mcp_server`) —
  use that when `wfd` drives Claude via the SDK, and only fall back to a subprocess for
  Codex. Namespacing is `mcp__<server>__<tool>` in Claude Code; grant with
  `allowedTools: ["mcp__wf__*"]`.
* **Skill plugins → package as (skill file + hooks + optional MCP server).** Both
  ecosystems have a plugin container that can carry hooks: Claude Code plugins ship
  `hooks/hooks.json`; Codex supports "plugin-bundled hooks via `hooks/hooks.json` or
  manifest entries". So one plugin format can carry the same three artifacts to both.
* Claude Code also lets skills/agents declare hooks in **frontmatter** (with `once:
  true` for run-once-per-session) — the cleanest way to bind a template step's behavior.
* Per-session loading without global install: `--plugin-dir <path>` / `--plugin-url`,
  `--settings <json>`, `--agents '<json>'`, `--mcp-config <json>` + `--strict-mcp-config`.
  Combined with `--bare`, `wfd` can construct a **fully deterministic agent environment
  per node from data** — no user-global config leakage. This is a big deal for
  reproducibility and it directly serves principle #2.

---

# PART 8 — Open questions from the braindump, answered

| Question | Answer |
|---|---|
| What does an edge physically mean? | A permission row in `wfd` + `wf__send` tool outbound + channel/steer inbound. §0.1. |
| Is the plugin interface MCP? | Yes for tooling. For skills, a plugin bundle carrying `SKILL.md` + `hooks/hooks.json` + an optional MCP server. §7.5. |
| Where does workflow state live? | `~/.wf/state.db`, SQLite WAL, owned by `wfd`, `events` append-only as the source of truth. §4.1. |
| Claude/Codex parity for skills/templates? | Better than feared. Both have SKILL.md-style skills, TOML/frontmatter subagents, project memory files (`CLAUDE.md`/`AGENTS.md`), and a near-identical hooks contract. The real gaps are **inbound push** (channels) and **structured output reliability**. §2.5. |
| Human injection without corrupting the controller | Route all human input through `wfd`; mark status stale; let the Stop gate force a fresh report. Controller never reads the message. §6.2. |
| Abandon semantics for children | OTP supervision tree: `wfd` owns the process tree; abandoning a node SIGTERMs the subtree; both CLIs handle SIGTERM cleanly (CC runs `SessionEnd` hooks, exits 143). §3.4. |
| Is the controller an LLM or a scheduler? | Deterministic scheduler over SQL. Escalate to an LLM only on `blocked` with an unrecognized `blocked_on`, and give that LLM the *state row*, never a transcript. §0.2. |
| Herdr as substrate? | Herdr (v0.8.0 locally) is a **terminal workspace manager** — panes, tabs, worktrees, PTY, remote attach, `agent prompt` / `agent wait`, `api snapshot`, `api schema` (protocol 19). It is a *presentation and process* layer, not a protocol layer. Use it for PTY/worktree/attach if you want a TUI cheaply, but **`wfd` must own the agent processes and the MCP/hook wiring** — driving agents via `send-keys`/`prompt` is terminal scraping by another name and gives up everything in §0.2. Recommended split: `wfd` spawns and controls agents; herdr optionally *displays* them. |

---

# Appendix A — Sources

Claude Code / Agent SDK
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/agent-sdk/python
- https://code.claude.com/docs/en/agent-sdk/mcp
- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/channels
- https://code.claude.com/docs/en/channels-reference
- https://code.claude.com/docs/en/remote-control
- https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins

Codex
- https://learn.chatgpt.com/docs/app-server
- https://learn.chatgpt.com/docs/hooks
- https://gist.github.com/oneryalcin/ee2c27e2d8aa040da8fbe7eebcc2ecea (app-server field guide)
- https://github.com/openai/codex/blob/main/codex-rs/docs/codex_mcp_interface.md
- https://github.com/openai/codex/issues/14343 (`--output-schema` + `exec resume`)
- https://github.com/openai/codex/issues/15451 (`--json`/`--output-schema` ignored with MCP)
- https://openai.com/index/unlocking-the-codex-harness/
- https://codex.danielvaughan.com/2026/04/18/codex-cli-headless-batch-mode-automation/

Protocols
- https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture
- https://blog.modelcontextprotocol.io/posts/2026-07-28/
- https://agentclientprotocol.com/protocol/overview , /protocol/schema
- https://github.com/zed-industries/claude-agent-acp , https://github.com/zed-industries/codex-acp
- https://zed.dev/blog/acp-progress-report
- https://a2a-protocol.org/latest/specification/
- https://docs.ag-ui.com/concepts/events
- https://docs.langchain.com/oss/python/langgraph/interrupts
