# 04 — Workflow engines, step machines, and template formats

Research question: for our agentic workflow system, should we **adopt/embed an existing
engine**, **steal a format**, or **build a small purpose-built step machine**?

Date: 2026-08-06

---

# TL;DR — the recommendation

**Build a small purpose-built step machine. Steal the format. Do not adopt a durable
execution engine.**

> **Read this first.** Claude Code 2.1.223 **already ships a workflow engine** —
> `.claude/workflows/*.js` plus a `Workflow` tool with phases, structured-output subagents,
> worktree isolation, budget caps, and resume. It is **imperative JavaScript, not data**; it
> has **no human gates** (its own docs say *"No mid-run user input… For sign-off between
> stages, run each stage as its own workflow"*); and its resume is **same-session only**.
> This does not invalidate the plan — it sharpens it. The gap it leaves is *exactly* our
> product: a declarative template, durable cross-restart state, real human gates, and a
> status board. But we should know we are building **next to** a native engine, not into a
> vacuum, and we should seriously consider using it as the fan-out executor for a single
> `type: agent` step rather than reimplementing parallel subagent orchestration.
> See "Area 7 — prior art" for the full description.

Four findings drive this:

1. **Every serious durable-execution engine defines workflows as _code_, not data.**
   Temporal, Restate, DBOS, Inngest, Trigger.dev, Hatchet, Cadence, Azure Durable
   Functions — all of them are "write a function in Go/TS/Python, we make it durable."
   Our number-one requirement is the exact opposite: *a template is JSON/YAML, editable by
   a user, renderable in both a web and terminal UI, and sometimes generated as a one-off
   throwaway.* If we adopted Temporal we would write exactly one Temporal workflow — an
   interpreter that loads our YAML and walks it. At that point the engine supplies only
   durability, and charges us a server, a worker process, and an SDK for it.
   The two exceptions that *are* data — AWS Step Functions' ASL and CNCF Serverless
   Workflow — are formats worth stealing from, not runtimes worth running.

2. **Our durable-execution problem is genuinely tiny, and the hard part is somewhere
   else.** One user. Tens of steps. Steps that last minutes to hours. The actual work
   happens inside an external agent process (Claude Code / Codex) that we supervise but do
   not control, so we can never replay it deterministically anyway — in Temporal terms
   *everything* is a non-deterministic Activity and the workflow body is a `switch`
   statement. What we need to persist is: which step, what status, what structured result,
   how many times we've looped. That is two SQLite tables. The genuinely hard parts of
   this product — supervising agent processes, worktrees, human gates, the controller's
   escalation policy, the status board — are not what any of these engines solve.

3. **Footprint disqualifies most of them, and the survivors don't help enough.**
   Trigger.dev self-host is 10+ containers and ~14 GB RAM across two machines. Windmill is
   4–7 containers with mandatory Postgres. Hatchet needs Postgres. Cadence needs Cassandra.
   Azure Durable Functions needs Core Tools + Azurite. Temporal's dev server is a single
   binary but is **ephemeral by default** (state is lost unless you pass `--db-filename`),
   opens gRPC 7233 + UI 8233, needs a separate worker, and its Queries — the natural status
   board API — **require a live worker to be polling**, so the board breaks exactly when the
   app isn't running.
   Two genuinely are light: **Restate** (single self-contained binary, embedded RocksDB, no
   external DB) and **DBOS Transact**, which is the real surprise — it is a *library*, not a
   server, and **it no longer requires Postgres**: with no connection string it creates a
   local SQLite database automatically. One process, one SQLite file, zero containers.
   So the argument against these two is not footprint, it's finding 1 plus a fourth point.

4. **We would be paying for durability we're already buying.** Our steps are coarse
   (minutes to hours) and externally executed, so every checkpoint we need falls naturally
   on a step boundary — and we are already writing those rows, because the status board
   demands them. A durable execution engine makes *fine-grained in-process control flow*
   crash-safe; we have roughly ten checkpoints per run and all of them are already durable
   by construction. Embedding DBOS would mean two overlapping persistence layers writing
   the same facts.

   Worse, there is a **determinism trap** aimed squarely at our product. Replay-based
   engines (Temporal, Azure Durable Functions) re-execute the workflow function from the
   top and assert the command sequence matches history. If our interpreter re-reads a
   template the user edited mid-run, in-flight runs die with non-determinism errors.
   Azure DF has no versioning API at all — its official guidance for breaking changes is
   side-by-side deployment into a new task hub. Checkpoint-based engines (DBOS, Restate)
   are far more forgiving. Either way the mitigation is the same and we adopt it directly:
   **snapshot the template into the run at start and never re-read the file.**

**What we build instead:** a ~600-line interpreter over an ordered list of steps with
guarded `goto` edges, persisted to SQLite, driven by a daemon. Small enough to own,
expressive enough for every workflow in the braindump.

**The hedge, stated explicitly.** If we later find ourselves hand-rolling crash-safe
sub-step logic and regretting it, **DBOS Transact is the one engine light enough to embed
without compromising the product** — a library, SQLite by default, zero extra processes,
checkpoint-based rather than replay-based, with `DBOS.send`/`DBOS.recv` for human blocks
and `list_workflow_steps` for the board. Adopting it later would not change the template
format at all, only what sits under the interpreter. That is a cheap option to keep open,
and it is the reason to keep the interpreter's persistence behind a narrow interface.
(Caveat found: `recv`/`get_event` default to a **60-second** timeout and return `None` on
expiry — a human gate must pass a large explicit timeout.)

**Also worth watching:** `microsoft/durabletask-go` (Apache-2.0) is an embeddable durable
engine with a SQLite backend — exactly the right shape — but its README states plainly that
it "should not be used for production workloads." Not today.

### What to steal, from where

| Concern | Steal from | Why |
|---|---|---|
| Overall skeleton, backward jumps, `try`/retry-as-data | **CNCF Serverless Workflow DSL v1.0** | Named tasks; `then: <taskName>` performs an explicit jump *including backwards*; retry policy is pure data. Closest single prior art to what we need. |
| Authoring ergonomics: ordered `steps:` list, `id`/`name`/`if`, implicit fall-through | **GitHub Actions** | Every user already knows it. Ordering is implicit in the list, which is what makes "step 4 of 11" renderable. |
| **Human gate** | **Kestra `io.kestra.plugin.core.flow.Pause` + `onResume`** | Best-in-class: the gate declares *typed inputs* the human fills in, and downstream steps read them as the task's outputs. Strictly better than Argo's `suspend: {}` (opaque) or GitHub environments (approve/reject only). |
| Agent-step binding (tools, MCP, params, structured result) | **Goose recipes** (Block) | `parameters` with `input_type`/`requirement`/`default`, `extensions` (MCP servers), `response.json_schema` for structured output, `retry.checks` with shell success-checks, `sub_recipes`. Nearest existing thing to "a step binds specific agent behavior". |
| Guarded transitions / choice semantics | **Amazon States Language** `Choice` + `Catch` | JSON, public spec, and `Next` may name *any* state — backward edges are legal and AWS's own iterate-pattern tutorial does exactly this. Take the semantics, not the JSONPath I/O plumbing. |
| Structured result as the only thing the controller reads | **Goose `response.json_schema`** + **Kestra outputs** | Directly implements braindump principle #2 and the "controller reads STATE not transcripts" rule. |
| **Gate = decision + data, split** | **Airflow 3.1 `HITLOperator`** | `chosen_options` (the routing decision) is separate from `params_input` (the payload). The runtime routes generically on the decision; the data stays opaque. `HITLBranchOperator.options_mapping` maps a choice straight to a downstream task — which is exactly how a human gate composes with a back-jump. |
| Human-fillable form declared **as data** | **Windmill OpenFlow `suspend.resume_form`** | The only engine where "block until a human fills in a form" is fully declarative, form schema included. One schema renders a web form *and* a TUI form. Also worth taking: `mock` (test a template without burning agent tokens), `skip_if`, `stop_after_if`. |
| Timeout behaviour as a named enum | **Kestra `pauseDuration` + `behavior`** | `RESUME` / `WARN` / `CANCEL` / `FAIL` beats a boolean. A gate that times out needs four possible meanings, not two. |
| Jump-scope discipline | **Serverless Workflow v1.0** | "Flow directives may only redirect to tasks declared within their own scope." One rule that stops `goto` becoming spaghetti and keeps reachability analysis trivial. ASL has the same restriction across `Parallel`/`Map` boundaries. |

**Named answer to "which prior-art schema should ours most resemble":**
**CNCF Serverless Workflow DSL v1.0**, written with GitHub Actions' surface ergonomics.

### Explicitly rejected, and why

- **Statecharts / XState / SCXML as the authoring format.** XState v5's `setup()` genuinely
  does make machine configs JSON-serializable (implementations are named references like
  `{ type: 'doSomething' }`), and persisted snapshots give durability. But statecharts model
  *reactive* systems: an 11-step template becomes 11 states each carrying explicit outgoing
  transitions, and the **linearity is not encoded anywhere**. A UI cannot render "step 4 of
  11" from a statechart without inferring it, and a human hand-editing YAML has to maintain
  every edge by hand. We have a *procedural* problem — an ordered checklist with a few back
  edges — and the ordered list is both the honest model and the renderable one. Borrow
  guards; skip the formalism. (Note: our ordered-list-with-`goto` compiles trivially to a
  flat FSM if we ever need one, so this is not a one-way door. If the implementation is
  TypeScript, XState is a defensible *internal execution kernel* — just never the file format.)
- **DAG engines (Airflow, Argo, Dagster, Prefect, Tekton).** They forbid cycles by
  construction. Our headline feature is a cycle.
- **LangGraph as the runtime.** Its `interrupt()` / `Command(resume=...)` HITL model is the
  best in the agent world and we should copy its *semantics*, but a LangGraph graph is
  Python code, not data, and it wants to own the agent loop — which Claude Code already owns.

---

# The draft schema

Format: YAML on disk (JSON is the same document; the canonical in-memory/API form is JSON).
`schema:` is a required version discriminator so we can migrate.

## Design decisions and their justification

1. **`steps` is an ordered array, not a map.** ASL and Serverless Workflow both use a
   *map* of named states. That is a mistake for us: order is the primary thing a checklist
   UI renders, and a map has no order. We take GitHub Actions' array instead, and keep
   ASL's "any step may be named as a jump target" by requiring a unique `id`.
2. **Implicit fall-through, explicit override.** No `next:` means "the following step in
   the array". This keeps the common case (a linear list) free of ceremony — the whole
   fix-bug template is readable top-to-bottom — while `next:` gives ASL/Serverless-style
   arbitrary jumps.
3. **One loop mechanism, not two.** We considered a nested `loop:`/`until:` block (Kestra's
   `LoopUntil`, Serverless's `for`). Rejected: `goto` to an earlier `id` plus `max_visits`
   expresses the same thing, matches how users describe it ("go back to step 3"), and needs
   no nesting. **The UI derives the loop bracket from the back-edge** — if a step's `next`
   targets an earlier step, render a bracket around that span and an "attempt 2 of 3" badge.
   Nested groups can be added later without breaking anything.
4. **Two separate failure concepts, deliberately.** `retry` handles *transient* failure
   (the agent crashed, the network died) — same step, same intent, bounded attempts, data-shaped
   like Temporal's `RetryPolicy` / ASL `Retry`. `next` handles *semantic* outcome (the review
   said "revise") — a normal, expected result that routes elsewhere. Conflating them is the
   most common workflow-schema mistake.
5. **Every step declares `result.schema`.** This is the load-bearing decision. It is what
   makes "the controller reads only STATE" mechanically enforceable rather than a wish: an
   agent step is not `done` until it has emitted a JSON object validating against its schema.
   Borrowed from Goose's `response.json_schema`.
6. **The human gate carries a typed form.** From Kestra `onResume`. A gate is not a
   yes/no button; it is a small typed record the human fills in, which downstream steps and
   routing conditions read exactly like an agent's result.
7. **Bounded by construction.** `max_visits` on each back-edge, plus a global
   `policy.max_total_steps` runaway guard (LangGraph's `recursion_limit`, which defaults to
   1000 super-steps). A template with an unbounded back-edge fails validation at load time.
8. **Expressions are a tiny whitelisted subset**, evaluated over a fixed context
   (`inputs.*`, `steps.<id>.result.*`, `run.*`, `visits.<id>`). Operators: `== != < > <= >=
   && || !`, `in`, and nothing else. No function calls, no interpolation into arbitrary
   fields. This is deliberately weaker than GitHub's `${{ }}` or Argo's `expr`: expression-language
   sprawl is the single most-criticised property of every format surveyed, and a restricted
   grammar is also the only way the web UI can *render* a condition as a human sentence.
   *Considered and rejected:* Tekton's fully-structured `when: [{input, operator, values}]`,
   which needs no parser at all and is trivially form-renderable. It is the safer choice on
   paper, but `steps.code_review.result.verdict == "revise"` is what a human — and an LLM
   writing a one-off — will actually type. Note the real cost we are accepting: **JSON Schema
   cannot validate expression contents** (SchemaStore's `github-workflow.json` types `if` as
   `["boolean","number","string"]` and gives up). We therefore need a separate lint pass over
   expressions from day one, checking that every `steps.<id>` reference names a real,
   *earlier-reachable* step. Design for that linter now, not later.
9. **A human gate splits its decision from its data.** From Airflow 3.1: `decide` produces
   `result.decision` (a closed enum the runtime routes on generically) and `collect`
   produces `result.collected` (arbitrary typed fields the runtime never interprets). Every
   gate has a decision; only some carry data. This split is what lets the engine handle
   timeouts, defaults and routing without knowing anything about the domain.
10. **A gate must not hold an agent session open.** Prefect distinguishes `pause_flow_run`
   (holds infrastructure) from `suspend_flow_run` (releases it); n8n's Wait node "offloads
   data to the database" and reloads on resume. Ours are always the releasing kind: when a
   run reaches a human gate, the agent process and its session are torn down. A manual-test
   gate can sit for two days and must cost nothing.

## Schema reference (abridged)

```yaml
schema: agentflow/v1          # required, versioned
id: string                    # unique slug; filename should match
name: string                  # human label
description: string
kind: template | oneoff       # oneoff = throwaway, snapshotted, never reused

inputs:                       # runtime parameters (Goose `parameters`)
  - id: string
    type: string | number | boolean | enum | file | issue_ref
    required: bool            # default false
    default: any              # only for optional
    options: [..]             # required when type: enum
    label: string
    description: string

policy:
  max_total_steps: int        # global runaway guard (default 100)
  default_backend: claude | codex
  on_unhandled_error: escalate | fail   # escalate = open a human gate

steps:
  - id: string                # unique; jump target
    name: string              # shown in both UIs
    type: agent | human | command
    if: <expr>                # skip this step when false
    timeout: <duration>       # e.g. 30m

    # --- type: agent ---
    agent:
      backend: claude | codex          # defaults to policy.default_backend
      subagent: string                 # named sub-agent / persona to spawn
      worktree: bool                   # isolate in a git worktree
      prompt: string                   # inline, {{ input }} templated
      prompt_file: path                # or a file reference
      skill: string                    # last-resort prose injection (principle #1)
      tools:
        allow: [string]                # tool-name globs
        deny:  [string]
      mcp: [string]                    # MCP servers to expose (Goose `extensions`)

    # --- type: human ---
    human:
      instructions: string             # markdown, TEMPLATED AT RUNTIME so the gate can
                                       # show what the agent just produced (Prefect's
                                       # with_initial_data(description=...))
      assignee: string
      notify: [string]                 # channels to ping on entry (Kestra `onPause`)
      decide:                          # THE DECISION (Airflow `chosen_options`)
        prompt: string
        options: [string]              # closed enum; the runtime routes on this
        default: string                # also the value used on timeout
      collect:                         # THE DATA (Airflow `params_input`)
        - id: string
          type: boolean | string | text | enum | file
          label: string
          required: bool
          options: [..]
      editable: bool                   # AutoGPT HumanInTheLoopBlock: may the reviewer edit
                                       # the upstream payload before approving? A gate that
                                       # can only say yes/no is much less useful than one
                                       # that can correct the plan in flight.
      timeout: <duration>              # ISO-8601 or 4h
      on_timeout: resume | warn | cancel | fail   # Kestra `behavior`, default warn

      # result shape is fixed and machine-generated:
      #   { decision, collected: {...}, decided_by, decided_at }
      # `decided_by` is captured automatically (Jenkins `submitterParameter`) —
      # who approved is audit-relevant and must never be optional.

    # --- type: command ---  (deterministic, no LLM)
    command:
      run: string                      # shell
      cwd: string
      expect_exit: int                 # default 0

    result:
      schema: <JSON Schema>            # REQUIRED for agent steps.
                                       # human steps derive it from decide+collect.
                                       # This is all the controller ever reads.

    mock: <object>                     # OpenFlow `mock`: when the run is in dry-run
                                       # mode, skip execution and return this literal.
                                       # Lets us test a template end-to-end without
                                       # spending a single agent token. Do not skip this.

    retry:                             # TRANSIENT failure only (see decision 4)
      max_attempts: int                # default 1 (no retry)
      backoff: constant | exponential
      initial_interval: <duration>
      max_interval: <duration>
      jitter: bool

    next:                              # omit => fall through to next in list
      - when: <expr>                   # first match wins (ASL Choice)
        goto: <step-id> | end | fail
        max_visits: int                # cap on entering `goto` target this run
        min_budget: <cost>             # SWE-agent `min_budget_for_new_attempt`: don't
                                       # start another loop unless this much budget remains
        on_exhausted:                  # hit at the cap OR out of budget
          goto: <step-id> | end | fail
      - goto: <step-id>                # no `when` => default arm
```

Two optional escape hatches, both borrowed from things that clearly work in practice:

```yaml
    # Step-level executor override (BMAD `customize.toml` instruction strings).
    # A user must be able to say "run THIS step with Codex / with a shell script /
    # with a Claude Code native workflow" without us shipping a new step type.
    executor: claude | codex | shell | claude_workflow
    executor_args: {...}

    # Cross-iteration scratch memory (Task Master's `loop` progress file).
    # A markdown file the agent appends to each visit. Cheap, durable, human-readable,
    # survives process death, and gives a re-entered step a memory of prior attempts
    # without stuffing the whole history into `result`.
    scratch: .agentflow/runs/{{ run.id }}/{{ step.id }}.md
```

Two constraints the loader enforces, both borrowed:

- **Jump scope**: `goto` may only target a step at the same nesting depth (Serverless
  Workflow v1.0's rule; ASL enforces the same across `Parallel`/`Map` boundaries). With a
  flat v1 list this is trivially satisfied, and it keeps the rule in place for when we add
  groups.
- **Every back-edge must be bounded.** A `goto` targeting an earlier step without
  `max_visits` is a load-time validation error. No surveyed system enforces this — Argo,
  Serverless Workflow and ASL all let you write an unbounded loop — and it is the one place
  where an agentic tool must be stricter than general workflow engines, because an unbounded
  loop here spends real money.

**Run-state model** (not part of the template; this is what the status board queries):

```
runs(id, template_id, template_snapshot_json, status, current_step_id,
     inputs_json, created_at, updated_at)
     status: running | blocked | waiting_human | failed | done | abandoned

step_runs(run_id, step_id, attempt, visit_no, status, started_at, ended_at,
          result_json, error_json, agent_session_ref)
          status: pending | running | blocked | done | failed | skipped

events(id, run_id, ts, kind, payload_json)     -- append-only, for audit/undo
```

**This model was independently arrived at by the closest existing tool.** `no-mistakes`
(MIT, 7.4k★) runs a 9-step AI validation pipeline in front of `git push` and its SQLite
schema is `runs` / `step_results` / `step_rounds` — the same three tables, with
`step_rounds` recording each *re-entry* of a step (`round`, `trigger_type`, `findings_json`,
`reviewed_head_sha`, `user_findings_json`, `selected_finding_ids`, `fix_summary`). We should
adopt that third table wholesale: **our `visit_no` deserves to be a row, not a counter**,
because "what did review say on attempt 2, and which findings did the human pick to fix?" is
exactly what the status board and the controller need. Two more details worth copying from
it: `step_results.agent_pid` (orphan detection) and `last_activity_at`/`last_activity`
(so a stalled agent is distinguishable from a slow one). And its budget rule —
*"the reservation is written before the provider call, so a crash mid-request spends the
budget rather than silently granting a free retry"* — is the correct failure direction for
`max_visits` too.

Task Master independently landed on the other half: it stores workflow state in
`~/.taskmaster/<project-id>/sessions/` **specifically** "to avoid git conflicts and support
multiple worktrees", with rotating backups. Same conclusion as ours, reached from pain.

`template_snapshot_json` is essential: **snapshot the template into the run at start.**
Editing `fix-bug.yaml` must never change the meaning of a run already in flight. (Argo and
GitHub Actions both pin the definition at dispatch; this is a well-trodden lesson.)

## The "fix bug" template, expressed in it

```yaml
schema: agentflow/v1
id: fix-bug
name: Fix a bug from a GitHub issue
description: >
  Triage a GitHub issue, design and plan a fix, implement it behind review loops,
  hand off for manual testing, then merge.
kind: template

inputs:
  - id: issue
    type: issue_ref
    required: true
    label: GitHub issue
    description: Issue number or URL to fix

policy:
  max_total_steps: 60
  default_backend: claude
  on_unhandled_error: escalate

steps:
  # 1 ────────────────────────────────────────────────────────────────
  - id: triage
    name: Read issue and self-assign
    type: agent
    agent:
      worktree: true
      prompt: |
        Read GitHub issue {{ inputs.issue }}. Assign it to me and move it to
        "In Progress". Summarise what is actually being asked for.
      tools:
        allow: [Read, Grep, Glob]
      mcp: [github]
    result:
      schema:
        type: object
        required: [issue_number, title, restated_problem]
        properties:
          issue_number:     { type: integer }
          title:            { type: string }
          restated_problem: { type: string }
          acceptance:       { type: array, items: { type: string } }

  # 2 ────────────────────────────────────────────────────────────────
  - id: context
    name: Read context
    type: agent
    agent:
      prompt: |
        Locate every file relevant to: {{ steps.triage.result.restated_problem }}
        Do not modify anything. Report the files and the current behaviour.
      tools:
        allow: [Read, Grep, Glob, Bash(git log:*)]
    result:
      schema:
        type: object
        required: [files, current_behaviour]
        properties:
          files:             { type: array, items: { type: string } }
          current_behaviour: { type: string }
          open_questions:    { type: array, items: { type: string } }

  # 3 ────────────────────────────────────────────────────────────────
  - id: design
    name: Design
    type: agent
    agent:
      subagent: architect
      prompt: |
        Design a fix for {{ steps.triage.result.restated_problem }}.
        Relevant files: {{ steps.context.result.files }}
        {% if visits.design > 1 %}
        A previous design was rejected. Address these findings:
        {{ steps.design_review.result.findings }}
        {% endif %}
      tools:
        allow: [Read, Grep, Glob]
    result:
      schema:
        type: object
        required: [approach, tradeoffs]
        properties:
          approach:  { type: string }
          tradeoffs: { type: array, items: { type: string } }
          risks:     { type: array, items: { type: string } }

  # 4 ────────────────────────────────────────────────────────────────
  - id: plan
    name: Plan
    type: agent
    agent:
      prompt: |
        Turn this design into an ordered implementation plan:
        {{ steps.design.result.approach }}
      tools:
        allow: [Read, Grep, Glob]
    result:
      schema:
        type: object
        required: [tasks]
        properties:
          tasks:
            type: array
            items:
              type: object
              required: [description, files]
              properties:
                description: { type: string }
                files:       { type: array, items: { type: string } }

  # 5 ── review, with the ↻ back-edge to step 3 ──────────────────────
  - id: design_review
    name: Review design and plan
    type: agent
    agent:
      subagent: reviewer
      prompt: |
        Critique this design and plan against the issue. Be specific.
        Design: {{ steps.design.result.approach }}
        Plan:   {{ steps.plan.result.tasks }}
      tools:
        allow: [Read, Grep, Glob]
    result:
      schema:
        type: object
        required: [verdict]
        properties:
          verdict:  { enum: [pass, revise] }
          findings: { type: array, items: { type: string } }
    next:
      - when: steps.design_review.result.verdict == "revise"
        goto: design                 # ↻ back to step 3
        max_visits: 3                # design may be entered at most 3x per run
        on_exhausted:
          goto: design_stuck         # give up looping, ask a human
      - goto: implement

  # 5a ── escape hatch when the design loop exhausts ─────────────────
  - id: design_stuck
    name: Design loop exhausted — human decision needed
    type: human
    human:
      instructions: |
        The design review rejected three attempts. Latest findings:
        {{ steps.design_review.result.findings }}
      decide:
        prompt: How should we proceed?
        options: [proceed_anyway, retry_design, abandon]
        default: abandon
      collect:
        - id: guidance
          type: text
          label: Guidance for the next attempt
      timeout: 24h
      on_timeout: warn
    next:
      - when: steps.design_stuck.result.decision == "proceed_anyway"
        goto: implement
      - when: steps.design_stuck.result.decision == "retry_design"
        goto: design
        max_visits: 6
        on_exhausted: { goto: fail }
      - goto: end

  # 6 ────────────────────────────────────────────────────────────────
  - id: implement
    name: Implement
    type: agent
    timeout: 2h
    agent:
      prompt: |
        Implement the plan. Work only in the worktree for this issue.
        Plan: {{ steps.plan.result.tasks }}
        {% if visits.implement > 1 %}
        A previous attempt was rejected. Fix these:
        {{ steps.code_review.result.findings }}
        {{ steps.manual_test.result.collected.notes }}
        {% endif %}
      tools:
        allow: [Read, Write, Edit, Grep, Glob, "Bash(git:*)", "Bash(npm test:*)"]
    retry:
      max_attempts: 2                # transient crash only, NOT review failure
      backoff: exponential
      initial_interval: 30s
    result:
      schema:
        type: object
        required: [changed_files, tests_pass]
        properties:
          changed_files: { type: array, items: { type: string } }
          tests_pass:    { type: boolean }
          summary:       { type: string }

  # 7 ── review, with the ↻ back-edge to step 6 ──────────────────────
  - id: code_review
    name: Review implementation
    type: agent
    agent:
      subagent: reviewer
      prompt: |
        Review the diff against the plan and the issue's acceptance criteria:
        {{ steps.triage.result.acceptance }}
      tools:
        allow: [Read, Grep, Glob, "Bash(git diff:*)"]
    result:
      schema:
        type: object
        required: [verdict]
        properties:
          verdict:  { enum: [pass, revise] }
          findings: { type: array, items: { type: string } }
          blocking: { type: boolean }
    next:
      - when: steps.code_review.result.verdict == "revise"
        goto: implement              # ↻ back to step 6
        max_visits: 4
        on_exhausted:
          goto: manual_test          # stop burning tokens; let the human look
      - goto: manual_test

  # 8 ── the human gate ──────────────────────────────────────────────
  - id: manual_test
    name: Manual test
    type: human
    human:
      assignee: "@me"
      notify: [slack]
      instructions: |
        Branch is ready in the worktree for issue
        {{ steps.triage.result.issue_number }}.
        Changed files: {{ steps.implement.result.changed_files }}
        Verify against the acceptance criteria:
        {{ steps.triage.result.acceptance }}
      decide:
        prompt: Did manual testing pass?
        options: [pass, send_back, abandon]
        default: send_back           # what a timeout means
      collect:
        - id: notes
          type: text
          label: What broke / anything to note
        - id: screenshot
          type: file
          label: Optional evidence
      timeout: 48h
      on_timeout: warn               # nag, do not cancel the run
    next:
      - when: steps.manual_test.result.decision == "send_back"
        goto: implement              # ↻ human can also send it back
        max_visits: 6
        on_exhausted: { goto: fail }
      - when: steps.manual_test.result.decision == "abandon"
        goto: fail
      - goto: merge

  # 9 ────────────────────────────────────────────────────────────────
  - id: merge
    name: Merge
    type: agent
    agent:
      prompt: |
        Open (or update) the PR for issue
        {{ steps.triage.result.issue_number }}, wait for CI, then merge.
        Close the issue referencing the PR.
      tools:
        allow: ["Bash(git:*)", "Bash(gh:*)"]
      mcp: [github]
    result:
      schema:
        type: object
        required: [merged, pr_url]
        properties:
          merged: { type: boolean }
          pr_url: { type: string }
    next:
      - when: steps.merge.result.merged == true
        goto: end
      - goto: fail
```

Reading the template top-to-bottom gives exactly the braindump's numbered list. The two
`↻ repeat` entries are the two back-edges, and each one is bounded and has a named escape
route. The human gate is step 8 and it produces typed data that both routes the workflow
and is shown on the status board.

### One-off throwaway templates

Same schema, `kind: oneoff`. They are never written to `.agentflow/templates/`; they are
written straight into `runs.template_snapshot_json`. This means an LLM can author a
throwaway workflow as data, it validates against the same JSON Schema as a shipped
default, and it renders in the same UI — with no second code path. A one-off can also be
promoted to a real template later by writing the snapshot out to a file.

### Where things live

- `.agentflow/templates/*.yaml` — project templates, **committed to the repo** and
  reviewable in PRs (precedent: `.github/workflows/`, `.claude/agents/`, `.cursor/rules/`).
- `~/.agentflow/templates/*.yaml` — user-global templates.
- `~/.agentflow/state.db` — SQLite, WAL, **gitignored / not in the repo at all**. Run state
  is not source code and must never create merge conflicts.
- Publish a JSON Schema for `agentflow/v1` so editors autocomplete it, the same way
  SchemaStore's `github-workflow.json` makes GitHub Actions tolerable to hand-author. Ship
  the `# yaml-language-server: $schema=...` magic comment at the top of every template —
  that is the whole editor integration, and it works in VS Code with zero configuration
  (Serverless Workflow does exactly this). Generate per-step-type schemas from the step
  implementations so plugin-contributed step types get autocomplete for free, the way
  Kestra derives its schemas from plugin class introspection.

### Unblocking from outside the UI

Every good system in this survey gives a gate an out-of-band completion path, and it is
consistently the feature users love most: Step Functions' `SendTaskSuccess(taskToken)`,
Restate's `POST /restate/awakeables/{id}/resolve`, Windmill's `getResumeUrls()`, n8n's
`$execution.resumeUrl`, Trigger.dev's `POST /waitpoints/tokens/{id}/complete`. We should
mint a per-gate **resume token** on entry and expose `agentflow resume <token> --decision
pass --notes "..."` plus a localhost HTTP endpoint. Then a manual-test gate can be cleared
from a Slack message, a GitHub PR comment, or a Claude Code hook — not only from our UI.
Trigger.dev's token shape is worth copying wholesale: `{id, url, publicAccessToken}`, with
the `url` server-to-server and the token safe to hand to a browser.

### Storage and the status board

SQLite in WAL mode, one writer (the daemon) and many readers (CLI, web UI, TUI). This is
the boring, correct answer: the status board is a `SELECT` over `runs` joined to
`step_runs`, which is exactly the query a KV store cannot serve. Keep the append-only
`events` table for audit and time-travel, but derive the board from current-state rows —
a pure event-sourced design makes the board expensive for no benefit at this scale.

For change notification, the daemon owns the DB and pushes over a unix socket / SSE;
polling every 500ms is also entirely adequate for a single-user tool and is a fine v0.
Note `sqlite3_update_hook` is in-process only and will not see another process's writes.

### Resume semantics — the one genuinely subtle part

Steps must be **restartable, not resumable**. If the daemon dies mid-step we do not try to
reattach to a half-finished agent turn; we mark the attempt `failed`/`orphaned` and start a
new attempt of the same step. This is exactly LangGraph's rule — on resume "the runtime
restarts the entire node from the beginning" — and it is why agent prompts must be written
to be idempotent, and why side-effecting steps (merge, self-assign) must check before
acting. Track a heartbeat/PID per `step_runs` row so orphans are detectable on daemon start.

---

# Survey

Sections below, in the order they appear: **Area 2** statecharts · **Area 6** state storage ·
**Area 1** durable execution engines · **Area 3** declarative formats and human gates ·
**Area 5** loops and bounds · **Area 4** agent-native systems.

## Area 2 — Statecharts: XState, SCXML, and whether the formalism fits

**Verdict: the formalism is capable but is the wrong authoring model for us. Borrow guards
and persistence lessons; do not adopt statecharts as the template format.**

### XState v5

- **Machine configs *are* JSON-serializable — but only under `setup()`.** v5's `setup()`
  registers named `actions`, `actors`, `guards` and `delays`; the machine config then refers
  to them by name (`entry: { type: 'doSomething' }`). Stately's docs are explicit that
  implementations are "not directly related to the state machine's logic (states and
  transitions)". So a v5 machine really can be stored as data with code looked up by name —
  which is architecturally *the same idea* as our `type: agent` + named subagent/tools.
  This is the strongest argument for XState and it deserves to be taken seriously.
- **Persistence:** `actor.getPersistedSnapshot()` → store → `createActor(machine, { snapshot })`.
  Deep: invoked/spawned child actors persist and restore recursively.
- **Critical caveat, and it applies to us regardless of what we build:** the docs warn that
  *"if your machine logic changes, restored state may no longer match the new definition"*,
  and that on restore **actions do not replay** while **invocations restart**. Stately
  themselves suggest event sourcing as the more robust alternative for long-running
  processes. This is exactly why our design snapshots the template into the run row.
- Tooling: `@statelyai/inspect`, Stately Studio (visual editor, imports/exports machine JSON).

### SCXML

W3C Recommendation, **1 September 2015**. Gives `<state>`/`<parallel>`/`<final>`,
`<transition event cond target>`, `<history>` for pause/resume semantics, `<datamodel>`,
`<invoke>`, `<send>`/`<raise>`. Implementations exist (Apache Commons SCXML, SCION, uscxml,
Qt SCXML). It is a genuinely complete statechart standard — and it is XML, which alone
disqualifies it for a format users hand-edit in 2026. Worth reading for its `history` and
`cond` semantics; not worth adopting.

### Why statecharts are the wrong power level here

Honest argument **for**: history states are a real answer to "resume where you left off";
nested states would let a sub-controller be a compound state; guards are exactly our `when`;
orthogonal regions would model parallel agents.

Argument **against**, which wins:

1. **Our problem is procedural, not reactive.** Statecharts exist to tame systems where
   *any* event can arrive in *any* state (UI, telephony, embedded). Our workflow is an
   ordered checklist with two back-edges. Encoding a linear sequence as a statechart means
   writing 11 states each with an explicit outgoing transition — the sequence becomes
   implicit and must be maintained by hand.
2. **Order is our primary UI affordance.** "Step 4 of 11", a progress bar, a checklist in a
   TUI — all trivial from an array, all require graph analysis (and are ambiguous) from a
   statechart.
3. **Hand-authorability and LLM-authorability.** Users customize templates and LLMs generate
   one-offs. An array of steps with optional `next` is dramatically easier to produce
   correctly than a transition graph, and much easier to validate.
4. **State explosion / complexity is the standard critique of statecharts** for workflow
   modelling, and we would pay it for features (parallel regions, deep history) we do not yet need.

**Non-lossy fallback:** our ordered-list-with-`goto` is a strict subset of a flat state
machine, so it compiles to one mechanically if we ever need statechart semantics. And if the
implementation language is TypeScript, XState v5 is a perfectly reasonable *internal
execution kernel* behind our schema — that is an implementation choice, not a format choice.

Other libraries surveyed briefly: `robot` (tiny, code DSL), Python `transitions` (supports
nested HSM + diagrams, config is data-ish), `python-statemachine`, Rust `statig`/`rust-fsm`,
Go `looplab/fsm`, .NET `stateless`, Ruby `AASM`. Most define machines in a code DSL rather
than data; `transitions` and `looplab/fsm` are the closest to data-driven.

## Area 6 — State storage for local-first tools (firsthand findings)

### SQLite in WAL mode is the answer

From the SQLite WAL docs, verified:

- Multiple **readers concurrent with one writer**; readers never block writers and vice
  versa. Exactly our daemon-writes / CLI-and-UI-read topology.
- **Multiple processes on the same host can share a WAL database**, via the `-shm`
  wal-index. The opening process needs write permission on the `-shm` file (or the
  containing directory). This is what makes daemon + CLI + web UI on one file legitimate.
- **WAL does not work over a network filesystem** — shared memory can't cross machines.
  Irrelevant for a laptop tool, but a reason to keep the DB out of Dropbox/iCloud folders,
  which is a real user footgun worth documenting.
- `PRAGMA synchronous = NORMAL` + WAL: writers skip the fsync on commit, so a transaction
  "might rollback following a power failure or hard reset". Note the nuance — an
  *application crash* does not lose committed data, only OS crash / power loss does. For a
  workflow checklist that is the right trade; use `NORMAL`.
- Add `busy_timeout`, and use `BEGIN IMMEDIATE` for write transactions to avoid
  upgrade-deadlock `SQLITE_BUSY`.

Ad-hoc queryability is the deciding factor over any embedded KV (RocksDB/LMDB/redb/fjall/
BadgerDB): the status board is inherently a query — *"every run, its current step, and
whether it is blocked"* — and a KV forces us to hand-maintain every index. SQLite also gives
free debuggability (`sqlite3 state.db 'select …'`) and JSON1 (`json_extract`, generated
columns + indexes) for the arbitrary result payloads.

### Litestream / replication: not needed

Litestream is alive (v0.5.x, actively maintained) and cheap, but it solves "my single server
might die and I need the data in object storage". For a single-user local dev tool, run
state is *reconstructible* — the git worktrees and the GitHub issues are the real durable
artifacts. An export/backup command is sufficient. Skip replication; revisit only if we ever
sync across machines.

### Event sourcing vs current state

Real engines split about evenly and the split is instructive: Temporal is pure append-only
event history with deterministic replay; LangGraph persists *checkpoints* (state snapshots
plus pending writes) per thread; DBOS writes workflow-status and step-output rows in
Postgres; Airflow keeps mutable `TaskInstance` rows.

We should be **hybrid, weighted toward current-state**: `runs` + `step_runs` rows are the
source of truth for the board (cheap indexed queries), and an append-only `events` table
gives audit, "what happened", and a future undo/time-travel. Pure event sourcing would make
the status board a fold over history for no benefit at ten-runs scale. Pure current-state
would throw away the audit trail that makes a controller's decisions reviewable.

The best local-first model of resumable state to imitate is **`git rebase`**: it stores
in-progress state as plain files under `.git/rebase-merge/` (`todo`, `done`, `msgnum`,
`onto`, `head-name`) and supports `--continue` / `--abort` / `--skip`. That is precisely our
step machine, solved with a done-list and a todo-list, and it is worth mirroring the
*conceptual* model (a stack of remaining steps + a record of completed ones) even though we
store it in SQLite. Jujutsu's operation log is the same idea generalized to undo.

### Change notification

`sqlite3_update_hook` is **in-process only** — it will not fire for another process's
writes, so it cannot drive a UI watching a daemon's DB. Practical options, in order:
daemon owns the DB and pushes over a unix socket / SSE (correct); file-watch the `-wal`
file (works, noisy); poll every 500ms (genuinely fine for a single-user tool, and the right
v0). Start with polling, add SSE when the web UI lands.

### Templates in git, run state not

Split them. Templates are source: `.agentflow/templates/*.yaml`, committed, diffable,
reviewable in a PR — the precedent is `.github/workflows/`, `.claude/agents/`,
`.cursor/rules/`, `devcontainer.json`, and Goose recipes. Run state is ephemeral machine
state: SQLite under `~/.agentflow/` (or a gitignored `.agentflow/state.db`), never
committed, because run state in git means merge conflicts on every branch switch.

## Area 1 — Durable execution engines, in full

### Footprint comparison (single user, laptop)

| Engine | Processes | Containers | External DB | Single binary / embeddable | Survives reboot |
|---|---|---|---|---|---|
| **DBOS Transact** | **1** (your app) | **0** | **none** — SQLite by default | **library** | yes |
| **Restate** | 2 | 0 | none (embedded RocksDB) | single binary | yes |
| **Inngest** (`inngest start`) | 2 | 0 | none (SQLite + in-mem Redis) | single binary | yes |
| Temporal (dev server) | 2–3 | 0 | SQLite via `--db-filename` | single binary (Go-embeddable) | **only with `--db-filename`** |
| microsoft/durabletask-go | 1 | 0 | none (SQLite) | library | yes — but WIP |
| Hatchet (lite) | 2 + worker | 2 | **Postgres** | no | yes |
| Windmill | 4–7 | 4–7 | **Postgres** | no | yes |
| Azure Durable Functions | 2–3 | 1 (Azurite) | Azure Storage emulator | no | yes |
| Cadence | many | many | **Cassandra/MySQL/PG** | no | yes |
| Trigger.dev v4 | 10+ | 10+ | **PG + Redis + ClickHouse** | no | yes |

Trigger.dev's published self-host requirements are worth stating plainly, because they
settle the question: webapp, Postgres, Redis, ClickHouse, s2-lite, Electric, supervisor,
Docker socket proxy, registry, MinIO, Traefik — **3+ vCPU / 6+ GB for the webapp machine
and 4+ vCPU / 8+ GB for the worker machine.** That is not a laptop tool.

### Human-in-the-loop primitives, compared

| Engine | Primitive | Shape |
|---|---|---|
| **Restate** | **Awakeables** | `const {id, promise} = ctx.awakeable(); await promise;` resolved by `ctx.resolveAwakeable(id, v)` **or plain HTTP `POST /restate/awakeables/{id}/resolve`**. The HTTP path means a shell script or a keypress can unblock a workflow with one `curl`, no SDK. Cleanest primitive in the survey. |
| **DBOS** | `send`/`recv`, `set_event`/`get_event` | `DBOS.recv(topic, timeout_seconds=N)` blocks durably; `DBOS.send(wf_id, payload, topic)` from anywhere. **Default timeout is 60s and returns `None` on expiry** — must be overridden for human waits. |
| **Temporal** | Signals / Updates + `await` | `@workflow.signal` handler sets a field; body sits in `workflow.await(lambda: ...)`. Blocks indefinitely, survives restarts. |
| **Step Functions** | `.waitForTaskToken` | Blocking-ness encoded as a **suffix on the Resource URI** — elegant. Token from `$$.Task.Token`; resumed via `SendTaskSuccess`/`SendTaskFailure`; kept alive by `SendTaskHeartbeat` with `HeartbeatSeconds`. **Max wait one year.** |
| **Inngest** | `step.waitForEvent` | `{event, timeout: "7d", match: "data.issueId"}` — correlate on a property path, returns the payload or `null`. |
| **Trigger.dev** | Wait tokens | `wait.createToken({timeout:"7d", tags:[...]})` → `{id, url, publicAccessToken}`; `wait.forToken(id)`; completed via SDK or HTTP. **`wait.listTokens({status:"WAITING"})` is a first-class "what's blocked" query** — an API design worth copying. Default timeout only 10m. |
| **Windmill** | `suspend` + `resume_form` | **Fully declarative** (see Area 3). |
| **Azure DF** | `waitForExternalEvent` | Canonical idiom is `Task.WhenAny(event, timer)` for a timeout race — worth copying regardless of engine. |

### Status board — how each answers "which step, what's blocked"

- **Restate — best remote-queryable.** It exposes an Apache DataFusion **SQL interface over
  its own state**, reachable over plain HTTP:
  `curl localhost:9070/query --json '{"query":"SELECT id,status FROM sys_invocation"}'`.
  System tables include `sys_invocation` (with a `status` enum covering `suspended`),
  `sys_journal`, `sys_service`, `state`. No SDK and no live worker required — which is
  precisely the braindump's "web and terminal are both just views over the same state".
  Caveat: only *active* invocations are retained; completed history is not archived.
- **DBOS — best local.** State lives in your own SQLite file, so the TUI and the web UI both
  just read it. Plus `list_workflows()`, `list_workflow_steps(id)`, `list_queued_workflows()`,
  and `cancel`/`resume`/`fork_workflow`. Statuses: `PENDING`, `SUCCESS`, `ERROR`, `ENQUEUED`,
  `CANCELLED`, `MAX_RECOVERY_ATTEMPTS_EXCEEDED`.
- **Temporal — worst fit.** Queries need a **live worker polling the task queue**, so the
  board fails when the app is closed. Search Attributes work on SQLite since server v1.20 but
  the dev server allows only **3 Keyword and 3 KeywordList attributes per namespace**, and
  they are eventually consistent with no propagation SLA.
- **Windmill** — `flow_status` already models per-module state; a ready-made board.

### Verdicts

| Engine | Too heavy for local-first single-user? |
|---|---|
| **DBOS** | **No** — lightest viable; the hedge if we ever want it |
| **Restate** | **No** — best if we want a language-agnostic HTTP boundary; BSL 1.1 caveat |
| Inngest | Borderline — light self-host, but SSPL, and dev-server persistence is undocumented |
| Temporal | **Yes** — ephemeral by default, worker-dependent queries, replay determinism fights template editing |
| durabletask-go | **Yes (for now)** — right shape, maintainers say not production-ready |
| Hatchet | **Yes** — mandatory Postgres for no benefit at this scale |
| Windmill | **Yes** — a whole low-code platform; steal OpenFlow instead |
| Azure Durable Functions | **Yes** — Azure-coupled, and *no versioning story at all* |
| Cadence | **Yes** — strictly dominated by Temporal |
| Trigger.dev | **Yes, emphatically** — steal the waitpoint API, do not run the platform |
| AWS Step Functions (service) | **Yes** (cloud-only) — **but ASL the format is the best single artifact in this survey** |

### Licensing, since we may distribute this

Temporal MIT · Cadence Apache-2.0 · Hatchet MIT · durabletask-go Apache-2.0 ·
**Restate BSL 1.1** (converts to Apache-2.0 four years after each release; the restriction
targets running a "Public Restate Platform Service", not shipping a local tool — but read it) ·
**Inngest SSPL v1.0** (converts to Apache-2.0 at three years; SSPL is genuinely restrictive
and needs a real legal read) · **Windmill AGPLv3** + paid EE.

### Local ASL tooling that actually exists

If we ever went ASL-shaped, we would inherit tooling — worth knowing, even though we aren't:
`asl-validator` (npm, JSON-Schema-based, also checks JSONPath syntax), `statelint`
(awslabs Ruby original; `wmfs/statelint` npm port), and `amazon-states-language-service`
(npm, wraps `vscode-json-languageservice` for validation/completion — what powers the AWS
Toolkit editor). Interpreters are thin on the ground: `@wmfs/statebox` (Node, MIT, ~45★),
`pyaslengine` (Python, small/new), `coinbase/step` (Go — **archived 2020**),
`checkr/states-language-cadence` (stale). AWS's own **Step Functions Local is officially
unsupported** — its docs now open by telling you to consider third-party solutions.
Conclusion: **no production-grade open-source ASL interpreter exists.** Anyone going
ASL-shaped writes the interpreter — which is the same conclusion we reached independently,
and a good sanity check that a purpose-built interpreter is normal rather than reckless.

### Footprints I verified directly

- **Temporal**: `temporal server start-dev` is a single CLI binary, uses **SQLite**
  (`--sqlite-pragma`, and `--db-filename` for persistence — *by default workflow executions
  are lost when the process dies*). Opens gRPC **7233**, Web UI **8233**, plus HTTP and
  metrics on random ports (`--headless` disables the UI). Still requires a separate worker
  process and an SDK, and workflows are **code**.
- **Restate**: genuinely "a single self-contained binary. No external dependencies needed."
  `restate-server`, ports 8080 / 9070 / 9071, UI on 9070, state in a `restate-data`
  directory. The cleanest footprint of any real durable engine. Workflows are still code
  (TS/Java/Go/Python/Rust SDKs), and its HITL primitive is durable promises / awakeables.
- **DBOS**: a **library**, not a server — "no separate orchestration server and no
  infrastructure required besides Postgres". The library model is exactly right for us; the
  **Postgres requirement is the disqualifier** for a laptop tool.
- **AWS Step Functions / ASL**: see the ASL notes below — the format is the interesting part.

### ASL as a format (evaluated directly against the spec)

Top level: `States` (a **map**, not a list), `StartAt`, `Comment`, `Version`,
`TimeoutSeconds`, `QueryLanguage` (JSONPath default, or **JSONata**).
State types: `Pass`, `Task`, `Choice`, `Wait`, `Succeed`, `Fail`, `Parallel`, `Map`.
Linking: every non-terminal state needs `Next` (except `Choice`), or `End: true`.

Three things ASL gets right that we should take:

1. **`Next` may name *any* state**, so **backward edges — loops — are legal**. The spec
   never forbids them; termination is achieved by reaching a terminal state. This is the
   proof that "ordered steps + named jump targets" is a sufficient loop mechanism.
2. **`Retry` is pure data**: `ErrorEquals`, `IntervalSeconds` (default 1), `MaxAttempts`
   (default 3), `BackoffRate` (default 2.0), `MaxDelaySeconds`. We copy this shape almost
   verbatim.
3. **`Catch` is routing-on-error**: `ErrorEquals` + `Next`. Cleanly separates "retry the
   same thing" from "go somewhere else", which is the distinction our `retry` vs `next`
   split preserves.

Two things ASL gets wrong for us:

1. **`States` is a map** — no inherent order, so a checklist UI has to reconstruct sequence
   by walking `Next` from `StartAt`, and any branch makes "step N of M" ill-defined.
2. **The JSONPath I/O plumbing** (`InputPath` → `Parameters` → `ResultSelector` →
   `ResultPath` → `OutputPath`) is famously painful. AWS effectively conceded this by adding
   JSONata. We avoid the whole category by having each step write a schema-validated
   `result` addressed as `steps.<id>.result`.

ASL also has **no loop-bound primitive** — to cap iterations you increment a counter in
state and add a `Choice`. Our `max_visits` is a direct improvement.

## Area 3 — Declarative workflow formats, and the human-gate patterns

### Step schemas at a glance

**GitHub Actions** — `id`, `if`, `name`, `uses`, `run`, `with`, `env`, `continue-on-error`,
`timeout-minutes`, `shell`, `working-directory`. `uses` and `run` are mutually exclusive
(the SchemaStore schema enforces it with a `oneOf` over `required` clauses).

**Kestra** — every task is `{id, type, ...}` where `type` is a fully-qualified class name.
Common properties: `description`, `disabled`, `timeout`, `retry`, `allowFailure`, `runIf`,
`workerGroup`. Verbose, but one uniform shape for everything.

**Serverless Workflow v1.0** — universal base properties on *every* task: `if`, `input`
(`{from, schema}`), `output` (`{as, schema}`), `export`, `timeout`, `then`, `metadata`.
That base set is well chosen and we take most of it.

**Tekton** — `params` with `type` + `default` + `description` is a good typed-input model;
results-via-filesystem-path is a container-ism not to copy.

**Conductor** — `name` / `taskReferenceName` / `type` / `inputParameters` / `optional` /
`asyncComplete` / `startDelay`. Note `asyncComplete: true` on *any* task keeps it
`IN_PROGRESS` rather than completing — i.e. **gating as a modifier rather than a node type**,
an interesting orthogonal design we are not taking but should remember.

### Kestra `Pause` — the model to copy

```yaml
- id: wait_for_approval
  type: io.kestra.plugin.core.flow.Pause
  onResume:
    - id: approved
      description: Whether to approve the request
      type: BOOLEAN
      defaults: true
    - id: reason
      description: Reason for approval or rejection
      type: STRING
      defaults: Well-deserved vacation
```

Without `delay:` the task "waits indefinitely until the task state is changed to Running";
with `delay: PT5M` it auto-resumes. The UI prompts for the `onResume` inputs on Resume, and
**downstream tasks read them as the Pause task's outputs**. That last property is the whole
design: a gate is a *typed data-producing step*, not a boolean button. Kestra's other
flowables are `Sequential`, `Parallel`, `Switch`, `If`, `ForEach`, and `LoopUntil`
("runs a group of tasks repeatedly until a boolean condition evaluates to true").

### Argo Workflows `suspend` — the model *not* to copy

```yaml
- name: approve
  suspend: {}
# or
- name: delay
  suspend:
    duration: "20"   # string; default unit seconds; "2m", "6h" also valid
```

Resumed with `argo resume WORKFLOW`. There is **no parameter-injection or approval-capture
mechanism** — it is an opaque "unpause" with no record of *who* decided *what*. For a
manual-test gate, where the tester's notes are the entire point, this is insufficient.

### CNCF Serverless Workflow DSL v1.0 — the closest overall skeleton

`do` is a map of named tasks executed sequentially. Task types: `call`, `do`, `emit`, `for`,
`fork`, `listen`, `raise`, `run`, `set`, `switch`, `try`, `wait`.

Flow control is the `then` property, whose values are `continue`, `exit`, `end`, **or the
name of a task — which enables backward jumps**, with the constraint that "flow directives
may only redirect to tasks declared within their own scope." Conditional execution is
`if: <runtime expression>`. Retry policy is data (`when`/`exceptWhen`, `delay`, `limit`,
`backoff` exponential|linear|constant, `jitter`). `listen` awaits external events with
`all`/`any`/`one` consumption strategies — the HITL hook.

This is the single closest prior art: named steps, implicit sequence, `if` guards,
`then: <name>` backward jumps, retry-as-data. Our schema is essentially this with
GitHub Actions' array-of-steps ergonomics and Kestra's typed human gate.

### Windmill OpenFlow — the only fully declarative human gate

OpenFlow is a real spec (openflow.windmill.dev) with a published OpenAPI definition. Any
flow module can carry a `suspend` block, **including the form schema**:

```yaml
suspend:
  required_events: 1        # number of approvals needed
  timeout: 1800             # seconds before auto-cancel
  user_auth_required: true
  self_approval_disabled: true
  resume_form:
    schema:
      properties:
        notes: { type: string, description: "Test notes" }
      required: []
```

`wmill.getResumeUrls()` returns `{resume, cancel}`; form values arrive downstream as
`resume["field_name"]`; a step can return `{default_args: {...}}` to prefill the form.
This is the only engine surveyed where "block until a human fills in a form" is expressed
**entirely as data, form schema included** — which is exactly what lets one definition
render both a web form and a TUI form. We copy the idea directly.

Module-level control fields also worth taking: `skip_if`, `stop_after_if` (with
`error_message`), `mock`, `continue_on_error`, `retry` (constant | exponential, with
`retry_if`), `cache_ttl`, `priority`. `mock` is the sleeper hit — it lets you exercise a
whole template without executing anything, which for us means testing a workflow without
spending agent tokens.

**Where OpenFlow doesn't fit:** its loops are **structured nested blocks**
(`forloopflow`, `whileloopflow`), not arbitrary backward edges. Our "↻ back to step 3"
would have to be restructured as "wrap steps 3–5 in a `whileloopflow` with a counter." That
is expressible but renders far worse as a flat step list. This is the crisp structural
difference: **ASL and Serverless Workflow are directed graphs with legal cycles; OpenFlow is
nested blocks.** We want the former.

### Airflow 3.1 HITL operators — newest and closest to our domain

```python
HITLOperator(*, subject, options, body=None, defaults=None, multiple=False,
             params=None, notifiers=None, assigned_users=None,
             response_timeout=None, **kwargs)
```

`subject` (headline), `body` (**Markdown**), `options` (the choices), `defaults` (used both
as prefill *and* as the value taken on timeout — one field, two jobs, neatly), `multiple`,
`params` (extra structured input), `assigned_users`, `notifiers`, `response_timeout`.
Returns **`chosen_options` and `params_input` as separate XComs**. Subclasses:
`ApprovalOperator` (options fixed to Approve/Reject, `fail_on_reject`), `HITLEntryOperator`
(pure data entry), and **`HITLBranchOperator(options_mapping=...)` which maps a chosen option
to a downstream `task_id`.**

That last one is the piece that makes human gates and back-jumps compose declaratively:
"Approve → continue, Revise → jump back to step 3, Abort → exit" is a mapping, not code.
Our `decide.options` + `next[].when` is the same construct spelled differently.

### The other human gates, briefly

- **GitHub Actions `environment:`** — the YAML is one line; required reviewers (up to 6),
  wait timer, branch policies and prevent-self-review all live in **repo settings, not the
  workflow file**. This is a deliberate security decision — *whoever can edit the workflow
  must not thereby be able to approve it* — and it is the one thing GitHub gets more right
  than Kestra. The cost is that the file is no longer self-describing. **Our position:** gate
  *shape* in the file (it is workflow logic), and if approver identity ever becomes
  load-bearing, keep the approver *list* somewhere trust-scoped and reference it by name.
  Note also that GHA's `workflow_dispatch` typed inputs (`choice`/`boolean`/`environment`/
  `number`, 25 max) and its `environment` gate are **completely unrelated mechanisms** — you
  cannot collect typed input at an approval point. That gap is precisely what Kestra's
  `onResume` and Airflow's `params` fill, and it is the strongest reason not to copy GHA here.
- **GitLab `when: manual`** — and a famous footgun to avoid: **`allow_failure` defaults
  differ by context.** Outside `rules` a manual job defaults to `allow_failure: true`
  (optional); inside `rules` it defaults to `false` (blocking). Make blocking-vs-optional an
  explicit, always-required field. GitLab also has `manual_confirmation` (a misclick guard on
  destructive jobs) worth stealing for a `merge` step.
- **Tekton** — no native gate; the community answer is the `ApprovalTask` custom task
  (openshift-pipelines/manual-approval-gate) with `approvers`, `numberOfApprovalsRequired`,
  and **mutable votes before quorum is reached**. M-of-N quorum is a good idea we don't need yet.
- **Jenkins `input`** — `message`, `ok`, `submitter`, `parameters`, and the injected value
  lands directly in scope. Also **`submitterParameter`** (capture *who* approved into a
  variable) — provenance of an approval is audit-relevant and we adopt it as mandatory.
- **CircleCI** — approval is a job that does no work (`type: approval`), zero input
  capability. Its genuinely interesting feature is elsewhere: **status-qualified
  dependencies** (`requires: [release: [failed, canceled]]`), i.e. edges conditioned on
  upstream outcome.
- **Conductor `HUMAN`** — has real assignment escalation (`assignments[]`, each with
  `slaMinutes`, cascading) and lifecycle `taskTriggers`. But it buries all of it in a
  magic `__humanTaskDefinition` key inside a generic `inputParameters` bag — invisible to
  validation — and points at externally-registered forms by `{name, version}`, so the
  workflow JSON isn't self-describing. **A catalogue of what not to do.**
- **Camunda 8 `userTask`** — the most mature model (assignee/candidate groups, priority
  0–100, due vs follow-up dates, explicit output mapping instead of blind variable merge),
  at the cost of BPMN XML and a modeler. Its `= expr` prefix for FEEL expressions is a nicer
  unambiguous marker than `${}`.
- **Serverless Workflow v1.0** — **has no first-class human gate.** Approval must be modelled
  as a CloudEvent someone emits via `listen`; no input schema, no form, no "who". This is the
  one place its otherwise-excellent DSL is a step backwards, and where we take Kestra instead.

### Linking models, compared

| System | Model |
|---|---|
| GitHub Actions | Steps: **implicit order, no linking at all.** Jobs: explicit `needs:` DAG |
| GitLab CI | Stages (implicit) + `needs:` to escape stage ordering |
| **Serverless Workflow v1.0** | **Implicit order + `then:` override** ← our model |
| Kestra | Implicit order; DAG only if you opt into a `Dag` task |
| Argo | Both: `steps:` (list-of-lists) or `dag.tasks[].depends` |
| Tekton | `runAfter:` + implicit result-based edges |
| ASL | Flat named map + explicit `Next` from `StartAt` |
| n8n | Pure edge list, no ordering at all |

**Argo's `depends` is the most expressive DAG syntax found** — a boolean expression over
task states: `depends: "task-a.Succeeded && (task-b.Failed || task-c.Errored)"` with
`.Succeeded/.Failed/.Errored/.Skipped/.Omitted/.Daemoned/.AnySucceeded/.AllFailed`. Powerful,
a real parser burden, and overkill for a linear model.

**n8n is the anti-pattern.** Its `connections` object is a separate adjacency map keyed by
node *display name*, and nodes carry `position: [x, y]` canvas coordinates in the same file.
Renaming a node rewrites edges; diffs are unreadable; merge conflicts are constant. Two rules
fall out for us, and they matter because our templates get committed to a repo and reviewed
in PRs: **never separate the edge list from the node list, and never put layout in the
document.** Our web UI computes layout from the step order and the back-edges.

### Expression languages, and what each costs

| System | Syntax | Engine | Impl cost |
|---|---|---|---|
| GitHub Actions | `${{ }}` | custom | High — own lexer/parser/contexts |
| GitLab CI | `rules.if: '$VAR == "x"'` | custom | Low |
| Argo | `when: "{{x}} == y"` | govaluate/expr | Medium |
| Kestra | `{{ }}` + `{% if %}` | **Pebble** (off-the-shelf) | Very low |
| Serverless WF v1.0 | `${ .expr }` | **jq** (mandated) | Low |
| **Tekton** | `when: {input, operator, values}` **or** `cel:` | none / CEL | **Trivial / Medium** |
| ASL (JSONPath) | 30-operator discriminated union | custom | Medium |
| ASL (JSONata) | `"Condition": "{% ... %}"` | JSONata | Low |
| n8n | `={{ $json.foo }}` | JS sandbox | High |

Two traps worth naming, because both are avoidable by decree:

- **GitHub's `if:` is implicitly an expression context**, so both `if: success()` and
  `if: ${{ failure() && steps.demo.conclusion == 'failure' }}` are legal. The SchemaStore
  schema types it `["boolean","number","string"]` and validates nothing. Result: a truthiness
  footgun. **Pick one — `if` is always an expression, or always requires delimiters. Never both.**
- **Serverless Workflow's strict vs loose modes**, where loose mode "returns string on
  failure." Silent-failure-to-string is a bug factory. **Don't offer two modes.**

### What each format gets wrong

- **GitHub Actions** — expression sprawl; no YAML anchors; no local execution (act is a
  third-party approximation); the `steps.x.outputs` → job `outputs:` double declaration;
  matrix `include`/`exclude` patch semantics nobody predicts correctly; `$GITHUB_OUTPUT`
  file-append as the only way to produce a value.
- **GitLab CI** — two overlapping condition systems (`rules` vs legacy `only`/`except`);
  context-dependent `allow_failure` defaults; three competing reuse mechanisms
  (`!reference`, `extends`, YAML anchors).
- **Argo** — everything must be a named template, so a 3-step pipeline is 60 lines;
  `{{ }}` is textual pre-parse substitution that fights YAML quoting; three expression
  languages in one file (`when` govaluate, `depends` custom, `expression` expr);
  `duration: "20"` must be a quoted string — a classic YAML type footgun.
- **Tekton** — CRD sprawl; results passed via filesystem paths; extreme verbosity; no gate
  without an external controller.
- **Serverless Workflow v1.0** — task kinds discriminated by *which key is present* rather
  than a `type:` field, which is elegant to read but **hostile to JSON Schema and to editor
  autocomplete** (you can't complete until the user has typed the discriminating key). The
  v0.8→v1.0 rewrite also invalidated the ecosystem, and much secondary documentation still
  describes v0.8 — a real research hazard. **We take its semantics but keep an explicit
  `type:` discriminator, Kestra-style.**
- **Kestra** — fully-qualified Java class names as `type:` is a lot of characters; Pebble is
  a templating engine doing double duty as an expression language; assignment is
  Enterprise-only; and `onResume` defaults **cannot be dynamic expressions**
  ([kestra#7926](https://github.com/kestra-io/kestra/issues/7926)) — we make gate defaults
  templatable from day one.
- **Conductor** — magic `__humanTaskDefinition`; JavaScript-in-JSON loop conditions; forms
  defined externally by name+version.
- **Camunda** — XML; a modeler is effectively required.

### Two structural ideas worth stealing that I nearly missed

- **Kestra makes control flow just another task.** `Sequential`, `Parallel`, `Switch`, `If`,
  `ForEach`, `Pause`, `Subflow` are all ordinary `{id, type, ...}` nodes. One uniform node
  shape, no special-cased grammar. Our `type: agent | human | command` follows the same rule,
  and any future `parallel` or `group` should be a step type rather than new syntax.
- **Conductor's `name` vs `taskReferenceName`** — *which definition* versus *this instance's
  identity in this workflow*, with outputs keyed off the reference. It's what lets the same
  task appear twice without collision. GitHub Actions has it as `uses` vs `id`. We have it as
  `agent.subagent` vs step `id` — worth being deliberate about, since a template that runs
  `review` three times needs three distinct result addresses.

## Area 5 — Loops, bounds, and why ours must be stricter

Max-iteration bounds in the wild: LangGraph `recursion_limit` (**default 1000** super-steps
as of 1.0.6, raises `GraphRecursionError`); Google ADK `LoopAgent(max_iterations=...)`;
CrewAI `max_iter`; AutoGen `max_turns` + termination conditions; OpenAI Agents SDK
`max_turns`; Temporal bounded by history size (warnings ~10k events, hard limits ~51,200
events / 50 MB) with `ContinueAsNew` as the escape; Argo `retryStrategy.limit`; ASL and
Step Functions have **no loop primitive at all** (25,000 history events is the only ceiling).

The finding that matters: **almost no general workflow engine bounds a backward jump.**
ASL lets you write an unbounded cycle. Serverless Workflow's `then: <taskName>` will happily
loop forever. Argo supports recursive templates. Conductor's `DO_WHILE` bounds only by an
outer timeout. They get away with it because an infinite loop in a CI pipeline wastes CPU.
**An infinite review→fix→review loop wastes money and produces slop**, so this is the one
place we deliberately exceed the prior art: `max_visits` on every back-edge is *mandatory*
and enforced at load time, `on_exhausted` must name a destination, and
`policy.max_total_steps` is a final backstop.

The retry-policy shape is well converged across systems and we adopt the consensus
(ASL's, essentially): `max_attempts`, `initial_interval`, `backoff` coefficient,
`max_interval`, `jitter`, and a list of retryable/non-retryable error classes. ASL defaults
worth copying: `IntervalSeconds: 1`, `MaxAttempts: 3`, `BackoffRate: 2.0`.

Loop-with-verification is a named agent pattern — Anthropic's "Building effective agents"
calls it **evaluator-optimizer**, alongside orchestrator-workers. Our design/review and
implement/review loops are exactly that, and the standard failure mode is the evaluator
never being satisfied. Bounding plus a named human escape hatch (`design_stuck`) is the
mitigation, and it is why the schema forces you to declare one.

## Area 4 — agent-native systems

### LangGraph — best HITL semantics in the agent world; wrong shape for us

- `interrupt(value)` pauses a graph mid-node; the value surfaces to the caller. Resume with
  `Command(resume=...)`, and "the value passed to `Command(resume=...)` becomes the return
  value of the `interrupt` call".
- Requires a checkpointer (`InMemorySaver`, `SqliteSaver`, `PostgresSaver`) and a
  `thread_id`; the checkpointer "writes the exact graph state so you can resume later, even
  when in an error state."
- **The caveat we must inherit:** on resume "the runtime restarts the entire node from the
  beginning — it does not resume from the exact line where `interrupt` was called." Side
  effects must be idempotent or placed after the interrupt. This is the single most
  important operational lesson in this whole survey, and it is why our steps are
  **restartable, not resumable**.
- Cycles: conditional edges routing back to an earlier node, bounded by `recursion_limit`
  (**default 1000 super-steps** as of 1.0.6; raises `GraphRecursionError`). Current step is
  readable at `config["metadata"]["langgraph_step"]`, so you can degrade gracefully before
  hitting the wall — we do the same with `visits.<id>` being addressable in conditions.
- **Definition is Python code, not data.** Disqualifying as our template format.

### Mastra workflows — closest agent-framework analogue to our design

`suspend()` pauses a step; `suspendSchema` types the payload handed *to* the human and
`resumeSchema` types what must come *back*. Resume:

```typescript
await run.resume({ step: step1, resumeData: { approved: true } })
```

`result.status === 'suspended'` with a `suspended` array of step IDs; snapshots persist to
configured storage (LibSQL/SQLite); nested workflows expose `suspendedStep.path`. The
typed-suspend/typed-resume pair is the same insight as Kestra's `onResume`, arrived at
independently — strong evidence that typed gates are the right design. Definition is
TypeScript, not data.

### Burr

An explicit state machine for LLM apps: `ApplicationBuilder().with_actions(...)
.with_transitions((from, to), ...).with_entrypoint(...)`, conditional transitions, and
`halt_before`/`halt_after` for human input via `application.step(inputs={...})`.
`application.graph` gives a static representation. Local persistence + a tracking UI.
Conceptually very close to us (state machine + cycles + a board), but the application is
Python code.

### Goose recipes — the agent-step binding to copy

The one widely-used *declarative* format for driving a coding agent. Fields: `version`,
`title`, `description`, `instructions` and/or `prompt` (at least one required),
`parameters`, `extensions`, `activities`, `settings`, `response`, `retry`, `sub_recipes`.

```yaml
parameters:
  - key: focus_area
    input_type: select          # string | number | boolean | date | file | select
    requirement: required       # required | optional | user_prompt
    description: Review focus
    options: [performance, security, maintainability]

extensions:
  - type: stdio                 # stdio | builtin | platform | streamable_http | frontend | inline_python
    name: github
    cmd: github-mcp-server
    timeout: 60
    env_keys: [GITHUB_TOKEN]

settings:
  goose_provider: anthropic
  goose_model: claude-sonnet-4-20250514
  max_turns: 50

retry:
  max_retries: 2
  timeout_seconds: 30
  checks:
    - type: shell
      command: "test -f review_complete.txt"
  on_failure: "rm -f review_complete.txt"

response:
  json_schema:
    type: object
    properties:
      issues_found: { type: number }
    required: [issues_found]

sub_recipes:
  - name: security_check
    path: ./security.yaml
    values: { scan_level: deep }
```

Three ideas we take directly: **`response.json_schema`** (structured result → our
`result.schema`, the thing that makes a state-only controller possible), **`extensions`**
(MCP servers bound per step → our `agent.mcp`), and **`retry.checks`** (success validated by
a *shell command exit code*, not by asking the model — very much in the spirit of the
braindump's "tools over prose"). Goose recipes have **no step sequencing, no loops, and no
human gates** — a recipe is one agent invocation. That gap is precisely our product.

### spec-kit (GitHub) — the anti-pattern to beat

Phases `/speckit.constitution` → `/specify` → `/clarify` → `/plan` → `/tasks` → `/analyze`
→ `/implement`, producing markdown artifacts under `.specify/`. There is **no
machine-readable workflow definition** — the process is "procedural and prompt-driven rather
than declaratively defined". So nothing can render where you are, nothing can enforce the
gates, and nothing can be queried. It is exactly the failure mode braindump principle #2
calls out, from the most prominent project in this space. Good validation of the thesis.

### herdr — confirmed viable as the substrate

Apache-2.0, open source, "the runtime your coding agents live on". Agents keep running when
the laptop closes. Detects **19 agent CLIs** out of the box including Claude Code and Codex.
Crucially: **"The CLI and the socket API are the same surface agents drive"** — agents can
split panes, start each other, prompt one another, and "wait for genuine blocking events
rather than relying on timed keystrokes". A plugin directory exists. This supports the
braindump's plan: herdr is the runtime, we are the orchestration + template + state layer
above it. The blocking-wait primitive in particular is what a step machine needs.


## Area 7 — Prior art: what already exists in agentic coding orchestration

Two structural findings dominate everything below.

**(1) Claude Code already ships a workflow engine.** Verified in the installed v2.1.223
binary: `.claude/workflows/*.js` (and `~/.claude/workflows/`), invoked as `/<name>`,
plugin-namespaceable, disabled by `--safe-mode` / `"disableWorkflows": true`. A script
exports a pure-literal `meta = {name, description, phases}` and calls a small runtime:

- `agent(prompt, opts?)` with `opts: {label, phase, schema, model, effort, isolation, agentType}`.
  **Passing `schema` forces the subagent to call a StructuredOutput tool and returns the
  validated object.** `isolation: 'worktree'` runs it in a fresh worktree, auto-removed if
  unchanged. Returns `null` if the user skips the agent mid-run.
- `pipeline(items, ...stages)` (no barrier), `parallel(thunks)` (barrier; throwing thunks
  become `null`), `phase(title)`, `log(msg)`, `args`, and `workflow(name, args)` for one
  level of nesting.
- `budget: {total, spent(), remaining()}` — *"a HARD ceiling, not advisory: once `spent()`
  reaches `total`, further `agent()` calls throw."*
- Determinism is enforced: `Date.now()`, `Math.random()` and argless `new Date()` **throw**,
  explicitly because "they would break resume". No filesystem or Node API access.
  Concurrency capped at `min(16, cores-2)`; 1000 agents per run.
- Persistence: the script is saved under the session dir; `resumeFromRunId` replays cached
  `agent()` results for unchanged `(prompt, opts)` pairs; per-agent results land in
  `<dir>/journal.jsonl`. Runtime functions `pauseWorkflowTask` / `skipWorkflowAgent` /
  `retryWorkflowAgent` / `killWorkflowTask` exist, and there is a `"paused"` status with
  `registerAdoptedWorkflowTask` for cross-session adoption.

**What it does not do, per its own documentation:** *"No mid-run user input. Only agent
permission prompts can pause a run. For sign-off between stages, run each stage as its own
workflow."* Resume is **same-session only**. It is imperative JS, so it is not renderable,
not user-editable as data, and not queryable. It is also never triggerable under `claude -p`,
the Agent SDK, or `bypassPermissions`.

**Read that as a buy-vs-build boundary, not a threat.** It is a very good *fan-out executor*
and a poor *workflow template*. The clean division: our step machine owns the durable,
gated, cross-restart sequence; a single `type: agent` step can delegate to a native workflow
(`executor: claude_workflow`) when it wants twelve parallel reviewers. Reimplementing
parallel subagent orchestration on top of a runtime that already caps concurrency, enforces
determinism, journals results and supports mid-run retry would be a waste.

**(2) No shipping tool anywhere has a user-authorable multi-step template with typed human
gates and repeatable steps.** The five holes, from a sweep of ~20 tools:

1. **No user-authorable workflow template exists.** `no-mistakes` has the machinery but
   hardcodes 9 steps in Go. BMAD and Sculptor have the sequence but only as prose an LLM
   must voluntarily obey. Claude Code's engine is imperative JS. **Vibe Kanban built
   structured task templates and then deleted them** (migration
   `20251020120000_convert_templates_to_tags.sql` drops `task_templates` and converts them
   to free-text tags) — the one genuine negative signal in this survey, and worth
   understanding before we commit.
2. **Gates are at the wrong altitude.** Every gate found — Vibe Kanban's `ApprovalRequest`,
   opencode's `Permission.Rule`, Sculptor's `ask_user_question`, Claude Code's
   `permissionDecision: "ask"` — fires on **a tool call inside a turn**. Only `no-mistakes`
   gates *between stages*, and it can't be reconfigured. Stage-level gates are open ground.
3. **Repeatable steps don't exist.** Nobody can express "run step 3 per item" or "repeat
   until green, max N". State of the art is `no-mistakes`' `auto_fix.<step>: N` (per
   hardcoded step), BMAD's `review_loop_iteration` capped at 5, and SWE-agent's
   `retry_loop: {max_attempts, min_budget_for_new_attempt, chooser}`.
4. **Board and engine are always separate products.** Backlog.md is a board with no engine;
   `no-mistakes` is an engine with no board; Vibe Kanban had both and is shutting down;
   Firstmate replaced the board with an LLM-written prose digest.
5. **Prose-as-control-plane is visibly failing, and its own practitioners say so.**
   Sculptor's `build` skill: *"agents that drift from this rhythm tend to forget to run
   verification, forget to commit, or skip ahead."* Backlog.md filed tasks just to detect
   stale agent-instruction files. Firstmate needs `disable_project_settings: true` so its
   gate agents don't inherit the wrong identity. **Host-side step state is the missing
   primitive** — which is braindump principle #2, confirmed empirically.

### The closest prior art: `no-mistakes` (MIT, 7.4k★, Go)

A local git proxy that runs an AI validation pipeline in a disposable worktree and only
forwards the push on green. Its step interface is the design we are generalizing:

```go
type StepOutcome struct {
    NeedsApproval bool   // step pauses for user action
    AutoFixable   bool
    Findings      string // JSON findings for TUI display
    Skipped       bool
    SkipRemaining bool
}
const ( StepStatusPending; StepStatusRunning; StepStatusAwaitingApproval;
        StepStatusFixing; StepStatusFixReview; StepStatusCompleted;
        StepStatusSkipped; StepStatusFailed )
const ( ActionApprove; ActionFix; ActionSkip; ActionAbort )
```

Note `ActionFix` as a distinct outcome from approve/skip/abort, and the
`ApprovalGateReconciler` interface that lets a parked gate auto-resolve when the world
changes (e.g. CI turns green) — *"implementations must be read-only and fail closed."*
Both are good ideas we should steal. Its limitation is exactly the gap we fill: one fixed
pipeline shape, tunable via `.no-mistakes.yaml` but not authorable, no board, no
cross-task parallelism.

### BMAD-METHOD (v6.10.0, MIT + trademark clause, 51.6k★)

Richest step semantics in the ecosystem, entirely as prose. v6 **abandoned its old XML/YAML
agent bundles and rebuilt on Claude Skills** — a `SKILL.md` shim shelling out to a Python
renderer that emits `workflow.md` pointing at numbered step files. Its `workflow.md`
declares the discipline our engine would *enforce*:

> **NEVER** load multiple step files simultaneously · **NEVER** skip steps or optimize the
> sequence · **ALWAYS** halt at checkpoints and wait for human input

Bounded loops with an escalation ceiling, stored in the artifact's own frontmatter:

> Before each loopback, read `{spec_file}` frontmatter `review_loop_iteration` (missing means
> `0`), increment it by 1, and write it back. **If it exceeds 5, HALT and escalate to the human.**

Resume is status-driven routing (`draft → step-02`, `ready-for-dev → step-03`,
`in-review → step-04`), and the board is a flat `sprint-status.yaml` with documented,
**monotonic** transitions (*"Never regress a story's status"*) plus an "epic lift" rule.

**The single best idea in BMAD: sub-agent invocations are user-overridable TOML strings.**

```toml
implementation_handoff = """
Launch a subagent with no prior conversation context, with this prompt:
> Read {spec_file} fully and implement it — the spec is the sole source of truth.
"""

[[workflow.review_layers]]
id = "blind-hunter"
name = "Blind Hunter"
instruction = """..."""     # "an override may run anything (e.g. an external reviewer via bash)"
```

That is a pluggable step-executor contract expressed as data, and it is why our schema now
has `executor` / `executor_args`. Merge semantics are deterministic (base → team → user;
scalars override, arrays append, arrays-of-tables keyed by `code`/`id` replace-or-append) —
a good model for shipped-default → user-customized template layering.

BMAD's unattended variant also carries a warning that lands directly on our design:
> Never run a subagent in the background / detached / async, and never end your turn to
> "await a completion notification." This workflow runs unattended: **there is no event loop
> to resume a yielded turn.** — precisely the thing a daemon-backed step machine fixes.

**Badly:** everything is prose an LLM chooses to obey; state is smeared across spec
frontmatter, `sprint-status.yaml` and in-memory variables with no transaction; loop counters
live inside the artifact being edited, so a botched edit loses the counter.

### Task Master (27.9k★)

`tasks.json` is **tag-namespaced** (`{tagName: {tasks, metadata}}`). Task fields: `id, title,
description, status, priority, dependencies[], details, testStrategy, subtasks[]`, plus rich
AI-guidance metadata worth stealing as a step-context format — `relevantFiles[]` with
`{path, description, action: create|modify|reference}`, `codebasePatterns`,
`existingInfrastructure`, `scopeBoundaries {included, excluded}`, `technicalConstraints`,
`acceptanceCriteria`. Two subsystems nobody discusses:

- **`autopilot`** — an explicit TDD state machine with `WorkflowPhase`
  (`PREFLIGHT|BRANCH_SETUP|SUBTASK_LOOP|FINALIZE|COMPLETE`), `TDDPhase` (`RED|GREEN|COMMIT`),
  typed `WorkflowEvent`s, `StateTransition {from, to, event, guard?}`, and
  `SubtaskInfo {attempts, maxAttempts}` — per-step retry budgets, same as ours.
- **`loop`** — shells out to `claude -p` N times with a **markdown progress file the agent
  appends to** as cross-iteration memory, terminating on a sentinel (`<loop-complete>` /
  `<loop-blocked>`) in the model's output. The progress file is a genuinely good cheap idea
  (now in our schema as `scratch`); the sentinel is not — a model that forgets to emit it
  burns all N iterations.

**Badly:** no human gates at all (`--dangerously-skip-permissions` is hardcoded into the
loop's argv — noted here as an observation about *their* code, not a recommendation);
`TaskStatus` has both `done` and `completed`, and `SubtaskInfo.status` uses a *different*
enum; one monolithic JSON blob rewritten wholesale, so git conflicts and lost writes.

### The rest, in one table

| Tool | Machine-readable workflow | Stage-level human gate | Loop w/ budget | State | Local-first | License |
|---|---|---|---|---|---|---|
| **no-mistakes** | Go enum (fixed 9 steps) + YAML tuning | **yes** — `awaiting_approval`, approve/fix/skip/abort | **yes** — `step_rounds` + per-step budgets | SQLite | yes | MIT |
| **Claude Code `Workflow`** | imperative JS | **no** (documented gap) | budget cap, no loop primitive | session journal | yes | proprietary |
| Firstmate | no — markdown/AGENTS.md | ~ prose "decision-holds" | ~ watcher rewake | md files + tmux | yes | MIT |
| Vibe Kanban | ~ Rust `ExecutorAction` chain | no — tool-level only | no | SQLite → ElectricSQL | core | Apache-2.0 |
| Conductor | no | no — manual diff review | no | worktrees + GitHub | ~ | closed |
| Crystal | no | no | no | SQLite | yes | MIT (**deprecated**) |
| Claude Squad | no | no (`auto_yes` *removes* them) | no | JSON files | yes | **AGPL-3.0** |
| Sculptor | ~ markdown plan folder | ~ `ask_user_question` | ~ prose "iterate until pass" | SQLite event log | yes | MIT |
| opencode | no (`steps` = turn cap!) | ~ `allow/deny/ask`, tool-scoped | no | SQLite | yes | MIT |
| Backlog.md | ~ task frontmatter + custom `statuses` | ~ status + AC checkboxes | no | git + markdown | yes | MIT |
| SWE-agent | **yes** — pure YAML | no | **yes** — `retry_loop` + chooser | trajectory file | yes | MIT |
| AutoGPT | **yes** — versioned node/link graph | **yes** — `HumanInTheLoopBlock` | no | Postgres | **no** | Polyform Shield |
| PocketFlow | no — ~100 LOC Python | no | per-node retry + fallback | **none** | yes | MIT |
| container-use | env config only | no (by design) | no | git branches + notes | yes | Apache-2.0 |

Notes on the ones that matter:

- **AutoGPT's `HumanInTheLoopBlock` is the only first-class gate node found**, and its shape
  is right: approve and reject are **two different output pins routing to different
  downstream paths**, and `editable: bool` lets the reviewer amend the payload in flight.
  That is why our gate is a `decide` + `next[]` pair rather than a boolean, and why
  `human.editable` now exists. Everything around it (cloud SaaS, Postgres+RabbitMQ, a
  visual builder, Polyform Shield licence, fixed block registry) is wrong for us.
- **SWE-agent is the cleanest declarative YAML in the survey** precisely because it never
  tries to express sequencing — a run is one agent loop, and "workflow" is tool bundles plus
  history processors. Its `retry_loop: {type: chooser, cost_limit, max_attempts,
  min_budget_for_new_attempt, chooser: {system_template, instance_template}}` is best-of-N
  with an LLM judge declared as data — the source of our `min_budget`.
- **PocketFlow (~100 LOC)** distils the right primitive: `post()` returns an **action
  string**, and the action selects the successor edge. That is our `next[].when → goto` with
  the condition moved into the step's own result. Worth remembering as a possible
  simplification: `result.verdict` *is* an action string.
- **Backlog.md has the best task-file format**, with delimited regions
  (`<!-- SECTION:PLAN:BEGIN --> … <!-- SECTION:PLAN:END -->`, `<!-- AC:BEGIN -->`) so a CLI
  can surgically rewrite part of a human-readable file. If we ever emit markdown artifacts
  alongside our YAML, use this convention. Its `config.yml` also makes `statuses` and
  `definition_of_done` user-definable — the only genuinely template-ish knob anyone ships.
- **Roo Code's `.roomodes`** has the best capability constraint found: per-mode write-path
  restriction via `groups: [read, command, [edit, {fileRegex: '...', description: '...'}]]`.
  Worth stealing for `agent.tools` — "this step may only edit test files" is a real thing to
  want. Its Orchestrator/"Boomerang" mode is *not* a workflow format, it's a system prompt,
  and the parent's entire memory of a subtask is one summary string the child chose to write.
- **`agent-os` v3 deleted its workflow layer** (v2.1 had real
  `profiles/default/workflows/{planning,specification,implementation}/*.md` with a
  verification sub-phase; v3 is five markdown slash commands delegating gates to Claude
  Code's plan mode and `AskUserQuestion`). Combined with Vibe Kanban's template deletion and
  Crystal's deprecation, that is three independent retreats from bespoke scaffolding toward
  host-native primitives. **Take it seriously as a caution: build the thin durable layer the
  host lacks, not a parallel universe.**
- **OpenHands V1 removed microagents** in favour of Agent Skills with `SKILL.md`-style
  frontmatter, and now reads `CLAUDE.md`/`GEMINI.md` directly. That is the **third**
  independent convergence on Claude's `SKILL.md` shape (BMAD v6, OpenHands V1, agent-os v3).
  Design implication: a step's prose should probably *be* a `SKILL.md` reference, with our
  YAML as the machine-readable envelope around it — which is what `agent.skill` is for.
- **"AgentOrchestrator / AO" does not exist as prior art.** A `gh search repos` sweep found
  only `jeremiah-k/agor` (16★, self-labelled alpha, built for copy-paste into web chat).
  Nobody owns the name or the niche.
- **Two of the best-known tools are dead or dying.** Vibe Kanban's README opens with
  *"Vibe Kanban is sunsetting"* despite 27.7k★; Crystal is *"Deprecated: February 2026"* and
  its successor pivoted away from orchestration toward being an AI-native IDE.

### Host primitives we would otherwise reimplement

Free substrate from Claude Code 2.1.223, worth designing *onto* rather than around:

- **Spawn/name/poll**: `claude --session-id <uuid>` (we choose the id up front),
  `claude --bg -n <step-name>`, `claude agents --json` (works without a TTY, returns
  `{pid, cwd, kind, startedAt, sessionId, name, status}`), `--worktree [name]`,
  `--max-budget-usd`, `--fork-session`, `--plugin-dir` (session-only plugin load, no
  install, no user-config mutation).
- **The real human-gate primitive**: hooks can return `permissionDecision: "ask"` (escalates
  to the interactive prompt) or exit code 2 (hard block, stderr becomes the reason). In the
  SDK, `canUseTool` sees every `AskUserQuestion` and every MCP tool marked
  `requiresUserInteraction` **even in `dontAsk` mode** — that is the programmatic hook our
  gates should sit on.
- **Auditability**: session JSONL at `~/.claude/projects/<cwd-slug>/<uuid>.jsonl` is a
  **DAG** (`parentUuid`/`leafUuid`), `isSidechain` marks subagent turns, `origin.kind:
  "human"` distinguishes typed from injected input, and `system` records carry `hookErrors`
  / `preventedContinuation` / `stopReason`. Gate decisions are auditable from the transcript
  without us storing transcripts.
- **Two traps.** `--bare` is slated to become the default for `-p`, so never depend on
  ambient `~/.claude` hooks in headless runs — pass everything via `--settings` /
  `--plugin-dir` / `--agents`. And **checkpoints are not a rollback story**: Bash-caused file
  changes (`rm`, `mv`, `cp`) are not tracked and subagent edits are not restored. Use git
  plus `isolation: worktree`.
- **TodoWrite has no durable store** — it lives in session state, reconstructible only from
  `tool_use` blocks in the JSONL, with no ordering guarantee, no gate concept, no assignee.
  **An orchestrator must own its own board.** Settled.

### Licences, if we ever vendor code

**Claude Squad is AGPL-3.0 — do not vendor.** AutoGPT's `autogpt_platform/` is Polyform
Shield, not OSS. BMAD is MIT plus a trademark clause covering "BMad/BMAD". Task Master is
NOASSERTION. Vibe Kanban and container-use are Apache-2.0. `no-mistakes`, Firstmate,
Sculptor, Crystal, Backlog.md, opencode, SWE-agent, PocketFlow, agent-os, claude-flow and
SuperClaude are MIT.


---

# Open questions and things to verify before committing

1. **Does `herdr agent wait` expose enough state granularity to drive a step machine?**
   The braindump already flags this and it remains the single biggest unknown. Our step
   machine needs a blocking "this agent reached a terminal state" primitive plus a way to
   read a structured result out. If `wait` only signals "the pane went idle", we need our
   own completion protocol (agent writes a result JSON to a known path, or calls a tool).
2. ~~**How does an agent step emit its `result`?**~~ **RESOLVED — both backends enforce
   output schemas natively in headless mode**, so `result.schema` is enforceable rather
   than aspirational, and we don't need a custom completion tool:
   - `claude -p "…" --output-format json --json-schema '{…}'`
   - `codex exec --json --output-schema <file> -C <dir> "…"`

   Claude Code's `Workflow` tool does the same thing internally: passing `schema` to
   `agent()` "forces the subagent to call a StructuredOutput tool" and returns the
   validated object. Our `result.schema` compiles straight down to these flags.
3. **Codex parity — better than expected.** Both backends now have: headless JSON with an
   enforced output schema (above), resumable sessions (`claude --resume <id>` is
   machine-wide as of 2.1.223; `codex exec resume --last|<id>`), and command-hook systems
   with the same `matcher`/`command`/`timeout` shape. **One asymmetry to design around:
   Codex's `Stop` hook cannot hard-block**, only prompt continuation — so any
   "keep going until done" trick built on Claude's blocking `Stop` hook has no Codex
   equivalent. Prefer driving iteration from our step machine, not from inside the agent.
   Still open: the Codex equivalent of `agent.subagent`, which may need a per-backend
   override block.
4. **Expression linter scope.** Confirm the whitelist grammar and write the reachability
   check (every `steps.<id>` reference must name an earlier-reachable step) before the
   schema ships, because JSON Schema provably cannot do it.
5. **Inngest dev-server persistence** — undocumented; if `inngest dev` is memory-only that
   settles a question we no longer need answered, but worth knowing if we revisit.
6. **Restate BSL 1.1 and Inngest SSPL** — if either ever becomes a dependency we ship,
   get a real legal read rather than relying on the summary above.
7. **Decide the boundary with Claude Code's native `Workflow` tool** before writing code.
   Proposal: our step machine owns the durable, gated, cross-restart sequence; a single
   `type: agent` step may delegate to a native workflow for parallel fan-out. Verify that a
   native workflow can be launched non-interactively — the docs say it is *never* prompted
   under `claude -p` / the Agent SDK / `bypassPermissions`, which may block this entirely.
   If it does, we own fan-out too, and `parallel` becomes a step type sooner than planned.
8. **Understand why Vibe Kanban deleted its task templates** (migration
   `20251020120000_convert_templates_to_tags.sql`) and why `agent-os` v3 deleted its
   workflow layer. Three independent retreats from bespoke scaffolding toward host-native
   primitives is the strongest disconfirming evidence in this document, and it deserves a
   direct look rather than a footnote. The distinguishing bet: those tools were replacing
   prose with *more prose*; we are replacing prose with **enforced host-side state**.
9. **herdr vs. running agents ourselves.** `claude --bg -n`, `--session-id <uuid>` and
   `claude agents --json` cover spawn/name/poll natively, which narrows herdr's value to
   panes, remote attach and the 19-CLI abstraction. Worth re-deciding now that the native
   surface is known, rather than assuming the braindump's conclusion.

## Validation note

The "fix bug" example above was parsed as YAML and checked against the rules this schema
declares: every `goto` resolves to a real step or a terminal, every back-edge carries
`max_visits`, every `agent` step declares `result.schema`, and every `human` step declares
`decide`. It passes. The four back-edges are
`design_review→design (3)`, `design_stuck→design (6)`, `code_review→implement (4)`,
`manual_test→implement (6)`. That check is about 30 lines of code — which is itself
evidence for the "build a small step machine" recommendation.

# Sources

Specs and references: [Amazon States Language](https://states-language.net/spec.html) ·
[ASL in Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-amazon-states-language.html) ·
[ASL iterate/loop tutorial](https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-create-iterate-pattern-section.html) ·
[waitForTaskToken](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html) ·
[Serverless Workflow DSL reference](https://github.com/serverlessworkflow/specification/blob/main/dsl-reference.md) ·
[Windmill OpenFlow](https://www.windmill.dev/docs/openflow) · [openflow.windmill.dev](https://openflow.windmill.dev/) ·
[Windmill flow approval](https://www.windmill.dev/docs/flows/flow_approval) ·
[SCXML (W3C Rec, 2015)](https://www.w3.org/TR/scxml/) ·
[SchemaStore github-workflow.json](https://json.schemastore.org/github-workflow.json)

Human gates: [Kestra Pause/Resume](https://kestra.io/docs/how-to-guides/pause-resume) ·
[Kestra Pause plugin](https://kestra.io/plugins/core/tasks/flow/io.kestra.plugin.core.flow.pause) ·
[Kestra approval processes](https://kestra.io/docs/use-cases/approval-processes) ·
[Argo suspending](https://argo-workflows.readthedocs.io/en/latest/walk-through/suspending/) ·
[Airflow HITL operators](https://airflow.apache.org/docs/apache-airflow-providers-standard/stable/_api/airflow/providers/standard/operators/hitl/) ·
[Prefect interactive flows](https://docs.prefect.io/v3/advanced/interactive) ·
[Conductor HUMAN task](https://orkes.io/content/reference-docs/operators/human) ·
[n8n Wait node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/) ·
[GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) ·
[Tekton manual approval gate](https://github.com/openshift-pipelines/manual-approval-gate)

Engines: [Temporal CLI server](https://docs.temporal.io/cli/server) ·
[Temporal search attributes](https://docs.temporal.io/search-attribute) ·
[Temporal async activity completion](https://docs.temporal.io/develop/go/asynchronous-activity-completion) ·
[Temporal DSL sample](https://github.com/temporalio/samples-go/tree/main/dsl) ·
[Restate local dev](https://docs.restate.dev/develop/local_dev) ·
[Restate awakeables](https://docs.restate.dev/develop/ts/awakeables) ·
[Restate introspection](https://docs.restate.dev/operate/introspection) ·
[DBOS architecture](https://docs.dbos.dev/architecture) ·
[DBOS configuration (SQLite default)](https://docs.dbos.dev/python/reference/configuration) ·
[DBOS workflow communication](https://docs.dbos.dev/python/tutorials/workflow-communication) ·
[Inngest self-hosting](https://www.inngest.com/docs/self-hosting) ·
[Inngest waitForEvent](https://www.inngest.com/docs/reference/functions/step-wait-for-event) ·
[Inngest Workflow Kit](https://github.com/inngest/workflow-kit) ·
[Trigger.dev wait tokens](https://trigger.dev/docs/wait-for-token) ·
[Trigger.dev self-hosting](https://trigger.dev/docs/self-hosting/docker) ·
[Hatchet Lite](https://docs.hatchet.run/self-hosting/hatchet-lite) ·
[Windmill self-host](https://www.windmill.dev/docs/advanced/self_host) ·
[durabletask-go](https://github.com/microsoft/durabletask-go) ·
[Azure Durable Functions](https://learn.microsoft.com/en-us/azure/durable-task/durable-functions/durable-functions-overview)

Agent-native: [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) ·
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) ·
[LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) ·
[Mastra suspend/resume](https://mastra.ai/docs/workflows/suspend-and-resume) ·
[Burr state machine](https://burr.dagworks.io/concepts/state-machine/) ·
[Goose recipe reference](https://block.github.io/goose/docs/guides/recipes/recipe-reference/) ·
[Goose sub-recipes](https://block.github.io/goose/docs/guides/recipes/sub-recipes/) ·
[spec-kit](https://github.com/github/spec-kit) · [herdr](https://herdr.dev)

State/statecharts: [XState machines](https://stately.ai/docs/machines) ·
[XState persistence](https://stately.ai/docs/persistence) ·
[SQLite WAL](https://www.sqlite.org/wal.html) · [Litestream](https://litestream.io/)

Prior art: [no-mistakes](https://github.com/kunchenguid/no-mistakes) ·
[Firstmate](https://github.com/kunchenguid/firstmate) ·
[BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) ·
[Task Master](https://github.com/eyaltoledano/claude-task-master) ·
[SWE-agent](https://github.com/SWE-agent/SWE-agent) ·
[Roo Code](https://github.com/RooCodeInc/Roo-Code) ·
[Cline workflows](https://github.com/cline/cline/tree/main/.clinerules/workflows) ·
[OpenHands](https://github.com/OpenHands/OpenHands) ·
[agent-os](https://github.com/buildermethods/agent-os) ·
[PocketFlow](https://github.com/The-Pocket/PocketFlow) ·
[AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) ·
[Vibe Kanban (sunsetting)](https://www.vibekanban.com/blog/shutdown) ·
[Backlog.md](https://github.com/MrLesk/Backlog.md) ·
[container-use](https://github.com/dagger/container-use) ·
[claude-flow/ruflo](https://github.com/ruvnet/ruflo) ·
[SuperClaude](https://github.com/SuperClaude-Org/SuperClaude_Framework)
