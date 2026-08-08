# 02 — Multi-agent coding orchestrators & agent-management harnesses (2026 landscape)

Research date: **2026-08-06**. Sources are linked inline.

---

## 0. Executive summary — read this first

**The space is enormous and far more mature than the braindump assumes.** There is a public
directory ([yetanotherorchestrator.app](https://yetanotherorchestrator.app/)) listing **48+ shipping
products** in the "run parallel coding agents" category alone, and a curated awesome-list
([andyrewlee/awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators))
with **~200 projects** across seven categories. Several have 5k–75k GitHub stars. Most are 3–12
months old and functionally identical (worktree + kanban + diff review). This is a crowded,
fast-moving, largely commoditised market that has *already* started dying back.

**The headline finding on our four differentiators:**

| Differentiator | Already exists? | Where |
|---|---|---|
| Nestable controllers (main → sub-controller → leaf) | **Yes, several times** | Firstmate (secondmates), fractal, Gas Town (Mayor→Deacon→Witness→polecats), multi-agent-shogun, agent-runbook |
| Human talks **directly** to any leaf agent | **Yes — including natively in Claude Code** | **Claude Code Agent Teams** (documented: *"interact with individual teammates directly without going through the lead"*), GraphCode (`graphcode node send`), hcom (`hcom send -b @luna`), ClawTeam (`clawteam inbox send`), Fusion (direct chat + @mention rooms), 5dive (per-agent Telegram topic), AO (attach to worker terminal), Gas Town, AG2 v1 (`HumanClient` as network peer) |
| Controller reads **structured state, not transcripts** | **Yes, and better than we planned** | bernstein (zero LLM in the loop), AO (OBSERVE→durable facts→DERIVE), OpenHands (`TaskObservation`, transcript to disk never to parent), Firstmate ("zero-token supervision"), Claude Code Agent Teams (lead sees mailbox + task list, not teammate transcripts), Gas Town (beads ledger + `.events.jsonl`), herdr (5-state agent model over socket API) |
| Declarative JSON/YAML templates w/ repeatable steps + human gates | **Yes** | agent-runbook (YAML: loop/branch/parallel/checkpoint/quality_check), bernstein (YAML DAG), tutti (TOML w/ nested `workflow` steps), Fusion (workflow stages + gate policies), Gas Town ("molecules"/TOML formulas), kandev (portable YAML) |

**Brutal version: every single one of our four differentiators already exists in shipped software,
and two of them are free built-in features of Claude Code itself.**

Three findings that should change the plan:

1. **Claude Code Agent Teams** (experimental, env-var-gated) already gives you *"interact with
   individual teammates directly without going through the lead"* — the docs' own words — with the
   lead seeing only a mailbox and a shared task list, never teammate transcripts. That is
   differentiators #2 and #3, native, free, today. See §5c.
2. **The premise of principle #3 is factually wrong.** The braindump says existing orchestrators
   funnel all human interaction through a single root. Of ~13 tools examined closely, **all 13
   preserve direct human→sub-agent addressing.** Firstmate is the outlier we generalised from.
3. **Gas Town** (MIT, Go, 17.5k★) already ships nesting + structured state + TOML workflow templates
   + direct agent attach + a bisecting merge queue. It is the closest existing thing to the whole
   product.

4. **Nesting is being clamped industry-wide, not expanded.** Gemini CLI 0 (explicit recursion
   protection), Factory 0, Claude Code agent teams 0, Codex V1 1, Cursor 2 (hard cap), Claude Code
   subagents 3 — after oscillating 5 → 0 → 3 across four releases in 2026. And **OpenAI now blocks
   direct human input to subagents in code** (Codex multi-agent V2). Two of our differentiators are
   moving *against* the industry consensus. That may be right — but it needs an argument, not an
   assumption.

Two more things to weigh: the category has **already had a consolidation wave** (Vibe Kanban, at
27.7k stars, shut down in April 2026 for lack of a business model; Crystal, Terragon, uzi and
container-use are all dead or dormant), and **GitHub Agent HQ** is turning multi-backend fan-out
plus a status board into a free-at-the-margin Copilot feature across Claude, Codex, Jules,
Cognition and xAI.

What genuinely remains unclaimed: **reconciliation semantics for out-of-band human intervention**,
**human-owned blocking steps as a template primitive**, and **a rendered capability graph**. See §6.

---

## 0b. Master comparison table

Legend — **Human→leaf**: can a person address an individual leaf agent directly? **Observes**:
how the controller learns agent state. **Templates**: declarative workflow files.

| Tool | OSS / License | Lang | ★ | Orchestration model | Nest | Human→leaf | Observes | Backends | Templates | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **Firstmate** | MIT | Bash/MD | 3.0k | Hierarchy: captain→FM→secondmate→crew | ✅ | ❌ **forbidden** | State files, wake events, zero-token watcher | CC, Codex, Grok, Pi, OpenCode | ❌ prose briefs | **Borrow ideas** |
| **AgentOrchestrator (AO)** | Apache-2.0 | Go+TS | 8.8k | Flat parallel + 1 planner agent | ❌ | ✅ terminal attach | ✅✅ OBSERVE→durable facts→DERIVE, SQLite CDC | 23 adapters | ❌ | **Fork the state layer** |
| **Gas Town** | MIT | Go | 17.5k | 4-tier: Mayor→Deacon/Witness→polecat + **bisecting merge queue** | ✅✅ | ✅ `nudge`/`sling`/`seance --talk` | **Beads ledger in Dolt** (versioned SQL) + `.events.jsonl` + stall analysis | CC, Codex, Copilot, Gemini, Cursor, Kiro | ✅ TOML Formulas + `needs` DAG | **Best fork candidate** |
| **Claude Code Agent Teams** | proprietary | — | — | Lead + N full sessions, shared task list | ❌ | ✅✅ native | Mailbox JSON + task list; **no transcripts** | Claude only | ⚠️ subagent `.md` + plan gates | **Use it first** |
| **bernstein** | Apache-2.0 | Python | 797 | Deterministic DAG, **no LLM in loop** | ❌ | ⚠️ TUI | ✅✅ objective gates: tests/lint/types/git | 40+ | ✅ YAML DAG + loops | **Study closely** |
| **agent-runbook** | Apache-2.0 | Python | 17 | YAML runbook → SKILL.md | ⚠️ | ❌ | Files, not context; JSON-Schema outputs | CC, Codex | ✅✅ **best schema** | **Borrow schema** |
| **Sculptor (Imbue)** | MIT | — | 213 | Workflow stages as named agents | ✅ | ✅ tabs | ✅✅ **CC control protocol / streaming JSON; Pi RPC** | CC, Pi | ✅ 6-stage, durable artifacts | **Underrated — study** |
| **tutti** | MIT | Rust | 110 | TOML workflow, typed artifacts | ✅ `workflow` step | ⚠️ focus mode | SSE stream + telemetry JSONL | CC, Codex, Aider, OpenClaw | ✅ TOML | **Borrow** |
| **GraphCode** | FSL→MIT | Swift | 11 | **Graph**: handoff/message/spawn edges | ✅ | ✅✅ `node send` | Session exit + shell predicates | CC, Codex, Copilot | ❌ | **Only graph impl** |
| **hcom** | MIT | Rust | 420 | Messaging bus, no hierarchy | ⚠️ spawn | ✅✅ `@name`/`@tag` | SQLite hooks + event log | CC, Codex, Cursor, OpenCode, Gemini | ❌ | **Borrow / depend** |
| **fractal** | Apache-2.0 | Python | 678 | Recursive delegation, `max-depth` | ✅✅ | ✅ CLI any node | SQLite run metadata (cost/steps/signals) | CC, Codex, Grok, OpenCode | ⚠️ 30+ params | **Borrow nesting** |
| **ClawTeam** | MIT | Python | 5.5k | Leader spawns workers | ⚠️ 2 levels | ✅ `inbox send` | Task board + inbox | CC, Codex, OpenClaw, Kimi | ✅ TOML teams | Borrow |
| **Fusion** | MIT | TS | 1.1k | Stages + gates, multi-node | ⚠️ | ✅✅ chat + @rooms | Mixed | 440+ agents | ✅ stages + gate policies | **Borrow oversight levels** |
| **ORCH** | MIT | TS | 132 | State machine + departments | ⚠️ | ✅ DM/broadcast | `.orchestry/` YAML+JSON+JSONL | — | ✅ org templates | Borrow |
| **5dive** | MIT | TS/bash | 38 | Declarative org chart | ⚠️ | ✅✅ Telegram topic/agent | SQLite queue + journald | Claude | ✅ `5dive.yaml` | **Borrow UX** |
| **kandev** | AGPL-3.0 | Go+TS | 551 | Per-step agent binding | ⚠️ | ✅ | Session review | 22+ via **ACP** | ✅ portable YAML | Borrow |
| **Ivy-Tendril** | FSL-1.1 | C# | 170 | Plan lifecycle + verification gates | ⚠️ | ✅ PTY chat | Build/test/lint checks | CC, Copilot, Gemini | ⚠️ Markdown plans | Borrow gates |
| **Vibe Kanban** | Apache-2.0 | Rust | 27.7k | **MCP recursive spawn** | ✅✅ | ✅ | Normalised executor streams, typed enums | 10+ | ⚠️ issues+relations | **DEAD — read code** |
| **Conductor** | closed | — | — | Parallel sessions (+cloud API) | ⚠️ cloud only | ✅ | Polling, status enums, `POST /v0/sql` | CC, Codex, Cursor, **acp** | ❌ (TOML config only) | Borrow API spec |
| **Claude Squad** | AGPL-3.0 | Go | 8.2k | None — session manager | ❌ | ✅ attach | tmux + git | CC, Codex, Gemini, Aider | ❌ | Baseline |
| **awslabs/cli-agent-orchestrator** | Apache-2.0 | Python | 1.0k | Supervisor→specialist over tmux | ❌ | ✅ tmux attach | Profiles + web UI | 9+ CLIs | ⚠️ flows/profiles | Borrow |
| **OpenHands** | MIT | Python | 83.3k | Control center; Task/Delegate tools | ✅ | ⚠️ resume by id | ✅✅ `TaskObservation`, transcript→disk | **any ACP agent** | ✅ `.md`+YAML, skills | **Evaluate seriously** |
| **guild** | Apache-2.0 | Go | 309 | None — memory/task substrate | ❌ | ❌ | SQLite | MCP (any) | ❌ | **Use, don't rebuild** |
| **herdr** | Apache-2.0 | Rust | 25.1k | None — imperative runtime substrate | ✅✅ env-var context injection | ✅ `agent attach --takeover` | ✅✅ status enum + `agent wait --until` + 4 read planes + events | **21 kinds** | ❌ **config only, no workflow** | **Substrate** |
| **sandbox-agent** | Apache-2.0 | Rust | 1.5k | None — API substrate | n/a | ✅ API | ✅✅ Universal Session Schema (JSON events) | CC, Codex, OpenCode, Cursor, Amp, Pi | n/a | **Alt substrate** |
| **OpenAI Symphony** | Apache-2.0 | Elixir ref | 26.5k | Scheduler + tracker reader (flat) | ❌ | ⚠️ | Structured logs, claims, run-attempt phases, CI/PR proof-of-work | Codex | ✅ `WORKFLOW.md` YAML front matter + hooks | **Read the SPEC** |
| **gh-aw** | MIT | Go | 4.9k | Markdown → GH Actions | ❌ | ❌ | Actions run state | Copilot, CC, Codex, Gemini | ✅ Markdown+YAML | Niche |
| **GitHub Agent HQ** | closed, in Copilot sub | — | — | Mission control fan-out | ❌ | ⚠️ via PR/branch | PR/CI/branch state, first-line self-review | **Claude, Codex, Jules, Cognition, xAI** | ✅ `AGENTS.md` custom agents | **Platform risk** |
| **Sourcegraph Amp** | closed, $5+ credits | — | — | Main agent + subagents + oracle | ❌ **proxy only** | Final summary only (good hygiene) | GPT-5.6, Claude Fable 5 | ✅ `AGENTS.md` + YAML skills | Counter-example |

---

## 1. The two you named

### 1.1 Firstmate — [kunchenguid/firstmate](https://github.com/kunchenguid/firstmate)

**What it is (honest sentence):** An "agent distro" — a checked-out directory of Markdown
instructions, bash scripts and state-file conventions that turns *one* general-purpose coding agent
into a fleet supervisor. Not an app, not a binary, not an MCP server.

| | |
|---|---|
| Open source | Yes, **MIT** |
| Language | Bash + Markdown (no compiled runtime) |
| Stars / maturity | ~3.0k stars, 955 forks; very active |
| Backends | Harnesses: **Claude Code, Grok, Pi (co-primary), Codex, OpenCode**. Session backends: tmux (reference), **herdr**, zellij, Orca, cmux |
| Orchestration model | Strict hierarchy: **Captain (human) → Firstmate → Crewmates**, plus optional **Secondmates** (persistent sub-supervisors with their own `FM_HOME`, on this machine or over SSH) |
| Human → leaf directly? | **Explicitly forbidden by design.** Prime Directive #4: *"Crewmates never address the captain."* All communication is filtered through the firstmate. |
| Observation mechanism | **State files, not transcripts.** `state/<id>.status` (append-only wake events), `state/<id>.meta` (window, worktree, harness, model, `pr=`). A bash watcher `bin/fm-watch.sh` sleeps on the fleet and wakes the firstmate only on `signal:`/`stale:`/`check:`/`heartbeat:` events. Marketed as **"event-driven, zero-token supervision."** |
| Declarative templates | **No step-execution engine.** `bin/fm-brief.sh` generates task *briefs* (prose scaffolds). Durable knowledge lives in **Markdown**: `data/backlog.md`, `data/learnings.md`, `data/captain.md`, `data/projects.md`. Only `config/crew-dispatch.json` is structured — and its `when` conditions are *natural-language strings* an LLM evaluates. |
| Nesting | **Yes** — secondmates are real sub-controllers with isolated homes and their own backlogs. Depth is effectively 3 (captain → firstmate → secondmate → crewmate). |
| Task lifecycle | Two shapes. **Ship**: dispatched → under way → validation active → PR ready → landed → done. **Scout**: dispatched → under way → report complete → done (promotable to ship via `bin/fm-promote.sh`). Project modes: `no-mistakes` / `direct-PR` / `local-only`, with `+yolo`. |

**The one nuance that matters to us:** the docs say *"Direct captain intervention in crewmate windows
is treated as authoritative but reconciled at the next supervision review."* So typing into a
crewmate's tmux window **is** possible and Firstmate has a reconciliation story for it — it is just
not a first-class, addressable channel. This is a direct answer to the braindump's open question
*"how do you attach to a leaf agent mid-run without corrupting the orchestrator's model?"*

**Verdict: BORROW HEAVILY, DON'T FORK.** Firstmate is the single best prior art for "low-context
controller" and the closest thing to our thesis. But it is the *anti-pattern* for two of our
principles: (a) all human interaction is funnelled through the root — the opposite of principle #3;
(b) its durable state is **Markdown prose** (`learnings.md`, `backlog.md`) — the exact thing
principle #2 rejects. Its architecture is also bash-in-a-directory, so there is nothing to fork
structurally; you borrow the *ideas*: the status/meta split, the wake-event taxonomy, the
ship-vs-scout lifecycle, the reconciliation rule for human intervention.

Further reading: [DeepWiki](https://deepwiki.com/kunchenguid/firstmate),
[AGENTS.md](https://github.com/kunchenguid/firstmate/blob/main/AGENTS.md),
[configuration.md](https://github.com/kunchenguid/firstmate/blob/main/docs/configuration.md),
and a practitioner writeup: [SudoAll](https://sudoall.com/talk-to-one-agent-first-mate-agentic-stack/).

---

### 1.2 AgentOrchestrator (AO) — [AgentWrapper/agent-orchestrator](https://github.com/AgentWrapper/agent-orchestrator) · [aoagents.dev](https://aoagents.dev/)

**What it is (honest sentence):** A "meta-harness agent IDE" — an Electron desktop app plus a
long-running **Go daemon** that supervises many parallel coding-agent sessions, each in its own
worktree/branch/PR, and auto-routes CI failures, merge conflicts and review comments back to the
session that owns the branch.

> Note: the repo moved `ComposioHQ/agent-orchestrator` → `Untrivial-ai/…` → `AgentWrapper/…` during
> 2026. All three URLs resolve to the same project.

| | |
|---|---|
| Open source | Yes, **Apache-2.0** |
| Language | Go daemon + TypeScript/Electron frontend |
| Stars / maturity | **~8.8k stars**, 2,077+ commits, nightly releases as of June 2026. Most mature OSS thing in this space. |
| Backends | **23 worker adapters** — Claude Code, Codex, Cursor, Aider, OpenCode, Grok, Copilot, Devin, Cline, KimiCode… plus separate *reviewer* harnesses (Claude Code, Codex, OpenCode) |
| Orchestration model | One "main orchestrator agent" per project that plans, spawns workers into worktrees, and **escalates only what needs a human**. Fundamentally **flat parallel**, not nested. |
| Human → leaf directly? | **Yes.** "Live terminal control" — attach to the worker terminal while keeping session summary, PR state and follow-up actions in view. Agents keep their native interfaces. |
| Observation mechanism | **The best-engineered state model I found.** Three-stage pipeline: **OBSERVE** external facts → **UPDATE** durable facts → **DERIVE** display status. *"Display status is never stored. It is computed at read time from durable facts."* Durable facts include `activity_state` (active / idle / waiting_input / blocked / exited), `is_terminated`, `session_mode`, PR facts. Two observer loops: **SCM Observer** (30s poll of PRs/CI/review threads) and **Runtime Reaper** (5s liveness probe; *"failed probes are NOT proof of death"*). All writes hit SQLite; DB triggers append to a `change_log`; a CDC poller broadcasts to SSE subscribers. |
| Declarative templates | **No.** No workflow/template DSL. Config is env-based + per-project settings. This is its biggest gap. |
| Nesting | **No.** README explicitly emphasises parallel, non-mixing sessions rather than nested orchestration. |
| Notable architecture | Strict **ports-and-adapters**: "core code never depends on concrete implementations"; adapters for agent harness / runtime / workspace / SCM implement ports and never import core. Also a **TUI-vs-Chat controller duality** — a session has exactly one live controller (terminal multiplexer *or* native protocol), with durable handoff between them. |

**Verdict: FORK-CANDIDATE FOR THE STATE LAYER; BORROW THE ARCHITECTURE.** AO has already solved,
properly, the hardest unglamorous part of our design — a durable, derived, event-sourced session
state model that a controller can read cheaply. The OBSERVE/UPDATE/DERIVE split and "status is
computed, never stored" is exactly the discipline principle #2 needs. Apache-2.0 makes it forkable.
What it lacks is precisely our product: **nesting, templates, and a topology graph**.

Docs: [architecture.md](https://github.com/AgentWrapper/agent-orchestrator/blob/main/docs/architecture.md)

---

## 2. The projects that hit our differentiators head-on

These are the ones that make specific parts of the braindump non-novel. Read this section carefully.

### 2.1 bernstein — [sipyourdrink-ltd/bernstein](https://github.com/sipyourdrink-ltd/bernstein) · bernstein.run

**Kills our "minimal-context controller" claim.** Apache-2.0, Python, ~797 stars, solo maintainer.

- **Zero LLM in the coordination loop.** One LLM call decomposes the goal into tasks; **everything
  after that is plain Python scheduling**. *"Scheduling is plain Python, so a run is reproducible
  end to end."* Our braindump's open question — "is the controller an LLM agent or a deterministic
  scheduler that escalates to an LLM only on ambiguity?" — bernstein has already answered
  "deterministic," and shipped it.
- **Observes objective gates only**: tests pass/fail, file existence, lint, typecheck, git worktree
  status. Never reads transcripts.
- **Declarative YAML DAG** with `agent`, `command` and `loop` node types. `bernstein run plan.yaml`
  skips LLM planning entirely.
- **40+ CLI agent adapters** (Claude Code, Codex, Gemini CLI, Cursor, Aider…) plus a generic
  `--prompt` wrapper.
- TUI (`bernstein live`) and browser dashboard (`bernstein gui serve`) both read the same task API.
- Has a "Janitor" that runs lint/typecheck/tests before merge.

**Verdict: BORROW / STUDY CLOSELY.** This is the purest expression of "controller consumes minimal
context." Weaknesses vs. us: no nesting story, no human-owned gate steps, no direct human→leaf
addressing, and a DAG (not a repeatable step sequence with human blocks).

### 2.2 agent-runbook — [KnoxOps/agent-runbook](https://github.com/KnoxOps/agent-runbook)

**Kills our "declarative template" claim.** Apache-2.0, Python 3.10+, ~17 stars (tiny, but the
design is exactly ours).

Compiles **YAML runbooks → SKILL.md** for Claude Code and Codex. Step types:

| Step type | Meaning |
|---|---|
| `inline` | Orchestration prompt run by the current agent |
| `agent` | Dispatch an independent sub-agent |
| `script` | Shell/Python |
| `parallel` | Concurrent agents, configurable instance count |
| `branch` | Conditional on step output |
| `loop` | **Iterate until goal met or max_iterations** ← our "↻ repeat" |
| `checkpoint` | Persist progress for pause/resume |
| `quality_check` | **Auto-generated supervisor gate that blocks** ← our human-owned step |

Steps declare typed outputs with **JSON Schema** files, and contract closure is validated at *build
time* — every input schema, dependency and output requirement verified before compilation. The
project's own framing is "loop engineering… all persisted via **files rather than LLM context**."

**Verdict: BORROW THE SCHEMA WHOLESALE.** This is our template system, already designed, with a
better idea than we had (build-time contract validation + JSON-Schema-typed step outputs). It is
immature and has no runtime/UI — which is where we'd add value.

### 2.3 GraphCode — [scgopi/GraphCode](https://github.com/scgopi/GraphCode)

**Kills our "graph view + talk to any node" claim.** FSL-1.1-MIT (→ MIT after 2 years),
Swift/SwiftUI, macOS-only, **only 11 stars** but 333 commits.

- Renders a **live graph** where each node is a real CLI coding-agent session and **each edge is a
  hand-off, message, or spawn**. That is literally braindump §2.
- Three edge semantics: **hand-off** (fires when source resolves), **message** (direct input into
  another loop's session), **spawn** (conditional trigger with cycle guards).
- **`graphcode node send`** — the human can message any node directly from the CLI, or attach to the
  live session and type. That is literally braindump principle #3.
- Daemon fires hand-off edges and polls goal predicates; a loop resolves when its session exits or a
  shell predicate exits 0. Persists across reboots via `zmx`.
- Backends: Claude Code (primary), Copilot CLI, Codex.

**Verdict: THE MOST DIRECT CONCEPTUAL COMPETITOR, AND IT IS TINY.** Nobody has adopted it (11
stars), it is macOS/Swift-only, and it has no template layer. This is the clearest evidence that our
graph+direct-addressing idea is (a) not novel and (b) not yet executed well enough to matter.

### 2.4 Gas Town — [gastownhall/gastown](https://github.com/gastownhall/gastown)

**The most complete implementation of "everything we want" that already exists.** MIT, Go,
**~17.5k stars**.

- **Four-tier hierarchy**: *Mayor* (AI coordinator with full workspace context) → *Deacon*
  (cross-rig supervisor, continuous patrol) → *Witness* (per-rig lifecycle manager) → *polecats*
  (worker agents), plus *Dogs* (infra workers). This is a real nested controller tree.
- **Structured state, not transcripts**: a git-backed **"beads" ledger** of issue/work state,
  `.events.jsonl` session logs, worktree "Hooks" that survive crashes, a `gt feed` TUI with agent
  tree / convoy panel / event stream, and a **Problems view** that surfaces stuck agents via stall
  analysis and "GUPP violation" detection.
- **Declarative templates**: "**Molecules**" are workflow templates defined as **TOML formulas** for
  multi-step coordination; "**Convoys**" bundle work items with autonomous stall detection.
- **Direct human→agent**: yes — crew workspaces, and `gt mayor start --agent auggie` attaches to a
  specific agent session.
- **Bors-style merge queue** ("the Refinery"): a **bisecting** merge queue that batches MRs, runs
  gates, and isolates failures. Polecats never push to main. **Nobody else in this survey has this.**
- **Direct addressing, four ways**: `gt nudge` (real-time inter-agent message), `gt sling` (place
  work on an agent's Hook), **`gt seance --talk <id>`** (one-shot question to a *predecessor
  session* — i.e. you can interrogate a dead agent's context), plus tmux attach / `claude --resume`.
- **Beads** are "git-backed atomic work units stored in **Dolt**" (versioned SQL) — a queryable,
  version-controlled work ledger. That is principle #2 taken further than we proposed.
- Polecats have **persistent identity but ephemeral sessions**, each in its own worktree — a useful
  decomposition (the *agent* is durable; the *session* is disposable).
- Runtimes: Claude, Copilot, Codex, Gemini, Cursor, Kiro. Real project structure (`cmd/`, `docs/`,
  Dockerfile, goreleaser, Nix flake). Last push 2026-08-05.

**Verdict: THIS IS THE BIGGEST THREAT TO THE PROJECT'S NOVELTY, AND THE BEST FORK CANDIDATE.**
Nesting ✅, structured state ✅, TOML templates ✅, direct agent addressing ✅, MIT ✅, Go ✅,
17.5k stars ✅. The things it does *not* have: a rendered communication **graph** (it has an agent
*tree*), human-owned blocking steps as a first-class template primitive, and a tool-based
plugin/learnings layer. Read this repo before writing any code.

### 2.5 Fusion — [Runfusion/Fusion](https://github.com/Runfusion/Fusion)

MIT, TypeScript/Node + PostgreSQL + React, ~1.1k stars, "early preview, shipping weekly."

Hits an uncomfortable number of our boxes simultaneously:
- **Declarative workflow system**: customisable stages Planning → Triage → Execution → Review →
  Merge, with **gate policies** (human *or* AI validation), per-step review cycles, step sequencing.
- **Planner oversight levels**: `off` / `observe` / `steer` / `autonomous` — i.e. **the controller's
  policy is user-configurable**, which is braindump principle #4.
- **Direct chat with individual agents** plus task chat; **inter-agent mailbox**; experimental
  **Chat Rooms where @mentioned agents respond directly**. That is principle #3 *and* the
  "who-can-talk-to-whom" edge semantics.
- Multi-node, kanban board, plugin authoring framework, 440+ pre-built agents.
- All destructive actions and merges require explicit human confirmation regardless of oversight.

**Verdict: BORROW THE OVERSIGHT-LEVEL CONCEPT.** `off/observe/steer/autonomous` is a cleaner
articulation of "customizable controller" than the braindump has.

### 2.6 tutti — [nutthouse/tutti](https://github.com/nutthouse/tutti)

MIT, **Rust**, ~110 stars, v0.10.0 (May 2026). Config-driven "org code" in **`tutti.toml`**.

- Step types: `prompt`, `command`, `ensure_running`, **`workflow` (nested sub-workflow calls)**,
  `review`, `land`. Dependencies via `depends_on = [step_numbers]`.
- **Typed artifact pipeline**: steps capture outputs via `artifact_glob`/`artifact_name`; downstream
  steps consume via `inject_files = ["{{output.artifact_name.path}}"]`; artifacts are copied into
  the target agent's worktree before execution.
- Checkpoints at `.tutti/state/workflow-checkpoints/`, resume via `tt run --resume <run_id>`.
- **Merge gates** on `land` steps (GitHub required checks + resolved review threads).
- Observation: SSE event stream `/v1/events/stream`, per-agent terminal logs, token stats,
  telemetry to `.tutti/state/run-telemetry.jsonl`, "Agent Focus Mode" with live output + git diffs.
- Backends: Claude Code, Codex CLI, Aider, OpenClaw + a direct ModelProvider spine.

**Verdict: BORROW.** `workflow`-as-a-step-type is exactly our nestable-template primitive, and typed
artifacts passed between steps is a better answer than "agents share a markdown file."

### 2.7 hcom — [aannoo/hcom](https://github.com/aannoo/hcom)

MIT, **Rust**, ~420 stars, single binary, no background services.

Pure inter-agent messaging substrate: `agent → hooks → db → hooks → other agent`, backed by local
SQLite. Messages arrive mid-turn (between tool calls) or wake idle agents. **Collision detection**
alerts both agents if they edit the same file within 30s. Agents have queryable identities (name,
status, inbox, transcript, event log of file edits and tool calls); groups are tagged so you can
address `@tag`. Cross-device via MQTT relay with E2E encryption.

**The human addresses any agent directly: `hcom send -b @luna -- hey`.**

Backends: Claude Code, Codex, Cursor, OpenCode, Gemini and others.

**Verdict: STRONG BORROW / POSSIBLE DEPENDENCY.** This is the "edge in the graph physically means a
message-passing tool" answer, already built, in Rust, MIT, and backend-agnostic.

### 2.8 fractal — [plasma-ai/fractal](https://github.com/plasma-ai/fractal)

Apache-2.0, Python, ~678 stars. **Recursive delegation** — parent nodes spawn children into separate
git worktrees via a `/fractal` skill, with a `max-depth` parameter capping nesting. Parents observe
children through **run metadata in a single local SQLite DB** (runs, iters, steps, costs, signals),
surfaced in a TUI dashboard — not transcripts. **The `fractal` CLI manages any node independently of
parent-child relationships, so an operator can steer or stop a nested child directly.** 30+ declarative
parameters. Backends: Claude Code, Codex, Grok Build, OpenCode, Oh My Pi.

**Verdict: BORROW THE NESTING MODEL.** Nesting + direct-child-addressing + SQLite-metadata
supervision, all three at once.

### 2.9 ClawTeam — [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)

MIT, Python, **~5.5k stars**. Leader agents call `clawteam spawn` to create workers, each with its own
git worktree, tmux window and identity, auto-injected with a coordination protocol
(`clawteam task list` / `task update` / `inbox send`). **Teams are declared in TOML templates**
(roles, tasks, prompts); `clawteam launch <template>` starts a whole team. Humans address any
teammate directly: `clawteam inbox send <team> <agent-name> "message"`. Views: terminal kanban,
`board live`, tiled tmux `board attach`, web `board serve`. Two levels only (leader → workers).
File-based or ZeroMQ transport. Backends: Claude Code, Codex, OpenClaw, nanobot, Kimi CLI.

### 2.10 ORCH — [oxgeneral/ORCH](https://github.com/oxgeneral/ORCH)

MIT, TypeScript, ~132 stars. Explicit state machine `todo → in_progress → review → done`, every
transition validated. Typed "departments" (CTO / Engineering / QA / Code Review). **All state in
`.orchestry/` as plain YAML, JSON, JSONL** — no cloud. Agents observed via status transitions and
structured JSON event logs, not transcripts. Direct messages and team broadcasts supported.
Templates: `orch org deploy startup-mvp --goal "…"`.

### 2.11 5dive — [5dive-ai/5dive](https://github.com/5dive-ai/5dive)

MIT, TypeScript/bash, ~38 stars. A **declarative `5dive.yaml`** defines agents, roles and team
structure; `5dive up` provisions; `5dive org set` defines **who reports to whom**; `5dive ui` renders
the org chart with live handoffs. **Every agent gets its own Telegram forum topic**, so the human
messages any agent directly from a phone. Agents **park tasks at human gates** and push tap-to-answer
notifications; `5dive task inbox` is the human's queue. State: SQLite task queue + journald.

**Verdict on the Telegram-topic-per-agent trick: steal it.** It is the cheapest possible
implementation of "human is a peer node addressable to any agent."

### 2.12 kandev — [kdlbs/kandev](https://github.com/kdlbs/kandev)

AGPL-3.0, Go + TypeScript/React, ~551 stars, [kandev.ai](https://kandev.ai). "Agentic workflows" =
**multi-step pipelines that mix-and-match a different agent per step** (e.g. Claude Opus plans →
Copilot Sonnet implements → Codex reviews), **exported/imported as portable YAML**. 22+ agents via
the **Agent Client Protocol (ACP)**. Execution backends: local process, Docker, SSH remote, cloud.
Embedded VSCode, LSP, git panel. Review-first philosophy.

**Verdict: closest thing to our "template binds a specific agent+skill per step", and it's on ACP.**

### 2.13 OpenAI Symphony — [openai/symphony](https://github.com/openai/symphony)

Apache-2.0, **26.5k stars**, Elixir *reference* implementation, "low-key engineering preview for
testing in trusted environments." OpenAI's own orchestrator: turns tracker issues into **isolated,
autonomous implementation runs** so teams "manage work instead of supervising coding agents."

**Read [`SPEC.md`](https://github.com/openai/symphony/blob/main/SPEC.md) — it is spec-first and
language-agnostic, and its state model is directly reusable:**

- **Entities**: *Issue* (normalised schedulable work item with opaque dispatch `id`, tracker-native
  `state`, priority, labels, explicit `dispatchable` flag), *Workspace* (per-issue isolated dir),
  *Run Attempt* (attempt number, workspace path, terminal reason), *Live Session* (subprocess
  metadata, `session_id`, token counters, event timestamps), *Retry Entry* (attempt count,
  exponential-backoff due time, error context).
- **Issue orchestration states** — deliberately distinct from tracker states:
  `Unclaimed → Claimed (Running | RetryQueued) → Released`.
- **Run attempt phases**: `PreparingWorkspace → BuildingPrompt → LaunchingAgentProcess →
  InitializingSession → StreamingTurn → Finishing → (Succeeded | Failed | TimedOut | Stalled |
  CanceledByReconciliation)`. Note `Stalled` and `CanceledByReconciliation` — they thought about
  the failure modes.
- **Declarative config: `WORKFLOW.md`** — a repo-owned Markdown file with YAML front matter defining
  `tracker` (adapter kind, auth scope, required labels, active/terminal states), `polling` interval
  (dynamically reloaded), `workspace` root, **`hooks`** (`after_create`, `before_run`, `after_run`,
  `before_remove`, with timeouts), `agent` (concurrency limits, max turns, retry backoff cap,
  per-state limits), and `codex` (command, approval/sandbox policy, turn/read/stall timeouts). The
  Markdown body after the front matter is the **prompt template**, rendered with strict Liquid using
  `issue` and `attempt` variables.
- **Observation**: structured logs keyed by `issue_id`/`issue_identifier`/`session_id`, aggregate
  token + runtime metrics, an optional snapshot API and per-issue detail endpoint (workspace path,
  attempt history, recent events). Proof-of-work from **CI status, PR review feedback, complexity
  analysis, walkthrough videos**.
- **Human gates**: deliberately **implementation-defined** — "implementations are expected to
  document their trust and safety posture explicitly", ranging from auto-approve in trusted
  environments to strict operator gatekeeping. The one hard rule: unsupported tool calls and
  user-input-required signals **must not leave runs indefinitely stalled**.
- **Nesting: none.** Layered but flat — Policy → Configuration → Coordination → Execution →
  Integration → Observability. Explicitly *"a scheduler and tracker reader, not a workflow engine."*

**Verdict: READ THE SPEC, DON'T USE THE IMPLEMENTATION.** Its lifecycle state machine and the
`WORKFLOW.md` front-matter schema are the most carefully specified in this entire survey, and it is
Apache-2.0 prose you can lift. Its deliberate refusal to be a workflow engine is also a useful
warning about scope.

### 2.14 Others worth a line each

| Tool | Why it matters |
|---|---|
| [Ivy-Tendril](https://github.com/Ivy-Interactive/Ivy-Tendril) (FSL-1.1-ALv2, C#, ~170★) | **Markdown plans with verification gates** — "plans only advance when all checks pass"; plan state versioning; **"Chat with Agent (PTY)"** = direct human→leaf |
| [ruflo](https://github.com/ruvnet/ruflo) (MIT, TS+Rust, **~67.2k★**) | Queen-led / mesh / hierarchical / gossip swarm topologies, reusable multi-step workflow templates, GOAP planner. Enormous star count, heavy hype-to-substance ratio |
| [paperclip](https://github.com/paperclipai/paperclip) (MIT, TS, **~75.8k★**) | Heartbeat/wake queue model — agents wake to claim tickets from a DB-backed queue with atomic checkout + execution locks + budget enforcement. "If OpenClaw is an employee, Paperclip is the company." |
| [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator) (Apache-2.0, Python, ~1.0k★) | AWS Labs. Hierarchical supervisor→specialist over isolated tmux; **you can attach to any agent's tmux window**; agent *profiles*, *skills*, and "flows/workflows" for scheduled multi-step pipelines; 9+ provider CLIs |
| [guild](https://github.com/mathomhaus/guild) (Apache-2.0, Go, ~309★) | **Our "learnings plugin", already built.** MCP tools over embedded SQLite: *Quest* (tasks w/ deps + atomic claims), *Lore* (typed knowledge: observation/decision/research/principle/idea), *Oath* (auto-loaded principles), *Brief* (session handoffs). Hybrid BM25 + vector retrieval. |
| [kodo](https://github.com/ikamensh/kodo) (MIT, Python, ~126★) | Cheap orchestrator model (Gemini Flash) directing expensive workers; independent architect + tester agents verify before accept |
| [Agent Teams](https://github.com/777genius/agent-teams-ai) (AGPL-3.0, Electron, ~1.9k★) | Peer-to-peer teammate messaging *not* routed through a lead; **"send a direct message to any agent"**; departments/squads/nested groups; per-teammate activity logs, CPU/RAM, token cost |
| [shire](https://github.com/victor36max/shire) (MIT, TS/Bun, ~37★) | Agents "discover peers and collaborate on their own — no orchestrator required"; shared drive; dashboard chat with any agent |
| [Traycer](https://github.com/traycerai/traycer) (MIT, ~1.1k★) | BYO-subscription desktop workspace, agent-to-agent comms, model switching mid-agent |
| [Ouijit](https://github.com/ouijit/ouijit) (AGPL-3.0, Electron/TS, ~141★) | Kanban + per-task terminal wired by **lifecycle hooks** (`ouijit hook`); **all CLI output is JSON for piping to jq** |
| [amux](https://github.com/andyrewlee/amux) (MIT, Go, ~144★) | `.amux/workspaces.json` declares setup/run/archive commands per workspace; gates untrusted repo scripts until approved |
| [codecast](https://github.com/codecast-sh/codecast) (MIT, TS/Bun, ~15★) | **Reads agents' own transcript files** (`~/.claude/projects/**/*.jsonl`, `~/.codex/sessions/**/*.jsonl`, OpenCode SQLite, Cursor SQLite) via chokidar and derives a triage inbox: Pinned → Working → Needs Input → Idle → Deferred. Useful reference for "how to derive state when the agent won't report it" |
| [skillfold](https://github.com/byronxlg/skillfold) (MIT, TS, ~11★) | `skillfold.yaml` + `skillfold.lock` — skills as pinned dependencies with sha256, composable into one SKILL.md. Relevant to "skills as data, not prose" |
| [CompanyHelm](https://github.com/CompanyHelm/companyhelm) (MIT, Node, ~73★) | Every agent session in a fresh E2B VM; multi-repo; MCP/skills customisation |
| [omnigent](https://github.com/omnigent-ai/omnigent) (Apache-2.0, Python, ~8.2k★) | Meta-harness over Claude Code/Codex/Cursor/OpenCode/Hermes/Pi. **Agents declared in YAML** (prompts, tools, sub-agents). Approval gates, co-driving, fork-conversation, policy governance at server/agent/session scope |
| [sandbox-agent](https://github.com/rivet-dev/sandbox-agent) (Apache-2.0, Rust, ~1.5k★) | **Universal Session Schema** — one HTTP+SSE API normalising Claude Code, Codex, OpenCode, Cursor, Amp and Pi events into a single JSON event stream, with OpenAPI + TS SDK. A serious alternative substrate to herdr |
| [Orkas](https://github.com/Orkas-AI/Orkas) (MIT) | Local-first desktop; "visibility slicing" — agents only see relevant conversation portions |

---

## 3. The substrate question — herdr and its alternatives

### herdr — [herdrdev/herdr](https://github.com/herdrdev/herdr) · [herdr.dev](https://herdr.dev)

The braindump's assumption that herdr is a good substrate **checks out, and it's bigger than you thought.**

| | |
|---|---|
| Open source | **Yes — Apache-2.0**, full source on GitHub |
| Language | **Rust**, single binary ("one rust binary, no electron") |
| Stars | **25,108** (1,770 forks, 136 open issues) |
| Repo | **`herdrdev/herdr`** — the widely-cited `ogulcancelik/herdr` URL redirects (same repo id). Author Oğulcan Çelik; graduated from personal repo to org |
| Age / velocity | Created **2026-03-27**; **v0.8.0** (2026-08-03) + rolling weekly `preview`. **0 → 25k stars in ~4 months** |
| Business model | Free, no paid tier. `hey@herdr.dev` advertises enterprise partnerships |
| Backends | **21 agent kinds**: pi, claude, codex, gemini, cursor, devin, agy, cline, omp, mastracode, opencode, copilot, kimi, kiro, droid, amp, grok, hermes, kilo, qodercli, maki. 16 have deeper `integration install` hooks for self-reporting |
| Persistence | Sessions survive machine restarts and network disconnects; remote attach over SSH |

**Socket API surface** (documented at [herdr.dev/docs/socket-api](https://herdr.dev/docs/socket-api/)),
dot-namespaced: `workspace.*`, `tab.*`, `pane.*` (split/swap/move/zoom/resize/focus/**read**/**send
input**/close), `agent.*` (**list / get / read / prompt / wait / start / focus**), `layout.*`,
`events.subscribe` / `events.wait`, `plugins.*` (link/list/enable/disable/**invoke actions**),
`integrations.*`, `notifications.show`, `session.snapshot`.

**Crucially for principle #2:** herdr has a **semantic agent state model — `idle`, `working`,
`blocked`, `done`, `unknown`** ("done means idle and not yet seen"), and **`pane.report_agent`**
lets an integration *report* agent state directly rather than having anything infer it from a
transcript. That is a ready-made structured-state channel for our controller.

**Four observation layers, and it's honest about its blind spots:**
1. Typed status enum, with real semantics — `done` = idle-after-unseen-background-work;
   `blocked` = a *recognised* approval/question UI; **`unknown` explicitly does not prove
   completion**. "Seen" is tracked, and CLI reads deliberately do *not* mark a tab seen.
2. **`agent wait --until blocked --timeout N`** — a blocking state-transition primitive (with an
   `agent_prompt_stalled` guard at 5s). This is the single most useful call for a step machine.
3. **`agent read --source visible | recent | recent-unwrapped | detection [--format ansi]`** — four
   read planes including the exact detection buffer.
4. Socket **event subscription**, plus `pane wait-output --match/--regex`.
   Documented blind spot: alt-screen rows never enter host scrollback.

**Worktrees are first-class over the socket API** — `worktree create --branch --base --path`,
`open`, `list`, `remove` — so an agent can create its own.

**Nesting is structural.** herdr injects `HERDR_ENV=1` and `HERDR_WORKSPACE_ID` / `TAB_ID` /
`PANE_ID` into every pane. Any agent can `pane split` → `agent start` → `agent prompt --wait` →
`agent read`; the spawned agent inherits the same context and can do it again. It ships an agent
skill (`herdr --skill`) teaching exactly this, with safety rules. **Effectively unlimited depth.**

**Machine-readable contract:** `herdr api schema --json` emits a full JSON-Schema (draft 2020-12),
**protocol version 19**, with typed event unions — the best control-plane contract in the survey.

**Plugin system:** plugins are public GitHub repos containing a **`herdr-plugin.toml`** manifest,
auto-indexed by the `herdr-plugin` topic. **506 plugins across 502 repos**, no review queue. So our
tool-plugin layer could plausibly *be* a herdr plugin.

**The gap — and it is exactly our product:** `~/.config/herdr/config.toml` is **UI/runtime config
only** (`[theme]`, `[terminal]`, `[update]`, keybindings). **There are no steps, gates, templates, or
DAG.** herdr's orchestration is entirely **imperative**. It is deliberately primitives without
policy.

**Verdict: yes, build on herdr.** Apache-2.0 + Rust + 25k stars + a semantic agent-state API +
`agent wait` + four read planes + worktrees + structural nesting + 21 backends + a versioned typed
schema. It removes exactly the undifferentiated work the braindump identified, and the thing it
pointedly does *not* have — declarative templates with gates — is the thing we would add.
Firstmate already uses it as an (experimental) backend, and hcom lists it as a supported terminal,
which validates the pattern.

**Alternative substrate to evaluate: [sandbox-agent](https://github.com/rivet-dev/sandbox-agent)** —
Rust daemon, Apache-2.0, HTTP+SSE, and its **Universal Session Schema** normalises six agents' event
formats into one JSON schema. herdr gives you *panes and semantic state*; sandbox-agent gives you
*normalised structured events*. You may want both, or you may find sandbox-agent's schema is the
better source of truth for the controller and herdr is just the display/PTY layer.

---

## 4. Landscape taxonomy

From [yetanotherorchestrator.app](https://yetanotherorchestrator.app/) (48 products) and
[awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators) (~150):

| Category | Count | Examples |
|---|---|---|
| Desktop apps | 29 | Conductor, cmux, Mux, Orca, Emdash, Nimbalyst, Superset, Clave, Proliferate |
| Web dashboards | 9 | Vibe Kanban, amux, AI Maestro, CliDeck, Fusion, Sortie, Agent Kanban |
| Terminal UIs | 9 | Claude Squad, herdr, dmux, Agent Deck, Gas Town, Ralph TUI, OpenKanban |
| Multi-agent swarms | 23 | ClawTeam, gastown, hcom, ruflo, ORCH, tutti, 5dive, shire, Orkas, CompanyHelm |
| Autonomous loop runners | 10 | bernstein, fractal, Dex, ralph-* family, LoopTroop, toryo |
| Autonomous task runners | 17 | OpenHands, open-swe, cyrus, sortie, gh-aw, claude-code-action, codex-action |
| Agent infrastructure | 15 | guild, sandbox-agent, agent-runbook, omnigent, skillfold, agenttier, Claudexor |

### The 2026 graveyard — read this before assuming a tool is alive

The category has already had a brutal consolidation. **Of the six most-cited 2025 tools, only two
are healthily maintained.**

| Tool | ★ | Status |
|---|---|---|
| **Vibe Kanban** | 27.7k | **SHUT DOWN 10 Apr 2026.** *"The vast majority are free users and we couldn't find a business model we could get excited about."* Cloud ran 30 more days, then local-only. Final commits 24 Apr add a sunsetting banner + export-only page. 535 open issues, no maintainer replies. |
| **Crystal** | 3.1k | **DEAD 26 Feb 2026.** Last 10 commits are migration/SEO copy from one day; the app ships a modal telling users to leave. → **Nimbalyst** (1.4k★, MIT, healthy, but scope-crept into a WYSIWYG workspace) |
| **Terragon** | 253 | **DEAD 9 Feb 2026.** Site shows a shutdown page; docs domain has an expired TLS cert. Source dumped to `terragon-labs/terragon-oss`, unmaintained. **Devboxer** ($30/$60 per user/mo) claims continuity "on literally the same foundations." |
| **uzi** | 581 | **ABANDONED** — last commit June 2025. Docs site returns HTTP 410. 8 of its last 10 commits were README edits. Homepage still hardcodes "211 stars". |
| **container-use** (Dagger) | 4.0k | **DORMANT** — no release since v0.4.2 (Aug 2025), two docs-only commits in 2026, 84 open issues |
| **HumanLayer** | 11.2k | Repo **explicitly deprecated** ("the code here is pretty much all deprecated"). Product is now a **proprietary** AI IDE: QRSPI phase gates, comment-driven design review, BYOK. Free ≤3 users/200 sessions, **Pro $100/user/mo** |
| **`parruda/claude-swarm`** | — | **DELETED** (HTTP 404, absent from the owner's repo list). The 2025 Ruby/YAML/MCP hierarchical swarm tool is gone; the name now belongs to unrelated forks. **Treat any 2025 write-up citing it as stale.** |
| **Devlo** | closed | Alive but trivial — a GitHub/Jira bot (tag `@devloai` → plan → you confirm → PR). No parallelism, no worktrees, no sub-agents, undisclosed models. 1,039 Marketplace installs. Not really in this category. |
| **Sculptor** | 213 | **Healthy**, committed today. See §5a. |
| **Claude Squad** | 8.2k | **Healthy**, last push 2026-07-30. ⚠️ **AGPL-3.0** |

**Lesson for us:** 27.7k stars did not save Vibe Kanban. This category has no proven business model
and a punishing free-user ratio. Whatever we build should be justified by our own use, not by a
market opportunity.

Useful framing from [Addy Osmani's "Code Agent Orchestra"](https://addyosmani.com/blog/code-agent-orchestra/):
three tiers — **in-process** (Claude Code subagents/Teams), **local orchestrators** (Conductor, Vibe
Kanban, OpenClaw), **cloud async** (Claude Code Web, Copilot agent, Jules, Codex Web) — and the
observation that *human supervision is the bottleneck, not generation speed*. He also identifies the
"teams of teams" pattern (feature leads spawn their own specialists) and the flat peer-to-peer
pattern (teammates communicate directly, no lead bottleneck) as the two live architectural bets —
which is exactly the axis our design sits on.

---

## 5a. The worktree/session runners — three that matter more than the rest

Most of the 48 desktop/web products are interchangeable. Three are not.

### Vibe Kanban — dead, but the best nesting design in the survey

Apache-2.0, **Rust** + Node, **27.7k stars** — and **sunset**. Shutdown post **10 April 2026**:
*"the vast majority are free users and we couldn't find a business model that we could get excited
about."* Cloud ran 30 more days then reverted to fully local; final commits 24 Apr 2026 added a
sunsetting banner and an export-only page. 535 open issues, unlabelled and unassigned.

**Read it anyway.** It ships an **MCP server that gives agents the human's full powers**:
`start_workspace` (with executor choice), `create_session`, `run_session_prompt`, `create_issue`,
`create_issue_relationship` (blocking / related / duplicate). An agent can decompose an issue into
related sub-issues and **spawn a workspace + agent per sub-issue, choosing a different backend for
each — recursively.** That is our nestable controller, expressed as MCP tools rather than a bespoke
protocol, and it answers the braindump's open question "is the plugin interface MCP servers?" with
a working existence proof.

Its executor layer is also the reference implementation for multi-backend: a
`StandardCodingAgentExecutor` trait normalising 10 agents' output streams
(`plain_text_processor.rs`, `stderr_processor.rs`) → SQLite → `MsgStore` → WebSocket, with
**Rust→TypeScript type generation making status enums compile-time-enforced** end to end. Also has
an `crates/executors/src/acp/` path.

### Sculptor (Imbue) — punches far above its 213 stars

MIT, free, actively committed. **It reversed its own founding architecture:** Sculptor launched in
2025 on the explicit thesis that *containers beat worktrees*; today the docs say *"By default a
workspace is a **git worktree** off your repo."* Containers are now an unstable experimental
backend. (`docs.imbue.com/features/containers` and `/changelog` now 404; the docs site
302-redirects to the GitHub repo. **Every third-party summary still calling Sculptor
"a container per agent" is stale.**)

Three things make it the most relevant of the runners:

1. **The most transparent observation layer anywhere.** *"Sculptor runs Claude Code as a streaming
   JSON process with its control protocol enabled"*, and Pi in **RPC mode**. It surfaces structured
   todo steps (`1 / 8`, pending/in-progress/done) and **per-turn context-usage %**. This is the
   underexploited option: don't scrape a PTY, drive the agent's own machine-readable control
   protocol.
2. **A real repeatable multi-stage pipeline** — `sculptor-workflow`: spec → mock → architect → plan
   → build → review, **each stage its own named agent in its own tab, each emitting a durable
   on-disk artifact so stages are resumable and skippable.** That is braindump §5's "fix bug"
   template, shipped.
3. **Nesting is built in**: skills *are* agents that spawn parallel subagents; workflow stages run
   as their own agents; and a **CI Babysitter autonomously spawns an agent when a PR's checks fail**
   — no human trigger.

Extension SDK is refreshingly simple: `manifest.json` + a plain ES module, no build step.
Constraints: two integrated harnesses only, no Windows or Intel Mac, external contributions limited.

### Conductor — closed source, but its API is a spec worth copying

Closed source. **v0.79.0 (4 Aug 2026)**, ~weekly releases. **Conductor Cloud shipped 30 Jul 2026**
— persistent microVM workspaces, real-time multiplayer, REST API (beta). Free / **Pro $50** /
**Teams $60 per user** / Enterprise.

Its **public OpenAPI spec** is the single most useful artifact: workspace status
`initializing | ready | sleeping | archived | deleted | updating`; **session status
`idle | working | error`**; agent types `claude | codex | cursor | **acp**`. Polling only (~15 s),
no webhooks — with a caveat every harness in this space hits and almost nobody documents:

> **"Wait for `working` before trusting `idle`. A queued prompt hasn't started."**

Also unusual: **`POST /v0/sql` over a `session_transcripts_view`** — SQL across agent transcripts.
Config is **TOML with 5-layer VS Code-style precedence** (`.conductor/settings.toml` committed,
`.local.toml` uncommitted, `~/.conductor/`, managed org settings, defaults) with a published JSON
schema and multiple named run scripts. Cloud workspaces auto-inject `CONDUCTOR_API_URL`,
`CONDUCTOR_API_KEY`, `CONDUCTOR_SESSION_ID`, and the docs ship orchestration cookbook recipes
("Plan, Implement"; "Multi-PR Task") — so **nesting is possible on the cloud tier only**; the free
local tier has no nesting mechanism. Still **no workflow DAG and no declarative gates.**

### Claude Squad — the baseline

AGPL-3.0, Go, **8.2k stars**, actively maintained. tmux + git worktrees + a TUI. Attach to any
session with Enter/`o` to re-prompt; pause/resume with `r`; config at
`~/.claude-squad/config.json`. Claude Code, Codex, Gemini, Aider, custom via flags. No orchestration
model at all — it is a session *manager*. This is the floor the whole category is built on.

### The finding that matters most from this cluster

Across every tool examined closely — Conductor, Vibe Kanban, Sculptor, Gas Town, ClawTeam, Fusion,
awslabs/cli-agent-orchestrator, hcom, herdr, AO, GraphCode, 5dive, and Claude Code Agent Teams —
**all of them preserve direct human→sub-agent addressing.** Where hierarchy exists, children remain
first-class sessions the human can open and type into.

**The mandatory-proxy design that the braindump is reacting against has essentially one adherent in
2026: Firstmate** (plus Claude Code's plain subagents, which are a different primitive). It is not
the industry norm we're breaking from — it is an outlier we happened to look at first.

---

## 5b. General multi-agent frameworks — mostly a dead end for us

Detailed sweep of AutoGen/AG2, LangGraph, CrewAI, ADK, OpenAI Agents SDK, MetaGPT, ChatDev,
Magentic-One, OpenHands, SWE-agent, Agno, Pydantic AI, Mastra, Temporal, Dify/Flowise/n8n.

**The one-line verdict: these orchestrate *LLM API calls*, not *long-lived interactive processes*.**
A "worker" in these frameworks is a **blocked function call**, not an addressable entity — which is
exactly why they all fail our two key tests. You cannot spontaneously message a running worker; you
can only answer a request the worker raised. And "how does the supervisor observe the worker"
collapses to "the return value of a tool call."

| Framework | License | Stars | Latest | Human→leaf mid-run? | Supervisor sees | Declarative | Drives CLI coding agents? |
|---|---|---|---|---|---|---|---|
| **OpenHands** | MIT | **83.3k** | v1.10.0 (Aug 5 2026) | ⚠️ resume by `task_id` | ✅✅ `TaskObservation{task_id, subagent, status, text}` — transcript persisted to disk, **never injected** | ✅ `.md`+YAML agents, skills, plugins | ✅✅ **YES — best in class, via ACP** |
| MS Agent Framework | MIT | 12.6k | Aug 4 2026 | ❌ typed `RequestInfo` only | Typed edge messages + event stream; Magentic task/progress ledgers | ✅✅ **YAML Declarative Workflows 1.0** | ❌ |
| AutoGen | — | 60.3k | **maintenance mode** | ⚠️ `UserProxyAgent` | Full transcript in group chat | ❌ | ❌ frozen |
| **AG2 v1.0** | Apache-2.0 | 4.8k | **v1.0.1 (Jul 29 2026)** | ✅ **`HumanClient` is a first-class network peer** | Envelopes on channels you're a member of | ⚠️ `TransitionGraph` (code) | ⚠️ **new ACP support, unproven** |
| CrewAI | MIT | 56.7k | Aug 5 2026 | ❌ post-hoc stdin | `TaskOutput` via explicit `context` | ✅ `crew.jsonc`, `agents.yaml` | ❌ |
| LangGraph | MIT | 39.1k | Jul 28 2026 | ⚠️ `interrupt()` + resume by interrupt ID | ⚠️ **`output_mode: full_history` vs `last_message`** | ❌ code | ❌ |
| Google ADK 2.0 | Apache-2.0 | 21.0k | Aug 4 2026 | ⚠️ `RequestInput` per node; chat-mode subagent holds the turn | Events on **isolated session branches** | ⚠️ YAML, Gemini-only, experimental | ❌ |
| OpenAI Agents SDK | MIT | 28.4k | Aug 5 2026 | ❌ run-wide tool approval | ⚠️ handoff inherits **full history** by default | ❌ | ❌ |
| MetaGPT | MIT | 69.7k | **v0.8.2 (Mar 2025) — 17mo stale** | ❌ | shared pub/sub | ⚠️ | ❌ **frozen** |
| ChatDev 2.0 | Apache-2.0 | 33.9k | Mar 2026 | ❌ | chat-chain transcripts | ✅ YAML DAG | ❌ research |
| Agno | Apache-2.0 | 41.6k | Aug 6 2026 | ❌ | member responses kept **separate** from leader | ⚠️ | ❌ |
| Pydantic AI | MIT | 19.1k | Aug 6 2026 | ⚠️ deferred/approval tools | delegate output as tool return; `UsageLimits` | ❌ | ❌ |
| Mastra | NOASSERTION | 27.0k | Aug 6 2026 | ⚠️ **suspend/resume by step ID** | typed step outputs + snapshots | ⚠️ | ❌ |
| Temporal | MIT | 22.2k | active | n/a | n/a | n/a | ⚠️ **right substrate, zero agent semantics** |
| SWE-agent / mini-swe-agent | MIT | 20.0k / 6.3k | superseded / Jul 2026 | ❌ | **no multi-agent at all** | ✅ YAML | ❌ (they *are* the agent) |
| Dify / Flowise / n8n | various | 151k / 55k / 200k | active | ⚠️ Human Input node | node outputs | ✅ JSON/YAML DSL | ❌ wrong shape |

**Things worth stealing from this tier anyway:**

- **OpenHands `TaskObservation`** — the single best context-hygiene design found anywhere: parent
  gets `{task_id, subagent, status, text}`; the sub-agent's **full transcript is persisted to disk
  and re-engageable via `resume='task_00000001'`, but never injected into the parent's context.**
  That is precisely our "controller reads state, not transcripts" *plus* an answer to "but what if
  I need the detail later."
- **LangGraph's `output_mode` knob** (`full_history` vs `last_message`) is the clearest articulation
  in the industry of the exact tradeoff our principle #1 is about. LangChain has soft-deprecated
  `langgraph-supervisor` in favour of subagents-as-tools that return only the last message.
- **Magentic's Task Ledger + Progress Ledger** — the manager keeps a structured per-round record
  (`IsRequestSatisfied`, `IsInLoop`, `IsProgressBeingMade`, `NextSpeaker`, `InstructionOrQuestion`)
  with stall detection triggering auto-replan. A good model for controller state.
- **MS Agent Framework Declarative Workflows 1.0** — the most mature declarative workflow YAML in
  existence (`kind: Workflow`, trigger, action kinds, loops/jumps, **human-in-the-loop actions**,
  Power Fx expressions for state, checkpoint/resume). Worth reading the schema even though the
  runtime is useless to us.
- **AG2 v1.0's `HumanClient`** — the human modelled as a first-class network participant with the
  same envelope plumbing as agents, subject to per-agent access lists. That is *exactly* braindump
  principle #3 ("the human is a peer node"), expressed as an architecture rather than a slogan.
  Nine days old at time of writing; tiny community; do not bet on it, but read it.
- **ADK's honest restriction** that task-mode subagents **must be leaves** (cannot have sub-agents) —
  an admission that nested auto-return delegation is genuinely hard. Expect to hit this.

**Three things no general framework models, that coding agents require:** git worktree isolation +
file-conflict detection; process supervision (streaming stdout, permission-prompt forwarding,
mid-turn interrupt, session resumption); and a live channel to a running worker.

---

## 5c. Claude Code Agent Teams — Anthropic shipped our differentiator #3

**This is the most important single finding in this document.**

Claude Code has an experimental **Agent Teams** feature (behind
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, v2.1.199+,
[docs](https://code.claude.com/docs/en/agent-teams)). A **lead** plus N teammates, each a **full
independent Claude Code session** — not in-process subagents.

| Property | Behaviour |
|---|---|
| **Human → teammate direct** | ✅✅ **Yes.** In the agent panel, ↑↓ to select a teammate, **Enter to open its transcript and type directly to it**, **Esc to interrupt that teammate's current turn.** Or split panes (tmux/iTerm2) and click into a pane. |
| **Lead's context** | ✅ **Teammate transcripts are NOT in the lead's context.** The lead sees mailbox messages, idle/failure notifications, and shared-task-list status changes. |
| **Coordination** | Shared task list with dependencies and **file-lock claiming**; per-teammate mailbox JSON |
| **Gates** | Plan-approval gates |
| **Hooks** | `TeammateIdle`, `TaskCreated`, `TaskCompleted` |
| **Declarative** | Subagent `.md` definitions |
| **Nesting** | ❌ **No nested teams.** Lead is fixed for its lifetime. |
| **Backends** | Claude only |

**The docs say it in our own words.** Verbatim from
[code.claude.com/docs/en/agent-teams](https://code.claude.com/docs/en/agent-teams):

> "Unlike subagents, which run within a single session and can only report back to the main agent,
> **you can also interact with individual teammates directly without going through the lead.**"

That is braindump principle #3, shipped, by Anthropic, as a documented feature.

**On-disk state model** (worth copying — it is all structured, no prose):
- Mailbox per agent: `~/.claude/teams/{team}/inboxes/{agent}.json` — malformed entries are validated,
  reported and removed, valid messages still delivered
- Team config: `~/.claude/teams/{team}/config.json` — `members` array with name + agent ID + agent
  type; teammates read it to **discover other team members** (a rudimentary topology)
- Task list: `~/.claude/tasks/{team}/` — persists across resume; task states pending / in-progress /
  completed, with **dependencies auto-unblocked on completion** and **file-locking on claim** to
  prevent races

**Also directly relevant to our template idea:** subagent definitions (`.claude/agents/*.md`, any
scope incl. plugins) can be **reused as teammate roles** — the definition's `tools` allowlist and
`model` are honoured, body appended to the system prompt. And **plan approval** is a real gate: a
teammate works read-only in plan mode, submits a plan, the lead approves or rejects with feedback,
and it loops until approved. That is braindump §5 steps 5–6 (review → ↻ repeat), already shipped.

**Security note we must not regress on:** when one agent messages another, Claude Code tells the
recipient the message came from another Claude session, **not from the human**. A teammate cannot
approve a permission prompt on the human's behalf, and a denied teammate cannot relay the action to
another teammate to bypass the check. In auto mode a classifier reviews every inter-agent message
and treats relayed approval claims as untrusted input. **Any inter-agent messaging bus we build
needs this property**, or we build a privilege-escalation machine.

**Documented limitations — this is our opening:**
- ❌ **No nested teams.** "Teammates cannot spawn their own teammates. Only the lead can manage the team."
- ❌ **One team per session**, scoped to that session; can't share a team across sessions
- ❌ **Lead is fixed** — no promoting a teammate, no transferring leadership
- ❌ **No session resumption** with in-process teammates (`/resume` and `/rewind` don't restore them)
- ❌ Permissions set at spawn (lead's mode for all); no per-teammate mode at spawn time
- ❌ Task status lags — teammates forget to mark complete, blocking dependents
- ❌ Claude-only, obviously

**Claude Code now ships FOUR parallelism primitives, deliberately separated**
([docs/en/agents](https://code.claude.com/docs/en/agents)):

| Primitive | Who holds the plan | Shape | Human→leaf |
|---|---|---|---|
| **Subagents** | Claude, turn by turn | Hierarchical, context-isolated workers | ❌ parent is proxy |
| **Background agents / agent view** | You | Flat independent sessions | ✅ peek/attach |
| **Agent teams** | A lead agent | Lead + peers, shared task list, mailbox | ✅ panel/panes |
| **Dynamic workflows** | **A JavaScript script** | Programmatic DAG/loop, runtime-executed | ❌ by design |

**⚠️ Dynamic workflows are the direct competitor to our template system, and they went the opposite
way from us.** Claude *writes* a JS script using `agent()` and `pipeline()` calls; a runtime executes
it **out of context**; you can save it to **`.claude/workflows/*.js`** as a slash command or ship it
in a plugin. Caps: **16 concurrent agents, 1,000 agents per run**, with a `workflowSizeGuideline`
setting (`small`/`medium`/`large`, default `medium` ≈ <15 agents). `/effort ultracode` makes Claude
auto-plan a workflow for every substantive task. A `/workflows` view shows per-phase agent counts,
token totals, elapsed time, and pause / resume / restart-one-agent.

**Anthropic chose an imperative, model-authored JS program over a declarative data file** — the exact
opposite of braindump principle #2. And critically, the docs state there is **no mid-run human input
by design**: *"For sign-off between stages, run each stage as its own workflow."* **That is precisely
the gap our human-owned gate step would fill.**

**Subagent nesting: 3 deep by default** (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`; set `1` to disable),
20 concurrent (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`), 200 spawns per session, `--max-budget-usd`
kills background subagents. The history is instructive: **5 through v2.1.216 → hard off in v2.1.217
→ back to 3 in v2.1.219.** They are actively struggling with this.

Subagent results are **final message only**, and as of v2.1.210 that final message is
**scanned for prompt injection** before the parent reads it (control-tag imitation gets a backslash,
`Human:`/`Assistant:` markers escaped, a `[harness: ...]` marker prepended). Observers *outside* the
parent get more: `--forward-subagent-text` puts subagent text/thinking into stream-json, messages
carry `parent_tool_use_id`, and `SubagentStart`/`SubagentStop` hooks fire.

**Adjacent and equally relevant: Claude Code background agents / agent view** (`claude agents`).
A real status enum — **working / needs input / idle / completed / failed / stopped**, plus glyphs for
process-exited and `/loop`-sleeping — with auto worktrees under `.claude/worktrees/`,
`claude attach | logs | stop | rm`, **Space to peek-and-reply without attaching**, `claude --bg`,
`/bg`, `/fork`, a `WorktreeCreate` hook for non-git VCS, and `worktree.bgIsolation: "none"` to opt
out. Between agent teams and agent view, Anthropic has shipped most of a session manager.

**The signal in the limitation:** Anthropic shipped direct teammate addressing and *then*
deliberately capped nesting at one level ("no nested teams… only the lead can manage the team";
in-process teammates can't even launch background subagents). They had the harder feature and chose
not to build the easier one. Read that as evidence that **depth's coordination cost may exceed its
value at current model capability** — which is a direct challenge to differentiator #1. Worth
testing empirically before committing to nesting as the headline feature.

**What this means for us:** two of our four differentiators — *human talks directly to any leaf* and
*controller reads structured state, not transcripts* — are now **native, first-party Claude Code
behaviour**, free, behind an env var. Our remaining defensible ground is: **nesting** (explicitly
absent), **declarative templates with human-owned gates**, **Codex as a co-equal backend**,
**cross-session/persistent teams**, and **the graph view**.

---

## 5d. Vendor control planes — the platform risk

### GitHub Agent HQ

The most strategically significant thing in this space, because it is a **cross-vendor control
plane owned by the place the code already lives.** "Mission control" spans GitHub, VS Code, mobile
and CLI: *"choose from a fleet of agents, assign them work in parallel, and track their progress
from any device."*

- **Third-party agents**: Anthropic (Claude), OpenAI (Codex), Google (Jules), Cognition, xAI —
  *"available on GitHub as part of your paid GitHub Copilot subscription."*
- **Custom agents via source-controlled `AGENTS.md`** — declarative guardrails ("prefer this
  logger", "use table-driven tests for all handlers")
- Granular branch controls for CI oversight, agent identity management, one-click merge-conflict
  resolution, Slack/Linear/Jira/Teams/Azure Boards/Raycast integration
- Copilot coding agent now does a **first-line self-review before a human sees the code**
- Bundled into paid Copilot subscriptions — i.e. **free at the margin for most orgs**

**This is the commoditisation risk.** Multi-backend fan-out plus a status board plus PR/CI-based
observation — a large chunk of what everything in §5a does — is becoming a free feature of GitHub.
What Agent HQ does *not* have: nesting, declarative step sequences with human gates, local terminal
attach, or a communication graph.

### Sourcegraph Amp — a *counter*-example on direct addressing

Frontier agent platform with four modes (low / medium / high / ultra), multi-model (GPT-5.6, Claude
Fable 5, fast models), an "oracle" second-opinion model, `AGENTS.md`, and YAML-frontmatter skills.
Closed source; subscription + pay-as-you-go credits from $5; enterprise +50%.

Critically: **subagents give the main agent "only their final summary rather than monitoring their
step-by-step work", and the manual is blunt — *"you can't guide them mid-task."*** Amp is a
*mandatory-proxy* design. It does have a cross-thread **agent mesh** (agents spawn, message and
exchange files across threads), plus **orbs** (remote autonomous agents), self-scheduling, and
**Multiplayer** (invite your team to share control of an orb) — but that is human↔human sharing and
thread↔thread messaging, not human↔subagent. Warp client is now **AGPL v3 open source**, and Warp's
**Oz** platform explicitly supports *"multi-agent orchestration for parent/child workflows, fan-out,
and review swarms"* while **driving Claude Code, Codex and OpenCode as third-party CLI agents** —
the strongest multi-backend client story of any vendor.

### ⚠️ OpenAI Codex is moving AWAY from direct addressing — enforced in code

This is the most important counter-signal in the report. Codex ships **two multi-agent generations
in the same binary**. V1 (`spawn_agent`/`send_input`/`resume_agent`/`wait_agent`/`close_agent`,
on by default) permits direct input. **V2** (`spawn`/`send_message`/`followup_task`/`wait`/
`interrupt_agent`/`list_agents`, off by default but force-enabled by model metadata) **blocks it
server-side:**

> `"direct app-server input is not allowed for multi-agent v2 sub-agents"` — `codex-rs/app-server/src/request_processors/turn_processor.rs`
> `"This sub-agent is controlled by its parent. Direct input is disabled."` — `codex-rs/tui/src/chatwidget.rs`

Docs match: `/agent` lets you switch threads and **inspect**; to steer, you *"ask Codex directly to
steer a running subagent."* V2 also replaces opaque IDs with **canonical task paths**
(`/root/research/api`) and adds `fork_turns` to control how much parent history a child inherits.

**One redeeming detail worth stealing: approval gates DO reach the human directly from a child.**
An approval overlay surfaces from inactive threads with a source label, and you press `o` to open
that thread before deciding. That is a working design for "escalate from a leaf to the human without
making the leaf generally addressable."

Codex is otherwise the most permissively licensed major: **Apache-2.0** CLI, SDK, App Server, skills,
plugins. Custom agents are **standalone TOML** in `~/.codex/agents/*.toml`. Skills follow the
[agentskills.io](https://agentskills.io) open standard (shared with Cursor). `approval.reviewer =
auto_review` routes approvals to a *reviewer subagent* instead of to you.

### ⚠️ Nesting is being deliberately clamped across the entire industry

| Product | Max subagent depth |
|---|---|
| Gemini CLI | **0** — *"subagents cannot call other subagents"*, explicit recursion protection |
| Factory Droid | **0** — *"the `Task` tool is not available to it"* |
| Claude Code **agent teams** | **0** — no nested teams |
| Codex V1 | **1** (`DEFAULT_AGENT_MAX_DEPTH = 1`) |
| Cursor | **2**, hard-capped and documented |
| Claude Code subagents | **3** — after oscillating 5 → 0 → 3 across four releases in 2026 |
| Amp cross-thread mesh, Codex V2 | uncapped / no cap found |

**Nobody thinks deep trees are a good idea, and the people with the most data are clamping hardest.**
This is a genuine challenge to differentiator #1. If Anthropic shipped direct-teammate addressing —
the *harder* feature — and then refused to ship nested teams, the most likely explanation is that
coordination cost exceeds value at current model capability. **Test nesting empirically before making
it the headline.**

### Where direct human→worker addressing actually works today

| Product | Mechanism |
|---|---|
| **Claude Code agent teams** | ↑/↓ in agent panel, Enter into a teammate's transcript and type; Esc interrupts; `x` stops |
| **Claude Code background agents** | `claude agents` → Space to peek-and-reply, Enter to attach, `claude attach <id>` |
| **Devin** | No subagent tree at all — every worker is an API-addressable session (`POST /sessions/{id}/messages`) |
| **Warp Oz** | Session sharing: *"attach to a running task to monitor and, where supported, steer it"* |
| **OpenCode** | ⭐ `@subagent` autocomplete invocation — *"regardless of task permission settings"*. Invocation-time, not mid-run |
| **Cursor** | Not for subagents; you **promote to a cloud agent/peer** (`&`, `/in-cloud`, `/babysit`) which is then fully addressable incl. via REST |
| **GitHub Agent HQ** | Peers yes, but **the channel is a PR comment**, not a chat |

And where it explicitly does **not**: Codex V2 (blocked in code), Amp (*"can't guide them mid-task"*),
Factory (`AskUser` disabled in subagents), Gemini CLI (`@name` is prompt-time routing only), Claude
Code plain subagents, Firstmate.

### GitHub's other two layers

Beyond mission control, GitHub ships two things worth noting:
- **Copilot CLI `/fleet`** — genuine hierarchical delegation: *"an orchestrator agent manages
  dependencies and runs independent subtasks concurrently"*, each subagent with its own context
  window, routable to `@CUSTOM-AGENT-NAME` or a specific model per subtask. Plus **Autopilot mode**
  and **Remote control** (monitor/steer a CLI session from github.com or mobile).
- **GitHub Agentic Workflows** — Markdown + YAML frontmatter in `.github/workflows/`, compiled to a
  hardened `.lock.yml` Actions workflow, writes only through declared **`safe-outputs`**, and
  critically an **`engine:` key selecting GitHub Copilot, Anthropic Claude, OpenAI Codex, or Google
  Gemini.** That is the most credible declarative *and* multi-backend workflow artifact anyone ships.

### Format convergence is total — switching costs at the config layer have collapsed

`AGENTS.md`, `SKILL.md` (the agentskills.io standard, shared by OpenAI *and* Cursor), MD+YAML
subagent files, `hooks.json`, and plugin manifests with marketplaces are near-universal. GitHub's
plugin format is a near-clone of Claude Code's. **Cursor literally reads `.claude/agents/`,
`.codex/agents/` and `CLAUDE.md`.** The moats are no longer config formats — they are the
orchestration runtime and the control plane. Which is where we'd be playing, and where everyone else
already is.

### Vendor summary table

| Product | License | Orchestration shape | Human→subagent direct? | Parent observes via | Multi-backend / ACP | Declarative | Nest depth |
|---|---|---|---|---|---|---|---|
| **Claude Code** | closed (SDK public) | subagents ∥ background sessions ∥ **teams** ∥ **JS workflows** | subagents ❌ · **teams ✅** · background ✅ | final message only + injection scan; mailboxes; `/workflows` view; hooks | Claude-only workers; **is** an ACP agent | `.claude/agents/*.md`, skills, hooks, plugins, **`.claude/workflows/*.js`** | subagents **3**; teams **0** |
| **Codex** | **Apache-2.0** CLI/SDK | hub-and-spoke + join barrier; V1 & V2 | **❌ blocked in code (V2)**; V1 unblocked. **Approvals do reach you from children** | summaries to model, transcripts to human; `exec --json`; App Server JSON-RPC | OpenAI-compatible only; **ACP first-party**; MCP server | `AGENTS.md`, agent **`.toml`**, `SKILL.md`, hooks, `.rules` | V1 **1**; V2 no cap found |
| **Cursor** | proprietary | **peers (Agents Window) + subagents**; `/best-of-n` + judging | ❌ subagents; **promote to cloud peer → ✅** | `~/.cursor/subagents/` files, `NestedTaskUpdate`, **REST+SSE**, artifacts, ~20 hooks | multi-*model*; **ACP server**; **reads `.claude/` + `.codex/`** | MDC rules, `SKILL.md`, hooks.json, `worktrees.json`, **Automations** | **2, hard-capped** |
| **GitHub Agent HQ** | closed, in Copilot sub | mission control (flat, PR-shaped) + **`/fleet`** + **Agentic Workflows** | peers ✅ *via PR comments*; fleet subagents ❌ | **PR state**, session history, agent identities, metrics | ⭐ **Anthropic, OpenAI, Google, Cognition, xAI**; `engine:` per workflow | **`.github/workflows/*.md` + `safe-outputs`**, `.agent.md`, `plugin.json` | 1 documented |
| **Devin / Cognition** | closed | **flat parallel sessions** (Multi-Devin de-emphasised) | ✅ every worker is an addressable session | session API v1/v2/v3, PR state, Slack/Linear, embedded IDE | Adaptive Router; MCP + **DeepWiki**; Desktop ACP (unconfirmed) | **Playbooks**, Knowledge, skills, Cascade hooks | not documented |
| **Warp / Oz** | ⭐ **AGPL-3.0 client** | Oz: **parent/child, fan-out, review swarms** across machines | **closest to ✅** — attach and *"where supported, steer"* | management UI, status/history APIs, session attach | ⭐ **drives Claude Code, Codex, OpenCode** | WARP.md, Warp Drive workflows, agent profiles | unstated |
| **Factory Droid** | closed | subagents + **Missions** (plan → Mission Control) | ❌ `AskUser` disabled; Mission-level pause/steer ✅ | final message; `TaskOutput` for background; milestone checkpoints | model-independent; **ACP registry** | `droids/*.md`, `AGENTS.md`, skills, hooks | **0** |
| **Amp** | closed | subagents + **cross-thread agent mesh**, orbs, multiplayer | ❌ *"can't guide them mid-task"* | final summary; shareable thread permalinks; `parentThreadID` | multi-model (Oracle); no ACP found | `AGENTS.md`, MCP, `amp.createAgent()` | cross-thread; no cap |
| **Gemini CLI** | **Apache-2.0** | subagents + ⭐ **remote subagents over A2A** | ❌ (`@name` is prompt-time routing) | separate context loop; reports on completion; hooks | ⭐ **ACP (`--acp`) + A2A**; MCP | `GEMINI.md`, `.gemini/agents/*.md`, skills, hooks | **0 — explicit** |
| **OpenCode** | open source | primary agents + subagents | ⭐ **✅ `@subagent` invoke, bypasses task permissions** | Task tool results; server/SDK | many providers; **`opencode acp`** at full parity | `.opencode/agents/*.md`, `opencode.json`, policies | undocumented |
| **Jules** | closed | independent async tasks + **Planning Critic** reviewer | plan approval only | notifications, PRs, API | Gemini only; MCP | `AGENTS.md`, Scheduled Tasks | n/a |
| **Kiro** (AWS) | closed | custom agents + sub-agents; Web agent multi-repo | ⚠️ unconfirmed | session mgmt, checkpoint/rewind/**fork** | **ACP in Kiro CLI**; MCP | ⭐ **Specs** (req→design→tasks), **steering files**, hooks | ⚠️ unconfirmed |
| **Zed** | open source | ACP client only | n/a | Agent Panel, Threads Sidebar | ⭐ reference ACP client | n/a | n/a |

---

## 5e. ACP is the plug, NOT the control plane

**Agent Client Protocol** ([agentclientprotocol.com](https://agentclientprotocol.com/overview/introduction))
— JSON-RPC 2.0, "LSP for coding agents." **Apache-2.0, no CLA**, jointly governed by **Zed and
JetBrains** with an RFD process (50+ RFDs), working groups, biweekly maintainer votes, and official
SDKs in Rust, TypeScript, Python, Java and Kotlin. A foundation transition is stated as pending.

> ⚠️ **Correction to a common 2026 claim:** several secondary sources say MCP/A2A/**ACP** now all sit
> under the Linux Foundation. **ACP's own governance page contradicts this** — Zed+JetBrains interim
> governance, foundation move pending. Trust the governance page.

**Adoption is genuinely won:** ~**37 agents** in the registry — Claude Agent (via Zed's SDK adapter),
Codex CLI, Cursor, GitHub Copilot (public preview), Gemini CLI, Factory Droid, Kiro CLI, OpenCode,
Cline, Goose, Junie, Qoder CLI, Qwen Code, Mistral Vibe, Poolside, OpenHands, Kimi CLI, Augment,
Docker cagent, OpenClaw. Clients: Zed (native), JetBrains (official), Neovim, Emacs, Qt Creator,
Visual Studio, Obsidian, five VS Code extensions, plus Discord/Slack/Telegram/Matrix bridges.
v2 (2026) moved prompt lifecycle into `session/update` state notifications
(`running`/`idle`/`requires_action`), added `session/resume` with `replayFrom`, upsert patching,
agent plans, `session/request_permission`, elicitation, and **removed** client-side `fs/*` and
`terminal/*` in favour of MCP.

> ⭐ **The critical fact for us: ACP does not model subagents, nested sessions, or agent hierarchies
> at all.** It is strictly one client ↔ one agent session. Multi-agent orchestration is explicitly
> out of scope, and **every vendor implements it privately above the protocol.**

**So ACP gives us a uniform way to *drive* each backend, and nothing at all for the orchestration
layer — which is precisely the layer we'd be building.** That is good news: it means the multi-backend
problem is genuinely solved and reusable, and the hard part is genuinely ours.

Also notable: **ACP-native orchestrators already exist as clients** — "Codeg — collaborative
multi-agent coding workbench" and "Jockey — multi-agent orchestrator." Those are the emergent
third-party cross-vendor control planes to watch (and possibly the closest direct competitors).

Adjacent normalisation layers if you don't want raw ACP: **sandbox-agent**'s Universal Session
Schema (6 agents), **herdr**'s 21 integrations, **AO**'s 23 worker adapters, **bernstein**'s 40+.

**Distinct from A2A** (Google's agent-to-agent protocol, v1.0 Apr 2026, Linux Foundation, 150+ orgs)
— and note that **Gemini CLI's "remote subagents 🔬" delegates over A2A**, which is the only
first-party attempt at an agent↔agent wire for coding agents that this research found.

**Implication: do not hand-write Claude/Codex adapters.** Speak ACP (or sit on herdr /
sandbox-agent), and spend the effort on the hierarchy ACP deliberately omits.

---

## 6. Gap analysis — brutally honest

### 6.1 Differentiator by differentiator

**(a) "Nestable controllers: main → sub-controller scoped to one issue → leaf agents"**
→ **NOT NOVEL.** Shipped in at least five places:
- **Gas Town**: Mayor → Deacon → Witness → polecats, four tiers, 17.5k stars.
- **Firstmate**: captain → firstmate → secondmate (own `FM_HOME`, own backlog, optionally on a
  different host over SSH) → crewmate.
- **fractal**: arbitrary recursion with an explicit `max-depth` cap.
- **tutti**: `workflow` is itself a step type, so workflows nest by construction.
- **multi-agent-shogun**: shogun → karo → ashigaru.
- **Claude Code subagents** nest **3 deep** by default; **herdr** nests structurally without limit
  via env-var context injection; **Vibe Kanban** nests recursively via MCP.
- Also AutoGen/CrewAI/LangGraph hierarchical teams in the framework world.

**But there is a serious counter-signal: the whole industry is clamping nesting, not expanding it.**
Gemini CLI 0 (explicit recursion protection), Factory 0, Claude Code agent teams 0, Codex V1 1,
Cursor 2 (hard-capped), Claude Code subagents 3 after oscillating 5 → 0 → 3 in four releases. The
vendors with the most usage data are converging on *shallow*. Before making nesting the headline
differentiator, we should be able to articulate why our 3-level case (main → issue-scoped
sub-controller → leaf) succeeds where theirs is being walked back. The plausible answer — that our
middle tier is a *deterministic controller* rather than an LLM re-planning the world — is actually a
good one, but it needs to be said explicitly and tested.

**(b) "The human can talk DIRECTLY to any agent or sub-controller"**
→ **NOT NOVEL — and worse, it is a free built-in feature of the primary backend we're targeting.**
**Claude Code Agent Teams** ships exactly this, and the docs describe it in the same words the
braindump uses. Beyond that it is shipped in at least eight third-party places, with four distinct
UX idioms:
- CLI message-send: `graphcode node send`, `hcom send -b @luna`, `clawteam inbox send <team> <agent>`
- Attach-to-PTY: AO ("live terminal control"), awslabs/cli-agent-orchestrator (tmux attach),
  Ivy-Tendril ("Chat with Agent (PTY)"), Gas Town (`gt mayor start --agent auggie`)
- Chat UI per agent: Fusion (direct chat + @mention chat rooms), Agent Teams ("send a direct message
  to any agent"), shire (dashboard chat)
- Messaging-app bridge: 5dive (one Telegram forum topic per agent)
**And the framing in the braindump is backwards.** Principle #3 says *"Existing orchestrators funnel
all human interaction through a single root."* That is **not true of the 2026 market.** Of every
tool examined closely here — Conductor, Vibe Kanban, Sculptor, Gas Town, ClawTeam, Fusion, AO,
GraphCode, hcom, 5dive, herdr, awslabs/cli-agent-orchestrator, Claude Code Agent Teams —
**every single one preserves direct human→sub-agent addressing.** Where hierarchy exists, children
stay first-class sessions you can open and type into.

**Firstmate is the outlier, not the norm.** Its Prime Directive #4 ("crewmates never address the
captain") is a deliberate, unusual choice — and it is essentially the *only* adherent, alongside
Claude Code's plain subagents (a different primitive: in-process, report-once, not sessions). We
generalised from a sample of one.

**(c) "The controller consumes MINIMAL context — reads structured STATE, never transcripts"**
→ **NOT NOVEL, and others have gone further than the braindump proposes.**
- **bernstein** removes the model from the coordination loop *entirely* — plain Python scheduling,
  gates are tests/lint/typecheck/file-existence/git status. Zero tokens, fully reproducible.
- **AO** has a rigorous event-sourced model: OBSERVE → durable facts → DERIVE, status computed at
  read time, SQLite + CDC + SSE, with a well-thought-out `activity_state` enum.
- **Firstmate** markets exactly this phrase — "event-driven, zero-token supervision" — with a bash
  watcher over `state/<id>.status` and `.meta` files.
- **Gas Town** uses a git-backed beads ledger plus `.events.jsonl`.
- **herdr** exposes `idle/working/blocked/done/unknown` over its socket API with a `pane.report_agent`
  push channel.
- **OpenHands** returns a typed `TaskObservation{task_id, subagent, status, text}` to the parent
  while persisting the sub-agent's full transcript to disk, re-engageable by `task_id` — the best
  version of this idea anywhere, because it keeps the detail without paying for it.
- **Claude Code Agent Teams** already does it: teammate transcripts are never in the lead's context;
  the lead gets mailbox messages, idle/failure notifications, and task-status changes.
- Our braindump's open question ("LLM controller vs deterministic scheduler?") is answered by the
  market: **deterministic, escalate on exception**, and bernstein proves it works.

**(d) "Templates as declarative JSON/YAML step sequences with repeatable steps and human-owned gates"**
→ **NOT NOVEL, and one project has a strictly better design than ours — but this is the *thinnest*
part of the market and therefore our best structural opening.**

Of ~40 tools examined closely, **only seven have a real workflow file** (as opposed to a config
file): **gastown** (TOML Formulas + `needs` DAG), **tutti** (`tutti.toml`, typed steps,
`depends_on` waves, nested workflows, review + merge gates), **OpenAI Symphony** (`WORKFLOW.md`),
**gh-aw** (Markdown + frontmatter → GitHub Actions), **kandev** (portable YAML, agent-per-step),
**Sculptor** (Markdown skills, fixed linear 6-stage pipeline), **tmux-ide** (`workspace.yml`, layout
only). Add **agent-runbook** and **bernstein** from the loop-runner tier.

Everything else — herdr, Claude Squad, Conductor, AO, superset, container-use, Vibe Kanban, uzi —
has **config files but no workflow files**. `.conductor/settings.toml`,
`.container-use/environment.json`, `.superset/config.json`, `~/.config/herdr/config.toml` all
describe *where* work happens, never *what sequence* or *where the human gates are*. **This is the
clearest open gap in the category.**

Prior art you'd be competing with:
- **agent-runbook**'s YAML has `loop` (repeat until goal/max_iterations) and `quality_check`
  (blocking supervisor gate) as first-class step types, plus JSON-Schema-typed step outputs and
  **build-time contract validation**. That is our "fix bug" template's step 6/9 (↻ repeat) and step
  10 (human fills in) already specified.
- **bernstein**: YAML DAG with `agent`/`command`/`loop` nodes.
- **tutti**: TOML with `prompt`/`command`/`review`/`land`/`workflow` steps, `depends_on`, typed
  artifacts, checkpoints, resume, merge gates.
- **Gas Town**: "molecules" as TOML formulas.
- **kandev**: portable YAML workflows binding **a different agent per step** — the exact thing
  braindump §5 describes ("each step can bind a specific skill").
- **Fusion**: stages + gate policies with human-or-AI validation.
- **Ivy-Tendril**: plans that only advance when verification gates pass.
- **GitHub Agentic Workflows**: Markdown + frontmatter → hardened Actions lockfile, writes gated
  through `safe-outputs`, and an **`engine:` selector across Copilot / Claude / Codex / Gemini**.
  The most credible declarative *and* multi-backend artifact in existence.
- **Claude Code dynamic workflows**: `.claude/workflows/*.js` — but **imperative model-authored
  JavaScript** (`agent()`, `pipeline()`), not declarative data. Anthropic went the opposite way from
  principle #2. **And the docs state there is no mid-run human input by design**
  (*"for sign-off between stages, run each stage as its own workflow"*) — which is exactly the hole
  our human-gate step fills.
- **OpenAI Symphony**: `WORKFLOW.md` front matter + Liquid-rendered prompt body + lifecycle hooks.

**(e) "Supports both Claude Code and Codex"**
→ **TABLE STAKES, NOT A DIFFERENTIATOR.** AO has 23 worker adapters. bernstein has 40+. kandev has
22+ via ACP. herdr, hcom, Gas Town, tutti, omnigent, sandbox-agent, fractal, kodo, ClawTeam,
awslabs/cli-agent-orchestrator — all multi-backend. Anyone shipping single-vendor in 2026 is behind.

### 6.2 Does anything do ALL of it?

**Direct answer: no single tool does all four, but Gas Town does three-and-a-half and Fusion does
three, and the remaining delta is small.**

| | Nesting | Human→leaf direct | State-not-transcripts | Declarative templates | Rendered graph | Tool-based memory |
|---|---|---|---|---|---|---|
| **Gas Town** | ✅ 4 tiers | ✅ `--agent` attach | ✅ beads + events.jsonl | ✅ TOML molecules | ⚠️ agent *tree*, not graph | ⚠️ beads ledger |
| **Firstmate** | ✅ secondmates | ❌ **forbidden by policy** | ✅ zero-token watcher | ❌ prose briefs | ❌ | ❌ `learnings.md` |
| **AO** | ❌ flat | ✅ terminal attach | ✅✅ best-in-class | ❌ none | ❌ | ❌ |
| **Fusion** | ⚠️ multi-node | ✅ chat + @mention rooms | ⚠️ mixed | ✅ stages + gates | ❌ | ❌ |
| **bernstein** | ❌ | ⚠️ TUI only | ✅✅ zero LLM | ✅ YAML DAG | ❌ | ❌ |
| **tutti** | ✅ `workflow` step | ⚠️ focus mode | ✅ SSE + telemetry | ✅ TOML | ❌ | ⚠️ artifacts |
| **agent-runbook** | ⚠️ step-level | ❌ | ✅ files not context | ✅✅ best-in-class | ❌ | ⚠️ JSON schemas |
| **GraphCode** | ✅ spawn edges | ✅✅ `node send` | ⚠️ predicates | ❌ | ✅✅ **only one** | ❌ |
| **guild** | ❌ | ❌ | ✅ SQLite | ❌ | ❌ | ✅✅ **only one** |
| **hcom** | ⚠️ spawn | ✅✅ `@name` | ✅ SQLite events | ❌ | ⚠️ tags, unrendered | ❌ |
| **Claude Code Agent Teams** | ❌ **explicitly none** | ✅✅ native, documented | ✅✅ mailbox+task list only | ⚠️ subagent `.md` roles + plan gates | ❌ | ❌ |
| **OpenHands** | ✅ file-based agents | ⚠️ resume by `task_id` | ✅✅ `TaskObservation` | ✅ `.md`+YAML, skills, plugins | ❌ | ⚠️ skills |
| **Sculptor** | ✅ skills-as-agents, CI babysitter | ✅ per-agent tabs | ✅✅ **control protocol / RPC**, todo steps, context % | ✅ 6-stage workflow, durable artifacts, resumable | ❌ | ⚠️ artifacts |
| **Vibe Kanban** (dead) | ✅✅ **MCP recursive spawn, per-child backend** | ✅ sessions | ✅ normalised executor streams, typed enums | ⚠️ issues+relationships | ❌ | ❌ |

### 6.3 What is actually novel

Stripping out everything already shipped, the genuinely unclaimed territory is:

1. **Reconciliation semantics for out-of-band human intervention.** This is the strongest idea in
   the braindump and nobody has solved it. Firstmate is the only project that even *names* the
   problem — "direct captain intervention in crewmate windows is treated as authoritative but
   reconciled at the next supervision review" — and its answer is a prose rule an LLM is asked to
   follow, not a mechanism. Claude Code Agent Teams lets you message a teammate directly and simply
   does not tell the lead. If the human can talk to any leaf, **the controller's model of the world
   silently goes stale**, and every tool in this survey either ignores that or hand-waves it. Build
   the machinery: intervention events in the state log, controller re-derivation, explicit
   "your plan is stale" signalling. **This is the hardest and most defensible problem here.**

2. **Human-owned blocking steps as a first-class template primitive.** agent-runbook's
   `quality_check` dispatches an `@supervisor` *agent*; Fusion's gates can be human or AI;
   Ivy-Tendril's and bernstein's gates are automated checks; Claude Code's plan approval is decided
   by the *lead*, autonomously; Codex's `approval.reviewer = auto_review` routes approvals to a
   *reviewer subagent* instead of to you. **Claude Code's dynamic workflows document the absence
   outright — "no mid-run human input by design… for sign-off between stages, run each stage as its
   own workflow."** Nobody has a step type meaning *"stop — this is a manual test, a person types
   the result here, and the status board shows it blocking-on-human."* That is braindump §5 step 10.
   The market skipped it because everyone is optimising for autonomy, not for keeping the human
   genuinely in the loop — and the strongest evidence it's a real gap is that the biggest vendor
   wrote the limitation into its own docs.

   *(The one design worth copying: **Codex's approval overlay surfaces from an inactive child thread
   with a source label, and `o` opens that thread before you decide.** That is escalation-from-leaf
   without general addressability.)*

3. **The rendered communication graph as the primary interaction surface.** Only GraphCode does it,
   at 11 stars, macOS/Swift-only, with no template layer. Everyone else renders a *tree* (org chart,
   agent tree, `members` array) or a *board* (kanban). A general graph where an edge is a
   *capability* ("these two may communicate") rather than a completed handoff, and where the human
   is a first-class node that can re-attach anywhere, is not solved. Weakest of the three — it is a
   UI affordance, and Gas Town/5dive get 80% of the value from a tree.

4. **The union itself.** Nesting + direct addressing + zero-context control + declarative templates
   + a graph + tool-based memory in one coherent, multi-backend product. Each part is a solved
   problem; the integration is not. This is a real but *modest* claim — an integration play, not an
   invention. Be honest with yourself that that is what it is.

Meanwhile, two braindump items should be reclassified as **already built, use don't rebuild**:
- **§4 Learnings plugin** → this is [guild](https://github.com/mathomhaus/guild), almost exactly:
  MCP tools, SQLite, typed knowledge kinds, auto-loaded principles, hybrid BM25+vector retrieval by
  relevance. Apache-2.0, Go, single binary.
- **§3 Tooling plugins over markdown files** → guild again (quests/lore/oaths/briefs as MCP tools),
  plus herdr's `herdr-plugin.toml` marketplace with 506 plugins.

### 6.4 Strategic risk

The braindump's own warning — "setup theatre: building orchestrators instead of shipping features"
— is called out by name in the Firstmate community writeup. Four compounding pressures:

1. **~200 projects**, most under a year old, most functionally identical.
2. **A consolidation wave already happened** — Vibe Kanban (27.7k★) shut down for lack of a business
   model, Crystal deprecated, Terragon dead, uzi abandoned, container-use dormant, HumanLayer's OSS
   repo deprecated in favour of a $100/user/mo proprietary product. **Stars do not equal survival.**
3. **Anthropic is shipping it natively** — agent teams and agent view give away direct addressing,
   structured state, worktrees, and a status board.
4. **GitHub is shipping it as a free-at-the-margin platform feature** — Agent HQ mission control
   over Claude, Codex, Jules, Cognition and xAI, bundled into Copilot subscriptions.

**The honest question is not "how do we differentiate a 201st orchestrator."** It is whether the
three genuinely-novel pieces (§6.3) are worth building *for our own use*, on top of a substrate
someone else maintains, and whether they'd be better contributed to Gas Town or AO than shipped
standalone.

---

## 7. What to fork / borrow / ignore

### Fork candidates (in order)

1. **[Gas Town](https://github.com/gastownhall/gastown)** — MIT, Go, 17.5k★. Already has nesting,
   structured state, TOML workflow templates, direct agent attach, merge queue. Adding a graph view,
   human-gate step type, and reconciliation semantics is a *much* smaller job than building from
   zero, and you inherit the community. **Read this repo before writing a line of code.**
2. **[AO](https://github.com/AgentWrapper/agent-orchestrator)** — Apache-2.0, Go daemon + Electron,
   8.8k★. Fork for the state layer if you want the best OBSERVE/DERIVE model and ports-and-adapters
   discipline; you'd be adding nesting + templates + graph.

### Borrow (specific, concrete)

| From | Take |
|---|---|
| **agent-runbook** | The YAML step-type taxonomy verbatim: `inline / agent / script / parallel / branch / loop / checkpoint / quality_check`. Plus JSON-Schema-typed step outputs and **build-time contract validation** — that's how you make templates *validatable*, which is braindump principle #1's whole point |
| **AO** | OBSERVE → durable facts → DERIVE; "display status is never stored"; `activity_state` enum; SQLite `change_log` triggers + CDC poller + SSE fanout; "failed probes are NOT proof of death"; ports-and-adapters layering |
| **bernstein** | Deterministic Python/Rust scheduler with **no model in the coordination loop**; completion gates as objective predicates (tests, lint, typecheck, file existence, git status) |
| **Firstmate** | The `status` (append-only wake events) vs `meta` (current facts) file split; the wake taxonomy `signal:/stale:/check:/heartbeat:`; ship-vs-scout task shapes with promotion; the "human intervention is authoritative, reconcile at next review" rule |
| **tutti** | `workflow` as a step type (free nesting); typed artifacts with `artifact_glob`/`inject_files` copied into the target worktree; run checkpoints + `--resume` |
| **Fusion** | Oversight levels `off / observe / steer / autonomous` as the user-facing knob for "customizable controller" |
| **GraphCode** | Edge semantics: **hand-off** (fires on source resolve) vs **message** (direct input) vs **spawn** (conditional, cycle-guarded). This is the answer to "what does an edge physically mean" |
| **hcom** | `@name` / `@tag` addressing; mid-turn message delivery between tool calls; wake-idle-agent semantics; file-edit collision detection across agents |
| **5dive** | One chat-app thread per agent as the direct-addressing UX; task parking with tap-to-answer at human gates |
| **guild** | Don't reimplement — **use it**, or copy its schema: Quest / Lore (typed kinds) / Oath / Brief over MCP + SQLite with hybrid retrieval |
| **kandev** | Per-step agent binding in portable YAML; ACP for multi-backend |
| **herdr** | The substrate itself. Semantic agent states, `agent.wait`, `pane.report_agent`, `events.subscribe`, `herdr-plugin.toml` |
| **Sculptor** | **Drive Claude Code as a streaming-JSON process with its control protocol enabled** (and Pi in RPC mode) instead of scraping a PTY — this is the single best answer to "how does the controller see state." Plus: workflow stages as named agents emitting **durable on-disk artifacts**, making stages resumable and skippable |
| **Vibe Kanban** (dead, Apache-2.0) | **Expose the controller's own powers to agents as MCP tools** (`start_workspace`, `create_session`, `run_session_prompt`, `create_issue`, `create_issue_relationship`) — that is how you get nesting for free and let a child pick its own backend. Also its `StandardCodingAgentExecutor` trait + Rust→TS codegen for compile-time-enforced status enums |
| **OpenAI Symphony** | Its `SPEC.md` lifecycle state machine (`Unclaimed→Claimed(Running\|RetryQueued)→Released`; run phases through `Stalled`/`CanceledByReconciliation`) and the **`WORKFLOW.md`** pattern: YAML front matter for config + hooks, Markdown body as a Liquid-rendered prompt template |
| **Conductor** | Its **public OpenAPI spec** as a status-enum reference (`initializing/ready/sleeping/archived/deleted/updating`, `idle/working/error`), the 5-layer TOML config precedence model, and the hard-won race-condition rule: **"wait for `working` before trusting `idle` — a queued prompt hasn't started"** |
| **Claude Code Agent Teams** | The on-disk shape: per-agent mailbox JSON with validation-and-drop on malformed entries; task list with dependencies auto-unblocked on completion and **file-locking on claim**; `TeammateIdle`/`TaskCreated`/`TaskCompleted` hooks with exit-code-2-to-reject; plan-approval loop; and critically the **security property that an inter-agent message can never carry human consent** |
| **OpenHands** | `TaskObservation{task_id, subagent, status, text}` to the parent + **full transcript persisted to disk and re-engageable by `task_id`** — detail without context cost |
| **Codex** | The **approval overlay that surfaces from an inactive child thread with a source label, `o` to open that thread before deciding** — escalation from a leaf without general addressability. Also `fork_turns` (control how much parent history a child inherits) and **canonical task paths** (`/root/research/api`) instead of opaque agent IDs — that path syntax is a natural addressing scheme for a nested controller tree |
| **GitHub Agentic Workflows** | Markdown + frontmatter compiled to a **hardened lockfile**, writes only through declared **`safe-outputs`**, and an **`engine:` key** selecting the backend per workflow. The security model (declare your writes, compile to something auditable) is better than anything else here |
| **Kiro** | **Specs** as a first-class artifact (requirements → design → implementation tasks) plus **steering files** applied across every surface — the strongest spec-driven-development framing in the market |
| **codecast** | Fallback state derivation from agents' own JSONL transcript files when an agent won't self-report |
| **Ouijit** | All CLI output as JSON for piping — good hygiene for principle #2 |

### Reconsider entirely

Before building, weigh three cheaper paths:

1. **Set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` and use it for a week**, and try
   `.claude/workflows/*.js` dynamic workflows alongside it. Between them you get direct teammate
   addressing, structured-state supervision, a shared task list with dependencies and file locking,
   plan-approval gates, `TeammateIdle`/`TaskCreated`/`TaskCompleted` hooks, and programmatic
   multi-agent pipelines — for free. Find out empirically which of the documented limitations (no
   nesting, no resume, Claude-only, no declarative templates, **no mid-run human input in
   workflows**) actually hurt before building a system to fix them.
2. **Contribute the three novel pieces to Gas Town or AO** rather than shipping the 151st
   orchestrator. Both are permissively licensed, actively maintained, and already have the boring
   80%.
3. **If you do build:** the thinnest viable wedge is *not* another runner. It is a
   **template/gate/reconciliation layer** that sits on top of herdr (or ACP directly), reads
   structured state, and adds exactly the three things nobody has. Everything else — panes,
   worktrees, adapters, kanban — is undifferentiated work that six projects will give you.

### Ignore

- **The ~40 desktop apps / web dashboards** that are "worktree + kanban + terminal tabs" (Emdash,
  Mux, Clave, Superset, Nimbalyst, Proliferate, diri, supacode, parallel-code, t3code, …). Fully
  commoditised, no orchestration model, nothing to learn. Note **superset is Elastic-2.0, not OSI
  open source**, and **Claude Squad and kandev and coder/mux are AGPL-3.0** — check before copying
  code.
- **ruflo / paperclip** despite 67k and 76k stars — the star-to-substance ratio is poor, the
  abstractions (Raft consensus, Byzantine fault tolerance for coding agents) do not solve our
  problem, and ruflo runs standalone processes with no worktrees or tmux; much of its value is
  prompt scaffolding.
- **Everything in the graveyard** as a dependency: Vibe Kanban, Crystal, Terragon, uzi,
  container-use, `parruda/claude-swarm`. Read Vibe Kanban's and Crystal's *code*; don't adopt them.
- **Personal-assistant category** entirely (openclaw et al.) — different product.
- **CompanyHelm, Orkas, shire, Traycer, Devlo** — small, generic, nothing distinctive.

---

## 8. Confidence and caveats

- Star counts, licences and last-push dates for the ~35 most important repos were read from the
  **GitHub API**, not badges. The long tail of the ~200-project awesome-list contains many
  three-month-old, sub-200-star, plausibly AI-generated projects — **do not cite from it without
  checking the API**.
- **Untrivial/AgentWrapper `agent-orchestrator` (AO)**: the repo description claims a planner that
  "spawns agents"; the README reads as flat and human-supervised. **Its hierarchy claim is
  unverified** — check before treating it as a nesting precedent.
- **Vibe Kanban's recursive MCP nesting** is inferred from the tool list, not from a running system.
- **OpenAI Symphony's `WORKFLOW.md`** detail comes from `SPEC.md`, not a live deployment.
- **Conductor** is closed source; behaviour is from its public docs and OpenAPI spec only. Its
  `/docs/configuration` page 404s.
- **Sculptor's product page** contradicts its own repo on supported models — trust the repo.
- **GitHub's docs site has no reference page titled "Agent HQ" or "mission control"** (404s on the
  obvious URLs). Those specifics come from the [launch blog](https://github.blog/news-insights/company-news/welcome-home-agents/)
  and secondary coverage. The doc-backed GitHub facts are: the cloud coding agent, `/fleet`, Agentic
  Workflows, plugins, third-party agents (Claude + Codex), and
  [control-plane GA, 2026-02-26](https://github.blog/changelog/2026-02-26-enterprise-ai-controls-agent-control-plane-now-generally-available/).
- **"ACP is under the Linux Foundation"** appears in secondary sources but is **contradicted by
  ACP's own governance page** (Zed + JetBrains interim, foundation move pending).
- **Codex V2 nesting depth** and **which users get V1 vs V2** are unresolved — V2 can be force-enabled
  by model metadata, which flips the direct-addressing answer. Codex docs moved:
  `developers.openai.com/codex/*` → `learn.chatgpt.com/docs/*`.
- **Devin's "Multi-Devin"** page no longer appears in `docs.devin.ai/llms.txt` — the 2025
  manager-spawning-workers pattern appears de-emphasised, but I could not confirm removal vs re-homing.
  **Devin Desktop is the rebranded Windsurf**, retaining Cascade as its agent.
- **Kiro's subagent reference page 404s**; its "Crew" description reads oddly for an AWS IDE product
  and warrants a second source.
- **Blitzy (403), Tembo (unresearched), Trae (empty fetch), Ona, Antigravity 2.0** are thinly covered.
- Web-search budget was exhausted during this research (200/200), so late-stage discovery relied on
  the GitHub API and direct doc fetches. A few niche 2026 tools may be missing.
</content>
