# Scout: plugin/command/state architecture for the "plans" plugin

Read-only survey of the code, for whoever writes the implementation plan. Design source:
`design/PLANS-AND-STEPS.md`.

## 1. Plugin system (`switchboard/plugins.py`)

A plugin is `defaults/plugins/<name>/__init__.py` (shipped) or
`<repo>/.switchboard/plugins/<name>/__init__.py` (repo-local, replaces a shipped one of the
same name wholesale — `plugins.py:262-280`, `available()`).

- **Registration**: the module must define `API = 1` (`plugins.py:78-79`, `SUPPORTED_API`),
  optionally `SCOPE` (`"repo"`|`"user"`, default `"repo"`, `plugins.py:91,458-461`),
  optionally `LOCK` (default `True`, `plugins.py:462`), and a top-level `register(reg)`
  function that calls `reg.command(...)` for each subcommand (`plugins.py:464-477`).
  `register()` must declare at least one command or the plugin is reported `broken`
  (`plugins.py:475-476`). `VERSION` is optional, shown in `sb plugin list`.
- **Commands / dispatch**: `reg.command(name, handler, *, audience="both", help="", args=[...])`
  (`plugins.py:221-241`). `handler(ctx: Context, args: argparse.Namespace) -> Result`. Args
  are declared via `reg.arg(name, repeat=, flag=, choices=, help=)` — only 4 keys, deliberately
  capped (`plugins.py:162-170`). `sb plugin <name> list`/`info` are reserved verb names
  (`RESERVED`, `plugins.py:81-83`).
- **State**: `plugins.state_dir(loaded, worktree)` returns `<state_root>/<scope>/plugins/<name>/`
  and creates it (`plugins.py:603-617`). `state_root()` for `scope="repo"` is
  `store.store_dir(worktree)/plugins` — keyed on the **shared `.git`**, so it is identical
  from every worktree of the same clone (`plugins.py:589-600`). `scope="user"` is per-machine
  (`paths.user_state`). sb **never reads inside** a plugin's state dir (`plugins.py:604-606`,
  610-612) — a plugin owns its own file format and does its own migrations. `plugins.locked()`
  gives an exclusive `flock` on `<state_dir>/.lock` for the length of one handler call
  (`plugins.py:659-681`); `LOCK = False` opts a plugin out if it is append-only.
  Orphaned state dirs (plugin gone, directory still there) are reported by `sb doctor`, never
  deleted (`plugins.py:632-656`).
- **Prompt injection**: a plugin's `agent.md` (flattened to one line, capped at
  `[limits] plugin_fragment`) is its "fragment" — `plugins.fragment(repo, name)`
  (`plugins.py:323-338`), read through the same static-markdown pipeline as presets, **no
  import, no code execution**. A fragment is injected into a spawn only when something
  **binds** it: `presets.toml` names `"@<plugin>"` in `all = [...]` (every spawn) or under a
  role (`defaults/presets.toml:17-28,70`). Today `report-bug` and `suggestions` are bound to
  every agent (`defaults/presets.toml:70`: `all = ["@report-bug", "@suggestions"]`); `todo`
  is **not** bound (its binding was deliberately removed — comment at
  `defaults/presets.toml:57-63`). Binding costs context on *every* spawn forever; enabling
  only costs a directory (`plugins.py:283-293`).
- **Enable/disable**: `sb plugin <name> ...` only dispatches if `name` is listed in
  `enabled = [...]` in `.switchboard/plugins.toml` (or legacy `plugins.toml`) — checked in
  `cli.py:505-508` (`_validate_plugin`). Disabling leaves state untouched
  (`plugins.py:640-642`). **Deleting the plugin's folder removes it from `available()`**, so
  its commands vanish and any `@name` binding in `presets.toml` is *skipped with a warning*
  rather than erroring (`plugins.py` docstring 17-28, `broker.py:3158-3164`) — but its state
  directory is left on disk as an orphan (`plugins.py:632-656`), never deleted.
- **Load cost model**: 4 levels, cheapest-first — `plugins.py:17-30`. Nothing that spawns
  (`delegate`, `start`) ever imports plugin code — only `sb plugin <name> ...` and
  `sb plugin list` do (level 3/4). This is enforced/tested (`plugins.py:31-39`).

### Closest existing plugin — `todo`, as the template to copy

`defaults/plugins/todo/__init__.py` (see full read above) is the closest analogue:
commands + repo-scoped state + a lock, though **it is not bound to any spawn today**
(`agent.md` exists but nothing in `presets.toml` includes `@todo`). Layout to copy:

```
defaults/plugins/<name>/
  __init__.py     # API=1, VERSION, SCOPE="repo", LOCK=True, register(reg), handlers
  agent.md        # optional — the fragment injected wherever presets.toml binds "@<name>"
```

State pattern in `todo/__init__.py`: one JSON file (`FILE = "todos.json"`), whole-file
rewrite via tmp + `os.replace` under sb's own per-state-dir lock (`_read`/`_write`, lines
~180-210 in that file), monotonic non-reused ids (`t-<n>`), open string vocabulary for
`state` rather than a closed enum (explicit design note in the module docstring — matches
"Plans, steps and templates" §"open vocabulary" style guidance). **Note**: design doc
explicitly says (`design/PLANS-AND-STEPS.md:559-560`) *"The `todo` plugin is unrelated and
retired. Not the ancestor of this, and not to be grown into it."* — so copy its *shape*
(file layout, lock usage, JSON-file-per-repo pattern) but do not literally extend/rename it.

`report-bug` and `suggestions` (`defaults/plugins/report-bug/`, `.../suggestions/`) are the
templates for **prompt injection wired up and live** — their `agent.md` files are what
`presets.toml`'s `all = [...]` actually binds today. Good template for "one line told to
every agent at spawn."

## 2. Command dispatch (`switchboard/cli.py`)

Top-level parser is fully static (`build_parser()`, `cli.py:77-355`) — no plugin commands
appear in `sb --help`/`sb plugin --help` without importing the plugin, deliberately
(`cli.py:219-225`, avoids importing plugin code just to print top-level help). `sb plugin`
takes `name` then `REMAINDER` (`cli.py:226-228`). Resolution happens in
`_validate_plugin` (`cli.py:469-523`): look up the name in `plugins.available()`, check it's
enabled, `plugins.must_load()` (imports + calls `register()`), then build a **sub-parser**
from the declared commands (`plugins.build_parser`, `plugins.py:526-546`) and parse the rest
of argv against it. So `sb plan ...` is **not a first-class `sb` verb** — it is always
`sb plugin plan ...` unless the design wants a literal top-level `sb plan` alias, which
would require adding a dedicated case in `cli.py` (there is currently no mechanism for a
plugin to register a bare top-level verb — the only "plugin command hook" is the
`sb plugin <name> <verb>` namespace). Flag this to the plan author: **the design doc doesn't
name a command surface explicitly**, but if `sb plan ...` (no `plugin` in the middle) is
wanted, that's new work in `cli.py`, not something the plugin system gives for free.

Dispatch of an already-resolved plugin command happens in `_plugin_run`
(`cli.py`, search `_plugin_run` — invoked from `_dispatch` at `cli.py:1091-1092`), which
builds a `Context` (repo, worktree, state_dir, agent, json) and calls `plugins.run()`
(`plugins.py:683-701`), which wraps the handler and turns any exception into a
`PluginError` (one line, no traceback, unless `SB_DEBUG=1`).

## 3. State / store (`switchboard/store.py`, `switchboard/models.py`)

- **The STORE** is one sqlite file at `store.db_path(cwd)` = `store_dir(cwd)/state.db`
  (`store.py:90-91`), and `store_dir()` is keyed on the shared `.git`
  (`store.py:80-88` — same identity plugins' `state_root(scope="repo")` reuses).
- **Agents** table (`store.py:140-262`): primary key `name` (never an opaque id), `parent`
  (tree, not graph — `store.py:142`), `role`, `state` (working|blocked|done|failed),
  `workspace` (a **label only**, not proof of a checkout — `store.py:163-165`), `branch`
  (the worktree's git branch; **NULL means bare**, `store.py:166-172`), `is_top` (stamped
  only by `sb start`, `store.py:173-192`), `session_id`, `cwd`, `pane_id`/`terminal_id`
  (herdr handles), `turn` (`working`/`idle`, written by Claude Code hooks —
  `store.py:225-244`), `turn_doubt_since`, `absent_since` (liveness-detection bookkeeping,
  `store.py:215-224,245-259`).
- **Workspaces** table (`store.py:314-338`): primary key `name`, `checkout` (path, or
  **NULL = bare workspace**, `store.py:322-327`), `retired_at`, `retiring` (an agent name
  holding a claim, `store.py:330-334`).
- **Worktree identity for a plan to attach to**: there is **no standalone "worktree" row/id**
  in the schema. A worktree is identified by the **workspace name** (`agents.workspace` /
  `workspaces.name`), and its checkout path is `workspaces.checkout` (or
  `agent_branch()`/`workspace_branch()` helpers, `store.py:1107-1131`). So "a plan belongs to
  one worktree" (design doc) should key a plan on the **workspace name**, the same key
  `agents.workspace` uses — there is no separate worktree-id concept to reuse or invent
  beyond that. `store.checkout_verdict()` (`store.py:1404-1466`) is how sb re-derives whether
  a recorded checkout path is actually still a live worktree on disk — useful if the plugin
  ever needs to check a worktree still exists rather than trusting the stored path.
- **Reading agent liveness (never storing it)**: `store.get_agent`, `store.live_agents`,
  `store.live_tops` (`store.py:1085-1156`) read `state`/`turn`/`absent_since` directly off
  the `agents` row — this is exactly the same table `status.collect()` (used by `sb status`/
  board) reads for liveness/drift. A plans plugin should call into `store`/`status` (or shell
  out to `sb status --json` / `sb inspect`) to answer "is this step's owner alive", never
  cache that fact in its own JSON file — matches the design's explicit "plans never store
  liveness" rule. Note: **a plugin `Context` does not include a store handle or `Broker`**
  (`plugins.py:44-49,124-144` — deliberate, "no privilege escalation"), so a plugin handler
  cannot import `switchboard.store` and query it directly without breaking the documented
  isolation contract; the realistic path is shelling out to `sb status --json`/`sb inspect
  <name> --json` as a subprocess, or the design accepting a documented exception for this one
  plugin. **This is a real gap to flag** — worth asking Andrew whether "plans" plugin gets a
  sanctioned way to read agent liveness, since the plugin contract as built assumes handlers
  don't touch the store.
- `switchboard/models.py` is unrelated to plans — it's the model-tier resolution table
  (`sb models`, `--model` tiers). Not relevant to plan/step state.

## 4. The spawn / trigger path (`switchboard/broker.py`, `Broker.delegate`)

Prompt assembly happens in `Broker.delegate()` (`broker.py:3316-...`, list built at
`broker.py:3403-3424`):

```
prompts = [
    self._protocol(),                                    # the whole protocol text
    self._say("spawn.identity", name=, role=, parent=),   # "you are agent X, role Y..."
    self._say("spawn.roles", roles=...),                  # the role list
]
if ws: prompts.append(self._say("spawn.workspace", ...))
if as_prompt: prompts.append(as_prompt)
elif r.prompt: prompts.append(r.prompt)                   # the role's own prompt text
prompts.extend(self._resolve_bindings(role, with_))       # <-- plugin fragments land HERE
```

`_resolve_bindings()` (`broker.py:3137-3168`) calls `presets_mod.for_role(repo, role, extra)`
to get the ordered list of names (every-agent bindings + role bindings + explicit `--with`),
then `presets_mod.resolve(names, repo, on_event=...)` which is what turns `"@plan"` into
`plugins.fragment(repo, "plan")` and flattens/clips it (`plugins.clip`, `plugins.py:341-357`).
Every resolved fragment is `validate.line()`-checked (one line, capped at
`validate.MAX_PROMPT`) before going into the herdr spawn call — herdr flatly refuses a
multi-line agent argument (`broker.py:3410-3416`).

**This is exactly the "one line told to every agent at spawn" mechanism the design wants**:
bind `@plans` in `presets.toml`'s `all = [...]`, write `defaults/plugins/plans/agent.md` as
one short line/paragraph (same shape as `report-bug`/`suggestions` today), and it lands in
every spawn's prompt automatically via the path above — no code change needed in
`broker.py`/`cli.py`.

**The longer "plan-making instruction the lead reads when the job comes up"** is *not*
injected anywhere by default — the matching mechanism that exists today is `sb presets
<name>` (`cli.py:1049-1070`, `Broker.apply_preset` `broker.py:3757-3820`), which reads a
markdown file **on demand** and either prints it or pastes it into the caller's own session.
That preset lookup is level-1 (glob + read, no plugin import) per the plugins.py load model
(`plugins.py:26`), so it's cheap for an agent to call mid-turn. Two ways to wire this for
"plans": (a) ship it as an ordinary preset file (`.switchboard/presets/<name>.md` /
`defaults/presets/`) alongside the plugin, referenced by name from the one-line fragment
("...go read `sb presets plan-making`"); or (b) add a plugin **command** that prints the
instruction (`sb plugin plans instructions`), which costs one more load level (3, an import)
but keeps everything inside the plugin's own directory rather than splitting it across two
subsystems. The design doc doesn't decide between these — worth flagging as an open question
for the plan.

## 5. Records / sweep (`switchboard/sweep.py`)

`sweep.py` is **policy only** (what makes a worktree safe to delete — live agents, dirty
tree, unpushed/unmerged commits, 24h quiet on both clocks — `sweep.py:19-39`) and
**deliberately never imports `store`** (`sweep.py:14-17`, enforced by
`tests/test_panel.py::RendererImports`). It has **zero references to `plugins`** (confirmed:
no hits for "plugin" in `sweep.py`, `status.py`, or `board.py`). This matches the design
doc's own claim (`design/PLANS-AND-STEPS.md:445-447`): *"Nothing tells a plugin that an agent
was closed, a worktree deleted or a session restored — there are no lifecycle hooks and the
sweep runs with nothing of the plugin's alive."* **Confirmed true of the current code**: there
is no plugin registry hook anywhere in the sweep/close/cleanup path (`Broker.sweep`,
`Broker.cleanup`, `sb workspace close` in `broker.py`) — a plugin's state directory
(`plugins.state_dir`) is never touched by any of those paths; it just sits there keyed on the
repo's shared `.git`, independent of which worktree gets deleted. So "a plan stores which
worktree it belongs to and reads liveness live" is the only workable design — there's nothing
to subscribe to even if the plugin wanted a callback.

## Gaps the design assumes that the code does not (yet) support

1. **No top-level `sb plan ...` verb mechanism.** Only `sb plugin plan ...` exists today
   (§2 above). If a bare `sb plan` surface is wanted, that's new `cli.py` work, not something
   the plugin system provides.
2. **No sanctioned way for a plugin handler to read agent/workspace liveness.** `Context`
   deliberately excludes a store handle (§3). The plans plugin needs to read liveness (never
   store it, per the design) but the current contract doesn't give a handler a store
   connection — likely needs shelling to `sb status --json`/`sb inspect --json`, or a
   documented exception. Worth a decision before implementation starts.
3. **No board extension point.** Design doc says *"The board needs a hook for it"*
   (`design/PLANS-AND-STEPS.md:513-515`) — confirmed `board.py` has no plugin-rendering hook
   today (grep for "plugin"/"extension"/"hook" in `board.py` found nothing relevant). This is
   new work, not a gap in understanding — flagging so the plan accounts for it as its own
   task rather than assuming the board already supports it.
4. **No lifecycle hooks exist, confirmed** (matches the design's own claim) — §5.
5. **Which mechanism carries the "plan-making instruction" is undecided** — preset file vs.
   plugin command (§4) — the design doc doesn't pick one.

## Recommended recipe for a new plugin ("plans")

1. `defaults/plugins/plans/__init__.py` — `API=1`, `SCOPE="repo"`, `LOCK=True`,
   `register(reg)` declaring commands (create/list/show/tick/etc., modeled on `todo`'s
   `register()` shape but per the design's "one door" rule: each command changes only the
   steps it names, never rewrites the whole plan file wholesale where two commands could
   race — unlike `todo`'s simple whole-file rewrite, a plans plugin likely needs
   finer-grained locking or a read-modify-write discipline that checks it isn't clobbering a
   concurrent tick; `plugins.locked()` gives one lock per state dir for the whole handler
   call, which serializes all writes through sb already — probably sufficient, but note it's
   coarser than the design's own "a command changes the steps it names, never the whole plan"
   phrasing suggests they were worried about).
2. `defaults/plugins/plans/agent.md` — the one-line spawn trigger, bound in
   `defaults/presets.toml`'s `all = [...]` next to `@report-bug`/`@suggestions`.
3. Plan/step state as JSON file(s) under `plugins.state_dir()`, same tmp+`os.replace` pattern
   as `todo`.
4. Plan keyed on **workspace name** (`agents.workspace`/`workspaces.name`), not any new
   worktree-id concept — none exists in the schema (§3).
5. The longer plan-making instruction ships as a preset or plugin command — undecided, see
   gap #5 above.
6. Board rendering and `sb plan` (if wanted as bare verb) are both new surface-level work
   outside anything the plugin system gives for free — gaps #1 and #3.
