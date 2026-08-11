# Is an agent actually working? What herdr knows, why it currently lies, and what to trust instead

**Bottom line, first.** herdr's live Claude/idle detection is currently broken for every pane on
this machine, root-caused and reproduced live below. It is not a mystery and not ours to patch at
the source — it's a one-line regex in herdr's bundled manifest that Claude Code's own CLI silently
invalidated by changing its spinner glyphs. But the deeper problem is architectural and **is**
ours: switchboard has no signal of its own. It used to (`Herdr.report_state`), stopped because that
call permanently costs the agent's name binding, and never replaced it with anything — so today
there is exactly one source of busy/idle truth (herdr's screen-scraper), it is fragile by
construction, and it just broke. The durable fix is to record the fact ourselves, from Claude
Code's own hooks, into switchboard's own store — never touching herdr's agent registry, so nothing
is evicted. Ranked recommendation is in the [What to trust](#what-to-trust-ranked) section.

## 1. What herdr actually tracks

One state per pane, four values, defined once in the detection engine:

```rust
// src/detect/mod.rs:10-19 (herdr, /Users/andrew/Code/herdr)
pub enum AgentState {
    Idle,     // Agent finished, prompt visible, nothing happening.
    Working,  // Agent is actively working/processing.
    Blocked,  // Agent needs human input and is blocked on a response.
    Unknown,  // Plain shell or unrecognized program.
}
```

There is **no internal state finer than this**. "Model is generating" and "a tool call is
running" are the same value, `Working`. Confirmed by reading `src/terminal/state.rs` end to end and
every file the brief asked about (`agent_view.rs`, `actions.rs`, `api/subscriptions.rs`,
`api/wait.rs`, `terminal/metadata.rs`): no richer enum, no extra field, anywhere.

The CLI/JSON layer (`herdr agent list`/`agent get`, what switchboard actually reads) exposes a
fifth value, `AgentStatus::Done` — but it isn't a distinct detection, it's `Idle` plus a "have you
looked at this pane yet" flag:

```rust
// src/app/api_helpers.rs:99-108
pub(super) fn pane_agent_status(state: AgentState, seen: bool) -> AgentStatus {
    match (state, seen) {
        (AgentState::Idle, false) => AgentStatus::Done,
        (AgentState::Idle, true)  => AgentStatus::Idle,
        (AgentState::Working, _)  => AgentStatus::Working,
        (AgentState::Blocked, _)  => AgentStatus::Blocked,
        (AgentState::Unknown, _)  => AgentStatus::Unknown,
    }
}
```

## 2. What sets each state — and why Claude has no redundancy

**herdr never asks Claude Code anything.** There is no heartbeat, no hooked API call, no
process-state check for the *state itself*. The whole signal is a manifest-driven regex/contains
matcher run over (a) the pane's rendered screen buffer and (b) two OSC escape-sequence payloads the
child process writes to the pty — the window/tab **title** (OSC 0/2) and a **progress** string
(OSC 9;4) — captured by herdr's terminal core (`src/pane/terminal.rs:1163-1179`) and fed to
`detect_agent_with_osc` (`src/detect/mod.rs:250-273`).

Per agent type, herdr loads a TOML rulebook, highest `priority` wins. Claude's is
`src/detect/manifests/claude.toml` (162 lines, `version = "2026.08.04.1"`). Reading the whole file,
there are exactly **two rules that can ever produce `Working`**:

```toml
# osc_title_working — priority 1100, the highest rule in the file
region = "osc_title"
regex = ['^[\x{2800}-\x{28FF}] ']   # a Braille Patterns glyph (U+2800–U+28FF) + a space

# btw_overlay_working — priority 975, unrelated to general tool activity
region = "bottom_non_empty_lines(5)"
line_regex = ['^\s*/btw(?:\s|$)', '(?i)esc to close\s*$']
```

There is no generic screen-text "esc to interrupt" / spinner-text / tool-banner rule for Claude at
all (herdr's Codex manifest has one; Claude's does not — confirmed by grepping the full file and
its two-commit history for "interrupt", zero hits). **The entire busy signal for Claude reduces to
one regex matching one specific Unicode block in the terminal's title string.**

This is *by design* a single point of failure, and a documented one. herdr's own CHANGELOG
(`/Users/andrew/Code/herdr/CHANGELOG.md:380`, v0.6.7, 2026-06-03):

> "Claude Code, Codex, GitHub Copilot CLI, Droid, Kimi Code CLI, and Qoder CLI integrations now
> report session identity only. Native state for those agents comes from Herdr's screen detection…"

Confirmed live in the current code: `full_lifecycle_hook_authority()` (`src/detect/mod.rs:283-291`)
— the whitelist of integrations whose *own* state reports are trusted over screen detection — lists
`pi, omp, mastracode, opencode, kilo, kimi`. Claude is not in it, and never has been. So the bundled
Claude Code integration herdr ships cannot tell herdr "I'm working" even if it wanted to; only the
screen-scraper can.

(Separately, `session_identity_only_integration()` — a *different*, two-entry list, `hermes` and
`antigravity_cli` — is not the same gate; it is not the reason Claude has no redundancy. The reason
is that Claude is simply absent from the full-lifecycle whitelist above.)

## 3. Which call switchboard uses today, and why it inherited this fragility

`switchboard/herdr.py` (`Agent.from_json`, line 136) reads `agent_status` straight off `herdr agent
list`/`agent get` into `Agent.state`. `Broker._busy` (`switchboard/broker.py:4003-4009`) is the
consumer:

```python
def _busy(self, who: str) -> bool:
    return (self._agent_states() or {}).get(who) == WORKING
```

`_agent_states()` (`broker.py:3900-3915`) is one `herdr agent list` call, cached per `sb` process.
That's the whole path: `_busy` ⇐ `agent_status` ⇐ herdr's screen/OSC scraper ⇐ the one regex above.

Switchboard *does* have its own authoritative-report mechanism — `Herdr.report_state`
(`switchboard/herdr.py:782-861`), which calls `pane report-agent` under a private source
(`custom:<ourtool>`, never `herdr:*`). Per `src/terminal/state.rs`'s effective-state formula, a
report under any source outside the six-integration whitelist above **is always authoritative**
over screen detection (confirmed against source in `reference/herdr-state-authority.md`, itself
checked against `src/terminal/state.rs:2006-2047` and `:1692-1697`). If switchboard were still
calling it, this whole bug class would be masked.

It isn't called any more, and `report_state`'s own docstring says why, plainly: any call —
regardless of the state value — **permanently evicts the agent's herdr name binding**:

> "Measured on herdr 0.8.0 against a throwaway pane: `agent start` → resolvable, `report_session` →
> still resolvable, one `report_state(..., IDLE)` → agent_not_found for good."
> — `switchboard/herdr.py:806-809`

So switchboard traded a reliable status signal for a reachable name, on purpose, and has run with
*no* redundant status signal ever since. That trade is the real vulnerability the current bug
exposes: there has been exactly one source of truth for a long time, and it just broke.

## 4. Why every pane reports idle right now — reproduced live, not inferred

**Root cause: Claude Code changed its terminal-title spinner glyph set; herdr's regex is hard-coded
to the old glyph range.**

Claude Code's own changelog, version **2.1.228** (fetched from
`https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`, line 20 under that
version's heading):

> "Updated terminal title busy-spinner glyphs to reduce tab-bar jitter on some terminals"

herdr's `osc_title_working` rule requires the title to start with a glyph in `U+2800`–`U+28FF`
(Braille Patterns — the classic braille-dot spinner, e.g. `⠋⠙⠹`) followed by a space. I checked
`git log --all -p --follow -- src/detect/manifests/claude.toml` in the herdr checkout myself: only
two commits ever touch that file, and neither changed this regex — it has read
`'^[\x{2800}-\x{28FF}] '` since the file's first commit in this history (2026-08-03). herdr's
manifest didn't move. Claude Code's glyphs did.

**Live proof, captured from my own pane while this exact investigation was running** (I am, myself,
a Claude Code session running under herdr — `HERDR_PANE_ID=wVN:p1`, agent name `truth-status`).
Sampled `herdr agent get truth-status` eight times, one second apart, during a single long shell
tool call:

```
"terminal_title":"◐ Determine agent real status from herdr source"
"agent_status":"idle"
```
(repeated identically all eight times — the pane was continuously mid-tool-call throughout)

`◐` is U+25D0 — Geometric Shapes, not Braille. `python3 -c "print(hex(ord('◐')))"` → `0x25d0`,
outside `0x2800`–`0x28ff`. A sibling pane (`audit-status-model`, also mid-tool-call at the same
moment, per `herdr agent list`) showed the same pattern with `◑` (U+25D1), also outside the range.
Panes that really were idle at that moment showed `✳` (U+2733) — which *is* matched by herdr's
`osc_title_idle` rule (`regex = ['^\x{2733} ']`) — so idle detection still works; only the
*working* rule is dead.

And herdr's own diagnostic confirms the mechanism directly, run live against my own pane
mid-tool-call:

```
$ herdr agent explain truth-status
agent: claude
state: idle
manifest: remote:/Users/andrew/.local/state/herdr/agent-detection/remote/claude.toml 2026.08.04.1
rule: live_prompt_box (region=prompt_box_body priority=950)
evidence: "❯\n"
```

So the failure has two layers, both confirmed: (1) `osc_title_working` (priority 1100) never fires
because the title glyph is outside its regex's range, and (2) with the one rule that could win
disqualified, the next rule that *does* match anything is `live_prompt_box` (priority 950) — because
Claude Code's prompt box still renders a bare `❯` on screen even while a tool call is in flight, and
that pattern satisfies `live_prompt_box`'s idle rule. Fixing the glyph range alone is sufficient:
1100 > 950, so a corrected `osc_title_working` would win back the priority race.

This is not speculative — it is the literal output of `herdr agent explain`, run against a pane that
was, at that instant, blocked in a Bash tool call I had started myself.

## 5. Is there a better call available today?

No. I looked at `agent_view.rs`, `actions.rs`, `render_prof.rs` (there is no `render_signal.rs` or
`terminal_notify.rs` in this checkout — verified absent by `find`/`grep`, not assumed), and the
subscription/wait API (`EffectiveStateChange`, `src/terminal/state.rs:78-87`) — every one of them
carries the same four-value `AgentState`/five-value `AgentStatus`, nothing finer. There is no herdr
call, today, that distinguishes "model generating" from "tool running" from "waiting at a prompt."
`Working` is `Working`, full stop, and for Claude it is currently produced by exactly one regex that
is presently broken.

## 6. Outside evidence — Claude Code's own status surfaces

Checked against official docs (`code.claude.com/docs/en/hooks`, `.../statusline`), not folklore:

- **Hooks are the only mechanism with real granularity.** `PreToolUse` fires immediately before a
  tool executes; `PostToolUse` immediately after it succeeds (`PostToolUseFailure` on failure);
  `Stop` when a turn ends; `UserPromptSubmit` when a new turn begins; `PermissionRequest` when a
  tool call is waiting on a permission decision. Documented, first-party, and — critically for us —
  switchboard **already wires one of these up**: `switchboard/hooks.py` installs a `Stop` hook via
  `--settings` on every spawn, specifically to require `sb done`/`sb block` before a turn is allowed
  to end. The plumbing to add `PreToolUse`/`PostToolUse` the same way already exists and is proven
  to fire reliably (verified against the real CLI per that file's own header note, 2026-08-11).
- **There is no hook that fires *during* a tool call** — only immediately before and immediately
  after. That's fine: "PreToolUse fired, PostToolUse hasn't yet" *is* "mid-tool-call," recorded as a
  fact rather than inferred from a screen glyph.
- **The status line is not a live busy/idle signal.** Per docs, it only re-runs on a new assistant
  message, `/compact`, a permission-mode change, vim-mode toggle, or an optional fixed
  `refreshInterval` timer — explicitly *not* on tool start/stop. Not a candidate.
- **Session transcript files** (`transcript_path`, referenced in hook payloads) are what
  `switchboard/herdr.py`'s `deliver()`/`_took_prompt()` already lean on as its own "proof" mechanism
  for confirming a prompt was taken — but that file is documented as flushed on the agent's own
  schedule (measured 35s late once, per that file's docstring), so it's a good confirmation signal
  and a bad live one.

## What to trust, ranked

| Signal | Reliability | Cost | Verdict |
|---|---|---|---|
| **Claude Code hooks → switchboard's own store** (`PreToolUse` sets working, `PostToolUse`/`Stop` clears it) | Highest — a fact Claude Code's own runtime writes down, not inferred from cosmetics | One more `--settings` hook, same mechanism `hooks.py` already uses; no herdr call involved at all | **Recommended.** Never touches `pane report-agent`, so no name-binding eviction risk. Distinguishes tool-running from model-generating from waiting, which herdr cannot do even when healthy. |
| herdr's screen/OSC detector (current sole source) | Low, proven by this doc to be silently breakable by an upstream cosmetic change, with zero redundancy for Claude | Free (already polled) | Keep only as a secondary check, e.g. for `Blocked` where a live permission-prompt-on-screen safety net still has value regardless of what's reported. |
| `Herdr.report_state` (switchboard's old mechanism) | Would be authoritative (confirmed: any non-whitelisted source always beats screen detection) | **Permanently evicts the agent's name binding on the very first call** | Not viable as-is. This is why it was retired, and reintroducing it would trade one bug for a worse one. |

**If one signal must be picked today: none is reliable alone**, and the two that matter measure
different things. herdr's screen-scraper is the only source that currently exists in the running
system, and it just demonstrated it can go dark for an entire agent type with a single unannounced
cosmetic change upstream, with nothing to catch the fall. The honest combination is: **hooks
recording PreToolUse/PostToolUse/Stop into switchboard's own store** as the primary "is this agent
mid-turn" fact (this is the "record the fact" fix the `STALL_GRACE` comment in `status.py:150-177`
gestures at — currently that constant is explicitly "a clock standing in for a fact nobody
records"; this would be the fact), **plus herdr's screen detector kept alive only for `Blocked`**
(permission prompts), where a live-screen safety net genuinely adds something a hook can't easily
give for free (herdr's own `visible_blocker_overrides_hook` already treats this as a special case,
even for agents with hook authority).

## Whose bug is this?

Both, at different depths.

- **The proximate break is herdr's to fix, narrowly**: `osc_title_working`'s regex needs to track
  whatever Unicode range Claude Code's CLI 2.1.228 spinner actually uses now (I did not enumerate
  the new set beyond the two glyphs observed live, `◐ U+25D0` and `◑ U+25D1` — both in the
  Geometric Shapes block, U+25A0–U+25FF, consistent with a rotating quadrant-circle spinner). That's
  a one-line manifest change, upstream, in `/Users/andrew/Code/herdr`, not something to patch
  locally without also losing it on herdr's next manifest update.
- **The systemic gap is ours.** Depending on a third party's cosmetic terminal output as the *only*
  signal for something switchboard's own reliability depends on (mail delivery timing, the
  reconciler's stall detection, the board's working/stalled display) was already fragile before this
  specific regex broke — it would have broken the same way from any future spinner change, terminal
  emulator quirk, or herdr manifest regression, because there was no second signal to fall back on.
  Fixing herdr's regex fixes today's symptom; it does not fix that switchboard has no fact of its
  own to fall back on next time. That part is ours to build, and the pieces to build it
  (`hooks.py`'s `--settings` mechanism, the store's `events`/`agents.state` tables) already exist in
  this codebase.

## What I did not verify

- I did not enumerate Claude Code's full new spinner glyph set — only the two frames observed live
  (`◐`, `◑`). There may be more; any of them landing outside `U+2800`–`U+28FF` reproduces the bug.
- I did not check whether other agent kinds herdr detects (Codex, Gemini, etc.) are similarly
  affected by unrelated spinner changes in their own CLIs — out of scope for this brief, which was
  Claude-specific.
- I did not open a herdr issue or PR, and made no change to herdr or to switchboard's code, per the
  brief's read-only instruction.
- I did not test a working PreToolUse/PostToolUse hook end-to-end (e.g. in an isolated clone) — the
  brief asked me to verify *herdr's* current behavior live, which I did (§4); the hook-based
  alternative is a recommendation grounded in documented, first-party hook semantics and
  switchboard's own already-proven `Stop`-hook plumbing, not something I built and ran here. That
  build-and-verify step belongs to whoever picks up the recommendation.
