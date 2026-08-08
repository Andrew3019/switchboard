# Herdr adapter reference (M2)

Pinned version: **0.8.0** (tag `v0.8.0`, commit `346411f`). Protocol version: **19**
(`src/protocol/wire.rs::PROTOCOL_VERSION`, matches `schema_version` in `herdr-api-schema.json`).
This is the only doc our M2 adapter should need — it's the sole piece of code that knows herdr
exists.

Sources: `docs/versions/0.8.0/website/src/content/docs/{cli-reference, socket-api,agent-
automation,agents,session-state,integrations}.mdx`, `AGENTS.md`/`CLAUDE.md` (symlink),
`CHANGELOG.md`, `skills/herdr/SKILL.md`, `src/api/schema.rs`+`schema/*.rs`, `src/api/server.rs`,
`src/api/wait.rs`, `herdr-api-schema.json` (protocol 19, 90 methods). `docs/next` vs the
`v0.8.0` tag differs by one unrelated sentence — the 0.8.0 snapshot is current.

## 1. Docs inventory

`docs/` has `docs/next/` (draft), `docs/preview/` (mutable snapshot), `docs/versions/<X.Y.Z>/`
(immutable per-release — **use `0.8.0`**).

All `.../` paths below are under `docs/versions/0.8.0/website/src/content/docs/`.

| File | Copy? | Why |
|---|---|---|
| `.../socket-api.mdx`, `.../cli-reference.mdx` | Yes | Canonical wire format/methods/events/plugin API; full flag reference, exit codes, env vars. |
| `.../agent-automation.mdx` | Yes | "Drive agents from a script" doc; recipes match M2 almost verbatim. |
| `skills/herdr/SKILL.md` (repo root) | Yes, verbatim | Herdr's own agent-authoring skill (`herdr --skill` prints the binary-matched copy); cross-check for our command choices. 195 lines. |
| `.../agents.mdx`, `.../session-state.mdx` | Skim | Status-authority model + idle/done seen-bit (needed for waits); what survives restart/update (feeds §6). Detection precedence itself is out of scope (owned elsewhere). |
| `.../integrations.mdx` §"Integrate your own agent" | Skim | Shows `pane.report_agent` from hooks; relevant only if we report synthetic state. |
| `.../plugins.mdx`, `troubleshooting.mdx`, `herdr.dev/agent-guide.md` (remote) | No | Plugin authoring / terminal-input issues / teaches a *human* to set up Herdr — none relevant to a headless socket driver. |

No separate OpenAPI reference exists beyond the bundled schema (`herdr api schema --json`,
source of `herdr-api-schema.json`) — every payload below was checked against it.

`AGENTS.md`/`CLAUDE.md` (identical) are **not** about driving herdr — they're contributor
instructions for agents working *on* herdr's own codebase (worktree layout, release process,
commit style). Not applicable, don't copy.

## 2. The six calls

CLI commands print JSON to stdout except `pane read`/`agent read` (raw text). Socket payloads
are single-line NDJSON.

### 2.1 spawn

`agent start` requires an **existing idle shell pane** — confirmed in docs and source
(`AgentStartParams` takes `pane_id`, not layout params; *"agent start therefore requires an
existing shell pane and never creates, splits, or moves layout"*).

```bash
created=$(herdr workspace create --cwd /path/to/repo --label myproj --no-focus)
pane_id=$(echo "$created" | jq -r '.result.root_pane.pane_id')
# only if you need a fresh pane instead of the workspace's root pane:
split=$(herdr pane split "$pane_id" --direction right --no-focus)
agent_pane=$(echo "$split" | jq -r '.result.pane.pane_id')
herdr agent start myagent --kind claude --pane "$agent_pane" --timeout 30000 -- --some-flag
```

```json
{"id":"r1","method":"workspace.create","params":{"cwd":"/path/to/repo","label":"myproj","focus":false}}
{"id":"r2","method":"pane.split","params":{"target_pane_id":"w1:p1","direction":"right","focus":false}}
{"id":"r3","method":"agent.start","params":{"name":"myagent","kind":"claude","pane_id":"w1:p2","args":["--some-flag"],"timeout_ms":30000}}
```

`AgentStartParams`: `{name, kind, pane_id, args?, timeout_ms?}`. `name` required,
`[a-z][a-z0-9_-]{0,31}`, unique among live agents. `kind`: `pi, claude, codex, gemini, cursor,
devin, agy, cline, omp, mastracode, opencode, copilot, kimi, kiro, droid, amp, grok, hermes,
kilo, qodercli, maki`. `timeout_ms` must be `>3000` and `<=300000`, default 30000. Returns after
herdr detects the expected agent owns the terminal and is interactive-ready, at `.result.agent`
(an `AgentInfo`, §4). `workspace create`/`tab create`/`pane split` all default `focus: false`.

Errors: `agent_pane_not_found`, `agent_pane_unavailable` (shell not idle), `agent_pane_busy`,
`agent_name_taken`, `unsupported_agent_kind`, `invalid_agent_name`, `invalid_agent_timeout`,
`agent_start_input_failed`, `agent_launch_pending` (start already in flight for that pane —
don't race a second call), `timeout`.

### 2.2 poke

```bash
herdr agent prompt myagent "Fix the failing test" --wait --until idle --until blocked --timeout 120000
```

```json
{"id":"r4","method":"agent.prompt","params":{"target":"myagent","text":"Fix the failing test","wait":{"until":["idle","blocked"],"timeout_ms":120000}}}
```

`AgentPromptParams`: `{target, text, wait?: {until?: AgentStatus[], timeout_ms?}}`. Bundle
`wait` into the same request — avoids the poke→wait race; prefer this over separate `agent
prompt` + `agent wait`.

Queues if busy? **Yes.** `agent prompt` submits text + encoded Enter (honors live bracketed-
paste) and can target an already-working agent — text is not dropped. But herdr **does not track
individual turns**: if the agent was already working, completion of the turn already in flight
may satisfy `--wait`, not necessarily your new prompt's turn. Poking a non-working agent with
`--wait` requires an observed lifecycle change within 5s or returns `agent_prompt_stalled`
(`--timeout <=5000` gets plain `timeout` instead). Without `--wait`, returns immediately, fire-
and-forget.

Size limits: none in schema (`text: string`, unconstrained) beyond the server's 1 MiB request-
line cap (`MAX_INITIAL_REQUEST_BYTES`). Needs idle? **No** — that's the point of `agent prompt`
vs `pane send-text`. Requires the target to be a live recognized agent (`agent_not_running`/
`agent_not_found` otherwise).

### 2.3 wait

```bash
herdr agent wait myagent --until idle --until done --until blocked --timeout 120000
```

```json
{"id":"r5","method":"agent.wait","params":{"target":"myagent","until":["idle","done","blocked"],"timeout_ms":120000}}
```

`AgentWaitParams`: `{target, until?: AgentStatus[], timeout_ms?}`. States: `idle, working,
blocked, done, unknown`.

- `idle` = ready for input **and** its tab has been seen by a focused UI client (`pane
  focus`/`agent focus`/`agent attach` — CLI reads do NOT mark it seen). `done` = same idle
  state, tab not yet seen. **A fully headless driver that never focuses the TUI will only ever
  see `done`, never `idle`, for background work** — keep `done` in `--until`.
- `blocked` = approval/question UI recognized. `unknown` = can't classify confidently — **not**
  a completion signal.

Default `until` (both CLI and socket, when omitted): `[idle, done, blocked]`; add `--until
unknown` explicitly if wanted. `timeout_ms`/`--timeout`: **no default, waits indefinitely if
omitted** — always pass one. `agent.wait` is server-owned/event-driven and *pins the resolved
pane occupant so a replacement can't satisfy the wait*. Exit codes (CLI): timeout/server error →
JSON on stderr, exit 1; bad usage → exit 2. Returns `agent_not_running` promptly (not after full
timeout) if the target pane closes mid-wait. Standalone `agent wait` returns immediately if
status already matches.

### 2.4 worktree

```bash
herdr worktree create --workspace w1 --branch worktree/api --base main --no-focus
```

```json
{"id":"r6","method":"worktree.create","params":{"workspace_id":"w1","branch":"worktree/api","base":"main","path":null,"label":"api-wt","focus":false}}
```

`WorktreeCreateParams`: `{workspace_id?, cwd?, branch?, base?, path?, label?, focus (default
false)}`. Use at most one of `workspace_id`/`cwd`; omit both for active workspace. Raw socket
`cwd`/`path` must be absolute. Returns `.result.{workspace,tab,root_pane,worktree}`. Existing
`--branch` is checked out; otherwise created from `--base` (default `HEAD`). Without `--path`,
lands under `<worktrees.directory>/<repo>/<branch-slug>`. Emits `workspace.created`,
`tab.created`, `pane.created`, `worktree.created`.

**Cleanup** — `worktree remove`, not `workspace close`:

```bash
herdr worktree remove --workspace w2 --force
```

```json
{"id":"r7","method":"worktree.remove","params":{"workspace_id":"w2","force":true}}
```

`WorktreeRemoveParams`: `{workspace_id (required), force (default false)}`. Runs `git worktree
remove`, **never deletes the branch**. `--force` needed for a dirty checkout. `workspace close`
alone leaves the git checkout on disk — full cleanup needs `worktree.remove`.

### 2.5 attach/focus

`agent.focus` (socket, `{target}`; CLI `herdr agent focus myagent`) points the server's focused
workspace/tab/pane at that agent for any attached TUI client, and marks a `done` agent as *seen*
(flips future waits' idle semantics). `herdr agent attach <target> [--takeover]` is CLI-only,
**not a socket method** (no `agent.attach` in the `Method` enum/raw-methods table) — it opens a
raw terminal stream (same mechanism as `herdr terminal attach <terminal_id>`), replacing the
current shell with a live view; detach `ctrl+b q`, `--takeover` steals control from another
attached client. Human/interactive only — **not used by the M2 adapter**.

```bash
herdr agent focus myagent      # jump UI to it, mark done->seen
herdr agent attach myagent     # human only
```

### 2.6 release/cleanup

```bash
herdr pane release-agent w1:p1 --source custom:m2 --agent myagent   # release reporting authority
herdr pane close w1:p1                                              # kill pane + process
```

```json
{"id":"r8","method":"pane.release_agent","params":{"pane_id":"w1:p1","source":"custom:m2","agent":"myagent"}}
{"id":"r9","method":"pane.close","params":{"pane_id":"w1:p1"}}
```

`PaneReleaseAgentParams`: `{pane_id, source, agent, seq?}`. `PaneTarget` (`pane.close`,
`pane.get`): `{pane_id}`.

For "I'm done with this agent," use **`pane.close`** — tears down the terminal/process; the
agent name clears automatically. `pane.release_agent` is only for a custom state-reporting
integration relinquishing *authority* without killing the pane — irrelevant unless our adapter
itself reports state via `pane.report_agent`. Full teardown of a worktree-backed agent:
`pane.close` then `worktree.remove --force`. If a workspace's last tab closes, the workspace
closes too; with `confirm_close` enabled that can return `confirmation_required` instead —
relevant only if we call `tab.close`/`workspace.close` rather than `worktree.remove`.

## 3. Socket protocol mechanics

Transport: NDJSON over Unix domain socket (`~/.config/herdr/herdr.sock`, or
`~/.config/herdr/sessions/<name>/herdr.sock`) / Windows named pipe. Resolution order: `--session
<name>` → `HERDR_SOCKET_PATH` → `HERDR_SESSION=<name>` → default.

**Confirmed: one request per connection.** `src/api/server.rs::handle_connection` reads exactly
one line, dispatches, writes exactly one response, returns — closing the connection; no loop for
additional lines after a non-streaming response. **A second write on the same connection hits a
closed socket** (BrokenPipe/ECONNRESET) — by design. Open a fresh connection per request.
`INITIAL_REQUEST_TIMEOUT`=5s for the first line; `STREAM_WRITE_TIMEOUT`=5s/write;
`MAX_INITIAL_REQUEST_BYTES`=1 MiB.

Exceptions (still one *request* each): `pane.graphics.stream` (n/a to M2), `events.subscribe`
(push stream, below), and the blocking trio
`events.wait`/`agent.prompt(wait)`/`agent.wait`/`pane.wait_for_output` — these block server-
side, then write one final response and close.

`events.subscribe`: send one request with a `subscriptions` array; first response line acks it,
then further lines are pushed `EventEnvelope {event, data}` (no `id` — that's how you tell them
apart from replies). Genuinely persistent; no resume/replay on drop. Pattern: `session.snapshot`
(one-shot full state) → separate `events.subscribe` connection for increments → re-snapshot
after any reconnect.

Subscribe-as (`type`, dot.case) vs received-as (`event`, snake_case) differ:

| Subscribe `type` | Received `event` | Extra request fields |
|---|---|---|
| `pane.created/closed/updated/focused/moved/exited` | `pane_*` | — |
| `pane.agent_detected` | `pane_agent_detected` | — |
| `pane.agent_status_changed` | `pane_agent_status_changed` | `pane_id?`, `agent_status?` |
| `pane.output_matched` | delivered as match result | `pane_id`, `source`, `match` (req); `lines?`, `strip_ansi?` |
| `pane.scroll_changed` | subscription-only | `pane_id` |
| `workspace.*` / `worktree.*` / `tab.*` | `workspace_*` / `worktree_*` / `tab_*` | — |
| `layout.updated` | `layout_updated` | — |

Most relevant to M2: `pane.agent_status_changed` (poll-free wait/monitor, filter by `pane_id`);
`pane.created`/`pane.closed`/`pane.exited` (distinguish crash vs. explicit close);
`pane.output_matched` (poll-free `pane wait-output` for non-agent processes).

## 4. Identity plumbing

| Identifier | Format | Stability | Source |
|---|---|---|---|
| `terminal_id` | `term_<opaque>` | **Most stable** — tied to the PTY/process, distinct from `pane_id` (herdr's own tests assert `terminal_id != pane_id`). | `PaneInfo.terminal_id` / `AgentInfo.terminal_id` (required) |
| `pane_id` | `<workspace>:p<n>`, e.g. `w1:p2` | Stable within a workspace; **cross-workspace `pane.move` assigns a new public id** (old one kept as an alias for `--current`, not canonical going forward). Same-workspace tab moves don't change it. | `PaneInfo.pane_id` |
| agent name | `[a-z][a-z0-9_-]{0,31}` | **Follows the terminal across pane moves.** Cleared on exit/release/replacement. Only set via `agent start <name>`/`agent rename`. | `AgentInfo.name` |

`--agent-session-id` (`pane report-agent-session --agent-session-id`,
`pane.report_agent_session.params.agent_session_id`) is a **fourth, orthogonal** value: the
agent CLI's own native/vendor session id (e.g. Claude Code's `--resume <id>`), reported by an
official integration hook for herdr's own resume-after-restart feature. Surfaced read-only as
`agent_session: {source, agent, kind: "id"|"path", value}`; no fixed relationship to
pane/terminal/name identity, may be null. Don't use it as our tracking handle.

**Recommended DB reference**: store `terminal_id` as primary handle plus current `pane_id` as a
cache (nothing addresses by `terminal_id` directly — commands take `pane_id`/`target`). Assign
our own agent **name** at spawn (`agent start <name>`) and address by name in steady state —
universally accepted as `target` and resilient to pane moves. Reconcile `pane_id` from
responses/`pane.moved` events, don't cache it long-term; ignore `agent_session_id` except for
optional display mirroring.

## 5. Stability signals (0.8.0)

Protocol version 19, bumped on breaking wire changes; mismatched client/server gets a loud
`protocol_mismatch` error, not silent breakage.

- **0.8.0**: adds `workspace.move_block`/`workspace.reordered` (unused by M2). No changes to
  `agent.start`/`agent.prompt`/`agent.wait`/`worktree.*`.
- **Pre-0.7 (still recent)**: the entire `agent.start`/atomic
  `agent.prompt`/`agent.send_keys`/`agent.wait` facade was a breaking rework replacing older
  top-level `wait`/`agent send`. Our six calls are from the *current* generation, not legacy
  holdovers — lower churn risk than a raw CHANGELOG skim suggests. `agent_prompt_stalled` was
  added after that base rework — confirm it still exists on any version bump. Worktree
  socket/CLI surface stable since protocol 10, only additive since (provenance, reorder events).
  `session.snapshot`/`herdr api schema` (source of our schema file) are comparatively new — re-
  run `herdr api schema --output ...` after any `herdr update` rather than trusting a stale
  schema file.

**Marked experimental/unstable**, avoid depending on: `[experimental]
kitty_graphics`/`pane.graphics.*` and `[experimental] pane_history` (both unused by M2,
off/gated by default); plugin API ("an early host surface... v1," unused by M2 — direct socket
client instead); and **live handoff** (`herdr update --handoff`, `server.live_handoff`) — docs
say it does not preserve in-flight requests/waits/subscriptions across the swap, *"clients
should reconnect and retry"*, so reconnect+resubscribe defensively regardless of whether handoff
is used.

**Likely to break under us with no version bump at all**: manifest-driven screen detection
(`idle`/`working`/`blocked` for agents without full lifecycle hooks) auto-updates from herdr.dev
by default (`[update] manifest_check`) — detection *behavior* for a given agent kind can shift
underneath a pinned binary. Pinning the binary alone doesn't freeze behavior; that's the agent-
state-precedence area another agent owns — flag it there.

## 6. Gotchas for an external driver

- **One request per connection, no pipelining** (§3) — never reuse a connection for a second
  request.
- **`agent prompt --wait` on a busy agent can resolve on the wrong turn.** No per-turn tracking.
  To confirm *our* prompt specifically finished, record `AgentInfo.state_change_seq` (monotonic)
  before poking and require it to advance *and* status to settle, rather than trusting `--wait`
  alone.
- **Headless driver sees `done`, not `idle`, and `unknown` is not success.** Reading via
  CLI/socket never marks a pane seen, so always wait on the default trio (`idle, done, blocked`)
  or explicitly include `done` — never wait on `idle` alone headlessly, and never act on
  `unknown` as completion.
- **Alternate-screen full-history reads require idle.** `agent read --lines N` beyond the
  visible screen for full-screen agents (Claude Code, OpenCode) drives synthetic mouse-wheel
  scrolling and **returns `agent_not_idle`** while working/blocked/unknown. Wait for idle/done
  first, or use `--source visible`/`detection` (always passive/safe).
- **Server restart drops running processes** unless native agent-session restore is configured
  for that agent kind — `herdr update` without `--handoff`, `herdr server stop`, or a crash
  kills our agents' actual processes even if herdr reconstructs pane *shape*. Treat "server
  unreachable" as "assume agents died" and re-verify state on reconnect.
- **`worktree.create`/`remove` responses are authoritative** (deferred git work completes before
  the response returns) — no need to poll for completion. `remove` without `--force` refuses a
  dirty checkout; don't auto-retry with `--force` by default, that's a data-loss footgun.
- **Races: pane replaced or moved mid-wait.** `agent.wait` pins the original occupant and won't
  spuriously resolve against a replacement, but treat `agent_not_running` as a distinct outcome
  from `timeout`, not something to blindly retry. Cross-workspace `pane.move` (including
  implicitly via worktree reorganization) changes `pane_id` and ends an in-flight wait with
  `agent_not_running` too — address by agent name (§4) to dodge this, and don't cache `pane_id`
  long-term.
- **Errors are typed, not free-text**: `{"id","error":{"code","message"}}` — match on `code`,
  never parse `message`. Spawn errors are listed in §2.1; also relevant: `agent_not_found`,
  `agent_not_running`, `agent_not_idle`, `agent_target_ambiguous`, `confirmation_required`,
  `server_not_running`, `server_unavailable`, `protocol_mismatch`, `invalid_params`,
  `invalid_request`, `pane_not_found`, `internal_error`.
- **No rate limiting found** on the agent/pane/worktree calls we use (`notification.show` does
  rate-limit — not one of our six); nothing stops a tight `agent.wait`/`agent.get` poll loop
  besides normal socket-accept overhead — prefer `events.subscribe` push over polling anyway.
  CLI stdout is JSON except `pane read`/`agent read`, which print raw text by design
  (`.result.read.text` is the JSON form via socket) — don't `jq` those.
