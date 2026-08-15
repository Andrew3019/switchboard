# Does herdr itself support a `codex` agent kind? — verified

**Direct answer: herdr's `--kind codex` already exists, works, and detects status
correctly** — I started, drove, and read back a real `codex` TUI through herdr in a
throwaway pane and it behaved correctly at every stage (spawn, trust-prompt `blocked`,
prompt delivery, `working`→`done` transition). The gap is not in herdr; it is entirely
in switchboard's own adapter (`switchboard/herdr.py`), which is hardcoded to Claude
Code's CLI flags, hook system, and session-id source. See §5.

`herdr 0.8.0` / protocol 19 (same binary version switchboard is pinned to,
`herdr.py:9`). All claims below are **VERIFIED** (I ran the command) unless marked
**READ** (from `--help`/config files only).

## 1. `--kind` vocabulary

**VERIFIED** via `herdr agent start --help` / `herdr agent --help`:

```
pi, claude, codex, gemini, cursor, devin, agy, cline, omp, mastracode, opencode,
copilot, kimi, kiro, droid, amp, grok, hermes, kilo, qodercli, maki
```

`codex` is on the list. `herdr integration status` (**VERIFIED**) separately lists
per-kind *integration* hook scripts (e.g. `/Users/andrew/.codex/herdr-agent-state.sh`,
mirroring `/Users/andrew/.claude/hooks/herdr-agent-state.sh`) — all reported
`not installed` on this machine, which is correct: switchboard's own
`Herdr.check()` (`herdr.py:320-335`) refuses to run if the `claude` one *is* installed,
because it would silently steal state-write authority from switchboard's own hooks
(same mechanism would apply to a `codex` integration if it were ever installed).

What `--kind` changes, from spawning `codex` through it (§2 below): the canonical
executable invoked (`argv":["codex"]` in the `agent_started` response — plain `codex`,
no extra flags), and which detection manifest (§3) and integration-hook path (above)
herdr looks up for that pane. It does **not** change how `agent prompt`/`send-keys`
work (§4).

## 2. Live test — spawn, trust prompt, prompt/response, teardown

Done in a throwaway git repo under the scratchpad dir, in its own herdr workspace
(`herdr workspace create --cwd <scratch> --no-focus`, pane `w1H5:p1`), never touching
the live fleet's agents (`herdr agent list` was read once beforehand only to confirm I
wasn't colliding with anything, and every real agent shown there has kind `claude`).

- `herdr agent start herdr-kind-probe --kind codex --pane w1H5:p1` → **VERIFIED**
  succeeds immediately, `agent_status: idle`, `argv: ["codex"]`.
- A read one call later showed `agent_status: blocked` — **VERIFIED**. `herdr pane
  read` showed codex's real "Do you trust the contents of this directory?" prompt
  (the same trust gate the earlier codex-CLI scout note found, `notes/codex-scout-cli-behaviour.md`
  §1). herdr classified it as `blocked` correctly, unprompted, using a codex-specific
  rule (see §3).
- `herdr agent send-keys w1H5:p1 "1"` then `herdr agent send-keys w1H5:p1 enter` (two
  calls, `sleep 1` between — same race the earlier codex scout note flagged for typed
  text vs Enter) → **VERIFIED** dismissed the trust prompt; codex reached its normal
  idle screen (`herdr agent read --source detection` showed the ASCII banner
  `>_ OpenAI Codex (v0.147.0)`).
- `herdr agent prompt w1H5:p1 "Reply with exactly the single word: PONG" --wait
  --timeout 60000` → **VERIFIED** returned once codex settled, `agent_status: done`.
  Re-reading the pane showed the literal exchange (`› Reply with exactly the single
  word: PONG` / `• PONG`) — herdr's blind paste-and-Enter delivered correctly into
  codex's input box and the wait correctly tracked the working→done edge.
- Teardown: `send-keys esc` (idle no-op), `herdr workspace close w1H5` → **VERIFIED**
  pane and process gone (`pgrep -f "^codex$"` empty afterward), `codex delete --force
  <session-id>` removed the session, removed the one `[projects."<scratch path>"]
  trust_level = "trusted"` entry that got written to the real `~/.codex/config.toml`
  by accepting the trust prompt, deleted the scratch repo. No other file under
  `~/.codex` was touched. Nothing was spawned against the live switchboard store.

## 3. Status detection: per-kind manifest, not a hardcoded Claude scraper

**This is the headline finding, and it overturns what the existing hooks.py comment
implies.** `hooks.py:9-13` says herdr infers status "by matching Claude's spinner
glyphs in the terminal title," and that a Claude Code point release once broke this
for every pane on the machine. That was true as a historical incident, but it is not
the current architecture:

- herdr ships a **remote-updatable, per-kind TOML rule manifest** at
  `~/.local/state/herdr/agent-detection/remote/<kind>.toml` — one file per kind, 18
  files present including `claude.toml` and `codex.toml` (**VERIFIED**, `ls` +
  `cat` both files).
- `herdr agent explain <target> --verbose` (**VERIFIED**, run against the live probe)
  dumps exactly which manifest and which rule fired, with the priority-ordered list of
  every rule it evaluated and why each did or didn't match. This is a real
  introspection tool, not something I had to infer.
- `codex.toml` (`version = "2026.08.09.1"`) has **codex-specific rules**: an
  `osc_title_blocked` rule keyed on the terminal-title substring `"Action Required"`,
  a `trust_directory` rule matching codex's exact trust-prompt wording (this is the
  rule that fired in my test — confirmed by `agent explain`'s `rule:` field), a
  `live_strong_blocker` rule for codex's approval-prompt phrasing (`"allow command?"`,
  `"press enter to confirm or esc to cancel"`), and — matching the earlier codex-CLI
  scout note's own screen-scrape observation almost verbatim — a
  `screen_working_fallback` rule with `line_regex =
  '^[•◦]\s+Working \([^)]*esc to interrupt\)(?: · .*)?$'`, i.e. herdr already knows
  codex's own `• Working (Ns • esc to interrupt)` banner text.
- `claude.toml` (`version = "2026.08.13.1"`) — the update date is two days *after*
  the incident the hooks.py comment describes — now matches both the old braille
  spinner range and the newer half-circle glyphs
  (`[\x{2800}-\x{28FF}\x{25D0}-\x{25D3}]`), i.e. herdr's own manifest system already
  self-healed the exact break switchboard's comment is about, independent of
  switchboard's own turn-signal hooks.
- Both manifests also carry an `osc_title_working` rule matching the *same* spinner-
  glyph braille set (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) — so "Claude's spinner glyphs" was never fully
  Claude-specific to begin with; codex apparently emits a similar-shaped busy
  indicator in its own terminal title, and herdr's manifest author reused the pattern.

Net: detection **is** per-kind, actively maintained, remote-updated independent of a
herdr binary release, and already has a working codex manifest — verified working
correctly on a real trust-prompt block and a real working→done turn in my test. The
one thing my test did *not* exercise is a genuine `working` mid-turn read (codex
answered "PONG" fast enough that I never captured a mid-flight snapshot) — I did not
independently confirm the `osc_title_working`/`screen_working_fallback` rules fire
live, only that they exist and that the overall turn was correctly bracketed
(`idle`→ prompt →`done`).

## 4. `agent_session` / session id capture

**Not automatic for either kind.** Neither the `agent_started` response from `herdr
agent start --kind codex` nor any subsequent `herdr agent get` on that pane carried an
`agent_session` field — **VERIFIED**, checked at every stage of the test. The real
live fleet's `herdr agent list` output (read once, not touched) shows the same: none
of the currently-running real `claude`-kind agents have an `agent_session` field
either.

This matches what `switchboard/herdr.py` already documents: session id is not
something herdr extracts from the pane on its own for *any* kind. Switchboard supplies
it itself via `report_session()` (`herdr.py:1022-1036`), fed from
`CLAUDE_CODE_SESSION_ID` — an env var **Claude Code itself** sets in its own process
environment, which switchboard's Stop/UserPromptSubmit hook payload happens to carry.
I checked the actual `codex` process's environment during my test
(`ps eww -p <pid>`, **VERIFIED**) and there is no analogous `CODEX_SESSION_ID` (or
similar) env var — codex does not expose its own thread id via process environment at
all.

What codex *does* expose (from the earlier scout note, `notes/codex-scout-cli-behaviour.md`
§3 and §5, not re-verified here but consistent with what I found): the
`~/.codex/sessions/<date>/rollout-<timestamp>-<thread-id>.jsonl` file it writes on
every launch (I located mine — `01a00797-5213-7e40-810d-afb6d55025fe`, matching what
`codex delete --force` accepted during cleanup), and a `notify` config hook whose
payload includes `"thread-id"`. Neither of those is a herdr-level capability — herdr
would have to be told the id the same way switchboard tells it a Claude session id
today: `herdr pane report-agent-session <pane> --agent-session-id <id>` (**READ**,
`herdr agent --help` documents this via `Herdr.report_session`'s own call shape,
`herdr.py:1032-1033`, but I did not call it directly against codex in this test).
`herdr agent explain --help` and `herdr pane report-agent-session --help` were not
separately dumped in this pass; the call shape is read from switchboard's existing
code rather than herdr's own help text.

## 5. `agent prompt` / `send-keys esc` — kind-aware or blind?

**Blind — confirmed by direct test, not just help text.** `herdr agent prompt`
(**VERIFIED**) pasted literal text into whatever was focused in the pane and pressed
Enter; it worked identically against codex's input box with no special handling, and
nothing in `--help` (`herdr agent prompt --help`, `herdr agent send-keys --help`)
mentions kind at all — `send-keys`'s only documented special case is that `esc` is
"the canonical Escape key name," which is generic terminal vocabulary, not Claude- or
codex-specific. This is consistent with switchboard's own `Herdr.prompt` docstring
(`herdr.py:600-626`, "pastes into the pane's chat box and presses enter — the same
channel as literal human typing").

## 6. What actually blocks codex support today — it's switchboard, not herdr

herdr's `--kind codex` is real and works. The blockers found by the earlier scout
passes (`notes/codex-scout-sb-prompt-plumbing.md`) are all in
`switchboard/herdr.py`/`hooks.py`/`store.py`, not in herdr:

- `Herdr.start_agent` hardcodes Claude Code CLI flags —
  `--append-system-prompt-file`, `--permission-mode`, `--model`/`--effort`,
  `--settings`, `--resume` (`herdr.py:557-580`) — none of which codex accepts (codex's
  own flags are `-C`/`--add-dir`, `-m`/`--model`, `-s`/`--sandbox`,
  `-a`/`--ask-for-approval`, `--resume`/`codex resume`, per the earlier cli-behaviour
  scout note). Passing Claude's flags to codex would fail at the CLI-argument level,
  before herdr's `--kind` even matters.
- `hooks.py`'s whole Stop-gate/turn-signal mechanism (`--settings`,
  `UserPromptSubmit`/`Stop` hook events) is Claude Code's own hooks.json shape, which
  codex does not have — codex's nearest equivalent is the `notify` config key (a
  program invoked on turn completion, confirmed in the earlier cli-behaviour note) or
  its own broader-but-unexplored `hooks` config struct.
- `store.transcript_dir`/`output.py`'s transcript parser hardcode `~/.claude/projects/
  ...` and Claude Code's own JSONL record shape — codex's rollout files live at
  `~/.codex/sessions/...` in a different shape.
- Session id: as above, no env var equivalent to `CLAUDE_CODE_SESSION_ID` for codex.
- `models.py`'s `wired_providers()` only has `claude` wired; an unwired provider
  raises before any spawn is attempted.

If someone wanted the fastest low-risk way to get a codex TUI up under herdr **today**,
without touching switchboard: `herdr agent start <name> --kind codex --pane <id> --
<codex-args>` works standalone, driven directly (not through `sb`) — I did exactly
this in the test above. What breaks if switchboard tried to drive it through the
existing `Broker.delegate`/`start_agent` path unmodified: the spawn itself would fail
first, because `agent_args` still carries `--append-system-prompt-file`/
`--permission-mode`/`--settings`, all of which are invalid codex CLI arguments — codex
would reject the whole invocation before ever reaching herdr's `--kind` dispatch.
Status detection and session-id capture, once past that, would each need their own
codex-shaped source (herdr's own manifest for status — already works, per §3; some new
non-hook mechanism for session id, per §4) — switchboard's Claude-only hook and env-var
assumptions would simply never fire and those two signals would silently go missing,
not error loudly.

## Summary of confidence

- §1 (kind list), §2 (live spawn/prompt/status/teardown), §5 (prompt/send-keys
  blindness): **VERIFIED** by direct commands in this session.
- §3 (manifest-driven detection): **VERIFIED** that the manifest system and
  codex-specific rules exist and that the trust-prompt rule fired correctly live; the
  `working`-state rules were read from the manifest file and cross-referenced against
  the earlier scout note's independent screen-scrape, but not caught firing live in my
  own test (my test's turn completed too fast).
- §4 (session id): **VERIFIED** that no automatic capture happens for either kind and
  that codex's process env has no session-id var; the `report-agent-session` API shape
  for wiring a codex thread id in is **READ**, not itself called against codex in this
  test.
- §6 is synthesis of the above against `switchboard/herdr.py`/`hooks.py` code already
  read (file:line cited throughout), not new investigation.
