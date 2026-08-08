# Research synthesis

Cross-cutting conclusions from the six research reports in this directory. Read this
first; the numbered reports are the evidence.

| # | Topic | One-line verdict |
|---|---|---|
| 01 | herdr | Build on top. Apache-2.0. **Display, not control.** |
| 02 | Orchestrator landscape | Most differentiators already ship. Two survive. |
| 03 | Dual web/terminal UI | Two thin front ends over one typed state model. |
| 04 | Workflow engines | Build a small step machine, steal the CNCF format. |
| 05 | Memory / learnings | Build a small MCP server; the category solves a different problem. |
| 06 | Agent comms | MCP + Claude channels + Codex app-server. Ignore A2A/AG-UI/ACP. |

---

## 1. The headline: the original scope is mostly already built

Report 02 is the disconfirming one. Of the four claimed differentiators:

- **Human→leaf direct addressing** — ships in Claude Code Agent Teams, in nearly the
  same words. **13 of 13 tools examined preserve it.** The premise was wrong; Firstmate
  (which forbids it) is the outlier the intuition generalised from.
- **State-not-transcripts** — bernstein removes the LLM from coordination entirely;
  OpenHands' `TaskObservation` is better than what we sketched.
- **Nesting** — Gas Town (4 tiers), fractal, Vibe Kanban, herdr. And it is being
  **clamped industry-wide**: Gemini 0, Factory 0, Agent Teams 0, Cursor 2, Claude
  subagents 3 (after oscillating 5→0→3). Codex V2 blocks direct subagent input in code.
- **Declarative templates** — agent-runbook's YAML already has `loop` and
  `quality_check` as typed step types with build-time contract validation.

Plus, from report 04: **Claude Code 2.1.223 already ships a workflow engine** —
`.claude/workflows/*.js` with a `Workflow` tool (phases, schema-forced subagents,
worktree isolation, budget caps, `resumeFromRunId`). Imperative JS, same-session resume,
and — critically — **no human gates**. Its own docs say: *"For sign-off between stages,
run each stage as its own workflow."*

## 2. What is genuinely novel

Two things, and they are the same thing viewed from two angles:

1. **Human-owned blocking steps.** Claude Code's dynamic-workflow docs concede the hole
   outright: *"no mid-run human input by design."*
   **Narrowed by report 07:** Gas Town's `interactive = true` *is* a working durable
   gate, so "nobody ships a resumable human gate" is false. What remains true: nobody
   ships one that **separates decision from data and reconciles it** — Gas Town's is
   crude (`if step.Interactive || hasInteractive` changes dispatch for the entire
   formula), and Gas City's spec §4 honestly lists `gate type = "human"` as inert:
   *"no bundled watcher acts on them. Zero bundled formulas use `gate`."*
2. **Reconciliation semantics for out-of-band human intervention.** When a human talks
   directly to a leaf agent, every supervisor's world-model goes stale. **Nobody has
   solved this.** Firstmate alone even names it — as a prose rule.

Everything else in the braindump is table stakes we need in order to demonstrate these
two. **The controller is not the product. The human-gate + reconciliation layer is.**

Corollary: herdr is the right substrate precisely *because* it has no declarative
workflow layer to conflict with. That is the gap we occupy.

## 3. The strongest evidence against building this at all

Three independent retreats from bespoke agent scaffolding toward host primitives:

- **Vibe Kanban built structured task templates and then deleted them** — then shut down
  entirely at 27.7k stars for lack of a business model.
- **agent-os v3 deleted its workflow layer.**
- **Crystal is deprecated.** So are Terragon, uzi, and container-use.

This does not mean don't build. It means: build the two novel things, lean on host
primitives for everything else, and treat any urge to build general scaffolding as a
smell. Keep the surface small enough that a vendor shipping the feature is an
inconvenience, not an extinction event.

---

## 4. Architecture that falls out of the research

### Runtime: herdr, for display only

Apache-2.0 (relicensed from AGPL in 0.8.0), Rust, 25.1k★, one dominant maintainer
(Herdr Inc., YC F26). 90 socket methods over newline-delimited JSON on `herdr.sock`;
`events.subscribe` streams 28 event types.

**Do not drive agents through `agent send-keys` / `agent prompt`** — that is terminal
scraping by another name, and `agent read` returns raw scrapes only (alt-screen agents
like Claude and Codex lose scrollback permanently). herdr's default state detection is
literally regex over the TUI.

**Instead:** we drive the agent CLIs directly, and push authoritative state *into* herdr
via `pane report-agent`, which lets an external process take state authority (verified
live). herdr renders; we decide. The TUI can be a herdr plugin pane via
`plugin.pane.open`, and `agent.view.set` can replace herdr's agent list with our own.

Sharp edges: `agent wait` is **not turn-scoped** (gate on `state_change_seq`), pane IDs
are unstable across `pane move`, `agent start` needs a pre-made idle shell pane.

### Control plane: a broker daemon over SQLite

- **A graph edge is a routing permission**, enforced by one local broker. Outbound is an
  MCP tool call (`wf__send`, `wf__report`, `wf__ask`) from a single stdio server injected
  into every agent; sending to a non-adjacent node errors. The edge is a SQLite row.
  This makes the graph load-bearing rather than decorative.
- **Inbound to a live agent** — the primitive that makes the whole design possible:
  Claude Code **channels** (`capabilities.experimental['claude/channel']` →
  `notifications/claude/channel`) and Codex **`turn/steer`** via `codex app-server`
  (long-lived JSON-RPC 2.0: `thread/start|resume|fork`, `turn/start|steer|interrupt`).
  One `deliver()` abstraction over both.
- **Status is mechanically enforced, not requested.** A `Stop` hook blocks the agent from
  finishing without emitting `wf__report`. Both backends have hooks — Codex has 11 events
  with the same envelope and exit-2-blocks semantics as Claude Code.
- **Reconciliation:** any human event marks the run `status_stale`. The controller learns
  *that* a message happened, never *what* it said, and the Stop gate guarantees a fresh
  structured status within one turn.

### Templates: small step machine, borrowed format

Do not adopt Temporal/Restate/Inngest — they define workflows as **code, not data**, so
adopting one means writing an interpreter for our YAML anyway. Our durability need is
~10 checkpoints per run, all on step boundaries, all rows the status board needs regardless.
(DBOS is the named hedge: library-only, SQLite by default, no containers.)

Resemble **CNCF Serverless Workflow DSL v1.0** (named steps, `if`, `then: <taskName>`
backward jumps, retry-as-data), with GitHub Actions' `steps:` ergonomics, Kestra's
`Pause`/`onResume` gate, and Goose recipes' agent binding.

Key schema decisions:
- Ordered array — order is what renders "step 4 of 11"
- **One** loop mechanism: `goto` + **mandatory `max_visits`**. Unbounded back-edges fail
  validation — stricter than any surveyed engine, because here an infinite loop costs money.
- `retry` (transient failure) and `next` (semantic outcome) stay separate
- Gates split **decision from data** (per Airflow 3.1)
- **Snapshot the template into the run** — editing a template must not kill in-flight runs
- SQLite: `runs` / `step_results` / `step_rounds` — a loop re-entry deserves a row, not a
  counter. (`no-mistakes`, MIT 7.4k★, arrived at this schema independently.)

### Learnings: a small MCP server, not a memory system

The whole memory category (mem0, Letta, Zep, Cognee, Cipher, LangMem, …) solves *recall*
via embeddings. Ours is **dispatch**: at step N, inject the rules for step N. Only 2 of 14
systems support label retrieval with no query string. Adopting one buys an LLM call per
write, a vector DB, non-deterministic retrieval, and ~1k tokens of tool schema each.

Four tools: `learnings_get` (labels + any/all, returns grouped), `learnings_add` (returns
`near_duplicates`), `learnings_update` (`op` enum, soft-delete only), `learnings_labels`.
Labels are flat strings with a `facet:value` convention (`step:`, `risk:`, `area:`,
`kind:`) against a closed vocabulary in `labels.yaml`.

**The differentiator falls out of the template model:** bind labels to steps, and the
runtime injects the right learnings automatically. Devin needs a hand-written trigger
description per entry because it has no workflow model; our templates give us the trigger
for free.

Note: **guild** (MCP + SQLite, typed lore, hybrid retrieval) is essentially this, already
built. Evaluate before writing code.

### UI: two shells, one typed core

One codebase for both surfaces is **not** practical in 2026. Textual is out — its web
story is xterm.js streaming a TUI, `textual-web` is untouched since Aug 2024, and
**Textualize Ltd dissolved 17 Feb 2026**.

- Web: **`@xyflow/react` + `elkjs`** — independently chosen by Airflow 3.x in a
  from-scratch 2025 rewrite. ELK returns parent-relative coords and auto-sizes parents,
  matching React Flow's `parentId` contract, so nested controllers need no coordinate math.
  Benchmarked at 48ms / 111 nodes.
- Architecture: copy **Vibe Kanban** — Rust core with `#[derive(TS)]` generating frontend
  types. "Everything is data" enforced by the compiler.
- **The status board is the product; the graph is decoration.** Airflow's docs call the
  grid "the primary interface"; Temporal shipped no DAG at all; Metaflow, Trigger.dev and
  Inngest ship no graph library. Build #6 before #2.
- "openui" = **Open WebUI** — do not build on it. Chat data model, and it relicensed in
  v0.6.6 to a non-OSI license with a mandatory branding clause.
- Don't put UI schema in the workflow YAML. Templates describe work; rendering is the
  front end's business.

---

## 5. Unresolved conflict between reports

**Can `result.schema` be enforced natively?**

- **Report 04** says yes — `claude -p --json-schema` and `codex exec --output-schema`
  both exist, so no custom completion tool is needed.
- **Report 06** says no for Codex — `--output-schema` is gpt-5-only, incompatible with
  `exec resume`, and reportedly ignored when MCP servers are active
  (openai/codex#15451). It recommends a `Stop`-hook-enforced `wf__report` tool call instead.

These cannot both be right. **Resolve empirically before designing the status contract**,
since it's the load-bearing interface. Report 06's approach is the safer default: a Stop
hook works on both backends and doesn't depend on model or flag support. If 04 is right,
the schema flag becomes an optimisation, not the mechanism.

## 6. Read before writing code

- ~~**Gas Town** — closest thing to the whole vision, best fork candidate.~~
  **RETRACTED — see reports 07 and 08.** `gastownhall/gastown` is Steve Yegge's, and
  he killed it on 2026-08-03: *"Gas Town effectively burned down."* Maintenance mode
  since May, `main` frozen 2026-07-23. 17,482★ but 96 watchers; no one ever answered
  "has anyone shipped anything with this?" The metaphor is a closed Go enum, not
  decoration — role-add requests were closed unimplemented. Custom formulas are
  **half-wired** (#3322, open since March: authored steps never reach the polecat).
  Three blockers specific to us: non-code work is auto-rejected, **two towns on one
  machine actively corrupt each other** (fatal for work + personal repos), and it burns
  money at idle. **Borrow the overlay/directive split, the layered role schema, per-role
  model routing, and the failure catalogue. Do not fork, do not run.**
- **Gas City** (`gastownhall/gascity`, MIT, 1,082★, v1.4.0, active) — the successor, and
  the actual find. *"The orchestrator hardcodes zero roles — every role you knew is now
  configuration."* `gc rig add <path>` works on repos anywhere on disk, `GC_BEADS=file`
  drops the mandatory Dolt server, and its provider list already includes **herdr**.
  Its `formula-spec-v2` is a normative version of report 04's step machine, with `retry`
  and `check` correctly split. Evaluate properly before building anything.
- **AgentOrchestrator** (Apache-2.0, Go+Electron, 8.8k★) — best state engineering found
  anywhere: OBSERVE → durable facts → DERIVE, "display status is never stored",
  SQLite CDC → SSE, ports-and-adapters, 23 backends.
- **Firstmate** (MIT, bash, 3.0k★) — best low-context supervision prior art.
- **agent-runbook** — its YAML step types beat our draft.
- **guild** — our learnings plugin, already built.
- **no-mistakes** (MIT, 7.4k★) — the run/step_results/step_rounds schema.
- **CodeRabbit learnings** — provenance, usage stats, curation UI, redaction on write.
- **Claude Squad is AGPL-3.0** — do not vendor.

"AgentOrchestrator / AO" as a distinct product **could not be verified as prior art** —
the 8.8k★ Go+Electron project above is what the search surfaced. Worth confirming which
one was meant.

---

## 7. Recommended sequence

1. **Resolve the §5 conflict** — one afternoon, decides the status contract.
2. **Status contract + broker + SQLite schema.** `wf__report` enforced by a Stop hook on
   both backends. Nothing renders yet.
3. **Step machine + template YAML**, with the human-gate step type as a first-class
   citizen from day one — it's the novel part, not a later addition.
4. **Status board** (web first). This is the product.
5. **Learnings MCP server** — evaluate `guild` first; only build if it genuinely doesn't fit.
6. **herdr integration** — `pane report-agent` for state, `plugin.pane.open` for the TUI.
7. **Graph view** — last, and only if the board proves insufficient.
