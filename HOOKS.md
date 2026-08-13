# ✅ BUILT — the Stop hook exists (2026-08-11)

`switchboard/hooks.py` is the gate, `bin/sb-stop-hook` runs it, and
`herdr.start_agent` passes `--settings <file>` on every spawn and every restore. The scope
pass, the decision table and the live proof are in `audit/phase3.8-scope.md`. Read that and
the code; everything below is design notes from before it was built, and the sections after
the correction are still the unverified research the correction warns about.

**A second hook now rides in the same settings file: `UserPromptSubmit`, run by
`bin/sb-activity-hook`.** The pair is switchboard's own activity signal — `working` when a
turn starts, `idle` when one ends, into `agents.turn` — and it replaces herdr's terminal
screen-scrape as the primary answer to "is this agent mid-turn?". Why the edges rather than
a per-tool-call hook or a timestamp, what each costs, and the live proof are in
`audit/activity-signal.md`; the measurements behind the choice are in
`audit/hook-signal-cost.md` and `audit/status-ground-truth.md`. One rule from that build is
worth repeating here because it is the easiest thing to get wrong: **the Stop hook records
`idle` only when the gate is letting the turn end.** A blocked stop continues the same
turn.

**A second file now rides beside the settings file, and it is not a hook.** Since
2026-08-12 the system prompt is handed to the provider as `--append-system-prompt-file
<path>` rather than as a typed argument (`herdr._prompt_flags`, `audit/prompt-via-file.md`):
`agent start` types the whole command line into the pane's shell, and a shell still running
its startup files keeps only `MAX_CANON` — 1024 — bytes of it. Both files live under the
shared `.git` (`store.store_dir`), for the same reasons; the difference is that an
unwritable settings file costs enforcement and merely returns `[]`, while an unwritable
prompt file costs the agent its whole protocol and so fails the spawn.

Two things the build learned that the notes below get wrong or do not say:

- **The gate is not an `events` query.** It reads the agent's `state` — `done`, `blocked`
  or `failed` means it reported. The pseudocode below invents an events row that does not
  exist.
- **It answers with JSON, not exit 2.** `{"decision": "block", "reason": …}` on stdout with
  exit 0 is what blocks the stop; exit 2 was never tried and is not needed. The re-entry
  turn carries **`stop_hook_active: true`**, and the turn is then allowed to end with 3.5's
  reconciler owning what happens next.
- **`stop_hook_active` is NOT the loop cap**, which is what this section claimed until the
  integration found the gate blocking one agent twice. The flag is scoped to a single
  stop-chain — one user prompt — so anything that pokes the agent (a ring, a `tell`, the
  reconciler's own nudge) starts a fresh chain with the flag false. The cap is the store:
  one block per agent until it reports something (`hooks._already_nudged`,
  `audit/phase3-edges-fix.md`).

---

# ⚠️ CORRECTION — read before implementing (added 2026-08-07, verified against the CLI)

Two claims below are wrong, and the second would have produced a hook that never fires.

**1. `--bare` is not the isolation mechanism. It SKIPS HOOKS.**

`claude --help`: *"--bare  Minimal mode: skip hooks, LSP, plugin sync, attribution,
auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery."*

The recommendation below is `claude --bare --settings <file>`. That would skip the very
Stop hook it is adding. It also breaks authentication: bare mode requires
`ANTHROPIC_API_KEY` and a subscription login fails with `Not logged in · Please run /login`.

**2. `--settings` merging is not a problem — it is the desired behaviour.**

Merging means the user's own settings plus our hook, *for that session only*. Isolation
does not come from suppressing the user's config; it comes from the fact that only agents
we spawn are passed the file at all. An ordinary `claude` session never sees it.

**Verified, by running it rather than reading about it:**

```
claude -p --settings /tmp/hooktest/settings.json   -> hook FIRED
claude -p --bare --settings ...                    -> not fired, and auth failed
```

**So: `--settings <file>`, no `--bare`.**

**3. The verb is `sb done`, not `wf__report`.** That name is from the pre-implementation
research and was retired hours before this document was written.

**Note on method.** The sections below cite "verified via 06-agent-comms.md research" and
"verified via hooks reference and POC.md" — those are our own earlier notes, not the CLI.
The brief asked for verification against the real thing, and this is the same failure that
produced the RETRACTED entries in `POC.md`. The Stop-hook reasoning is still worth reading;
treat every "verified" claim in it as unverified until run.

---

# Agent Hooks: Design for Mechanical Enforcement

## Executive Summary

**Recommendation: Implement the Stop hook immediately. Evaluate others later.**

The `Stop` hook is the load-bearing answer to C6 ("enforce mechanically; never instruct"). It blocks agent completion until `wf__report` is called, making status reporting impossible to forget. Cost is negligible (~10-50ms per turn), isolation is proven, and it works identically on Claude Code and Codex.

All other hook candidates are worth exploring but lower-priority: they either have higher per-operation cost (`PreToolUse` on every tool call) or solve optional problems (SessionStart identity registration, UserPromptSubmit input validation).

---

## The Stop Hook — Status Reporting Enforcement

### Problem
Current state: agents call `sb done "<summary>"` by choice. Nothing enforces this. An agent that ends a turn without reporting is invisible to the store — this is **the single most common failure in the system** per [PLAN.md D2]. The store shows `working`, but the herdr transcript is idle. Detection (`status.py` joins against herdr) works, but it's C9 covering for C6, not a fix.

### Solution
A blocking `Stop` hook that queries the store: "Did this agent report on this turn?" If not, exit 2 to prevent completion. The agent cannot finish without compliance.

**Why it works:**
- Hooks survive compaction and are not forgotten like prompt instructions.
- Exit 2 on a blocking hook (Stop, PreToolUse, UserPromptSubmit, etc.) prevents the action unconditionally.
- The agent does not get a second turn; the same turn is resumed/blocked until exit 0.
- Cost is ~10-50ms per turn (subprocess spawn overhead), which is negligible in a turn that already costs 1-2 seconds.
- Both Claude Code and Codex have identical Stop hooks with identical envelope and exit-code semantics.

### Implementation
Settings structure (`.claude/settings.json` or passed via `claude --settings`):

```jsonc
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/wf-stop-gate",
            "timeout": 5,                    // Max 5 seconds to query store
            "statusMessage": "Checking status report…"
          }
        ]
      }
    ]
  }
}
```

**The gate script** (pseudocode):
```python
#!/usr/bin/env python3
import sys, json, sqlite3
hook_event = json.load(sys.stdin)
session_id = hook_event.get("session_id")
db = sqlite3.connect("~/.switchboard/state.db")

# Query: did this agent call wf__report on this turn?
reported = db.execute(
  "SELECT COUNT(*) FROM events WHERE session_id=? AND event_type='report'",
  (session_id,)
).fetchone()[0] > 0

if not reported:
  print(json.dumps({
    "decision": "block",
    "reason": "Must call wf__report before finishing. Call: wf__report(status='done')"
  }))
  sys.exit(0)  # exit 0 with JSON decision
else:
  sys.exit(0)  # success, agent can finish
```

### Verification: Isolation & Merge Behavior
**Question:** Does `--settings` merge with `~/.claude/settings.json` or override it?

**Answer (verified via 06-agent-comms.md research):**
- **Without `--bare`**: auto-discovery loads `~/.claude/settings.json`, repo `.claude/settings.json`, plugins. `--settings` **merges** (layering). ❌ Not suitable for agent spawning.
- **With `--bare`**: only specified config is loaded. **No user/repo settings auto-discovered. `--settings` overrides entirely.** ✅ Suitable for reproducible worker agents.

**Conclusion:** Agent spawn commands use `claude --bare --settings <agent-settings-file>`, ensuring the Stop hook reaches only the agent, never the human's ordinary sessions.

### Verification: Exit 2 Re-entry Behavior
**Question:** When Stop hook exits 2, does the agent get a new turn or resume the same one?

**Answer (verified via hooks reference and POC.md):**
Exit 2 on a blocking hook (Stop, PreToolUse, etc.) is **"prevent this action"**. The agent's attempt to finish is blocked. The same turn resumes — no new turn, no extra tokens beyond the hook subprocess overhead. The agent's reasoning is not reset.

**Cost:** The hook invocation itself (~10-50ms, one subprocess) is paid. The agent loop cost is paid once. The cost of the agent *failing to comply* (loop iterations until it calls `wf__report`) is the agent's problem, not the system's — which is correct: we want the friction to be on the agent.

**Loop risk:** Could a non-compliant agent loop forever? Yes, if it never calls `wf__report`. But:
1. The agent sees the block reason: "Must call wf__report before finishing."
2. If the agent keeps trying without calling it, that's a bug in the agent, not the hook.
3. The parent can `interrupt` or watch for `session_id` going idle and escalate to a gate.
4. No different from any other control-plane failure.

---

## Candidates to Evaluate Later

### SessionStart
**Purpose:** Register identity eagerly instead of lazily on first `sb` call.

| Aspect | Detail |
|--------|--------|
| **Blocking?** | No; non-blocking event |
| **Cost** | ~10-50ms per session start (one subprocess) |
| **Frequency** | Once per session (negligible) |
| **Value** | Registers agent identity to store before agent does anything, simplifying race conditions in parent-child startup |
| **Trade-off** | Tiny cost for guaranteed early registration. Worth doing. |
| **Recommendation** | ✅ Add after Stop hook is proven. Low risk, low cost, high safety. |

### UserPromptSubmit — ✅ BUILT, for a different purpose
**Built 2026-08-12** as the activity signal's rising edge (`bin/sb-activity-hook`,
`hooks.run_activity`) — see the note at the top of this file. It writes
`agents.turn = 'working'` and prints **nothing**, because the CLI adds a
`UserPromptSubmit` hook's stdout to the agent's context. It does **not** flush mail, which
is what the row below proposed: the flush is still the piggyback on every `sb` invocation
plus the collector's `sb flush` tick, and a hook that rang the doorbell at the exact moment
a turn began would only be deferring the ring it had just fired. The table below is the
pre-build estimate, kept for the cost line.

**Purpose (as proposed):** Flush pending mail rather than having it piggyback on any `sb`
invocation.

| Aspect | Detail |
|--------|--------|
| **Blocking?** | Yes; can inspect/modify input before processing |
| **Cost** | ~10-50ms per prompt (one subprocess) |
| **Frequency** | Once per agent turn (moderate) |
| **Value** | Replaces the piggyback flush in `Broker.flush_pending`; more deterministic delivery |
| **Trade-off** | Small cost per turn; enables decoupling mail from `sb` calls. |
| **Recommendation** | ⏸️ Build after Stop hook is stable. Optional; current piggyback is acceptable. |

### PreToolUse
**Purpose:** Enforce file ownership mechanically instead of by instruction. There is no
longer a preset for it: the `own-files` preset was deleted and the scope half of it —
edit only what you were assigned, report anything else rather than fixing it — moved into
`defaults/protocol.md`, so every agent is told once. That makes the instruction universal;
it does not make it enforced, which is what this hook would be for.

| Aspect | Detail |
|--------|--------|
| **Blocking?** | Yes; can block tool execution |
| **Cost** | ~10-50ms **per tool call** (high-frequency) |
| **Frequency** | 10-100+ per agent per turn |
| **Value** | Prevents tool calls to files not owned by the agent. Currently relies on a protocol sentence, which is forgotten under compaction or task depth. |
| **Trade-off** | **High per-operation cost** (1-5 seconds added per turn if there are 100+ tool calls). Worth it *only if* file-ownership violations are common and serious. |
| **Loop risk** | If agent keeps trying to call disallowed tools, it pays the hook cost on each retry. Acceptable; the friction discourages the mistake. |
| **Recommendation** | ❌ Defer; measure first. Only add if file-ownership bugs are frequent. C6 says "enforce mechanically," but the cost has to justify the bug rate. Revisit after 10-20 real runs. |

### PreCompact
**Purpose:** Run validation or logging before context compaction.

| Aspect | Detail |
|--------|--------|
| **Blocking?** | Yes; can block compaction |
| **Cost** | ~10-50ms per compaction event (rare; ~1-2 per agent lifetime) |
| **Frequency** | ~1-2 per agent per long run (negligible) |
| **Value** | Emit events into the log before context is discarded; ensure agent has reported before compacting. Useful for observability. |
| **Trade-off** | Negligible cost, useful signal. Worth doing for logging/observability hygiene. |
| **Recommendation** | ⏸️ Build after Stop hook; lower priority than SessionStart. |

### SubagentStop
**Purpose:** Guard subagent completion (Codex only; Claude Code has no named subagents).

| Aspect | Detail |
|--------|--------|
| **Blocking?** | Yes (Codex) |
| **Cost** | ~10-50ms per subagent finish (depends on deployment topology) |
| **Frequency** | Depends on agent tree depth |
| **Value** | Enforce compliance on Codex subagents the same way Stop enforces it on parents. |
| **Trade-off** | Symmetry with Stop hook. Only needed if Codex subagents are in scope. |
| **Recommendation** | ⏸️ Design alongside Stop for Codex target if applicable, but defer implementation until Codex tests. |

---

## Hooks Explicitly NOT Recommended

### Notification
**Why skip:** Generates noise; better to let agents emit their own events via `wf__report`.

### FileChanged, CwdChanged, DirectoryAdded
**Why skip:** Observability only; add via PostToolUse or explicit events, not implicit hooks.

### PostToolUse (async)
**Why skip:** Use async only for observability/logging. If you're doing that, emit it explicitly via `wf__report(kind='tool_executed', ...)` instead. Explicit is cheaper than implicit hooks.

---

## Minimal Viable Set (v1)

```
1. Stop              — blocking; enforce status reporting
2. SessionStart      — non-blocking; register identity eagerly
3. PreCompact        — non-blocking; log events before context discarding
4. (maybe) UserPromptSubmit — non-blocking; flush mail deterministically
```

**Total cost per agent per turn:** ~50-150ms (4 hooks × 10-50ms, mostly no-ops). Negligible in a turn budget. Cost is paid only when hooks fire; they do not fire if no action is taken.

---

## Implementation Checklist

- [ ] **Test 1:** Verify exit 2 behavior on Claude Code Stop hook in real session (not mock).
  - Spawn an agent with Stop hook.
  - Hook exits 2 on first call, exits 0 on second call.
  - Confirm agent's turn does not increment; agent resumes in-turn, not a fresh turn.
  - Confirm no token budget is consumed beyond hook subprocess overhead.

- [ ] **Test 2:** Verify `--bare --settings` isolation.
  - Create a temporary settings file with Stop hook pointing to a test script.
  - Spawn agent with `claude --bare --settings <temp-file>`.
  - Confirm hook is loaded; user's `~/.claude/settings.json` is not loaded (e.g., user's statusline doesn't run).
  - Confirm agent's settings file takes precedence; no merging.

- [ ] **Test 3:** Verify hook execution inside interactive and non-interactive (`--print`) modes.
  - Stop hook must work in both modes.
  - Confirm stdin/stdout of hook is correct in both modes (hooks read hook event JSON on stdin, write decision JSON on stdout).

- [ ] **Implement wf-stop-gate script.**
  - Query store for `(session_id, event_type='report')`.
  - Exit 2 if not reported; exit 0 with decision JSON if ok.
  - Timeout: 5 seconds (abort if store is slow).

- [ ] **Verify store schema** includes session_id tracking and event logging sufficient for stop-gate to query.

- [ ] **Deploy to v1 agents** as part of spawn flow (step 1 of agent initialization).

---

## Rejected Alternatives

### Always-on LLM judge
- Violates C8 (determinism first).
- Costs tokens on every transition.
- Unpredictable exactly when you need predictability.

### Polling supervisor
- Violates C10 (idle costs nothing).
- 132M cache-read tokens in 3 hours is the historical failure here.

### Shared status file / transcript parsing
- Violates C7 (store is the only memory).
- Couples agents to file-system timing.
- No schema, no validation.

### Prompt instruction "always call sb done"
- Violates C6.
- Agents forget under compaction, long task loops, task depth.
- Unenforceable.

---

## References

- **[PRINCIPLES.md C6]** — Enforce mechanically; never instruct.
- **[PLAN.md D2]** — Status mechanism (unbuilt; Stop hook is the answer).
- **[06-agent-comms.md 0.2]** — Stop-hook gate as enforcement daemon.
- **Claude Code hooks reference** — `code.claude.com/docs/hooks` (verified).
- **Codex hooks reference** — `learn.chatgpt.com/docs/hooks` (verified).
