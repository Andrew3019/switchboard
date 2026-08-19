# Principles

Engineering principles for this system. What it is, what it refuses to be, and what
follows mechanically from each choice.

Evidence for the empirical claims lives in `research/`, and Appendix A compresses the
failure evidence. Report refs look like `[02]`.

---

## The system in one paragraph

A personal agent-workflow runtime. Agents are spawned on demand, given a scoped job,
and cleaned up when done. They coordinate through a tiny set of CLI/MCP verbs — never
through prose protocol or shared files. A parent knows what its children are doing
because they report structured state, not because it reads their transcripts. Work is
described by declarative templates with repeatable steps and human-owned gates. It is
built around one real project first; generality is earned, not designed in.

---

# Part 1 — Core principles

## C0. Context economy is the whole game

Saving tokens and context isn't an optimisation — it's the thing that makes the rest
work. Every other principle is a way of buying context back. Three mechanisms, each
operating at a different level:

- **Orchestrators save context by deferring work.** A parent that delegates pays for a
  summary instead of the whole job. This is what makes deep trees affordable at all.
- **Agents save tokens by being scoped.** A worker holding only its own problem carries a
  fraction of the context of one holding the whole project — and produces better output
  for the same reason.
- **Tools save context by collapsing turns.** A tool that does in one call what would
  take an agent 20 turns of reading, reasoning, and editing saves those 19 round-trips of
  accumulated context, permanently.

Context spent on protocol, coordination, or instructions is context not spent on the
work. When a design choice is close, take the cheaper one.

## C1. Minimum scaffolding

Keep it simple. Agents send messages to other agents and may optionally wait for a
response. **Communication is parent↔child only. No sibling communication.**

*Follows from this:*
- The topology is a **tree**, not a graph. No edge-permission table, no routing rules, no
  message bus. A message goes up or it goes down.
- A parent is the only thing that can correlate two children's work — which is exactly
  what a parent is for.
- Deadlock surface shrinks to almost nothing: cycles require siblings.
- The "graph view" collapses to a tree view, and mostly stops being interesting.
- Anything that feels like it needs sibling comms is a signal the parent's scope is
  wrong, not that we need more plumbing.

## C2. Abstract everything into tooling

All an agent does is call a small, stable set of CLI/MCP commands. No large instruction
blocks, no prose protocols, no "remember to always…". **The tooling carries the contract.**

*Follows from this:*
- **The agent *wants*; the tooling *does*.** Verbs are named after intents, never
  mechanisms. Test: can the verb be read aloud as something a person wants? `ask` passes;
  `send` + `poll-inbox` + `match-correlation-id` fails.
- Correlation, retries, locking, and storage live inside the tool where agents never see
  them.
- Instructions that could be a tool are a bug. Skills are the fallback of last resort.
- Since agents only ever see verbs, **every storage and internals decision is
  reversible** — and therefore cheap. The verb set is the expensive thing.

## C3. Customizable, and agents are ephemeral

Everything else is built on top of the primitives. We don't need a standing team of 10
agents. **Agents are created when needed and cleaned up when their job is done.**

*Follows from this:*
- No roster, no fixed roles, no closed enum of agent types. Roles are data. `[09]`
- Agents are cattle. Anything worth keeping must be in the store **before** the agent
  dies — see C7.
- Spawn cost must be low enough that spawning is the obvious move, not a decision.
- Cleanup is automatic and unconditional. A leaked agent is an idle cost forever.

## C4. Scope: lazy parents, narrow workers

**Parents are lazy.** A top-level agent only cares about getting lower-level agents to
work. It should not do a round with more than ~10 tool calls or ~10 file reads — if it
did, that work should have been delegated.

**Workers are scoped executors.** They touch nothing that isn't theirs. They do the job,
give a status/report, and finish. They hold detailed context, but only about what they
are directly working on.

*Follows from this:*
- **Context flows down; results flow up.** A parent never inherits a child's context — it
  receives a summary. This is what makes laziness mechanical rather than aspirational.
- Parent context stays small and cheap indefinitely, no matter how deep the tree.
- The ~10-call budget is measurable, so it can be enforced by the tooling rather than
  requested in a prompt.
- A worker that needs something outside its scope must ask its parent — which is C1's
  tree, arriving again from a different direction.

---

# Part 2 — Derived principles

These aren't separate opinions; each one falls out of C1–C4 or is forced by how the agent
CLIs actually behave.

## C5. State is the interface

A parent learns what happened from a structured report, never by reading a transcript.
Status is a row: `done` / `blocked` / `needs-review` / `failed`, plus a small payload.

Reading transcripts to infer progress is the failure mode C4 exists to prevent — it's how
a lazy parent becomes an expensive one. `[02]` `[06]`

## C6. Enforce mechanically; never instruct

Anything an agent is asked to remember, it will eventually forget — under compaction,
under a long tool loop, under a confusing error. **If it matters, make it impossible to
skip.**

A `Stop` hook that blocks completion until a report is emitted beats "please report when
done". Both Claude Code and Codex have hooks with the same envelope. `[06]` Hooks can't be
ignored, survive compaction, and cost zero context — which is C2 applied to the control
plane.

> **As built, v0 now honours this.** Reporting is `sb done`, and a `Stop` hook
> (`bin/sb-stop-hook`, `switchboard/hooks.py`, installed via `--settings` on every spawn)
> refuses a turn that ends without `sb done` or `sb block` — the failure it exists to
> prevent, an agent finishing invisibly, was the most common one in the system. Detection
> remains underneath it rather than in place of it: `status.py` joins the store against
> herdr and names the disagreement (STALLED), and the reconciler pings an agent it catches.
> See D2 in `PLAN.md`.

## C7. The store is the only memory

Agent heads are volatile; the store is the system of record. Nothing important exists
only in a conversation.

Corollary: **the store is the only shared state.** No module calls another module — they
meet in the store. This is what keeps modules independently rewritable.

## C8. Determinism first; models only at the edges

The runtime is a state machine. Judgment is escalated — to a human gate, or to a scoped
agent that is asked one question — never diffused into an always-on reasoning layer.

A supervisor that "thinks" costs tokens on every transition and is unpredictable at
exactly the moments you need predictability.

**Note — orchestration is a role, not a component.** An agent *becomes* an orchestrator
when it's handed a template (or enough steps/context to constitute one): it sees that
template through, spawning an agent per step as needed. That doesn't contradict C8,
because the determinism lives in the template, not in a standing reasoning layer. The
guards that keep it honest are C4 and C5 — an orchestrator stays lazy, reads step results
rather than transcripts, and its context must not grow as the run proceeds. What C8
forbids is an always-on supervisor that reasons about every transition; what it permits
is an agent whose bounded job happens to be "execute this template."

## C9. Fail into a gate, never into a crash

Exhausted retries, exhausted budget, an ambiguous result, an unexpected state — all of
these route to a human gate. **Blocked-on-human is a normal, first-class state, not an
error.**

Corollary: **budget is a first-class failure mode.** Per-run and per-day ceilings that
halt into a gate. Every back-edge in a template carries a mandatory `max_visits`, because
here an infinite loop costs real money. `[04]` `[07]`

## C10. Idle costs nothing

No polling supervisors. Event subscriptions and blocking waits only. A loop that wakes up
to check on things bills you forever — measured at 132M cache-read tokens in three hours
in one shipped system, and still unfixed in its successor. `[07]` `[10]`

> **As built: no daemon exists, so there are no event subscriptions yet — and the polling
> that replaces them is deliberately the free kind.** What the principle is actually about
> is *token* cost, and nothing here spends a token to look: the deferred doorbell is
> flushed by whatever `sb` command runs next, and otherwise by the one elected collector
> process on a timer — one process per repo, no agent woken, no context paid. (This
> paragraph used to cite `sb ask` polling one indexed SQLite row inside a process that was
> already blocked, and `sb wait` blocking server-side inside herdr. Both verbs have since
> been **deleted**: no agent waits on another agent at all, which is this principle taken
> further than it was written.)
>
> The one place this was violated outright was `Herdr.wait`, which span at ~100% of a core
> re-issuing `agent wait` with no backoff. Still zero tokens — and still exactly the shape
> the principle forbids. Fixed; `tests/test_herdr.py` pins it.
>
> When `events.subscribe` and a daemon arrive they replace the *trigger*, not the model.

## C11. The step is the unit of recovery

If a step dies mid-way, run the step again. No mid-step checkpointing, no transaction
log, no replay. `--resume` is a token-saving optimisation, never a correctness mechanism.

Two things make this safe: a git worktree + per-step commit so restart is a real reset,
and a `side_effects: external` marker on steps that touch the outside world (open a PR,
push, merge) so they're gated instead of auto-restarted.

Neat: the non-idempotent steps are the risky ones, so they're the ones we'd gate anyway.

## C12. Vocabulary is data

No closed enums — of roles, step types, statuses, or labels. A closed enum is where
customization goes to die: a shipped system made its roles a Go enum, and every request
to add one was closed unimplemented. `[07]`

## C13. One API surface, narrow and frozen

The CLI **is** the API. MCP servers, hooks, the UI, and we ourselves are all thin shims
over the same verbs. *"There is no separate plugin SDK — the entire Herdr CLI is the
plugin API."* `[01]`

- Every command takes and emits JSON, so wrapping is mechanical.
- A new capability is one subcommand plus one row type, and it appears everywhere at once.
- **The agent-facing surface stays tiny and frozen.** Internals churn freely. This is what
  lets everything underneath be rewritten without re-teaching the agents.

## C14. The human is a node, not a spectator

The human can be addressed and can address. Human-owned steps block and resume cleanly.

This is the one thing nothing else ships: Claude Code's docs concede *"no mid-run human
input by design"*, and Gas City's own spec lists `gate type = "human"` as inert — *"no
bundled watcher acts on them."* `[09]` The data model is proven; the watcher is the work.

### Humans are exempt from C1

The tree constrains **agents**. A human may do anything: interrupt a conversation,
address a leaf directly, unblock it without involving its parent. Why the exemption is
correct rather than a compromise:

1. **No context lost relaying** a message down through every level of the tree.
2. **Saves tokens and context** in every intermediate node.
3. **Faster** — one hop instead of N.
4. The only real risk is **node misalignment**, and it's already handled: a child reports
   on `done` or `blocked` anyway, and a human-caused change of direction is exactly the
   kind of thing that report carries. The parent finds out through the normal channel,
   one report later.

### The blocked-leaf shortcut

A blocked leaf calls a tool that surfaces the block **directly to the human UI** — not up
through its parent. The human unblocks it in place, and **the parent's context is never
polluted**.

This is the load-bearing mechanism of the whole design, not a convenience:

- It's what makes C4 hold in practice. Without it, every block walks up the tree and
  parent context grows with the run — which is precisely the failure C4 forbids.
- It's C9's gate and C14's human node arriving as one mechanism.
- It's why the status board (not the graph) is the product: the board *is* the surface
  where blocks appear and get answered.
- It means gates and notifications are wired **leaf → store → UI**, bypassing the tree
  entirely. Worth building that way from v0.

## C15. Generality is earned, not designed

Built around **one real project** first. Templates, skills, and labels start repo-specific
and ugly. Something moves to the global layer only after it has worked on a *second*
repo.

The named failure here is the author of a 17k-star orchestrator: *"Gas Town was intended
to be reusable, but I only ever wound up using it to build itself."* `[08]` Use it on
unrelated work within two weeks or the design is unfalsified.

---

# Part 3 — What these rule out

Stated plainly, so scope creep is recognisable:

| Not building | Ruled out by |
|---|---|
| A message bus / routing table / sibling addressing | C1 |
| A standing team of named agents | C3 |
| An always-on LLM orchestrator *(an agent handed a template is fine — see C8 note)* | C8, C4 |
| Prose protocols, large system prompts, skill hierarchies | C2, C6 |
| A durable-execution engine (Temporal/Restate/…) | C11 — our need is ~10 rows per run |
| A vector/semantic memory system | C2 — ours is label dispatch, not recall `[05]` |
| A graph visualisation | C1 — it's a tree |
| Multi-user, auth, teams, a business model | C15 |

---

# Appendix A — Failure evidence

Compressed. Detail, issue numbers, and quotes are in `research/`.

| # | Failure | Where | Principle |
|---|---|---|---|
| F1 | Themed vocabulary became a closed Go enum; role-add requests closed unimplemented | Gas Town `[07]` | C12 |
| F2 | Custom templates parsed, merged, printed — never executed (#3322); user lost half a day | Gas Town `[07]`, echoed in Gas City #4382 `[09]` | C13 |
| F3 | 300k LoC of ceremony; the orchestrator ignored its own protocol *"appearing no different than a `claude` invocation"* | Gas Town `[08]` | C1 |
| F4 | *"I only ever wound up using it to build itself"* — author's own post-mortem | Gas Town `[08]` | C15 |
| F5 | 17,482★ / 96 watchers; nobody ever answered "has anyone shipped anything with this?" | Gas Town `[08]` | C15 |
| F6 | 132M cache-read tokens in 3h at idle; still unfixed in successor (#1751, #3892) | `[07]` `[10]` | C10 |
| F7 | Two projects on one machine corrupted each other; 23,759 restart flaps in 6h | `[07]` `[10]` | C7, C15 |
| F8 | Tasks with no git diff auto-closed — research/design steps structurally impossible | Gas Town `[07]` | C5 |
| F9 | Agent state detected by regex over the TUI; scrollback lost permanently | herdr `[01]` | C5, C6 |
| F10 | Durable memory as Markdown — whole file read to use any of it, conflicts on write | Firstmate `[02]` | C2 |
| F11 | 12 of 14 memory systems require a query string; category churns hard | `[05]` | C2 |
| F12 | Workflow engines define workflows as code — adopting one means writing an interpreter | `[04]` | C11 |
| F13 | Vibe Kanban built templates, deleted them, shut down at 27.7k★; agent-os v3 deleted its workflow layer | `[02]` `[03]` | C15 |
| F14 | Airflow calls the grid *"the primary interface"*; Temporal ships no DAG at all | `[03]` | C1 |
| F15 | `textual-web` untouched since Aug 2024; Textualize Ltd dissolved Feb 2026 | `[03]` | — |
| F16 | Two reports disagree on whether `--output-schema` works on Codex — **unresolved** | `[04]` vs `[06]` | C6 |

---

# Appendix B — Borrow list

| Source | License | Status | Take |
|---|---|---|---|
| **herdr** `herdrdev/herdr` `[01]` | Apache-2.0 | Active, 25.1k★ | The runtime, **display only**. `events.subscribe`, `pane report-agent` for state authority, `plugin.pane.open`, worktree helpers. |
| **Gas City** `gastownhall/gascity` `[09]` `[10]` | MIT | Active | `formula-spec-v2` step model: `check` vs `retry` vs `drain`, `on_complete`, roles-as-data. Reference, not dependency. |
| **Gas Town** `[07]` | MIT | **Dead** 2026-08-03 | Overlay/directive split, layered role schema, per-role model routing, failure catalogue. Don't fork, don't run. |
| **Firstmate** `[02]` `[08]` | MIT, bash | Active | Event-driven zero-token supervision over status files. Ignore its no-direct-addressing rule and Markdown memory. |
| **AgentOrchestrator** `[02]` | Apache-2.0 | 8.8k★ | OBSERVE → durable facts → DERIVE; **"display status is never stored"**; SQLite CDC → SSE. |
| **Vibe Kanban** `[03]` | MIT | Shut down | Rust core + `#[derive(TS)]` generating frontend types. |
| **agent-runbook** `[02]` | — | — | `loop` / `quality_check` as typed step types with build-time contract validation. |
| **no-mistakes** `[04]` | MIT | — | `runs` / `step_results` / `step_rounds` — a loop re-entry gets a row, not a counter. |
| **CNCF Serverless Workflow v1.0** `[04]` | Spec | — | Named steps, `if`, `then:` back-jumps, retry-as-data. The format to resemble. |
| **Kestra** `[04]` | — | — | `Pause` / `onResume` — the human gate done properly. |
| **Airflow 3.x** `[03]` `[04]` | Apache-2.0 | — | Gate decision separated from gate data. (`@xyflow/react`+`elkjs` only if a tree view ever needs it.) |
| **CodeRabbit learnings** `[05]` | Product | — | Provenance, usage stats, curation UI, redaction on write, scope-based retrieval. |
| **guild** `[02]` `[05]` | — | — | MCP + SQLite typed lore ≈ our learnings plugin. Evaluate before building. |
| **OpenHands** `[02]` | MIT | — | `TaskObservation` — a good structured-status shape. |
| **A2A / AG-UI / ACP** `[06]` | Specs | — | **Vocabulary only** — task-state enums, stop-reason enums. Ignore the runtimes. |

**Do not vendor:** Claude Squad (AGPL-3.0). **Do not build on:** Open WebUI (non-OSI
relicense, mandatory branding).
