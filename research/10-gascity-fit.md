# Gas City (gastownhall/gascity) — Practical Fit for Personal Agent-Workflow Use

Repo: MIT, Go, 1082★, 348 forks, created 2026-02-22, last push 2026-08-07 (active).
v1.4.0 (2026-07-24), 50 releases total including a rolling `edge` tag.

## 1. herdr provider — how it actually works

Source: `internal/runtime/herdr/{client,provider,launchspec,panebinding,capabilities}.go`,
docs at `docs/reference/herdr-provider.md`, design doc `internal/runtime/herdr-provider-design.md`.

- It is a **display/session-topology backend, not an agent driver**. Quote: "one shared herdr
  session-server per city, one workspace per rig (and one for the town), and one tab per agent."
  It is an alternative to tmux for organizing panes/sessions — agents are still launched and
  controlled through their normal transport (Claude Code CLI, ACP, etc.), not through herdr
  send-keys/scraping.
- Selection is **city-wide only**: "herdr cannot be selected for individual agents." (This
  contradicts a generic doc line elsewhere claiming per-agent/per-rig granularity — the provider
  code itself only supports the city-wide switch.)
- Known gap: "the herdr provider does not implement the transport-capability check, so [an
  ACP] pin is neither honored nor rejected; the agent falls back to the base provider and runs
  on herdr" — i.e., a real, acknowledged edge-case bug, not hidden.
- Maturity: verified against "herdr 0.7.1+", labeled opt-in with "pilot safety" rollout guidance
  in the design doc. Has dedicated tests (`prestart_test.go`, `seedmeta_test.go`,
  `liveness_test.go`, `placement_test.go`, `agentname_test.go`). Reads as a real, maintained
  feature — not a stub — but young and explicitly not the default.

## 2. Multi-repo / multi-project support

- `gc rig add <path>` attaches any repo in place (no forced clone into a prison directory) —
  this genuinely fixes Gas Town's `~/gt/` requirement.
- However, state is **still a single global "city" per machine** (`internal/gchome/gchome.go`):
  resolution order is `GC_HOME` env var → `~/.gc` (user home) → temp-dir fallback → PID-stamped
  last resort. All rigs (repos) you add live inside one shared city/home, not fully isolated
  processes. This is architecturally the same single-town model as Gas Town, just now allowing
  many repos to be *rigs* under one town instead of forcing one town = one repo-clone-tree. It
  should avoid the "two towns corrupting each other" failure mode specifically (there's only
  one town), but cross-rig interference is still architecturally possible since supervisor,
  Dolt/beads store, and session server are shared.
- Evidence of shared-state fragility even with one city: issue #1920, "Dual supervisor on same
  Dolt port → restart flap (23,759 restarts in 6 hours)"; issue #3341, "Dolt compact integrity
  check races continuous writers — quarantine loop silently blocks GC and backups on busy DBs";
  issue #1979, "Non-beads dolt databases... lost on every JSONL-based recovery." These are
  centralized-state/shared-DB failure classes, not resolved by rig-level `add`.
- No open/closed issue matched "cross-project state corruption" or "two towns" directly —
  because the multi-town scenario no longer exists in this design (good), but shared-DB races
  across rigs are a live, ongoing bug category (bad, if you want strict isolation).

## 3. Install footprint & dependencies

- Always required (per README): **tmux, git, jq, pgrep, lsof**. tmux is NOT optional — it
  remains a baseline dependency; herdr is described as "an optional alternative backend" to
  tmux for session display, not a tmux replacement/removal.
- Dolt is genuinely optional: `GC_BEADS=file` switches the beads store to file-based storage,
  dropping the Dolt MySQL-protocol server requirement. Confirmed in README and via
  `cmd/gc/dolt_standalone_conflict.go` existing as a guard path.
- Building from source needs Go 1.26.4+ and ICU libraries; NixOS/Flox users need manual CGO
  path configuration — mostly irrelevant on a stock Mac, but signals the binary isn't fully
  static/dependency-free.
- Net for Mac: brew-installable tmux/git/jq/lsof (pgrep is built-in), plus the `gc` Go binary.
  Dolt avoidable. tmux not avoidable.

## 4. Cost / idle-token behavior

Did not find a resolved fix confirming Gas Town's 132M-cache-read-in-3-hours problem is gone.
Evidence it's a live, acknowledged concern:
- Issue #1751 (open): "feat: per-agent watchdog gate to cut idle token burn from fresh-mode
  utility agents" — i.e., idle token burn is a known, still-open problem area in v1.4.0-era
  Gas City, not a solved one.
- Issue #3892 (open): "control-dispatcher --follow serve loop never quiesces: multi-fork bd
  ready scan up to 12x/min per dispatcher on a fully idle city" — a background daemon actively
  polling on an idle city, independent of LLM token cost but the same category of "burns
  resources at idle."
- No closed issue or changelog entry found declaring idle-burn solved. Conclusion: reduced
  scope of the problem is plausible (file-based beads removes one polling loop; herdr may
  reduce tmux-scrape overhead) but there is no evidence the core "town runs background
  agents/dispatchers that cost money while you're not looking" behavior has been eliminated —
  the architecture (supervisor + dispatcher + patrol loops) is still fundamentally
  daemon/polling-based.

## 5. Backend support: Claude Code vs Codex

- `cmd/gc/runtime_registry.go` registers multiple runtimes; README/docs list Claude, Codex, and
  Gemini as backend options. 30 code hits for "codex" across the repo (providers, tests, docs) —
  real, non-trivial support, not a one-line mention.
- Could not verify feature-parity depth in the time budget; issue #672 "Review and action
  non-Claude provider parity audit report" (open) suggests the project itself acknowledges
  Claude Code is the primary/reference backend and other providers (including Codex) may lag in
  parity. Treat Codex support as present but second-class pending that audit's resolution.

## 6. Project health / bus factor / AI authorship

- Contributors: 158 total, 5225 commits. Top contributor `julianknutsen`: 66.9% of all commits
  (3498). #2 `quad341`: 9.2%. #3 `sjarmak`: 4.3%. This is concentrated but **meaningfully less
  extreme than Gas Town's reported ~95%/one-bot** — there's a real (if thin) second/third tier
  of contributors.
- Recent 30 merged PRs: julianknutsen 18, sjarmak 7, jacobhausler 2, remuscazacu 1, quad341 1,
  A3Ackerman 1 — i.e., in the current window one person still authors 60% of merges. Bus factor
  is weak; if `julianknutsen` stops, velocity likely drops sharply.
- AI-authorship signal: in a 100-commit sample, only 5% carry an explicit "Co-Authored-By:
  Claude" / "Generated with" trailer — far lower than Gas Town's reported 94%-bot-PRs figure.
  This is not proof the maintainer isn't using AI assistance without disclosure, but the visible
  trailer rate is low, unlike Gas Town.
- Cadence: very active — 50 releases from v1.0.0-rc1 (2026-04-21) to v1.4.0 (2026-07-24), roughly
  weekly point releases, plus a rolling `edge` tag. Issues: 494 open / 687 closed — a large,
  actively-triaged backlog typical of a fast-moving young infra project, not an abandoned one.

## 7. Non-code work

Documentation and code surfaced are exclusively about coding/orchestration workflows (formulas,
beads, rigs, sessions, supervisors). No mention found of general non-code task support, and no
issue found proposing or reverting a "no git diff = auto-reject" policy — could not confirm
whether the specific Gas Town auto-rejection behavior persists, but nothing in the README,
docs, or issue search suggests non-code task support was added. Treat as still coding-workflow-
only pending direct testing.

## Bottom line

Gas City fixes the most acute Gas Town dealbreakers on paper: no forced clone-into-`~/gt/`
prison (`gc rig add <path>` works in place), Dolt is genuinely optional (`GC_BEADS=file`), and
there's no more "two towns" scenario since multiple repos are rigs under one town. Contributor
concentration and AI-authored-commit rate are both markedly better than Gas Town.

But: tmux is still a hard dependency (herdr is an optional alternative pane backend, not a
tmux-removal), idle-token/idle-daemon burn is an **open, unresolved** issue class as of v1.4.0
(not "reportedly fixed" — actively being worked on), state is still centralized in one shared
city/Dolt-or-file store with real ongoing races (#1920, #3341), Codex support looks real but the
project's own parity-audit issue suggests it's behind Claude Code, and non-code task support is
unconfirmed/likely still absent. Bus factor remains thin (one person ≈ 60-67% of all activity).
