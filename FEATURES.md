# FEATURES.md — what switchboard does

This is the maintained inventory of switchboard's features. It is derived from reading
`switchboard/*.py` and `defaults/*` directly, not from `PLAN.md`/`POC.md`/`PRINCIPLES.md`,
which describe intent and are known to be partly stale or retracted. Entry point for
everything below: `bin/sb` → `switchboard.cli.main()` (there is no pip install; the repo
is not packaged, `bin/sb` just puts the repo root on `sys.path`).

Verified by reading cli.py, broker.py, status.py, store.py, output.py, board.py,
config.py, models.py, roles.py, presets.py, plugins.py, validate.py, herdr.py in full,
plus every file under `defaults/`, and by grepping every call site of `board.py`.

## Agent-facing verbs (the ones in `defaults/protocol.md`)

The seven below. The protocol also names `sb cleanup` and `sb restore` — an orchestrator
sweeps its own finished subtree — but those are documented under **Human-facing verbs**,
which is where they started and where the flags that qualify them live.

### `sb delegate <task> [--role] [--as] [--with] [--name] [--workspace] [--model] [--keep|--ephemeral]`
Spawns a child agent in its own pane to do a task independently; the caller does not
wait for it — it ends its turn and is woken (doorbell) when the child calls `sb done`.
- Entry point: `cli.py:663-681` → `Broker.delegate` (`broker.py:1193-1316`)
- Depends on: `roles.get` (role → tier and prompt), `presets.for_role`/`resolve`
  (`--with`), `models.Tiers.resolve` (`--model`), `store.claim_agent` (race-safe name
  claim), `herdr.start_agent`. `--keep`/`--ephemeral` write the child's cleanup
  disposition; no role file carries one any more, so without a flag the store's default
  (`[vocabulary] default_cleanup`, `close`) stands.
- Status: working; has tests specifically covering name-claim races
- Config: `defaults/roles/*.md`, `defaults/models.toml`, `defaults/presets.toml`,
  `defaults/prompts.toml [spawn] identity/workspace`

### `sb ask <who...> <question> [--timeout]`
Sends a question to one or more agents and blocks the caller's own turn until every
target answers or times out. Agent-to-agent only — refuses `human` as a target and
points the caller at `sb block` instead.
- Entry point: `cli.py:683-689` → `Broker.ask` (`broker.py:1369-1448`)
- Depends on: `store.put_message`/`reply_to_ask`, `Broker._ring`,
  `Broker._will_never_answer`/`_is_registered`, `Broker.flush_pending`
- Status: working; engineered around herdr's liveness signal being flaky (grace period
  before declaring a target vanished)
- Config: `settings.toml [timeouts] ask/ask_poll/gone_grace`

### `sb tell <who...> <message> [--re]`
Fire-and-forget message to one or more agents. If the recipient has a pending `sb ask`
outstanding, this implicitly answers it — there is no separate `reply` verb. Refuses
`human` (no mailbox to write to).
- Entry point: `cli.py:691-705` → `Broker.tell` (`broker.py:1326-1367`)
- Depends on: `store.put_message`/`pending_ask`/`mark_collected`, `Broker._ring` (message
  is deferred, not lost, if the target is mid-turn — see **deferred delivery** below)
- Status: working

### `sb inbox [--peek]`
Reads all of the calling agent's unread messages in one batched call and marks them
read, unless `--peek`. Human callers get a fixed explanatory string — humans have no
mailbox.
- Entry point: `cli.py:707-725` → `Broker.inbox` → `store.unread_for`
- Status: working

### `sb done <summary>`
Reports the calling agent finished. The summary is delivered to the parent's mailbox
(`[done] ` prefix) if it has one, otherwise only logged (root agents have no parent).
Also pushes `idle` to herdr and rings the parent's doorbell.
- Entry point: `cli.py:727-730` → `Broker.done` (`broker.py:1486-1509`)
- Depends on: same doorbell mechanism as `tell`
- Config: `settings.toml [vocabulary] done_prefix`

### `sb block <why>`
The only way an agent reaches a human. Ends the turn, records `state=blocked` in the
store (deliberately never surfaced to herdr as `blocked`, to avoid herdr un-registering
the agent's name), pushes a desktop notification, and shows up in `sb status --needs-me`
until a human answers via `sb tell`.
- Entry point: `cli.py:732-736` → `Broker.block` (`broker.py:1511-1544`)
- Status: working; `Broker._unblock_if_needed` re-registers the herdr name once answered,
  documented as a workaround for a herdr quirk

### `sb status [--active/--live] [--needs-me] [--mine]`
The whole agent tree as one join of store state against herdr's live pane state,
flagging drift: **STALLED** (store says working, herdr says idle/done, and `sb done` was
never called), **GONE** (the pane closed under it — self-heals by writing `state=failed`),
**UNDELIVERED** (mail was written but the doorbell never rang because the target was
mid-turn).
- Entry point: `cli.py:738-745` → `status.collect`/`status.render` (`status.py:232-331`, `583-611`)
- Depends on: `store` (agents/messages/events tables), single batched `herdr.list_agents`
  call
- Status: working
- Config: `settings.toml [states]` groupings, `[limits] task_clip`

## Human-facing verbs

### `sb init`
Pins the current repo for switchboard: writes `main_checkout` into the store's
`config.json` (`store.write_config`) and excludes linked config from `git status`. Writes
no `CLAUDE.md` — the protocol is delivered as a system prompt only, not a repo file.
- Entry point: `cli.py:625-632` → `Broker.init` (`broker.py:354-365`)

### `sb start [task] [--name] [--new] [--no-focus] [--no-board]`
Starts a top-level orchestrator agent, or returns to the existing one if re-run with no
args (asks for confirmation, but only at an interactive tty). Depends on **`sb board`**
being auto-opened beside it unless declined.
- Entry point: `cli.py:649-661` → `Broker.start`/`Broker._top` (`broker.py:367-475`)
- Depends on: `store.live_roots`, `herdr.create_workspace`/`start_agent`,
  `board.open_beside` (auto-fires here — see **`sb board`**), `config.prompt`
  (`[spawn] start_task`)
- Status: working, with detailed handling for concurrent `sb start` calls
- Config: `settings.toml [vocabulary] main_role/main_name`, `defaults/prompts.toml
  [spawn] start_task`

### `sb doctor [--reset-store [--force]]`
Health check: confirms the `herdr` binary is present, at a compatible version, and that
no conflicting herdr integration is installed; reports the store's condition (a pending
schema rebuild is otherwise invisible by design) and every plugin's, since this is the one
verb whose job is to import them all and say which will not load. `--reset-store` drops
and recreates the sqlite schema; refuses if any agent is currently live, unless `--force`.
- Entry point: `cli.py:585-623` → `Herdr.check` / `store.reset` / `_doctor_plugins`
- Note: plugin **problems** (one that will not import, one targeting an API this sb does
  not support) join a pending rebuild in making the exit code non-zero. Plugin **notices**
  — an orphaned state directory, a plugin being imported out of `.switchboard/` rather
  than `defaults/`, a pre-rename spelling still on disk — deliberately do not, because an
  orphan is permanent and would hold the exit code non-zero forever.
- Status: working. The store has no migration system by design: schema changes are
  compared by hash, additive column changes auto-apply, anything destructive triggers a
  full drop/recreate (`store.py:220-304`). See `BUGS.md` #4 for a case where this
  deadlocked running agents.
- Config: `settings.toml [herdr] min_version`

### `sb cleanup [name...] [--include-kept] [--force] [--dry-run]`
Closes finished agents' panes — never their history; `sb restore` brings a closed agent
back. With no names, sweeps the caller's own subtree (or everything, for a human). Three
layered safety gates: must be finished with no unread mail; the agent's own recorded
disposition (`--include-kept` lifts it); `--force` lifts every gate but only alongside an
explicit name.
- Entry point: `cli.py:801-806` → `Broker.cleanup` (`broker.py:1554-1626`)
- Depends on: the store's per-agent `cleanup` column, written at spawn
- Status: working. The disposition is a **run-time** decision, not a role's property: no
  role file sets `cleanup` any more, so an agent is a keeper only because someone spawned
  it with `sb delegate --keep` (or because it is one of the roots and leads the broker
  keeps by construction). `cli.py`'s own `--include-kept` help still says "whose role says
  keep" and is stale in that one word.
- Config: `settings.toml [vocabulary] default_cleanup` (`close`), overridden per spawn by
  `sb delegate --keep`/`--ephemeral`

### `sb workspace new [name] [--task] [--role] [--name/--agent] [--base] [--focus]`
Idempotently opens (or creates) one named "workspace" = one git worktree + one herdr
workspace + one lead orchestrator agent. The same name always resolves to the same
triple; concurrent callers with the same name are safe — the loser joins the winner
rather than erroring.
- Entry point: `cli.py:808-812` → `Broker.workspace_new` (`broker.py:561-628`)
- Depends on: `herdr.create_worktree`/`open_worktree`/`rename_workspace`,
  `store.claim_agent`, `Broker.link_config` (symlinks main checkout's `CLAUDE.md`/
  `.switchboard` into the new worktree), `roles.get`
- Status: working. This is the code path where **BUGS.md #1** lived (`Broker._adopt`
  raced on `agents.name` under concurrent openers) — marked **FIXED** in `BUGS.md`, but
  re-check `BUGS.md` before relying on the concurrent case being solid.
- Config: `settings.toml [vocabulary] workspace_role/base_branch/lead_suffix`,
  `[paths] linked_config`

### `sb restore <name>`
Brings a closed agent back with full context via herdr `--resume`, into a fresh tab in
its recorded workspace, on the model tier it was originally spawned with.
- Entry point: `cli.py:814-817` → `Broker.restore` (`broker.py:1636-1689`)
- Status: working

### `sb interrupt <name> <text>`
Cancels a running agent's current turn (sends `esc`, waits a settle delay, then sends the
new instruction) — the deliberate exception to the doorbell's normal "wait until idle"
deferral. For humans, meant for emergencies only.
- Entry point: `cli.py:819-822` → `Broker.interrupt` (`broker.py:1691-1716`)
- Config: `settings.toml [timeouts] interrupt_settle`, `defaults/prompts.toml [notify]
  interrupt`

### `sb inspect <name> [-n] [--events]`
Everything about one agent in one call: task, state + drift diagnosis, workspace/pane/
cwd/session, unread and undelivered mail, unanswered asks in both directions, its last
`sb done` summary, recent events, and a tail of its terminal output.
- Entry point: `cli.py:824-831` → `status.inspect`/`status.render_detail`
  (`status.py:813-974`), which calls `output.read_output`
- Depends on: `output.py` (reads the live herdr pane, falling back to the on-disk Claude
  Code JSONL transcript if the pane is gone), `store.transcript_path`
- Status: working. Subsumes a former `sb output` verb — that verb no longer exists;
  `output.py` is called directly by `inspect` now.
- Config: `settings.toml [display] output_lines/events`, `[limits] output_clip`

### `sb wait <name> [--for state] [--timeout]`
Blocks, server-side via `herdr agent wait`, until an agent reaches a given state.
**Human/script use only** — cli.py's own module docstring and the command's `--help`
both say agents should never call this: an agent ending its turn and being woken by the
doorbell is free, whereas `wait` burns a turn/process doing the same thing synchronously.
- Entry point: `cli.py:833-837` → `status.wait_for` (`status.py:1037-1108`)
- Status: working. Works around a herdr quirk where `agent wait --until <state>` returns
  instantly if already in that state — this instead waits for the opposite transition
  first, then loops. See `BUGS.md` #5 ("`sb wait` returns success while still working") —
  marked **NOT REPRODUCIBLE**, i.e. suspected but not confirmed as still an issue.
- Config: `settings.toml [timeouts] wait/wait_slice_ms`

### `sb log [--agent] [-n]`
Prints recent rows from the append-only `events` table. Debugging only.
- Entry point: `cli.py:839-847` → `store.recent_events`

### `sb presets [<name>]`
With no argument, lists available preset files and which roles/bindings use them. Naming
one **prints its prose** instead — unflattened, comments stripped — which is how a preset
that is bound to nothing gets read at all. Read-only and load level 1 (no plugin import),
so an agent can run it mid-turn.
- Entry point: `cli.py` `presets` branch → `presets.available`/`presets.bindings`/
  `presets.text`
- Config: `defaults/presets.toml`, `defaults/presets/*.md`, repo's
  `.switchboard/presets.toml` and `.switchboard/presets/*.md`
- Note: the naming form exists because of `adversarial` — see **Presets** below. An
  unknown name exits 1 and lists the ones that do exist.

### `sb plugin list`
Lists every plugin this repo can see, with its `VERSION`, its status
(`ok` / `not enabled` / `incompatible` / `broken`) and its bindings. Each import is wrapped
per plugin, so a broken one is a row saying so rather than a traceback; `SB_DEBUG=1` adds
the tracebacks after the table.
- Entry point: `cli.py` `plugin` branch → `_plugin_list` → `plugins.load_all`
- Config: `defaults/plugins.toml`, repo's `.switchboard/plugins.toml`, both plugin roots
- Note: two plugins ship — `report-bug` (enabled and bound to every agent) and `todo`
  (present but **not enabled**, the shipped example of available-without-being-enabled).

### `sb plugin <name> <verb> …`
Runs a command a plugin declared. The top-level parser takes the rest as `REMAINDER`; the
plugin's own arguments are parsed by a subparser sb builds from what its `register()`
declared, so `--help`, flag-level errors and `--json` are sb's throughout. sb creates the
state directory, takes an exclusive `flock` around the handler, enforces the command's
`audience`, and logs one event per dispatch.
- Entry point: `cli.py` `_validate_plugin` (resolve, import, parse) → `_plugin_run`
- Depends on: `plugins.must_load`/`build_parser`/`state_dir`/`locked`/`run`,
  `store.repo_root` (repo identity), `store.log_event`
- Status: working — `sb plugin report-bug …` dispatches out of the box; `sb plugin todo …`
  does not until the repo enables it. `tests/test_plugins.py` exercises the contract and
  `tests/test_shipped_plugins.py` the two that ship
- Config: `settings.toml [paths] plugins_dir/plugins_file/user_state/store_dirname`

### `sb plugins` — retired
Was `sb presets`. Now a hard error naming both replacements (`sb presets` for prompt text,
`sb plugin list` for code plugins), for one release, then removed. The `--json` key was
renamed from `plugins` to `presets` at the same time so the two payloads cannot be
confused.

### `sb models`
Prints the resolved tier → (provider, model, effort, CLI flags) table for this repo,
marking any tier "UNAVAILABLE" if its provider has no backend wired.
- Entry point: `cli.py:776-799` → `models.load`/`models.Tiers.resolve`/
  `models.ModelSpec.cli_args`
- Config: `defaults/models.toml`, `~/.config/switchboard/models.toml`, repo's
  `.switchboard/models.toml`

### `sb board` — hidden, human-only
A clickable live view of the agent tree (glyphs, click-to-focus, scroll), periodically
refreshed. Read-only against the store except for one side effect: `herdr agent focus`
when a human clicks an agent.
- Entry point: `cli.py:120` (registered `hidden=True`, so it does not appear in
  `sb --help`) → `broker._open_board` / `board.main`/`board.open_beside`
  (`switchboard/board.py`, 463 lines)
- Depends on: `status.collect` (the same join `sb status` uses), `herdr.split_pane`/
  `focus`/`pane_ids`
- Status: **working and reachable — not dead code.** It was flagged as a suspect (POC
  wired into `broker.start()`, "nobody could tell you what it does"). Verified reachable
  two ways: (1) `sb board` is a real subcommand — `cli.py:634-647` dispatches it, gated
  to refuse any caller `whoami()` resolves as an agent; (2) `Broker._top`
  (`broker.py:449,473`), which is `sb start`'s code path, calls `_open_board` →
  `board.open_beside` automatically, unless `--no-board` is passed. `board.py`'s own
  docstring confirms `open_beside()` was briefly dead code before `_top` started calling
  it. It is deliberately absent from `--help` and from `defaults/protocol.md` — hidden
  from agents on purpose, not orphaned. `tests/test_board.py` exercises it, and
  `scripts/05-mouse.py`/`scripts/06-board.py` are kept as the proof-of-concept record the
  maintained version was built from.
- Config: `settings.toml [display] board_refresh/board_chrome`, `NO_COLOR` env var

## Not verbs, but load-bearing

### Deferred message delivery ("the doorbell")
`Broker._ring` and `Broker.flush_pending`, run at the top of every `sb` invocation
(`cli.py:531-534`). Herdr's `agent prompt` interleaves into a running turn, so a message
to a mid-turn agent is held back and delivered the next time that agent calls `sb`, once
it has gone idle. Underlies `tell`, `ask`, `done`, and `block`; surfaced to humans in
`sb status`/`sb inspect` as `UNDELIVERED`.
- Entry point: `broker.py` `Broker._ring`, `Broker.flush_pending`

### Identity resolution
`Broker.whoami` (`broker.py:230-268`) resolves the calling agent from the
`CLAUDE_CODE_SESSION_ID` or `HERDR_PANE_ID` env vars that switchboard injects into every
spawned pane. A finished agent that calls `sb` again is auto-"revived" to `working`.
- Depended on by: every agent-facing verb (it's how `sb` knows who's calling)

### Config linking into worktrees
`Broker.link_config` (`broker.py:307-334`) symlinks `CLAUDE.md`/`.switchboard` from the
main checkout into each new worktree, so config is not duplicated per-worktree, and
excludes the symlinks from `git status` via `.git/info/exclude`.
- Depended on by: `sb workspace new`

### Layered config (`defaults/` → `.switchboard/`)
`config.py` merges two layers, most-general first: `defaults/` (shipped, complete on its
own) then `<repo>/.switchboard/` (that repo's differences only). Merge rules
(`config.merge`, `config.py:189-202`), applied per file type:
- Tables merge key-by-key (overriding one field of a role/tier leaves the rest).
- Scalars replace outright.
- Arrays join (base items, then override's new items, de-duped) — unless the override
  array's first element is `"!reset"`, which discards the base instead.
- `roles`: three sources merged field-by-field: `defaults/roles/*.md` →
  `<repo>/.switchboard/roles.toml` → `<repo>/.switchboard/roles/*.md`
  (`config.py:332-355`).
- `models`: `defaults/models.toml` → `~/.config/switchboard/models.toml` (or
  `$SWITCHBOARD_MODELS_CONFIG`) → `<repo>/.switchboard/models.toml`, per-tier
  (`models.py:230-247`) — the only layering with a global per-user middle tier.
- `presets.toml` bindings join shipped + repo's (`config.preset_bindings`). Preset
  **files** are layered by name out of `defaults/presets/*.md`, and a repo's
  `.switchboard/presets/<name>.md` replaces the shipped one of that name. The shipped
  bindings are **not** empty (`all = ["@report-bug"]` plus a `[roles]` table), so a repo
  that adds one is adding to those rather than starting from nothing. The pre-rename
  `.switchboard/plugins/` and `plugins.toml` are still read when a repo has not moved them
  (`config.path_for_legacy`).
- `plugins.toml` enablement (`enabled = [...]`) joins shipped + repo's
  (`config.plugin_enablement`); plugin *packages* are layered by name out of
  `defaults/plugins/<name>/`, a repo's directory replacing a shipped one of that name
  wholesale. `plugins.toml` carries both meanings during the transition — `all`/`[roles]`
  are pre-rename preset bindings, `enabled` is plugin enablement — and the keys are
  disjoint, so a file holding both parses correctly as both.
- `protocol.md` is the one exception to "join": a repo's `.switchboard/protocol.md`
  **fully replaces** the shipped one (`config.py:393-400`), rather than merging.
- `prompts.toml`/`settings.toml` merge entry-by-entry / table-by-table.
- `[paths] repo_dir` (the name `.switchboard` itself) is read only from the *shipped*
  `settings.toml` — a repo cannot use its own settings file to relocate its own settings
  directory (`settings.toml:8-9`, `config.py:78-88`).
- `SWITCHBOARD_DEFAULTS` env var replaces the whole `defaults/` directory (used by tests).
- Reads are cached by `(path, mtime_ns, size)` (`config.py:121-183`).
- Entry point: `switchboard/config.py`
- Depended on by: nearly everything — roles, models, presets, prompts, protocol,
  timeouts/paths/vocabulary settings all resolve through this layer

### The store
Sqlite schema for agents/messages/events (`switchboard/store.py`). No migration system:
schema changes are compared by hash; additive column changes auto-apply; anything
destructive triggers a full drop/recreate, refused while agents are live (breakable via
`sb doctor --reset-store --force`).
- Depended on by: every verb above

### The herdr adapter
`switchboard/herdr.py` wraps the external `herdr` CLI (pane/workspace management, agent
liveness, prompt injection). Nearly every verb above calls into it. `sb doctor` checks it
directly.

## Presets
Called "prompt plugins" until the word was needed for code that runs: a preset is markdown
and cannot run, a plugin is Python and can.

Three preset *files* ship (`defaults/presets/*.md`) and `defaults/presets.toml` ships the
bindings for them:

| preset | bound to | what it is |
|---|---|---|
| `evidence` | `researcher`, `reviewer`, `qa` | report only what you verified, and point at it precisely enough to be checked |
| `verify` | `qa` | find how *this* repo runs its checks and run them before reporting done — it deliberately names no command |
| `adversarial` | **nothing** | a procedure an orchestrator runs: one long-lived proposer, a fresh reviewer with an unrepeated lens each round, sequentially until nothing changes or four rounds are up |

Plus `all = ["@report-bug"]`, the one fragment every agent carries whatever its role.

Shipping a file only makes a preset available; a binding is what makes it applied. The
mechanism (`presets.available`/`bindings`/`for_role`/`resolve`/`text`) is wired into
`sb delegate --with` and `sb presets`. An unrecognized `--with` name is treated as a
literal inline instruction, not an error.

`adversarial` is the case that shaped `sb presets <name>`. It is bound to nothing on
purpose: it was a reviewer's disposition, which made every review adversarial and made
"run an adversarial review of this" impossible to *say*, since there was no procedure
anywhere. Now the orchestrator role points at it by name and the orchestrator reads it
when the job comes up, so an occasionally-used procedure is not paid for on every spawn
that might one day want it. It is also the one preset whose layout matters — it is read as
prose, never flattened.

One notation covers both kinds of prompt text, in `presets.toml` and in `--with` alike,
and the `@` sigil says which is meant (`presets.resolve`). Three rules, in order:

| the name | what happens |
|---|---|
| `@<name>` | that plugin's `agent.md`, or a failure — the `@` prefix is reserved, and never passes through as a literal |
| a bare name matching no preset file but matching an enabled plugin | an error naming the sigil: `'todo' is a plugin fragment — write '@todo'` |
| any other bare name | unchanged — preset file if one matches, otherwise a literal instruction |

**Failure is asymmetric for `@<name>` and only for it.** A fragment named explicitly (it is
in `delegate`'s `extra`, i.e. `--with`) that will not resolve is an error; one that arrived
from a binding is skipped with a line on stderr and a `fragment_skipped` event, because
delegation must not fail over a half-installed plugin. A name in both counts as explicit.
The bare-name error is not asymmetric: an unresolvable `@name` is a fact about this
machine, while a bare plugin name is wrong in the file wherever it is read.

## Plugins
A plugin is a Python package sb imports — `defaults/plugins/<name>/` or a repo's
`.switchboard/plugins/<name>/`, holding an `__init__.py` that defines `register(reg)`. It
owns a CLI verb and a directory of durable state.

Three states, separately settable: **available** (present in either root), **enabled**
(listed in `plugins.toml` — its commands dispatch and it gets a state directory), **bound**
(`@<name>` listed in `presets.toml` — its `agent.md` is flattened and appended to the spawn,
riding the existing `with_` list in resolution order with no slot of its own).

Two plugins ship, and between them they demonstrate all three states:

| plugin | scope | state |
|---|---|---|
| `report-bug` | `user` (`LOCK = False`) | enabled in `plugins.toml`, and bound to every agent by `all = ["@report-bug"]` — an agent that works around an sb bug silently costs everyone after it more than the bug did |
| `todo` | `repo` (`LOCK = True`) | available only. It was enabled and bound and came off both: the fragment is paid on every spawn forever and a shared list repays that only if somebody is actually working from it. One line in either file turns each half back on |

Enabling and binding stay separate precisely so "use `sb plugin todo` myself without taxing
every spawn" is a thing you can say.

A fragment is capped at `[limits] plugin_fragment = 4000` characters, against
`text = 40000` for traffic and `prompt = 80000` for presets and role prompts. Over-budget
text is truncated at a word boundary with a `fragment_truncated` event, never rejected: a
chatty plugin must not break spawning.

The load model is the load-bearing part. Four levels, and the assignment of verbs to them
is fixed and tested (`tests/test_plugins.py::IsolationTest`):

| level | operation | verbs |
|---|---|---|
| 0 | nothing | `status`, `done`, `ask`, `tell`, `inbox`, `block`, `log`, `cleanup`, `inspect`, `wait`, `init`, `restore`, `interrupt`, `board`, `models` |
| 1 | glob the roots, merge `plugins.toml` | `presets` |
| 2 | + read `<plugin>/agent.md`, flatten | `delegate`, `start`, `workspace` |
| 3 | + import, call `register()` | `plugin list`, `plugin <name> …`, `doctor` |
| 4 | + invoke one handler | `plugin <name> <verb>` only |

**No verb that spawns imports plugin code.** A plugin with a `SyntaxError`, or one that is
`raise SystemExit(3)` at module scope, cannot break `sb delegate`, `sb start` or
`sb workspace new`, because those verbs read a markdown file and stop.

State is a directory sb creates and never reads inside:
`<shared .git>/agentflow/plugins/<name>/` for `SCOPE = "repo"` (byte-identical from every
worktree, the same repo identity `state.db` uses), or
`~/.local/state/switchboard/plugins/<name>/` for `SCOPE = "user"`. sb takes an exclusive
`flock` around each handler call unless the plugin sets `LOCK = False`. Nothing goes in
`state.db`.

What a handler is handed is the contract, and so is what it is not: `Context` carries
`api`, `name`, `state_dir`, `repo`, `worktree`, `agent`, `json` — no `Broker`, no store
handle, no spawn authority. `Context`, `Result` and the parsed args are all
JSON-serialisable, which keeps a future out-of-process hatch open without building one.
- Entry point: `switchboard/plugins.py`
- Design of record: `.switchboard/design/PLUGIN-REDESIGN.md` §4–§7

## Roles
`defaults/roles/*.md` — front matter (`model` only) plus a markdown body used as the
spawned agent's prompt. Four ship:

| role | tier | purpose |
|---|---|---|
| `orchestrator` | default | delegates only, never does work itself; used at every scope (`sb start`, workspace leads, sub-orchestrators). Owns cleanup policy and the `adversarial` procedure |
| `reviewer` | default | reads the work and gives a verdict, led with in plain words |
| `qa` | default | runs the work and finds out whether it actually behaves — evidence about behaviour, as against the reviewer's judgement about code |
| `researcher` | cheap | investigates and writes findings to a file; the only role on the `cheap` tier |

`cleanup` is no longer a role field anywhere: what stays open depends on what is happening
in the room, which is not a property of a *kind* of agent, so it is a run-time call
(`sb delegate --keep`/`--ephemeral`, and the orchestrator's sweep).

No shipped role is on `strong`. `designer` was, and the fact it rested on — design is one
of the places a better model pays — is real; what did not follow was pinning a tier to a
role, when `sb delegate --model strong` buys the same thing per call without every spawn
of that kind paying for it.

`worker` has **no prompt file and is still a role name.** It is `[vocabulary] default_role`
and `fallback_role`: a plain `sb delegate` with no `--role` produces a `worker`, and
`--role archaeologist` inherits `worker`'s fields while keeping its own name. Such an agent
gets the protocol, its identity line, its bound presets and its task — nothing else. The
two rules `worker.md` used to carry (do only what you were asked; hand back what is too big
or underspecified) were universal, so they moved into `defaults/protocol.md` and every role
pays for them once.

## Model tiers
`defaults/models.toml`: `cheap` (sonnet, **medium** effort), `default` (no pin — CLI default),
`standard` (explicit legacy alias of `default`, kept for backward config compatibility,
not a bug), `strong` (opus, high effort). Only `claude` is a wired provider; `codex` is a
config field placeholder with no backend behind it yet.

`cheap` is still cheap the same *way* — sonnet, with effort as the dial — but at medium
rather than low, because its one consumer changed underneath it: an orchestrator's first
move is now to spend a researcher on understanding a task before splitting it, so the tier
picked for "one of five parallel readers, none of them load-bearing" became the tier every
subsequent split depends on. No tier uses haiku, and that is a measured decision rather
than a preference: `--permission-mode auto` runs a model-dependent classifier, and haiku's
stops for a human on ordinary shell commands.

## Overlaps worth knowing about (not bugs)
- **`tell` vs `interrupt`**: both send an agent text, but `tell` defers if the target is
  mid-turn; `interrupt` cancels the current turn and delivers immediately.
- **`block` vs `ask`**: `ask` is agent→agent and blocking; `block` is agent→human and
  non-blocking for the system. There is no `ask human` — it's refused, pointing at
  `block`.
- **`wait` vs the doorbell**: `wait` is a human/script-only blocking poll on herdr+store
  state; it is not "ask, deferred" — agents already get deferred delivery for free.
- **`inspect` vs the old `output`**: `sb output` no longer exists as its own verb;
  `output.py` is called directly by `inspect`.
- **`sb models` vs `sb presets`**: deliberately kept as two separate answers to "what
  vocabulary does this repo have."

## Known issues
See `BUGS.md` for the full write-ups. As of the last entries there: `Broker._adopt`
race (**FIXED**), herdr `wait` sending the wrong `--until` value and spinning CPU
(**FIXED**, both in the adapter), a schema change that deadlocked running agents
(**FIXED**, one shape still open — check `BUGS.md` #4 before relying on schema changes
being fully safe), and `sb wait` returning success early (**NOT REPRODUCIBLE**).

## Keeping this current
The cheapest rule that will actually survive delegated agents who haven't read this
file: **treat a `FEATURES.md` update as part of the definition of done for any change
that adds, removes, or changes the behavior of an `sb` verb or a `defaults/` file** —
the same way a change isn't done without its test passing. Put one line to that effect
in `defaults/protocol.md` (or wherever the orchestrator role's prompt lives), since that
is the one document every agent actually reads before doing anything. Don't rely on a
human periodically re-auditing — the auditor should be whoever's PR touched the surface
this file describes, at the moment they touch it, because that's the only point where
the cost of writing it down is smaller than the cost of finding out later it's stale.
