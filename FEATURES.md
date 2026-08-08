# FEATURES.md — what switchboard does

This is the maintained inventory of switchboard's features. It is derived from reading
`switchboard/*.py` and `defaults/*` directly, not from `PLAN.md`/`POC.md`/`PRINCIPLES.md`,
which describe intent and are known to be partly stale or retracted. Entry point for
everything below: `bin/sb` → `switchboard.cli.main()` (there is no pip install; the repo
is not packaged, `bin/sb` just puts the repo root on `sys.path`).

Verified by reading cli.py, broker.py, status.py, store.py, output.py, board.py,
config.py, models.py, roles.py, presets.py, validate.py, herdr.py in full, plus every
file under `defaults/`, and by grepping every call site of `board.py`.

## Agent-facing verbs (the seven in `defaults/protocol.md`)

### `sb delegate <task> [--role] [--as] [--with] [--name] [--model] [--keep|--ephemeral]`
Spawns a child agent in its own pane to do a task independently; the caller does not
wait for it — it ends its turn and is woken (doorbell) when the child calls `sb done`.
- Entry point: `cli.py:473-490` → `Broker.delegate` (`broker.py:867-948`)
- Depends on: `roles.get` (role → tier/cleanup/prompt), `presets.for_role`/`resolve`
  (`--with`), `models.Tiers.resolve` (`--model`), `store.claim_agent` (race-safe name
  claim), `herdr.start_agent`
- Status: working; has tests specifically covering name-claim races
- Config: `defaults/roles/*.md`, `defaults/models.toml`, `defaults/presets.toml`,
  `defaults/prompts.toml [spawn] identity/workspace`

### `sb ask <who...> <question> [--timeout]`
Sends a question to one or more agents and blocks the caller's own turn until every
target answers or times out. Agent-to-agent only — refuses `human` as a target and
points the caller at `sb block` instead.
- Entry point: `cli.py:492-498` → `Broker.ask` (`broker.py:1001-1080`)
- Depends on: `store.put_message`/`reply_to_ask`, `Broker._ring`,
  `Broker._will_never_answer`/`_is_registered`, `Broker.flush_pending`
- Status: working; engineered around herdr's liveness signal being flaky (grace period
  before declaring a target vanished)
- Config: `settings.toml [timeouts] ask/ask_poll/gone_grace`

### `sb tell <who...> <message> [--re]`
Fire-and-forget message to one or more agents. If the recipient has a pending `sb ask`
outstanding, this implicitly answers it — there is no separate `reply` verb. Refuses
`human` (no mailbox to write to).
- Entry point: `cli.py:500-514` → `Broker.tell` (`broker.py:958-999`)
- Depends on: `store.put_message`/`pending_ask`/`mark_collected`, `Broker._ring` (message
  is deferred, not lost, if the target is mid-turn — see **deferred delivery** below)
- Status: working

### `sb inbox [--peek]`
Reads all of the calling agent's unread messages in one batched call and marks them
read, unless `--peek`. Human callers get a fixed explanatory string — humans have no
mailbox.
- Entry point: `cli.py:516-534` → `Broker.inbox` → `store.unread_for`
- Status: working

### `sb done <summary>`
Reports the calling agent finished. The summary is delivered to the parent's mailbox
(`[done] ` prefix) if it has one, otherwise only logged (root agents have no parent).
Also pushes `idle` to herdr and rings the parent's doorbell.
- Entry point: `cli.py:536-539` → `Broker.done` (`broker.py:1118-1141`)
- Depends on: same doorbell mechanism as `tell`
- Config: `settings.toml [vocabulary] done_prefix`

### `sb block <why>`
The only way an agent reaches a human. Ends the turn, records `state=blocked` in the
store (deliberately never surfaced to herdr as `blocked`, to avoid herdr un-registering
the agent's name), pushes a desktop notification, and shows up in `sb status --needs-me`
until a human answers via `sb tell`.
- Entry point: `cli.py:541-545` → `Broker.block` (`broker.py:1143-1176`)
- Status: working; `Broker._unblock_if_needed` re-registers the herdr name once answered,
  documented as a workaround for a herdr quirk

### `sb status [--active/--live] [--needs-me] [--mine]`
The whole agent tree as one join of store state against herdr's live pane state,
flagging drift: **STALLED** (store says working, herdr says idle/done, and `sb done` was
never called), **GONE** (the pane closed under it — self-heals by writing `state=failed`),
**UNDELIVERED** (mail was written but the doorbell never rang because the target was
mid-turn).
- Entry point: `cli.py:547-554` → `status.collect`/`status.render` (`status.py:216-726`)
- Depends on: `store` (agents/messages/events tables), single batched `herdr.list_agents`
  call
- Status: working
- Config: `settings.toml [states]` groupings, `[limits] task_clip`

## Human-facing verbs

### `sb init`
Pins the current repo for switchboard: writes `main_checkout` into the store's
`config.json` (`store.write_config`) and excludes linked config from `git status`. Writes
no `CLAUDE.md` — the protocol is delivered as a system prompt only, not a repo file.
- Entry point: `cli.py:435-440` → `Broker.init` (`broker.py:323-334`)

### `sb start [task] [--name] [--new] [--no-focus] [--no-board]`
Starts a top-level orchestrator agent, or returns to the existing one if re-run with no
args (asks for confirmation, but only at an interactive tty). Depends on **`sb board`**
being auto-opened beside it unless declined.
- Entry point: `cli.py:459-471` → `Broker.start`/`Broker._top` (`broker.py:336-444`)
- Depends on: `store.live_roots`, `herdr.create_workspace`/`start_agent`,
  `board.open_beside` (auto-fires here — see **`sb board`**), `config.prompt`
  (`[spawn] start_task`)
- Status: working, with detailed handling for concurrent `sb start` calls
- Config: `settings.toml [vocabulary] main_role/main_name`, `defaults/prompts.toml
  [spawn] start_task`

### `sb doctor [--reset-store [--force]]`
Health check: confirms the `herdr` binary is present, at a compatible version, and that
no conflicting herdr integration is installed. `--reset-store` drops and recreates the
sqlite schema; refuses if any agent is currently live, unless `--force`.
- Entry point: `cli.py:418-433` → `Herdr.check` / `store.reset`
- Status: working. The store has no migration system by design: schema changes are
  compared by hash, additive column changes auto-apply, anything destructive triggers a
  full drop/recreate (`store.py:190-330`). See `BUGS.md` #4 for a case where this
  deadlocked running agents.
- Config: `settings.toml [herdr] min_version`

### `sb cleanup [name...] [--include-kept] [--force] [--dry-run]`
Closes finished agents' panes — never their history; `sb restore` brings a closed agent
back. With no names, sweeps the caller's own subtree (or everything, for a human). Three
layered safety gates: must be finished with no unread mail; the role's own
`cleanup = "keep"` disposition (`--include-kept` lifts it); `--force` lifts every gate
but only alongside an explicit name.
- Entry point: `cli.py:594-599` → `Broker.cleanup` (`broker.py:1186-1258`)
- Depends on: `defaults/roles/*.md` `cleanup` field
- Status: working
- Config: role files' `cleanup = "close"|"keep"` field

### `sb workspace new [name] [--task] [--role] [--name/--agent] [--base] [--focus]`
Idempotently opens (or creates) one named "workspace" = one git worktree + one herdr
workspace + one lead orchestrator agent. The same name always resolves to the same
triple; concurrent callers with the same name are safe — the loser joins the winner
rather than erroring.
- Entry point: `cli.py:601-605` → `Broker.workspace_new` (`broker.py:525-759`)
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
- Entry point: `cli.py:607-610` → `Broker.restore` (`broker.py:1268-1321`)
- Status: working

### `sb interrupt <name> <text>`
Cancels a running agent's current turn (sends `esc`, waits a settle delay, then sends the
new instruction) — the deliberate exception to the doorbell's normal "wait until idle"
deferral. For humans, meant for emergencies only.
- Entry point: `cli.py:612-615` → `Broker.interrupt` (`broker.py:1323-1348`)
- Config: `settings.toml [timeouts] interrupt_settle`, `defaults/prompts.toml [notify]
  interrupt`

### `sb inspect <name> [-n] [--events]`
Everything about one agent in one call: task, state + drift diagnosis, workspace/pane/
cwd/session, unread and undelivered mail, unanswered asks in both directions, its last
`sb done` summary, recent events, and a tail of its terminal output.
- Entry point: `cli.py:617-624` → `status.inspect`/`status.render_detail`
  (`status.py:792-953`), which calls `output.read_output`
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
- Entry point: `cli.py:626-630` → `status.wait_for` (`status.py:1016-1119`)
- Status: working. Works around a herdr quirk where `agent wait --until <state>` returns
  instantly if already in that state — this instead waits for the opposite transition
  first, then loops. See `BUGS.md` #5 ("`sb wait` returns success while still working") —
  marked **NOT REPRODUCIBLE**, i.e. suspected but not confirmed as still an issue.
- Config: `settings.toml [timeouts] wait/wait_slice_ms`

### `sb log [--agent] [-n]`
Prints recent rows from the append-only `events` table. Debugging only.
- Entry point: `cli.py:632-636` → `store.recent_events`

### `sb presets`
Lists available preset files and which roles/bindings use them.
- Entry point: `cli.py` `presets` branch → `presets.available`/`presets.bindings`
- Config: `defaults/presets.toml`, repo's `.switchboard/presets.toml` and
  `.switchboard/presets/*.md`
- Note: ships **inert** — see **Presets** below.

### `sb plugins` — retired
Was `sb presets`. Now a hard error naming both replacements (`sb presets` for prompt text,
`sb plugin list` for code plugins), for one release, then removed. The `--json` key was
renamed from `plugins` to `presets` at the same time so the two payloads cannot be
confused.

### `sb models`
Prints the resolved tier → (provider, model, effort, CLI flags) table for this repo,
marking any tier "UNAVAILABLE" if its provider has no backend wired.
- Entry point: `cli.py:569-592` → `models.load`/`models.Tiers.resolve`/
  `models.ModelSpec.cli_args`
- Config: `defaults/models.toml`, `~/.config/switchboard/models.toml`, repo's
  `.switchboard/models.toml`

### `sb board` — hidden, human-only
A clickable live view of the agent tree (glyphs, click-to-focus, scroll), periodically
refreshed. Read-only against the store except for one side effect: `herdr agent focus`
when a human clicks an agent.
- Entry point: `cli.py:444-457` (registered `hidden=True`, so it does not appear in
  `sb --help`) → `broker._open_board` / `board.main`/`board.open_beside`
  (`switchboard/board.py`, 463 lines)
- Depends on: `status.collect` (the same join `sb status` uses), `herdr.split_pane`/
  `focus`/`pane_ids`
- Status: **working and reachable — not dead code.** It was flagged as a suspect (POC
  wired into `broker.start()`, "nobody could tell you what it does"). Verified reachable
  two ways: (1) `sb board` is a real subcommand — `cli.py:444-457` dispatches it, gated
  to refuse any caller `whoami()` resolves as an agent; (2) `Broker._top`
  (`broker.py:418,442`), which is `sb start`'s code path, calls `_open_board` →
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
(`cli.py:389-392`). Herdr's `agent prompt` interleaves into a running turn, so a message
to a mid-turn agent is held back and delivered the next time that agent calls `sb`, once
it has gone idle. Underlies `tell`, `ask`, `done`, and `block`; surfaced to humans in
`sb status`/`sb inspect` as `UNDELIVERED`.
- Entry point: `broker.py` `Broker._ring`, `Broker.flush_pending`

### Identity resolution
`Broker.whoami` (`broker.py:199-247`) resolves the calling agent from the
`CLAUDE_CODE_SESSION_ID` or `HERDR_PANE_ID` env vars that switchboard injects into every
spawned pane. A finished agent that calls `sb` again is auto-"revived" to `working`.
- Depended on by: every agent-facing verb (it's how `sb` knows who's calling)

### Config linking into worktrees
`Broker.link_config` (`broker.py:276-321`) symlinks `CLAUDE.md`/`.switchboard` from the
main checkout into each new worktree, so config is not duplicated per-worktree, and
excludes the symlinks from `git status` via `.git/info/exclude`.
- Depended on by: `sb workspace new`

### Layered config (`defaults/` → `.switchboard/`)
`config.py` merges two layers, most-general first: `defaults/` (shipped, complete on its
own) then `<repo>/.switchboard/` (that repo's differences only). Merge rules
(`config.merge`, `config.py:170-211`), applied per file type:
- Tables merge key-by-key (overriding one field of a role/tier leaves the rest).
- Scalars replace outright.
- Arrays join (base items, then override's new items, de-duped) — unless the override
  array's first element is `"!reset"`, which discards the base instead.
- `roles`: three sources merged field-by-field: `defaults/roles/*.md` →
  `<repo>/.switchboard/roles.toml` → `<repo>/.switchboard/roles/*.md`
  (`config.py:299-322`).
- `models`: `defaults/models.toml` → `~/.config/switchboard/models.toml` (or
  `$SWITCHBOARD_MODELS_CONFIG`) → `<repo>/.switchboard/models.toml`, per-tier
  (`models.py:230-247`) — the only layering with a global per-user middle tier.
- `presets.toml` bindings join shipped + repo's (`config.preset_bindings`). Preset
  **files** are layered by name out of `defaults/presets/*.md`, and a repo's
  `.switchboard/presets/<name>.md` replaces the shipped one of that name; the shipped
  bindings are empty, so nothing shipped is ever *applied* unless bound or `--with`-ed.
  The pre-rename `.switchboard/plugins/` and `plugins.toml` are still read when a repo has
  not moved them (`config.path_for_legacy`).
- `protocol.md` is the one exception to "join": a repo's `.switchboard/protocol.md`
  **fully replaces** the shipped one (`config.py:360-367`), rather than merging.
- `prompts.toml`/`settings.toml` merge entry-by-entry / table-by-table.
- `[paths] repo_dir` (the name `.switchboard` itself) is read only from the *shipped*
  `settings.toml` — a repo cannot use its own settings file to relocate its own settings
  directory (`settings.toml:8-9`, `config.py:78-88`).
- `SWITCHBOARD_DEFAULTS` env var replaces the whole `defaults/` directory (used by tests).
- Reads are cached by `(path, mtime_ns, size)` (`config.py:99-149`).
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

`defaults/presets.toml` ships `all = []` and an empty `[roles]` table — **zero shipped
bindings.** Six preset *files* do ship (`defaults/presets/*.md`), so every repo can name
them, but shipping only makes a preset available; only a binding makes it applied. The
mechanism (`presets.available`/`bindings`/`for_role`/`resolve`) is wired into
`sb delegate --with` and `sb presets`. An unrecognized `--with` name is treated as a
literal inline instruction, not an error.

## Roles
`defaults/roles/*.md` — front matter (`model`, `cleanup`) plus a markdown body used as
the spawned agent's prompt:

| role | tier | cleanup | purpose |
|---|---|---|---|
| `worker` | default | close | fallback role — also what an undefined `--role` name inherits |
| `orchestrator` | default | keep | delegates only, never does work itself; used at every scope (`sb start`, workspace leads, sub-orchestrators) |
| `reviewer` | default | close | reviews critically, must give a clear pass/fail verdict |
| `researcher` | cheap | close | investigates and writes findings to a file; only role on the `cheap` tier |
| `designer` | strong | keep | produces a design doc; only role on the `strong` tier, kept open for follow-up |

## Model tiers
`defaults/models.toml`: `cheap` (sonnet, low effort), `default` (no pin — CLI default),
`standard` (explicit legacy alias of `default`, kept for backward config compatibility,
not a bug), `strong` (opus, high effort). Only `claude` is a wired provider; `codex` is a
config field placeholder with no backend behind it yet.

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
