# Plans, steps and templates — implementation plan

A PR-by-PR plan to build the `plans` plugin described in `design/PLANS-AND-STEPS.md`.
Ordered so each PR is independently reviewable and later PRs depend only on earlier ones.
A lead who has not seen the spec discussion can run this end to end.

**Design authority:** `design/PLANS-AND-STEPS.md` (Andrew-only). Where this plan and the
spec ever disagree, the spec wins and the discrepancy is a bug in this file.

**Format:** each PR has two bulleted sections — Problem, then Behavioral contract —
indented `-` / `---` / `-----`, bullets ~12 words (up to ~20 where genuinely tangled).
Metadata lines (Depends / Files / Verify) sit outside the two sections.

---

## Decisions locked before implementation

These resolve every open question the codebase scout surfaced. A running lead treats them
as settled; they are recommendations Andrew confirms by approving this plan.

- **D1 — Command surface is `sb plugin plans <verb>`.** No bare `sb plan` verb; that
  would be new `cli.py` core work the plugin system does not give for free.
- **D2 — Liveness is read by shelling out to `sb status --json` / `sb inspect <name>
  --json`.** A plugin `Context` has no store handle by design; the isolation contract holds.
- **D3 — The spawn trigger line lives in the plugin's `agent.md` fragment**, bound in
  `defaults/presets.toml` `all`. So deleting the folder removes the trigger, matching the
  spec's "delete = off = no agent is told plans exist." Not `protocol.md`, which survives
  deletion.
- **D4 — The plan-making instruction is a plugin command, `sb plugin plans guide`.** It
  lives in the plugin folder, so disabling or deleting the plugin removes it cleanly.
- **D5 — The bullet-format preset ships as a nameable-but-unbound preset.**
  Enforcement that it is spawn-only is convention, not code — consistent with the spec's
  "no stop hook, not doing enforcement yet." It is shared machinery rather than one gate's:
  it owns the bullet mechanics, `merge-human-review` uses the same format, and a step that
  names it may name its own two sections.
- **D6 — The `DESIGN-TRUTH.md` cut (PR6) is an Andrew-only edit.** The PR supplies the
  exact diff; Andrew applies it. It gates the merge gate (PR7).

---

## PR sequence and dependency graph

- PR1 — Plugin skeleton, state model, read + create + changelog
- PR2 — Step lifecycle write verbs (assign, tick, skip, note, checkpoint, rework)
- PR3 — Library steps, templates, obliged steps
- PR4 — Liveness and records derivation (live / dormant / abandoned / finished)
- PR5 — Spawn trigger, plan-making guide, role edits
- PR6 — Prose cuts (protocol, house-rules, DESIGN-TRUTH)
- PR7 — Gates (Change Approval, merge gate, gate preset)
- PR8 — Board hook (render plans under their worktree)
- PR9 — Analysis pass skill
- PR10 — Change Approval and Review as library steps

---
-----
- PR1 depends on nothing; PR2, PR3, PR4 depend on PR1.
- PR5 depends on PR1 (agents told about a plugin that works).
- PR6 depends on nothing; PR7 depends on PR3, PR5 and PR6.
- PR8 depends on PR4; PR9 depends on PR4; PR10 depends on PR3 and PR7.
- PR6 may land any time; PR7 must never precede PR6.

---

## PR1 — Plugin skeleton, state model, read + create + changelog

Depends: none
Files: `defaults/plugins/plans/__init__.py`, `tests/test_plans_plugin.py`
Verify: `sb plugin plans create`, then `show`/`list` render it; changelog append-only.

### Problem

- No plugin exists; nothing can create, hold or show a plan.
- Plans and steps each need an identity independent of worktree names.
- A plan must attach to one worktree without any worktree-id concept existing.
- The state file is written by many commands and must not corrupt.

### Behavioral contract

- Ships `defaults/plugins/plans/__init__.py` with `API=1`, `SCOPE="repo"`, `LOCK=True`.
---
- `register(reg)` declares `create`, `list`, `show`, `changelog` verbs.
- State is one JSON file under `plugins.state_dir()`, tmp-write then `os.replace`.
- Superseded: the store is one `p-<n>.json` per plan there, plus a `_meta.json`.
---
- Plan id `p-<n>` and step id `s-<n>` are monotonic, never reused.
- Superseded for steps: they number per plan from `step-1`, held in the plan's own file.
- A step is addressed `p-16/step-3`, or bare where exactly one plan holds that number.
- A plan stores its owning worktree as the **workspace name**, nothing about its liveness.
- A plan holds: id, workspace, steps, changelog, notes; JSON-like, open vocabulary.
- A step holds: id, name, progress, why, owner, try-count, notes, deps, checkpoints.
- `why` is the reason for the progress a step currently carries; PR2 fills it.
---
- `create` makes an empty plan or one with steps already present.
- `show <plan>` renders steps, deps and changelog; `list` shows plans on this worktree.
- The changelog is append-only, written only by commands, never hand-editable.
- Every mutating command appends a changelog entry carrying the agent-supplied reason.
- Two commands touching different steps never corrupt the file; the state lock serializes writes.

---

## PR2 — Step lifecycle write verbs

Depends: PR1
Files: `defaults/plugins/plans/__init__.py`, `tests/test_plans_plugin.py`
Verify: assign an owner, tick, skip with reason, add a note, bump a try count.

### Problem

- A plan can be created but its steps cannot progress, be owned, or be reworked.
- Progress must never be inferred; nothing ticks automatically.
- A skipped step must be a visible state, never an omission.
- Rework must be a count on a step, not a graph edge.

### Behavioral contract

- `assign <step> <agent>` sets the step's owner; reassigning simply overwrites it.
---
- Progress is set only by `tick <step>` or `skip <step> --reason`, never by `sb done`.
- A step is complete or skipped, never both; skip requires a reason.
- The reason is kept on the step as `why`, so a skip renders beside its state.
- `why` is overwritten by whatever moves progress next, including with nothing.
---
- `note <step> --text` and plan-level `note` append free-text notes.
- `checkpoint <step> --ref` records a reference to a brief or artifact, never its content.
- Re-entering a done step for rework bumps its try count; a count above one renders.
- Reassigning does not tell the old owner; the plan does not push to running agents.
- `add-step` invents an on-the-fly step; `dep <step> --after <step>` records fan-out/join edges.
- Edges are data the lead interprets; nothing executes, evaluates or enforces them.

---

## PR3 — Library steps, templates, obliged steps

Depends: PR1, PR2
Files: `defaults/plugins/plans/__init__.py`, `defaults/plugins/plans/library/*`,
`defaults/plugins/plans/templates/*`, `tests/test_plans_plugin.py`
Verify: name a library step; copy a template; add a merge step and see merge-human-review appear.

### Problem

- Every step is invented on the fly; nothing is reusable or named once.
- There is no way to start a job from a preconfigured plan.
- Creating a PR should oblige its review steps automatically, not by memory.
- An obliged step routed around by never creating it would be enforcement in appearance only.

### Behavioral contract

- A library holds step definitions; a named step in a plan links to its definition.
---
- A named step is a link plus its own run object: progress, owner, try-count, notes.
- Editing a library definition reaches every plan naming it, including live ones.
- A variant is a new on-the-fly step, never a forked or edited link.
- Library steps may compose into several steps, so long as nothing is circular.
- Later: a definition may carry a `command`, resolved onto the step and never run.
- What a plan holds is always flat; naming a composite expands it into flat steps.
---
- A template is a preconfigured plan; using one copies it, and the copy is freely edited.
- Nothing links a copy back to its template; named steps inside stay names.
- `template list` browses templates; the lead finds one once the work is shaped.
---
- Adding a merge step automatically adds its merge-human-review step; this is obliged, not optional.
- An obliged step may be skipped with a reason, never silently omitted.
- The catalogue may be nearly empty and the system still works.

---

## PR4 — Liveness and records derivation

Depends: PR1
Files: `defaults/plugins/plans/__init__.py`, `tests/test_plans_plugin.py`
Verify: kill a step's owner; `show` reports it dead without the plan storing that.

### Problem

- A step names its owner but cannot say whether that owner is alive.
- Liveness copied onto a step would disagree with the agent's real state.
- A plan whose worktree is gone must read as abandoned, not finished.
- There are no lifecycle hooks; condition must be derived, never written.

### Behavioral contract

- Owner liveness is read live by shelling to `sb status --json` / `sb inspect --json`.
---
- A step shows two things: its progress (ticked) and its owner's read status.
- The owner's status — working, blocked, dead — is never stored on the step.
- `show` renders a dead owner the moment it is displayed, routing nothing.
---
- Live / dormant / finished / abandoned are derived at display time, never written.
- All agents on a worktree closed → the plan is dormant; restored when they return.
- Worktree gone with open steps → abandoned; worktree gone, steps done → finished.
- A dormant or dead plan is never deleted; its record is kept as plain text.
- Cleanup means dropping out of the UI, never erasing the record.

---

## PR5 — Spawn trigger, plan-making guide, role edits

Depends: PR1
Files: `defaults/plugins/plans/agent.md`, `defaults/presets.toml`,
`defaults/plugins/plans/__init__.py` (adds `guide` verb), `defaults/roles/lead.md`,
`defaults/roles/worker.md`
Verify: a fresh spawn's prompt carries the trigger line; `sb plugin plans guide` prints it.

### Problem

- Agents are never told plans exist, so none are ever made.
- Knowing plans exist is not knowing when to make one.
- The lead's planning prose predates plans and reads as already satisfied.
- A sole worker is told to do nothing beyond its one task.

### Behavioral contract

- `agent.md` is one line: if your work heads for a landing change, read the plan guide.
---
- It is bound in `defaults/presets.toml` `all`, beside `@report-bug` and `@suggestions`.
- Deleting the plugin folder drops the binding, so no agent is told — matching "off".
- The trigger travels at spawn; the longer instruction does not.
---
- `sb plugin plans guide` prints the full plan-making instruction on demand.
- It explains when a plan exists, who creates it, and how to choose a template.
---
- `lead.md` "Plan, then re-plan" is trimmed to say the plan is now written, not held in head.
- `worker.md` gains a carve-out: a sole worker with no lead creates the plan, counting as lead.
- No role edit adds merge/push prose; that lives only in the files PR6 touches.

---

## PR6 — Prose cuts (protocol, house-rules, DESIGN-TRUTH)

Depends: none (may land any time; must precede PR7)
Files: `defaults/protocol.md`, `.switchboard-shared/presets/house-rules.md`,
`DESIGN-TRUTH.md` (Andrew-only — supplied as a diff for him to apply)
Verify: the three texts no longer forbid merging; each points at the merge gate instead.

### Problem

- Three texts tell every agent never to merge without its parent.
- The merge gate will tell an agent to merge, contradicting all three.
- That exact contradiction once split four agents' behaviour in one session.
- `DESIGN-TRUTH.md` is Andrew-only, so an agent cannot cut it.

### Behavioral contract

- `protocol.md` lines about push / open-PR / never-merge are cut back to a pointer.
---
- The pointer says: where a plan runs, the merge gate is the authority.
- `house-rules.md` "Landing work" push/PR/merge clause is cut to the same pointer.
- The unrelated "unproven belongs in your summary" bullet is left untouched.
---
- The `DESIGN-TRUTH.md` three passages (approval, cleanup, merge) are trimmed to a pointer.
- That edit is delivered as an exact diff; Andrew applies it, no agent edits the file.
- The DESIGN-TRUTH edit re-reads the whole file for consistency, never appends.
- After this PR, off is today's behaviour minus this prose — a weaker, honest promise.

---

## PR7 — Gates (Change Approval, merge gate, gate preset)

Depends: PR3, PR5, PR6
Files: `defaults/plugins/plans/__init__.py`, the bullet-format preset under
`defaults/presets/`, `defaults/plugins/plans/guide` text, `tests/test_plans_plugin.py`
Verify: a Change Approval step's exit blocks the agent; approving the agent clears the step.

### Problem

- A gate that needs a human has no representation on a step.
- A gate must not be a control surface Andrew edits; he talks only to agents.
- A child blocking at a gate would wrongly stand its lead down.
- The bullet format must be nameable without being auto-attached to spawns.

### Behavioral contract

- A gate is a step's exit condition requiring a human, not a step of its own.
---
- At a gate the owning agent blocks; the step shows its owner blocked.
- Answering the agent clears both; there is no unblocking a gate through the plan.
- A step is complete or skipped; a trivially small change may skip a gate with a reason.
---
- Change Approval is the design gate: summarise, block, before any implementation exists.
- Its format is the bullet-format preset — nameable, unbound, convention-only spawn-only.
- The bullet format is `-`/`---`/`-----`, ~12 words, ~20 where a contract branches.
- The preset owns the bullet mechanics; the step's definition names its own two sections.
- A gate message may point at a fuller artifact and may name the other plan.
---
- The merge gate creates the PR and writes the description; he is not asked whether to create it.
- On approval, merge / cleanup / delete-worktree / close-agents run automatically.
- Any failure in that chain — conflict, red checks, teardown — makes the agent block.
- A step is ticked before its teardown command runs, never after.
- The lead stays until its plan completes; a child at a gate does not finish it.

---

## PR8 — Board hook (render plans under their worktree)

Depends: PR4
Files: `switchboard/board.py`, `switchboard/richboard.py`, `tests/test_board.py`
Verify: an enabled plan renders under its worktree group in both renderers.

### Problem

- The board has no extension point; plugins cannot render anything.
- Plans must render under their worktree, where grouping already exists.
- Two renderers exist and share no row-emission code.
- Window-fit math assumes one or two lines per row.

### Behavioral contract

- The board grows one extension point rather than knowledge of plans.
---
- For each worktree group, the hook asks the plans plugin for extra lines.
- Both `board.py` and `richboard.py` gain the call at their per-group loop.
- Plan lines read owner liveness from the same `AgentStatus` row, not a new channel.
---
- The window / scroll math accounts for variable-height plan blocks per group.
- With the plugin absent or disabled, the board renders exactly as today.
- The hook never imports plugin spawn code; it reads rendered lines only.

---

## PR9 — Analysis pass skill

Depends: PR4
Files: `defaults/plugins/plans/` skill or `.md`, docs
Verify: run the pass over saved plans; it proposes additions without editing anything.

### Problem

- Saved plan records exist but nothing reads them back.
- Recurring patterns across jobs go unnoticed.
- The catalogue should grow from real runs, not be decided up front.
- The record is biased toward jobs that went well.

### Behavioral contract

- A recurring skill reads past plan records and proposes what to add.
---
- It suggests new steps, templates, presets, roles, tooling or optimisations.
- It only proposes; it never edits the catalogue or any plan.
- It reads records cold, so records must carry enough notes to analyse.
---
- It distinguishes rework-as-try-count from rework-as-added-step via the changelog.
- It flags abandoned plans so derailed jobs are not read as successful.
- It names its own bias toward well-run jobs in every output.

---

## PR10 — Change Approval and Review as library steps

Depends: PR3, PR7
Files: `defaults/plugins/plans/library/change-approval.json`,
`defaults/plugins/plans/library/review.json`,
`defaults/plugins/plans/library/create-pr.json`,
`defaults/plugins/plans/__init__.py`, the bullet-format preset under `defaults/presets/`,
`tests/test_plans_plugin.py`
Verify: `name-step create-pr` lands three steps; a multi-line `output` survives
`show --markdown` line for line and forges no row.

### Problem

- PR7's design gate lives in convention, so a plan gets it only if someone remembers.
- The gate and the review that checks it are not tied to the PR that needs both.
- `show --markdown` flattens every stored newline, so no step can carry prose to a PR.
- A `gate` field on a step that is later ticked paints the plan permanently red.

### Behavioral contract

- Change Approval is promoted into the step library and replaces the design gate.
---
- Its two sections are Scope & Objectives and Change Contract, in that order.
- Scope is the agent's to derive; the objectives are inferred from his own words.
- The Change Contract is high-level only, nested, and ordered for reading not building.
- Rejection redoes the design work, not the wording; try count up, progress back to `open`.
---
- The gate is prose in the step's `about`, as `merge` already does; no `gate` field.
- That is deliberate: a gate on a ticked step is a defect, and this step ends in a tick.
- The cost is that `show` prints no gate line, so the reader must know the definition.
---
- Steps grow an `output` field: the step's own finished result, written by hand.
- Change Approval puts the full approved text there; Review puts a compact verdict there.
- `show --markdown` dumps `output` as quoted lines, so no dumped line can forge a row.
- The terminal render prints it too, so a PR-only field is not a field nobody proofreads.
---
- Review is the review an agent would do anyway, plus two checks, never fewer.
- With Change Approval in the plan it also checks objectives met and contract aligned.
- Standing alone it is a plain review; skipping those two is not a defect.
---
- `create-pr` obliges Change Approval, which obliges Review — three steps in one act.
- Obligations are never deduped, so naming `create-pr` twice is two of each, by design.
- Minted deps are a starting shape: Change Approval is re-deped to the plan's root by hand.
- Either step may be skipped with a reason; neither may be omitted.

---

## Global acceptance (plan is done when)

- With the plugin enabled and bound, a lead creates a plan, runs it through Change Approval
  and a merge gate, and a change lands with merge / cleanup / teardown automatic.
- With the plugin deleted, no agent is told plans exist and the board renders as today.
- The merge gate never ships in a tree where PR6's cuts have not landed.
- `name-step create-pr` mints Change Approval and Review, and the approved contract
  reaches the PR comment as the lines he read, not as escaped `\n`.
