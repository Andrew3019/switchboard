# What model does each switchboard role/task use today?

Read-only investigation. All claims are from code/config actually read in this checkout
(`/Users/andrew/.herdr/worktrees/switchboard/model-selection`, `.switchboard` symlinked to
`/Users/andrew/Code/switchboard/.switchboard`), not from README prose.

## 1. What roles exist, and where they're defined

Roles are markdown files with TOML front matter, one per role, under `defaults/roles/`:

- `switchboard/roles.py:1-90` — the `Role` dataclass and loader. A role is "a spawn profile:
  which model tier, and the prompt that tells an agent who it is" (roles.py:1-8). Vocabulary
  is open (no closed set); an unknown role name still works.
- Shipped roles, one file each: `defaults/roles/dispatcher.md`, `lead.md`, `qa.md`,
  `researcher.md`, `reviewer.md`, `worker.md`.
- Layering (`roles.py:16-19`, `switchboard/config.py:381-390`):
  `defaults/roles/<name>.md` → `<repo>/.switchboard/roles.toml` → `<repo>/.switchboard/roles/*.md`,
  merged field-by-field so overriding one field (e.g. tier) leaves the prompt alone.
- In this checkout, `.switchboard/roles.toml` (`/Users/andrew/Code/switchboard/.switchboard/roles.toml`)
  sets nothing — the `[reviewer] model = "strong"` override is commented out. So every role
  here is exactly the shipped default.
- Fallback / default role handling — `switchboard/roles.py:92-121` (`get()`):
  - Unknown role names inherit the **fallback role**'s fields (prompt, tier, delegate) but
    keep their own name. Fallback role name comes from config: `[vocabulary] fallback_role`
    in `defaults/settings.toml:107` = `"worker"`.
  - `sb delegate` with no `--role` uses `[vocabulary] default_role` (`defaults/settings.toml:104`)
    = `"worker"` (`DEFAULT_ROLE = config.setting("vocabulary.default_role")`, `switchboard/broker.py:88`).
  - `sb start`'s top agent always gets `[vocabulary] main_role` (`defaults/settings.toml:96`)
    = `"dispatcher"`.
  - Retired names alias forward: `[vocabulary] role_aliases = { orchestrator = "lead" }`
    (`defaults/settings.toml:113-125`) — `orchestrator` resolves fully to `lead` (name, tier,
    prompt), not to the fallback.

## 2. What model each role actually gets — traced end to end

Roles never name a model, only a **tier** (`cheap`, `default`, `strong`, or any invented
name). Tier → (provider, model, effort) is resolved in `switchboard/models.py`, the only
module besides `defaults/models.toml` where a model name may appear
(`models.py:1-25`, and `defaults/models.toml:1`: "the only file in the tree where a model
name appears").

**Front-matter tiers, read directly from each shipped role file:**

| Role | File | `model =` (tier) | defaults/roles/*.md:line |
|---|---|---|---|
| dispatcher | dispatcher.md | `default` | dispatcher.md:2 |
| lead | lead.md | `default` | lead.md:2 |
| qa | qa.md | `default` | qa.md:2 |
| researcher | researcher.md | `cheap` | researcher.md:2 |
| reviewer | reviewer.md | `default` | reviewer.md:2 |
| worker | worker.md | `default` | worker.md:2 |

A role file that names no tier at all falls back to `[vocabulary] default_tier`
(`defaults/settings.toml:133` = `"default"`) — see `Role.__post_init__`,
`switchboard/roles.py:52-56`. In practice every shipped role names one explicitly, so this
only matters for a hand-defined role that omits `model`.

**Tier → model, from `defaults/models.toml` (the shipped table; nothing overridden in this
repo's `.switchboard/models.toml`, which is present but has every line commented out):**

| Tier | provider | model | effort | defaults/models.toml:line |
|---|---|---|---|---|
| `cheap` | claude | `sonnet` | `medium` | :51-53 |
| `default` | claude | *(unset)* | *(unset)* | :58-59 |
| `standard` (alias of `default`) | claude | *(unset)* | *(unset)* | :61-63 |
| `strong` | claude | `opus` | `high` | :65-67 |

So today, concretely:

- **researcher** → tier `cheap` → `--model sonnet --effort medium`.
- **dispatcher, lead, qa, reviewer, worker** → tier `default` → **no `--model` flag and no
  `--effort` flag at all**. `ModelSpec.cli_args()` only appends `--model`/`--effort` when
  the field is non-None (`models.py:132-150`); tier `default` has both unset
  (`defaults/models.toml:55-59`, comment: "No model and no effort: whatever the provider CLI
  itself defaults to. Deliberately not a pinned choice"). This means five of the six roles
  spawn with the bare Claude Code CLI, which then applies **its own session default model**
  — switchboard does not choose or know what that is; it is whatever `claude` picks (this
  session's own environment reports the resolved model as Sonnet 5 / `claude-sonnet-5`, but
  that is a fact about the CLI invocation, not something switchboard sets — I did not trace
  the Claude Code CLI's own default-selection logic, which is out of this repo).
  This matches `notes/FEATURES.md:970-975` (untrusted prose, but consistent with the code):
  "`cheap` (sonnet, medium effort), `default` (no pin — CLI default)... `strong` (opus, high
  effort)."
- No shipped role uses `strong` (opus). `reviewer.md:2-13` says this explicitly: "NO SHIPPED
  ROLE IS ON `strong` ANY MORE... The fact worth keeping is which work repays a better
  model; the mechanism for acting on it is a flag, not a file." This repo's own
  `.switchboard/roles.toml` used to pin `reviewer` to `strong` and that override is now
  commented out (`.switchboard/roles.toml:29-38` — path
  `/Users/andrew/Code/switchboard/.switchboard/roles.toml`).
- No tier uses `haiku` — deliberate, per `defaults/models.toml:32-37`: haiku's
  `--permission-mode auto` classifier is measurably more conservative (blocked on an
  ordinary multi-`cd` shell command that opus allowed), so an unattended haiku agent stalls
  waiting on a human. `defaults/settings.toml:190` sets `permission_mode = "auto"` fleet-wide
  under `[herdr]`, which is exactly the mode this reasoning is about.

**Layering that could change the above, checked and found inert in this checkout:**

- `~/.config/switchboard/models.toml` (path from `[paths] global_models`,
  `defaults/settings.toml:36-38`, overridable by env var `SWITCHBOARD_MODELS_CONFIG`,
  `models.py:102`) — does not exist on this machine (empty read).
- `<repo>/.switchboard/models.toml` (`/Users/andrew/Code/switchboard/.switchboard/models.toml`)
  — present, but every tier override is commented out.
- `<repo>/.switchboard/roles.toml` — present, `[reviewer] model = "strong"` is commented out.
- No `<repo>/.switchboard/roles/*.md` directory exists to layer further (checked: only
  `roles.toml` and `presets.toml`/`presets/` are present under
  `/Users/andrew/Code/switchboard/.switchboard/`).

**How the resolved spec actually reaches the spawned process:**

- `switchboard/broker.py:3405-3410` (`Broker.delegate`): `r.spec(model).cli_args()` is
  passed as `model_args` to `self.h.start_agent(...)`, where `model` is the caller's
  `--model` override (a tier name) or `None`.
- `switchboard/herdr.py:517-538,574`: `start_agent(..., model_args=...)` takes the
  already-resolved flag list (e.g. `["--model", "opus", "--effort", "high"]`) and appends it
  to the herdr/claude launch args — "This module takes flags, never a tier name."
- **Restore is a special case**: `switchboard/broker.py:4643-4648` — when an agent is
  restored (`sb restore`), the tier is re-resolved from `roles_mod.get(...).spec()` **with
  no override**, i.e. from the agent's stored role only. A per-call `--model strong`
  override given at the original `sb delegate` does **not** survive a restore; the agent
  comes back on its role's plain tier. The comment there explains why restoring must pin
  *some* tier explicitly (so it doesn't fall through to the CLI's bare default), but doesn't
  address the override being dropped — I'm treating this as a real, unremarked gap rather
  than something I might have missed; worth flagging separately if it matters.

## 3. Is there a per-role or per-task model selection mechanism today?

Yes, at the **role** and **per-call** levels, no finer:

- **Per-role**: a repo can override any role's tier field-by-field in its own
  `.switchboard/roles.toml` (e.g. `[reviewer] model = "strong"`) or by shipping a full
  `.switchboard/roles/<name>.md`. This repo currently does neither (see above).
- **Per-call, from a lead or a human**: `sb delegate --model <tier>`
  (`switchboard/cli.py:143`, `_tier_help()` at `cli.py:59`, validated as a plain token at
  `cli.py:362`) — resolved through `Role.spec(override=...)` (`roles.py:59-73`), which goes
  through the *same* tier table, so a caller naming `strong` also gets `strong`'s effort,
  not just its model. The comment at `roles.py:66-71` is explicit that this replaced a
  now-deleted `model_id()` shortcut that silently dropped effort.
- **Tier names are open vocabulary**: nothing stops a repo from inventing e.g.
  `[tiers.midnight]` with any model/effort (`defaults/models.toml:64-67` shows `strong` as
  the pattern to copy; the repo's own commented-out `.switchboard/models.toml:22-24` shows
  a `midnight` example). An *unknown* tier name at the CLI is also a valid escape hatch — it
  passes straight through as a literal model id (`models.py:166-179`, "An unknown name is
  passed through verbatim as a model id... so you can pin a specific model without
  inventing a tier for it").
- There is **no per-task-kind selector** beyond this — i.e. nothing that says "adversarial
  review procedures get model X" or "summarisation gets model Y" automatically. The
  `adversarial` preset (`defaults/presets/adversarial.md`) is a *procedure* a lead runs
  (spawning reviewers with different lenses in the task string), not a model choice — it
  does not touch tiers at all (confirmed: no `model`/`tier` string in that file).
- Nothing in `defaults/presets.toml` or the plugin fragments (`defaults/plugins/*`) sets or
  mentions a model/tier — checked by grep, zero hits.

## 4. Other places models get chosen

Full grep for model-id-shaped strings (`claude-`, `opus`, `sonnet`, `haiku`, `fable`) across
the repo, restricted to code/config (excluding `research/*`, `notes/*`, `learnings/*`, which
are research prose / prior scratch notes, not live config):

- `defaults/models.toml:52,66` — the two tier definitions (`sonnet` for `cheap`, `opus` for
  `strong`), documented above. This is the **only** file where a model alias is set as
  config.
- `switchboard/herdr.py:537` — a docstring example (`e.g. ["--model", "opus", "--effort",
  "high"]`), not a live value.
- `tests/test_herdr.py:215,219`, `tests/test_broker.py:272,278,441,443,2676`,
  `tests/test_models.py` (many lines), `tests/test_roles.py:329` — test fixtures and
  assertions exercising the tier system (`sonnet`/`opus`/`haiku`/`claude-fable-5` as sample
  values). Not runtime config; confirms the mechanism above, does not add another one.
- **No hits** for any Anthropic API call with a hardcoded model id anywhere in
  `switchboard/*.py`, `bin/*`, or `defaults/plugins/*` — grepped explicitly.
- **No cron / scheduled-agent feature exists inside switchboard itself** — grepped
  `switchboard/`, `defaults/`, `bin/` case-insensitively for `cron`: zero hits. (Claude
  Code's own `/schedule`-style cloud cron, referenced in this session's system prompt, is a
  harness feature outside this repo, not something switchboard wires up.)
- **`switchboard/collector.py`, `panel.py`, `hooks.py`, `status.py`, `live.py`,
  `richboard.py`, `output.py`, `board.py`** — grepped for `model`: no matches except a few
  unrelated English uses of the word "model" in comments (e.g. panel.py:300, hooks.py:41).
  No subagent or summarisation calls of switchboard's own that invoke a model directly — the
  whole system's only path to a model is `sb delegate`/`sb restore` → `Role.spec()` →
  `ModelSpec.cli_args()` → herdr → the `claude` CLI. Switchboard is a spawner of Claude Code
  CLI sessions, not a direct Anthropic API caller.
- Presets under `.switchboard/presets/` (both the repo-local
  `/Users/andrew/Code/switchboard/.switchboard/presets/` and the committed
  `.switchboard-shared/presets/house-rules.md`) — no model/tier content, confirmed by grep.

## 5. Distinct kinds of task switchboard runs, beyond roles

These aren't a separate selection axis today (see §3 — nothing auto-picks a model per kind),
but they are real, distinct shapes of work the system runs, mostly expressed as **presets**
(behaviour injected into a role's prompt) or as procedures a `lead` runs over its children,
not as roles of their own:

- **Scouting / first-pass understanding** — `researcher.md:5-13`: "an orchestrator's FIRST
  move is now to spend one agent understanding a task before splitting it, and that agent is
  usually a researcher." This is why `researcher`'s tier was bumped from low to medium
  effort (`defaults/models.toml:38-50`).
  Bound preset: `evidence` (`defaults/presets.toml:60-63`).
- **Implementation** — plain `worker` (or ad-hoc) agents given a task string; no dedicated
  preset. `reviewer.md:8` notes there's no `builder`/implementation role any more —
  "implementation work goes to a plain agent with a well-written task."
- **Adversarial review** — `defaults/presets/adversarial.md`: a multi-round procedure a
  `lead` runs itself (spawn a proposer, spawn a fresh-lens reviewer, repeat until they
  converge), not a disposition baked into the `reviewer` role. Deliberately unbound by
  default; discovered via `sb presets adversarial` (`defaults/presets.toml:52-58`).
- **QA / behavioural verification** — role `qa`, distinguished explicitly from review:
  "A reviewer reads the work and gives a verdict on it; qa finds out whether the thing
  actually works" (`qa.md:9-11`). Bound presets: `verify` + `evidence`
  (`defaults/presets.toml:64-66`).
- **Plain code review** — role `reviewer`, bound preset `evidence`
  (`defaults/presets.toml:62`).
- **Dispatching** — role `dispatcher`, the sole top-of-repo role, decides lead vs. worker
  for each incoming ask but "holds no context to size it with" beyond that
  (`dispatcher.md:6-17`).
- **Task-owning orchestration** — role `lead`, "owns one job end to end and runs it through
  its own children," at any nesting depth (`lead.md:5-16`).
- **Summarisation** — no dedicated role/preset; `sb done "<summary>"` is written by whatever
  agent finishes, under the protocol's human-facing-summary rules (not a role-specific
  concern, and not model-differentiated).

None of these kinds carries its own tier — they ride on whatever role runs them
(`researcher`→cheap, everything else→default-i.e.-CLI-default), confirming §2/§3: model
choice in switchboard today is **role-tier-based only, plus an explicit per-call
`--model` override**, with no automatic kind-of-task-based selection.

## Confidence / what I did not check

- High confidence on all switchboard-repo-internal claims above (roles.py, models.py,
  broker.py, herdr.py, config.py, defaults/*.toml, defaults/roles/*.md,
  defaults/presets*.toml, the repo's live `.switchboard/*` overrides) — read directly,
  file:line given for each.
- I did **not** trace how the `claude` CLI itself picks its default model when switchboard
  passes no `--model` flag (tier `default`) — that's outside this repo. I only confirmed
  switchboard passes nothing in that case.
- I did not run `sb models` live to cross-check the resolved table (read-only task, and the
  code path is unambiguous from source), so this is a static-analysis trace, not a runtime
  observation. Worth a quick `sb models` if a live sanity check is wanted.
- `notes/FEATURES.md` and role-file HTML comments are switchboard's own design-rationale
  prose (untrusted per the task's own instruction), but every specific claim I drew from
  them is cross-checked directly against the TOML/Python that implements it, not taken on
  their word alone.
