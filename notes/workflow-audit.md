# Switchboard Workflow and Prompt Audit

## Purpose

This audit maps the accepted operating model in `notes/workflow-redesign.md` onto the
Switchboard system that exists today. It covers delivered instructions and the runtime
mechanisms that make those instructions true or false.

This is a diagnosis and change-surface map. It does not edit prompts, runtime behavior,
trusted design documents, or the plans plugin.

## Audit basis and limits

- `DESIGN-TRUTH.md` is the current trusted product authority.
- `design/PLANS-AND-STEPS.md` is the current trusted plan design.
- `notes/workflow-redesign.md` records the newly accepted target behavior.
- The trusted documents now carry the accepted direct, shaped, ownership, review and landing
  model. Findings below describe the prompt/runtime system that still needs implementation.
- Switchboard-owned prompt composition was traced through the runtime. Host, provider,
  project, user, and platform instructions outside that composition remain external layers;
  Switchboard can accommodate them but cannot claim to own or render all of them.
- Historical briefs and plans were sampled for recurring shapes. They are evidence of what
  the producers encourage, not additional canonical instructions.

## Concrete vocabulary used in this audit

| Design concept | Concrete meaning | Current implementation surfaces |
| --- | --- | --- |
| Task owner | Agent accountable for the whole requested outcome and the next transition. | Usually a `lead`; sometimes a top-level `worker`; currently not represented as a first-class runtime fact. |
| Main agent | The task owner while executing an approved or directly authorized change. It may be a lead or worker; it is not a proposed role name. | `defaults/roles/lead.md`, `defaults/roles/worker.md`, task brief, plan ownership fields, parent-child relationships. |
| Direct path | Bounded change performed without a placeholder plan or separate change-approval ceremony. | Missing as a named runtime path; contradicted by the universal plans trigger and current plugin guide. |
| Shaped path | Work whose investigation, design, formal plan, and contract need approval before implementation. | Plans plugin, planner prompt, plan library, lead prompt, plan store and renderer. Current implementation starts the plan too late. |
| Planner | Bounded specialist who challenges and expands the evolving plan. | `defaults/plugins/plans/planner.md` and planner package behavior. It is not a normal role in the role table today. |
| Fresh review | Formal implementation review by an agent that did not author the target before review began. | Reviewer role, review step, delegation/runtime identity. Independence is prose-only and not consistently required. |
| QA | Optional specialized verification for an environment or perspective the main agent cannot efficiently cover. | `defaults/roles/qa.md`, `verify` and `evidence` preset bindings. Current prompt instead makes QA a routine test runner. |
| Human-action block | The first PR-comment section saying exactly what Andrew must test or decide. | Plan markdown renderer and `merge-human-review` output. Current renderer puts status and observability first. |

The role-to-responsibility mapping is therefore deliberate: the redesign does not require a
new `main` role. It requires current lead and worker paths to agree on who owns the whole
outcome, and runtime records to identify that owner where identity matters.

## Effective instruction assembly

### Initial spawn

`Broker.delegate` currently composes a new agent's Switchboard-owned instructions in this
order:

1. `defaults/protocol.md`, with repository overrides applied.
2. Generated spawn identity from `defaults/prompts.toml`.
3. Generated live role vocabulary from `defaults/prompts.toml`.
4. Workspace/concurrency fragment when the agent has a workspace.
5. Dispatcher-only operator menu when procedures exist.
6. An explicit ad-hoc prompt, otherwise the resolved role prompt.
7. Resolved globally bound, role-bound, and explicitly requested presets/plugins.

The task or idle instruction is delivered separately after spawn. Later turns can receive
just-in-time rules from `defaults/guidance.toml`, messages, notifications, applied presets,
capability changes, and workspace changes.

### Provider delivery differs

- Claude fragments are flattened and joined into one appended system-prompt file once per
  session.
- Codex fragments are written to a private `CODEX_HOME/AGENTS.md`. The fragments are
  separated by blank lines, but each fragment has already been flattened. Codex consumes
  this as a leading user-role instruction on turns rather than as a provider system prompt.
- Headings and paragraph structure inside source prompts do not survive flattening. Rules
  that rely on visual hierarchy are therefore weaker in delivery than in their source file.
- The same Switchboard text has different authority and recurrence semantics between the
  two providers. Current inspection tools do not expose this provenance as an effective
  prompt manifest.

### Active repository additions

- `.switchboard-shared/presets.toml` binds `house-rules` to every role.
- `.switchboard-shared/presets/house-rules.md` adds repository-wide landing, testing,
  trust, and verification policy.
- `.switchboard/roles/py-qa.md` adds a local role.
- `.switchboard/presets.toml` binds the local `py-qa` procedure.

### Approximate initial Switchboard-owned prompt cost

These counts exclude the task, later guidance/messages, and host/provider instructions.

| Role | Delivered characters | Large contributors |
| --- | ---: | --- |
| Dispatcher | 22,259 | protocol 8,458; role 8,525; house rules 2,777 |
| Lead | 21,730 | protocol 8,458; role 8,568; house rules 2,777 |
| Worker | 14,430 | protocol, worker role, house rules |
| Reviewer | 14,882 | protocol, reviewer role, evidence, house rules |
| Researcher | 14,570 | protocol, researcher role, evidence, house rules |
| QA | 15,160 | protocol, QA role, verify, evidence, house rules |
| py-qa | 14,220 | protocol, local role, py-qa preset, house rules |

Every role also receives plugin bindings for bug reports, suggestions, and plans. The
dispatcher and lead begin near 22,000 characters before knowing the task. This is not by
itself a failure, but it makes contradictions expensive and gives duplicated universal
rules disproportionate influence.

## Surface inventory

| Surface | Defined or assembled in | Audience and timing | Audit result |
| --- | --- | --- | --- |
| Universal protocol | `defaults/protocol.md`, `switchboard/config.py` | Every agent at spawn | Overloaded; contains lifecycle, delegation, human communication, landing, and formatting rules that do not all belong universally. |
| Role prompts and metadata | `defaults/roles/*.md`, `switchboard/roles.py` | Selected role at spawn | Dispatcher partly aligned; lead, reviewer, and QA materially conflict with the target model. |
| Generated spawn fragments | `defaults/prompts.toml`, `switchboard/broker.py` | Conditional at spawn | Live vocabulary is useful; unsupported-role behavior and flattened delivery weaken it. |
| Repository policy | `.switchboard-shared/presets/house-rules.md` | Every role at spawn | Useful trust/testing facts, but repeats workflow and test sequencing at universal scope. |
| Presets | `defaults/presets/*.md`, preset configuration | Bound at spawn or applied later | Evidence is reusable; verify makes QA routine; design-gate is tightly coupled to the old plan ceremony. |
| JIT guidance | `defaults/guidance.toml`, `switchboard/guidance.py` | Matching later turns/commands | Strong reusable mechanism; one rule hard-codes the obsolete lead/worker split. |
| Plans trigger | plans plugin agent instruction | Every role through plugin binding | Direct conflict: every landing change must use a plan, regardless of shape. |
| Plans guide | plans plugin `GUIDE` | Agent explicitly reads it | Direct conflict: investigation is outside the plan and small changes are not exempt. |
| Planner prompt | `defaults/plugins/plans/planner.md` | Spawned planning specialist | Strong research expectations, but owns a new formal plan, forces a fresh main, and remains load-bearing for the plan lifetime. |
| Plan library | `defaults/plugins/plans/library/*.json` | Plan authors and step owners | Approval placement is now early; implementation review, PR human action, evidence identity, and merge semantics remain wrong or incomplete. |
| Plan renderer/comment | `_markdown`, `_comment`, `comment` in plans plugin | PR readers | Stable comment identity exists; layout is observability-first and all step output is labeled `contract`. |
| Notifications | `[notify]` in `defaults/prompts.toml`, broker delivery | Later turns | Doorbells omit payload and cause inbox turns; child completion has partial coalescing but no cohort wait primitive. |
| Lifecycle guidance/errors | broker, CLI, stop hook, prompts | State transitions | Blocking/completion are mature; generic waiting and any/all waiting are absent. |
| Model/role vocabulary | `switchboard/models.py`, `switchboard/roles.py`, generated role list | Delegation and spawn | Exact catalog is available, but common shorthand is not normalized and unknown roles silently inherit worker defaults. |
| Briefs and handoffs | dispatcher/lead/planner prompts plus task text | Per delegated job | Lossless relay is good; producers encourage file-sliced, stepwise work and oversized handoff schemas. |
| External instructions | provider/platform/project/user layers | Provider-dependent | Not represented in the current Switchboard composition view; must be shown as external boundaries in inspection tooling. |

## Findings by workflow concept

### 1. Work-path selection and plan lifecycle — critical design conflict

**Intended meaning**

- Research or discussion can remain planless.
- A clear bounded change uses the direct path.
- Work needing shaping creates one lightweight evolving plan before investigation diverges.
- The same record grows into the formal plan and receives combined plan/contract approval
  before tracked implementation.

**Current surfaces and behavior**

- `DESIGN-TRUTH.md` and `design/PLANS-AND-STEPS.md` say every landing change gets a plan,
  small work is not exempt, and investigation happens before the plan.
- The universally bound plans instruction and plugin guide repeat that rule.
- The planner prompt expects completed investigation, then creates the formal plan.
- The plan library correctly anchors `change-approval` before implementation once that step
  exists. The recent approval-placement fix is sound and should be preserved.
- `change-approval.json` makes an exception for a trivial change by skipping the gate inside
  a plan. That is not the direct path; it still pays for the plan and its workflow.

**Required ownership**

- The trusted design authorities establish the target behavior.
- The plans plugin trigger, guide, planner prompt, and library vocabulary need one
  coordinated rewrite around explicit direct and shaped paths.
- Plan storage must support an initially sparse evolving record without requiring invented
  implementation detail.
- Path selection remains agent judgment. Runtime may record the selected path and validate
  the consequences, but should not infer complexity from syntax.

### 2. Dispatcher and operational vocabulary — partial alignment, runtime defect

**Intended meaning**

- Dispatcher routes; it does not investigate or implement.
- It preserves the human's objective and chooses the smallest suitable owner.
- Human-friendly model and role requests resolve to valid live vocabulary or actionable
  alternatives.

**Current surfaces and behavior**

- `defaults/roles/dispatcher.md` is intentionally context-light and routes to lead or worker.
  That responsibility is broadly correct.
- It always spawns even for a one-line question, so research/discussion and direct work are
  prematurely forced through a role choice before their shape is understood.
- `Tiers.resolve` deliberately passes any unknown model name through as a raw model ID.
  Thus `gpt5.6sol` is not mapped to `gpt-5.6-sol`; it becomes an invalid literal provider
  model.
- `Roles.get` permits an unknown role name and applies fallback worker behavior. This is a
  useful ad-hoc-role escape hatch but also turns typos into silently different authority.
- The dispatcher prompt contains an explicit exception explaining that parts of the
  surrounding protocol and house rules do not apply to it. That is evidence the wrong text
  is being composed, not a durable precedence model.

**Required ownership**

- Runtime should expose canonical names, normalize safe common variants, and return nearby
  exact choices on ambiguity or failure.
- Ad-hoc role creation should be explicit rather than indistinguishable from a typo.
- Dispatcher prompt should express routing judgment only after irrelevant universal rules
  are removed or conditionally delivered.

### 3. Lead, worker, and main-agent ownership — critical prompt contradiction

**Intended meaning**

- A lead owns the result and can investigate, edit, verify, integrate, and communicate
  directly.
- Delegation is optional and must have a concrete benefit.
- A worker owns a bounded delegated outcome, gathers its own context, and chooses its method.
- Whichever lead or worker owns execution is the main agent for that change.

**Current surfaces and behavior**

- `defaults/roles/lead.md` repeatedly says the lead gets other agents to do the work, must
  not read the codebase, must not implement, and should spend an initial scout before it can
  shape the work.
- JIT rule `delegate-to-a-lead` says a lead is expected to split and delegate while a worker
  does one piece.
- The worker prompt is much closer to direct ownership, but frames its assignment as one
  bounded piece and has no shared main-agent lifecycle.
- Current capabilities reinforce the old split: lead has delegation authority while ordinary
  workers generally do not.

**Required ownership**

- Rewrite lead as an active task owner, removing every prohibition on reading or doing its
  own work.
- Replace the JIT lead/worker split with guidance about when delegation earns its cost.
- Keep `main agent` as a recorded responsibility, not another role.
- Give a worker temporary delegation only through explicit bounded authority when a helper
  is justified; wider orchestration should still move to a lead.

### 4. Planner role and plan ownership — critical prompt and lifecycle conflict

**Intended meaning**

- Planner is a first-class bounded specialist and challenger.
- It expands the task owner's existing placeholder into an execution-ready plan.
- It challenges infeasible, over-scoped, over-delegated, or weakly verified designs.
- The original task owner normally continues; a fresh main is chosen only when justified.

**Current surfaces and behavior**

- Planner exists as a plugin package/prompt rather than a role in the live role table.
- Its research, alternative analysis, and proportional-plan language are useful.
- It assumes investigation is complete before planning, owns plan shape exclusively, writes
  a new formal plan, must spawn a fresh sibling main, and stays alive for completion and
  replanning handshakes.
- The guide and planner brief require exact agent names, many required handoff fields, and a
  large completion protocol. This makes planning infrastructure load-bearing and encourages
  overly specific briefs.

**Required ownership**

- Make planner selectable through generated role/capability vocabulary.
- Let it edit the existing evolving plan under a bounded ownership handoff.
- Preserve its challenge function and catalog validation.
- Return plan ownership/accountability to the task owner after planning; keep the planner
  available only when likely replanning value justifies it.
- Remove mandatory fresh-main and long-lived completion handshakes.

### 5. Delegation briefs — efficiency and ownership defect

**Intended meaning**

- Briefs specify objective, broad but firm scope, constraints, acceptance, evidence, and
  ownership boundaries.
- The receiver discovers relevant context and chooses detailed implementation.
- Related edits remain one coherent assignment unless isolation or specialization justifies
  a split.

**Current surfaces and behavior**

- Dispatcher relay preserves the human's words, which protects against scope loss.
- Lead instructions explicitly split work, assign disjoint files, and discourage the lead
  from gathering context itself.
- Planner handoff requires a large fixed schema and exact workflow mechanics.
- Representative historical briefs show file-by-file edits and command-by-command checking.
  These artifacts are not canonical, but they are the predictable output of the producers.

**Required ownership**

- Put brief quality rules once in the role that writes the brief or in a shared brief helper,
  not in every receiving role.
- Make the brief a scoped problem contract rather than an execution transcript written in
  advance.
- Generated runtime facts should supply exact workspace, role, model, capability, and plan
  identifiers instead of asking the author to restate or guess them.

### 6. Implementation, verification, and QA — prompt contradiction and inefficiency

**Intended meaning**

- Finish the coherent implementation before normal verification.
- Early diagnostics are allowed when they discriminate between causes or guide the change.
- Main agent owns failures and fixes.
- Run proportionate checks once per coherent result; broaden only when risk or changed
  evidence warrants it.
- QA is optional specialized coverage, not a routine test relay.

**Current surfaces and behavior**

- No canonical prompt clearly states the coherent-change boundary.
- Repository house rules say to run the touched test while editing and the full suite before
  commit/report. `verify.md` asks for tests, linter, build, and manual behavior.
- Lead decomposition plus narrow briefs causes each worker to verify its slice separately,
  after which the parent can verify the assembled change again.
- QA is bound to both `verify` and `evidence`; its role says it finds and runs verification.
  This invites the inefficient loop where QA discovers ordinary failures and sends them
  back to the author.
- Evidence formatting itself is useful and can support reuse, but it is not bound to a
  commit or environment identity.

**Required ownership**

- Put sequencing and proportionality in the main-agent role/workflow instruction.
- Repository policy may name the canonical test command without universally requiring it
  after every edit or for every risk level.
- Main agent performs ordinary tests/builds and fixes failures immediately.
- QA prompt should require a specialized environment, perspective, or manual scenario and
  should consume existing ordinary evidence instead of rerunning it.
- Runtime evidence records should identify target commit/artifact and environment so current
  results can be reused safely.

### 7. Independent review and reviewer fixes — critical authority gap

**Intended meaning**

- Every landing change receives a fresh implementation review; breadth is proportional.
- Reviewer classifies major, minor, and nit findings.
- Nits are omitted. Safe local minor fixes are applied by the reviewer and reported.
- Major findings are defensible: reachable live path, likelihood, impact, and remediation
  value are considered before returning work.

**Current surfaces and behavior**

- `review.json` says “run your own review” and does not require a fresh agent.
- Reviewer role is read-only and says any edit invalidates the review.
- There is no common severity vocabulary or cost/reachability analysis.
- Plan review is correctly fresh and optional, but that is design-plan review rather than
  mandatory independent implementation review.
- Independence, target commit, applied-fix identity, and unresolved blocking state are not
  runtime-enforced before PR creation.

**Required ownership**

- Reviewer role receives scoped write authority for the reviewed change.
- Review prompt owns severity judgment, live-path analysis, remediation value, and concise
  reporting of applied minor fixes.
- Runtime/validation owns independent identity, target commit/artifact, post-fix result
  identity, and the unresolved-major gate before PR creation.
- A reviewer that applies a minor fix remains the reviewer; only a material redesign or
  broad change returns ownership to the main agent and may require another fresh review.

### 8. Communication, waiting, and child cohorts — missing runtime affordance

**Intended meaning**

- Preserve current blocking, reply, cancellation, recovery, and cleanup behavior unless a
  concrete defect exists.
- A generic no-argument waiting state covers native subagents and background work and avoids
  the stop hook.
- Any/all cohort waiting reduces repeated completion turns.
- Ordinary mail payload reaches the recipient directly when safe; inbox remains durable
  history rather than a mandatory extra hop.

**Current surfaces and behavior**

- `notify.mail` sends only “You have mail. Run: sb inbox”; the broker stores the payload and
  rings a separate prompt.
- `notify.child_done` similarly wakes once per child and instructs an inbox read. Broker
  holdback/coalescing already reduces some duplicate rings and should be preserved.
- Protocol says never wait and to end the turn for a later poke.
- Runtime has `awaiting_task`, outstanding reply, and live-child stop-hook exemptions, but no
  generic waiting state and no `waiting --any` or `waiting --all` cohort operation.
- Lead prompt forbids provider-native subagents as equivalent to doing work itself, even for
  short bounded read-only assistance.

**Required ownership**

- Add explicit generic, any-child, and all-child wait state transitions with stop-hook
  recognition and causal wake conditions.
- Deliver message payload with the wake when transport limits allow, while keeping durable
  inbox state, sender marking, reply tracking, and interrupt semantics.
- Preserve existing ring holdback; extend it around declared cohorts rather than replacing
  it with polling.
- Update protocol and lead/worker prompts only after runtime semantics exist.

### 9. PR comment, human review, and landing — critical workflow and rendering gap

**Intended meaning**

- PR opens only after implementation, proportionate verification, and fresh review are
  complete.
- The first comment section is “what you need to do,” containing only checks agents could
  not cover, or an explicit statement that none remain.
- Root cause/feature intent, chosen solution, evidence, and reviewed commit follow.
- Detailed plan and execution record are secondary.
- Human landing approval applies to the current reviewed result; merge consumes that
  approval and evidence without routine reruns.

**Current surfaces and behavior**

- `create-pr.json` correctly waits on the implementation review in the plan path and posts
  one plan comment.
- The comment command uses a stable hidden marker and updates the same comment idempotently.
  This is a strong mechanism to preserve.
- `_comment` deliberately renders status, elapsed/tokens, dependency graph, every step
  output under a generic `contract` section, then gates and folded steps.
- `merge-human-review` is obliged by `merge`, after PR creation. At the first PR comment its
  output is normally empty and its gate is merely ahead. The actual manual checklist is
  therefore unavailable when the human first needs it.
- Even when populated, all step outputs—including approval, review, and manual checks—are
  grouped under `contract`, so their audience and purpose are lost.
- `merge.json` instructs updating the comment after merge, too late to make it the live
  review interface.
- Approval is prose in a step output. There is no structured approved head, reviewed head,
  evidence identity, or merge comparison to the current PR head.
- Switchboard has no GitHub PR merge state machine; the library describes what an agent
  should do. `sb merge` is a child-branch integration command, not PR landing.

**Required ownership**

- Move creation of the human-only checklist before PR opening; it is authored from already
  completed agent evidence.
- Replace the generic output dump with purpose-aware rendering. Human action comes first;
  intent/solution, evidence/reviewed commit, risks, then collapsed plan history follow.
- Keep the stable marker and single-comment update mechanism.
- Record approval, review, evidence, and current PR head identities structurally.
- Landing checks identity and unresolved state once, then merges; it does not automatically
  rerun tests or review. Unexpected head change pauses and explains exactly what changed.

### 10. Prompt ownership, composition, and efficiency — systemic defect

**Intended meaning**

- Each rule has one canonical owner.
- Roles receive authority and judgment guidance relevant to them.
- Runtime-generated facts replace guessed vocabulary.
- Conditional reminders arrive just in time.
- Effective prompt inspection preserves source, order, conditions, and provider delivery.

**Current surfaces and behavior**

- Protocol, role prompts, shared house rules, presets, plugin instructions, and briefs each
  restate parts of lifecycle, delegation, verification, reporting, and landing.
- Some duplication is intentionally defensive, but there is no provenance or precedence
  contract that distinguishes deliberate reinforcement from drift.
- Dispatcher uses prose exceptions to ignore surrounding rules. Lead receives universal
  work/landing detail despite being told never to do work. QA receives ordinary verification
  procedure by binding. These are composition defects, not wording defects.
- `defaults/guidance.toml` is a good conditional-delivery mechanism with conditions, repeat
  policy, provenance comments, and a delivery ledger. It should remain the preferred home
  for genuine later-turn reminders.
- Flattening destroys headings, bullet hierarchy, and paragraph priority. Source comments
  acknowledge this, but the delivered corpus still depends on prose order to carry
  precedence.
- No development command renders the actual effective instruction set with segment
  provenance, resolved bindings, task, conditional guidance, and provider semantics.

**Required ownership**

- Establish the canonical ownership table from the redesign before rewriting individual
  files.
- Remove wrong-layer text first, then reconcile contradictions, then shorten what remains.
- Preserve structural separation through provider delivery where supported; where not,
  explicitly render boundaries and order.
- Add a development-only effective-prompt renderer and small structural tests. Do not freeze
  whole prompts in giant snapshots.

## What is already worth preserving

- Runtime-generated live role and operator-procedure vocabulary.
- Layered repository overrides and preset resolution.
- JIT guidance conditions, repeat semantics, configuration, and delivery ledger.
- Capability and parent-child facts in runtime rather than prose alone.
- Early placement of change approval before implementation in the plan anchor system.
- Stable hidden marker and idempotent update for the plan's PR comment.
- Existing message durability, sender tags, reply tracking, interrupts, cancellation,
  restoration, and ring holdback.
- Plan validation for dependency structure and completed gates.
- Evidence prompt's emphasis on precise, independently checkable reporting.

The repair should reuse these mechanisms. The problem is not that every current component is
bad; it is that good mechanisms are composed around an obsolete ownership and plan model.

## Prioritized repair surface

### Authority baseline

`DESIGN-TRUTH.md` and `design/PLANS-AND-STEPS.md` establish the direct versus shaped paths,
active lead ownership, evolving plan, bounded planner, coherent verification, fresh review,
change record, human-first PR interface and identity-bound landing. Runtime and prompt work
is reviewed against those sources.

### Runtime foundations

Primary implementation surfaces:

- `switchboard/models.py`: model alias normalization and actionable resolution.
- `switchboard/roles.py`: explicit handling of ad-hoc roles versus unknown names.
- `switchboard/broker.py` and lifecycle/stop-hook code: task-owner/path identity, direct
  message delivery, generic waiting, cohort wakes, review/evidence/head identity.
- `defaults/plugins/plans/__init__.py`: evolving-plan lifecycle, validation, purpose-aware
  rendering, structured approval/review/evidence identity, and current-head checks.
- CLI/help surfaces: generated vocabulary, waiting commands, explicit path/state inspection,
  and effective-prompt rendering.

### Prompt and procedure rewrite

Rewrite as one coordinated pass after the runtime contract is settled:

- `defaults/protocol.md`
- `defaults/roles/dispatcher.md`
- `defaults/roles/lead.md`
- `defaults/roles/worker.md`
- `defaults/roles/reviewer.md`
- `defaults/roles/qa.md`
- `defaults/plugins/plans/agent.md`
- `defaults/plugins/plans/planner.md`
- the plans guide and plan library definitions
- `defaults/guidance.toml`
- `defaults/presets/verify.md`
- `defaults/presets/design-gate.md`
- repository `house-rules` where canonical test and landing policy remains necessary

Researcher and evidence prompts need a consistency pass, but they are not primary blockers.

## Cross-cutting conclusions

1. This is one system problem. The old premise—lead delegates everything and every landing
   change starts its plan after investigation—drives the plan, role, brief, test, review, and
   human-interaction failures together.
2. A prompt-only fix is insufficient. Model normalization, waiting, message delivery,
   review/evidence identity, PR-head identity, and human-first comment structure need runtime
   support.
3. A runtime-only fix is insufficient. Current lead, planner, reviewer, QA, plans-guide, and
   universal instructions would continue steering agents toward the old workflow.
4. Runtime vocabulary and state are the first implementation milestone. The prompt rewrite
   follows as one composition-aware change, not isolated wording fixes.
5. Validation should focus on identity and impossible state. Direct-versus-shaped choice,
   delegation value, verification breadth, and remediation value remain engineering
   judgment.
6. Real-use observation is the right behavioral validation. Focused tests should pin only
   concrete mechanisms such as alias resolution, state transitions, comment ordering,
   stable update identity, and approval/review/head binding.

## Coordinated repair contract

### Objective

Make Switchboard express and support one adaptive engineering workflow across prompts,
plans, roles, delegation, verification, review, human interaction, and landing.

The repair succeeds when straightforward work stays straightforward, uncertain work is
shaped before implementation, every landing change receives independent review, and the
human sees only the decisions and manual checks that genuinely remain theirs.

### 1. Follow one authority

- `DESIGN-TRUTH.md` and `design/PLANS-AND-STEPS.md` are the implementation authority.
- All prompts, runtime behavior and validation point to their adaptive workflow model.
- Conflicting old behavior is removed rather than documented as an alternative.

### 2. Support adaptive work paths

- Direct work uses the human's bounded request as authorization and creates no placeholder,
  formal plan, or separate change-approval gate.
- Research and discussion remain planless until a change path is deliberately entered.
- Shaped work creates one lightweight plan before investigation can diverge.
- The placeholder records objective, constraints, questions, and selected shaping steps
  without guessing implementation details.
- The planner expands that same record into the execution plan.
- Solution, formal plan, and change contract receive one human approval before tracked
  implementation.
- Material uncertainty discovered on the direct path moves the work to the shaped path.

Path choice remains engineering judgment. Runtime records the choice and protects the
transitions that follow from it.

### 3. Restore end-to-end ownership

- Dispatcher routes the request and preserves intent; it does not investigate or implement.
- Lead investigates, designs, edits, verifies, integrates, and communicates directly when
  that is the efficient path.
- Lead delegates only for independence, specialization, useful parallelism, extensive
  research, planning, review, or genuinely separable large work.
- Worker owns its bounded outcome, gathers its own context, and chooses the detailed method.
- `Main agent` describes whichever lead or worker owns execution; it is not a new role.
- The original task owner normally continues after planning. A fresh main requires a
  concrete continuity, capability, independence, or scale reason.

### 4. Make operational vocabulary reliable

- Generate supported role, model, capability, preset, plugin, and plan-step names from live
  configuration.
- Normalize safe common spelling and formatting variants such as `gpt5.6sol`.
- Refuse ambiguous input with nearby valid choices and the exact accepted form.
- Distinguish an intentional ad-hoc role from a misspelled configured role.
- Remove prompt instructions that require agents to memorize identifiers the runtime knows.

### 5. Replace procedural briefs with scoped ownership

- A delegation brief states the objective, broad but firm scope, constraints, acceptance
  conditions, evidence expectations, and ownership boundary.
- It does not preselect files, prescribe a command sequence, or divide coherent work into
  tiny edits unless those details are genuinely load-bearing.
- The receiving agent gathers context, reasons about alternatives, and determines execution
  details within the boundary.
- Main-agent handoffs preserve decisions, rejected alternatives, open risks, approval, and
  current evidence without copying the entire investigation transcript.
- Runtime-generated identity and workspace facts are referenced rather than retyped.

### 6. Make implementation and verification coherent

- The main agent completes the coherent implementation before normal verification begins.
- Early diagnostic or discriminating checks remain allowed when they guide investigation or
  implementation.
- Ordinary tests, builds, and agent walkthroughs run after the coherent result exists.
- Verification breadth follows risk and scope; a full suite is not a universal requirement.
- The main agent fixes ordinary failures instead of handing them to QA.
- Existing evidence is reused while its commit, inputs, and environment remain applicable.
- Review fixes receive only the targeted re-verification their impact warrants.
- QA is used only for a specialized environment, perspective, or scenario that adds coverage.

### 7. Require useful independent review

- Every landing change receives a fresh implementation reviewer.
- The main agent chooses one review brief or several facets according to risk.
- Reviewer evaluates correctness, scope, approved intent, tests, reachable live paths,
  likelihood, impact, and remediation value.
- Nits are omitted.
- Safe, local, unambiguous minor fixes are applied by the reviewer under scoped write
  authority and listed in the result.
- Major findings return to the main agent with enough evidence to defend why they matter.
- A rare, low-impact issue does not justify a large complex repair merely because it exists.
- Review, evidence, and reviewer-applied fixes identify the commit or artifact they cover.

### 8. Improve coordination without replacing working behavior

- Preserve current human blocking, reply tracking, interrupt, cancellation, restoration,
  cleanup, durable mail, sender identity, and notification holdback behavior.
- Add a generic no-argument waiting state for native subagents and background work.
- Add any-child and all-child waiting with causal wake conditions.
- Let declared cohorts complete without one agent turn per child notification.
- Deliver ordinary message content with its wake when safe while retaining the durable inbox.
- Permit short bounded provider-native assistance where it is useful; do not treat it as a
  replacement for an independent formal review.

### 9. Make the PR the human decision interface

- PR creation waits for coherent implementation, applicable verification, and fresh review.
- Manual checks are authored before the PR opens from gaps in completed agent evidence.
- The authoritative comment begins with `What you need to do`.
- That section contains only decisions or checks that require the human, or says plainly
  that none remain.
- Root cause or feature intent, selected solution, evidence, reviewed commit, and relevant
  risks follow.
- Detailed plan history and observability remain available after the human-facing summary.
- One stable comment is updated in place; competing plan comments are not added.
- Human approval applies to the current reviewed result.

### 10. Make landing safe without restarting the workflow

- Record the approved result, reviewed result, relevant evidence, and current PR head.
- Compare the expected and current target once when landing begins.
- Merge directly when approval and evidence still apply and required state is complete.
- Pause on an unexpected head, unresolved major review state, relevant red check, or
  cancellation/hold that reached the landing decision.
- Distinguish evidenced baseline or infrastructure failures from change failures.
- Do not automatically rerun tests, builds, reviews, or manual checks during merge.
- If merge or cleanup fails, report the exact unfinished action without claiming completion.

### 11. Rebuild prompt composition around canonical ownership

- Universal protocol keeps only universal communication, lifecycle, scope, and safety rules.
- Role prompts define role purpose, standing authority, ownership, and judgment.
- Plugin instructions define only plugin concepts and procedures.
- Command implementations and generated help own exact syntax and vocabulary.
- JIT guidance carries situational reminders instead of expanding every spawn prompt.
- Briefs own task-specific objectives, constraints, and acceptance.
- Change contract and plan own the behavior the human approved.
- Repository procedures own only repository-specific policy.
- A development renderer shows effective delivered instructions in order, with provenance,
  conditions, resolved bindings, flattening, and provider delivery semantics.

Remove wrong-layer and duplicated instructions before shortening the remaining prose.

### Mechanisms to preserve

- Generated live vocabulary and layered repository overrides.
- Capability and parent-child state.
- JIT guidance conditions and delivery ledger.
- Durable messages, sender tags, reply tracking, interrupts, and ring holdback.
- Plan dependency validation and early approval anchors.
- Stable PR-comment marker and idempotent update.
- Precise evidence reporting.
- Existing human blocking and cleanup behavior unless a focused defect requires adjustment.

### Explicit exclusions

- No universal plan requirement for every landing change.
- No complexity score or rigid heuristic that chooses direct versus shaped work.
- No new `main` role.
- No mandatory planner, scout, QA agent, fresh main, or multi-agent fan-out.
- No reviewer nit reporting.
- No reviewer authority for broad redesigns or ambiguous fixes.
- No ban on early diagnostic tests.
- No automatic full-suite, rebuild, re-review, or re-verification loop at merge.
- No attempt to make prompts a filesystem security boundary.
- No giant snapshots that freeze complete prompt wording.
- No rewrite of working communication and lifecycle mechanisms merely for uniformity.

### Ordering constraints

1. Trusted authority is reconciled before implementation follows the new model.
2. Runtime vocabulary, state, identity, and rendering contracts are settled before prompts
   promise them.
3. Plan lifecycle and PR rendering change as one coherent workflow, not isolated text edits.
4. Role, protocol, preset, plugin, guidance, and brief instructions are rewritten in one
   composition-aware pass.
5. Focused mechanism tests run after the coherent implementation is complete.
6. A fresh agent reviews the complete result before the PR opens.
7. Andrew validates judgment-heavy behavior by using the repaired workflow on ordinary work.

### Contract completion conditions

- Direct, shaped, and research/discussion paths are all usable without contradictory prompts.
- Approval cannot appear to authorize implementation that preceded it on the shaped path.
- Lead can complete a task without children.
- Planner can challenge and expand an evolving plan without becoming its permanent owner.
- Briefs preserve scope while leaving detailed engineering judgment to the receiver.
- Normal verification occurs once per coherent result unless evidence justifies another run.
- Fresh review happens before every PR and can safely absorb minor fixes.
- QA adds specialized coverage rather than relaying ordinary failures.
- Waiting and batched completion do not waste agent turns.
- The PR comment tells Andrew what to do before showing observability detail.
- Approval, review, evidence, and merge target the same identifiable result.
- Effective prompts have one canonical owner per rule and no material workflow contradiction.

## Audit outcome

The trusted authority, audit, coordinated repair contract and formal implementation plan now
agree on the target behavior. Implementation begins with runtime vocabulary and effective
instruction inspection in `notes/workflow-repair-plan.md`.
