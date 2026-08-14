# herdr — deep dive

Research date: 2026-08-06 · herdr version inspected: **0.8.0** (protocol 19, schema_version 1)
Method: local inspection of the installed binary + live socket experiments on the running session, plus web research.

---

## Verdict

**Build on top of it. Do not fork (yet). Do not avoid.**

- **It is open source and forkable.** `github.com/herdrdev/herdr`, **Apache-2.0**, Rust, 25.1k stars, 1.77k forks, ~1,346 commits, actively pushed *today*. Fork is legally and practically available as an escape hatch.
- **But you almost certainly should not fork**, because herdr already exposes essentially all of its internals through a stable, versioned, schema-documented local socket API — **90 request methods**, a live event stream, a plugin system, and hooks that let an external process *write* agent state and UI metadata back into herdr. Everything an orchestration layer needs is reachable as a client. Forking would fork a fast-moving weekly-release codebase (54 releases in 4.5 months) for no capability gain.
- **The one real risk is velocity and single-vendor concentration**: the project is ~4.5 months old, ~99% of commits are from one person (`ogulcancelik` / Can Celik, Herdr Inc.), it **relicensed from AGPL-3.0 to Apache-2.0 three days ago (0.8.0, 2026-08-03)**, and it just announced YC batch F26 **today**. Monetization direction is stated but unbuilt. Treat the Apache-2.0 0.8.0 tag as your fork-safe floor: vendor a pinned copy of the tarball so a future license change cannot strand you.
- **Critical architectural caveat for us**: herdr's default agent-state detection is **regex screen-scraping of the TUI**, and `agent read` returns **terminal text only — never structured agent output**. If our controller must read STATE not transcripts, we must supply the state ourselves via `pane report-agent` (herdr explicitly supports third-party state authority), and get structured results out-of-band (agent writes a file / JSON; we read the file). Do not build on `agent read` parsing.

**Recommended posture:** API client + a herdr plugin for the UI surface + our own state authority via `pane.report_agent` / `pane.report_metadata`. Pin to protocol 19 and check `ping.protocol` at startup.

---

## 1. What herdr is, and provenance

herdr is a **terminal multiplexer purpose-built for AI coding agents**. Architecture is client/server: a headless server owns PTYs, layout, and session persistence; TUI clients attach over a Unix socket. Think tmux, but with first-class "agent" objects, agent lifecycle states, git-worktree-backed workspaces, and a documented control API.

Object model (four levels):

```
workspace (w1)  ->  tab (w1:t1)  ->  pane (w1:p1)  ->  terminal (term_xxxx)
                                       ^
                                   agent (0 or 1 per pane, named)
```

| Fact | Value |
|---|---|
| Repo | https://github.com/herdrdev/herdr (formerly `ogulcancelik/herdr`, 301-redirects) |
| License | **Apache-2.0** since 0.8.0 (2026-08-03). AGPL-3.0-or-later before that. |
| Language | Rust (confirmed: log lines are `tracing` from `herdr::…`, `src/api/server.rs`, `src/persist/plugin_registry.rs`) |
| Stars / forks / open issues | 25,108 / 1,770 / 136 |
| Created | 2026-03-27 (~4.5 months old) |
| Releases | 54 stable, 0.1.0 → 0.8.0, ~weekly + `preview-*` prereleases |
| Maintainer | Can Celik / **Herdr, Inc.** — 1,103 commits vs. 4 for the next human contributor |
| Funding | **Y Combinator F26**, announced 2026-08-06 |
| Pricing | None. No paid tier, no account, no license key. `/pricing` does not exist. |
| Distribution | `install.sh` prebuilt binaries, `brew install herdr` (32k installs/365d), mise, Nix flake |
| Community | GitHub Discussions only (no Discord/Slack). HN front page 2026-06-29 (166 pts, 110 comments). #1 GitHub Trending 2026-06-30. |
| Contribution | **Gated** — "approved-contributor list… curated by maintainers." Only focused bug fixes welcome unsolicited. |

Docs: https://herdr.dev/docs/socket-api/ , /docs/plugins/ , /docs/marketplace/ , /docs/agent-automation , /docs/cli-reference , /docs/agent-skill/ .
No `llms.txt`. herdr.dev serves an SPA 200 for nonexistent paths — a 200 is not proof a page exists.

**Ecosystem**: ~503 community plugins indexed at herdr.dev/plugins. Notable prior art directly relevant to us:
`persiyanov/herdr-reviewr` (347★, review sidebar over an agent's diff), `smarzban/herdr-file-viewer` (352★), `AltanS/collie` (266★, PWA remote control), `ogulcancelik/herdr-browser` (262★, Chromium in a pane over CDP), `cloudmanic/herdr-plus` (208★, Go plugin toolkit), `devashish2203/herdr-worktrunk` (79★, worktrees), `yigitkonur/awesome-herdr` (112★, best index).
Several projects already use herdr **as a substrate for visible, persistent subagents** — that is precisely the pattern we're proposing, so we are not first, and that's good.

---

## 2. The API surface (this is the important part)

### 2.1 Transport — verified by direct socket experiment

Newline-delimited JSON (JSON Lines) over a Unix domain socket. **Not** JSON-RPC 2.0 — no `jsonrpc` field.

```
socket: ~/.config/herdr/herdr.sock          (also $HERDR_SOCKET_PATH)
named:  ~/.config/herdr/sessions/<name>/herdr.sock
```

Request `{ "id": string, "method": string, "params": object }`
Success `{ "id": string, "result": <ResponseResult, internally tagged by "type"> }`
Error   `{ "id": string, "error": { "code": string, "message": string } }`

Verified handshake:

```
$ printf '{"id":"1","method":"ping","params":{}}\n' | nc -U ~/.config/herdr/herdr.sock
{"id":"1","result":{"type":"pong","version":"0.8.0","protocol":19,
 "capabilities":{"live_handoff":true,"detached_server_daemon":true}}}
```

**Connection semantics (measured, undocumented gotcha):** for plain request/response the server writes the reply and **closes the connection** — a second request on the same socket raises `BrokenPipeError`. Persistent connections exist only for streaming methods (`events.subscribe`) and long-poll methods. Budget one connect per call, or hold a subscription connection.

Also present: `HERDR_CLIENT_SOCKET_PATH` (`herdr-client.sock`) — the attached TUI client's own channel (resize/input/render), not the control API. Don't touch it.

**No authentication.** Anything with filesystem access to the socket has full control, including `pane.send_text` into any pane. Socket is `srw-------`, owner-only.

### 2.2 Schema

`herdr api schema --json` dumps a **251 KB** self-describing JSON Schema (draft 2020-12) bundled in the binary. Five root schemas: `request`, `success_response`, `error_response`, `event`, `subscription_event`. 105 request `$defs`, 67 response `$defs`. **This is generated from the Rust types — it is authoritative and machine-consumable. Codegen our client from it.**

### 2.3 All 90 methods

| Group | Methods |
|---|---|
| server (6) | `ping`, `server.stop`, `server.live_handoff`, `server.reload_config`, `server.agent_manifests`, `server.reload_agent_manifests` |
| session/client (4) | `session.snapshot`, `notification.show`, `client.window_title.set`, `client.window_title.clear` |
| workspace (9) | `create`, `list`, `get`, `focus`, `rename`, `move`, `move_block`, `report_metadata`, `close` |
| worktree (4) | `list`, `create`, `open`, `remove` |
| tab (6) | `create`, `list`, `get`, `focus`, `rename`, `move`, `close` |
| **agent (12)** | `list`, `get`, `read`, `explain`, `send_keys`, `rename`, `focus`, `start`, `prompt`, `wait`, `view.set`, `view.clear` |
| pane (30) | `split`, `swap`, `move`, `zoom`, `layout`, `process_info`, `neighbor`, `edges`, `focus_direction`, `resize`, `list`, `current`, `get`, `focus`, `rename`, `send_text`, `send_keys`, `send_input`, `read`, `wait_for_output`, `graphics.set/clear/info/stream`, `report_agent`, `report_agent_session`, `report_metadata`, `clear_agent_authority`, `release_agent`, `close` |
| layout (3) | `layout.export`, `layout.apply`, `layout.set_split_ratio` |
| events (2) | `events.subscribe`, `events.wait` |
| integration (2) | `install`, `uninstall` |
| **plugin (12)** | `link`, `list`, `unlink`, `enable`, `disable`, `action.list`, `action.invoke`, `log.list`, `pane.open`, `pane.focus`, `pane.close` |
| misc | `popup.close` |

### 2.4 Event stream — verified working

```python
sendall('{"id":"s1","method":"events.subscribe","params":{"subscriptions":[
  {"type":"pane.agent_status_changed","pane_id":"w1:p2"},
  {"type":"pane.focused"},{"type":"layout.updated"}]}}\n')
```
returns

```json
{"id":"s1","result":{"type":"subscription_started"}}
{"data":{"pane_id":"w1:p1","type":"pane_focused","workspace_id":"w1"},"event":"pane_focused"}
{"data":{"tab_id":"w1:t2","type":"tab_focused","workspace_id":"w1"},"event":"tab_focused"}
{"data":{"layout":{…full layout tree…},"type":"layout_updated"},"event":"layout_updated"}
```

Subscribable events (28): `workspace.created/updated/metadata_updated/renamed/moved/reordered/closed/focused`, `worktree.created/opened/removed`, `tab.created/closed/focused/renamed/moved`, `pane.created/closed/updated/focused/moved/exited/agent_detected/scroll_changed`, **`pane.agent_status_changed`**, **`pane.output_matched`** (server-side substring/regex watch with `source`/`lines`/`strip_ansi`), `layout.updated`.

`events.wait` is the one-shot variant with an `EventMatch` filter and `timeout_ms`, including `pane_output_changed` with `min_revision` — useful for revision-gated polling.

**This event stream is the correct backbone for our controller.** Do not poll `session.snapshot`.

### 2.5 Snapshot shape

`herdr api snapshot` returns one `SessionSnapshot`: `{version, protocol, workspaces[], tabs[], panes[], layouts[], agents[], focused_workspace_id, focused_tab_id, focused_pane_id}`.

`AgentInfo` (22 fields) is the object we care about:

```
terminal_id, pane_id, tab_id, workspace_id, focused, revision   (required)
agent            — canonical kind, e.g. "claude"
name             — our assigned handle, [a-z][a-z0-9_-]{0,31}, unique among live agents
agent_status     — idle | working | blocked | done | unknown
state_change_seq — monotonic counter, THE thing to compare for "did it move"
interactive_ready, launch_pending, screen_detection_skipped
cwd, foreground_cwd
title, terminal_title, terminal_title_stripped, display_agent
state_labels     — map<status, string>   (we can write these)
tokens           — map<name, string>, ≤32 entries, /^[A-Za-z0-9_-]{1,32}$/  (we can write these)
agent_session    — {source, agent, kind: id|path, value}  — native session id for resume
```

`WorkspaceInfo` additionally carries `worktree: {repo_key, repo_name, repo_root, checkout_path, is_linked_worktree}` and a rolled-up `agent_status`.

---

## 3. Q2 — Can `agent prompt` + `agent wait` drive an agent to completion?

**Mostly yes, with two important limits.**

### The state machine

`AgentStatus = idle | working | blocked | done | unknown`

Semantics, per the bundled skill file (`herdr --skill`):

> `idle` means the agent is ready for input **and its tab has been seen in the focused Herdr UI**. `done` is the same underlying idle state after **unseen** background work finishes. Focusing the tab or targeting the pane or agent with a focus command marks it seen. CLI reads do not mark it seen. `blocked` means Herdr recognized an approval or question UI. `unknown` means an agent is present but Herdr cannot classify it confidently; **it does not prove completion.**

So the real state lattice is **3 states + a seen bit**: `working`, `blocked`, `ready(seen=true → idle | seen=false → done)`, plus `unknown` as an explicit "I don't know."

**Granularity verdict: sufficient for a step machine** — `working` / `blocked` / `done` is exactly the ternary a controller needs (running / needs-human / finished). `done` vs `idle` is genuinely useful: `done` = "finished and nobody has looked at it," which is a free unread flag for a dashboard.

Extra signals beyond the enum: `state_change_seq` (monotonic — use it to detect *any* transition, including working→working restarts), `interactive_ready`, `launch_pending`, and `revision` (pane output revision).

### `agent wait`

```
herdr agent wait <target> [--until idle|working|blocked|done|unknown]... [--timeout MS]
```
Default match set is `idle, done, blocked`. Returns immediately if the current status already matches. Without `--timeout`, waits indefinitely. Repeat `--until` for a set.

### `agent prompt`

```
herdr agent prompt <target> <text> [--wait] [--until STATUS]... [--timeout MS]
```
Submits text + encoded Enter **atomically**, honoring the pane's live bracketed-paste mode, and works even while the agent is working. 0.8.0 added a deliberate short delay between text and Enter so prompts don't get stranded in a composer.

Stall guard, quoted from `src/cli/spec.rs` in the repo:

> "When submission starts from a non-working state, `--wait` first requires an observed state change within 5000ms; otherwise it returns `agent_prompt_stalled`. A shorter `--timeout` returns `timeout` instead. It then matches idle, done, or blocked by default… **It does not track turns: if the agent is already working, that active turn's completion may match.** Without `--timeout`, the settled-state wait is indefinite."

### The two limits

1. **`wait` is not turn-scoped.** It tracks lifecycle state, not "the turn I just started." If you prompt an already-working agent, `--wait` can be satisfied by the *previous* turn finishing. **Mitigation:** always read `state_change_seq` before prompting and require the post-wait `state_change_seq` to exceed it; and prefer to prompt only from a settled state.
2. **Detection is screen-scraping by default** (see §4). `unknown` is common and explicitly non-authoritative. A controller that treats `unknown` as "done" will corrupt itself.

### The fix: become the state authority

herdr has a **first-class third-party state-reporting path** and it works from outside:

```
herdr pane report-agent <pane_id> --source ID --agent LABEL \
  --state idle|working|blocked|unknown [--message TEXT] [--seq N] \
  [--agent-session-id ID] [--agent-session-path PATH]
herdr pane release-agent <pane_id> --source ID --agent LABEL [--seq N]
```

Verified live — I registered a synthetic agent from a shell pane with no real agent in it:

```
$ herdr pane report-agent w1:p5 --source myctl --agent testbot --state working --message "step 3/7" --seq 1
$ herdr agent list
{"agents":[ …,
 {"agent":"testbot","agent_status":"working","cwd":"~/Code/agent-workflows",
  "pane_id":"w1:p5","state_change_seq":26,"tab_id":"w1:t2","workspace_id":"w1"}]}
```

Note `PaneAgentState` for *reporting* is `idle | working | blocked | unknown` — **`done` is derived by herdr**, not reportable. Reported state takes lifecycle authority over screen detection (`pane.clear_agent_authority` releases it).

This is the single most important finding for our design: **our controller can be the source of truth for agent state and herdr will render it, sort by it, notify on it, and stream it back over `pane.agent_status_changed`.**

### Built-in integrations do exactly this

`herdr integration install <target>` writes a hook script that calls `pane report-agent` from inside the agent CLI. 16 targets: claude, codex, cursor, copilot, devin, droid, kimi, opencode, kilo, hermes, qodercli, mastracode, antigravity-cli, grok, pi, omp. For Claude Code it installs `~/.claude/hooks/herdr-agent-state.sh` and wires `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SessionEnd` (hook names confirmed in the binary's strings).

**Install the integrations. They convert screen-scraping into event-driven ground truth,** and they also report `agent_session_id`, which enables `session.resume_agents_on_restore` (agents resume their native conversation after a server restart).

Current machine: all 16 report `not installed`.

---

## 4. Q3 — How `agent read` works. **Raw terminal only.**

```
herdr agent read <target> --source visible|recent|recent-unwrapped|detection [--lines N] [--format text|ansi]
herdr pane  read <pane_id> --source … [--raw]
```

Returns `PaneReadResult { pane_id, workspace_id, tab_id, source, format, text, revision, truncated }`.

`text` is **a terminal screen scrape**. There is no structured agent output, no message objects, no tool-call records, no JSON transcript. Sources:

- `visible` — current viewport
- `recent` — recent rendered output including soft wraps
- `recent_unwrapped` — soft wraps joined (best for logs/transcripts)
- `detection` — the plain-text bottom-buffer snapshot herdr itself uses for state detection

**Hard limitation, stated in the skill file:** agents running on the terminal's **alternate screen** (Claude Code, codex, pi all do) lose rows permanently — they never enter herdr's host scrollback, so raising `--lines` cannot recover them. herdr's own recommended workaround is to ask the agent to write its answer to a Markdown file and reply with the path.

`truncated: true` now flags omitted rows (0.8.0).

### How state detection actually works

`server.agent_manifests` shows per-agent TOML rule packs, auto-fetched from `https://herdr.dev/agent-detection/index.toml` into `~/.local/state/herdr/agent-detection/remote/`. 20 agents currently active. `~/.local/state/herdr/agent-detection/remote/claude.toml` is a prioritized regex ruleset over screen regions:

```toml
[[rules]]
id = "osc_title_working"   # priority 1100, region = osc_title
state = "working"
regex = ['^[\x{2800}-\x{28FF}] ']    # braille spinner in the OSC title

[[rules]]
id = "bash_permission_prompt"        # priority 850, region = whole_recent
state = "blocked"
contains = ["do you want to proceed?"]
any = [{ contains = ["bash command"] }, { contains = ["ctrl+e to explain"] }, …]

[[rules]]
id = "live_prompt_box"               # priority 950, region = prompt_box_body
state = "idle"
line_regex = ['^\s*❯']
not = [{ contains = ["enter to select"] }, { contains = ["esc to cancel"] }, …]
```

`herdr agent explain <target> --format json -v` shows the full rule evaluation with matched/unmatched evidence — genuinely excellent debugging, and it is what you use when state looks wrong. Live output against this very session:

```
agent: claude
state: working
manifest: remote:…/claude.toml 2026.08.04.1
rule: osc_title_working (region=osc_title priority=1100)
evidence: "⠂ Create private GitHub repository for agent workflows"
✓ osc_title_working  priority=1100 region=osc_title state=working
✗ live_blocked_form  priority=980  region=after_last_horizontal_rule state=blocked
✓ live_prompt_box    priority=950  region=prompt_box_body state=idle
✗ bash_permission_prompt priority=850 …
```

Note `osc_title_working` and `live_prompt_box` both matched — priority decided it. Detection is brittle by construction: it depends on Claude Code's exact TUI chrome. herdr mitigates with remote manifest updates (claude.toml is dated 2026-08-04, two days old), but a Claude Code UI change can silently break state for everyone until a manifest ships.

**Design rule for us: never parse `agent read` output for control decisions.** Use it only for human-facing display and diagnostics. Get structured results from the agent through a side channel (file, JSON output mode, our own hook), and drive control off `pane.agent_status_changed` + our own `report-agent` writes.

---

## 5. Q4 — Plugins. **Yes, a real one, and it's the right hook.**

herdr has a full plugin system. It is *not* an in-process extension API — plugins are **manifests that declare commands herdr runs as subprocesses**. Manifest file: `herdr-plugin.toml`.

Official docs quote: **"There is no separate plugin SDK or restricted command set. The entire Herdr CLI is the plugin API."**

### Manifest surface (from `InstalledPluginInfo` in the schema)

| Field | Meaning |
|---|---|
| `plugin_id`, `name`, `version`, `min_herdr_version` | identity; `plugin_requires_newer_herdr` is enforced |
| `platforms` | `linux \| macos \| windows` |
| `build[]` | `{command[], platforms}` — build steps run at install; herdr aborts if the build mutates `herdr-plugin.toml` |
| `startup[]` | `{command[]}` — one-shot init. **Explicitly not supervised daemons.** |
| `actions[]` | `{id, title, description, command[], contexts[], platforms}` — `contexts` = `global \| workspace \| tab \| pane \| selection`; surfaced in herdr's UI menus and invocable via `plugin.action.invoke` |
| `panes[]` | `{id, title, description, command[], placement, width, height}` — **a UI panel** (see §6) |
| `events[]` | `{on: <event name>, command[]}` — subprocess hooks on herdr events |
| `link_handlers[]` | `{id, title, pattern, action}` — regex over terminal text; clicking a match invokes an action |

### Install / dev loop

```
herdr plugin install <owner/repo[/subdir]> [--ref REF] [-y]   # GitHub
herdr plugin link <path> [--enabled|--disabled]               # local dev
herdr plugin list [--plugin ID] [--json]
herdr plugin enable|disable|unlink <plugin_id>
herdr plugin config-dir <plugin_id>
herdr plugin action list|invoke [--plugin ID] <action_id>
herdr plugin log list [--plugin ID] [--limit N]
herdr plugin pane open --plugin ID --entrypoint ID [--placement …] [--env K=V]… 
herdr plugin pane focus|close <pane_id>
```

Marketplace is zero-friction: add the GitHub topic `herdr-plugin` to a public repo; the index refreshes every 30 min. No review queue.

### Plugin runtime environment (extracted from the binary)

Panes/entrypoints receive: `HERDR_SOCKET_PATH`, `HERDR_ENV=1`, `HERDR_BIN_PATH`, `HERDR_PLUGIN_ID`, `HERDR_PLUGIN_ENTRYPOINT_ID`, `HERDR_PLUGIN_CONTEXT_JSON`, `HERDR_PLUGIN_ROOT`, `HERDR_PLUGIN_CONFIG_DIR`, `HERDR_PLUGIN_STATE_DIR`.
Event hooks additionally receive: `HERDR_PLUGIN_EVENT`, `HERDR_PLUGIN_EVENT_JSON`, `HERDR_WORKSPACE_ID`, `HERDR_TAB_ID`, `HERDR_PANE_ID`.
Action invocations receive `PluginInvocationContext`: `workspace_id/label/cwd`, `tab_id/label`, `focused_pane_id/cwd/agent/status`, `selected_text`, `clicked_url`, `link_handler_id`, `invocation_source`, `correlation_id`, `worktree{…}`.

Observability: `plugin.log.list` returns `PluginCommandLogInfo { log_id, plugin_id, command[], status: running|succeeded|failed, started/finished_unix_ms, exit_code, stdout, stderr, error }` — herdr captures our plugin's stdout/stderr for us.

### `.plugins.lock` — resolved

It is **not** a lockfile in the dependency sense. From `src/persist/plugin_registry.rs`:

```rust
const REGISTRY_LOCK_FILE: &str = ".plugins.lock";
fn registry_path()      -> PathBuf { config_dir().join("plugins.json") }
fn registry_lock_path() -> PathBuf { config_dir().join(REGISTRY_LOCK_FILE) }
```

It's a zero-byte **flock advisory file** guarding atomic read-modify-write of the real registry, `~/.config/herdr/plugins.json` (an array of `InstalledPluginInfo`, written via tmp+rename). Ours is 0 bytes because no plugins are installed. Undocumented on the website.

Current state on this machine: `herdr plugin list` → `No plugins installed.`

---

## 6. Q5 — Can herdr host our UI? **Yes, three independent ways.**

Layout itself is a fixed binary-split tree (`LayoutNode` = `pane | split{direction,ratio,first,second}`) — you cannot install a custom renderer or a non-terminal widget. But:

### (a) Plugin panes — a full TUI panel we own

```json
{"method":"plugin.pane.open","params":{
  "plugin_id":"ours","entrypoint":"dashboard",
  "placement":"overlay|popup|split|tab|zoomed",
  "direction":"right|down","target_pane_id":"w1:p2","workspace_id":"w1",
  "width":"80%","height":40, "cwd":"…","env":{"K":"V"},"focus":false}}
```

Our process just draws to a PTY. Any language, any TUI framework. `popup` accepts cell counts or `"NN%"`. Placement `overlay`/`popup`/`zoomed` give us modal-ish surfaces; `split`/`tab` give docked surfaces. This is how `herdr-file-viewer`, `herdr-reviewr`, and `herdr-browser` work.

### (b) Sidebar injection — structured state, not a scrape

herdr's sidebar rows are **template-configurable and accept custom tokens we publish**:

```toml
[ui.sidebar.agents]
row_gap = 0
rows = [["state_icon", "workspace", "tab"], ["agent"]]
[ui.sidebar.agents.rows_by_agent]
claude = [["state_icon","workspace","tab"], ["terminal_title_stripped"], ["agent"]]

[ui.sidebar.spaces]
rows = [["state_icon", "workspace"], ["branch", "git_status"]]
```

> "Custom values reported through pane metadata use a `$name` token." Tokens can be styled inline: `{ token = "workspace", fg = "#89b4fa", bold = true, dim = false }`.

We publish those tokens with:

```
herdr pane report-metadata <pane_id> --source ID [--agent LABEL] \
  [--title TEXT] [--display-agent TEXT] [--state-label STATUS=TEXT] \
  [--token NAME=VALUE]… [--clear-token NAME]… [--seq N] [--ttl-ms N]
herdr workspace report-metadata <workspace_id> --source ID --token NAME=VALUE… [--ttl-ms N]
```

Verified live:

```
$ herdr pane report-metadata w1:p5 --source myctl --agent testbot \
    --title "step 3/7: refactor" --display-agent "flow:build" \
    --state-label "working=RUNNING STEP 3" --token step=3 --token flow=alpha --seq 2
$ herdr agent get w1:p5
{"agent":"testbot","agent_status":"working","display_agent":"flow:build",
 "state_labels":{"working":"RUNNING STEP 3"},
 "title":"step 3/7: refactor","tokens":{"flow":"alpha","step":"3"}, …}
```

Limits: ≤16 tokens per `report-metadata` call, ≤32 retained, names `^[A-Za-z0-9_-]{1,32}$`, optional `ttl_ms` ≤ 24h (self-expiring — good for liveness), `seq` for ordering/idempotency.

**This is the "controller reads and writes STATE" surface.** Our step machine's state becomes herdr's sidebar content with no scraping in either direction.

### (c) `agent.view.set` — we can replace the agent list

Undocumented in the CLI (socket-only). Verified live:

```json
→ {"id":"v1","method":"agent.view.set","params":{
     "source":"myctl","label":"Flow: alpha",
     "filter":{"op":"eq","field":"status","value":"working"},
     "sort":[{"field":"attention","order":"desc"}]}}
← {"id":"v1","result":{"type":"agent_view","active":true,"source":"myctl","label":"Flow: alpha"}}
```

`AgentViewFilter` is a real boolean algebra: `all`/`any`/`not`/`eq`/`in`/`exists` over fields `status | workspace_id | tab_id | pane_id | agent | seen | state_change_seq` **or `{token: "<our custom token>"}`**. Sort fields: `workspace_order | tab_order | pane_order | attention | status | agent | seen | state_change_seq | {token}`. `agent.view.clear` restores the default.

So we can retitle and re-scope herdr's primary navigation to *our* workflow — e.g. "Flow: release-cut" showing only panes carrying our `flow=release-cut` token, sorted by our `step` token.

### (d) Bonus: raster graphics

`pane.graphics.set/stream/clear/info` accept `png|rgb|rgba` base64 with cell-grid placement (Kitty graphics protocol). Gated behind `experimental.kitty_graphics = false` and requires a Kitty-graphics-capable outer terminal. Charts in a pane are technically possible; treat as experimental.

### Other UI affordances
`notification.show {title, body, sound, position}` (toast → in-app / outer terminal / OS), `client.window_title.set/clear`, `layout.export` / `layout.apply` (declarative layout trees with per-pane `command`, `cwd`, `env`, `label` — **we can materialize an entire workflow layout in one call**).

---

## 7. Q6 — Git worktrees. **Good enough for parallel agents on one repo.**

Worktrees are first-class: a *worktree workspace* is a workspace whose cwd is a linked git worktree. Workspaces carry `worktree: {repo_key, repo_name, repo_root, checkout_path, is_linked_worktree}`, and worktree siblings are grouped and kept packed together in the sidebar (0.8.0 added atomic worktree-group reordering via `workspace.move_block`).

```
herdr worktree create [--workspace ID] [--cwd PATH] [--branch NAME] [--base REF]
                      [--path PATH] [--label TEXT] [--focus|--no-focus]
herdr worktree open   [--workspace ID] [--cwd PATH] [--path PATH] [--branch NAME] [--label TEXT] [--focus|--no-focus]
herdr worktree list   [--workspace ID] [--cwd PATH]
herdr worktree remove --workspace ID [--force]
```

`create` = create branch off `--base` + create the checkout + open a workspace on it, one call, `--no-focus` safe. Verified against this repo:

```json
{"type":"worktree_list",
 "source":{"repo_key":"…/agent-workflows/.git","repo_name":"agent-workflows",
           "repo_root":"~/Code/agent-workflows",
           "source_checkout_path":"~/Code/agent-workflows"},
 "worktrees":[{"path":"…/agent-workflows","branch":"main","is_bare":false,
               "is_detached":false,"is_prunable":false,"is_linked_worktree":false,
               "label":"agent-workflows"}]}
```

`WorktreeInfo` also reports `is_prunable` and `open_workspace_id`, so we can reconcile "worktrees on disk" vs "worktrees herdr has open."
Events `worktree.created / opened / removed` are subscribable.

**Sufficient for N parallel agents on one repo:** one worktree workspace per work item, agents isolated by checkout, sidebar groups them, `workspace.report_metadata` tokens can carry per-branch status (`$git_status`, `$jj_status` are the documented pattern).

**What it does NOT do:** no merge/rebase/conflict handling, no branch lifecycle policy, no PR integration, no cleanup-on-completion, no locking against two agents in one worktree, no `.env`/node_modules seeding into the new checkout. All of that is our layer's job. `devashish2203/herdr-worktrunk` (79★) is prior art worth reading.

---

## 8. Q7 — Sharp edges that will bite an orchestration layer

Ordered by how much they'd hurt us.

1. **State detection is regex over the TUI.** The default path is fragile against agent-CLI UI changes and produces `unknown` — which is explicitly *not* "done." *Mitigation: install the integrations (hook-based ground truth), and/or take state authority ourselves with `pane report-agent`. Use `agent explain --json` when state looks wrong.*
2. **`agent read` cannot recover alternate-screen scrollback.** Rows that leave the alt screen are gone; `--lines` can't get them. *Mitigation: never rely on reading transcripts. Have agents emit structured output to files.*
3. **`agent wait` is not turn-scoped.** Prompting an already-working agent can be "satisfied" by the previous turn. *Mitigation: gate on `state_change_seq` monotonic increase; prompt only from settled states; always pass an explicit `--timeout`, since the default is indefinite.*
4. **`idle` vs `done` depends on UI focus.** `done` flips to `idle` when a human (or a `focus` API call) looks at the tab. A controller that calls `agent.focus` / `tab.focus` mutates its own observable state. *Mitigation: never focus for measurement; CLI reads deliberately do not mark seen.*
5. **One request per connection.** The socket closes after a non-streaming reply (measured). Naive connection reuse breaks with `BrokenPipeError`.
6. **Pane IDs are not stable across moves.** `pane move` mints a new workspace-qualified pane ID; the old one only resolves for the moved process's inherited context. Closed tab/pane IDs are never reused. *Mitigation: key our state on the agent `name` (which follows the occupant) or `terminal_id`, not `pane_id`.*
7. **Agent names are ephemeral.** `[a-z][a-z0-9_-]{0,31}`, unique among *live* agents only, cleared when the agent exits/is released/replaced. Not a durable identity. *Mitigation: keep our own ID and map it via a token.*
8. **`agent start` will not create layout.** It requires an existing pane already at an interactive shell prompt with no foreground process. We must `pane split` first, then `agent start`, and handle `agent_pane_busy` / `agent_pane_unavailable` / `agent_start_failed`. Default startup timeout 30s (min 3s, max 300s).
9. **No auth on the socket.** Anything on the box with fs access can `pane send_text` into any agent pane. Not a herdr bug, but our layer must not widen it (don't proxy the socket over a network without auth).
10. **Protocol/version churn.** 54 releases in 4.5 months; protocol is at 19; `herdr status` reports `compatible: yes/no`. Clients must check `ping.protocol` and tolerate unknown fields. `herdr update` auto-updates by default. *Mitigation: pin, and gate our layer on a protocol range.*
11. **CLI leaf `--help` is broken in 0.8.0.** `herdr agent read --help` prints top-level help, not the subcommand's. Group-level help works (`herdr agent`). Use `herdr completion zsh` (1,736 lines, complete flag specs) as the real reference. Reported flags are in this doc's appendix.
12. **CLI ergonomics traps.** `herdr` with no args launches/attaches the TUI — never call it for discovery. Mutating nested commands (`workspace create`) execute with defaults when given no args. Server errors are JSON on stderr with exit 1; syntax errors exit 2.
13. **Plugin startup hooks are one-shot, not supervised.** If our controller daemon should survive, we supervise it ourselves (launchd/systemd) or run it as a plugin *pane*, which is a real long-lived process.
14. **Single-maintainer, gated contribution.** ~99% of commits from one person; contributions require being on a curated approved-contributor list. Upstreaming a fix we need is not a reliable plan. Budget for workarounds.
15. **License history.** Apache-2.0 is 3 days old (0.8.0). Anything ≤0.7.5 is AGPL. If we ever vendor or fork, vendor from ≥0.8.0 and archive the tag.

---

## 9. Recommended architecture for a layer on top

1. **Client**: codegen from `herdr api schema --json` (draft 2020-12, generated from Rust types). Envelope `{id, method, params}` NDJSON, one connect per call, plus one held connection for `events.subscribe`.
2. **State in**: subscribe to `pane.agent_status_changed`, `pane.agent_detected`, `pane.exited`, `workspace/worktree.*`. Reconcile against `session.snapshot` on connect and on protocol mismatch.
3. **State out**: our step machine writes `pane.report_agent` (authority) + `pane.report_metadata` tokens (`flow`, `step`, `attempt`, …) with `ttl_ms` for liveness and `seq` for ordering.
4. **UI**: a herdr plugin declaring (a) a `panes[]` entrypoint for our dashboard TUI (`placement = "split"` docked, or `"popup"` modal), (b) `actions[]` with `pane`/`workspace` contexts for "retry step", "approve", "abort", (c) `events[]` hooks. Plus `agent.view.set` to rescope the sidebar to the active flow, and `[ui.sidebar.agents].rows` referencing our `$tokens`.
5. **Topology**: `worktree create` per work item → `pane split` → `agent start --kind … --no-focus`. Or `layout.apply` with a declarative tree to stand up a whole flow in one call.
6. **Driving**: `agent prompt --wait --timeout N`, guarded by a `state_change_seq` delta check. On `blocked`, read `agent read --source detection` **for display only** and route the decision to a human or a policy; act via `agent send-keys`.
7. **Results**: structured output out-of-band (agent writes JSON/MD to a path we own). Never parse the terminal for control flow.
8. **Prerequisite**: `herdr integration install claude` (and the others we use) so state is hook-driven, not scraped.

---

## Appendix A — CLI surface (from `herdr completion zsh`, since leaf `--help` is broken)

```
agent list
agent get      <target>
agent read     <target> --source visible|recent|recent-unwrapped|detection [--lines N] [--format text|ansi] [--ansi]
agent send-keys <target> <key>...
agent prompt   <target> <text> [--wait] [--until idle|working|blocked|done|unknown]... [--timeout MS]
agent rename   <target> [name|--clear]
agent focus    <target>
agent wait     <target> [--until STATUS]... [--timeout MS]
agent attach   <target> [--takeover]
agent start    <name> --kind <pi|claude|codex|gemini|cursor|devin|agy|cline|omp|mastracode|opencode|
                             copilot|kimi|kiro|droid|amp|grok|hermes|kilo|qodercli|maki>
                      --pane <ID> [--timeout MS] [-- <agent args>...]
agent explain  [target] [--file PATH] [--agent LABEL] [--format text|json] [--json] [-v]

pane list [--workspace ID] | current [--pane ID|--current] | get <id> | layout | process-info
pane neighbor|focus|resize --direction left|right|up|down [--pane ID|--current] [--amount FLOAT]
pane zoom [--toggle|--on|--off]
pane read <id> --source … [--lines N] [--format text|ansi] [--raw]
pane split [--pane ID|--current] [--direction right|down] [--ratio F] [--cwd PATH] [--env K=V]... [--focus|--no-focus]
pane swap|move [--tab ID] [--split right|down] [--target-pane ID] [--workspace ID] [--new-tab] [--new-workspace] [--label T]
pane send-text <id> <text> | send-keys <id> <key>... | run <id> <command>...
pane wait-output <id> (--match TEXT | --regex PATTERN) [--source …] [--lines N] [--timeout MS] [--raw]
pane report-agent <id> --source ID --agent LABEL --state idle|working|blocked|unknown
                       [--message TEXT] [--seq N] [--agent-session-id ID] [--agent-session-path PATH]
pane report-agent-session <id> --source ID --agent LABEL [--seq N] [--agent-session-id ID]
                               [--agent-session-path PATH] [--session-start-source SRC]
pane release-agent <id> --source ID --agent LABEL [--seq N]
pane report-metadata <id> --source ID [--agent LABEL] [--applies-to-source ID] [--title T]
                          [--display-agent T] [--state-label STATUS=TEXT] [--token N=V]... [--clear-token N]...
                          [--seq N] [--ttl-ms N] [--clear-title] [--clear-display-agent] [--clear-state-labels]
pane rename|close|graphics…

workspace list|create|get|focus|rename|close ; workspace report-metadata <id> --source ID --token N=V... [--ttl-ms N]
tab list|create|get|focus|rename|close
worktree list|create|open|remove   (flags in §7)
plugin install|uninstall|link|unlink|enable|disable|list|config-dir|action|log|pane   (flags in §5)
integration install|uninstall|status
terminal attach|session|title      (undocumented in top-level help)
server stop|reload-config|agent-manifests|update-agent-manifests|reload-agent-manifests
session list|attach|stop|delete ; config check|reset-keys ; channel show|set ; api snapshot|schema
```

Env injected into every managed pane: `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, `HERDR_WORKSPACE_ID`, `HERDR_TAB_ID`, `HERDR_PANE_ID` (verified).

## Appendix B — files on disk

```
~/.config/herdr/config.toml         user config (13 sections; `herdr --default-config` prints 324 annotated lines)
~/.config/herdr/session.json        persisted workspace/tab/pane/layout tree (version 3)
~/.config/herdr/plugins.json        plugin registry (absent until first plugin)
~/.config/herdr/.plugins.lock       flock guard for plugins.json (0 bytes)
~/.config/herdr/herdr.sock          control API socket   (srw-------)
~/.config/herdr/herdr-client.sock   attached-client channel — not the control API
~/.config/herdr/herdr-server.log    tracing logs, e.g. `INFO herdr::logging: tab focused event="tab.focus" …`
~/.config/herdr/herdr-client.log
~/.local/state/herdr/agent-detection/remote/*.toml   auto-updated detection rule packs (20 agents)
~/.local/state/herdr/agent-detection/status.toml
```

Config sections: `[theme] [terminal] [update] [keys] [ui] [ui.toast] [ui.toast.herdr] [ui.toast.clipboard] [ui.sound] [session] [remote] [experimental] [advanced]`.
Ones that matter to us: `[ui.sidebar.agents]/[ui.sidebar.spaces]` row templates + `$token`s (§6b), `session.resume_agents_on_restore`, `experimental.pane_history` (persist pane screen history across restarts — off by default), `experimental.kitty_graphics`, `advanced.scrollback_limit_bytes = 10000000`.

## Appendix C — error codes observed

`agent_not_found`, `agent_not_ready`, `agent_not_running`, `agent_name_taken`, `agent_name_not_found`, `agent_kind_mismatch`, `agent_pane_not_found`, `agent_pane_busy`, `agent_pane_unavailable`, `agent_start_failed`, `agent_start_input_failed`, `agent_start_transport_failed`, `agent_prompt_failed`, **`agent_prompt_stalled`**, `agent_send_keys_failed`, `agent_explain_unavailable`, `invalid_agent_view`, `invalid_agent_argument`, `worktree_not_found`, `worktree_list_failed`, `worktree_open_failed`, `ambiguous_worktree_branch`, `plugin_not_found`, `plugin_manifest_not_found`, `plugin_manifest_parse_failed`, `plugin_requires_newer_herdr`, `invalid_plugin_{id,name,version,command,platform,source,pane_id,pane_title,pane_size,action_id,action_title,event,link_handler_*}`, `duplicate_plugin_{pane_id,action_id,link_handler_id}`, `plugin_command_limit_reached`, `platform_unsupported`, `server_unavailable`, `server_not_running`, `stream_closed`, `invalid_request`, `internal_error`, `timeout`.

Live example:

```json
{"id":"cli:agent:get","error":{"code":"agent_not_found","message":"agent target testbot not found"}}
```
(`agent get` resolves by *name* or *pane id* — not by the `agent` kind label.)

## Appendix D — live experiment log (all artifacts cleaned up)

```
1. herdr pane split --pane w1:p2 --direction down --cwd …/agent-workflows --no-focus
   → {"result":{"pane":{"pane_id":"w1:p5","terminal_id":"term_6586a2ff3b51f5",…},"type":"pane_info"}}
2. herdr pane run w1:p5 "echo HELLO_HERDR_TEST_MARKER; git status --porcelain | head -3"
3. herdr pane wait-output w1:p5 --match HELLO_HERDR_TEST_MARKER --timeout 8000
   → {"result":{"type":"output_matched","matched_line":"… echo HELLO_HERDR_TEST_MARKER; …",
      "read":{"text":"…\nHELLO_HERDR_TEST_MARKER\n?? braindump.md\n…","truncated":false,"revision":0}}}
   (wait-output searches the existing snapshot immediately — already-present output matches)
4. herdr pane report-agent w1:p5 --source myctl --agent testbot --state working --message "step 3/7" --seq 1
   → synthetic agent appears in `herdr agent list` with agent_status=working, state_change_seq=26
5. herdr pane report-metadata w1:p5 … --title … --display-agent … --state-label … --token step=3 --token flow=alpha
   → reflected in `agent get` as title/display_agent/state_labels/tokens
6. herdr agent rename w1:p5 flowstep  → name="flowstep"; `agent get flowstep` resolves
7. socket: agent.view.set {source:"myctl",label:"Flow: alpha",filter:{op:"eq",field:"status",value:"working"},
                           sort:[{field:"attention",order:"desc"}]}  → {"type":"agent_view","active":true}
8. socket: agent.view.clear {source:"myctl"} → {"active":false}
9. herdr pane release-agent w1:p5 --source myctl --agent testbot --seq 3
10. herdr pane close w1:p5 → {"type":"ok"}   (agent list back to the single real claude agent)
```
