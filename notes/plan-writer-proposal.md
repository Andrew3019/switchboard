# Plan writer

**Status:** Ready to build.

**Context:** Issue #185. PR 184 spent 62 minutes on a 13-minute fix because the process was
chosen implicitly and was too heavy.

## Why

Today, process is chosen implicitly. Plans name the work, but each step owner still has to decide
how to execute it.

That causes three failures:

- Small changes get too much process.
- Risky changes start without clear scope, success, or termination conditions.
- Step owners spend context rediscovering orchestration, tools, skills, depth, and work budgets.

A plan writer uses the investigation brief and its knowledge of sb, models, skills, presets, and
tools to make those decisions once, before implementation. The main agent receives a focused plan
instead of inheriting the investigation or planning process.

## What

The plan writer turns completed investigation into an executable plan.

The plan defines the job-level contract:

- Scope and exclusions.
- Success criteria.
- Constraints and work budget.
- Termination condition.

Each step defines:

- Objective and expected output.
- Relevant context and dependencies.
- Recommended continuity: the main agent by default; a fresh agent, lead, or native subagents when
  justified.
- Suggested model, skills, presets, and tools.
- Suggested delegation and isolation strategy.
- Suggested depth and work budget.
- Verification shape and useful evidence.
- Handoff or result needed by later steps.

A plan step is a unit of work, not an agent boundary. One main agent normally owns most steps and
survives across implementation, testing, fixes, and integration.

This is a reasoning task, not a form-fill. The plan writer considers alternatives and chooses an
execution strategy for each step. It may use a fresh review when the planning risk justifies one.

The execution strategy is a recommendation, not enforcement. The main agent and any supporting
agents follow it by default but may adapt when new evidence makes the plan wrong. They record
material deviations so later work inherits the updated reasoning.

## Who

The investigator produces a problem brief. Every non-trivial task then gets a fresh initial
plan-writer agent that turns the brief into a complete execution plan.

The spawning parent is the task-owning agent, never a dispatcher. A dispatcher may establish that
owner but does not read, write, or approve the plan.

Each plan writer starts with the planner package below plus the task-specific investigation brief
and evidence.

The plan writer stays open for the life of the plan. After approval and handoff, it becomes inactive
until the main agent reports a material delta or completion. It does not become a runtime
orchestrator or participate in ordinary execution.

One main agent normally owns execution. It performs most steps itself and survives across
implementation, testing, fixes, and integration. Fresh agents are used only when independence,
specialization, or real parallelism justifies the context switch.

Andrew approves every non-trivial plan. Clearly trivial work may skip both the plan writer and the
blocking approval with a recorded reason. A fresh agent may review the plan before approval when the
planning risk justifies it.

## Planner package

A plan writer is assembled from four parts:

- **Existing `researcher` role with a strong model override.** This supplies a non-writing identity
  without adding a global planner role that survives when the plugin is disabled.
- **Plans plugin planner instruction.** `sb plugin plans planner` prints plugin-owned `planner.md`.
  The planner reads it on its first turn; it is not injected into every agent through `agent.md`.
  It defines planning, review, approval, handoff, inactivity, and replanning behaviour, and states
  that step strategy is advisory. For this task it replaces the researcher's normal findings-note
  deliverable and tells the planner not to call `done` after handoff.
- **Plans guide: `sb plugin plans guide`.** Holds the detailed procedure and current plan schema.
  Read at the start of each planning or replanning pass.
- **Generated live catalogue.** Built at planner start from the repo's merged roles, models, presets,
  enabled plugins, capabilities, plan library, and templates. The planner's session already supplies
  the current skills and tools available to that agent.

The catalogue is generated, never maintained as a hardcoded inventory. The planner instruction says
how to generate it and load relevant details on demand. Generate it once when the planner starts.
Refresh only when the planner has reason to believe the available vocabulary changed.

The catalogue covers sb-managed vocabulary. The planner's context manifest separately records the
skills and tools exposed in its session. When recommending a different provider or runtime, it names
a tool only when that target inventory is known; otherwise it describes the needed capability and
leaves final tool selection to the main agent.

The role says what the agent is. The plans plugin owns every planner-specific instruction, command,
schema, catalogue, and record interpretation. Disabling the plugin removes every planner-specific
behaviour and UI surface; existing plan data remains inert in repo state. Only the generic
`researcher` role remains. The only task-specific input is the tidied problem brief and its evidence
references.

## When

Planning starts after the problem is understood well enough to choose an execution strategy and
before implementation begins.

Planning depth is proportional to the work. Go deeper when:

- The approach has real alternatives.
- Scope or blast radius is unclear.
- Work crosses subsystems or needs coordination.
- Changes are difficult to reverse.
- Verification is expensive or uncertain.

Clearly trivial work may skip the planning pass. Bounded work with an obvious approach gets a short
plan. Complex work gets deeper decomposition and review. These are judgments, not fixed tiers.

For a PR-184-sized bounded fix, the expected result is either a recorded trivial skip or a short
one-main-agent plan with no agent plan review and focused verification. If this design routinely adds
a planner, reviewer, or handoff to that shape of work, it has repeated the failure it exists to fix.

Reopen the plan only when new evidence changes its scope, risk, or execution strategy. Ordinary
implementation details do not require replanning.

## Where

The plan writer belongs in the plans plugin, not the core sb substrate.

The plan file is the source of truth:

- Job-level scope, success, constraints, and termination live with the approval step.
- Each plan step carries its execution strategy.
- Detailed briefs remain separate files referenced by the step.
- Approved plan content continues into the PR comment through existing rendering.

The plans plugin stores and displays the recommendations. Agents interpret them; the plugin does not
become an execution engine.

## How

1. The investigator returns a tidied problem brief to the task's owning parent.
2. The parent records a trivial-work skip or spawns a fresh strong-model `researcher` whose task says
   to run `sb plugin plans planner` first, then read the problem brief.
3. Before planning, the parent grants the plan writer held `spawn` (for its own plan reviewer) and
   held `fork` when an isolated helper is foreseen. The planner never holds `write-tracked`, and it
   is granted nothing delegable-only: under the sibling model the parent seeds the main agent
   directly, so no capability is passed through the fragile planner.
4. It defines the job-level contract and decomposes the work into steps.
5. For each step, it compares viable approaches and records the recommended continuity, model,
   orchestration, tools, depth, verification, and handoff. The main agent is the default.
6. A fresh agent reviews the plan when planning risk warrants it.
7. Andrew approves or rejects every non-trivial plan. Rejection returns the work to planning and
   increments `tries`.
8. The plan writer creates a focused brief for a fresh main agent, states its capability seed, tells
   its parent it is ready, and remains open but inactive. The parent — not the planner — then spawns
   the main as its own child, the planner's sibling, and grants the seed directly. `sb delegate` only
   ever makes the caller's own child, which is why the handoff has two halves.
9. The main agent performs most steps and uses the plan's delegation recommendations unless new
   evidence justifies adapting them.
10. The main agent maintains execution state and handles local adjustments. When new evidence
   materially invalidates the contract, it sends the planner a delta by name — its own parent is the
   lead, not the planner. If the planner is gone, the delta routes to the parent instead, and the
   worktree's owner takes over the shape.
11. The same plan writer revises the affected contract and downstream steps, then returns material
    changes through review and Andrew approval.
12. Before final `done`, the main agent sends the planner a completion candidate with
    `--needs-reply`. The planner checks the termination condition, returns missing work or clears the
    main agent to finish, then closes after the main agent's final report. If the planner has died,
    the main detects the unanswered handshake on its next wake and routes the candidate to the parent,
    which is the lead.

No automatic evaluator or permanent orchestrator is added. The plugin represents the plan; the main
agent runs it.

This is a role and capability boundary, not a filesystem sandbox. Switchboard does not prevent a
planner from editing tracked files directly. The planner instruction forbids it; existing mutation
signals may surface a violation but do not prevent or reliably attribute one.

## Review and approval

Andrew approves every non-trivial plan. Agent review happens before that approval when it is likely
to find planning errors.

Use a fresh plan reviewer when:

- The approach has meaningful tradeoffs.
- The plan crosses subsystems.
- Several agents or handoffs are proposed.
- Verification is expensive or incomplete.
- Failure would have a large blast radius.

The reviewer checks:

- Every success criterion is covered.
- Steps have coherent dependencies and handoffs.
- The main agent retains work that does not need separation.
- Recommended models, tools, skills, and capabilities exist.
- Work budgets and termination conditions are usable.
- Verification matches the risk.

The reviewer reports problems to the plan writer. It does not approve the plan or redesign it
silently. The plan writer resolves the findings, then asks Andrew for approval.

Small, linear plans go directly to Andrew.

## Plan ownership

The main agent maintains execution state. It may update progress, notes, evidence, checkpoints, and
outputs. It records local adaptations in notes rather than reshaping the plan.

The plan writer is the sole shape writer for a planner-managed plan. It owns scope, success criteria,
decomposition, cross-step dependencies, strategy, verification strategy, and termination. It
remains open in a waiting state so it can revise the plan without losing the original rationale.

When material replanning is needed:

1. The main agent pauses affected work and sends the plan writer a delta with the new evidence.
2. The plan writer rereads the current catalogue, approved plan, and referenced evidence.
3. It revises the affected contract and downstream steps.
4. Review runs again when the revised planning risk warrants it.
5. Andrew approves the material change.
6. The main agent resumes execution.

Step agents report results and proposed deviations. Reviewers report findings. Neither reshapes the
plan directly.

## Representation

Use the existing `change-approval` gate. Do not change its two-section output contract; implementation
review already reads that output as the approved objectives and change contract.

Keep the plan-writer instruction, catalogue generator, schema, and workflow inside the plans plugin.
Use the existing `researcher` role as the non-writing agent substrate.

Store planning output in the existing plan:

- `change-approval.output`: the existing approved Scope & Objectives and Change Contract. For a
  planner-managed plan, the Change Contract contains the concise execution outline.
- Plan `planner`: the planner agent name; absent means the current worktree-owner rule applies.
- Step `strategy`: advisory orchestration and framework recommendations.
- Step checkpoint: path to any detailed problem or execution brief.

Before approval, the planner presents the full plan within the existing two-section format rather
than adding a third section. The output retains that approved text for later implementation review.
A material plan revision reopens the same approval step and increments `tries`.

`planner.md` tells the planner to keep the execution outline high-level: step objectives, continuity,
meaningful agent boundaries, work budget, verification, and termination. It does not put
implementation detail into the Change Contract.

Render strategy in terminal, Markdown, JSON, and PR comments.

Existing plan composition, obligations, gates, progress, and dependencies remain unchanged.

### Step strategy

Each step may carry a sparse `strategy` object:

```json
{
  "strategy": {
    "continuity": "main agent continues",
    "orchestration": "single-agent implementation with a fresh reviewer afterward",
    "model": "standard for implementation; strong and fresh for review",
    "resources": {
      "skills": ["github"],
      "presets": [],
      "tools": []
    },
    "isolation": "shared unless parallel tracked writes become useful",
    "budget": {
      "context": "about half of one main-agent context",
      "passes": "one implementation pass and one review-driven correction pass"
    },
    "verification": "focused evidence during work; reuse valid evidence; one final suite",
    "replan_if": "scope expands or the implementation approach becomes ambiguous",
    "brief": ".switchboard/briefs/p-42/implementation.md"
  }
}
```

The strategy focuses on context continuity, orchestration shape, model characteristics, useful
resources, isolation posture, verification shape, and when to return to planning. It does not
prescribe implementation details that require deeper problem knowledge.

All values are recommendations. They are neither requirements nor ceilings. Missing strategy means
use normal judgment. Agents may depart from it without permission; only materially consequential
departures need to be recorded.

Names under `resources` must come from the generated catalogue or the planner's exposed session
inventory. Qualitative model or isolation advice may remain free text. A reviewer checks only exact
names against the catalogue.

Use agent context and passes as budget units, not wall-clock minutes. Context estimates how much of
an agent context the work deserves. Passes estimate how many independent work or review attempts are
justified. Exceeding either is a signal to reconsider or replan, not an automatic stop.

#### Canonical strategy schema

Ship this contract as `defaults/plugins/plans/strategy.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://switchboard.local/plans/strategy.schema.json",
  "title": "Plan step strategy",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "continuity": {
      "type": "string",
      "minLength": 1
    },
    "orchestration": {
      "type": "string",
      "minLength": 1
    },
    "model": {
      "type": "string",
      "minLength": 1
    },
    "resources": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "skills": {
          "type": "array",
          "items": {"type": "string", "minLength": 1},
          "uniqueItems": true
        },
        "presets": {
          "type": "array",
          "items": {"type": "string", "minLength": 1},
          "uniqueItems": true
        },
        "tools": {
          "type": "array",
          "items": {"type": "string", "minLength": 1},
          "uniqueItems": true
        }
      }
    },
    "isolation": {
      "type": "string",
      "minLength": 1
    },
    "budget": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "context": {
          "type": "string",
          "minLength": 1
        },
        "passes": {
          "type": "string",
          "minLength": 1
        }
      }
    },
    "verification": {
      "type": "string",
      "minLength": 1
    },
    "replan_if": {
      "type": "string",
      "minLength": 1
    },
    "brief": {
      "type": "string",
      "minLength": 1,
      "pattern": "^[^\\r\\n]+$"
    }
  }
}
```

Every field is optional. The schema fixes field names and shapes, not recommendation values. There
are no enums for orchestration choices. Unknown fields are preserved but warned about by
`plans validate`; they never become runtime enforcement. The plugin loads this file as the single
field-and-type contract; it does not maintain a second hardcoded schema. Schema violations are
non-fatal plan defects, consistent with existing validation. Validation checks representation only;
it never checks whether an agent followed a recommendation.

The loader implements only the keywords this file uses: `type` (`object`, `string`, and `array`),
`properties`, `additionalProperties`, `items`, `uniqueItems`, `minLength`, and `pattern`. `$schema`,
`$id`, and `title` are metadata. This is not a general JSON Schema implementation and adds no
dependency.

## Implementation units

### Unit 1 — step strategy

**Objective:** render and check advisory orchestration strategy without changing execution.

- Add and load the canonical schema above.
- Warn on out-of-schema strategy keys or types in `plans validate`; preserve the data.
- Add readable terminal rendering for the structured object.
- Reuse the existing open-field pass-through for storage, JSON, Markdown, PR comments, and template
  copies. Add no storage migration.
- Add no edit verb, enforcement, spawning, or automatic execution.

**Done when:** strategy round-trips and renders everywhere; a plan without it behaves and renders as
before. Verify with one complete sample, one no-strategy sample, and two or three focused tests.

**Files:** `defaults/plugins/plans/strategy.schema.json`, `defaults/plugins/plans/__init__.py`, and
focused cases in `tests/test_plans_plugin.py`.

### Unit 2 — planner package and catalogue

**Objective:** give a fresh non-writing planner current sb knowledge with no hardcoded inventory.

- Add plugin-owned `planner.md` and `sb plugin plans planner`, which prints it.
- Add `sb plugin plans catalog` with readable and JSON output.
- Set the plan-level `planner` field when the planner creates a plan.
- Update the guide so the planner is the sole shape writer for planner-managed plans; other plans
  keep the current worktree-owner rule.
- Add read-only core `sb roles [name]` and `sb capabilities` listings with JSON output. Role JSON
  exposes name, model tier, capability template, configuration ceiling, and full prompt on the
  named-detail form. Capability JSON exposes the sorted vocabulary from
  `Broker.known_capabilities()`.
- Generate the plugin catalogue from those listings plus existing models, presets, enabled plugins,
  plan library, and template listings.
- Use a strong-model `researcher` as the agent substrate.
- Keep every planner-specific asset under `defaults/plugins/plans/`; the two generic core listings
  remain when the plugin is disabled.
- Generate the catalogue once when the planner starts; refresh only when something likely changed.

**Done when:** a real planner can inspect the current environment and make grounded recommendations
without inventing catalogue entries. Save its context manifest, probe responses, and model metadata
for development inspection. Disabling the plugin removes every planner-specific surface.

**Files:** `switchboard/cli.py` and focused role/capability CLI tests; plugin-owned `planner.md`,
catalogue and guide handlers in `defaults/plugins/plans/__init__.py`, and plans-plugin tests.

### Unit 3 — approval and plan review

**Objective:** approve a complete execution plan through the existing human gate.

- Keep `change-approval.json` and `review.json` semantics unchanged.
- The planner shows Andrew the full plan within the existing two-section contract before blocking.
- Rejection returns the same planner to design work and increments `tries`.
- Add optional `plan-review.json` in the existing `design` anchor band; it is never an obligation.
- When used, the planner explicitly makes `change-approval` depend on `plan-review` and clears
  `change-approval.root`; a step cannot be both a root and dependent.
- A fresh reviewer returns findings to the planner. The planner stores the compact result in
  `plan-review.output` and ticks the step; the reviewer never edits or approves the plan.
- Keep trivial skip, implementation review, and merge approval unchanged.

**Done when:** a small plan goes directly to Andrew, a higher-risk plan can take a fresh review first,
and a rejected plan can be revised and approved. Save the drafts, review, approval, and planner model
metadata from those development runs. A focused test proves the same-band dependency validates and
places plan review before approval without changing the anchor spine.

**Files:** `defaults/plugins/plans/library/plan-review.json`, the plugin planner instruction and guide,
and focused plans-plugin tests. Do not edit `change-approval.json` or `review.json`.

### Unit 4 — planner lifecycle

**Objective:** keep one main agent executing while the same non-writing planner remains available only
for material replanning.

- Add the plugin-owned planner-spawn and handoff procedures to the guide.
- Before planning, grant the strong `researcher` held `spawn` (for its own plan reviewer) and held
  `fork` when an isolated helper is foreseen. Never grant held `write-tracked`, and grant nothing
  delegable-only: the spawner seeds the main agent directly rather than passing capabilities through
  the fragile planner.
- Seeding the main is two verbs — `sb delegate --role` sets the role template, `sb grant` adds
  anything beyond it — and the chosen main role still narrows its seed by the existing
  template/intersection rule. If a required capability or isolated handoff is unavailable, record that
  precondition and resolve it before handoff.
- Define the planner-to-main brief and the main/planner ownership boundary.
- Create the plan in the workspace the lead, the planner and the main share. The lead spawns the main
  there by default; an isolated main uses the same repo-state plan by qualified id while the plan
  remains attached to that workspace.
- The planner and the main agent are SIBLINGS under the shared lead; the lead spawns the main and it
  stays the lead's child across implementation, testing, fixes, and integration. `sb delegate` only
  makes the caller's own child, so a sibling can only come from the shared parent.
- Let current live-child behaviour keep the inactive planner open.
- Route material deltas to the planner by name; keep local adjustments with the main agent. If the
  planner is gone, the delta and the completion candidate route to the parent (the lead), and the
  worktree's owner takes over the shape.
- Replan and reapprove with the same planner and main agent.
- Before final `done`, the main sends a completion candidate with `--needs-reply`. The planner either
  returns missing work or clears it to finish; the final `done` then wakes the planner to close. If
  the planner has died, the main detects the unanswered handshake and routes the candidate to the
  parent.

**Done when:** one live run proves handoff, capability narrowing, the sibling relationship, inactive
planner, local adjustment, completion handshake, final closure, and the fallback with the planner
actually gone. A second run introduces a material delta and proves replanning, reapproval, and
same-main continuation. Save each run's plan, briefs, messages, status snapshots, and model metadata.

**Files:** the plugin planner instruction and guide. Existing capability seeding, live-child waiting,
messages, and completion notification provide the mechanics; add no lifecycle engine.

### Unit 5 — development inspection and evaluation

**Objective:** prove the planner receives the intended context and produces proportional, grounded
plans.

- Capture its effective instructions, generated catalogue, brief, model configuration, skills, and
  tools.
- Run representative cases: bounded work, investigation, fresh review, parallel work, and material
  replanning.
- Use a fresh judge to score grounding, proportionality, main-agent continuity, verification, and
  invented details.
- Save briefs, manifests, plans, and judge reports for Andrew to inspect.
- Keep deterministic schema, rendering, catalogue, and approval tests in CI.
- Keep AI plan evaluations development-only, not runtime behaviour or a required CI gate.
- Inspect inputs, outputs, and concise decision rationales; do not request private reasoning.

**Done when:** the real planner package passes the sample cases, invents no catalogue entries, and
Andrew can inspect every evaluation artifact.

**Files:** committed cases, rubric, and development harness under `defaults/plugins/plans/evals/`;
deterministic tests under `tests/`. Put raw AI-run artifacts and model metadata on the implementation
issue or its PRs. Add no runtime eval command.

## Build order

Build and merge one unit at a time, with one plan and PR per unit. Use each landed capability to
build the next:

1. Plan Unit 1 by manually following this spec.
2. Use Unit 1 strategy while building Unit 2.
3. Use the real planner package from Unit 2 to plan Unit 3.
4. Use the approval flow from Unit 3 while building Unit 4.
5. Use the complete planner lifecycle from Unit 4 to run Unit 5.

Each unit includes focused tests and inspectable artifacts. Each should be independently reviewable
and landable without enabling unfinished behaviour.

Before Unit 1, create the self-contained implementation issue. Put this spec in the issue or a
committed tracked file; `.switchboard/notes/` is machine-local and cannot be the handoff. Before a
capability exists, mimic its intended input and output manually. After it merges to `main`, use the
real capability for every later unit. Update the running plan and implementation issue after each
merge so they describe the system that actually exists.

At the end, commit and merge all remaining work to `main`. Finalize the implementation issue with the
merged state, design decisions, verification evidence, artifacts, remaining work, exact next action,
and links to relevant commits and files. A new session on another computer must be able to continue
from that issue without this conversation or any machine-local note.
