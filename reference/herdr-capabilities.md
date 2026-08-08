# What herdr can do — capability map

Human-readable inventory. **The point is knowing it exists**, so we don't reinvent it in
six months. Exact flags live in `herdr-adapter-reference.md`; the full contract is
`herdr-api-schema.json` (v0.8.0, protocol 19).

**Everything here is scriptable.** None of it needs an agent. That's the important part:
orchestration setup is a *shell script*, not a reasoning task.

---

## 1. It owns the workspace

Create and arrange terminal real estate programmatically.

- **Workspaces** — create, close, focus, rename, move, reorder, list, get. Attach metadata.
- **Tabs** — same set.
- **Panes** — split, close, focus, move, swap, resize, zoom, rename; navigate by direction
  or neighbour; inspect layout and edges.
- **Layout** — export a layout, apply one, set split ratios.

*Meaning:* "give this run its own workspace, with a pane per agent, laid out how I like"
is a handful of calls, not a feature we build.

## 2. It owns git worktrees

`worktree create --branch --base` · `list` · `open` · `remove`

Stable since protocol 10. Worktree metadata rides along on workspaces, and siblings group
in the sidebar.

*Meaning:* per-run isolation is one call. We never shell out to `git worktree` ourselves.

## 3. It runs the agents

`agent start` · `prompt` · `wait` · `list` · `get` · `read` · `rename` · `explain`

- 16 integrations available — **claude, codex**, cursor, opencode, grok, copilot, devin,
  droid, kimi, kilo, hermes, qodercli, mastracode, antigravity-cli, pi, omp.
- `agent start` drops an agent into an **existing idle pane** — it never creates topology.
- `agent prompt` queues even against a busy agent.
- `agent wait --until <states>` blocks until the agent reaches one.

*Meaning:* no PTY code, no per-CLI quirks, no process supervision. Ever.

## 4. It lets us own agent state

`pane report_agent` · `report_agent_session` · `report_metadata` · `release_agent` ·
`clear_agent_authority`

We push authoritative state in; herdr's regex detector loses to us (proof:
`herdr-state-authority.md`). States: `idle | working | blocked | unknown`.

*Meaning:* our step machine's truth becomes what the UI shows, everywhere, for free.

## 5. It watches things for us

- `events.subscribe` — persistent connection, **26 event types**: agent status changes,
  pane created/closed/exited/focused/moved, output changed, tab and workspace lifecycle,
  worktree created/opened/removed, layout updated.
- `pane wait-output --match TEXT | --regex PATTERN --timeout MS` — **server-side** pattern
  matching on pane output, with a real timeout. (Socket: `pane.wait_for_output` /
  `pane.output_matched`.)
- `pane run <pane_id> <command>` — run a command directly in a pane. Cleaner bootstrap
  path than `send-text`.
- `pane report-metadata --ttl-ms N` — metadata that expires on its own.
- `agent wait` — block until an agent is idle/done/blocked.
- `session snapshot` — the whole live state in one call.
- `pane process_info` — what's actually running in there.

*Meaning:* we are event-driven without writing a watcher, and we never poll (C10).

## 6. It shows things to the human

- `notification.show` — **this is the blocked-leaf shortcut in v0.** A leaf can surface to
  you with no UI of our own.
- `agent view.set` / `view.clear` — **replace herdr's agent list with our own**, filtered
  and sorted by our custom tokens. Comes with a filter DSL: `eq`, `in`, `regex`,
  `substring`, `all`, `any`, `not`, `exists`.
- `pane report_metadata` / `workspace report_metadata` — attach `--token NAME=VALUE` pairs
  and state labels that render in the sidebar.
- `plugin pane.open` — host our own pane inside herdr *(experimental — not for v0)*.
- `client.window_title.set` · `popup.close`.

*Meaning:* a usable status surface exists before we write any UI at all.

## 7. It lets the human reach in

`agent focus` · `agent attach` (CLI-only) · `pane focus` · `send_text` · `send_keys` ·
`send_input`

*Meaning:* C14's human exemption — talk directly to any leaf — is already built. Clicking
a pane and typing *is* the feature.

## 8. It manages itself

`server reload_config` · `reload_agent_manifests` · `agent_manifests` · `stop` ·
`live_handoff` *(experimental)* · `integration install/uninstall` · `plugin`
enable/disable/link/unlink/list/action.invoke *(experimental)* · `ping`

Sessions are named and persistent; reattach from any terminal or over SSH; agents survive
lid-close, network loss, and restarts.

---

## Recipes — all of this is a shell script

### Start a run from a GitHub issue

```
gh issue view $N --json title,body        # ours
herdr worktree create --branch issue-$N --base main
herdr workspace create "issue-$N"
herdr pane split                          # one pane per agent, as needed
herdr agent start claude --pane $P
herdr agent prompt $A "You are the orchestrator for issue $N. Run: wf inbox"
```

**No agent decided any of that.** Scaffolding is deterministic (C8); the model only does
the work inside a step.

### Surface a blocked agent to me

```
herdr pane report-agent $P --source wf --state blocked --message "needs decision" --seq $N
herdr notification show "issue-$N: orchestrator blocked"
```

Leaf → store → human, bypassing the parent (C14).

### Make herdr's sidebar our status board

```
herdr pane report-metadata $P --token step=implement --token run=issue-$N \
                              --state-label blocked="awaiting review"
herdr agent view.set '<filter over our tokens>'
```

### Watch everything, poll nothing

```
herdr events subscribe        # persistent; drives our reconciler
```

### Clean up a finished run

```
herdr pane release-agent $P   # hand state back to the detector
herdr pane close $P
herdr worktree remove <path>
```

---

## What herdr does NOT do — our product

Templates · step machine · run history · gates and the human-gate watcher · the status
contract (what "done" means) · learnings · budget accounting · reconciliation.

Nothing in herdr conflicts with any of it.

## Don't depend on (experimental in 0.8.0)

`server.live_handoff` · the entire `plugin.*` surface.
