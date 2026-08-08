# Proposal B — explicit contract, in-process, layered

Design only. Reworked against `decisions.md`, which is binding.
Where the human's decisions conflicted with my assigned stance, the decisions win; where
they left room, the rigor went into the registration API, the layering, versioning, and
error isolation.

**Nouns, fixed by decision 1:** a **preset** is prompt text (`sb delegate --with X`); a
**plugin** is Python that sb imports (`sb plugin todo add …`).

The one idea the whole design hangs on:

> A plugin is answered in **four layers of increasing cost** — glob it, read its constants
> without executing it, import it, call it — and every sb verb uses the cheapest layer that
> answers its question. `sb delegate` never gets past layer 2.

That is how I keep an explicit contract without a manifest DSL (decision 3 forbids one),
and how a broken plugin still cannot break the verbs that matter.

---

## 1. Naming, and what happens to `sb plugins`

| concept | is | lives in | reached by |
|---|---|---|---|
| **preset** | one markdown file, pure prompt text | `defaults/presets/`, `.switchboard/presets/` | `--with adversarial`, `presets.toml` bindings |
| **plugin** | a Python package with a state dir | `defaults/plugins/<name>/`, `.switchboard/plugins/<name>/` | `sb plugin todo add …` |

**`sb plugins` is retired outright, not repurposed.** It is replaced by two commands:

```
sb presets        list prompt fragments        (what `sb plugins` does today)
sb plugin list    list installed code plugins  (new)
```

and `sb plugins` itself becomes an error for one release:

```
$ sb plugins
sb: `sb plugins` has been split. Prompt fragments are now `sb presets`;
    code plugins are `sb plugin list`.
```

This is the only genuinely breaking change in the proposal and it is deliberate. The
tempting alternative — keep `sb plugins` and point it at the *new* meaning — would hand a
`--json` caller the key `plugins` with entirely different contents. A script that parsed
`{"plugins": ["adversarial", …]}` would keep running and start reading the wrong list.
This codebase already engineers against exactly that class of silent divergence (the
`--live`/`--active` and `--all-idle`/`--include-kept` aliases share one dest specifically
so "the two can never disagree", `cli.py:157`, `cli.py:190`). An error that names both
replacements costs one lookup, once. Silent wrong data costs a debugging session.

`sb presets` emits `{"presets": [...], "all": [...], "roles": {...}}` — key renamed with
the command, so the two payloads can never be confused either.

Note the deliberate asymmetry: `sb presets` is plural and flat, `sb plugin` is singular
and a namespace. Presets have no verbs — there is nothing to namespace. Plugins do.

### Telling them apart in the one place they mix

Presets and plugin-contributed prompt text both land in `--with` and both bind in
`presets.toml`. They are distinguished by a sigil:

```toml
# .switchboard/presets.toml
all = ["own-files", "@todo"]
[roles]
reviewer = ["adversarial", "@report-bug"]
```

`adversarial` is a preset file. `@todo` is the fragment contributed by the plugin `todo`.
The `@` means a preset and a plugin may share a name without colliding, and it makes the
provenance of every line of injected prompt text visible in the binding file itself.

`--with @todo` works too. Unresolvable `@name` is an **error**; unresolvable bare names
keep passing through as literal instructions exactly as today (`plugins.py:94-110`) — that
documented behaviour is untouched, the `@` prefix is simply reserved.

### The optional un-namespaced form

`sb plugin todo list` is a thing you type forty times a day, and the ceremony is not worth
it at that frequency. A repo may opt one plugin into a top-level alias:

```toml
# .switchboard/plugins.toml
alias = { todo = "todo" }        # enables `sb todo add "…"`
```

sb refuses the alias if it collides with any core verb (hidden ones included) or another
alias. Resolution happens in `main()` before argparse: unknown first word that matches an
enabled alias is rewritten to `["plugin", name, *rest]`. Core verbs always win, so a future
sb verb reclaims the name rather than breaking. A plugin can never request this itself —
un-namespacing is the repo's consent, not the author's.

---

## 2. Layering — both concepts, `defaults/` and `.switchboard/`

### What today's rule actually is, and why it survives

The current docstring says plugin files are "not layered out of `defaults/`"
(`plugins.py:14-19`), but the code tells a more precise story: `available()` **does** read
`defaults/plugins/*.md` on every call (`plugins.py:57-63`), and `defaults/plugins.toml`
ships `all = []` with an empty `[roles]`. So all six shipped presets are nameable from any
repo, and none of them apply to anything.

The real guarantee is therefore:

> **Shipping makes something *available*. Only a binding makes it *applied*.**

That is still right, and it is the load-bearing idea for both concepts. It answers the
worry the docstring was actually about — a shipped behaviour arriving in every repo and
having to be "argued back out" — without the cost of making shipped vocabulary invisible.

### It generalizes to plugins with one extra state

Presets have two states (available → bound). Plugins have three, because they own state and
add CLI surface:

| state | means | set by |
|---|---|---|
| **available** | sb can see it and describe it | present in either root |
| **enabled** | its commands dispatch; its state dir exists | `enabled` in `plugins.toml` |
| **bound** | its `@fragment` is injected into prompts | `presets.toml` bindings |

Enablement is separate from availability for the same reason bindings are: a shipped `todo`
plugin that is enabled everywhere means every repo you touch silently grows a todo
database. Enabling is one line and it is the repo's call.

Enablement is **not** the same as binding, either — you can use `sb plugin todo` yourself
without every spawned agent being told about it.

### The files

```
defaults/presets/*.md              shipped presets              (moved from defaults/plugins/)
defaults/presets.toml              shipped bindings             (moved from defaults/plugins.toml)
defaults/plugins/<name>/           shipped plugin packages
defaults/plugins.toml              shipped enablement

<repo>/.switchboard/presets/*.md   this repo's presets          — file replaces shipped, per stem
<repo>/.switchboard/presets.toml   this repo's bindings         — array-JOIN onto shipped
<repo>/.switchboard/plugins/<name>/ this repo's plugin packages — dir replaces shipped, per name
<repo>/.switchboard/plugins.toml   this repo's enablement       — array-JOIN onto shipped
```

Both `.toml` files use the existing `config.merge()` semantics — tables merge, arrays join
base-first with `"!reset"` as the escape hatch (`config.py:170-211`). No third merge rule is
introduced; sharp edge #6 is respected. Both directories use the existing "override by
name, last write wins" rule that `available()` already implements.

Per decision 2, **everything is authored in `defaults/` for now**: both `todo` and
`report-bug` ship there, and `defaults/plugins.toml` sets `enabled = ["todo",
"report-bug"]`. sb has one user today; the layering exists so that stops being true
without a redesign. A repo turns them off with `enabled = ["!reset"]`.

### The migration hazard, and why it is not a flag day

Renaming the preset directory is forced: `.switchboard/plugins/` cannot mean prompt files
and code packages at once. But the two are trivially distinguishable *by shape* —

- presets are `*.md` **files**
- plugins are **directories** containing `__init__.py`

— so during the transition sb reads both spellings out of `.switchboard/plugins/` with no
ambiguity, and `sb doctor` reports the deprecation with the exact `git mv`. Same for the
TOML: a `plugins.toml` containing top-level `all` or `[roles]` is a pre-rename bindings
file; sb reads it as such, warns, and never mistakes it for enablement config. There is no
moment at which a repo is broken, and no version of sb that understands only one spelling.

---

## 3. The plugin contract

### 3.1 The four layers

This is the whole design. Each layer costs more and answers more, and every verb uses the
cheapest one that suffices.

| layer | operation | yields | who uses it |
|---|---|---|---|
| **1. glob** | list directories in the two roots | names, which root, enabled? | `sb plugin list`, `sb doctor` |
| **2. read** | `ast.parse(__init__.py)`, no execution; and stat `agent.md` | `API`, `VERSION`, `SUMMARY`, `SCOPE`, imports, fragment text | `sb delegate`, `sb plugin list`, `sb doctor` |
| **3. import** | `importlib` the package, call `register(reg)` | the command table | `sb plugin <name> …`, `sb plugin list --commands` |
| **4. call** | invoke one handler | the actual work | `sb plugin <name> <cmd>` only |

**Layer 2 is the part I care about.** Decision 3 forbids a manifest DSL, and it is right to
— a TOML file restating what Python already says is a second source of truth that drifts.
But the *reason* I wanted a manifest was to answer questions about a plugin without running
it, and Python gives that up for free if the metadata is module-level literal constants:
`ast.parse` reads them exactly, in about a millisecond, executing nothing.

```python
# defaults/plugins/todo/__init__.py
API     = 1
VERSION = "0.3.0"
SUMMARY = "one todo list per repo, shared across every worktree"
SCOPE   = "repo"
```

sb requires these to be plain literals and says so when they are not ("`VERSION` must be a
string literal — sb reads it without importing the module"). That constraint is the price
of the property, it is easy to satisfy, and it is checkable at layer 2.

So the manifest is gone and almost everything I wanted from it survives.

### 3.2 The fragment is convention, not declaration

`<plugin dir>/agent.md`, if it exists, is the plugin's prompt fragment, injected as
`@<name>`. It is not declared anywhere.

This is not tidiness — it is what keeps `sb delegate` off the import path entirely.
Injecting prompt text becomes: glob, check `API` via AST, read a markdown file, run it
through the same `config.flatten()` every preset and role prompt already uses
(`config.py:216-232`). **`sb delegate` never imports plugin code**, so no plugin can slow,
crash, or hang the one verb the entire system is built on.

The fragment is static. It is not computed at spawn time, and that is a decision rather
than a limitation: a computed fragment would put plugin code on the delegate hot path, and
its content would be stale the moment the agent's system prompt was fixed for life. The
fragment tells the agent to **pull** instead — agents have a CLI, which is the premise of
switchboard.

```markdown
# todo
- Before starting, run `sb plugin todo list --state open` and check what you are about
  to do is not already claimed.
- Claim before you start: `sb plugin todo claim <id>`; close with `sb plugin todo done <id>`.
- Work you find but are not doing: `sb plugin todo add "…" --label found`.
```

Headings are dropped by `flatten`, bullets become `; ` — it reaches herdr as one line, so
the no-newline constraint (sharp edge #1) is satisfied by reusing the existing pipeline
rather than by a new rule anybody has to remember.

### 3.3 Registration

Small on purpose. A plugin defines one function:

```python
def register(reg):
    reg.command("add",   add,   audience="both",  help="add a todo",
                args=[reg.arg("text"), reg.arg("--label", repeat=True)])
    reg.command("list",  ls,    audience="both",  help="list todos",
                args=[reg.arg("--state", choices=("open", "doing", "done", "all")),
                      reg.arg("--mine", flag=True)])
    reg.command("drop",  drop,  audience="human", help="delete a todo outright")
```

`register` may call `reg.command()` and nothing else; the registry object exposes nothing
else. It runs at load and must not touch the filesystem or the network — a plugin that
does work in `register` is doing it on every `sb plugin` invocation, including `--help`.

**Arguments are declared as data, and sb builds the argparse subparser from them.** This
buys back the property `cli.py`'s own docstring is proud of — "this is the last point where
an error can name the flag the caller typed" (`cli.py:16-18`). `sb plugin todo add --labl x`
gets an sb-quality error, and `sb plugin todo --help` is generated by sb, so every plugin's
help looks like sb's. The declared vocabulary is four keys (`repeat`, `flag`, `choices`,
`help`) and stops there; a plugin needing more than that should be reconsidered.

`audience` is `agent | human | both`. Human-only commands are refused for a caller sb
resolves to an agent, and the refusal names the alternative — the same treatment `sb ask
human` already gets (`broker.py:1026-1033`) and the same principle that hides `sb board`
(`cli.py:110-114`). This is how an agent is prevented from running destructive verbs, and
it is why `audience` is part of the contract rather than a convention.

### 3.4 The handler surface — and the escape hatch it preserves

```python
def add(ctx, args) -> Result: ...
```

`ctx` is a frozen dataclass and is the plugin's **entire** view of sb:

```python
@dataclass(frozen=True)
class Context:
    api:       int
    state_dir: Path          # sb made it; the plugin owns what goes inside
    repo:      Path          # the shared .git — the repo identity
    worktree:  Path
    agent:     str | None    # resolved caller; None means a human
    json:      bool
```

```python
@dataclass
class Result:
    ok:    bool = True
    human: str  = ""         # printed without --json
    data:  Any  = None       # printed with --json
    code:  int  = 0
```

What is **not** in `Context` is the contract: no `Broker`, no `Herdr`, no sqlite handle, no
access to another plugin's state. A plugin cannot spawn agents, read the message store, or
reach into sb's internals through anything sb hands it. Spawn authority in particular stays
core — a plugin that can call `sb delegate` is both a privilege escalation and a fork bomb
waiting for a bad loop.

Decision 3 says keep the surface small enough that an out-of-process escape hatch is not
precluded, and this is that. `Context` is scalars and paths; `Result` is scalars and JSON;
`args` is the parsed namespace of a declarative arg spec. **All three are already
JSON-serializable.** The day sb wants subprocess isolation, the same handler signature
works over a pipe and no plugin author changes a line. The escape hatch stays open by the
shape of the data, not by building anything.

`--json` therefore works uniformly across every plugin for free, which keeps the C13
property that wrapping sb in an MCP server stays mechanical (`cli.py:11-13`).

### 3.5 Registering against the existing argparse

`build_parser()`, `_validate()` and `_dispatch()` are three parallel `if cmd == …` chains
(`cli.py:75-251`, `254-341`, `415-639`). Dynamic registration at parse time would mean
reading and importing plugin code just to print `sb --help` — and `_tier_help()` already
has to wrap a config read in a bare `except Exception` so that `sb --help` outside a repo
does not traceback (`cli.py:68-71`). One such hazard is enough.

So: one static subparser, and sb defers.

```python
pl = cmd("plugin", help="run an installed plugin (see: sb plugin list)")
pl.add_argument("name", nargs="?")
pl.add_argument("rest", nargs=argparse.REMAINDER)
cmd("presets", help="list available presets")
```

`REMAINDER` means the parser is static and cheap and cannot be broken by anything on disk.
The plugin's own arguments are parsed *after* dispatch, by the argparse subparser sb builds
from the layer-3 arg spec — so deferral costs nothing in error quality. `_validate()` gains
one branch that checks the plugin name and, using the command table, that `rest[0]` is a
real subcommand (with a *did you mean* for near misses).

`list` is a reserved plugin name, along with `info`, `enable`, `disable` — otherwise
`sb plugin list` is ambiguous.

### 3.6 Error isolation

Stated so it can be written as a test:

> `sb status`, `sb done`, `sb inbox`, `sb ask`, `sb tell`, `sb block`, `sb log`,
> `sb cleanup`, `sb inspect`, `sb wait`, `sb start`, `sb init`, `sb workspace new`,
> `sb restore`, `sb interrupt` reach **layer 0** — they do not glob, read, import, or call
> a plugin under any circumstances.
>
> `sb delegate` and `sb presets` reach **layer 2**. They read files. They never import.
>
> `sb plugin list` and `sb doctor` reach **layer 3**, wrapping each import.
>
> Only `sb plugin <name> <cmd>` reaches **layer 4**.

A broken plugin cannot break `sb status` because `sb status` has never heard of plugins.
That is a topology, not defensive coding.

Within the verbs that do reach a plugin, failure is a *status*, never a traceback:

```
$ sb plugin list
  todo          0.3.0   ok            [enabled, @todo bound to every agent]
  report-bug    0.2.1   ok            [enabled]
  ci-check      1.2.0   not enabled   add to .switchboard/plugins.toml
  shiny         2.0.0   incompatible  targets API 2, this sb supports API 1
  halfthing     —       broken        __init__.py:14 SyntaxError: invalid syntax
```

`halfthing` being broken cost `todo` nothing — layer 1 glob and layer 2 AST read are
per-plugin, and the layer-3 import is wrapped per-plugin.

`sb delegate` treats fragment failure asymmetrically, on purpose:

- a fragment reached via a **binding** in `presets.toml` that fails to resolve is
  **skipped**, with one line on stderr naming the plugin. Delegation must not fail because
  somebody's todo plugin is half-installed.
- a fragment named **explicitly** (`--with @todo`) that fails to resolve is an **error**
  naming the plugin. You asked for it by hand; silently dropping it spawns an agent missing
  an instruction you believed it had.

Handler exceptions are caught at dispatch and reported with the plugin name and a reserved
exit code, never as a raw sb traceback (`SB_DEBUG=1` re-raises for the plugin's author).

**What in-process cannot protect against, said plainly.** A handler that calls
`sys.exit()`, monkeypatches sb internals, imports `switchboard.store` and writes to the
database, leaks memory, or blocks forever, will do all of those things to the sb process
itself. Subprocess isolation would have stopped every one; decision 3 trades that away.
Two cheap mitigations that do not require building the escape hatch:

- The layer-2 AST read already parses the import statements. `sb doctor` flags a plugin
  importing anything from `switchboard` other than `switchboard.plugin` — a static check,
  no execution, and it catches the coupling that would make the future escape hatch
  impossible.
- Everything above the handler call is wrapped, so the blast radius of the *common*
  failures (import error, bad register, handler exception) is one plugin.

### 3.7 Versioning

`API` is the contract version — the shape of `Context`, `Result`, the registry, the
`agent.md` convention. sb knows the set it supports. A plugin declaring an unsupported
`API` is `incompatible`: **its commands refuse and its fragment is not injected.** The
second half matters more. A fragment telling an agent to run `sb plugin todo claim <id>`
when `claim` no longer exists is worse than no fragment — the agent burns turns on a
command that fails. Because `API` is read at layer 2, `sb delegate` can enforce this
without importing anything.

`VERSION` is the plugin's own, semver, opaque to sb, shown by `sb plugin list`, and owned by
the plugin for its own state-format migrations.

---

## 4. State

### 4.1 Repo identity, precisely

```
git rev-parse --git-common-dir
```
anchored against the invocation cwd and resolved — exactly `store.repo_root()`
(`store.py:44-59`). From the main checkout and from every worktree this returns the *same*
absolute path, because `--git-common-dir` is the shared git directory. The anchoring is
load-bearing and already commented in the source (`store.py:54-56`): resolving the bare
relative result against the process cwd hands back a different repo's directory.

> **A repo identity is the absolute path of its shared `.git` directory.**

Consequences, stated rather than discovered later: every worktree of a clone shares one
todo list (the requirement); two clones on one machine have two; a fork and its upstream
have two; a repo with no remote still has an identity.

I rejected identifying a repo by first-commit hash or remote URL — both merge a fork's list
into its upstream's, and remote URL leaves a remote-less repo with no identity. More
importantly, the shared-`.git` definition is *already* in force for the store, for
`config.json`, and for the config symlinks. A second definition of "same repo" living
beside the first is correct until someone relocates a `.git`, and subtly wrong forever
after.

### 4.2 The three scopes

| `SCOPE` | path | shared by |
|---|---|---|
| `repo` | `<shared .git>/agentflow/plugins/<name>/` | every worktree of this clone |
| `user` | `~/.local/state/switchboard/plugins/<name>/` | every repo on this machine |
| `worktree` | `<worktree>/.switchboard/state/<name>/` | this worktree only |

sb creates the directory and passes it as `ctx.state_dir`. **sb never reads inside it.**
The path is sb's; the contents are the plugin's.

### 4.3 Not `state.db`, and why

The reasons are all in the store's own source:

1. It is **documented as disposable** — "on a schema change we simply drop and recreate"
   (`store.py:192-195`). A todo list that vanishes when sb adds a column is not a todo list.
2. **One schema hash covers all tables** (`store.py:176`). A plugin's table would bump the
   hash and force the reset-or-migrate decision for `agents` and `messages` too. There is no
   per-subsystem versioning, and adding one is a bigger change than this whole proposal.
3. There is **no extension point** — a plugin's table would have to be spliced into the one
   `SCHEMA` string inside `store.py`, which is the opposite of "installable".

The precedent for the alternative is right there: `config.json` lives *beside* the store, in
the same shared directory, deliberately not as a table in it, because "the database is
disposable by design and gets dropped on a schema change, whereas this must survive that"
(`store.py:85-87`). Plugin state is that same argument with the same answer. Sharp edge #4
is avoided entirely: no schema change, no reset.

**Format is the plugin's choice**, because the access pattern differs and only the plugin
knows it — `todo` is read-modify-write (one JSON file), `report-bug` is append-only (one
file per bug, no locking needed at all). A plugin that genuinely needs indexed queries opens
its own sqlite file in its own directory with its own migrations, versioned by its own
`VERSION` — the independent versioning `state.db` cannot offer.

**Concurrency is sb's problem, not the author's.** sb's normal pattern is "many short-lived
processes" (`store.py:24-26`) and that does not change. sb takes an exclusive `flock` on
`<state_dir>/.lock` around the handler call, so a plugin doing a read-modify-write JSON
update gets serialization without knowing the word "lock". A plugin sets `LOCK = False` when
it does not need one. This is the payoff of sb owning the path: the two things naive
authors get wrong — *where does my data go* and *what happens when two agents write at
once* — are both answered before their code runs.

---

## 5. `todo`

Per decision 4: serves humans and agents equally, deliberately dumb, a store and nothing
more. `SCOPE = "repo"`, state at `<shared .git>/agentflow/plugins/todo/todos.json`.

```
sb plugin todo add "<text>" [--label L]…                both
sb plugin todo list [--state open|doing|done|all] [--label L] [--mine]   both
sb plugin todo claim <id> / release <id>                both
sb plugin todo done <id> [--note "…"]                   both
sb plugin todo show <id>                                both
sb plugin todo drop <id> / edit <id> "<text>"           human
```

One record:

```json
{"id": "t-7", "text": "…", "labels": ["config"], "state": "open|doing|done",
 "owner": null, "created_by": "orchestrator", "created_at": 1754570000,
 "done_at": null, "note": null}
```

- Ids are `t-<n>`, monotonic, never reused, so a commit message citing `t-7` stays true.
- Three states, not more. A fourth makes it a project tracker, which it is not.
- `owner` is set by `claim` from `ctx.agent`, or `"human"` when a person runs it. That is
  the entire assignment model — a todo is inert text with an owner. It does not spawn
  anything: spawn authority is core sb (§3.4), and a list that spawns is a scheduler with
  failure modes (runaway fan-out, orphans) this design does not have. An orchestrator reads
  the list and delegates, which is the orchestrator doing its job.
- Whole file rewritten via tmp + `os.replace` under the lock sb already holds.

Agents reach it through the CLI only, guided by the `@todo` fragment in §3.2. The fragment
says *never edit the file directly* — the CLI is the only writer, which is what makes the
lock sufficient.

**`sb status` integration is out of scope** per decision 4, and the design leaves the door
open in one specific way: a plugin may define `def summary(ctx) -> str`. Nothing calls it
today. If it is ever wanted, the shape that preserves §3.6 is an opt-in human-typed flag
(`sb status --with-plugins`) rather than plugin code on the default `sb status` path.

---

## 6. `report-bug`

Per decision 5: whichever is simplest, files on disk, no GitHub integration.

`SCOPE = "user"`, `LOCK = False`. One markdown file per bug in
`~/.local/state/switchboard/plugins/report-bug/`, named
`2026-08-07-143022-ask-human-refused.md`.

```
sb plugin report-bug file "<what broke>" [--command "…"] [--expected "…"] [--actual "…"]   both
sb plugin report-bug list                                                                  both
sb plugin report-bug show <id>                                    both
sb plugin report-bug drop <id>                                    human
```

One file per bug is the simplest thing that works: no format, no index, no locking (two
agents filing at once write two different files), greppable, and readable by anything.

**User scope, not repo**, because a bug in switchboard is a fact about switchboard, not
about whichever repo you were standing in. Repo-scoped, you would file three bugs in three
repos and find none of them later. The repo and worktree paths are still *recorded in the
file* — the context is useful, the partitioning is not.

Auto-capture is limited to what sb already knows and hands over in `ctx`, plus sb's and
herdr's versions and the platform. Everything narrative comes from the caller. Transcripts
are not captured: a Claude Code transcript (`store.py:668-678`) contains everything the
agent read, and hoovering that into a bug report by default is a data-exfiltration shape
even with no publishing step.

This supersedes the existing `report-bug` *preset*, which currently tells agents to append
to `BUGS.md`. The preset stays (deleting it would make an existing `--with report-bug`
silently degrade into the literal instruction `"report-bug"` — a spawn that looks fine and
ships a one-word prompt) but its text should point at the plugin.

---

## 7. Migration

| change | breaking? |
|---|---|
| `sb plugins` → `sb presets` **+** `sb plugin list` | **Yes, deliberately.** One release of a hard error naming both. §1. |
| `--json` key `plugins` → `presets` | Yes, with the command. Renamed together so they cannot disagree. |
| `--with adversarial`, unknown-value-is-literal | No. Untouched, except `@`-prefixed names are reserved. |
| `defaults/plugins/*.md` → `defaults/presets/*.md` | No. Shipped-side move; discovery reads both. |
| `.switchboard/plugins/*.md` → `presets/` | No. Both read; distinguishable by shape (`*.md` vs `*/`); `sb doctor` reports the `git mv`. |
| `plugins.toml` → `presets.toml` | No. A file with top-level `all`/`[roles]` is read as bindings and flagged. |
| the 6 shipped presets | Unchanged content, moved directory. |
| `state.db` schema | Unchanged. No schema-hash bump, no reset. |
| `Broker.delegate` prompt assembly, flatten, herdr | Unchanged. |

Two shipped-content bugs to fix while in the area, flagged not fixed:

1. `ask-dont-guess.md` tells agents to run `sb ask human`, which `Broker.ask()` refuses in
   favour of `sb block` (`broker.py:1026-1033`). Every agent that ever received this preset
   was told to run a command that errors.
2. `report-bug.md` tells agents to append to `BUGS.md`; once the plugin exists the two will
   disagree about where bugs live.

---

## 8. Where this stance costs you

1. **In-process is a real loss and the mitigations are partial.** A handler that calls
   `sys.exit()`, writes to `state.db`, or blocks forever does it to sb. The AST import scan
   catches the *coupling* but not the *behaviour* — nothing stops a plugin doing
   `__import__("switchboard.store")` at runtime. Every isolation claim in §3.6 is about
   import-time and handler-exception failures, which are the common ones, not the malicious
   ones. I am not going to pretend the four-layer structure is equivalent to a process
   boundary; it is a good approximation of one for accidents and no defence at all against
   intent.

2. **Layer 2's constant-literal rule is a real constraint on authors.** `VERSION =
   _read_version()` is a natural thing to write and sb rejects it. The rule is easy to
   follow and impossible to discover without hitting it, so the error message is doing a
   lot of work.

3. **`sb plugins` breaking is a genuine cost I chose to pay.** Every alternative I could
   find either returns silently-wrong data to a `--json` caller or keeps a confusing name
   forever. I picked the loud one, but it is still the one thing in this proposal that will
   annoy someone on the day it lands.

4. **The declarative arg spec buys error quality and costs expressiveness.** Four keys
   covers `todo` and `report-bug` comfortably and will not cover the first plugin that wants
   mutually-exclusive groups or subcommand nesting. When that plugin appears the honest
   answers are "make it two commands" or "widen the spec", and the second one starts the
   slide toward reimplementing argparse in data.

5. **Static-only fragments trade responsiveness for isolation.** A push design would put the
   open todos directly in the system prompt where an agent cannot miss them. Mine requires
   the agent to *choose* to run `todo list`, and agents skip instructions. Some real
   fraction of a todo plugin's value is lost to agents that never pull. I still think the
   trade is right; it is not free.

6. **The alias hatch undermines the namespace argument I used to justify the namespace.** I
   argued for `sb plugin todo` on collision-safety grounds and then provided `sb todo`. Most
   people will enable it. The guarantee survives at dispatch — core verbs always win — but
   the clean story of "plugin commands are visibly namespaced" does not.

7. **Three notations for prompt text is one too many.** Bare name = preset, `@name` = plugin
   fragment, unrecognised bare name = literal instruction. Someone typing `--with todo` and
   getting the literal string `"todo"` in a system prompt — because they forgot the `@` — is
   a failure that looks like success. I preserved the literal-passthrough rule (sharp edge
   #3) rather than fixing it; a warning when a bare name matches a plugin fragment would
   close it cheaply.

8. **`API = 1` is a constant nobody reads yet.** Version negotiation earns its keep the day
   there is an `API = 2` and a third-party plugin in the wild, and not one day before. I
   keep it because it costs one line now and cannot be added later without breaking every
   plugin that already exists.

9. **Three plugin states (available / enabled / bound) is one more concept than presets
   have,** and the difference between "enabled" and "bound" will need explaining more than
   once. It is the right split — using a plugin yourself and injecting it into every agent
   are genuinely different decisions — but it is a thing to learn.

---

## 9. Summary of changes

**New:** `switchboard/plugins_api.py` (the `Plugin`/`Context`/`Result`/registry surface a
plugin imports) and `switchboard/plugin_loader.py` (the four layers: glob, AST read,
import, dispatch), both sitting above `config.py` the way `plugins.py` and `roles.py` do,
importing nothing from `broker.py`. `sb plugin <name> …`, `sb plugin list`, `sb presets`.
New `[paths]` entries for the preset and plugin directories and TOML files. Plugin state
roots under `<shared .git>/agentflow/plugins/` and `~/.local/state/switchboard/plugins/`.
`todo` and `report-bug` shipped in `defaults/plugins/`.

**Renamed:** today's `switchboard/plugins.py` becomes `switchboard/presets.py`, with
`available()` gaining the extra directories and `resolve()` gaining the `@` sigil.
`defaults/plugins/` → `defaults/presets/`; `defaults/plugins.toml` → `defaults/presets.toml`.

**Unchanged:** `state.db` and its schema, `--with` semantics for bare names, the six shipped
preset texts, the config merge rules, `Broker.delegate`'s prompt assembly order, the flatten
pipeline, the no-newline constraint, herdr.
