# herdr v0.8.0: Can an external process own agent state?

**Verdict: YES, with one narrow exception.** An externally-reported state
(`pane report-agent`) wins over the built-in screen-scraping detector for any
agent/source pair that isn't one of herdr's six "full lifecycle" integrations
(`pi`, `omp`, `mastracode`, `opencode`, `kilo`, `kimi` — all gated to source
`herdr:<name>`). Claude, Codex, Gemini, Cursor, etc. are **not** in that list,
so for those agents (and for any custom source you invent) your reported
state is the sole authority — with one safety-net exception: a live,
freshly-observed "visible blocker" (permission prompt) on screen can force
the state to `Blocked` even if you reported something else. It never forces
you *out* of `Blocked`, and a working-spinner never overrides you.

## 1. Built-in detection path

Manifests live in `src/detect/manifests/*.toml` (bundled) with a mirrored
copy under `website/agent-detection/*.toml` for docs. Example,
`src/detect/manifests/claude.toml:1-162`: each `[[rules]]` block has an `id`,
target `state` (`idle|working|blocked|unknown`), `priority` (higher wins),
a `region` (`osc_title`, `osc_progress`, `prompt_box_body`,
`bottom_non_empty_lines(N)`, `after_last_horizontal_rule`, `whole_recent`),
and matchers (`contains`, `line_regex`, `regex`, `any`/`all`/`not` gates).
Flags: `visible_blocker`, `visible_idle`, `visible_working`,
`skip_state_update`. Example rule that produces `Blocked` off the literal
"do you want to proceed?" permission box (`claude.toml:94-110`):

```toml
[[rules]]
id = "bash_permission_prompt"
state = "blocked"
priority = 850
region = "whole_recent"
visible_blocker = true
contains = ["do you want to proceed?"]
any = [{ contains = ["bash command"] }, ...]
```

Dispatch: `src/detect/mod.rs:254-277` (`detect_agent_with_osc`) resolves
`Agent` from the foreground process (`identify_agent_in_job`,
`src/detect/mod.rs:210-238`) then delegates to `manifest::detect_with_osc`.
Output states: `AgentState::{Idle, Working, Blocked, Unknown}`
(`src/detect/mod.rs:11-20`) plus an `AgentDetection` struct carrying
`visible_blocker`/`visible_idle`/`visible_working` — this is the metadata
that later arbitrates against your reported state.

Important: **the built-in Claude hook never reports state at all.** It only
calls `pane.report_agent_session` for session identity
(`src/integration/assets/claude/herdr-agent-state.sh:83`; confirmed no
`report_agent` call in that file). So for a Claude pane, the *only* competing
state authorities are (a) your report and (b) the screen-regex detector.

## 2. `pane report-agent` code path

CLI parse: `src/cli/pane.rs:1072` (usage string), flags `--source`, `--agent`,
`--state`, `--message`, `--seq`, `--agent-session-id`, `--agent-session-path`.
It builds a `pane.report_agent` JSON-RPC request → server dispatch
`src/app/api.rs:1098` → `handle_pane_report_agent`
(`src/app/api/panes.rs:1201-1228`), which:

1. Normalizes `--agent` to a label (`normalize_reported_agent_label`).
2. Emits `AppEvent::HookStateReported { pane_id, source, agent_label, state,
   message, seq, session_ref }`.
3. **Always returns `{"result":"ok"}`** regardless of whether the report was
   actually applied — rejections (stale seq, conflicting owner, etc.) are
   silent at the API layer (`src/app/api/panes.rs:1201-1228`, no error path).

Event handling: `src/app/actions.rs:2798-2827`. Unless the source/agent pair
is a "session-identity-only" integration (`herdr:hermes`+`hermes`,
`herdr:antigravity_cli`+`agy` — `src/detect/mod.rs:295-300`), it calls
`terminal.set_hook_authority_with_session_ref(...)` →
`set_hook_authority_at` (`src/terminal/state.rs:598-712`).

`set_hook_authority_at` gates (all in `src/terminal/state.rs`):
- `session_identity_only_integration` check (line 608) — blocks state for
  those two reserved pairs.
- `known_agent_label_conflicts_with_detected_agent` (line 630, def at
  1510-1516) — **rejected if `--agent` names a *known* herdr agent that
  differs from the process herdr currently sees running in that pane.**
  Using an agent label herdr's parser doesn't recognize sidesteps this
  entirely (see test `hook_authority_can_override_with_unknown_agent_label`,
  `src/terminal/state.rs:2184-2200`).
- `current_session_owner_conflicts` (line 633, def 1215-1221) — rejected if
  a different `(source, agent_label)` already owns the persisted session and
  you don't supply a session ref that "confirms takeover".
- `accept_hook_report` (line 665, def 1553-1568) — the `--seq` gate (see §4).

If accepted, it stores `self.hook_authority = Some(HookAuthority{source,
agent_label, state, message, reported_at, session_ref})`
(`src/terminal/state.rs:692-699`) — no TTL field exists on `HookAuthority`.

## 3. THE CRUX — `--source` and precedence

A "source" is just an opaque string key you choose (e.g. `herdr:claude` for
the bundled hook, `custom:pi` in tests, or your own `myapp:reporter`). Each
source gets its own monotonic `--seq` counter (`hook_report_sequences:
HashMap<String, u64>`, `src/terminal/state.rs:135`) and its own slot in
`hook_authority` — only the single most-recently-accepted report is "the"
hook authority for the pane; there's no per-source stacking for state (there
is for presentation metadata, see `agent_metadata: HashMap<String,
AgentMetadata>`).

Effective-state formula, `recompute_effective_state`
(`src/terminal/state.rs:2006-2047`):

```rust
let state = if self.visible_blocker_overrides_hook() {
    AgentState::Blocked
} else {
    self.hook_authority
        .filter(|a| self.hook_authority_is_effective(a))
        .map(|a| a.state)
        .unwrap_or(self.fallback_state)   // fallback_state = screen detector
};
```

`hook_authority_is_effective` (`src/terminal/state.rs:1692-1697`): for any
source/agent NOT in the six full-lifecycle-integration whitelist, this is
**always `true`** (`!full_lifecycle_hook_authority(...)` short-circuits).
So your reported state always wins over `fallback_state` — screen detection
keeps running underneath (updates `fallback_state`) but is masked.

The one override, `visible_blocker_overrides_hook`
(`src/terminal/state.rs:1738-1749`):

```rust
fn visible_blocker_overrides_hook(&self) -> bool {
    if self.live_full_lifecycle_hook_authority() { return false; }
    self.fallback_visible_blocker
        && self.fallback_not_older_than_hook()
        && self.hook_authority.as_ref().is_some_and(|a| {
            a.state != AgentState::Blocked
                && parse_agent_label(&a.agent_label) == self.detected_agent
        })
}
```

Translation: if the screen detector sees a **live permission-prompt style
blocker** (`visible_blocker = true` rule, e.g. "do you want to proceed?")
*after* your last report, and you did **not** report `Blocked` yourself, the
effective state is forced to `Blocked`. A working-spinner detection never
does this (spinners aren't `visible_blocker` rules) — so:

> **If I call `report-agent --state blocked` and the TUI later shows a
> spinner, does herdr flip it back to `working`?** No — spinner-only
> detections carry `visible_working`, not `visible_blocker`, and only
> `visible_blocker_overrides_hook` can override your report, and only to
> `Blocked`, never to `Working`/`Idle`.
>
> **If I report `idle`/`working` and a real permission prompt appears on
> screen, does it override me?** Yes, to `Blocked` — this is a deliberate
> safety net (see `src/terminal/state.rs:1738`), not a bug you can configure
> away for a given pane. Report `blocked` yourself proactively when you know
> a prompt is coming and this never triggers (condition requires
> `a.state != Blocked`).

**Stickiness / TTL**: `HookAuthority` has no TTL. It persists until: (a) a
newer report on the *same* source with a higher `--seq` replaces it, (b)
`pane release-agent` from the *same* `(source, agent_label)` clears it
(`release_agent_with_mutation`, `src/terminal/state.rs:1627-1690` — checks
`authority.agent_label == agent_label && authority.source == source` at
line 1633, i.e. **only the setter can release its own authority**), (c)
the underlying agent process exits (`process_exited` branch,
`src/terminal/state.rs:364-539`, clears the authority if its agent matches
the exited process and no newer custom report supersedes it), or (d) the
undocumented `pane.clear_agent_authority` JSON-RPC method
(`handle_pane_clear_agent_authority`, `src/app/api/panes.rs:1432-1447` —
**not exposed as a CLI subcommand**, socket-only).

**Disable built-in detection for a pane?** No such toggle exists. Screen
detection always runs and keeps `fallback_state`/`fallback_visible_blocker`
current; it's just masked by your `hook_authority` except for the blocker
safety net above.

**`release-agent`** (`src/cli/pane.rs:1276`, handler
`src/app/api/panes.rs:1449-1469` → `AppEvent::HookAgentReleased` →
`release_agent_with_mutation`): clears `hook_authority = None`. If the
detector still sees the same agent process running in the pane
(`process_owns_agent`, line 1651-1654), state immediately reverts to
whatever `fallback_state` the detector currently holds — i.e. **authority
reverts to the built-in detector**, confirmed by falling through to
`fallback_state` in the next `recompute_effective_state` call. If the
process is gone, it also resets `detected_agent`/`fallback_state` to
`Unknown` and clears the agent name.

## 4. `--seq` semantics

Per-source monotonic counter, `accept_hook_report`
(`src/terminal/state.rs:1553-1568`):

```rust
fn accept_hook_report(&mut self, source: &str, seq: Option<u64>) -> bool {
    let Some(seq) = seq else { return !self.hook_report_sequences.contains_key(source) };
    if self.hook_report_sequences.get(source).is_some_and(|last| seq <= *last) {
        return false;   // stale/duplicate — silently dropped
    }
    self.hook_report_sequences.insert(source.to_string(), seq);
    true
}
```

- Out-of-order or duplicate `seq` (≤ last seen for that source) is silently
  ignored — no error surfaces through the API (`handle_pane_report_agent`
  always returns `ok`).
- Omitting `--seq` only works reliably as long as you *never* mix it with
  sequenced calls for the same source: once any seq has been recorded for
  that source, subsequent seq-less calls are rejected (map lookup finds the
  key present). **Always pass `--seq` on every call once you start using it
  for a source.**
- `agent wait` is confirmed not turn-scoped: `src/cli/spec.rs:386-388` — "It
  does not track turns: if the agent is already working, that active turn's
  completion may match." `--seq` has no relationship to wait's turn
  semantics; it's purely an idempotency/ordering token for report acceptance.

## 5. `done` state

`crate::api::schema::PaneAgentState` (the `--state` enum accepted by
`report-agent`) has exactly four variants: `Idle | Working | Blocked |
Unknown` (`src/api/schema/common.rs:140-147`). **There is no `Done` variant
here — you cannot set `done` via `report-agent`.** `Done` only exists in the
read-side `AgentStatus` enum (`src/api/schema/common.rs:149-157`, used by
`agent wait`/events), computed by `pane_agent_status`
(`src/app/api_helpers.rs:99-110`):

```rust
(AgentState::Idle, seen=false) => AgentStatus::Done,
(AgentState::Idle, seen=true)  => AgentStatus::Idle,
```

`seen` is a per-pane view flag (`app/state.rs:896`) flipped to `true` when
the pane is focused (see test `api_pane_focus_marks_already_focused_done_pane_seen`,
`src/app/api/panes.rs:3685`). So: report `--state idle`; herdr derives `done`
until a client focuses/views the pane, then it becomes `idle`. This matches
report 01's description exactly. Implication for your adapter: **report
`idle`, not "done"** — there's no such input state.

## 6. Events

`PaneAgentStatusChanged` (wire name `pane_agent_status_changed`) fires from
`emit_pane_state_update` (`src/app/api.rs:576-625`), triggered whenever
`previous_agent_status != agent_status || presentation changed`. This
function is fed by `PaneStateUpdate`, which is produced uniformly by
`recompute_effective_state` regardless of whether the change originated from
`set_hook_authority_at` (your report) or `set_detected_state_with_screen_signals_at`
(screen detector) — **same struct, same emission code, same event schema**.
There is no way to distinguish "externally reported" from "detected" from
the event payload alone (it carries `agent_status`, `agent`, `title`,
`display_agent`, `state_labels`, not a provenance/source field).
`PaneAgentDetected` also fires on agent-label/`agent_released` changes
(`src/app/api.rs:586-597`).

## Rules for our adapter

1. **Never use a `herdr:*`-prefixed source.** Reserve those for herdr's own
   integrations; some are matched by exact `(source, agent_label)` tuples
   for special-case behavior (full-lifecycle whitelist, session-identity-only
   pairs). Use something like `custom:<ourtool>` or `<ourtool>:<agent>`.
2. **Pass `--agent` matching the real running CLI's label** (`claude`,
   `codex`, etc.) whenever herdr can detect the process, to avoid the
   "known agent label conflicts with detected agent" rejection. If you're
   reporting for a pane herdr can't identify a process in, any label works.
3. **Always send `--seq`, monotonically increasing, from call one.** Don't
   mix seq-less and seq'd calls for the same source.
4. **Map "done" to `--state idle`.** There is no `done` input; it's derived
   from idle + unviewed.
5. **Proactively report `blocked` the moment you know a permission prompt is
   coming**, so the built-in visible-blocker safety net has nothing to
   override — it only fires when your last reported state isn't already
   `Blocked`.
6. **Treat `report-agent`'s success response as fire-and-forget, not
   confirmation.** It always returns ok even when the report was dropped
   (stale seq, owner conflict). If you need certainty, follow up with
   `pane read`/`pane info` or watch `pane_agent_status_changed`.
7. **Use `pane release-agent --source <same> --agent <same>` to hand control
   back to the detector** when your process is done narrating state for that
   pane; only the exact source that set the authority can release it.
8. There's no per-pane "disable detection" switch — don't rely on one;
   design around the single visible-blocker exception instead.
