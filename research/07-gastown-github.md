# 07 — Gas Town: GitHub investigation

**Question asked:** *"It seems to be very structured already and predefined."* Is that true,
and can it be bent to a personal work+personal-projects workflow?

**Short answer:** The instinct is **correct, and it points at the wrong repo.**

Gas Town's *designed* extension surface is better than it looks — user-authored TOML
formulas are meant to be first-class, role definitions are layered TOML, there is a real
overlay system. But its *ontology* is hardcoded in Go (seven roles, one directory tree, one
merge model, one ledger), the customization paths that would let you escape that are
**half-wired and openly broken**, and non-code work is structurally rejected.

**And it doesn't matter, because Gas Town has been declared finished.** The maintainers
declared **maintenance mode in March–May 2026** and bulk-redirected feature work to a
successor. `main` has been frozen since 2026-07-23, the last release was 2026-06-06,
Steve Yegge's last commit was 2026-06-06, and 57% of the open backlog is untriaged. The
successor is **Gas City** (`gastownhall/gascity`, MIT, 1,082★, actively developed), whose
entire pitch is the thing this user is asking for: *"the orchestrator hardcodes **zero
roles** — every role you knew is now configuration."* It ships a native **herdr** session
backend, TOML packs, and a normative formula spec. **That** is the repo to read.

**Verdict: don't fork Gas Town, don't run Gas Town. Read it for prior art — the overlay
model and the failure catalogue are genuinely valuable — then evaluate Gas City seriously.
It is closer to the target design than anything in reports 01–06, including the herdr
substrate choice.**

---

## 1. Identification

| | |
|---|---|
| Repo | `github.com/gastownhall/gastown` (`steveyegge/gastown` 301-redirects here — a transfer, not a fork) |
| License | **MIT**, © 2025 Steve Yegge — confirmed in `LICENSE` |
| Language | Go 1.26 |
| Stars | 17,482 · forks 1,602 · watchers 96 |
| Created | 2025-12-16 |
| Last commit on `main` | **2026-07-23** |
| Last release | **v1.2.1, 2026-06-06** |
| Size | 248,289 LOC source + 225,304 LOC tests across `internal/` + `cmd/`; 253 CLI command files; 248 `go.mod` requires |
| Issues | 290 open / 901 closed |
| PRs | 47 open / 1,632 merged / 1,672 closed-unmerged |
| Discussions | enabled, 85 threads |

Note the module path was never renamed: `go.mod` still declares
`module github.com/steveyegge/gastown`. The org move is half-finished.

**The `gastownhall` org, for scale context (all MIT):**

| Repo | Stars | Last push | Status |
|---|---|---|---|
| **beads** | **26,090** | 2026-08-07 | the ledger dependency — *more popular than the orchestrator* |
| **gastown** | 17,482 | `main` frozen 2026-07-23 | maintenance mode |
| **gascity** | 1,082 | 2026-08-07 | active successor, v1.4.0 |
| gascity-packs | 71 | 2026-08-04 | shareable config packs |

### The status that overrides everything else: declared maintenance mode

Gas Town stopped accepting this class of work **five months ago**. **39 issues carry a
canned maintenance-mode redirect**, bulk-applied by collaborator `Bella-Giraffety` in a
single sweep on 2026-05-01, after earlier sweeps by `steveyegge` on 2026-03-29/31 and
2026-04-12. Verbatim (#1163):

> "This sounds interesting, but **Gastown is in maintenance mode and staying focused on
> infrastructure and reliability fixes only.** If you want to pursue multi-town feature work
> like this, please check out **Gas City** instead: https://github.com/gastownhall/gascity"

Yegge's own version (PR #3372, 2026-04-12):

> "…maintaining a third opinionated commit-flow skill in-tree creates rot risk when our
> conventions evolve. … **for major new skill/feature additions, please direct those at Gas
> City going forward — Gas Town is in maintenance mode.**"

An earlier sweep (~25 more issues, 2026-03-29/31): *"Closing ahead of v1.0.0 — **Gas Town is
transitioning to Gas City.** If still relevant, please re-file against the new project."*

> ⚠️ **Do not read "closed" as "shipped" in this repo.** Every one of these bulk-closed
> feature requests is marked `stateReason: COMPLETED` on GitHub with nothing implemented.
> Example: **#1382** "Support headless/sandboxed polecat agents (no tmux requirement)" →
> CLOSED/COMPLETED 2026-05-01, sole comment being the redirect. Same for #3406
> (configurable pr_requirements), #2325, #945, #1791, #1792/#1793, #3601 (PR-based merge
> mode), #1163 (multiple towns), #2229 (sandboxes), #3538 (Windows), #1344 (Docker), and
> ~30 others.

Yegge also said explicitly where the customization abstractions went (PR #3841, 2026-05-06,
declining an opencode adapter):

> "**What Gas City does**: `config.ProviderSpec`: a declarative TOML schema describing any
> agent — Command, Args, PromptMode… users override or add new providers via
> `[providers.xxx]` in `city.toml`. **New agents land as a TOML stanza, not new Go files.**"

And (PR #2277, 2026-03-06), declining a capacity scheduler:

> "The existing direct-dispatch path … is **intentional and sufficient for the current
> architecture. When Gas City ships, it'll provide extension points for custom orchestration
> rules** — so if you need capacity-gated dispatch for your setup, you'll be able to build
> that as an orchestration policy without modifying the core dispatch path."

**Evaluating Gas Town for customization in August 2026 is evaluating the wrong repo, by the
maintainer's own instruction.**

---

## 2. Core abstractions, and how load-bearing the metaphor is

The Mad Max theme is **not cosmetic**. It is the type system.

`internal/constants/constants.go:248-269` defines the role set as Go constants:

```go
RoleMayor = "mayor"      // AI coordinator, town-level
RoleWitness = "witness"  // per-rig lifecycle monitor
RoleRefinery = "refinery"// per-rig merge queue processor
RolePolecat = "polecat"  // ephemeral worker
RoleCrew = "crew"        // your workspace
RoleDeacon = "deacon"    // cross-rig supervisor
RoleBoot = "boot"        // watchdog's watchdog
```

Each has an embedded prompt template (`internal/templates/roles/{mayor,crew,deacon,dog,
polecat,refinery,witness,boot}.md.tmpl`), an emoji constant, a tmux session naming
convention, a directory in the town tree, and a bead identity in the ledger
(`hq-mayor`, `<prefix>-<rig>-witness`, …). **There is no registration point for an
eighth role.** Adding "reviewer" or "planner" means a Go patch across constants,
templates, session management, the bead-ID scheme, and the health patrol.

The other load-bearing nouns:

- **Town** — `~/gt/`, the single workspace root.
- **Rig** — a project. Critically, `~/gt/<rig>/` is **not** your repo. It is a container
  holding `mayor/rig/` (the canonical clone), `crew/<name>/` (full clones), `polecats/
  <name>/` (worktrees), `refinery/rig/` (worktree), `witness/`, plus config. Your project
  gets cloned *into* the town, 2–4 copies deep.
- **Bead** — every unit of work, stored in **Dolt**, a MySQL-protocol SQL server. The
  architecture doc is explicit: *"There is no embedded Dolt fallback — if the server is
  down, `bd` fails fast."*
- **Hook** — a pinned bead that is an agent's work queue. Governed by **GUPP**: *"If there
  is work on your Hook, YOU MUST RUN IT."*
- **Convoy / Molecule / Wisp / Formula / Protomolecule** — the workflow layer.
- **Refinery** — a Bors-style bisecting merge queue. Polecats never push to main.

Design principles are stated as doctrine with acronyms: **MEOW**, **GUPP**, **NDI**,
**ZFC** ("Zero Framework Cognition: Agent decides. Go transports."), **Propulsion
Principle** ("Gas Town is a steam engine. Agents are pistons.").

`docs/why-these-features.md` names the actual target user, and it is not this one:

> "You deploy 50 agents across 10 projects. One of them introduces a critical bug. Which
> one? … **Compliance:** Audit trails for SOX, GDPR, enterprise policy"

---

## 3. Customization — what actually works

This is where the "predefined" impression is **wrong**, and it is worth being precise
because the good parts are borrowable.

### 3a. User-authored formulas are first-class by design ⚠️ — and broken in practice

Formulas are declarative TOML **data**, not code. 39 ship embedded in the binary
(`internal/formula/formulas/`), but resolution is three-tier and implemented —
`internal/formula/embed.go:55`:

```go
// Tier 1 (rig):   townRoot/rigName/.beads/formulas/<name>.formula.toml
// Tier 2 (town):  townRoot/.beads/formulas/<name>.formula.toml
// Tier 3 (embedded): compiled into the binary
func ResolveFormulaContent(name, townRoot, rigName string) ([]byte, error)
```

`gt formula create <name> --type=task|workflow|patrol` scaffolds one for you
(`internal/cmd/formula.go:1152`). Four formula types exist: `workflow` (DAG with `needs`),
`convoy` (parallel legs + synthesis), `expansion` (templated step generation), `aspect`
(multi-aspect parallel analysis). Formulas compose via `extends` and `[compose.expand]`.

`ProvisionFormulas()` explicitly *"skip[s] if formula already exists (don't overwrite user
customizations)"*, and `CheckFormulaHealth` tracks each formula as
`ok / outdated / modified / missing / new / untracked` by sha256 against `.installed.json`.
Editing a shipped formula is a supported first-class act. The design doc's stated goals
include *"Local customization — Override system defaults without forking"*.

**And a third party did it:** `Xexr/gt-toolkit` (55★) is **11 custom formulas** implementing
a 9-stage spec→plan→beads→delivery pipeline with multi-LLM review legs (Claude + Codex +
Gemini in parallel, then synthesis), built entirely in the expansion/workflow pattern with
zero Go changes.

**But the execution path never reads them.** `docs/design/formula-resolution.md` is headed
*"Status: Partially implemented"*, and **#3322 (OPEN since March)** names the consequence:

> "`gt prime` `showFormulaStepsFull` only reads embedded formulas — custom formulas
> invisible to polecats. … **All custom formulas (user-created workflows) fail to render
> steps at prime time.** The formula system works for `gt sling` (cook/pour) but breaks at
> execution time."

A second user in that thread:

> "Hit this hard today. **Spent ~half a day authoring four custom formulas** … and slinging
> them, **before realising none of them were reaching the polecats.** Three PRs landed
> without any GitHub PR until we manually backfilled. … In the meantime **our workaround is
> to move the redseed-specific guidance into the rig's CLAUDE.md and use stock
> `mol-polecat-work-monorepo`.**"

That is the decisive data point for this user: a serious customizer authored his own
workflows and the pragmatic outcome was *give up, use the built-in one, put your differences
in a prompt file.*

Supporting rot in the same area:
- **#4039 OPEN** — 11 shipped formulas use bare `{{key}}` instead of `{{.key}}`, which
  *"does not panic, it just silently renders to nothing"*; two document `gt formula run`
  flags that *"have never existed"*.
- **#4585 / #4586 OPEN** — the gt↔bd variable seam: gt injects empty-string defaults for the
  five rig commands, which `bd mol bond` rejects as missing — *"On a rig that configures none
  of the five, **every sling dies at formula instantiation**."* And
  `ensureFormulaRequiredVars` hardcodes `{"base_branch", "main"}` *"without consulting rig
  config, unlike every comparable call site."*
- **#1753 OPEN** — the shipped `code-review.formula.toml` is wired to nothing. Yegge:
  *"Your analysis is correct. … **Answer: This is intentionally manual-only for now.**"*

### 3b. Two real override layers, both implemented ✅

`docs/design/directives-and-overlays.md` — subtitle *"Operator-customizable agent behavior
without modifying the Go binary"* — opens by naming the rigidity problem outright:

> "The MEOW stack embeds formulas and role templates in the binary — intentionally
> centralized for consistency, **but leaving no override path. Operators cannot customize
> agent behavior at the rig or town level.**"

The fix is two layers, both shipped (`internal/config/directives.go`,
`internal/formula/overlay.go`, CLI in `internal/cmd/directive*.go` and
`formula_overlay*.go`, validated by a `gt doctor` check):

**Role directives** — markdown injected at prime time, town + rig concatenating:

```
~/gt/directives/<role>.md          # all rigs
~/gt/<rig>/directives/<role>.md    # wins (appended last)
```

**Formula overlays** — CSS-like per-step patches:

```toml
# ~/gt/<rig>/formula-overlays/mol-polecat-work.toml
[[step-overrides]]
step_id = "submit-review"
mode = "replace"          # replace | append | skip
description = """
Report findings in conversation. Do NOT post via gh pr review."""
```

`skip` reroutes the DAG (dependents inherit the skipped step's `needs`). Stale `step_id`s
are caught by `gt doctor` and removed by `gt doctor --fix`. There is a
`docs/contrib-harnesses/` directory of copy-and-adapt examples — currently one,
`polecat-pr-flow`, which replaces the entire Refinery merge model with a GitHub PR flow.

### 3b-bis. Role *definitions* are layered TOML ✅ — but the role set is closed and one key field is inert

Worth flagging because it is the closest Gas Town gets to Gas City's model.
`internal/config/roles.go` loads `roles/<role>.toml` from an embedded FS, then merges
`<town>/roles/<role>.toml`, then `<rig>/roles/<role>.toml`. The schema is a real agent spec:

```toml
# internal/config/roles/polecat.toml
role = "polecat"
scope = "rig"
nudge = "Check your hook for work assignments."
prompt_template = "polecat.md.tmpl"

[session]
pattern = "{prefix}-{name}"
work_dir = "{town}/{rig}/polecats/{name}"
needs_pre_sync = false
start_command = "exec claude --dangerously-skip-permissions"

[env]
GT_ROLE = "{rig}/polecats/{name}"

[health]
ping_timeout = "30s"
consecutive_failures = 3
kill_cooldown = "5m"
stuck_threshold = "2h"
```

Compare Gas City's `agent.toml` (§8) — nearly the same shape. Gas Town had 80% of "roles as
config" already; what it lacked was an open name set:

```go
func AllRoles() []string {
    return []string{"mayor", "deacon", "dog", "witness", "refinery", "polecat", "crew"}
}
// LoadRoleDefinition: if !isValidRoleName(roleName) {
//   return nil, fmt.Errorf("unknown role %q - valid roles: %v", roleName, AllRoles()) }
```

**And `prompt_template` is a dead field.** It is parsed, merged by
`mergeRoleDefinition` (roles.go:270), and printed by `gt role show` (`cmd/role.go:762`) —
but nothing resolves it. `internal/templates/templates.go:130` parses
`//go:embed roles/*.md.tmpl` only, and `RenderRole` hardcodes `role + ".md.tmpl"`. **You
cannot point a role at your own prompt template.** Directives (§3b) append to the built-in;
they never replace it.

Requests to add a role were closed unimplemented:
- **#1791** "Lightweight headless role for non-repo tasks (no git worktree)" — noted that
  *"Every current Gas Town role with an agent session creates a git checkout"* and that
  *"convoy formulas dispatch all legs exclusively to polecats (`executeConvoyFormula`
  **hardcodes** `gt sling <bead> <rig>`)"*. → maintenance-mode redirect.
- **#2818** "Crew & Polecat Postings — behavioral specialization system", a 3-tier design
  born from rejected PR #2702 (*"rejected because it hardcoded a 'dispatcher' check on the
  crew member's name"*). Never landed.

### 3c. Plugins ✅ (design doc says "not implemented" — it lies; it is)

`docs/design/plugin-system.md` is marked *"Design proposal — not yet implemented"* and is
out of date. `internal/plugin/{scanner,recording,sync}.go` are real, and `plugins/`
contains 13 working plugins. Format is markdown + TOML frontmatter, scanned from
`~/gt/plugins/` (town) and `<rig>/plugins/` (rig), gated and dispatched to Dogs:

```toml
+++
name = "git-hygiene"
version = 1
[gate]
type = "cooldown"     # cooldown | cron | condition | event | manual
duration = "12h"
[execution]
timeout = "10m"
notify_on_failure = true
+++
# markdown body = agent-executable instructions
```

### 3d. Custom agents/models ✅ — genuinely good

`settings/config.json` at town level, overridable per rig. Arbitrary named agents mapped to
arbitrary roles:

```json
{ "agents": {
    "opus-46":        {"command":"claude","args":["--model","opus","--dangerously-skip-permissions"]},
    "opus-46-capped": {"command":"cgroup-wrap","args":["claude","--model","opus", "..."]},
    "kimi-k2.5":      {"command":"opencode","args":["-m","kimi-for-coding/kimi-k2.5"],
                       "env":{"OPENCODE_PERMISSION":"{\"*\":\"allow\"}"}}},
  "role_agents": {"mayor":"opus-46","polecat":"opus-46-capped","witness":"opus-46-capped"} }
```

11 built-in presets (`claude`, `gemini`, `codex`, `kiro`, `cursor`, `auggie`, `amp`,
`opencode`, `copilot`, `pi`, `omp`), and `[runtimes.*]` lets you declare a new harness in
JSON — hook provider/dir, tmux process names, ready-delay, session-ID env var, instructions
filename. Per-rig merge gates are configurable commands:

```json
"gates": { "lint": {"cmd":"golangci-lint run ./...","timeout":"2m"},
           "test": {"cmd":"go test ./...","timeout":"5m"},
           "build-check": {"cmd":"go build ./...","phase":"post-squash"} }
```

### 3e. The human gate — the one that matters for report 00 §2 ⚠️

Report 00 asserts: *"Nothing shipping models a step that blocks on a person and resumes
cleanly."* **Gas Town partially contradicts this.** `internal/formula/types.go:128`:

```go
Interactive bool `toml:"interactive"` // requires user dialog; runs in the current
                                      // session instead of being dispatched to a polecat
```

`mol-idea-to-plan.formula.toml` uses it, and says so in prose:

```toml
[[steps]]
id = "human-clarify"
title = "Gather human clarifications on PRD"
needs = ["prd-review"]
target = "mayor"
interactive = true
description = """
...
This is a human gate. The molecule pauses here until you have answers.
"""
```

It is enforced, not decorative — `internal/cmd/formula.go:857` hooks the step bead to the
current session rather than slinging it, and the DAG halts because dependents have unmet
`needs`. Durability comes free: the gate is a database row, so it survives a crash.

**But the implementation is crude.** The condition is
`if step.Interactive || hasInteractive` — if *any* step in the formula is interactive, *all*
ready steps get hooked to the current session instead of dispatched. That is a bug-shaped
shortcut, not a design. And resumption is `bd close <id>` by hand; there is no typed
decision payload, no reconciliation of what the human decided back into the graph.

**Conclusion: the human-gate differentiator survives, but narrowed.** "Nobody ships a
resumable human gate" is false. "Nobody ships a human gate that separates decision from
data and reconciles it" remains true.

---

## 4. Customization — what does not work

| Want | Possible? |
|---|---|
| Edit a built-in formula's steps | ✅ overlay: `replace` / `append` / `skip`, validated by `gt doctor` |
| Change what a role is told | ✅ role directives (markdown, town+rig, concatenating) |
| Retune a role's session/health/env | ✅ layered `roles/<role>.toml` |
| New model / harness / per-role model | ✅ `agents` + `role_agents` + `[runtimes.*]` |
| Scheduled / conditional automation | ✅ plugins with 5 gate types |
| **A new workflow / formula** | ⚠️ authoring works, `gt sling` cooks it, **the polecat never sees the steps** (#3322, open since March) |
| **A new step *type*** | ❌ every step is prose in `description`; there are no typed steps |
| **A new agent role** | ❌ closed Go enum (`AllRoles()`), rejected at load; #1791, #2818 closed |
| **Replace a role's base prompt** | ❌ `prompt_template` is parsed and displayed but never resolved; templates are `//go:embed` only |
| **Drop the ledger** | ❌ Dolt SQL server mandatory, no embedded fallback; beads is *operational state*, not issue tracking (#764) |
| **Drop tmux** | ❌ #3538: *"the daemon architecture assumes tmux sessions exist"*; #1382 (headless) closed unimplemented |
| **Non-code work** | ❌ polecats auto-close beads with no git diff (#2496, #4505, #4583) |
| **Point at your existing checkout** | ⚠️ `gt rig add --adopt` exists; default clones into `~/gt/<rig>/mayor/rig/` |
| **Non-GitHub hosting** | ⚠️ #3599 (Bitbucket) and #743 (Forgejo/Gitea) closed/stalled; GitLab is *"supported only at the git transport level… no API integration"* |
| **Branch protection / PR-required repos** | ⚠️ #3601 and #2630: *"Without this, the Refinery is running but doing nothing"* |
| **Two towns (work / personal firewall)** | ⚠️ #1163 closed → Gas City; #3191, #757, #4637 document active cross-town damage |

### The deal-breaker for "personal projects": non-code work is rejected

**#2496 CLOSED** — "Polecats auto-close beads on non-code tasks (no git diff = done)":

> "Polecats auto-close beads when they detect no git diff, before the task's `--message`
> instructions are even executed. **This makes polecats unusable for non-code tasks** (email
> drafting, research, API calls, etc.). … 3 out of 3 beads slung to polecats were auto-closed
> instantly … **Current workaround: Mayor uses subagents instead of polecats.**"

Confirmed by a second user (*"Trying gastown for first time. Also seeing this."*) and still
recurring as **#4505** and **#4583**, both open. If "personal projects" means anything other
than code that produces a diff, the worker abstraction rejects it outright.

### The structural impositions

1. **Directory shape is the architecture.** `docs/design/architecture.md` documents identity
   as *path-derived*. Rig names reject hyphens and dots (`my_project`, not `my-project`).
   Every project ends up with a canonical clone + crew clone + N worktrees.
2. **The merge model is opinionated to the point of hazard.** Polecats push branches; the
   Refinery merges to main. `CONTRIBUTING.md` documents the failure mode in bold:
   > "**Current limitation — the refinery is not yet fork-aware.** … even a correctly-
   > configured fork rig will have its refinery attempt to **merge polecat branches into
   > the fork's `main`**, diverging it from upstream."

   The stated workaround is to park the rig and not start the refinery — i.e. turn off the
   headline feature.
3. **`gt enable` is global.** It installs shell hooks that set `GT_TOWN_ROOT`/`GT_RIG` and a
   Claude Code SessionStart hook that runs `gt prime` — *for every Claude session on the
   machine*. Escape hatch is `GASTOWN_DISABLED=1`. v1.2.1's changelog exists because this
   misbehaved: the shell hook *"re-prompted before **every** command"* and could
   *"loop indefinitely across restored terminal sessions."*
4. **Work + personal on one machine is where it actually falls over.** This is the user's
   literal requirement, so it deserves the detail.

   *One town, two rigs* is the supported model — but rig isolation leaks:
   - **#4225 / #4514 OPEN** — *"Event channels are town-global, not rig-scoped… every rig's
     refinery polls the same `refinery` channel… **Destructive cross-rig races**: with
     `--cleanup`, an idle rig's refinery can consume-and-delete another rig's real
     `MQ_SUBMIT` event before the owning rig sees it."*
   - **#3068 CLOSED** — a user with **77 rigs** reported bead prefixes derived from the first
     2 chars of the rig name producing **8 collisions**, and *"When two rigs share a prefix,
     `routes.jsonl` **silently routes to whichever is listed last** — potentially sending
     work to the wrong rig. `gt doctor` detects these but `--fix` can't resolve them."* His
     direct question — *"What is the intended scale for a single Gas Town?"* — got no
     authoritative answer before closure. (See also #3341.)
   - **#4094 OPEN** — *"background polecat operations checkout in **town root `.git`**,
     destroying `mayor/rigs.json` and uncommitted files."* Reporter: *"We hit this **three
     times in one session** today on gt 1.1.0 (Homebrew)."*
   - **#4604 OPEN** — `gt dolt cleanup` *"treats any database not referenced by rig metadata
     as an orphan — **deletes rig databases** under a shared-DB layout."*
   - **#4602 OPEN** — crew spawn *"**rewrites the enclosing workspace's git remote**."*

   *Two towns* (a real work/personal firewall) is worse, and was explicitly deferred:
   - **#1163 CLOSED** "Support multiple towns per machine without containers" — triaged p2
     (*"this blocks a real multi-town use case"*), partially fixed by per-town tmux sockets
     (PR #2289), **then reverted** (#3042: *"7ea8586a reverts per-town tmux socket isolation"*),
     then closed with the Gas City redirect.
   - **#3191 CLOSED** — *"Town A's Deacon… runs `ps aux | grep claude` and sees Claude
     processes from **both** towns… concludes Town B's agents are orphans and sends SIGTERM…
     Mayor process exits with code 143… **Crash loop**."* Root cause partly *"AI agent
     autonomy"* — the patrol formula doesn't mandate the built-in cleanup command, so the LLM
     improvises `ps | grep | kill`.
   - **#923 CLOSED** — orphan cleanup also kills Claude processes in **non-Gas-Town** tmux
     sessions.
   - **#757 CLOSED** — five shipped formulas contain literal `~/gt/...` paths; on a
     `~/gt-private` install this causes *"**cross-town contamination** — state written to
     wrong town's directory, **corrupting both installations**."*
   - **#304 OPEN** — *"Atm, the town location is **assumed always to be `~/gt`**."*
   - **#3861 CLOSED / #3855, #4494 OPEN** — hardcoded `gastown` rig fallback and hardcoded
     `gt` bead prefix break non-default installs; maintainer confirmed *"a real bug from the
     current hardcoded `gastown` fallback."*

   Yegge himself, Discussion #282: *"**I know vertical scaling is tough here, adding lots of
   rigs won't scale very well. Open to ideas.**"* and *"Having multiple gas towns on one box
   seems undesirable but maybe that's a way forward."*

5. **Undocumented layout constraints bite immediately.** **#3516 CLOSED** — *"`gt rig add
   cc-mem` **fails silently** while `gt rig add cc_mem` works. **Hyphens in rig names are not
   allowed**, but this constraint appears nowhere in README.md or INSTALLING.md."*
   **#932 CLOSED** asked to hide the scaffolding: *"If I `git clone` this project on a machine
   without gastown installed, I should see a coherent project — not a maze of agent workspaces
   and config files."* Not done. **#254 OPEN** on monorepos: *"In some ways gastown is
   incompatible afaict."*

6. **The maintainer's stated philosophy on config requests.** Triage on #2966:
   > "start with a single Mode field on RigSettings that applies to all roles. The per-role
   > RoleModes map adds complexity for a use case that may not materialize — **if someone
   > needs different modes per role, that is likely a signal that they need different rigs
   > rather than per-role mode config.**"

   And PR #1333 (Yegge), the cleanest statement of opinionatedness:
   > "Closing this PR — **the push-to-main policy for crew and mayor is intentional
   > architecture, not a safety gap. These are trusted roles in a trusted multi-agent
   > environment, and the direct-push workflow is by design.**"

   In fairness, the project *did* ship a lot of configurability before the freeze — per-rig
   `settings/config.json`, `role_agents`, `--push-url`/`--upstream-url`, `gt rig add --adopt`,
   `gt config agent set`, and `GASTOWN_DISABLE_OFFER_ADD=1` shipped within days of the
   request (#1227, fixed by Yegge personally). **The freeze is what stopped the trend, not a
   philosophical refusal of config.**

### Multi-backend: Claude is first-class, everything else is degraded

`docs/agent-provider-integration.md` defines four integration tiers (0: zero, 1: preset
registration, 2: hooks, 3: deep) and publishes an honest capability matrix:

| Agent | Hooks | Resume | Non-interactive | Fork | Prompt mode |
|---|---|---|---|---|---|
| **Claude** | Yes (settings.json) | `--resume` flag | Native | **Yes** | arg |
| Gemini | Yes | `--resume` flag | `-p` | No | arg |
| Cursor | Yes (`.cursor/hooks.json`) | `--resume` flag | `-p`/`--print` | No | arg |
| OpenCode | Yes (plugin JS) | **No** | `run` subcmd | No | none |
| **Codex** | **No** | `resume` subcmd | `exec` subcmd | No | **none** |
| Auggie | No | `--resume` flag | No | No | arg |
| AMP | No | `threads continue` | No | No | arg |

**Claude is the only backend with session forking**, and one of only four with hooks. In
`internal/config/agents.go` the split is one grep: `HasTurnBoundaryDrain: true` → claude
only; `SupportsForkSession: true` → claude only (so `gt seance` is structurally
Claude-only); `InstructionsFile: "CLAUDE.md"` → claude only, everyone else gets `AGENTS.md`;
and two surviving hardcoded fallbacks `return []string{"node", "claude"}`.

Four Claude-only subsystems, all filed 2026-05-02/03, **all still open 3+ months later**:

- **#3833 OPEN p1** — *"GT lists `opencode` as a built-in agent… but the binary contains:
  `opencode adapter not yet implemented`."*
- **#3835 OPEN p2** — *"`gt costs record --session` only parses Claude Code transcript
  format… **every opencode polecat silently reports `$0.00`**"* — and `modelPricing`
  contains only Anthropic models plus a `"default"`, so **a non-Claude model is silently
  billed at Anthropic rates.**
- **#3836 OPEN p2** — *"compaction: session auto-cycle does not work for non-Claude agents…
  **Context accumulates without automatic reset.**"*
- **#3837 OPEN p3** — `HooksConfig`/`SettingsJSON` map 1:1 to Claude's event names;
  `DiscoverTargets()` hardcodes `.claude/settings.json` paths for **every** role.

**The posture is explicit. #1927 was opened 2026-02-23 02:19 and closed at 02:25 — six
minutes.** It tabulated what non-Claude agents lose: *"Non-Claude agents can create PRs and
branches **without guardrails**"* / *"**Nudges and mail are silently lost** — agent never
sees them"* / *"Agent loses Gas Town context after compaction, **runs blind**"* / *"**No cost
tracking**"* — summarised as *"they're effectively **'off-grid' for the entire session**."*
Closing rationale:

> "Closing — the affected hooks… **don't apply to polecats, which are the only agents that
> use non-Claude runtimes via `--agent`**. Polecats are short-lived, non-interactive
> workers."

That is the real design: **non-Claude runtimes are disposable worker processes, not agents
that can run the town.** It contradicts the README's first line and matches README line 50
(*"The Mayor is a Claude Code instance"*).

Historically, non-Claude sessions were **killed outright** — #1025 (*"zombie detection uses
`IsClaudeRunning()` which only checks for Claude-specific process names (`node`)… the daemon
incorrectly identifies live sessions as zombies and **kills them**"*), regressed via #1861,
#1808, #2417. Busy/idle detection still screen-scrapes: **#4240 OPEN** — *"the 'is the agent
generating?' decision relies on **scraping the agent TUI status bar for the literal
substring `esc to interrupt`**… It fails open and silently."*

**Gemini is dead upstream. #4332 OPEN** — *"Google deprecated and shut down the Gemini CLI on
June 18, 2026… users who depend on Gemini-powered agents in gastown currently **have no
reliable path forward**"* — 6 weeks open, **zero comments.** Cursor's mayor role has been
broken since **#506, open 2026-01-14** (needs a PTY).

The abstraction that would fix this is still unwritten: **#4402 OPEN** is titled *"**Design**
first-class runtime agent selection for roles"*, and the original ask **#10 has been open
since 2026-01-02 with no maintainer reply in 7 months**: *"Gas Town currently only supports
Claude Code as the runtime for agents… there's no abstraction layer."* Every non-Claude
feature that shipped came from an outside contributor; contributor PRs for OpenCode parity
(#3841, #4356, #4368) were all rejected or converted back into design issues.

For Codex specifically there is *"no file — nudge only"*: Gas Town cannot inject mail or
prime context on a lifecycle event, so it sends a blind startup nudge after a fixed delay.
There is an experimental `.codex/hooks.json` path, but the doc caps it explicitly:

> "This path **does not attempt broader hook parity** such as tool guards, prompt-submit
> hooks, or pre-compact behavior. The default built-in `codex` preset does not change. It
> remains on the no-hooks fallback path."

Codex also needs a manual `~/.codex/config.toml` edit
(`project_doc_fallback_filenames = ["CLAUDE.md"]`) just to see its role instructions.

The same doc contains the succession statement from inside the repo:

> "**Gas Town is being succeeded by Gas City**, which formalizes the implicit provider
> interface into an explicit contract… making native what was previously heuristic."

### The resource cost

`gt up` starts: a Dolt SQL server, a Go daemon, **and standing LLM sessions** — Deacon +
Mayor at town level, Witness + Refinery *per rig*. Three rigs ≈ 8 always-on agent sessions
running patrol cycles whether or not you are working.

Discussion #1542 (highest-upvoted non-announcement) quantifies it:

> "Gas Town burns through Claude Opus budget fast… **All models: 100% used. Sonnet only:
> 2% used.** This is likely the same for anyone running Gas Town on a Claude Pro/Team plan."

A contributor then ran a 91-test promptfoo eval across the patrol formulas:

| Model | Pass | Cost/test |
|---|---|---|
| Haiku 4.5 | 90% | $0.001 |
| Sonnet 4.5 | 89% | $0.003 |
| Opus 4.6 | 91% | $0.006 |

Haiku matches Opus on patrol work at 1/6 the cost — the framework was spending Opus on
shell-script-grade decisions. Yegge's own v0.13.0 notes: *"Max backoff increased from 5m to
15m for idle patrols, cutting idle-rig cost by ~66%."* Related: #1577, #2710, #4577
(a user built a proxy + heavily hacked fork so people without Pro subscriptions could run
it), #1642.

**The hard numbers, all from issues:**

- **#3675 OPEN** (gt 1.2.1, deacon patrol never calls `/handoff`) — *"Across the 11
  sessions, deacon consumed **~132M cache-read tokens and ~625K output tokens, draining the
  usage window of a $20/month Claude Code subscription in under 3 hours**."*
- **#3660 CLOSED** ("severely eating up usage limits **just on startup**", a Claude *Team*
  subscriber) — *"I confirmed my current session usage was at 0%. Then I did… `gt up` /
  `gt mayor attach` and **Immediately hit over 50% usage**. I asked it why it used up so
  much usage, and I was at **over 90% usage** after asking that question."* … *"I have been
  loving the agent orchestration and memory of gastown, but this is quickly ruining it for
  me. **It's not sustainable.**"* The reporter closed it himself and uninstalled.
- **#4626 CLOSED** — `gt shutdown` ("done for the day") does *not* stop crew; only the
  reversible `gt down` does. *"**704.9k tokens survived a done-for-the-day shutdown,
  silently**"*, and *"On 2026-07-30 — the first day after that shutdown — **total spend was
  $113.35**, of which two agent sessions accounted for **$49.44**, both at 98–99% input cost
  with zero cache reads."*
- **#2614 CLOSED** — a **failed install** drained the quota: *"This morning I went to use
  Claude code separately and **my token usage limit had already been reached, consumed by
  Gas Town without a proper install**."*
- **#3332 CLOSED** — *"`gt prime --hook` outputs **33,575 characters / 979 lines**"* before
  the polecat reads a single project file. **#319 CLOSED** — *"48k+ tokens burned per polecat
  spawn on unnecessary exploration."*
- **You couldn't even measure it. #24 OPEN**, filed by Yegge himself: *"Cost tracking
  infrastructure was implemented (PR#292) but **never actually worked**… `gt costs` returns
  **$0.00 for all 20+ sessions**."* The request to show raw token counts instead (#3375) was
  **declined as out of scope for maintenance mode**.
- **#3649 CLOSED — the one to be genuinely uncomfortable about:** *"Does Gas Town 'steal'
  usage from users' LLM credits & paid services to improve itself?"* —
  `gastown-release.formula.toml` *"causes local Gas Town installation to review open Issues
  on `github.com/steveyegge/gastown`, **burning through usage on subscribed LLMs and
  credits… without the user's explicit direction**"* … *"**Your Claude credits / usage may be
  funding fixes to the maintainer's codebase**, and your GitHub account submitted PRs to his
  repo."* The reporter linked four PRs (#3643/#3644/#3646/#3647) opened from his own
  instance. Closed with the maintenance-mode boilerplate.

**Idle CPU is not free either.** **#4028 CLOSED P0** is the canonical incident: many
short-interval loops all shelling out to `bd` against one shared Dolt server, *"self-feeding"*
because each write re-exports Dolt→`issues.jsonl`, producing *"**200–343% Dolt CPU on a
mostly-parked deployment**"* which *"**survives killing the daemon and all agents**"* —
measured at *"60–76 new connections/sec"* and *"~63 distinct short-lived `bd` subprocess PIDs
spawned per 10s… **no pooling**."* Closed with *"Closing as fixed from the Gas Town side… It
does not claim to fix the beads-side root cause."*

The dashboard is worse, with four reports and three still open. **#4165 OPEN** is the
cleanest proof, on gt **1.2.0** (i.e. *after* the hardening) with **no browser attached**:
`dolt_idle_after_30s dolt_cpu=0.00` → `dashboard_server_after_30s_no_request
**dolt_cpu=70.13**`. *"This makes the built-in dashboard **impractical as an always-on local
service**."* #1760's workaround was blunt: *"**Do not run `gt dashboard`.**"* Also **#3938
OPEN** — *"**32 orphaned `dolt sql-server` processes**… ~32% CPU on an otherwise-idle
system… **~1.9 GB committed to dead processes**"* (cleanup request #3572 *"rejected as out of
scope for Gastown maintenance mode"*), and **#27 CLOSED** — *"**~253 Claude processes
consuming ~24.4 GB RSS**… Requires hard restart."*

**No rate-limit recovery.** **#1066 OPEN since 2026-01-29** — *"For folks on Claude Pro or
Max plans, when we hit our usage limit for a given period, **everything comes to a halt.**"*
**#232 OPEN since 2026-01-06** — idle rigs during throttling *"requir[e] manual intervention,
which defeats 'always-on' operation."* Both still open.

---

## 5. Reliability: the failure mode is confident lying

This deserves its own section because it is the most transferable finding — it is a design
lesson, not just a complaint about someone else's software.

Gas Town's signature bug is **not crashing. It is reporting success while destroying or
losing work.** Clustered across all 1,191 issues: **silent failure / swallowed errors — 225
issues**; **stale / orphaned / ghost state — 337 issues**; **fail-open safety gates — 83
issues**; **race conditions — 117**. Seven open P0s. The oldest (#2682, split-brain
databases) has been open since March.

- **#4472 CLOSED p0** — *"`mq post-merge` records a merge it never verified — and deletes the
  branch… Deleting the head branch auto-closes the unmerged PR. `origin/main` never moved.
  The only surviving copy of the work is the polecat's local worktree. **Every bead record
  says the work landed.**"*
- **#4469 OPEN p0** — a Python repo configured with `test_command = "go test ./..."` exits
  127 on every branch, so it is classified *"pre-existing"* everywhere, and *"**every branch
  merges with a filed bead as a fig leaf**. The gate that exists to catch regressions **can
  never fail a branch**."* It merged three branches this way.
- **#4397 OPEN p0** — *"gt printed `WORK AT RISK` with 14/46/46 unpushed detached-HEAD
  commits, **but still deleted those worktrees**."*
- **#4479 CLOSED p0** — *"`gt done` safety-net auto-commits the WORKSPACE ROOT… **198 files /
  3920 insertions** of unrelated multi-agent WIP… A safety net that can silently commit 198
  unrelated files is a bigger hazard than the data loss it protects against."*
- **#824 CLOSED p0** (a new user, week 3 of the project) — *"I went to push and there was a
  conflict as **my entire codebase was wiped on the remote**."*
- **#885 CLOSED p0** — `gt doctor --fix` overwrote a real `CLAUDE.md`: *"was 158 lines of
  project guidelines, now 6 lines of 'Mayor Context'."*
- **#4633 OPEN** — the general form: *"`gt done` has no guard distinguishing 'hook is empty'
  from 'hook read failed' — **destructive action fires on a false negative**."*

**The diagnostic tooling is itself untrustworthy — 42 issues, 13 open.** **#4614 OPEN**:
*"`gt health` is unsafe to act on: zombie detector name-matches… **It flagged another
workspace's HEALTHY, supervised, RUNNING dolt server for 36+ hours** — while simultaneously
missing 5 genuine STAT=Z defunct processes. The patrol formula's dolt-health step said to
KILL reported zombie PIDs: **following it literally destroys a different town's live
database.**"* And `backups.dolt_stale` *"is never computed… it has never once been true. A
permanently-green backup signal on top of zero configured backups."*

On the **current release**, `gt doctor --fix` is dangerous: **#4593 OPEN** — it *"**renamed
the town's main database directory**… `bd` immediately went down town-wide… **recovery took
~1.5h**"* while printing `🔧 FIXED: 1. identity-collision` with no mention of the rename. The
reporter's conclusion: ***"We now run with a standing 'never use --fix' rule, which defeats
the tool's purpose."*** Also **#4623** (blanked `prefix` in 2 of 14 rigs) and **#4651**, the
newest issue in the repo (2026-08-05, fresh WSL2 install): *"`gt doctor --fix` **repeatedly
reports that it is fixing missing agent beads, but no agent beads are ever created**."*

**Currently broken on the latest release: #4220 OPEN** — *"`gt sling` **fails for every
rig**… Reproducible on a **brand-new rig** cloned fresh from GitHub, so it is not state
corruption."* gt 1.2.1, bd 1.0.4, dolt 2.0.7 — all current. Filed 2026-06-10, still open.

**The lesson for the personal tool:** every one of these is a case of *inferred* state
(no git diff ⇒ done; exit 127 ⇒ pre-existing failure; empty read ⇒ empty hook; name match ⇒
my process) standing in for *reported* state. This is the single strongest independent
argument for report 06's Stop-hook-enforced `wf__report`, and for report 02's
OBSERVE → durable facts → DERIVE. **Never infer completion. Never let a check that cannot
fail count as a passing check.**

---

## 6. Community evidence

### Discussions (85 threads — a backwater vs 1,191 issues)

Engagement ceiling is 6 comments / 15 upvotes. Yegge posted 9 release announcements and
**one** substantive design comment (#282); zero replies in Q&A. A large share of "community"
answers come from a user posting **as an AI agent** (*"Crew worker here (gastown/crew/batty)
— sharing what I see from the inside of a running Gas Town"*). In #266 the OP answered his
own question with a Claude-generated post signed *"— Claude (Opus 4.5), via Gas Town Mayor"*,
then added: *"(Would be grateful if an actual human could confirm that Claude is right 😁)"*.

**#4435 "I really want to use gastown"** (2026-07-08, most recent General thread):
> "The concepts here are extremely powerful but I just cannot seem to get the platform to
> 'just work'. I'm always fighting different pieces of the system. **I even added my own
> additional meta observer to make changes to gastown itself to better fit my needs but I
> finally just gave up and went back to regular agents.**"

Reply: *"Yeah, I haven't been able to even make it sling a bead successfully, it ends up
with wanting to change its own tooling to 'fix it' in different ways. Hopeless."*

**#624 — the exact question this user is asking**, verbatim:
> "running 20-30 agents feels like overkill for my side projects. I don't need chariots. I
> need a motorcycle 🏍️ … Curious if… Gas Town has a 'lite mode' I'm missing?"

Answers:
- *"'Lite mode' imo is basically 'use beads'. Beads plus Ralph plugin if you want to get
  fancy. Given its lifecycle stage until you've kinda blown those up, gastown is going to
  be a lot to bite off."*
- *"I developed a /parallel-work skill that takes ready beads and spins up sub-agents in
  separate git worktrees… This was much more productive than I've experienced so far using
  gastown (**spending all my tokens fixing issues there now**), but the promise of gastown
  is too enticing."*

**#282**, same complaint from a serious user: *"The vertical scaling pain is real. I
immediately tried to add 5+ rigs… and kinda melted down on the deacon/witness/refinery
overhead when it got compounded by bead routing issues and zombie Claude sessions."*

**#874 "Mayor just acting like a regular claude session"** — the core value prop failing;
the Mayor codes instead of delegating. Recurs in #917, #1078, #282.

**#951 / #641 — the merge model is an adoption blocker:**
> "refinery auto-merging to main/master (protected branches) and polecats pushing to
> main/master are hard passes. **No company can really get on board with this.**"

**#464 — nobody runs it on bare metal.** Users report Docker, Lima, OrbStack, WSL, Tart VMs.
The candid answer: *"Gas Town does run in permissive mode… The approval-per-command model
would make multi-agent orchestration impossible."*

**#1109 (13 upvotes), Yegge on the Dolt migration:** *"Basically Gas Town beads/mail routing
has been totally busted, as well as some priming/startup. The upgrade of your Gas Town to
Dolt is a little painful; you have to update a LOT of hooks and stuff, it's not centralized
at all."*

**#636:** *"it told me I had 383 orphaned claude processes."*

### Ledger maintenance is a real chore

`Xexr/gt-toolkit`'s largest directory is `scripts/beads-cleanup/`, whose README opens:
> "**WARNING: These scripts permanently delete data from your Dolt databases.** They purge
> beads (wisps, molecules, ephemeral issues, tombstones), drop branches, squash commit
> history, and force-push to remotes… There is no undo."

Eight scripts: `purge-all-wisps.sh`, `purge-polecat-branches.sh`, `purge-stale-data.sh`,
`dolt-gc.sh`, `dolt-shallow-reset.sh`, `dolt-remote-reset.sh`, `audit-cruft.sh`, wrapper.
The engine's own docs cite ~6,000 wisp rows/day before the root-only-wisp optimisation.

---

## 7. Repo health

### Velocity: a cliff, not a curve

| Month | Commits |
|---|---|
| 2025-12 | 1,985 |
| 2026-01 | 1,199 |
| 2026-02 | **2,245** (peak) |
| 2026-03 | 1,426 |
| 2026-04 | 234 |
| 2026-05 | 381 |
| 2026-06 | 159 |
| 2026-07 | 141 |
| 2026-08 | **0** |

94% off peak. `main`'s last commit is 2026-07-23. Steve Yegge's last commit is
**2026-06-06** (`chore: Bump version to 1.2.1`). Last 90 days on `main`:
`thalia.geraghty@fiserv.com` 358, `Bella-Giraffety` 201, `steve.yegge` 50 (all pre-06-06).
**The founder has left and the bus factor is ~2 people who are not him.**

### Contributors: 727 "authors" is an artifact

`git shortlog` reports 727 author *names* but only 375 emails, because Gas Town writes its
own history under agent identities: `mayor`, `furiosa`, `nux`, `rictus`, `slit`, `dementus`,
`gastown/crew/{max,george,dennis,joe,jack,gus,tom,mel}`, `gastown/refinery`. All
`steve.yegge@gmail.com`.

- `steve.yegge@gmail.com` = **4,831 / 7,770 = 62%**
- Top 3 emails = **73%**
- **4,910 commits carry a `Co-Authored-By` trailer**, ~4,246 naming a Claude model.

### Governance

`.github/workflows/block-internal-prs.yml` auto-closes any same-repo PR:
> "**Internal PRs are not allowed.** Gas Town agents push directly to main. PRs are for
> external contributors only."

So the project's own agents merge to `main` unreviewed; review exists only as a gate on
outsiders. No CODEOWNERS. Org membership private. **50.6% of closed PRs were rejected**
(1,672 unmerged vs 1,632 merged) — consistent with a flood of AI drive-by PRs the maintainer
explicitly invited (#68: *"PRs are welcome, even (especially!) AI-generated PRs"*).

Outside participation is nonetheless real: the last 400 merged PRs span 103 distinct
authors, though `Bella-Giraffety` alone is 40% of them.

### Backlog

290 open issues: **165 `status/needs-triage` (57%)**, 80 `kind/bug`, 42 `kind/enhancement`,
7 `priority/p0`, 31 `priority/p1`, only 17 `status/accepted`. New issues arrive daily
(#4649, #4651 on 2026-08-05) against a frozen `main`, with nobody triaging.

**Triage stopped dead on 2026-07-20** — the newest issue carrying any `kind/*` or
`priority/*` label is #4532. The fix pipeline collapsed months earlier:

| Month filed | issues | still open |
|---|---|---|
| 2026-01 | 345 | 7.0% |
| 2026-03 | 267 | 10.5% |
| 2026-05 | 99 | **61.6%** |
| 2026-06 | 44 | **79.5%** |
| 2026-07 | 102 | **90.2%** |
| 2026-08 | 11 | **100%** |

Issues closed per month: Feb 300 → Mar 197 → **Jun 8 → Jul 15 → Aug 1.**

### The tracker is effectively write-only

| Cohort | non-author reply rate | zero comments | median time to first reply |
|---|---|---|---|
| All time (n=1,191) | 45.5% | 42.1% | 50.6h |
| Last 60 days (n=152) | **11.2%** | **71.1%** | 285h (11.9d) |
| Last 30 days (n=106) | **9.4%** | **73.6%** | 298h (12.4d) |

Only **1 of 106** issues filed in the last 30 days got a reply within 24 hours. Of the 290
open issues, **189 (65%) have zero comments** and **217 (75%) never got a reply from anyone
but their author**; median days since last update is **61.5**.

**Four accounts do 61% of all first responses, and two are agent-operated.**
`DreadPirateRobertz` 407 comments (25.7%), `Bella-Giraffety` 152, `julianknutsen` 143,
**`steveyegge` 108 (6.8%)**. Timing forensics: **62.5% of DreadPirateRobertz's comments were
posted within 60 seconds of that account's previous comment on a *different* issue** (#3087
and #3076 triaged 14 seconds apart) across 177 issues in a 12-day window — versus 0–4%
same-minute rate for human contributors. A representative agent comment (#3622,
Bella-Giraffety): *"I attempted the daemon event-poll regression tests, but **this sandbox
cannot run them because rootless Docker is unavailable for testcontainers**."*

**Merge control is now 100% agent:** in June 2026 `Bella-Giraffety` merged 100% of PRs; in
July it **authored 94% of merged PRs and merged 100% of them**, with no independent human
reviewer. Steve Yegge has not commented on an issue since **2026-05-08**.

### Onboarding

**112 of 1,191 issues (9.4%) are install/setup failures.** The shape improved a lot: **~19 of
the oldest 60 issues (32%)** were first-run failures, versus **4 of the 50 newest open (8%)**.
But 29.5% of install-cohort issues were filed by users who never filed another issue (vs
22.4% baseline) — drive-by-and-leave — and ~45% were never triaged.

The residue is now *"the repair tool damaged my install"* rather than *"install fails"*. And
**`brew install gastown` is still stuck below the current release — #4179, open since
2026-06-04**, 10 comments of escalation: *"Please care about the release process. This
shouldn't happen at a 1.x release stage"* → *"Knock knock. Who's there? The release process.
The release process who? **Exactly.**"* → *"**@steveyegge Did you give up on this project?**
… everything just fails nonstop… **It's just awful.**"*

**Windows is architecturally impossible**, not merely unsupported. **#3538 CLOSED** is the
definitive statement: *"Gas Town cannot run on Windows. This is not a single missing
feature — it is a chain of hard blockers at every level… **tmux is a Unix-only program**…
This is not a 'nice to have' — it is the core session multiplexing layer."* The reporter
spent months on a `psmux` port, then quit: *"I asked on discord [if] the maintainers want to
make Windows support a feature or not. I get response like **just use WSL2**. As you pointed
out and I tried, **it just doesn't work**."* Closed with the maintenance-mode boilerplate.

### Versioning honesty

26 tags, 14 releases, v0.1.0 (2026-01-02) → v1.2.1 (2026-06-06). CHANGELOG.md is 93 KB,
28 sections, well-written prose with cross-refs — but despite claiming SemVer adherence,
**there is not a single "Breaking Changes" section in the entire file.** Breakage is
announced only in Discussion release posts. The Dolt migration broke every install mid-week
with no version gate at all (#1109).

### Code quality: genuinely good

- **568 test files vs 663 source files (0.86)**; 225,753 test LOC vs 248,289 source LOC (0.91).
- 11 CI workflows: `-race -short -timeout=10m`, gotestsum + JUnit annotations, Codecov,
  **all third-party actions SHA-pinned**, top-level `permissions: contents: read`, guard
  jobs rejecting `replace` directives in go.mod.
- codecov patch target 60%, but every component status is `informational: true` — no
  blocking floor.
- Idiomatic Go: doc comments on exported symbols, sentinel errors, constants from a
  single-source package, constructor DI. **It does not read like slop.**
- Structural concerns: `doltserver.go` 4,646 lines, `tmux/tmux.go` 4,454,
  `witness/handlers.go` 3,577 (importing 12 sibling packages), `git/git.go` 3,573.

---

## 8. Gas City — the actual answer

`gastownhall/gascity`, MIT, Go, **1,082★**, created 2026-02-22, **83 commits in the first
week of August 2026**, v1.4.0 released 2026-07-24, 2,746 merged PRs, active Discord, docs
site at docs.gascityhall.com. Lead maintainer `julianknutsen` (Gas Town's #3 contributor).

Its README: *"Gas City is an orchestration-builder SDK for multi-agent systems. It extracts
the reusable infrastructure from Gas Town into a configurable toolkit."*

Its FAQ answers this user's question directly:

> "The platform **hardcodes zero roles** — every role Gas Town wired into code (mayor, crew,
> and the rest) is now configuration expressed as a pack, so the same engine runs Gas Town,
> Ralph, or whatever you configure."

> "**Do I have to write Go, or any code at all?** No. Everything user-facing is
> configuration: TOML files (`city.toml`, `pack.toml`) declare your agents, formulas, and
> orders, and markdown prompt templates define what each role does. **A 'reviewer' or
> 'planner' is a prompt you wrote, not a plugin you compiled.**"

> "**Can I use it with my existing repos?** Yes. Register any project as a rig with
> `gc rig add <path>` — its directory can live anywhere on disk, and each rig gets its own
> bead namespace and agent scope."

Every Gas Town imposition listed in §4 is inverted:

| Gas Town | Gas City |
|---|---|
| 7 hardcoded roles | zero; roles are `agents/<name>/{agent.toml, prompt.template.md}` in a pack |
| repo cloned into `~/gt/<rig>/mayor/rig/` | `gc rig add <path>`, directory anywhere |
| path-derived identity | *"Do not port code or prompts that assume directory path implies who the agent is."* |
| Dolt mandatory | `GC_BEADS=file` skips dolt + bd entirely |
| tmux only | providers: tmux, subprocess, exec, ACP, Kubernetes, **herdr** |
| Deacon/Witness as LLM agents | *"Stall detection, restart-with-backoff, reconcile-to-desired-state are orchestrator concerns, not a role agent."* |
| formulas run in-session, inert after cook | v2 compiles to a graph; the orchestrator executes control beads outside any session |

### Why this matters against reports 00–06 specifically

1. **herdr is a shipped backend.** `docs/reference/herdr-provider.md`: one shared herdr
   session-server per city, one workspace per rig, one tab per agent, verified against
   herdr 0.7.1+, selected via `[session] provider = "herdr"`. Report 01's substrate choice
   is already integrated by someone else. (Caveat: city-wide only — herdr cannot be selected
   per-agent.)

2. **The formula v2 spec is the step machine report 04 designed** — and it is normative,
   with MUST/SHOULD language. Step keys: `id`, `title`, `description`,
   `description_file`, `type`, `priority`, `tags`, `metadata`, `depends_on`/`needs`,
   `condition`, `children`, `assignee`, `expand`, `expand_vars`, `loop`, `waits_for`,
   `gate`, `check`, `retry`, `drain`, `on_complete`, `timeout`. **`retry` (transient) and
   `check` (semantic re-run) are separate constructs** — the exact split report 04 argued
   for. Compilation produces a flat graph of work beads + orchestrator-owned control beads
   (check, retry, fanout, drain, scope-check, workflow-finalize).

3. **Reconciliation is the stated architecture**, not an afterthought: *"a controller/
   supervisor loop that reconciles desired state to running state"*; *"the orchestrator acts
   on sessions… but reads their progress from the bead store and event bus rather than being
   called back directly. The loop closes through shared state, which is why work survives a
   crash on either side."* Gas Town's ZFC doctrine — *"Reality is truth. State is derived"* —
   is the same instinct as AgentOrchestrator's OBSERVE→DERIVE from report 02, arrived at
   independently, and Gas City makes it the engine.

4. **The human gate is still the gap.** `[steps.gate]` synthesizes a real gate bead that
   blocks its step until closed manually or by a watcher, and `gc converge approve <bead>`
   exists. But the spec's §4 "Accepted But Inert" is blunt:
   > "the `type` values `gh:run`, `gh:pr`, `timer`, **`human`**, and `mail` are doc-comment
   > vocabulary … the parser never validates them and **no bundled watcher acts on them.
   > Zero bundled formulas use `gate`.**"

   Also inert: `until`-loop re-execution (compiles a label nothing reads — the loop runs
   exactly once), `waits_for` gate modes, and `vars.<name>.type`. **The human gate as a
   typed, first-class, decision-vs-data-separated construct remains unbuilt.** Report 00 §2
   survives — against Gas City, not against Gas Town.

5. **A warning worth stealing:** the spec admits *"Unknown step keys are silently ignored. A
   typo like `dependson` produces no diagnostic — the dependency simply vanishes."* Report
   04's build-time contract validation is the right call; here is the failure it prevents.

### Gas City caveats

- **493 open issues** vs 687 closed — a bigger backlog than Gas Town's, on a younger repo.
- Still needs tmux even when using another backend ("default *and* fallback").
- Still Dolt-flavoured by default; `GC_BEADS=file` is the escape.
- ICU/CGO build pain is inherited (the README carries a NixOS workaround section).
- v1.4.0 in ~5 months means the config surface is still moving.
- **Same org, same culture.** Expect the same agent-authored, agent-merged governance and
  the same "documented but inert" gaps (its own spec admits four of them). Assume anything
  not covered by a bundled example is unproven — the Gas Town lesson is that a shipped
  design doc is not a shipped feature.
- Gas Town's own succession is only ~14 months old as a project lineage. Betting on Gas City
  is betting that this team's *third* system doesn't arrive in six months.

---

## 9. Verdict

### Is the "too predefined" instinct correct?

**Yes — and the honest version is worse than "predefined."** Gas Town is not rigid because
its authors refused configuration; they shipped a lot of it, and the *design* of the
extension surface (overlays, layered role TOML, three-tier formulas) is better than most
things in reports 01–06. It is rigid because:

1. **The ontology is hardcoded** — 7 roles in a Go enum, one `~/gt` tree, one merge model,
   one mandatory SQL server, one session multiplexer, and identity derived from filesystem
   path. If your mental model is "coordinator + ephemeral workers + watchdog + merge queue,"
   it bends far. Otherwise you fight it, which is exactly what #4435 describes.
2. **The escape hatches are half-wired.** Custom formulas cook but never render to the agent
   (#3322). `prompt_template` is parsed and ignored. `until` loops, `waits_for`, and gate
   types are inert in the successor too. The configurable path is a *draft*.
3. **Non-code work is rejected at the worker level** (#2496) — which removes most of
   "personal projects."
4. **Two towns on one machine actively damages both** (#3191, #757, #923, #4094).
5. **It stopped.** Feature work was redirected to Gas City in March–May 2026; `main` froze
   in July.

The one place the instinct *undershoots*: assuming "predefined" means "no templates of your
own." It has templates of your own. They just don't reach the agent.

### Fork / use / borrow / ignore?

**Do not fork Gas Town.** 248k LOC, frozen `main`, an absent founder, no breaking-change
discipline, and a module path that still points at a personal namespace. You would inherit
a dead enterprise-shaped system to extract a workflow engine that has already been
extracted for you.

**Do not use Gas Town as-is.** It is 8 always-on LLM sessions, a Dolt server, mandatory
tmux, a global shell hook, and a merge queue that will rewrite your `main`, to run one
person's side projects — and the maintainers have told you in 39 issues to go elsewhere.
The community's own answer to "is there a lite mode" was "use beads, not Gas Town." Note
that **`gastownhall/beads` has 26,090 stars — 50% more than Gas Town itself.** The
dependency outgrew the orchestrator.

**Borrow, specifically:**
- **The overlay model.** `replace` / `append` / `skip` on steps of a shipped template, with
  a doctor check that detects stale `step_id`s and `--fix` that removes them. That is the
  cleanest answer found anywhere to "let users patch a template you keep updating," and it
  is directly applicable to the template-snapshot decision in report 00 §4.
- **Directives vs overlays as two distinct layers** — broad role-scoped policy in markdown,
  surgical per-step patches in TOML. Different blast radii, different precedence rules
  (directives concatenate; overlays fully replace). Worth copying wholesale.
- **`interactive = true` as a step field**, and the insight that a durable human gate is
  free once steps are database rows. Also copy the *anti*-pattern: don't let one interactive
  step change dispatch for the whole formula.
- **Configurable gates as named commands with phases** (`phase: "post-squash"`).
- **Per-role model assignment** — and the promptfoo eval showing Haiku matches Opus at 1/6
  cost on supervisory work. Design for cheap supervisors from day one.
- **The layered role definition** (`roles/<role>.toml`, embedded → town → rig, merged) — a
  clean schema of session pattern, work dir, start command, env, nudge, and health
  thresholds. Copy it *with* an open name set, and *actually resolve* `prompt_template`.
- **The failure catalogue.** Every complaint in §4–§6 is a design constraint, stated as a
  negative requirement for the personal tool:
  - no idle token burn (#1542: patrol agents ran Opus; Haiku scored the same)
  - no global shell hook (#1227, v1.2.1 changelog)
  - no forced clone layout, no scaffolding in the project root (#932)
  - no writes to `main`, ever (#951, #641, #2630, #4045)
  - no mandatory database server (#764: *"When operational infrastructure loses state, the
    factory explodes"*)
  - **no "no diff ⇒ done" heuristic** (#2496) — completion must be reported, not inferred.
    This is an independent argument for report 06's Stop-hook-enforced `wf__report`.
  - cross-instance isolation must be a hard boundary, not a naming convention (#3191, #923:
    `ps | grep claude | kill` killed unrelated processes)
  - validate config keys at parse time (#3322 stale resolution, and Gas City's *"Unknown
    step keys are silently ignored"*)

**Actually evaluate: Gas City.** It is the same authors' second attempt with the opinions
removed, it is alive, it is MIT, and it already integrates herdr. Concretely:
1. `brew install gascity && gc init` — the `examples/swarm` city is 30 lines of TOML with
   four roles (mayor, deacon, coder, committer), and the pack comment reads *"Rig agents
   replace polecat/refinery/witness with a simpler combo… No worktree isolation, no
   formulas, no witness."* That is a personal-scale configuration written by the authors.
2. Read `docs/reference/specs/formula-spec-v2.md` before finalising the step schema in
   report 04. It is a superset, it is normative, and its §4 lists exactly which parts they
   failed to make real.
3. Check whether `[steps.gate] type = "human"` + a watcher + `gc converge approve` can be
   made to carry a typed decision payload. **If yes, the gap report 00 identified is a pack
   and a watcher, not a product.** If no, that gap is still the thing worth building — and
   Gas City is a better place to build it than a greenfield controller.

**Ignore:** the Wasteland federation, Mol Mall, the reputation-stamp system, `gt seance`,
the enterprise attribution/compliance framing, and the entire Mad Max vocabulary.

### What Gas Town does better than the plan in reports 00–06

Being fair to it, three things:

1. **Durable work outlives the session, by construction.** Every unit of work is a row, not a
   transcript entry. The plan has this (`runs`/`step_results`/`step_rounds`), but Gas Town
   proves the payoff: a crashed agent's work is still Ready, and a human gate is free.
2. **The overlay/directive split** is a better answer to template customization than
   "snapshot the template into the run" alone. Snapshotting protects in-flight runs;
   overlays let a user permanently amend a template you keep shipping. **You want both.**
3. **Per-role model routing with real cost evidence.** The plan treats model selection as
   incidental; Gas Town's #1542 eval shows it is the difference between a $20/month
   subscription lasting a month and lasting three hours.

### Where the instinct is exactly right

"Very structured and predefined" is the correct read of what Gas Town *asks of you*: it wants
you to reorganise your repos, your git workflow, your shell, and your vocabulary around its
model, and it spends money continuously to maintain that model whether or not you are
working. For one person across work and personal projects, that trade is upside-down. The
tool should hold your workflow's shape, not the reverse — which is precisely the sentence
Gas City opens with.
