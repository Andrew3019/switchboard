# Plan — modules, decisions, risk

Companion to `braindump.md` (what) and `PRINCIPLES.md` (what not to do).

> **Written before v0 was built; v0 now exists.** What has actually shipped is M1 ∪ M2 ∪
> M3 (+ the readouts) — see `POC.md` for the built design and `REVIEW.md` for what was
> found reviewing it. Two things to know while reading:
>
> - **The command is `sb`.** `wf` was the placeholder this document itself flags as one.
> - **D1 was decided against the recommendation: it is Python, stdlib only.** The
>   reasoning is at D1 below.
>
> Everything from M4 down is still unbuilt and this is still the plan for it.

---

## The shape of the thing

```
                    ┌─────────────────────────────┐
                    │  UI: status board (+graph)  │   M7
                    └──────────────┬──────────────┘
                                   │ reads
┌──────────────┐            ┌──────▼──────┐            ┌──────────────┐
│ herdr        │◄───────────│   STORE     │───────────►│ learnings /  │
│ (display)    │  report-   │  SQLite     │            │ todo MCP     │
│              │  agent     │             │            │ (own proc)   │
└──────────────┘   M8       └──▲───────▲──┘   M1       └──────────────┘   M6
                                │       │
                    ┌───────────┴──┐ ┌──┴───────────────┐
                    │ STEP MACHINE │ │ GATE + RECONCILE │
                    │      M4      │ │       M5         │
                    └───────┬──────┘ └──────────────────┘
                            │ drives
                    ┌───────▼────────────────────────┐
                    │ BROKER (sb) + status contract  │   M3
                    └───────┬────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │ BACKEND ADAPTER│   M2
                    └───┬────────┬───┘
                   Claude Code   Codex
```

**The seam that matters:** everything below M3 is vendor-specific and unstable;
everything above it is ours and boring. Keep that line clean and the project survives
Anthropic and OpenAI shipping breaking changes.

---

## Modules

| # | Module | Does | Depends on | Size |
|---|---|---|---|---|
| **M1** | **Store** | SQLite + typed accessors. `runs`, `step_results`, `step_rounds`, `agents`, `edges`, `gates`, `learnings`. Single source of truth; everything else is a view. | — | S |
| **M2** | **herdr adapter** | The *only* file that knows herdr exists: `spawn`, `poke`, `set_state`, `wait`, `worktree`, `attach`. Wraps CLI now, socket later. Also our insurance — if herdr dies, we swap this. | — | S |
| **M3** | **Broker + status contract** | ~~The `wf-bus` MCP server injected into every agent (`wf__report`, `wf__send`, `wf__ask`) + `Stop` hook.~~ **Shipped as the `sb` CLI**, with the verbs named after wants rather than mechanisms (`report`/`send` were the mechanism names P0 rewrote). No MCP server and no `Stop` hook yet — both are shims over the same verbs and can be added without re-teaching anything, which is the point of C13. Turns narration into rows. | M1, M2 | M |
| **M4** | **Step machine** | Reads template YAML, drives steps, `check`/`retry`/`goto`+`max_visits`, writes checkpoints, `side_effects: external` handling, git worktree + per-step commit. Pure logic — testable with a fake backend. | M1 | M |
| **M5** | **Gate + reconciliation** | Human gates that block and resume; the watcher/notifier nobody built. Marks `status_stale` on out-of-band human contact. **Wired leaf → store → UI, bypassing the parent** (C14) so parent context never grows with blocks. **The novel part.** | M1, M3 | M |
| **M6** | **Learnings + todo MCP** | Separate process. `learnings_get/add/update/labels` over labels. Standalone-useful. | — | S |
| **M7** | **Status board** | Web UI over M1. What's blocked, what needs me. | M1 | M |
| ~~M8~~ | *folded into M2* | herdr display is just more adapter calls. | — | — |
| ~~M9~~ | *dropped* | C1 makes it a tree, not a graph. A tree renders in M7 as indentation. | — | — |

**Independently shippable today:** M6 (useful with zero orchestration).
**Everything else gates on M3.**

---

## Decisions

### D1 — Language / runtime  ← *biggest fork*  · **DECIDED: Python, stdlib only**
- **TypeScript** (recommended): Claude Agent SDK is first-class TS, MCP SDK is best in TS,
  shares types with the web UI for free, fastest iteration for a personal tool.
- **Rust**: matches herdr, enables the Vibe Kanban `#[derive(TS)]` pattern, better daemon.
  Slower to iterate.
- **Go**: what both Gas Town and Gas City chose. No specific advantage for us.

*Recommendation was TypeScript.* Iteration speed dominates for a tool with one user.

**What was built is Python, with no dependencies at all** — `sqlite3`, `tomllib`,
`argparse`, `subprocess`. The recommendation's premises did not survive contact with the
design:

- *"Claude Agent SDK is first-class TS."* We do not use an agent SDK. herdr spawns the
  agents and we shell out to its CLI, which is language-agnostic by construction (C13).
- *"MCP SDK is best in TS."* There is no MCP server yet, and PLAN's own rule 5 below says
  MCP is an optimisation over the CLI rather than the foundation. When it arrives it wraps
  `sb`; it does not have to be written in the same language.
- *"Shares types with the web UI."* There is no web UI, and the readouts all emit `--json`.

Against that, stdlib Python has no install step, no build step, no lockfile and no
`node_modules` in a tool whose entire job is to be invoked a few hundred times a day by
short-lived subprocesses. `bin/sb` is five lines. Iteration speed did dominate — it just
pointed somewhere else.

### D2 — Status mechanism  ← *blocking, resolve empirically* · **SIDESTEPPED, not resolved**
`Stop`-hook-enforced `wf__report` tool call (works on both backends, per `[06]`) vs.
native `--json-schema` / `--output-schema` (per `[04]`). Reports conflict (F16).
**Test it. One afternoon. Nothing else gets designed until this is known.**

It was never tested, and everything else got designed anyway — because the third option
turned out to be enough: **the agent runs `sb done "<summary>"` itself**, and that is a
row. No hook, no schema, no backend-specific behaviour, so F16 stops mattering.

The cost is exactly what C6 warns about: nothing *enforces* it, and an agent that ends its
turn without reporting is invisible to the store. That is not hypothetical — it is the
single most common failure in this system. What was built instead of enforcement is
**detection**: `status.py` joins the store against herdr and names the disagreement
(store `working`, herdr `idle` → STALLED). Surfacing beats guessing (C9), and it works on
both backends today. A `Stop` hook is still the right answer and is still unbuilt; D2 is
open, it is just no longer blocking.

### D3 — Is there an LLM controller in v1?
*Recommendation: no.* A deterministic step machine only; escalate to a human gate instead
of to an LLM. Add LLM judgment later, at one named place, if the gates prove too noisy.
Cheapest way to honour "the controller reads state, not transcripts" is to not have one.

### D4 — Which repo do we build this around?
Must be a real project with real work. Determines every early template.
**Unanswered — yours to pick.**

### D5 — State location
Per-repo, for runs, gates, learnings; a small global registry of known repos. Per-repo is
what avoids F7.

**Shipped at `$(git rev-parse --git-common-dir)/agentflow/state.db`, not `<repo>/.agentflow/`.**
`.git` is already shared by every worktree of a repo, which is required rather than tidy:
the top-level orchestrator lives on `main` while its children live in worktrees, and
parent links do not survive them looking at different stores. It also cannot be committed
by accident and it dies with the repo. There is no global registry yet; nothing has needed
one, since the store is resolved from wherever `sb` was run.

### D6 — Learnings: build or adopt `guild`?
30-minute eval of `guild` before writing M6.

### D7 — Do we depend on inbound-to-live-agent in v1?
Claude channels are a **research preview** needing
`--dangerously-load-development-channels`; Codex `turn/steer` is experimental `[06]`.
*Recommendation: no.* v1 delivers inbound at step boundaries only. Direct human→leaf
messaging is a v2 feature layered on M2 once the primitives stabilise. This defers our
least-differentiated feature (13 of 13 tools already have it, `[02]`) and de-risks v1.

---

## Hardest parts, ranked

**1. The status contract (M3).** Everything depends on it, and it's a compatibility
problem against two moving targets, not a design problem. Two research reports already
disagree about what works. Reliability is the whole game: an agent that sometimes fails
to report is worse than no controller.

**2. Reconciliation (M5).** Genuinely novel, so no prior art to copy — nobody has solved
what a supervisor should believe after a human quietly redirected an agent. Subtle, and
easy to get *plausibly* wrong in a way that only shows up under load.

**3. Inbound delivery (M2).** Hard because it's outside our control — a research-preview
flag on one backend, an experimental JSON-RPC surface on the other. D7 defers this.

**4. Human gate watcher (M5).** Medium. Gas City proves the data model works and left the
watcher unbuilt; notification, resume, and timeout are the work.

**5–9. Everything else is easy.** Step machine (heavy prior art), store, learnings MCP,
status board, herdr display, graph.

**The pattern: every hard part is at the boundary with the agent CLIs. Everything we own
outright is boring.** That's the correct shape — and it argues for spiking the boundary
before building anything above it.

---

## Building on herdr

### What herdr already gives us (delete from our scope)

| Our need | herdr provides | Module impact |
|---|---|---|
| Spawn an agent | `agent start`, pane/tab/workspace management, `integration install claude\|codex` | **M2 mostly disappears** — no PTY code, no per-CLI quirks |
| Survive restarts, keep agents alive | background server; reattach from any terminal or over SSH | **our daemon requirement mostly disappears** |
| Git worktree per run | `worktree create --branch --base` | M4 gets it for one call |
| Human talks directly to a leaf | attach to the pane and type | **C14's exemption is free** |
| Notify a live agent | `agent prompt <id>` injects into a running session | **the inbound primitive, without channels** — see below |
| Wait until an agent is blocked | `agent wait --until blocked` | M3 |
| Working / blocked / idle state | pane status, and `pane report-agent` to take **authoritative** state | M3 — see caveat |
| Somewhere to render our UI | `plugin.pane.open`, `agent.view.set`, notifications | M7/M8 for near-free in v0 |
| Event stream | `events.subscribe`, 28 event types | C10 — event-driven, no polling |

**Caveat that shapes the design:** herdr's *default* state detection is regex over the
agent's TUI, and `agent read` returns raw terminal scrapes (alt-screen agents lose
scrollback permanently) `[01]`. So: **never read state out of herdr — push state into it**
via `pane report-agent`. herdr renders; we decide (C5).

### The messaging design this suggests

Content and correlation live in our store; herdr does delivery only.

```
sb ask B "question"
  1. write message row  → our store
  2. herdr agent prompt B  "you have mail: run `sb inbox`"   ← poke, not payload
  3. block on our store until B's reply row appears
```

The message body never travels through a terminal, so nothing is scraped and nothing is
lost to alt-screen. herdr is the doorbell; the store is the mailbox. This also sidesteps
D7 entirely — no channels, no `turn/steer`, works identically for Codex.

### What herdr does NOT do — this is the product

Templates, the step machine, gates and the human-gate watcher, run history, the status
contract, learnings. Nothing in herdr conflicts with any of it `[02]`.

### Fork, clone, or build on top?

**Build on top. Do not fork.**

- herdr ships ~weekly (54 releases in 4.5 months `[01]`). A fork means merging upstream
  forever, and we'd be merging a Rust codebase we don't otherwise touch.
- We need *zero* internal changes — everything we want is already exposed.
- Their own doctrine: *"There is no separate plugin SDK — the entire Herdr CLI is the
  plugin API."* The supported extension path is the one we want anyway.
- Apache-2.0 means forking is *allowed*; that's not a reason to do it.

**Clone it read-only for reference** (reading the API schema and source is useful) —
that's different from forking, and carries no maintenance cost.

### How to build on top — concretely

1. **Separate repo.** herdr is a *dependency you install*, like `git` or `jq` — a binary
   on `$PATH`, not code in our tree. `herdr update` keeps it current; nothing to merge.
   That is the entire benefit of not forking.
2. **Two ways to talk to it.** Shell out to `herdr …` (simple, start here), or open
   `~/.config/herdr/herdr.sock` and speak newline-delimited JSON `{id, method, params}`
   (90 methods; needed for `events.subscribe`). Use the CLI for v0, add the socket when we
   want the event stream.
3. **One adapter file.** Every herdr call goes through a single module — nothing else in
   the codebase knows herdr exists. When their API shifts, we fix one file. This is also
   our insurance against bus factor (one dominant maintainer, YC-backed startup `[01]`):
   if herdr dies, we swap the adapter, not the system.
4. **Pin a minimum version.** Check `herdr --version` at startup and fail loudly below it.
5. **Contract tests.** A small suite exercising only the herdr commands we depend on
   (`agent start`, `agent prompt`, `agent wait`, `pane report-agent`, `worktree create`).
   Run after every `herdr update`; an upstream break surfaces immediately instead of
   mid-run.
6. **Optionally ship as a herdr plugin later** (`herdr-plugin.toml`, actions + panes +
   event hooks) so our board lives inside their UI. Not needed for v0.

### Revised v0 in light of this

M2 shrinks to "call herdr", M8 folds in from the start, and the PoC becomes:
**our store + six verbs + herdr for spawn/poke/display.**

---

## The wrapping doctrine — one CLI is the whole API

herdr's own answer, and it's the right one: *"There is no separate plugin SDK — the
entire Herdr CLI is the plugin API."* `[01]`

**Everything is a `wf` subcommand. Every other surface is a thin shim over it.**

```
        agents ──Bash──►┐
        hooks ──────────┤
        MCP server ─────┼──► sb CLI ──► store (SQLite)
        UI backend ─────┤
        us, manually ───┘
```

Rules that make future tooling cheap:

1. **Every command takes and emits JSON** (`--json`). Wrapping becomes mechanical.
2. **The store is the only shared state.** No module calls another module; they meet in
   SQLite. Kills integration coupling before it starts.
3. **A new capability = one subcommand + one row type.** It appears in the MCP server,
   the hooks, and the UI for free.
4. **The agent-facing surface stays tiny and frozen** — 5–6 verbs. Internals churn
   freely; the contract agents depend on does not. This is what lets us rewrite
   everything underneath in week 3 without re-teaching the agents.
5. **MCP is an optimisation, not the foundation.** Agents can shell out to `wf` on day
   one with zero integration work. Generate the MCP server from the CLI's own command
   schema later, when token efficiency and typed args start to matter.

---

## v0 — the shitty version (the PoC)

**Goal: two Claudes talking to each other through an abstraction we own.** Nothing else.
No skills, no plugins, no templates, no UI, no gates, no Codex.

**PoC = M1 ∪ M2 ∪ M3**, each at v0 quality. Those three unioned is the whole thing; the
rest of the modules attach to it later without redesign.

### Delivery: doorbell + mailbox

Only the **asker** blocks. The **receiver** never polls — herdr pokes it.

```
A: sb ask B "question"
     1. write message row                          → store
     2. herdr agent prompt B "mail: run `sb inbox`" → doorbell (no payload)
     3. block until B's reply row appears           → store

B: (poked BETWEEN turns) sb inbox  → returns the message, non-blocking
   … does the work …
   sb tell A "answer"              → store → unblocks A
```

Payloads never cross a terminal, so nothing is scraped and nothing is lost to alt-screen
(C5). No channels, no `turn/steer`, no research-preview flags — D7 evaporates, and it
behaves identically on Codex.

**"Poked mid-session" was wrong, and it cost a mechanism.** `agent prompt` INTERLEAVES:
it is injected into the turn the agent is in the middle of, rather than queued behind it
(re-verified against a genuine 60s turn — the poke was handled at +13s, the running task
finished at +63s). So the doorbell is held back while the target is working and rung once
it is idle; `Broker.flush_pending` is that trigger, and it runs at the start of every `sb`
command and on every pass of a blocked `ask`. When an events daemon exists it replaces the
trigger, not the model.

`--wait` therefore exists only on the ask side. Add a timeout so a dead child can't hang
a parent forever; on timeout the asker gets `timed_out` and decides (C9: route to a gate).

### v0 CLI surface (the frozen part)

> **Name:** `wf` is a placeholder ("workflow"), picked for being short to type. Nothing
> depends on it.

Verbs are named after **wants, not mechanisms** (P0). An earlier draft used
`send`/`inbox`/`report` — mechanism names — which left agents doing protocol work:
correlating replies by hand and racing between "send" and "wait".

| Agent wants | Command | Notes |
|---|---|---|
| "do this for me" | `sb delegate "<task>" --role <role>` | spawn + assign in one; returns the child's name |
| "I need an answer" | `sb ask <who>… "<q>"` | **blocks, returns the reply.** Correlation is the tool's problem, not the agent's. Takes several targets — the fan-out is concurrent |
| "FYI, don't wait" | `sb tell <who>… "<msg>"` | fire and forget |
| "anything for me?" | `sb inbox` | non-blocking — you were poked |
| "here's your answer" | ~~`wf reply <msg-id>`~~ | **RETRACTED — no `reply` verb.** A plain `sb tell` back to the asker satisfies the pending ask; making an agent quote a message id is the protocol work P0 exists to remove |
| "I'm done" / "I'm stuck" | `sb done "<summary>"` / `sb block "<why>"` | the status contract, in agent language |
| "who can help?" | ~~`wf who`~~ | **RETRACTED — never built.** `sb status` answers it, and "roles + capabilities" is a roster, which C3 says there isn't |

> `$WF_AGENT_ID` is retracted too, and finding #16 in `POC.md` is why: env injected at
> spawn silently vanished when pane creation changed from `pane split` to `tab create`,
> and every child re-parented to `human`. Identity comes from `HERDR_PANE_ID`, which herdr
> puts in every pane whether or not we made it.

Agents learn these from ~8 lines via `--append-system-prompt` — the "shitty skill
injection", and the only one needed for a long time.

**`ask` is the load-bearing verb.** Reply threading, correlation ids, and the
send/wait race all live inside it, where agents never see them.

### Storage — different data, different store

Not inconsistency; matched to access pattern. **Agents see none of it**, so every choice
here is reversible (P0).

| Data | Store | Why |
|---|---|---|
| Templates, config | **YAML** in the repo | human-authored, hand-edited, diffed, commented, in git |
| Learnings | **JSON** files in the repo | append-mostly, curatable, belongs in git; the tool abstracts layout anyway, which was always the point |
| Runtime state — messages, agent states, runs | **SQLite** | **concurrent writes.** N agents on a JSON file = read-modify-write = lost messages. Plus atomic crash safety (a partial JSON write is a corrupt file) and cheap `--wait` polling. One file, no server, stdlib. |

At two-agent PoC scale JSON files would genuinely work. SQLite costs ~nothing and
concurrency bites the moment agents run in parallel, so start there.

### v0 module quality

| Module | v0 (in PoC) | grows into |
|---|---|---|
| **M1 Store** | 3 tables: `agents`, `messages`, `events` | + runs / step_results / gates / learnings |
| **M2 herdr adapter** | shell out to `herdr` for `spawn` / `poke` / `set_state` | socket API, `events.subscribe`, contract tests |
| **M3 Broker** | the `wf` CLI over M1 + M2. No MCP, no hooks | MCP shim, Stop-hook enforcement, Codex |
| M4 Step machine | — | reads templates, drives steps |
| M5 Gates | — | the novel part |
| M6 Learnings | — | separate MCP process |
| M7 Board | `sb status` printing a tree, plus a clickable `python3 -m switchboard.board` | herdr plugin pane, then web |

### v0 store schema (M1)

```sql
agents(   id, parent_id, role, task, state, herdr_pane, created_at, ended_at )
          -- state: spawning|working|blocked|done|failed
          -- parent_id NULL = root. Tree, not graph (C1). No edges table.

messages( id, from_agent, to_agent, kind, body, reply_to, created_at, read_at )
          -- kind: ask|tell|reply
          -- reply_to → messages.id  ← the correlation agents never see (P0/C2)

events(   id, agent_id, kind, payload_json, created_at )
          -- append-only. The board and any future replay read this.
```

Three tables, one file under the repo's shared `.git`, WAL mode. Everything later —
runs, gates, learnings — is more rows, not new plumbing.

### Done when

An agent can spawn a second agent, hand it a task, block until it reports back, and both
transcripts are irrelevant — the store alone says what happened.

**What v0 deliberately proves:** that the abstraction is enough. If two agents can
coordinate through six verbs and a SQLite file, then templates, gates, and the board are
all just *more rows*, and none of them need new plumbing.

---

## Sequence

Not module-by-module to production. **Build a shitty version of everything, then iterate.**
The modules are review boundaries and refactor seams, not delivery milestones.

**v0 — PoC.** M1∪M2∪M3 as described above. Two Claudes talking through six verbs.

**Review gate.** Walk each module separately, decide what's actually wrong, design
further. Do not extend v0 before this.

**v1 — shitty everything.** Add crappy M4 (one hardcoded template), M5 (a gate that's just
a blocking row), M2 (Codex behind the same verbs). M7 landed early — `sb status` is a
table and `switchboard/board.py` is the clickable version.
Nothing good, everything present.

**v2 — make the sharp parts sharp.** Resolve D2 properly, real gates + reconciliation
(M5), real board (M7), herdr display (M8).

**Later.** M6 (or `guild`), M9, and promotion of anything repo-specific that has now
earned generality by working twice.
