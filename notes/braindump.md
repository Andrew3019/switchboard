# Braindump — customizable agentic workflow system

Unfiltered notes. Nothing here is committed to; it's a scratch space.

> **⚠️ Research done — read `research/00-synthesis.md` before trusting this document.**
> Six research reports landed after this was written. Headline: most of the claimed
> differentiators already ship elsewhere (human→leaf direct addressing is a documented
> Claude Code Agent Teams feature; Claude Code already has a `Workflow` engine). What
> survives as genuinely novel is **human-owned blocking steps** and **reconciliation
> after out-of-band human intervention**. Sections below are preserved as the original
> thinking, not as the current plan.

---

## Scope: a personal tool, not a product

**This is being built for me.** Not for distribution, not for other users, no business
model. But **general enough to apply to work projects and any other codebase** — general
in the sense of "not hardcoded to one repo," not in the sense of "productized."

This reframe invalidates a chunk of the research conclusions:

- **The "it already exists" objection loses most of its force.** It matters enormously
  whether a *product* is differentiated. It matters much less whether a personal tool is —
  the question becomes "does anything existing fit MY workflow well enough to adopt
  instead," which is a far lower bar to clear and a much more specific question.
- **Vibe Kanban shutting down is no longer a warning.** It died of no business model.
  I don't need one. Its code is MIT and still readable.
- **Industry-wide nesting clamps matter less** — those are vendor defaults tuned for
  safety across a userbase. I can pick my own limits.
- **What now matters most: adoption cost vs. fit.** Forking something opinionated and
  bending it may beat building. Or it may be worse than building, if its opinions are
  baked in deep.
- **Still true from the research:** the human-gate + reconciliation gap is real, the
  tool-not-file principle is sound, and building a general durable workflow engine is
  still a waste of my time.

### Build it around ONE project first

Yegge's post-mortem is the warning: *"Gas Town was intended to be reusable, but I only
ever wound up using it to build itself."* Building for a general audience first is how
that happens. So — **build it around one real project**, and generalize only what earns
it. (See `PRINCIPLES.md` F4, P12.)

Concretely:

- **This tool lives in its own repo**, with the scaffolding: daemon, step machine, store,
  UI, backend adapters. Generic, project-agnostic.
- **Skills, plugins, templates, and label vocabulary start as REPO-SPECIFIC.** They live
  in a per-repo folder (`.agentflow/` or similar in the target repo) and are allowed to be
  hardcoded, opinionated, and ugly.
- **Promotion, not prediction.** When something in the repo-specific folder proves itself
  on a second repo, move it to the general place. Nothing gets generalized before it has
  worked twice. Generality is earned retroactively.
- The repo-specific folder is also the natural per-project state boundary — which
  independently solves F7 (Gas Town's two-towns corruption, and Gas City's shared `~/.gc`
  races).

Rough split:

| Scope | What lives there |
|---|---|
| **The tool** (`switchboard/`) | the engine, default roles/templates/prompts, everything promoted |
| **Per-repo** (`<repo>/.switchboard/`) | that repo's roles, templates, prompts, learnings |
| **Per-repo state** (`<repo>/.git/agentflow/state.db`) | agents, messages, events — disposable |

### The rule that keeps this from forking

**Use it on `lore` 100%. But refinements to the tool land in `switchboard`, never in `lore`.**

- `lore` is where the tool gets *used*, and it holds only `lore`-specific config.
- `switchboard` is where the tool gets *better*. Every engine fix, every default, every
  promoted template.
- Promotion path: something proves itself in `lore/.switchboard/` → moves into
  `switchboard`'s defaults. One direction only.

This is what avoids both failure modes at once: the tool never becomes a thing that only
builds itself (F4), and it never forks into a per-project copy that drifts.

"General" therefore means *not hardcoded to one repo* — not *productized for other
people*. Those are very different bars, and only the first one matters here.

---

## The pitch

A customizable agentic workflow setup: nestable agent orchestration, a graph view of
who can talk to whom, a plugin system for tools and skills, reusable step templates,
and a status board showing where every in-flight workflow is stuck.

Surface: either a localhost web UI or a terminal UI. **Preferred: build it on top of
[herdr](#herdr-as-the-substrate) rather than building a runtime from scratch.**

Must support **Claude Code** and **Codex** as agent backends.

---

## Core principles

These are the things that differentiate this from what already exists.

1. **Abstract away from "skills" as hard as possible.** Skills are prompt text — they
   burn context, can't be validated, and can't be rendered. Push everything we can into
   **tool calls, daemons, and background processes** instead. A skill should be the
   fallback of last resort, not the primary mechanism.
2. **Everything is data, not prose.** Templates, labels, learnings, workflow state — all
   stored as **JSON/YAML**, never as freeform markdown that only an LLM can parse.
   Consequence: any UI can render it. Web and terminal are both just views over the same
   declarative state, and neither is privileged.
3. **You are not stuck talking to the controller.** Existing orchestrators funnel all
   human interaction through a single root. Here, the human is a peer node — you can
   address the controller, a sub-controller, or any individual leaf agent directly.
4. **The controller is customizable.** Its policy, its escalation rules, what it decides
   vs. what it escalates — all user-defined. Not a fixed black box.
5. **Tools over file editing.** Anywhere agents would otherwise read/write a shared
   markdown file, give them a tool instead. Cleaner, less context burned, faster, and
   the on-disk representation becomes an implementation detail.
6. **Templates are step-at-a-time, not one monolithic skill.** A template is a sequence
   the agent walks; each step can bind its own behavior. Nothing gets forgotten, and no
   single mega-skill has to encode the whole process.

### Prior art to differentiate against

- **Firstmate**
- **AgentOrchestrator (AO)**

> TODO: write down concretely what each does badly / what we do differently, beyond
> "talk to any node" and "customizable orchestrator". Worth an honest look before
> building — some of this may already exist.

---

## 1. Controller (not really an "orchestrator")

**Reframe: this is a controller, not an orchestrator.** It doesn't own the conversation
or do the thinking — it spawns, watches, and unblocks.

- **Minimal context, by design.** The controller must consume as little context as
  possible. It does **not read transcripts**. It reads **state**.
- Typical use: "spawn agents to research aspects X, Y, Z of this." Then *I* follow up
  with those agents in detail, directly — not relayed through the controller.
- Canonical unblocking example: two agents each merging a PR. Agent 1 reports done.
  Controller does a quick check, then tells agent 2 it may now check for merge conflicts
  and merge. That's the entire job — a state machine with a little judgment, not a
  reasoning layer sitting between me and the work.
- Controllers nest: main controller → sub-controller (scoped to one issue) → agents.
- Human can inject at any level — root, sub, or leaf.

Implication for the design: agents must **report structured state** (done / blocked /
needs-review / failed + a small payload), because that's all the controller ever sees.
Agent status is data, not narrative. This is principle #2 applied to the control plane.

Open: mechanically, is the controller an LLM agent with a control tool belt, or a
deterministic scheduler that escalates to an LLM only on ambiguity? The
low-context requirement pushes hard toward "mostly deterministic, LLM on exception."

## 2. Organized layout / graph view

- A panel showing connected agents — **a graph, not strictly a tree**.
- Edge = link = "these two can communicate."
- Should make the topology obvious at a glance: who reports to whom, who's chatting
  sideways, where the human is currently attached.
- Node state visible on the graph: running / blocked / awaiting-review / done.

## 3. Plugins

Two distinct kinds:

**Tooling plugins** — expose tools to agents.
- Example: a todo list. Agents don't edit `TODO.md`; they call `todo.add`, `todo.list`,
  `todo.remove`. Cleaner, cheaper in context, faster, no merge conflicts between agents.

**Skill plugins** — inject behavior/instructions.
- Example: autosave-learnings (an agent that reflexively records what it learned).

Open: is the plugin interface MCP servers? Something native? MCP buys instant Claude +
Codex compatibility for the *tooling* half.

## 4. Learnings (the flagship example plugin)

- Learnings are stored and added **via a tool**, never by hand-editing files.
- Every learning carries **labels**: `pre-merge`, `code-review`, `p0`, `high-risk`, …
- Retrieval is by label: call the tool with a situation's labels, get back the relevant
  learnings, organized.
- **The physical layout genuinely does not matter** — grouped by file, by date, whatever.
  The tool abstracts it completely. That's the whole point.

This is the proof that principle #3 pays off: same data, but agents only ever pull the
slice they need instead of loading a growing file into context.

## 5. Templates

- Ship **defaults**, allow **customization**, and support **one-off throwaway** templates
  for a single task.
- A template is an ordered list of steps. **Steps are repeatable** — review/repeat loops
  are first-class, not an afterthought.
- Some steps are **human-owned** (manual test) and simply block until you fill them in.
- Each step can bind a specific skill, so the agent gets exactly the right instructions
  for that step and nothing more.

### Example: "fix bug" template

1. Read GitHub issue, self-assign
2. Read context
3. Design
4. Plan
5. Review
6. ↻ repeat (back to 3/4 until review passes)
7. Implement
8. Review
9. ↻ repeat (back to 7 until review passes)
10. Manual test — **human fills this in**
11. Merge

Flow: main orchestrator spawns a sub-orchestrator scoped to this issue → that
sub-orchestrator runs agents step by step, each with the step's designated skill.

## 6. Workflow status UI

- See all in-flight workflows, grouped under the template they're running.
- At a glance: which step each is on, which are **blocked**, which need **manual
  review**, which failed.
- Effectively the queue/inbox for "what needs me right now."

---

## Herdr as the substrate

Checked the local install (`~/.local/bin/herdr`, config at `~/.config/herdr/`). It is a
**terminal workspace manager for AI coding agents** — native binary, client/server over
unix sockets, with a real API. It already provides a lot of the runtime:

**Already there:**
- Built-in integrations for **`claude` and `codex`** (plus copilot, cursor, devin, droid,
  opencode, grok, and ~8 more) — `herdr integration install <name>`
- Agent control API: `herdr agent list | get | read | send-keys | prompt | rename |
  focus | wait | start | attach | explain`
  - `agent prompt` and `agent wait` are the key ones — that's programmatic drive + block
    on state, i.e. exactly what an orchestrator needs.
- `herdr api snapshot` (live session state) and `herdr api schema` (bundled API schema)
- Panes, tabs, workspaces, **git worktrees**, notifications — all over the socket API
- Named persistent sessions, remote attach over SSH
- Config in `config.toml`, hot-reloadable via `herdr server reload-config`
- A plugin lock file (`.plugins.lock`) — so some plugin concept exists already; needs
  investigating
- `herdr --skill` prints an agent skill file, meaning it's already designed to be driven
  *by* an agent

**What it does NOT appear to have — i.e. our actual product:**
- The orchestration layer (nesting, delegation, autonomous unblocking)
- The agent-relationship graph / who-can-talk-to-whom
- Templates and step sequencing with repeat loops
- The tool-plugin layer (todos, learnings)
- The workflow status board

**Implication:** herdr is the runtime (spawn agents, worktrees, panes, send prompts,
observe state, terminal UI). We build the orchestration + memory + template layer on top,
talking to `herdr.sock`. That removes an enormous amount of undifferentiated work — PTY
management, agent-CLI quirks, session persistence, remote attach.

**To investigate:**
- [ ] `herdr api schema` — full surface area of the socket API
- [ ] `herdr --skill` — what it already tells agents they can do
- [ ] `.plugins.lock` — what herdr's own plugin system is, and whether ours can be one
- [ ] Is herdr open source / extensible, or are we strictly an API client?
- [ ] Does `agent wait` expose enough state granularity to drive a step machine?

---

## 7. Durability: retries, resume, backups

### The step IS the unit of recovery

Settled: if a step dies mid-way, **just run the step again.** A half-finished design step
or review round restarting from scratch is fine — no correctness problem. So we do NOT
need mid-step checkpointing, transaction logs, or replay.

That demotes `--resume` from a correctness mechanism to a **cost optimization**: continue
the dying agent rather than redo the step, to save tokens. Nice to have, never relied on.
(And it can't be relied on anyway — compaction makes it lossy, Claude Code's `Workflow`
documents `resumeFromRunId` as **same-session only** `[04]`, and Codex's `--output-schema`
reportedly breaks under `exec resume` `[06]`.)

The one thing we genuinely must persist is therefore small: **which step was in flight,
and what the completed steps returned.** That's it.

### The two things that make step-restart safe

**1. Restart must actually mean restart.** An agent that wrote 3 of 5 files before dying
leaves a half-modified tree; re-running drops a fresh agent into it. Not corrupt, but not
a clean slate — a reliable source of confusing failures. Fix: worktree per run, snapshot
the commit at step start, `git reset --hard` before re-running. **This is the only reason
the git layer is needed.**

**2. Steps with external side effects can't be auto-restarted.** The "fix bug" template
has both kinds:

- *Freely restartable:* read issue, read context, design, plan, review, implement, manual test
- *Not restartable:* `gh pr create` (→ two PRs), push, post a comment, **merge**

So a step needs one attribute — `side_effects: external` — meaning: never auto-restart;
require an idempotency key or stop at a human gate first. Everything else is freely
re-runnable.

Neat consequence: the non-idempotent steps are exactly the risky ones, so they're the
steps we'd want a human gate in front of regardless. The durability requirement and the
human-gate feature land on the same mechanism.

### What to build

- **Checkpoint at step boundaries only.** ~10 rows per run — the same rows the status
  board needs anyway, so durability is nearly free. Schema per `no-mistakes`:
  `runs` / `step_results` / `step_rounds`, a loop re-entry getting its own row.
- **Snapshot the template into the run.** Editing a template must never kill in-flight
  runs (the determinism trap, F12).
- **git worktree + branch per run**, with a commit at each step start — so restart is a
  `git reset --hard`, not a replay.
- **`side_effects: external` on steps that touch the outside world**, gating auto-restart.

### Retries — two distinct things, kept separate

Borrowed from `formula-spec-v2` and CNCF Serverless Workflow `[04]` `[09]`:

- **`retry`** — *transient* failure. Same step, same intent, something broke (API 500,
  network, timeout). Bounded attempts, exponential backoff.
- **`next` / `goto`** — *semantic* outcome. The step succeeded and the answer was
  "revise". This is the review→implement→review loop, and it is **not** a retry.
- **`check`** — script-verified success criterion (tests/lint pass), so "done" is
  declared by evidence rather than by the agent's opinion (P7).

**Mandatory `max_visits` on every back-edge.** Unbounded loops fail validation at load
time — stricter than any surveyed engine, because here an infinite loop costs real money
(F6: 132M cache-read tokens in 3 hours). Pair with `min_budget` — don't enter a loop you
can't afford to finish — and `on_exhausted` routing to a human gate rather than a crash.

### Backups

- SQLite: WAL mode + periodic snapshot. It's small; keep the last N.
- Learnings are the only genuinely irreplaceable data — everything else can be re-derived
  from git and the templates. Export to plain JSON on write so a corrupted DB is an
  inconvenience, not a loss. (Gas City's #3341 shows integrity-check races blocking
  backups — don't couple backup to the live store.)

Open: budget caps as a first-class failure mode — per-run and per-day ceilings that halt
into a human gate rather than failing. Nobody surveyed does this well.

## Open questions

- **UI surface:** localhost web UI vs. TUI. If herdr is the substrate, the TUI is partly
  free — but a graph view and a status board are much easier in a browser. Possibly
  both: herdr owns the panes, a localhost UI owns the graph + board.
- **Where does workflow state live?** SQLite next to the repo? A daemon? Needs to survive
  restarts and be inspectable by tools.
- **Claude/Codex parity:** MCP works for both on tooling. Skills/templates are more
  Claude-native — what's the Codex equivalent, and how much is lost?
- **Inter-agent communication:** what does an edge in the graph physically mean? A
  message-passing tool? Shared context? Both?
- **Human injection UX:** how do you attach to a leaf agent mid-run without corrupting
  the orchestrator's model of what's happening?
- **Failure/abort semantics:** what happens to a sub-orchestrator's children when a
  parent decides to abandon the workflow?

## Ideas / notes

-
