# Proposal A — thin, in-repo, Python in-process

Revised against `decisions.md`, which is binding. Design only —
contract and shape, no implementation.

**The claim.** switchboard is a single-user tool with no packaging and no daemon. A real
extension system — manifest schema, subprocess protocol, registry, compat policy — is paid
for on day one and repaid only by a second user (C15's own falsification test; F4/F5 in
`PRINCIPLES.md` are what happens when you build for that user first). So: **a plugin is
Python that sb imports and calls two functions on.** Everything else is convention.

The decisions changed four things from the first draft, and two of them made the design
smaller. Noted where they land.

---

## 1. Naming, and exactly what gets renamed

Two concepts, two nouns, one telling difference: **the file extension**.

|  | **preset** | **plugin** |
|---|---|---|
| is | prompt text | Python code |
| ships in | `defaults/presets/<name>.md` | `defaults/plugins/<name>/` |
| overridden in | `.switchboard/presets/<name>.md` | `.switchboard/plugins/<name>/` |
| used as | `sb delegate --with <name>` | `sb plugin <name> <verb> …` |
| owns state | no | yes |
| listed by | `sb presets` | `sb plugins` |

`.md` cannot run; `.py` can. A preset can never add a verb, a plugin can never be
`--with`'d, and no directory ever holds both kinds — the sorting rule is the extension,
which needs no explaining.

### The renames, stated exactly

| today | becomes | note |
|---|---|---|
| `sb plugins` (lists prompt fragments) | **`sb presets`** | the rename decision 1 asks for |
| — | **`sb plugins`** (lists code plugins) | the name is reused, deliberately — see below |
| `defaults/plugins/*.md` | `defaults/presets/*.md` | 6 files move |
| `.switchboard/plugins/*.md` | `.switchboard/presets/*.md` | old path still read (§5) |
| `defaults/plugins.toml` (`all`, `[roles]`) | `defaults/presets.toml` | preset→role bindings |
| — | `defaults/plugins.toml` (`enabled`) | new, plugin enablement (§2.3) |
| `switchboard/plugins.py` | `switchboard/presets.py` | internal |
| — | `switchboard/plugin.py` | new, the loader |
| `[paths] plugins_dir`, `plugins_file` | `presets_dir`, `presets_file` (+ new `plugins_*`) | old keys read as fallback |

**On reusing the string `sb plugins`.** It changes meaning: today it prints preset names,
after this it prints plugin names. I considered making it a hard error for one release and
rejected it — it is a read-only lister whose output is visibly different, and the decision
picked this vocabulary precisely so `sb plugin todo add` reads correctly. The mitigation is
one line, not a mechanism: `sb plugins` prints a footer, `(prompt presets are now: sb
presets)`, for one release. This is the **only** user-visible break in the whole proposal.

**`sb plugin <name> …` nesting.** The decision's spelling (`sb plugin todo add …`) is a
nested subparser, exactly like `sb workspace new` already is (`cli.py:197-209`). This is
strictly less machinery than the top-level namespaces the first draft proposed: plugins
can no longer collide with core verbs, so the collision-detection rule that draft needed
is deleted rather than designed. sb's own management verbs stay off `sb plugin` entirely
and live as flags on the lister (`sb plugins --trust <name>`), so a plugin named `list`
cannot shadow anything either.

---

## 2. The plugin contract

### 2.1 Shape

```
defaults/plugins/todo/__init__.py            shipped
.switchboard/plugins/todo/__init__.py        this repo's override
.switchboard/plugins/todo.py                 single file, if it stays small
```

Two module-level names. One is required.

```python
"""Shared todo store for this repo."""       # first line = help text in `sb plugins`

def main(ctx, argv) -> int:                  # REQUIRED — implements `sb plugin todo …`
    ...

def prompt(ctx) -> str | None:               # optional — text injected at spawn
    ...
```

No `register()`, no base class, no manifest, no decorators. A plugin that only wants a CLI
verb writes one function.

`main` takes argv and returns an exit code. That is deliberately the shape of a *process*:
if in-process ever becomes untenable, the same contract runs out-of-process with no change
to any plugin's CLI, prompt text, or data. Not building it (decision 3) — just not
precluding it.

**No `status_line` hook.** Decision 4 puts `sb status` surfacing out of scope. Adding a
third optional function later is one line in the loader, which is exactly why it does not
need reserving now.

### 2.2 `ctx` — the whole API surface

One frozen dataclass. If it is not on `ctx`, sb does not offer it.

```python
@dataclass(frozen=True)
class Ctx:
    name:       str      # the plugin's own name
    repo:       Path     # THIS worktree            (store.worktree_root)
    repo_id:    Path     # the shared .git          (store.repo_root)   <- identity
    state:      Path     # <repo_id>/agentflow/plugins/<name>/  (created on first use)
    db:         Connection   # sb's store — for store.log_event only
    me:         str | None   # calling agent's name; None means a human is typing
    json:       bool         # --json was requested
    spawn_role: str | None   # set ONLY while prompt() is called during delegate
```

Plus one helper, `plugin.open_db(ctx, schema)`, so plugins do not each reimplement
WAL + busy_timeout + `CREATE TABLE IF NOT EXISTS`.

`ctx.db` is sb's store and plugins may **only** append to it via
`store.log_event(db, kind="todo.added", …)` — already a generic `(agent, kind, JSON)`
log (`store.py:638-650`) that takes new kinds with zero schema change, so plugin activity
shows up in `sb log` beside agent activity for free. Plugins must not create tables in it
(§3.3).

### 2.3 Lifecycle: discover → enable → trust → import → invoke

**Discovery** is a directory listing — no import, no execution. Two roots, most general
first, so a repo directory overrides a shipped one of the same name:

```
defaults/plugins/<name>/          shipped with sb
<repo>/.switchboard/plugins/<name>/   this repo's own or its override
```

Whole-unit replacement, not field merge — same rule presets already use, and the only rule
that makes sense for code.

**Enablement** is `plugins.toml`, mirroring `presets.toml` exactly:

```toml
# defaults/plugins.toml
enabled = []            # nothing is on by default

# <repo>/.switchboard/plugins.toml
enabled = ["todo"]      # joins the shipped list; "!reset" first to replace instead
```

Array-join with `!reset`, via the existing `config.merge()` — survey constraint #6 says
pick one of the two existing merge semantics rather than inventing a third, and this is
the same one preset bindings use. A plugin that is present but not enabled is listed by
`sb plugins` as `off`, and does not load, does not get a verb, and contributes no prompt
text.

**Trust.** Shipped plugins in `defaults/` are sb's own source and are trusted implicitly.
Repo plugins in `.switchboard/plugins/` are pinned by content hash in
`<repo_id>/agentflow/config.json` — the non-disposable JSON beside the store, explicitly
documented as surviving a schema reset (`store.py:82-88`), and uncommitted, so **a repo
cannot ship its own trust**. Unknown or changed hash → not imported, one line:

```
sb: plugin 'todo' is untrusted (changed since you trusted it) — sb plugins --trust todo
```

`sb plugins --trust <name>` re-pins. `sb doctor` reports untrusted plugins. See §7.1 for
why this is a speed bump rather than a boundary.

**Import** is `importlib.util.spec_from_file_location`, lazily:

- `sb plugin todo …` imports `todo` and nothing else.
- `sb delegate` imports every *enabled* plugin, because sb cannot know whether one defines
  `prompt()` without importing it.

That second case is the real cost. It is defensible with a number, not a hope: sb already
shells out to `git rev-parse` twice on every invocation (`store.repo_root`,
`store.worktree_root`) — tens of milliseconds of process spawn. A small stdlib-only module
imports in about a millisecond. Two or three enabled plugins is noise against a cost sb
already pays unconditionally; twenty, or one that imports a heavy dependency, is not, and
sb does nothing about that (§7.3).

**Invoke.** The `plugin` subparser captures everything after the plugin name with
`nargs=REMAINDER` and `add_help=False` (so `sb plugin todo --help` reaches the plugin
rather than printing sb's stub). sb does not parse plugin arguments; the plugin owns its
own `ArgumentParser(prog="sb plugin todo")`.

**Teardown: none, deliberately.** Every `sb` invocation is a short-lived process that
exits; a sqlite connection closes with it and WAL handles the rest. A plugin that needs
teardown needs a daemon, and sb has none (C10). Inventing a `close()` hook now would be
inventing it for a runtime that does not exist.

### 2.4 Error isolation

The rule, stated so it can be tested: **a plugin can only break the command it is asked to
run.**

| stage | can a plugin break it? | why |
|---|---|---|
| discovery, enablement, trust | no | listing, TOML merge, hash compare |
| parser build | no | no import; help line via `ast.get_docstring`, never execution |
| `prompt()` | no | wrapped; contribution dropped, spawn proceeds |
| import, for `prompt()` | no | wrapped per plugin |
| `main()` | yes, by definition | it *is* the command |

Hook failures follow the pattern `cli.py` already uses for the doorbell flush
(`cli.py:389-392` — "a doorbell that cannot ring must not take down `sb status`"): catch,
`store.log_event(kind="plugin_failed", …)`, one stderr line, carry on. A plugin with a
syntax error, a missing import, or a raising `prompt()` produces a named line above
otherwise-normal output; `SB_DEBUG=1` prints the traceback instead. `sb status` imports no
plugins at all, so it is isolated by construction rather than by care.

`main()` failures cannot be isolated — the plugin *is* the command — but they surface as
`sb: plugin 'todo' failed: <msg>` with exit 1, matching how `cli.main` already renders
`ValueError`/`KeyError` (`cli.py:399-401`) rather than a traceback.

**One deviation to name.** `cli.py`'s docstring says arguments are checked "here and
nowhere else" (`cli.py:16-18`); plugin argv is handed over unparsed. The boundary: sb
validates every value it *itself* passes onward, and the only one is `prompt()` output,
which is flattened with `config.flatten()` and checked with `validate.line()` before it can
reach herdr. What a plugin does with its own argv is the plugin's problem, because it is
your code.

### 2.5 Versioning

`switchboard.plugin.API = 1`; an optional `REQUIRES_API` that mismatches means skip plus
one warning. Four lines. No deprecation windows, no shims — if `Ctx` changes you edit your
two plugins. This is the single-user assumption cashed in directly, and it is the first
thing that breaks if there is ever a second user (§7.4).

---

## 3. Layering and state

### 3.1 What changes about "plugin files are not layered", and whether it was right

The survey's phrasing overstates today's behaviour slightly, and the distinction matters.
`plugins.available()` (`plugins.py:49-63`) *does* read `defaults/plugins/` — shipped
presets are discoverable by name in every repo. What is deliberately absent is two other
things:

1. no shipped file is ever **written into** a repo's directory, and
2. nothing shipped is ever **applied** unless bound in `plugins.toml` or named by `--with`
   — and `defaults/plugins.toml` ships `all = []` with an empty `[roles]`, so today
   *nothing* is on by default.

So the original decision is about **binding, not discovery**, and read that way it is still
exactly right — it is the "nothing arrives in your repo unargued" guarantee, and it costs
nothing to keep.

Decision 2 therefore changes less than it appears to. Both concepts layer
`defaults/` → `.switchboard/` by name, whole-unit replacement. Both stay inert until named:

- a **preset** is inert until `--with` names it or `presets.toml` binds it to a role;
- a **plugin** is inert until `plugins.toml` lists it in `enabled`, which ships empty.

One guarantee, one merge rule, expressed twice in the same file shape.

### 3.2 Repo identity — how a worktree resolves

The todo store must be shared across every worktree of a repo. sb already has the right
resolver, and it is *not* the one used for config:

```python
store.repo_root(cwd)   # git rev-parse --git-common-dir, anchored absolute  (store.py:44-59)
```

This returns the **shared `.git` directory**, byte-identical from the main checkout and
every worktree — which is precisely why the sqlite store lives there (`store.py:33-38`:
children in worktrees "must share one store or parent links do not survive"). A todo list
needs the same property for the same reason.

| standing in | `worktree_root()` | `repo_root()` = identity |
|---|---|---|
| `~/Code/switchboard` | `~/Code/switchboard` | `~/Code/switchboard/.git` |
| `~/.herdr/worktrees/switchboard/plugins-redesign` | `…/plugins-redesign` | `~/Code/switchboard/.git` |

Three working trees, one identity, one todo list. No new mechanism, no `repo_id` string to
generate or collide.

Note the deliberate asymmetry: `cli.py:381` uses `worktree_root()` for `Broker.repo`
because roles and presets are *this worktree's config*; plugin **state** uses
`repo_root()` because state is the *repo's*. `ctx` exposes both so a plugin picks
consciously rather than by accident.

### 3.3 Where state lives

```
<repo_id>/agentflow/plugins/<name>/
```

For this repo, from any worktree:
`/Users/andrew/Code/switchboard/.git/agentflow/plugins/todo/`

Beside the store and `config.json`: uncommitted, per-repo, visible from every worktree.
A plugin that needs something else computes it — `ctx.state` is a default, not a cage
(§6.1 uses this).

**Not sb's store**, for three specific reasons:

1. `_SCHEMA_HASH` is a sha256 over the *entire* `SCHEMA` string (`store.py:176`), so a
   plugin adding a table forces the reset-or-migrate decision for `agents`, `messages` and
   `events` too. A todo list must not be able to threaten the agent table.
2. The store is documented disposable (`store.py:6-8`, `190-195`: "There are no
   migrations… we simply drop and recreate"). Todos are not.
3. There is no extension point — a plugin would have to edit the one `SCHEMA` string in
   `store.py`, i.e. would not be a plugin.

Each plugin owns its own file or directory, its own schema, its own lifetime. `rm` is the
reset. That is C7's actual point — what keeps modules independently rewritable.

---

## 4. Prompt reach

The reason a plugin exists rather than a preset.

**Position.** `broker.delegate` assembles five sections (`broker.py:897-907`). Plugin text
becomes one more, at **position 2, immediately after the protocol**:

```
1. protocol
2. plugin prompts (N entries)   <- NEW
3. spawn.identity
4. spawn.workspace  [conditional]
5. as_prompt OR role.prompt
6. presets (--with, N entries)
```

A plugin's text is a *capability announcement* — "you have this verb" — which is protocol,
not persona. It should not be displaceable by `--as` (which replaces a role prompt
outright) nor reorderable by a preset. Presets stay last because they are the caller's most
specific intent, and a standing capability should not outrank that. Each entry is flattened
and validated, satisfying survey constraint #1 (no newlines, ever).

**Budget.** New `[limits] plugin_prompt = 400`, against `prompt = 8000` for presets and
role prompts. A plugin gets one or two sentences and sb enforces it. `protocol.md`'s own
header says it: everything outside the HTML comment "is paid for on every single spawn, by
every agent, forever." Over-budget text is truncated at a word boundary with an event
logged, not rejected — a chatty plugin must not break spawning.

**Why this beats a preset.** `prompt(ctx)` is a function, so it can return `None`:

```python
def prompt(ctx):
    n = open_count(ctx)
    if not n:
        return None            # an empty queue costs zero tokens
    return f'{n} open todos. File what you notice but were not asked to fix: sb plugin todo add "…"'
```

A preset is text on disk and is paid for whether or not it is relevant. That is the test
for which concept to use: **if the text never changes, write a preset.** `ctx.spawn_role`
lets a plugin be role-conditional with an `if` rather than a bindings table.

**They do not interact.** A plugin is deliberately not `--with`-able; two activation paths
would need reasoning about, and the plugin's own `if` covers every case `--with` would.

**Agent- vs human-facing verbs** need no machinery. `ctx.me` is the calling agent's name
(via `Broker.whoami`, `broker.py:215-256`) or `None` for a human. Two conventions: a verb
refuses the wrong caller in its own words, exactly as `sb wait` does today
(`cli.py:231-236`); and `prompt()` is the enumeration — agents know only the verbs they
were told about, which is how `sb board` is already kept out of their reach
(`cli.py:110-115`). This is weaker than enforcement, and anything irreversible should
check `ctx.me` explicitly.

---

## 5. Migration

Non-breaking except the one item named in §1.

| change | breaking? |
|---|---|
| `--with <name>`, unknown-value-is-literal | **unchanged** |
| preset files move to `defaults/presets/` | no |
| `.switchboard/plugins/*.md` still read as presets | no — deprecated, warned once |
| `presets.toml` and legacy `plugins.toml` `all`/`[roles]` both merged | no |
| `[paths] plugins_dir/plugins_file` read as fallback | no |
| plugin prompt at position 2 | no — nothing enabled by default, so assembly is byte-identical to today |
| `sb plugins` changes meaning | **yes** — the only one; footer line for one release |

The collision that needs care: `.switchboard/plugins/` and `plugins.toml` both keep their
names but change owner. Both resolve unambiguously without a flag day:

- **Directory** — presets are `.md`, plugins are `.py`/packages. The preset loader globs
  `*.md` in both `presets/` and `plugins/`; the plugin loader looks only for `<name>.py` or
  `<name>/__init__.py`. Neither can see the other's files, so an existing repo full of
  markdown keeps working and gets one deprecation line.
- **TOML** — distinct keys. `all`/`[roles]` are preset bindings (read from either
  `presets.toml` or a legacy `plugins.toml`); `enabled` is plugin enablement. A file
  containing both parses correctly.

Two content decisions while the preset files are being moved anyway:

1. **Fix `ask-dont-guess.md`.** It tells agents to run `sb ask human`, which `Broker.ask`
   refuses outright, pointing at `sb block` (`broker.py:1026-1033`). It has been
   instructing agents to run a command that cannot work. Pre-existing — flagging it rather
   than propagating it.
2. **Delete the `report-bug` preset when the `bug` plugin is enabled.** Two sources of
   truth for how to report a bug is worse than either. Safe to delete: nothing is bound to
   any role today, so only explicit `--with report-bug` users are affected, and for them the
   unknown-name rule degrades it to a literal instruction rather than an error. If you do
   not enable the plugin, keep the file.

---

## 6. The two plugins

Per decision 6, shape and contract — not exhaustive code. Both authored in `defaults/`.

### 6.1 `todo` — a deliberately dumb store

`defaults/plugins/todo/`, state at `<repo_id>/agentflow/plugins/todo/todo.db`.

It is a store, not a workflow engine. No claiming, no assignment, no queue semantics, no
auto-spawn — those are decisions, and decisions belong in a task string, not diffused into
every agent's system prompt (C8). Humans and agents use exactly the same verbs.

```
sb plugin todo add "<body>" [--label L]...
sb plugin todo list [--label L] [--state S] [--all]
sb plugin todo show <id>
sb plugin todo done <id> ["note"]
sb plugin todo drop <id> ["why"]
```

Rows: `id`, `body`, `state` (`open`/`done`/`dropped`), `labels`, `created_by`,
`created_at`, `closed_at`, `note`. Labels are a delimited string, not a join table — at
hundreds of rows on one machine a join table buys nothing. `state` is open vocabulary, not
a CHECK constraint (C12), so `blocked` works the day you want it.

**sqlite rather than a JSON file**, and the reason is a correctness bug rather than taste:
two agents running `sb plugin todo add` in the same second against a JSON file is a
read-modify-write race and a lost todo. This is the same reasoning that made `store.py`
choose sqlite with WAL — many short-lived `sb` processes writing concurrently
(`store.py:24-26`). JSONL survives concurrent appends but not `todo done 4`.

`--json` on every verb (C13: a plugin that only speaks human is one you cannot script).

`prompt()` returns `None` on an empty list, otherwise one sentence naming `add` only. It
does not tell agents to work from the list — an agent told there is a queue will work the
queue instead of its task, which is the failure C4 exists to prevent arriving through a new
door.

`sb status` surfacing is out of scope (decision 4). It stays possible: a third optional
function in the loader, one line, whenever it is wanted.

### 6.2 `bug` — files on disk

`defaults/plugins/bug/`. Simplest thing that works (decision 5): **one markdown file per
report**, no database, no GitHub.

```
<sb checkout>/.switchboard/bugs/<YYYYMMDD-HHMMSS>-<slug>.md
```

```
sb plugin bug file "<title>" [--cmd "…"] [--exit N] [--detail "…"]
sb plugin bug list
sb plugin bug show <name>
```

A file per report rather than appending to the existing root `BUGS.md` for one reason:
concurrent appends from several agents lose reports, which is F10 in the failure table
("durable memory as Markdown — whole file read to use any of it, conflicts on write"). One
file per report has no write contention at all, and `list` is a directory listing. Nothing
is deduplicated; the same bug filed three times is three files, and three files is itself
the reproduction signal. Not designing dedup is the simplest thing, per the decision.

**Where it writes is the interesting part.** A bug hit while running sb inside `lore` is a
bug about *switchboard*, and must not land in lore's state. So `bug` is the one plugin that
resolves a path to a repo it is not standing in: `Path(switchboard.__file__).parent.parent`
(which `bin/sb` already puts on `sys.path`), then `store.repo_root()` from there. Falling
back to `~/.config/switchboard/bugs/` if sb was copied rather than cloned.

This is a property of the stance, not a hack. `ctx.state` is a default; a plugin that knows
better computes its own path, because it is Python running in-process with the same imports
sb has. A manifest-driven subprocess plugin could not express "write under a different
repo's git dir" without the manifest growing a scope DSL. It is the strongest single
argument for the assigned execution model.

Auto-captured, because it is cheap and deterministic: sb version
(`git describe --always --dirty` of sb's own checkout — `--dirty` matters, since most of
these will be against uncommitted work), python, platform, the repo the bug was hit in, and
the calling agent and role from `ctx`. Everything else is what the agent passes. No
transcript capture: it is the highest-value and highest-risk field, and it is not needed to
make the simple thing work.

`prompt()` is unconditional — there is no state that makes it irrelevant — and is what
replaces the `report-bug` preset:

> If `sb` itself misbehaves, do not build a workaround silently: `sb plugin bug file "…"
> --cmd "…"`, then carry on with your task.

---

## 7. Where this stance costs you

1. **No sandbox; trust is a speed bump.** In-process Python has the full authority of your
   shell. The hash pin says *this exact code*, never *this code may only do X*. Anyone who
   can push to your repo can already run code on your machine via `conftest.py` or a
   `Makefile` — what the pin actually buys is narrower: without it, repo Python executes on
   `sb delegate` with no agent in the loop and nobody looking. Worth thirty lines; not a
   boundary. Enablement defaulting to empty is the larger part of the defence.

2. **Python-only in practice, permanently.** A Go or bash plugin needs a Python shim, at
   which point you have paid the subprocess cost in the worst way — ad hoc, per plugin,
   undocumented. §2.1 keeps the *contract* portable; it does not keep portable the plugins
   you will have written against `ctx.db` by then.

3. **Hook import cost is unbounded and I declined to bound it.** Every enabled plugin is
   imported on every `sb delegate`, and `prompt()` runs inside the spawn path with no
   timeout. One plugin doing I/O in `prompt()` taxes the hottest command in the system,
   forever, silently. I rejected `signal.alarm` or a thread as real machinery for a
   single-user tool — sound right up until it isn't, with no instrumentation to tell you
   the day arrived. Measure import + hook time before shipping rather than assuming it.

4. **`API = 1` detects a break and does nothing about one.** Changing a `Ctx` field breaks
   every plugin at once with no deprecation period. Correct for one user with two plugins;
   wrong for any other situation — and C15's test is whether this gets used somewhere else,
   so the design is betting against the thing the principles aim at.

5. **`nargs=REMAINDER` costs a consistency `cli.py` paid attention to.** `sb --json plugin
   todo list` works because `--json` is global; `sb plugin todo list --json` works only if
   the plugin bothers. That is the two-spellings-that-can-disagree problem the `common`
   parent parser exists to prevent (`cli.py:79-89`), reintroduced at the plugin boundary.
   sb can pass `ctx.json` as a hint; it cannot make a plugin honour it. `sb --help` also
   cannot show plugin verbs — it lists names and defers.

6. **Durable state sits beside disposable state.** `<repo_id>/agentflow/` is uncommitted and
   `.git`-adjacent. A fresh clone has no todos. The store is *designed* to be droppable and
   I have put non-droppable data in the same directory, distinguished only by filename.

7. **No test story.** sb has no packaging, so plugins load by path. sb can import them;
   `python -m unittest` in a plugin's directory cannot without replicating `bin/sb`'s
   `sys.path` trick. Plugins will be tested by running them, which means they will not be.

8. **Plugin prompts are a permanent context tax with one-directional pressure.** Two
   plugins × 400 chars is injected into every spawn forever, ahead of the role prompt —
   roughly the size of `protocol.md`, whose own header begs you to keep it short. The cap
   and the return-`None` pattern are mitigations, not a fix; nobody ever deletes a sentence
   from a plugin prompt.

9. **The core claim is unfalsifiable today.** "A heavyweight extension system is never
   repaid" is true for one user with two plugins and I cannot prove it stays true. The
   honest trigger to revisit: **five plugins, or the first person who is not you wanting to
   install one.** Then Q2 moves to global-install-only, the out-of-process hatch §2.1 keeps
   cheap gets built, and `API = 1` grows a real policy. Writing the trigger down is the only
   defence against noticing it three plugins late.

---

## 8. The surface, in one place

```
sb presets                        list prompt presets              (was: sb plugins)
sb delegate … --with <preset>     unchanged
sb plugins                        list plugins, enabled/off/untrusted
sb plugins --trust <name>         re-pin a repo plugin after an edit
sb plugin <name> <verb> …         whatever the plugin defines
```

```
defaults/presets/<name>.md                  shipped prompt text
defaults/plugins/<name>/                    shipped code
defaults/presets.toml                       preset→role bindings   (all, [roles])
defaults/plugins.toml                       enabled = []
.switchboard/presets/…  .switchboard/plugins/…  .switchboard/*.toml   per-repo overrides
<repo_id>/agentflow/plugins/<name>/         plugin state, per repo identity, all worktrees
```

```python
"""One line of help."""
def main(ctx, argv) -> int: ...
def prompt(ctx) -> str | None: ...
```
