# Gas City (gastownhall/gascity) — Evaluation

Repo verified live: 1082 stars, MIT, Go, v1.4.0-era, **839 open issues** (huge — the
project dogfoods itself with fleets of agents filing bugs; issue turnaround is
often same-day, e.g. #5008 opened 01:49 closed 11:26 same day). Cloned shallow
copy inspected directly (source, not just docs).

## 1. "Zero hardcoded roles" — holds up

No `RoleXxx` Go enum/const/iota anywhere in `internal/` or `cmd/`. Grepping
`role` across all `.go` files turns up only unrelated JSON `"role":"user"`
chat-transcript fields and one doctor check (`checks_beads_role.go`, which is
a generic health check, not a role registry). `role` is registered as a
**data-driven custom bead type** alongside `agent`, `rig`, `session`, `spec`,
`convergence`, `step` (`internal/beads/contract/files_test.go`:
`types.custom: molecule,convoy,message,event,gate,merge-request,agent,role,
rig,session,spec,convergence,step`). Roles are named freely in TOML/beads
(e.g. `roles.requirements-planner` in test fixtures) with no closed set to
extend. Verdict: **the claim is true in source** — you can invent any role
name; nothing in Go gates it.

## 2. Is the formula system actually wired?

**Mostly yes, and the code backs it — but with real, currently-open gaps
that are the spiritual descendant of Gas Town's #3322.**

- Real execution path exists: `internal/formula` (compile) →
  `internal/graphv2` (graph model) → `internal/dispatch` (runtime). `gc
  formula show`, `gc formula cook`, `gc sling --formula` compile a TOML
  formula into a flat bead graph; the **control dispatcher** in
  `internal/dispatch` (files: `control.go`, `ralph.go`, `retry.go`,
  `drain.go`, `fanout.go`) is a substantial, non-stub implementation —
  e.g. `ralph.go` has `appendRalphRetryGraphEdges`,
  `buildRalphRetryGraphNode`, `finalizeRalphRetry` that actually create new
  attempt/iteration beads and dependency edges in the store (via
  `beads.GraphApplyStore`), which is what makes a `check`/`retry` step's
  next iteration Ready-visible and thus routable to an agent. This is a
  genuine "steps reach the agent" pipeline, unlike Gas Town's "parsed,
  merged, printed, never resolved."
- **But it isn't fully closed-loop in practice.** Open issues describe the
  Gas-City-flavored version of the same class of bug Gas Town had — steps
  get created/routed but don't autonomously *reach* an agent turn:
  - **#4382** (open): "reconciler-spawned formula step sessions are born
    unprimed — routing is stamped at `bead.created`, nudge-on-route only
    watches `bead.updated`, and nothing enqueues a first prompt (autonomous
    runs stall at every step until manually nudged)."
  - **#3554** (open): "Pool agents claim routed work but then STALL: no
    auto-advance through the work formula for idle self-claimed pool
    sessions (continuation needs a per-step nudge)."
  - **#4700** (open): graph.v2 pool-workflow steps never report "active" —
    can't tell pending/blocked/running apart.
  - **#4704** (open): "five fixes to make the Kubernetes provider run a
    graph.v2 workflow end-to-end" — i.e. e2e execution is provider-specific
    and not proven for k8s.
  - **#4668** (open): formula order dispatch drops caller vars —
    `{{var}}` renders empty in instantiated bead text.

Verdict: the wiring is **real and substantially more complete than Gas
Town's**, but the "last mile" (autonomous nudge-to-first-prompt) has
multiple open, acknowledged holes — you will hit "step created, never
actually prompted" stalls on tmux/pool providers and should expect to
manually nudge sessions, especially on non-default runtime providers.

## 3. formula-spec-v2 — step types, loops, retry vs check

Read in full: `docs/reference/specs/formula-spec-v2.md` (authoritative,
dated 2026-06-12, backs claims to specific source files).

- **Step types / keys**: `id`, `title`, `description`(_file), `type`
  (`task`/`bug`/`feature`/`epic`/`chore`, unvalidated), `priority` (0–4),
  `tags`, `metadata`, `depends_on`/`needs`, `condition`, `children`,
  `assignee`, `expand`/`expand_vars`, `loop`, `waits_for`, `gate`, and the
  **graph-only** (require explicit `[requires] formula_compiler
  >=2.0.0`) constructs: `check`, `retry`, `drain`, `on_complete`, `timeout`.
- **Loops** (`[steps.loop]`): exactly one of `count` (compile-time N
  chained iterations), `range` (`"start..end"`, compile-time, exposes
  `{var}`), or `until` (`until = "<cond>"` + `max = N`). **`until` only
  ever runs one iteration** — the re-execution label is written but nothing
  reads it (confirmed §4, see below).
- **`check` vs `retry`**: `check` = run/verify loop — after each attempt an
  external **script** (`check.mode="exec"`, `check.path`) judges pass/fail;
  exhaustion closes the step failed. `retry` = orchestrator-classified
  transient-failure re-run (no script); `on_exhausted` = `hard_fail` (default)
  or `soft_fail`. Both compile to a control bead (`ralph`/`retry` kind) plus
  `<step>.iteration.N` / `<step>.attempt.N` work beads and a `<step>.spec`
  sidecar.
- **Real example** (from spec, minimal valid v2 formula):
  ```toml
  formula = "pancakes"
  [requires]
  formula_compiler = ">=2.0.0"
  [[steps]]
  id = "dry"
  title = "Mix dry ingredients"
  [[steps]]
  id = "wet"
  title = "Mix wet ingredients"
  [[steps]]
  id = "combine"
  title = "Combine wet and dry"
  needs = ["dry", "wet"]
  ```
  Compiles to 6 beads (5 steps + auto-appended `workflow-finalize` control
  step); `gc formula cook pancakes` materializes 7 (+root).

## 4. The human gate — confirmed inert, and how far from real

Spec §4 "Accepted But Inert" is explicit and matches the tip-off exactly:

> `[steps.gate]` synthesizes a real gate bead that blocks its step until the
> gate bead is closed (manually or by an external watcher), but the `type`
> values `gh:run`, `gh:pr`, `timer`, `human`, and `mail` are **doc-comment
> vocabulary** in `internal/formula/types.go` — the parser never validates
> them and **no bundled watcher acts on them**. Zero bundled formulas use
> `gate`.

Distance to working: **schema/plumbing is there, watcher is vapor.** The
gate bead itself is a real, closeable bead (any external process or human
running `gc bead close <gate-id>` unblocks the step today — that part
works). What's missing is purely a **watcher/poller component** that:
1. reads `gate.type` off the gate bead,
2. for `human`: does essentially nothing extra (a human closing it manually
   already works — this is arguably the *one* type that's already
   functional by manual action, just with no notification/UI around it),
3. for `gh:run`/`gh:pr`/`timer`/`mail`: poll GitHub Actions/PR status, a
   clock, or a mailbox and call the same close-bead call.
Effort estimate: a `human` gate with Slack/CLI notification is a small,
self-contained watcher (poll open gate beads with `type=human`, notify,
accept a close command) — a few hundred lines, no dispatcher changes
needed since the bead-close mechanism already unblocks steps. `gh:run` /
`timer` are similarly bounded (poll a webhook/cron). Nothing structural
blocks it; it's simply unbuilt, and `waits_for` mode distinctions
(`all-children`/`any-children`) are separately inert too (§4, "no current
dispatcher logic interprets" them).

## 5. Issues scan (skimmed ~40 of 839 open)

- **Volume and style**: nearly every issue is long, precise, root-caused,
  and machine-written in tone (consistent with a project that dogfoods
  itself — agents filing bugs against their own orchestrator). Virtually
  all open issues carry only `status/needs-triage` — there's no visible
  priority/severity triage layer, just a firehose.
- **What breaks most**: dispatch/routing edge cases (stranded assignees,
  unprimed sessions, stalled auto-advance — see Q2), mail/session-liveness
  mismatches (#5005–#5007), doctor/health-check self-inflicted issues
  (#5064: `gc doctor` amplifies an outage it's supposed to diagnose),
  and cross-provider parity gaps (k8s provider incomplete, #4704).
- **"Too opinionated" / "can't customize" complaints**: none found —
  searches for "opinionated", "can't customize", "hardcoded" turned up
  nothing on-topic, consistent with the role/formula system genuinely
  being data-driven rather than a superficial rebrand.
- **Maintainer responsiveness**: very fast close times on the sample pulled
  (hours, same-day), but this looks like it reflects an agent-fleet
  workflow closing its own filed bugs rather than a human maintainer
  triaging a community backlog — 839 open issues against 1082 stars is a
  high ratio for a project this young.
- **Is it repeating Gas Town's mistakes?** Partially. The core "does a
  custom formula step reach an agent" question is *better* than Gas Town —
  there's real dispatcher code, not just parse/print. But the *pattern* of
  "spec says X is wired, an open issue says the last hop silently doesn't
  fire" repeats (nudge-on-route, human gates, k8s e2e). The project is
  transparent about it (the spec's own §4 "Accepted But Inert" section is
  unusually honest), which is a good sign for trust, not a good sign for
  "ready today."

## Bottom line

**Borrow, don't adopt/fork.** For a solo personal cross-repo tool: the
role model is genuinely open (safe to build on), and formula v2's
check/retry/drain machinery is real, well-specified, and worth studying or
even vendoring in spirit. But (a) the project runs hot — 839 open issues,
same-day churn, docs that admit core features (human gates, until-loops,
waits_for modes) are inert — meaning you'd be tracking a fast-moving
target for personal-scale use; and (b) the exact failure mode you were
avoiding in Gas Town (steps that get created but never actually prompt an
agent without a manual nudge) still exists here, just at the "last mile"
instead of "entirely inert." If your goal is a stable personal tool today,
don't take a dependency on gascity directly — read `formula-spec-v2`'s
check/retry/scope model as a design reference for your own much smaller
implementation, and skip gate types entirely (build only what you need,
since even Gas City hasn't built them).
