# Plugin redesign — the design of record

Adjudicates `history/proposal-a.md` (thin/minimum-machinery) and `history/proposal-b.md`
(explicit contract) against `history/decisions.md`, which is binding. This document
supersedes both. It is
self-contained: nothing here requires reading the proposals or the current-state survey.

Design only. No implementation. Where a proposal lost, §12 records why.

**This document has been verified against the codebase.** Every claim it makes about
existing code was checked against source; the report is `verification.md`, alongside this file.
Two claims came back wrong and are corrected here:

- **§5.4 reason 1 was false.** An added column is precisely the case that *migrates in
  place*, not the case that wipes the store. The reason is deleted and §5.4 is rebuilt on
  the mechanism that genuinely does threaten the agent table. Its ruling is unchanged.
- **§4.6 claimed a reserved exit code.** There is none; the cited path returns 1. §4.6 now
  matches the real behaviour and says why no code is reserved.

Three more were incomplete rather than wrong, and are resolved rather than merely noted:
**§4.2's level table**, which then-in-flight work on `workspace-model` made wrong for `start`
and `workspace` (landed since, as `b36800c` — §0); **§6's skip-vs-error rule**, which had no provenance to work with and now
specifies how it is preserved; and **§8.1 row 7**, which undercounted the `sb ask human`
bug by one file. Everything else holds, including all of §5.1, §3.2's fact-check, and the
`--as`-never-displaces-`with_` argument §6 turns on.

**On citations.** Line numbers are against `plugins-redesign@86fac25` except in §4.2, §4.6
and §5.4, which were re-cited against `main@2637b5f` after `main` moved under this document
mid-verification, and except where a citation says `main@06232d9` — those were re-cited
during the reconciliation below, against the merged implementation.

---

## 0. Reconciliation — this document against what was built

**This is no longer design-only.** It was built in four phases and landed on `main` as the
merge `06232d9` (1120 tests): `048dd63` (the preset/plugin split), `366e9c6` (the loader),
`a0301bc` (the `@` sigil and injection), `156aa60` (both plugins and the `doctor` report),
rebased onto `430326d` and merged.

Each builder reported where this document was wrong or thin rather than working around it,
and each of those is now resolved *here*, at the section concerned, marked **[built]** where
the implementation was right and the text was wrong. The list, so that nothing is only in a
commit message:

| § | item | resolution |
|---|---|---|
| 4.2 / 6 | `start` and `workspace new` were level **0** in fact, not level 2 | **closed by the merge.** See below |
| 4.3 | `audience` defined only one of its two directions | **[built]** both directions enforced |
| 4.4 | `plugins.open_db` | **not shipped**, and the offer is withdrawn |
| 4.5 | `_validate` "gains one branch" | **[built]** the branch is the whole of level 3 |
| 4.5 | "`sb --help` lists plugin names" | **not built**; the claim is withdrawn, and why |
| 4.6 | the `SystemExit` fixture is not an `Exception` | **[built]** the asymmetry is now stated |
| 4.6 | `doctor` flags a plugin importing sb internals | **NOT BUILT — open, see §4.6** |
| 6 | the skip is silent unless something reports it | **[built]** `on_event`, now specified |
| 8.1 | "old `[paths]` keys read as fallback" | **wrong as written**; the fallback is path-level |
| 5.6, 8.4, 9.1, 9.2, 10 | six things the design left open | decided in phase 4, written in at each § |

**The level-0/level-2 divergence is closed, not deferred.** Phase 3 recorded, correctly,
that §4.2's and §6's claim of level 2 for `sb start` and `sb workspace new` was *not true on
this branch*: both called `Broker.delegate` with no `with_` at all, so they received no
bindings and therefore no fragments, and §4.6's test 2 passed for those two verbs trivially
— the exact hollowness its own comment warns about. That was a genuine divergence between
document and code, and it was nobody's mistake: the move it depended on lived on another
branch. `b36800c` has since landed binding resolution in `Broker._resolve_bindings`, and the
merge threaded phase 3's two keyword arguments through it, so the claim is now true of the
code as merged and the test is no longer hollow. Recorded closed.

One thing this document says that the merge did **not** silently lose, because it was checked
rather than assumed: `main`'s `_resolve_bindings` called `resolve` with neither
`explicit=` nor `on_event=`, both of which default safely — so the naive merge compiles,
passes, and quietly drops §6's asymmetry and every fragment event. It was verified by
reverting the broker to that body and confirming four spawn-path tests fail.

---

## 1. Problem statement

switchboard uses the word "plugin" for one thing and is about to need it for another.

**What exists today.** A plugin is one markdown file, `defaults/plugins/<name>.md` or
`<repo>/.switchboard/plugins/<name>.md`. It has no front matter; its name is its filename
stem. `sb delegate --with <name>` looks the name up, flattens the file to a single line
(headings dropped, bullets joined with `; `, whitespace collapsed — herdr refuses any
agent argument containing a newline), and appends it to the spawned agent's system prompt.
Six ship: `adversarial`, `ask-dont-guess`, `evidence`, `own-files`, `report-bug`,
`verify`. A separate file, `plugins.toml`, binds names to roles (`all = [...]` for every
agent, `[roles]` per role); shipped bindings are empty, so all six are `--with`-only and
nothing applies by default. An unrecognised `--with` value is not an error — it is passed
through verbatim as a literal instruction. `sb plugins` lists the names with their
bindings. That is the entire system: **discovery of static text, and binding of that text
to spawns.**

**What is wanted.** `sb plugin todo add "…"` — a unit that owns a CLI verb, owns durable
state, and can tell agents it exists. That is code, not text.

These are two concepts. Sharing one noun forces every sentence about either to disambiguate
first, and forces one directory (`.switchboard/plugins/`) and one config file
(`plugins.toml`) to mean two things. Splitting them is the whole point of this redesign.

**The split, fixed by decision 1:**

|  | **preset** | **plugin** |
|---|---|---|
| is | prompt text | Python sb imports |
| ships as | `defaults/presets/<name>.md` | `defaults/plugins/<name>/` |
| overridden at | `.switchboard/presets/<name>.md` | `.switchboard/plugins/<name>/` |
| reached by | `sb delegate --with <name>` | `sb plugin <name> <verb> …` |
| owns state | no | yes |
| listed by | `sb presets` | `sb plugin list` |

A preset is `.md` and cannot run. A plugin is `.py` and can. That is the sorting rule and
it needs no explaining.

---

## 2. The recommendation

**`sb plugins` is retired.** It becomes a hard error for one release naming its two
replacements: `sb presets` (the current behaviour) and `sb plugin list` (new). The `--json`
key is renamed to `presets` alongside the verb so the two payloads can never be confused.

**A plugin is a Python package that defines `register(reg)`.** `register` declares
commands and their arguments as data; sb builds the argparse subparser from that
declaration, so a plugin's `--help`, its flag-level errors, and its `--json` all look and
behave like sb's own. Handlers take `(ctx, args)` and return a `Result`. `Context`,
`Result`, and the parsed args are all JSON-serialisable, which keeps a future
out-of-process escape hatch open without building any of it.

**No verb on the hot path imports plugin code.** A plugin's prompt contribution is a
static markdown file, `<plugin>/agent.md`, read and flattened through exactly the pipeline
presets already use. The three verbs that spawn — `delegate`, and `start` and `workspace
new`, which reach `delegate` directly — glob, read a `.md`, and inject; none of them
imports. `sb status`, `sb done`, `sb ask`, and every core verb that does not spawn never
even glob. Plugin code is
imported only by `sb plugin …`, `sb plugin list`, and `sb doctor`, each wrapped per plugin.
A broken plugin cannot break the system, because the system has never heard of it.

**Three states, not two.** *Available* (present in either root) → *enabled* (listed in
`plugins.toml`; its commands dispatch and it gets a state directory) → *bound* (its
`@<name>` fragment is listed in `presets.toml`; its text is injected into spawns). Enabling
and binding are genuinely different decisions with different costs, so both stay separately
settable — but both shipped plugins default to enabled *and* bound (§7.4).

**State is a directory sb creates and never reads inside**, keyed by repo identity =
the absolute path of the shared `.git` directory (`git rev-parse --git-common-dir`), which
is byte-identical from the main checkout and every worktree. sb takes an exclusive `flock`
around each handler call, so a plugin doing read-modify-write on a JSON file is correct
without its author knowing the word "lock". Nothing goes in `state.db`.

**`todo`** is a JSON file of `{id, text, state, labels, created_by, created_at, …}` with
`add`/`list`/`show`/`done`/`drop`. No claiming, no assignment, no queue semantics. **`report-bug`**
is one markdown file per report under `~/.local/state/`, no index, no locking, no dedup,
no GitHub. Both ship in `defaults/`, and both ship **enabled and bound** — this is a
single-user tool and its user wants both in every repo (§7.4).

Everything below is the detail of those seven paragraphs.

---

## 3. Naming and separation

### 3.1 The commands

```
sb presets                     list presets and their bindings     (was: sb plugins)
sb delegate … --with <name>    unchanged for preset names
sb delegate … --with @<name>   a plugin's fragment, by explicit request
sb plugin list                 list plugins: available / enabled / bound / broken
sb plugin <name> <verb> …      whatever the plugin declared
```

`sb presets` emits `{"presets": [...], "all": [...], "roles": {...}}`.

Note the deliberate asymmetry: `presets` is plural and flat because presets have no verbs
to namespace; `plugin` is singular and a namespace because plugins do. `sb plugin <name>`
is a nested subparser, exactly as `sb workspace new` already is.

### 3.2 Retiring `sb plugins`

For one release:

```
$ sb plugins
sb: `sb plugins` has been split. Prompt fragments are now `sb presets`;
    code plugins are `sb plugin list`.
```

Then the verb is removed.

**The fact-check the brief asked for.** Proposal B argued the loud break was necessary
because repurposing `sb plugins` would hand a `--json` caller the key `plugins` with
entirely different contents. *That argument is wrong on the facts.* The only occurrences of
the string `"plugins"` as a payload key in this repo are `cli.py:565` itself — the producer
— and nothing consumes it. `scripts/` never invokes `sb plugins`. The three test hits
(`tests/test_status.py:750`, `tests/test_validate.py:253`, `tests/test_config.py:345`)
consume the *verb list* and the *module list*, not the JSON key. There is no consumer to
break.

The ruling stands anyway, on two different grounds:

1. **Decision 1 says the current `sb plugins` "must be renamed."** Pointing the same string
   at a new meaning is a repurpose, not a rename. It leaves `sb plugins` and `sb plugin`
   as a near-identical pair differing by one character and meaning two different things —
   precisely the two-spellings-that-can-disagree hazard this codebase already engineers
   against (`--live`/`--active` and `--all-idle`/`--include-kept` share one `dest`
   specifically so the two can never diverge, `cli.py:157`, `cli.py:190`).
2. **With zero consumers, the loud option is nearly free.** The usual argument for a
   soft transition — don't break the scripts — has no scripts to protect. Take the option
   that leaves no ambiguity.

The mitigation proposal A offered (keep the string, print a footer pointing at `sb presets`
for one release) is worse than it looks: a footer is read once by a human and by nothing
else, and after one release the confusing name is permanent.

### 3.3 One notation for prompt text, and the gap in it closed

Presets and plugin fragments both bind in `presets.toml` and both appear in `--with`. A
sigil distinguishes them:

```toml
# .switchboard/presets.toml
all = ["own-files", "@todo"]
[roles]
reviewer = ["adversarial", "@report-bug"]
```

`adversarial` is a preset file. `@todo` is the fragment shipped by the plugin `todo`. The
sigil means a preset and a plugin may share a name without colliding, and it makes the
provenance of every injected line visible in the binding file.

Three rules, in this order:

- `@<name>` that does not resolve to an enabled plugin with an `agent.md` is an **error**.
  The `@` prefix is reserved; there is no literal-passthrough for it.
- A **bare** name matching no preset file, but matching an enabled plugin, is an **error**:
  `sb: 'todo' is a plugin fragment — write '@todo'`. This closes the failure both proposals
  identified and neither fixed: typing `--with todo`, forgetting the sigil, and silently
  shipping the one-word string `"todo"` into an agent's system prompt. It looks like
  success and is not.
- Every other bare name behaves exactly as today: a preset file if one matches, otherwise
  a literal instruction passed through verbatim. That documented behaviour is untouched.

**No top-level aliases.** Proposal B offered an opt-in `sb todo` alias and then conceded in
its own costs that it undermines the collision-safety argument used to justify the
namespace. It does. `sb plugin todo add` is four extra characters. Rejected.

---

## 4. The plugin contract

### 4.1 Shape

```
defaults/plugins/todo/
    __init__.py        register(), handlers, API, VERSION
    agent.md           optional — the prompt fragment, injected as @todo
```

A repo's `.switchboard/plugins/<name>/` replaces a shipped directory of the same name
wholesale. Whole-unit replacement, not field merge — the same rule preset files already
use, and the only rule that makes sense for code.

```python
"""One todo list per repo, shared across every worktree."""   # first line = help text

API     = 1
VERSION = "0.3.0"
SCOPE   = "repo"        # "repo" (default) or "user"
LOCK    = True          # default; False for append-only plugins

def register(reg):
    reg.command("add", add, audience="both", help="add a todo",
                args=[reg.arg("text"), reg.arg("--label", repeat=True)])
    ...

def add(ctx, args) -> Result: ...
```

The module docstring's first line is the help text shown by `sb plugin list`. No separate
`SUMMARY` constant — the docstring is already there and is one fewer name to define.

### 4.2 The load model

Four operations of increasing cost. Every verb uses the cheapest one that answers its
question, and the assignment of verbs to levels is fixed and testable:

| level | operation | yields | verbs that reach it |
|---|---|---|---|
| 0 | nothing | — | `status`, `done`, `ask`, `tell`, `inbox`, `block`, `log`, `cleanup`, `inspect`, `wait`, `init`, `restore`, `interrupt`, `board`, `models` |
| 1 | glob the two roots, merge `plugins.toml` | names, roots, enabled | `presets` |
| 2 | + read `<plugin>/agent.md`, flatten | the prompt fragment | `delegate`, `start`, `workspace` |
| 3 | + `importlib`, call `register()` | help text, command table, `API`, `VERSION` | `plugin list`, `doctor`, `plugin <name> …` |
| 4 | + invoke one handler | the work | `plugin <name> <verb>` only |

**Three verbs stop at level 2, not one.** An earlier draft of this table put `start` and
`workspace` at level 0. That was true when the CLI's `delegate` branch owned binding
resolution, and it was a bug: `sb start` and `sb workspace new` reach `Broker.delegate`
directly, so their leads were spawned with no bindings at all — not even the repo's
every-agent ones. `b36800c` fixes it by moving resolution into `Broker._resolve_bindings`,
called from `delegate` itself (`main@06232d9`, `broker.py:1097-1128`, reached at `:1270`),
which every spawn passes through (`Broker.start`, `_spawn_lead`). Both verbs are therefore
level 2. `restore` stays at level 0: it resumes a session by id and assembles no system
prompt at all.

**This was level 0 in fact until the merge, and is level 2 now.** Between `a0301bc` and
`06232d9` the fix lived on another branch, so on this branch the table above described the
intent and not the code — recorded and closed in §0.

**`sb delegate` still stops at level 2, and so do the other two.** They read a markdown
file. None imports plugin code, so no plugin can slow, crash, hang, or `sys.exit()` the
verbs the entire system is built on. This is a topology, not defensive coding — and it is
the single most important property in this document.

**The safety property survives the move, and it was checked rather than assumed.** "Never
imports plugin code" now has to hold for three callers instead of one, so: the whole body
of `_resolve_bindings` is `presets.for_role` — a config read — followed by
`presets.resolve`, which globs the two roots, reads a `.md`, and flattens it, plus a
`validate.line` on the result. There is no `importlib` anywhere on that path, and under
this table there never will be: importing is level 3, and level 3 is reached only by
`sb plugin …`, `sb plugin list`, and `sb doctor`. A plugin with a `SyntaxError` still
cannot break `sb start`. What widened is the blast radius of a *level-2* failure — from one
spawn verb to three — and the set of things that can fail at level 2 is unchanged: a
missing file, or a file that will not flatten. §4.6's tests are extended accordingly.

One consequence to record rather than discover: `Broker` now imports the preset module
(`main@06232d9`, `broker.py:39` — `presets`, after phase 1's rename; the resolver's
`plugins_mod` alias was renamed with it), and the comment the old CLI-side topology leaned on —
"the broker takes prompt strings and knows nothing about plugins" — is deleted with the
move. Nothing here depended on the broker being plugin-ignorant. What it depends on is the
*level*, and `_resolve_bindings` is level 2.

**There is no `ast.parse` layer.** Proposal B put one between glob and import, to read
`API`/`VERSION`/`SCOPE` from module-level literal constants without executing the file.
Rejected, on cost:

- Its stated purpose — answering questions about a plugin without running it — is only
  load-bearing on a verb that must not import. Under the static-fragment decision (§6),
  `delegate` needs nothing from it: it needs a name, an enabled bit, and a `.md` file.
- Everywhere else, sb is importing the module anyway. A second reader of the same file,
  with different failure modes and a different answer when they disagree, buys nothing
  there.
- It imposes a constraint authors cannot discover except by hitting it — `VERSION =
  _read_version()` is a natural thing to write and would be rejected — in exchange for a
  property nothing needs.

What is genuinely lost: proposal B could refuse to inject the fragment of an
API-incompatible plugin at delegate time, on the theory that a fragment telling an agent to
run `sb plugin todo claim <id>` when `claim` no longer exists is worse than no fragment.
That check moves to `sb doctor` and to the command itself, which fails by name. For one
user with two plugins this is the right price; it is listed in §11 as knowingly deferred.

**Import failure is per plugin, always.** `sb plugin list` and `sb doctor` wrap each
import; one plugin with a `SyntaxError` costs the others nothing and is reported as a
status, never a traceback:

```
$ sb plugin list
  todo          0.3.0   ok            [enabled, @todo bound to every agent]
  report-bug    0.2.1   ok            [enabled]
  ci-check      1.2.0   not enabled   add to .switchboard/plugins.toml
  shiny         2.0.0   incompatible  targets API 2, this sb supports API 1
  halfthing     —       broken        __init__.py:14 SyntaxError: invalid syntax
```

`SB_DEBUG=1` prints the traceback instead. This follows the pattern `cli.py` already uses
for the doorbell flush (`cli.py:389-392` — "a doorbell that cannot ring must not take down
`sb status`"): catch, `store.log_event`, one stderr line, carry on.

**No trust gate.** Proposal A pinned repo-local plugins by content hash in
`<shared .git>/agentflow/config.json`, requiring `sb plugins --trust <name>` after any
edit. Rejected. Its own justification was that repo Python would otherwise execute on `sb
delegate` with no agent in the loop and nobody looking — and under the level-2 ruling above,
`sb delegate` never imports plugin code at all, so that justification evaporates. What
remains is a speed bump against a party who can already run code on the machine via
`conftest.py`, a `Makefile`, or a git hook, guarding a case that does not exist yet
(decision 2 says author everything in `defaults/` for now). The defence that does the real
work is `enabled` shipping empty. `sb doctor` names any enabled plugin loaded from
`.switchboard/plugins/` — visibility, not a gate.

**No teardown hook.** Every `sb` invocation is a short-lived process that exits. A plugin
needing teardown needs a daemon, and sb has none.

### 4.3 Registration

A plugin defines exactly one entry point. `register` may call `reg.command()` and
`reg.arg()` and nothing else; the registry object exposes nothing else. It runs at import
and must not touch the filesystem or the network — work done in `register` is work done on
every `sb plugin` invocation, including `--help`.

```python
def register(reg):
    reg.command("add",  add,  audience="both",  help="add a todo",
                args=[reg.arg("text"), reg.arg("--label", repeat=True)])
    reg.command("list", ls,   audience="both",  help="list todos",
                args=[reg.arg("--state", help="open, done, dropped, or any label you use"),
                      reg.arg("--label", repeat=True)])
    reg.command("drop", drop, audience="human", help="delete a todo outright")
```

**Arguments are data, and sb builds the argparse subparser from them.** This is the
decisive advantage over the alternative (proposal A's `main(ctx, argv)` with
`nargs=REMAINDER`, the plugin owning its own parser). Three properties fall out that a
REMAINDER hand-off cannot provide:

- `sb plugin todo add --labl x` gets an sb-quality error naming the flag the caller typed —
  the property `cli.py`'s own docstring is proud of (`cli.py:16-18`).
- `sb plugin todo --help` is generated by sb, so every plugin's help looks like sb's.
- **`--json` works everywhere, uniformly.** Under a REMAINDER hand-off,
  `sb plugin todo list --json` works only if the plugin bothers to implement it. C13 says
  the CLI *is* the API and every command emits JSON so that wrapping is mechanical; a
  `--json` that holds for eighteen verbs and maybe for plugin verbs is not one API surface.

The declared vocabulary is four keys — `repeat`, `flag`, `choices`, `help` — and stops
there. That ceiling is real and is recorded in §11.

`audience` is `agent | human | both`, and **it gates in both directions** — an earlier draft
of this paragraph defined only the first, which left `agent` and `both` meaning exactly the
same thing and made a third value that could never be observed. Phase 2 enforced both, and
that is the built behaviour (`main@06232d9`, `cli.py:926-935`):

- a `human` command called by a caller sb resolves to an agent is refused, and the refusal
  names the alternative (`sb block "..."`) — the same treatment `sb ask human` already gets
  (`broker.py:1026-1033`), and the same reason `sb board` is hidden;
- an `agent` command called by the human is refused too, pointing at
  `sb plugin <name> --help` for what is meant for them.

`both` is then the value that gates nothing, and the three are genuinely three. This is
declared once and enforced by sb rather than re-implemented (and eventually forgotten) per
plugin: C6, if it matters, make it impossible to skip.

What `audience` still has no vocabulary for, found by phase 4 building `todo`: **the caller's
own rows.** `drop` is `human`, so an agent can `add` a todo and then cannot withdraw it —
`done` would be a lie about what happened. "The human, or the agent that filed it" is not a
declarable audience, and inventing one for a single case would be worse than the gap. §11
records it.

`list` and `info` are reserved plugin names.

### 4.4 The handler surface

```python
def add(ctx, args) -> Result: ...

@dataclass(frozen=True)
class Context:
    api:       int
    name:      str           # the plugin's own name
    state_dir: Path          # sb created it; the plugin owns what goes inside
    repo:      Path          # the shared .git — the repo identity
    worktree:  Path          # this worktree
    agent:     str | None    # resolved caller; None means a human is typing
    json:      bool

@dataclass
class Result:
    ok:    bool = True
    human: str  = ""         # printed without --json
    data:  Any  = None       # printed with --json
    code:  int  = 0
```

What is **not** in `Context` is the contract: no `Broker`, no `Herdr`, no sqlite handle, no
access to another plugin's state. A plugin cannot spawn agents, read the message store, or
reach sb's internals through anything sb hands it. Spawn authority in particular stays
core — a plugin that can call `sb delegate` is both a privilege escalation and a fork bomb
waiting for a bad loop.

`Context` is scalars and paths, `Result` is scalars and JSON, `args` is a parsed namespace
built from a declarative spec. All three are JSON-serialisable. The day sb wants subprocess
isolation, the same handler signature works over a pipe and no plugin author changes a
line. That is decision 3's "do not preclude the escape hatch," satisfied by the shape of
the data rather than by building anything.

**`plugins.open_db` is not shipped, and the offer is withdrawn.** An earlier draft offered
one convenience, `plugins.open_db(ctx, schema)`, so that a plugin wanting sqlite in its own
state directory did not reimplement WAL + `busy_timeout` + `CREATE TABLE IF NOT EXISTS` —
and conceded in the same breath that neither shipped plugin uses it. Phase 2 declined to
build it on this document's own §9.3 precedent: F2 says do not ship a hook that does
nothing. The first plugin that actually wants sqlite can have it, and will be able to say
what shape it wants.

**Two things `Context` and `Result` do not carry**, both found by phase 4 building against
them, both recorded in §11 rather than fixed here:

- **A plugin cannot find sb's own checkout through anything sb hands it.** `report-bug`
  needs it for `git describe --always --dirty`, and the only `switchboard` module a plugin
  may import is `switchboard.plugins` — so it reaches `plugins.__file__` and walks up two
  parents. That is inside the letter of the rule and against its spirit: it recovers a
  filesystem fact by introspecting a module object, which is the coupling the rule exists to
  prevent. `Context` is scalars and paths and this is a path.
- **`Result` cannot carry a non-fatal warning.** `report-bug`'s herdr and git lookups can
  time out; the report is still filed and still correct, and there is nowhere to say
  "herdr version lookup timed out" beside a successful `Result`. `ok`/`human`/`data`/`code`
  expresses succeeded-with-a-note only by smuggling it into `human`, which then vanishes
  under `--json`. §6's `on_event` exists for exactly this shape of problem on the resolve
  path; handlers have no equivalent.

**Logging.** A plugin may append to sb's event log via `store.log_event(db, kind="todo.added",
…)` — already a generic `(agent, kind, JSON)` append log taking new kinds with zero schema
change (`store.py:638-650`) — so plugin activity shows up in `sb log` beside agent activity.
sb does this on the plugin's behalf at dispatch (one event per handler invocation: plugin,
command, ok/failed). Plugins get no database handle of their own.

### 4.5 Parser integration

`build_parser()`, `_validate()` and `_dispatch()` stay three static `if cmd == …` chains.
Dynamic registration at parse time would mean importing plugin code to print `sb --help`,
and `_tier_help()` already has to wrap a config read in a bare `except Exception` so that
`sb --help` outside a repo does not traceback (`cli.py:60-71`). One such hazard is enough.

```python
pl = cmd("plugin", help="run an installed plugin (see: sb plugin list)")
pl.add_argument("name", nargs="?")
pl.add_argument("rest", nargs=argparse.REMAINDER)
cmd("presets", help="list available presets")
```

`REMAINDER` keeps the top-level parser static, cheap, and unbreakable by anything on disk.
The plugin's own arguments are parsed *after* dispatch, by the subparser sb builds from the
registered spec — so deferral costs nothing in error quality.

**`_validate()` gains one branch, and that branch is the whole of level 3.** An earlier
draft described it as a cheap existence check — the plugin name exists and is enabled, and
`rest[0]` is a real command with a *did you mean* for near misses. It cannot be cheap:
answering "is `rest[0]` a real command" requires the `importlib` load and `register()` call,
and parsing the plugin's own arguments requires the subparser built from what `register`
declared. Doing that in `_validate` and again in `_dispatch` would import twice. So
`_validate_plugin` does the whole of it once and stashes the results on the argv namespace —
`args.plugin`, `args.command`, `args.pargs` (`main@06232d9`, `cli.py:381-434`) — and
dispatch reads them. This is not what the paragraph above described, and it is the right
shape: it keeps `cli.py`'s rule that arguments are checked at the boundary and nowhere else,
and it keeps level 3 confined to the `sb plugin …` path exactly as §4.2 requires.

**`sb --help` does not list plugin names.** An earlier draft claimed it did. It cannot,
without contradicting the argument three paragraphs above: listing them needs a glob of both
plugin roots at parser-build time, on every `sb` invocation including the ones that must
work outside a repo, which is precisely the disk-dependency that keeping the parser static
buys away. The claim is withdrawn rather than reconciled, because there is no reconciling
it — one of the two had to go and the static parser is worth more than the listing. `sb
--help` shows the `plugin` verb with `run an installed plugin (see: sb plugin list)`, and
`sb plugin list` is where names live.

### 4.6 Error isolation, stated as tests

All four run with `defaults/plugins/broken/__init__.py` containing `raise SystemExit(3)` at
module scope, and with `.switchboard/plugins.toml` enabling it.

1. Every level-0 verb in §4.2 runs to completion.
2. **Every level-2 verb** — `sb delegate`, `sb start`, `sb workspace new` — spawns normally
   with `@broken` bound. Level 2 is where the three spawn verbs live (§4.2), so this is the
   test that the topology actually holds, and it has to be all three: testing `delegate`
   alone would have passed on the day `start` was silently getting no bindings at all.
3. `sb plugin list` with that plugin present reports every *other* plugin correctly.
4. `sb plugin broken anything` exits non-zero with `sb: plugin 'broken' failed: …` and no
   traceback.

**The fixture is not an `Exception`, and the two wrappers deliberately differ.** `raise
SystemExit(3)` at module scope is a `BaseException`, so it slips straight through `except
Exception` — which means the four tests above only test anything if the import wrapper
catches `BaseException`. It does (`main@06232d9`, `plugins.py:399`, `:442`, `:472`). The
handler wrapper catches only `Exception` (`plugins.py:692`), and that is not an oversight:
§11.1 accepts that a handler calling `sys.exit()` exits sb, and catching `BaseException`
there would quietly convert a deliberate `sys.exit()` into a caught error — as well as
swallowing `KeyboardInterrupt`. The distinction is load-bearing and invisible from the type
names, so: **import is `BaseException`, invocation is `Exception`.** Both are commented at
the source.

Handler failures cannot be isolated — the handler *is* the command — but they surface as
`sb: plugin '<name>' failed: <msg>` on stderr and **exit 1**: the same rendering *and* the
same code `cli.main` already gives `ValueError`/`KeyError` (`main@2637b5f`,
`cli.py:438-440`).

**No exit code is reserved**, and this is a decision rather than an omission. An earlier
draft of this section claimed a reserved code "matching" that path; the path returns 1, so
reserving one would have been a departure from the cited precedent rather than a match to
it. sb has no reserved codes at all today — every failure path in `cli.main` returns 1 —
and minting one for this single error class would add a second machine-readable signalling
channel beside the one C13 actually specifies. The CLI *is* the API through `--json`, where
a failed handler is already `ok: false` with a reason; a caller that wants to distinguish
"the plugin broke" from "the argument was wrong" reads that, not `$?`. A plugin that wants
a non-zero code of its own still sets `Result.code` (§4.4) — that is the plugin's exit
status to spend. sb's own failures stay at 1.

**What in-process cannot protect against, plainly.** A handler that calls `sys.exit()`,
imports `switchboard.store` and writes to the database, leaks memory, or blocks forever
will do all of those to the sb process. Decision 3 trades that away knowingly. The
isolation claimed above is about import errors and handler exceptions — the common
failures, not the malicious ones.

**The internals-import check is NOT BUILT. This is an open item, not a deferral.** This
section says `sb doctor` flags a plugin importing anything from `switchboard` other than
`switchboard.plugins`, which is the check that catches the coupling that would foreclose the
future escape hatch. It is not among the four questions `doctor` actually answers (§5.6),
because it was not in phase 4's scope and because it needs source scanning rather than the
directory read the other four are. Phase 4 flagged it rather than deciding it, and so does
this reconciliation: **the document is right here and the implementation diverged**, which
is not a case to settle by editing the document.

The case for building it is stronger than it was when it was written, because it has already
had something to catch: `report-bug` reaches sb's checkout through `plugins.__file__`
(§4.4). That is inside the letter of the rule, so a naive check on the import statement
would still pass it — which is itself worth knowing before anyone writes the check. Pending
a decision, this paragraph is the record that the claim above describes intent and not code.

### 4.7 Versioning

`API = 1` is the contract version: the shape of `Context`, `Result`, the registry, the
`agent.md` convention. sb knows the set it supports; a plugin declaring an unsupported
`API` is reported `incompatible` by `sb plugin list` and `sb doctor`, and its commands
refuse. `VERSION` is the plugin's own semver, opaque to sb, shown in listings, and owned by
the plugin for its own state-format migrations.

There are no deprecation windows and no shims. If `Context` changes, you edit your two
plugins. This is the single-user assumption cashed in directly, and §11 records the trigger
that invalidates it.

---

## 5. State

### 5.1 Repo identity

> **A repo identity is the absolute path of its shared `.git` directory.**

`git rev-parse --git-common-dir`, anchored against the invocation cwd and resolved — which
is exactly `store.repo_root()` (`store.py:44-59`). The anchoring is load-bearing and
already commented in the source: resolving the bare relative result against the process cwd
hands back a different repo's directory.

| standing in | `worktree_root()` | `repo_root()` = identity |
|---|---|---|
| `~/Code/switchboard` | `~/Code/switchboard` | `~/Code/switchboard/.git` |
| `~/.herdr/worktrees/switchboard/plugins-redesign` | `…/plugins-redesign` | `~/Code/switchboard/.git` |

Three working trees, one identity, one todo list — which is decision 4's "global per repo
identity, shared across worktrees", with no new mechanism and no id string to generate or
collide. Consequences, stated rather than discovered later: every worktree of a clone
shares one list; two clones on one machine have two; a fork and its upstream have two; a
repo with no remote still has an identity.

Identifying a repo by first-commit hash or remote URL was considered and rejected: both
merge a fork's list into its upstream's, and remote URL leaves a remote-less repo with no
identity. More decisively, the shared-`.git` definition is *already* in force for
`state.db`, for `config.json`, and for the config symlinks. A second definition of "same
repo" beside the first is correct until someone relocates a `.git` and subtly wrong forever
after.

`Context` exposes both `repo` and `worktree` so a plugin picks consciously rather than by
accident.

### 5.2 Scope and paths

Two scopes. A plugin declares one with `SCOPE`; `repo` is the default.

| `SCOPE` | path | shared by |
|---|---|---|
| `repo` | `<shared .git>/agentflow/plugins/<name>/` | every worktree of this clone |
| `user` | `~/.local/state/switchboard/plugins/<name>/` | every repo on this machine |

Proposal B offered a third, `worktree` (`<worktree>/.switchboard/state/<name>/`). Cut:
nothing wants it, and a worktree-scoped store contradicts the shared-identity premise that
motivated the whole state design. It can be added later in one line.

sb creates the directory on first use and passes it as `ctx.state_dir`. **sb never reads
inside it.** The path is sb's; the contents are the plugin's.

### 5.3 Format is the plugin's

Because the access pattern differs and only the plugin knows it: `todo` is
read-modify-write (one JSON file), `report-bug` is append-only (one file per report, no
coordination needed at all). A plugin that genuinely needs indexed queries opens its own
sqlite file in its own directory with its own migrations, versioned by its own `VERSION` —
the independent versioning `state.db` cannot offer.

### 5.4 Not `state.db`

Two reasons, both in the store's own source. Cited against `main@2637b5f`, which rewrote
this machinery while this document was being verified — see the note below on what that
retired.

1. **A plugin's table is the one shape of schema change that cannot be migrated in place,
   and the store's answer to it is to drop `agents` and `messages`.** Compatibility is
   decided structurally by `_deficit` (`store.py:301-337`), which asks whether the store
   *contains* what this code needs. A missing **column** is `addable`: `_reconcile` ALTERs
   it in, re-stamps, and returns (`store.py:250-256`). A missing **table** is not — it is
   classified `blocking` outright, before its columns are even looked at
   (`store.py:318-320`) — and `_reconcile` falls through to `_reset`
   (`store.py:257-258`), which drops `agents`, `messages` *and* `events` and recreates them
   empty (`store.py:390-392`). Splice a `todos` table into `SCHEMA` and every pre-existing
   store in every clone loses its agent tree. **That is not a decision anybody weighs; it
   is the only branch there is.** A todo list must not be able to do that to the agent
   table.

2. There is **no extension point** — a plugin's table would have to be spliced into the one
   `SCHEMA` string inside `store.py` (`store.py:127-174`), which `_wanted()` then re-parses
   with a regex to learn what it wants (`store.py:284-298`). Nothing registers and nothing
   appends. This is the opposite of installable.

**The live-fleet deferral makes reason 1 worse, not better.** `_reset` refuses to run under
running agents, raising `LiveAgentsError` — and `_reconcile` swallows it (`store.py:257-260`),
leaving the old store open, serving, and deliberately *unstamped*, so the rebuild lands on
whichever `sb` runs after the last agent finishes (`store.py:232-247`; `schema_deficit`,
`store.py:263-277`). That is exactly right for the case it was built for. It is exactly
wrong as a safety net here: a plugin adding a table would not fail loudly at install time.
It would appear to work, for as long as the fleet was live, and take the tree when the
fleet drained.

**What this argument no longer rests on.** An earlier draft's first reason was that the
store is "documented disposable" and that a todo list vanishing when sb adds a column is
not a todo list. That was false — an added column is the paradigm case that *survives* —
and the docstring it quoted has since been deleted outright. The store's own framing has
moved with it: `_SCHEMA_HASH` now carries a comment demoting it to "a cache key, NOT a
version" (`store.py:176-182`), and `connect()` opens with "NEVER raises over a schema
change" (`store.py:201-210`). None of that rescues a plugin table. The hash was never the
threat; `_deficit`'s missing-table branch is, and it is unchanged by the rewrite. §5.4's
ruling is the same ruling it was, on evidence that is now the code's own.

The precedent for the alternative is immediately adjacent and survived the rewrite intact:
`config.json` lives *beside* the store in the same shared directory, deliberately not as a
table in it, because "the database is disposable by design and gets dropped on a schema
change, whereas this must survive that" (`store.py:82-88`, the sentence at `:85-86`).
Plugin state is that same argument with the same answer. No schema change, no reset, no
interaction with the live-agent guard.

### 5.5 Concurrency — sb owns the lock

sb takes an exclusive `flock` on `<state_dir>/.lock` around the handler call. A plugin sets
`LOCK = False` when it does not need one.

This is the payoff of sb owning the path: the two things naive authors get wrong — *where
does my data go* and *what happens when two agents write at once* — are both answered
before their code runs. It also dissolves the argument that a todo store must be sqlite:
the lost-write race between two concurrent `todo add` calls against a JSON file is what
sqlite was being reached for, and the lock removes it. Whole-file rewrite via tmp +
`os.replace` under the lock is then correct and is the simplest thing that works.

The lock is per state directory, so plugins never contend with each other, and it never
covers the delegate path (which does not run handlers).

**`LOCK = False` hands both questions straight back.** `report-bug` is genuinely lock-free —
one file per report, no coordination — and it still had to solve not-clobbering itself: two
agents filing the same words in the same second collide on a filename, so it opens with
`O_CREAT|O_EXCL`. One line and correct, but it is the second of the two things this section
claims sb answers before an author's code runs, and it comes back the moment `LOCK` is
false. Worth knowing before an author reaches for the flag: `LOCK = False` is not "I do not
need coordination", it is "I am doing my own."

### 5.6 Removal

**State directories are orphaned, never auto-deleted.** Removing a plugin — including by
`git pull` dropping a file from `defaults/` — must not delete data the user put there.
`sb doctor` reports:

```
orphaned plugin state: <shared .git>/agentflow/plugins/ci-check/  (no such plugin; rm -rf to discard)
```

Disabling a plugin does not touch its state either; re-enabling finds it intact. `rm` is
the only reset, and it is always the human's. Keyed on **available**, not on enabled: a
disabled plugin's directory is not orphaned, and reporting it would teach the wrong `rm`.

**`sb doctor` separates problems from notices, and only problems move the exit code.**
Decided in phase 4, because the four things §4.2, §4.6 and this section ask `doctor` to
report are not the same kind of thing:

| finding | kind | exit |
|---|---|---|
| a plugin that will not import | **PROBLEM** | 1 |
| a plugin targeting an unsupported `API` | **PROBLEM** | 1 |
| an orphaned state directory | note | unchanged |
| a plugin loaded from `.switchboard/plugins/` | note | unchanged |
| a pre-rename spelling still on disk (§8.2) | note | unchanged |
| a plugin importing sb internals (§4.6) | — | **not built; open** |

The two problems both mean a command an agent may have been *told to run* does not exist,
and incompatibility in particular is not caught at spawn time by design (§11 item 4), so
`doctor` is the only place either is visible before an agent trips over it. The three notes
are conditions somebody should know about and may perfectly well be choosing. An orphan is
permanent by construction — nothing ever deletes it — so letting one hold `sb doctor` at
non-zero forever would train everybody to stop reading the exit code, which is the only
thing it is for. This matches the existing rule that the code and the `ok` field can never
disagree: `ok` is false for problems and true when only notes are present.

---

## 6. Prompt reach

**A plugin's prompt contribution is `<plugin>/agent.md`: a static markdown file, injected
as `@<name>` when bound.** It is read, flattened by the same `config.flatten()` every
preset and role prompt already uses, validated by `validate.line()`, and appended to the
spawn. It is not declared anywhere and it is not computed.

```markdown
# todo
- This repo has a shared todo list, visible from every worktree. Run
  `sb plugin todo list` before you start so you do not redo something already filed.
- Work you notice but were not asked to do: `sb plugin todo add "…" --label found`.
- Never edit the store file directly; the CLI is the only writer.
```

Headings are dropped and bullets become `; `, so it reaches herdr as one line and the
no-newline constraint is satisfied by reusing the existing pipeline rather than by a new
rule anyone has to remember.

**Why static beats a `prompt(ctx)` hook called at spawn time.** Proposal A's hook could
return `None` on an empty list (costing zero tokens when irrelevant) and could vary by
role. Three reasons it loses anyway:

1. **A computed fragment is stale the instant it is written.** The system prompt is fixed
   for the agent's life. An agent spawned when the list was empty is told nothing, and then
   lives for an hour during which todos appear. The dynamic-ness buys a snapshot at the one
   moment it is least useful.
2. **It puts arbitrary code on the hot path with no timeout.** Every `sb delegate` would
   import every enabled plugin and call into it inside the spawn path. Proposal A
   acknowledged this and declined to bound it; there is no timeout, no instrumentation, and
   no signal on the day one plugin starts doing I/O in `prompt()`. Against that, the whole
   level-0/level-2 topology of §4.2 collapses — `delegate` becomes the verb most exposed to
   plugin failure rather than the verb most protected from it.
3. **The pull is the point.** Agents have a CLI; that is the premise of switchboard (C2 —
   the tooling carries the contract). A fragment naming the verbs is the contract. Pushing
   live rows into every system prompt is the other thing entirely, and it is the failure C4
   exists to prevent: an agent told there is a queue will work the queue instead of its
   task.

The honest cost is that agents skip instructions, and some fraction of a todo plugin's
value is lost to agents that never pull. That is real and is recorded in §11.

**Assembly position: unchanged.** `broker.delegate` assembles the system prompt as protocol
→ identity → workspace → (`--as` **or** role prompt) → `with_` entries
(`broker.py:897-907`; the same five lines at `main@06232d9`, `broker.py:1260-1270`,
where the last of them is now `_resolve_bindings`). Plugin fragments ride the existing
`with_` list, in resolution order, and get **no new slot**.

Proposal A argued for a dedicated position 2, immediately after the protocol, on the
grounds that a capability announcement is protocol rather than persona and should not be
displaceable by `--as`. The premise is factually wrong: `--as` replaces the *role prompt*
at position 4 and never touches `with_` at all, so fragments are already undisplaceable.
A new slot would buy nothing and would make `--with @todo` land somewhere other than where
the caller typed it.

**Budget.** New `[limits] plugin_fragment = 400`, against `prompt = 8000` for presets and
role prompts. `protocol.md`'s own header states the reason: everything it contains "is paid
for on every single spawn, by every agent, forever." Over-budget text is truncated at a word
boundary with an event logged, not rejected — a chatty plugin must not break spawning.

**The budget is enforced at spawn and nowhere at authoring time**, which phase 4 hit
immediately: its first `report-bug/agent.md` was 461 characters, and would have been clipped
on every spawn in every repo forever, logged as `fragment_truncated`, and read by nobody.
The mechanism cannot catch that — truncation is deliberately non-fatal — so **every shipped
fragment needs a test that it fits** (`test_every_shipped_fragment_fits_its_budget`). That
is a rule for whoever ships a third one, not a property of the design.

**Failure is asymmetric, on purpose — and the asymmetry has to be paid for.** A fragment
reached via a **binding** in `presets.toml` that fails to resolve is **skipped**, with one
line on stderr naming the plugin: delegation must not fail because somebody's todo plugin
is half-installed. A fragment named **explicitly** on the command line (`--with @todo`)
that fails to resolve is an **error** naming the plugin: you asked for it by hand, and
silently dropping it spawns an agent missing an instruction you believed it had.

Today nothing can tell the two apart. `for_role()` flattens the every-agent
bindings, the role's bindings, and the caller's `--with` into one undifferentiated
`list[str]` (`plugins.py:80-91`, pre-split — the module phase 1 renamed to `presets.py`),
and `resolve()` receives only that flat list
(`plugins.py:94-110`, same module). By the time resolution fails, how the name arrived is gone. This is
a real hole in the design, not a citation problem, and it is closed here rather than
discovered by whoever implements §6.

**The rule stands, and the provenance is preserved at the call site.** `for_role`'s return
type does not change. The caller already holds the explicit layer separately — it is the
`extra` argument it passed in one line earlier — so nothing has to be threaded through
anything. `resolve()` gains one keyword argument:

```python
presets.resolve(names, repo, explicit=frozenset(extra), on_event=…)
```

A name in `explicit` that fails to resolve raises; a name that is not is skipped with a
warning. There is exactly one production call site for each function, adjacent, in
`Broker._resolve_bindings` (`main@06232d9`, `broker.py:1124-1128`). The default is the
empty set, so every existing caller and every case in `tests/test_presets.py` is untouched
— and the empty set is the *correct* default, not merely a compatible one: a name nobody
typed is a binding.

**A second keyword, because a silent skip is only acceptable if something says so.**
`on_event` is the callback `resolve()` calls when it drops or cuts a fragment, and it is not
optional decoration: skipping is the whole point of the binding side of the asymmetry, so
without a report a spawn that lost a fragment its `presets.toml` says it should have had is
indistinguishable from one that never wanted it — the looks-like-success shape this document
legislates against everywhere else. Two kinds, and they are reported differently
(`Broker._fragment_note`, `main@06232d9`, `broker.py:1130-1145`):

- **`fragment_skipped`** — logged *and* one line on stderr naming the plugin. The spawn
  succeeds, which is the point of skipping, so this line is the only signal it happened.
- **`fragment_truncated`** — logged only. It is a note for whoever edits that `agent.md`
  next, and printing it on every spawn would train the reader to ignore both.

The callback is threaded from the broker rather than the CLI because that is where the
database handle already is, and because both keywords have to be passed at the one call site
or the behaviour is lost silently — see §0.

Both defaults are safe, which is the hazard: a caller that forgets `explicit=` gets skipping
for everything and a caller that forgets `on_event=` gets silence, and neither fails. The
merge nearly did exactly this. The behaviour is pinned by tests at the spawn path
(`cli.main("delegate", …)`), not at the resolver, for that reason.

Two things this pins down that the rule alone did not:

- **The dedupe tie-break.** `for_role` de-duplicates, so a name appearing both in a binding
  and on the command line resolves once. It counts as **explicit**. You typed it; a failure
  you can see beats a warning you cannot.
- **`extra`, not `--with`, is the definition of explicit.** Anything that reaches
  `delegate`'s `with_` was named by a caller. That is the property the rule is actually
  about, and it keeps holding for `sb start` and `sb workspace new`, which now reach
  `delegate` too (§4.2).

Dropping the asymmetry would have been cheaper still — one behaviour, no parameter. It was
rejected because the two cases genuinely differ, and because whichever single behaviour you
pick is wrong in one direction: erroring on everything means a half-installed plugin in
`presets.toml` stops the fleet spawning, and skipping everything means `--with @todo` can
silently do nothing. That second failure is the one §3.3's bare-name rule already exists to
prevent — a spawn that looks like success and ships nothing. One keyword argument is not a
price worth trading it for.

**Agent- vs human-facing.** Handled by `audience` on the command (§4.3), not by the
fragment. The fragment is the enumeration — an agent knows the verbs it was told about —
but enumeration is not enforcement, and anything destructive declares `audience="human"`.

---

## 7. Layering and bindings

### 7.1 What today's rule actually is

The current `plugins.py` docstring says plugin files are "not layered from `defaults/`."
The code says something more precise: `available()` **does** read `defaults/plugins/*.md`
on every call (`plugins.py:49-63`), so all six shipped presets are nameable from any repo
whether or not that repo has a `.switchboard/plugins/` directory at all. What is absent is
two other things — no shipped file is ever *written into* a repo's directory, and
`defaults/plugins.toml` ships `all = []` with an empty `[roles]`, so nothing shipped is
ever *applied* unless bound or named by `--with`.

So the historically accurate statement of the rule is:

> **Shipping makes something available. Only a binding makes it applied.**

Both proposals converged on this reading independently and both are right; the survey's
own summary ("plugin files are NOT merged from `defaults/` into every repo") overstates it,
even while the same document notes two paragraphs later that a repo with no plugin
directory still gets every shipped plugin by name. The guarantee the original decision was
protecting — a shipped behaviour arriving in every repo and having to be argued back out —
is about binding, not discovery.

### 7.2 Going forward: three states

That reading is still right and it generalises to plugins with one extra state, because a
plugin owns state and adds CLI surface where a preset owns neither.

| state | means | set by |
|---|---|---|
| **available** | sb can see it and describe it | present in either root |
| **enabled** | its commands dispatch; its state dir is created | `enabled` in `plugins.toml` |
| **bound** | its `@<name>` fragment is injected into spawns | `presets.toml` bindings |

Enabled and bound are separate, and the split is load-bearing: you can use `sb plugin todo`
yourself without every spawned agent being told about it — a directory versus a permanent
per-spawn context tax, which are not the same decision. Proposal A collapsed them by making
a plugin's fragment automatic on enable; that forecloses the cheaper of the two options
forever, for the sake of one fewer concept. C0 decides it.

The cost is honest: the difference between "enabled" and "bound" will need explaining more
than once.

### 7.3 The files

```
defaults/presets/*.md               shipped preset text            (moved from defaults/plugins/)
defaults/presets.toml               shipped bindings: all, [roles]  (moved from defaults/plugins.toml)
defaults/plugins/<name>/            shipped plugin packages
defaults/plugins.toml               shipped enablement: enabled = [...]   (§7.4)

.switchboard/presets/*.md           this repo's presets    — file replaces shipped, per stem
.switchboard/presets.toml           this repo's bindings   — array-JOIN onto shipped
.switchboard/plugins/<name>/        this repo's plugins    — dir replaces shipped, per name
.switchboard/plugins.toml           this repo's enablement — array-JOIN onto shipped
```

Both TOML files use the existing `config.merge()` semantics — tables merge key-by-key,
arrays join base-first de-duplicated, `"!reset"` as the first element discards the base
(`config.py:170-211`). No third merge rule is introduced. Both directories use the existing
override-by-name, last-write-wins rule.

### 7.4 Shipped defaults: everything on

**Both shipped plugins are enabled and bound out of the box.**

```toml
# defaults/plugins.toml
enabled = ["todo", "report-bug"]

# defaults/presets.toml
all = ["@todo", "@report-bug"]
[roles]
```

An earlier draft of this document shipped both lists empty, reasoning from the §7.1
guarantee that a shipped `todo` enabled by default means every repo you touch silently
grows a todo database. **That reasoning was overruled, and correctly.** It is an argument
about *other people's* repos. sb has one user, building only the things he actually needs;
every repo he touches is a repo he wants a todo list in. An off-by-default plugin that its
only user turns on in every repo is a line of ceremony, not a guarantee — and the "argued
back out" hazard §7.1 protects against requires someone to argue with.

**The mechanism is unchanged — only the default flips.** All three states in §7.2 remain
distinct and separately settable, because the argument for the split never depended on
which way they defaulted: enabling costs a directory, binding costs context on every spawn
forever, and those stay different decisions with different costs whether or not both start
true. Concretely, a repo can still take exactly one of them:

```toml
# .switchboard/presets.toml — use `sb plugin todo` yourself; stop taxing every spawn
all = ["!reset"]
```

```toml
# .switchboard/plugins.toml — turn a plugin off entirely
enabled = ["!reset"]
```

Both are the existing `config.merge()` escape hatch, not new machinery. Collapsing three
states into two would have made the first of those impossible to express.

The consequence to be clear-eyed about: from this release, **every agent spawned in any
repo carries both fragments**, and any repo where sb runs a plugin command grows a state
directory under its shared `.git`. That is the intent, it is a change from today's
zero-shipped-bindings behaviour, and it is listed as a user-visible change in §8.1.

---

## 8. Migration

### 8.1 Every user-visible break

| # | break | severity |
|---|---|---|
| 1 | `sb plugins` is a hard error for one release, then removed. Replaced by `sb presets` and `sb plugin list`. | **breaking, deliberate** |
| 2 | The `--json` key `plugins` becomes `presets`, renamed together with the verb so the two can never disagree. No consumer exists today (§3.2). | **breaking, no known consumer** |
| 3 | `--with <name>` where `<name>` matches an enabled plugin and no preset file is now an error directing you to `@<name>`. Previously it passed through as the literal one-word instruction. | **breaking, narrow, intentional** |
| 4 | `--with @<anything>` is now reserved and errors if unresolvable. Previously `@foo` would have passed through as a literal instruction. | **breaking, no known use** |
| 5 | **Every spawn's system prompt changes.** `defaults/presets.toml` ships `all = ["@todo", "@report-bug"]`, where today it ships `all = []` and nothing is bound to anything. Every agent in every repo now receives two extra fragments (≤400 chars each) it did not receive before. | **behaviour change, deliberate** (§7.4) |
| 6 | **Repos grow plugin state directories.** Both plugins ship enabled, so `<shared .git>/agentflow/plugins/todo/` is created the first time a todo command runs in a repo, and `~/.local/state/switchboard/plugins/report-bug/` the first time a bug is filed. Neither existed before; neither is created merely by `sb delegate` or `sb status`. | **new on-disk state, deliberate** (§7.4) |
| 7 | `sb ask human` → `sb block` in **both** presets that name a dead command: `ask-dont-guess.md` ("Use `sb ask human "<what you need>"`") and `report-bug.md` ("If the bug blocks you entirely, run `sb ask human` instead"). Two files, one fix. | content fix |
| 8 | `report-bug.md` text changes to point at the plugin. Row 7's fix lands inside this rewrite, but is listed separately because it is owed either way. | content fix |
| 9 | Three tests fail by construction and must be updated with the change: `tests/test_status.py:750` (asserts the exact verb set), `tests/test_validate.py:253` (argv samples), `tests/test_config.py:345` (module list contains `"plugins"`, which is now a different module). | internal |

Everything else is non-breaking:

| change | breaking? |
|---|---|
| `--with <preset>`, unknown-bare-name-is-literal | **no** — untouched for every name that is not an enabled plugin |
| `defaults/plugins/*.md` → `defaults/presets/*.md` | no — shipped-side move; discovery reads both |
| `.switchboard/plugins/*.md` → `.switchboard/presets/*.md` | no — both read during transition |
| `plugins.toml` with `all`/`[roles]` → `presets.toml` | no — read as bindings, warned |
| `[paths] plugins_dir`/`plugins_file` → `presets_dir`/`presets_file` | no — but **not** by the mechanism this row first claimed; see below |
| `switchboard/plugins.py` → `switchboard/presets.py`; new `switchboard/plugins.py` is the loader + API | no — internal |
| `state.db` and its schema | **unchanged** — no schema-hash bump, no reset |
| `Broker.delegate` assembly order, `flatten`, `validate.line`, herdr | **unchanged** |

**The `[paths]` fallback is path-level, not key-level.** This table first said "old keys read
as fallback", meaning: read `presets_dir`, and if that key is unset fall back to reading
`plugins_dir`. Phase 1 found that this does not work, and fails in the silent direction. A
repo carrying the old layout sets **no `[paths]` key at all** — it inherits both from
`defaults/`, where the new key is now present and populated — so a key-level fallback never
fires, sb reads the new key, finds the directory it names absent, and that repo's presets
vanish with no error.

What is needed is §8.2's rule applied to the path rather than to the key: resolve the new
path, and use the old **only if the new one is not on disk**. That is what ships, as
`config.path_for_legacy(new_key, old_key, repo)` (`main@06232d9`, `config.py:96`), keyed on
what is actually there. Same conclusion — the row stays non-breaking — reached by a
mechanism that works. The general lesson, worth keeping: **a fallback keyed on configuration
cannot see a repo that never configured anything.**

### 8.2 There is no flag day

`.switchboard/plugins/` must stop meaning "prompt files" and start meaning "code packages,"
but the two are trivially distinguishable *by shape*: presets are `*.md` **files**, plugins
are **directories** containing `__init__.py`. During the transition sb reads both spellings
out of `.switchboard/plugins/` with no ambiguity, and `sb doctor` reports the deprecation
with the exact `git mv`. Same for the TOML: a `plugins.toml` containing top-level `all` or
`[roles]` is a pre-rename bindings file — sb reads it as such, warns, and never mistakes it
for enablement. A file containing both parses correctly, because the keys are disjoint.
There is no moment at which a repo is broken and no version of sb that understands only one
spelling.

### 8.3 The six presets

Content unchanged, directory moved, with two exceptions:

1. **The `sb ask human` bug is fixed in the move — in both files that carry it.**
   `Broker.ask()` refuses `sb ask human` outright, pointing at `sb block`
   (`broker.py:1026-1033`). **`ask-dont-guess.md`** ends with "Use `sb ask human
   "<what you need>"`". **`report-bug.md`** ends with "If the bug
   blocks you entirely, run `sb ask human` instead" — the identical dead command, and an
   occurrence an earlier draft of this document missed. Every agent that ever received
   either preset was told to run a command that errors. Both proposals flagged the first
   and neither fixed it; neither noticed the second. Two one-line content edits, inside a
   change already touching both files. `report-bug.md`'s rewrite in point 2 would sweep it
   up incidentally — it is called out anyway, because a reader working from §8.1 row 7
   should not fix one file and leave the other.
2. **`report-bug.md` is repointed, not deleted.** Its text becomes the same guidance as the
   plugin's `agent.md`. It is **not** deleted, because deleting it makes an existing
   `--with report-bug` degrade silently into the literal one-word instruction
   `"report-bug"` — a spawn that looks fine and ships nothing. (It is not caught by the
   §3.3 error rule either: that rule fires only when a bare name matches an enabled plugin
   *and* no preset file, which is precisely why keeping the file is safe.) Two texts saying
   the same thing is a small redundancy, recorded in §11 as deferred cleanup.

### 8.4 A repo's own copies of shipped presets are deleted

**Decided in phase 4; the design had never said.** This repo's `.switchboard/presets/` held
byte-identical copies of all six shipped presets. Under §7.1's discovery rule a repo's
`<name>.md` replaces the shipped one wholesale, so those copies were not additive — they
were shadowing the files they were duplicates of.

**They are deleted.** The rule going forward: *a repo keeps a preset file only where it
differs from the shipped one.*

The argument is not tidiness. It is that this exact duplication had already cost a fix: the
`sb ask human` bug of §8.3.1 had to be repaired twice, in two files, because the repo's copy
was the one actually being read. Phase 4 reproduced it immediately — repointing
`defaults/presets/report-bug.md` at the plugin (§8.3.2) changed nothing at all in this repo,
because `.switchboard/presets/report-bug.md` was still winning and still telling agents to
append to `BUGS.md`. A silent second place for a bug to hide is not a backup; it is the
thing that makes the fix look applied when it is not.

Nothing depended on them. `presets.available()` reads `defaults/presets/` on every call, so
all six stay nameable from this repo and from any other, and `.switchboard/presets.toml` —
which is *not* a duplicate, and stays — keeps binding them exactly as before. The deletion
is invisible except that there is now one file per preset.

Note for whoever reads this from another checkout: `.switchboard/` in a worktree is a
symlink into the main clone, and it is untracked. The deletion is therefore not in any
commit and cannot be reverted with git. The correct restore, if one is ever wanted, is to
copy the file back out of `defaults/presets/` — which is the whole point.

---

## 9. `todo`

Per decision 4: humans and agents equally, deliberately dumb, a store and nothing more,
global per repo identity, no `sb status` work.

```
defaults/plugins/todo/{__init__.py, agent.md}
SCOPE = "repo"   LOCK = True
state: <shared .git>/agentflow/plugins/todo/todos.json
ships: enabled, and @todo bound to every agent  (§7.4)
```

### 9.1 Commands

```
sb plugin todo add "<text>" [--label L]... [--state S]   both
sb plugin todo list [--state S] [--label L]... [--all]   both
sb plugin todo show <id>                                 both
sb plugin todo done <id> [--note "…"]                    both
sb plugin todo drop <id> [--note "…"]                    human
```

Every command emits JSON under `--json`, for free, from `Result`.

**Two flags this list did not have before phase 4 built it**, both forced by §9.2 rather
than wanted for their own sake:

- **`add --state`.** Without a write path, the open vocabulary of §9.2 is decorative:
  `list --state blocked` would filter on a word nothing in the system can ever produce, and
  "`--state blocked` works the day you want it" would be false on that day. The only two
  states any verb could otherwise write are the two `done` and `drop` write. One flag on an
  existing command was preferred to a sixth verb.
- **`list --all`.** The default list has to hide closed todos or it stops being a list, and
  the filter it uses is **structural — `closed_at` is null — not a word**. Keying it on
  `state == "open"` would have quietly re-closed the vocabulary: a todo filed `blocked`
  would have vanished from the bare `list`, and a vocabulary that is open only to an
  explicit `--state` is not open. `--all` is how you see the closed ones.

Neither widens the four-key arg spec of §4.3; both are `reg.arg` with `help` and,
for `--all`, `flag`.

### 9.2 The record

```json
{"id": "t-7", "text": "…", "labels": ["config"], "state": "open",
 "created_by": "orchestrator", "created_at": 1754570000,
 "closed_at": null, "note": null}
```

- Ids are `t-<n>`, monotonic, **never reused**, so a commit message citing `t-7` stays
  true.
- `created_by` is `ctx.agent`, or `"human"`. It is provenance, not assignment.
- `state` is **open vocabulary**, not a closed enum: shipped values are `open`, `done`,
  `dropped`, and `--state blocked` works the day you want it. C12 is explicit that no
  closed enum of statuses or labels is permitted — the named failure is a shipped system
  whose role vocabulary became a Go enum and whose every add-one request was closed
  unimplemented. `--state` therefore declares no `choices`.
- Labels are a list on the record. At hundreds of rows on one machine, nothing more is
  warranted.
- The whole file is rewritten via tmp + `os.replace` under the lock sb holds (§5.5).
- **`drop` writes `state: "dropped"`; it does not delete the row.** §4.3's registration
  sketch helps it as "delete a todo outright" and this paragraph names `dropped` as a
  shipped state value; phase 4 had to pick one. Marking wins on the same argument that
  buys the never-reused counter three lines above: a deleted `t-7` makes a commit message
  citing `t-7` cite nothing, and `dropped` would otherwise be a word that never appears
  anywhere. `done` and `drop` are then the same operation with different words on it, and
  the difference between them is *finished* versus *not going to happen* — which is why
  `drop` is the human's and `done` is not.
- `next_id` is a stored field rather than `max(id) + 1`, so that a human editing the JSON
  by hand and deleting a row cannot make the next `add` mint a number somebody has already
  written down. It is floored by `max(id) + 1` on read, so a file that lost the counter is
  still monotonic — just no longer proof against that particular hand-edit.

### 9.3 What it deliberately is not

**No `claim`/`release`, no `owner`, no assignment, no spawning.** Proposal B included
claiming and a fragment instructing agents to "check what you are about to do is not
already claimed" and to "claim before you start." Rejected: that turns a store into a work
queue, and a work queue is a scheduler. Decision 4 says *deliberately dumb*. C8 says
decisions belong in a task string, not diffused into every agent's system prompt; C4 says a
worker holds its own problem. An orchestrator reads the list and delegates — which is an
orchestrator doing its job, not a feature of the todo plugin.

**Nothing is reserved for `sb status`.** Decision 4 puts it out of scope, and the design
leaves it possible in the cheapest way available: adding a third optional module-level
function to the loader later is one line. Proposal B reserved a `summary(ctx)` name that
nothing calls; rejected on the F2 precedent — a system whose custom templates were parsed,
merged, and printed but never executed, costing a user half a day. Do not ship a hook that
does nothing.

### 9.4 Fragment

Per §6, and note what it does *not* say: it does not tell agents to work from the list.

---

## 10. `report-bug`

Per decision 5: whichever is simplest, files on disk, no GitHub.

```
defaults/plugins/report-bug/{__init__.py, agent.md}
SCOPE = "user"   LOCK = False
state: ~/.local/state/switchboard/plugins/report-bug/
ships: enabled, and @report-bug bound to every agent  (§7.4)
```

```
sb plugin report-bug file "<what broke>" [--command "…"] [--expected "…"] [--actual "…"]   both
sb plugin report-bug list                                                                   both
sb plugin report-bug show <id>                                                              both
sb plugin report-bug drop <id>                                                              human
```

**One markdown file per report**, named `2026-08-07-143022-<slug>.md`. No index, no
database, no dedup, no locking — two agents filing at once write two different files.
Greppable, readable by anything, and `list` is a directory listing. Nothing is
deduplicated; the same bug filed three times is three files, and three files is itself the
reproduction signal. Not designing dedup is the simplest thing, which is what the decision
asked for.

**User scope, not repo.** A bug in switchboard is a fact about switchboard, not about
whichever repo you were standing in when you hit it. Repo-scoped, you would file three bugs
in three repos and find none of them later. The repo and worktree paths are still recorded
*in the file* — the context is useful, the partitioning is not.

**And `list` takes no repo filter**, which phase 4 built one of and then deleted. A
this-repo-by-default view is the same failure re-introduced one level up: it is not that the
reports were partitioned, it is that you cannot see the ones you filed elsewhere, and a
default that hides them does exactly that. The repo each report came from is on the row.

**`drop` deletes the file**, unlike `todo drop`, which marks. The two are different because
the things are: a todo is a ledger row that a commit message may cite by id, and a bug
report is a file. Nothing cites a report by id except the person holding the listing.

Proposal A instead resolved sb's own checkout (`Path(switchboard.__file__).parent.parent`,
then `store.repo_root()` from there) so reports land in sb's source tree ready to commit,
falling back to `~/.config/switchboard/bugs/` if sb was copied rather than cloned. Rejected:
it depends on sb being a clone, it has two behaviours depending on how sb was obtained, and
`sb plugin report-bug list` under user scope answers the same question more reliably.

**Auto-captured**, because it is cheap and deterministic: sb's version
(`git describe --always --dirty` of sb's own checkout — `--dirty` matters, since most
reports will be against uncommitted work), herdr's version, python, platform, the repo and
worktree the bug was hit in, and the calling agent from `ctx`. Everything narrative comes
from the caller.

**No transcript capture.** A Claude Code transcript (`store.transcript_path()`,
`store.py:668-678`) contains everything the agent read. Hoovering that into a bug report by
default is a data-exfiltration shape even with no publishing step, and it is not needed to
make the simple thing work.

This supersedes the `report-bug` preset, which currently tells agents to append to
`BUGS.md`; per §8.3 the preset stays and its text is repointed.

---

## 11. Open risks and what is knowingly deferred

**Accepted, per decision 3:**

1. **No sandbox.** In-process Python has the full authority of your shell. A handler that
   calls `sys.exit()`, writes to `state.db`, or blocks forever does it to sb. The
   level-0/level-2 topology is a good approximation of a process boundary for *accidents*
   and no defence at all against *intent*. Since all plugins ship in `defaults/` today, the
   threat model is "sb's own source," which is the same trust as `bin/sb`.
2. **Python-only in practice.** A Go or bash plugin needs a Python shim. §4.4 keeps the
   *contract* portable; it does not keep portable the plugins you will have written by
   then.

**Deferred, with the trigger written down:**

3. **`API = 1` detects a break and does nothing about one.** Changing a `Context` field
   breaks every plugin at once with no deprecation period. Correct for one user with two
   plugins, wrong for anything else.
4. **API incompatibility is not enforced at spawn.** Because `delegate` never imports
   (§4.2), a bound fragment from an incompatible plugin is still injected, and the agent
   discovers the problem by running a command that refuses. `sb doctor` reports it. The fix
   if this ever bites is a fourth state, not a fourth layer.
5. **The declarative arg spec has a ceiling.** Four keys covers `todo` and `report-bug`
   comfortably and will not cover the first plugin wanting mutually-exclusive groups or
   nested subcommands. The honest answers then are "make it two commands" or "widen the
   spec," and the second starts the slide toward reimplementing argparse in data.
6. **Static fragments trade responsiveness for isolation.** Agents must *choose* to run
   `todo list`, and agents skip instructions. Some real fraction of the plugin's value is
   lost to agents that never pull. The trade is right; it is not free.
7. **Fragments are a permanent context tax with one-directional pressure**, and as of §7.4
   it is being paid from day one: both shipped plugins are bound by default, so two
   fragments × 400 chars go into every spawn in every repo forever. The cap is a
   mitigation, not a fix; nobody ever deletes a sentence from a plugin fragment. If spawn
   prompts start feeling bloated, `all = ["!reset"]` in a repo's `presets.toml` is the
   lever, and the enabled/bound split exists precisely so pulling it does not also take
   away `sb plugin todo`.

8. **Default-on is right for this user and wrong for the next one.** §7.4 flips both
   plugins to enabled and bound because sb has exactly one user, who wants both in every
   repo he touches — so the ceremony of turning them on has no one to protect him from.
   That reasoning does not survive its own premise: the moment plugin code arrives from
   somewhere other than sb's own `defaults/`, or a second person installs one, default-on
   means a repo you cloned decides what goes into your agents' prompts and what appears
   under your `.git`. **Revisit at the same trigger as the rest of the stance** (below) —
   the flip back is two lines in `defaults/`, and the three-state mechanism that makes it
   expressible is deliberately kept intact for exactly this reason.
9. **No handler timeout.** A handler that hangs hangs `sb plugin …`. It cannot hang
   `delegate` or `status`, which is the part that mattered.
10. **`flock` semantics on network filesystems are not guaranteed.** Both the state root and
   the repo are local in every case that exists today.
11. **Durable state sits beside disposable state.** `<shared .git>/agentflow/` holds both
    the droppable `state.db` and non-droppable plugin directories, distinguished only by
    path. A fresh clone has no todos.
12. **Two texts will say where bugs go** — the repointed `report-bug` preset and the
    plugin's `agent.md` — until the preset can be removed without the silent-degradation
    hazard of §8.3.
13. **Plugin tests.** Shipped plugins live inside sb's own repo, so `tests/` can import them
    with the same `sys.path` arrangement `bin/sb` already uses; they are testable today.
    Out-of-repo third-party plugins would have no test story, and none exist.
14. **`sb status` surfacing** — out of scope per decision 4, one line in the loader when
    wanted.

**Found by building against the contract, and deferred rather than fixed** — all four are
gaps in `Context`/`Result`/`audience` that only appeared once two real plugins existed. Each
has exactly one instance today, which is why none of them is worth a contract change yet;
the second instance of any of them is the trigger:

15. **A plugin cannot get sb's own checkout from `Context`** (§4.4). `report-bug` recovers it
    from `plugins.__file__`. If a second plugin wants sb's version, put the path in
    `Context` — it is a path, which is what `Context` is made of.
16. **`Result` has no non-fatal warning channel** (§4.4). Succeeded-with-a-note is
    expressible only by smuggling it into `human`, where `--json` then drops it. The shape
    of the fix is known: handlers want what §6's `on_event` gives the resolve path.
17. **`audience` cannot say "the human, or the agent that filed it"** (§4.3). An agent can
    file a todo and cannot withdraw it. Adding a fourth audience for one case would cost
    more than the gap does.
18. **The fragment budget has no authoring-time check** (§6). Every shipped fragment needs
    its own test that it fits; the mechanism truncates silently by design and cannot tell
    an author before the fact.

**Open, and NOT deferred — awaiting a decision:**

19. **§4.6's `sb doctor` check for a plugin importing `switchboard` internals is not built.**
    This document asserts it; `doctor` does not do it. It is the check that would have
    caught item 15, and item 15 also shows that the obvious implementation — scanning import
    statements — would not have caught it, since `report-bug` imports only
    `switchboard.plugins`. It is recorded here so that its absence is a decision someone
    makes rather than a claim nobody checked. §4.6 carries the full note.

**The trigger to revisit the whole stance:** five plugins, or the first person who is not
you wanting to install one. At that point `API` needs a real policy, plugin code needs to
come from somewhere other than the repo you are standing in, and the out-of-process hatch
§4.4 keeps cheap gets built. Writing the trigger down is the only defence against noticing
it three plugins late.

---

## 12. Appendix — where A and B disagreed, and how each was resolved

| # | axis | A | B | ruling |
|---|---|---|---|---|
| 1 | `sb plugins` | keep the string for the new meaning, footer for one release | retire outright, hard error naming both replacements | **B**, on different grounds than B gave — see below |
| 2 | `--json` consumers | claimed the repurposed key is a trap | claimed a script would silently read the wrong list | **both overstated**; there are no consumers (§3.2). Ruling stands on decision 1's wording and on plural/singular ambiguity |
| 3 | load model | import in-process, try/except, content-hash trust gate | four layers, `ast.parse` for constants, delegate never imports | **B's topology, A's mechanism**: adopt "delegate never imports," drop `ast.parse` (§4.2) |
| 4 | trust gate | content-hash pin + `sb plugins --trust` | none | **neither** — A's own justification (repo code running on `delegate`) is void once `delegate` stops importing. Cut; `enabled` empty is the defence (§4.2) |
| 5 | registration | `main(ctx, argv)` + `nargs=REMAINDER` | `register(reg)` with declarative arg specs | **B** — uniform `--json` is C13, flag-level errors are `cli.py`'s stated property (§4.3) |
| 6 | audience gating | convention: the verb checks `ctx.me` in its own words | `audience=` declared, enforced by sb | **B** — C6, make it impossible to skip |
| 7 | help text | module docstring first line | `SUMMARY` constant | **A** — one fewer name, and sb imports on those paths anyway |
| 8 | state layout | one sqlite file per plugin | one directory per plugin, format the plugin's | **B** (§5.3) |
| 9 | concurrency | use sqlite, it handles it | sb `flock`s the state dir around the handler | **B** — answers the question before the author's code runs, and covers append-only plugins too (§5.5) |
| 10 | todo storage | sqlite, because concurrent `add` against JSON is a lost-write race | one JSON file | **B** — the race is real and the sb-owned lock removes it (§5.5) |
| 11 | scopes | one (`repo`), compute your own if you need more | three (`repo`/`user`/`worktree`) | **split**: two (`repo`, `user`). `worktree` cut as unused; `user` kept because `report-bug` needs it (§5.2) |
| 12 | state on removal | "`rm` is the reset" | not addressed | **neither** — orphan, never auto-delete, `sb doctor` reports (§5.6) |
| 13 | layering, historically | "inert until named"; the survey overstates today's rule | "shipping makes available, binding makes applied" | **agreed and both correct**; the survey's summary is the imprecise one (§7.1) |
| 14 | layering, going forward | two states, fragment automatic on enable | three states (available/enabled/bound) | **B** — enabling and binding have different costs; collapsing them forecloses the cheap option (§7.2) |
| 15 | shipped enablement | `enabled = []` | `enabled = ["todo", "report-bug"]` | **B, by human decision.** This doc first ruled A (B contradicted its own "no repo silently grows a todo database"). Overruled: that hazard is about other people's repos and sb has one user, who wants both plugins everywhere. B reached the right default from an argument that did not apply. Both plugins now ship enabled *and* bound; the three-state mechanism is untouched (§7.4) |
| 16 | prompt reach | `prompt(ctx)` hook at spawn, may return `None` | static `agent.md`, agent pulls via CLI | **B** — a spawn-time snapshot is stale immediately, and the hook puts unbounded code on the hot path (§6) |
| 17 | fragment position | new slot at position 2, after protocol | rides the existing `with_` list | **B** — A's premise is factually wrong; `--as` never displaces `with_` (§6) |
| 18 | fragment budget | `[limits] plugin_prompt = 400`, truncate + log | no cap | **A** (§6) |
| 19 | plugin↔`--with` | plugins deliberately not `--with`-able | `@name` sigil, bindable and `--with`-able | **B** — one bindings file, one mechanism (§3.3) |
| 20 | bare name colliding with a plugin | n/a (no sigil) | identified as "a failure that looks like success," declined to fix | **neither** — make it an error naming the sigil (§3.3) |
| 21 | top-level alias (`sb todo`) | none | opt-in per repo | **A** — B conceded in its own costs that it undermines the namespace argument (§3.3) |
| 22 | todo: claim/assign | none; a store, not a queue | `claim`/`release`/`owner` | **A** — decision 4 says deliberately dumb; C4/C8 (§9.3) |
| 23 | todo: state values | open vocabulary | exactly three | **A** — C12 forbids closed enums of statuses (§9.2) |
| 24 | todo: ids | plain `id` | `t-<n>`, monotonic, never reused | **B** — a commit citing `t-7` stays true (§9.2) |
| 25 | `sb status` door | leave it open by leaving it out | reserve `summary(ctx)`, call nothing | **A** — F2: do not ship a hook that does nothing (§9.3) |
| 26 | report-bug: where | sb's own checkout via `switchboard.__file__`, fallback `~/.config` | `SCOPE = "user"` | **B** — A's is fragile and has two behaviours (§10) |
| 27 | report-bug: storage | one file per report | one file per report | **agreed** (§10) |
| 28 | report-bug: transcripts | not captured | not captured | **agreed** (§10) |
| 29 | fate of the `report-bug` preset | delete when the plugin is enabled | keep, repoint the text | **B** — deleting degrades `--with report-bug` to a one-word literal (§8.3) |
| 30 | `sb ask human` bug in the presets | flagged in `ask-dont-guess.md`, not fixed | same, not fixed | **neither** — fix it in the move, and in `report-bug.md` too, which carries the same dead command and which neither proposal noticed (§8.3) |

**On the brief's framing of axis 1.** The brief states that A retires `sb plugins` and B
reuses the string. It is the other way round in the documents as written: proposal A §1
reuses `sb plugins` for the code-plugin lister with a pointer footer and calls it "the only
user-visible break in the whole proposal"; proposal B §1 retires it outright with a hard
error. The adjudication above judges the documents. The `--json`-consumer claim the brief
attributes to A belongs to B, and it is the claim that does not survive contact with the
code.

**On grafting.** No axis was averaged. Rows 7, 15, 18, 21 and 25 graft an idea from A into
a frame B won; rows 3 and 11 take structure from one and mechanism from the other. Rows 4,
12, 20 and 30 are cases where both proposals were wrong and the ruling is a third answer.
