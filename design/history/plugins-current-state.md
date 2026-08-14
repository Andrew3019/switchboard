# switchboard's current plugin implementation — a survey

Research only; nothing in this doc changes code. Every claim below cites `file:line` in
this worktree (`~/.herdr/worktrees/switchboard/plugins-redesign`).

---

## 1. `sb plugins` command

Registered as a plain subcommand with no arguments: `switchboard/cli.py:163`
(`cmd("plugins", help="list available prompt plugins")`).

Dispatch: `switchboard/cli.py:556-567`.

```python
found = plugins_mod.available(b.repo)
every, per_role = plugins_mod.bindings(b.repo)
lines = []
for n in found:
    using = [r for r, ps in per_role.items() if n in ps]
    tag = " [every agent]" if n in every else (f" [{', '.join(using)}]" if using else "")
    lines.append(f"  {n:16}{tag}")
```

- Lists every plugin **name** the repo can reference (`plugins_mod.available`, see §2),
  not file contents.
- Annotates each with where it is bound: `[every agent]` if it's in the `all` list, or
  `[reviewer, qa]`-style role names if it's bound to specific roles via `[roles]` in
  `plugins.toml`. A plugin that exists as a file but isn't bound anywhere gets no tag —
  it's only reachable via an explicit `--with <name>`.
- Human output: one line per plugin, `f"  {n:16}{tag}"`. With `--json`, the payload is
  `{"plugins": sorted(found), "all": list(every), "roles": {role: [names]}}`
  (`switchboard/cli.py:565-566`).
- If there are no plugins at all, prints `(none — add .switchboard/plugins/<name>.md)`
  built from `_plugin_dir_help()` (`switchboard/cli.py:46-53, 564`).

This command is **read-only discovery**: "what vocabulary does this repo have" — the
sibling of `sb models` (`switchboard/cli.py:164-168`).

---

## 2. `.switchboard/plugins/` — file format, discovery, parsing, validation

### File format

A plugin is **one markdown file**, no required front matter. Example, `defaults/plugins/adversarial.md:1-8`:

```markdown
# adversarial

You are reviewing to find what is wrong, not to approve.

- Assume the work is flawed and look for the specific flaw. Vague praise is a failure.
- Every objection needs a concrete pointer: file, line, and what breaks.
- ...
```

There is **no TOML front matter on plugin files** (unlike role files — see §4). A
plugin's identity (its name) comes entirely from its filename stem; its content is
whatever markdown follows.

### Discovery

`plugins.available(repo)` — `switchboard/plugins.py:49-63`:

```python
def available(repo: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    shipped = config.defaults_dir() / "plugins"
    for d in (shipped, plugin_dir(repo)):
        if d is None or not d.is_dir():
            continue
        found.update({f.stem: f for f in sorted(d.glob("*.md"))})
    return found
```

- Two directories, most-general-first: `defaults/plugins/*.md` (shipped), then
  `<repo>/.switchboard/plugins/*.md` (this repo's own). `plugin_dir(repo)` resolves via
  `config.path_for("plugins_dir", repo)` → `switchboard/plugins.py:41-42`, which is
  `<repo>/.switchboard/plugins/` per `defaults/settings.toml:22` (`plugins_dir = "plugins"`)
  under `paths.repo_dir = ".switchboard"` (`defaults/settings.toml:14`).
- `dict.update` means a repo file **replaces** a shipped file of the same stem (last write
  wins) — this is the one place in the plugin system where "layering" means "override the
  whole file" rather than "merge fields," unlike roles/settings/prompts.
- **Unlike roles, models, prompts, and settings, plugin *files themselves* are NOT merged
  from `defaults/` into every repo.** Only the shipped *bindings* (`plugins.toml`, see
  below) are layered. This is a deliberate design choice, explained in the plugins.py
  module docstring (`switchboard/plugins.py:14-19`) and `defaults/README.md:31-34`: a
  shipped plugin file would land in every repo whether or not it suited that repo's work,
  and would have to be "argued back out." A repo with no `.switchboard/plugins/` directory
  still gets every *shipped* plugin available by name (because `available()` always reads
  `defaults/plugins/`), it just has none of its own.

### Bindings — the `[reviewer, qa]`-style tags

Bindings (which plugin auto-applies to which role) live in **`plugins.toml`**, not in the
plugin files:

- Shipped: `defaults/plugins.toml` — currently empty (`all = []`, `[roles]` with nothing
  under it — `defaults/plugins.toml:29-33`).
- Repo override: `<repo>/.switchboard/plugins.toml`, resolved via
  `config.path_for("plugins_file", repo)` (`switchboard/plugins.py:45-46`), filename from
  `defaults/settings.toml:21` (`plugins_file = "plugins.toml"`).

Format (see the shipped file's own comments, `defaults/plugins.toml:1-33`):

```toml
all = ["own-files"]          # every agent, whatever its role

[roles]
reviewer = ["adversarial"]   # appended to `all` for this role
qa       = ["verify"]
```

Merge logic: `config.plugin_bindings()` — `switchboard/config.py:414-425`:

```python
def plugin_bindings(repo):
    shipped = read_toml(defaults_dir() / "plugins.toml")
    p = path_for("plugins_file", repo)
    data = merge(shipped, read_toml(p) if p is not None else {})
    every = tuple(data.get("all") or ())
    per_role = {k: tuple(v) for k, v in (data.get("roles") or {}).items()}
    return every, per_role
```

Uses the general `config.merge()` rules (`switchboard/config.py:170-211`, documented in
the module docstring `switchboard/config.py:17-34`): tables merge key-by-key, scalars
replace, **arrays join** (base first, then override, de-duplicated, order preserved) —
so a repo adding one binding to `all` cannot silently drop a shipped one. `"!reset"` as
the array's first element discards the base instead of joining
(`switchboard/config.py:53-55, 186-194`).

The `[reviewer, qa]` tag shown by `sb plugins` is exactly this `per_role` dict, inverted
per-plugin at print time (`switchboard/cli.py:561`) — it is **not** stored anywhere on
the plugin file itself.

### Parsing / flattening

Plugin file contents are never sent multi-line. `plugins.resolve()` —
`switchboard/plugins.py:94-110`:

```python
def resolve(names, repo=None):
    repo = Path(repo or Path.cwd())
    found = available(repo)
    out = []
    for n in names:
        if n in found:
            line = flatten(found[n].read_text())
            if line:
                out.append(line)
        else:
            out.append(n)     # unknown name -> literal instruction, verbatim
    return out
```

`flatten()` delegates to `config.flatten()` (`switchboard/plugins.py:66-69` →
`switchboard/config.py:216-232`):

```python
def flatten(text: str) -> str:
    body = _COMMENT.sub(" ", text)                          # strip <!-- ... --> entirely
    body = re.sub(r"^#.*$", "", body, flags=re.M)            # drop markdown headings
    body = re.sub(r"^\s*[-*]\s+", "; ", body, flags=re.M)    # bullets -> "; " separators
    body = re.sub(r"\s+", " ", body).strip()                 # collapse all whitespace
    return re.sub(r"^;\s*", "", body)
```

Why: herdr (the underlying agent-spawn adapter) refuses any agent argument containing a
newline (`switchboard/plugins.py:21-23`, `switchboard/validate.py:11-19`). So a plugin is
authored as wrapped, headed markdown for humans and arrives at the agent as one flat
sentence-ish line with `; `-joined bullets and no heading text at all (headings are
dropped, not converted).

### Validation

- No schema validation of plugin file *contents* — any markdown is legal; only the
  post-flatten *line* is checked. In `cli.py`'s delegate dispatch
  (`switchboard/cli.py:478-484`):
  ```python
  names = plugins_mod.for_role(b.repo, args.role, args.with_)
  with_ = [validate.line(p, "plugin text", max_len=validate.MAX_PROMPT)
           for p in plugins_mod.resolve(names, b.repo)]
  ```
  Each resolved line is re-validated with `validate.line(..., max_len=validate.MAX_PROMPT)`
  (`switchboard/validate.py:104-119`), which enforces: non-empty, no control characters, no
  embedded newline (raises if flattening somehow left one — comment at
  `switchboard/cli.py:479-482` explains this catches a `plugins.toml`-named plugin whose
  file no longer flattens cleanly, naming the plugin rather than surfacing as a generic
  `invalid_agent_argument`), and a length cap: `limits.prompt = 8000` chars
  (`defaults/settings.toml:133`, vs. `limits.text = 4000` for ordinary messages —
  `defaults/settings.toml:129` — plugin/role prompt text gets double the budget because it's
  "config… allowed to be a substantial briefing").
- `--with` values themselves are validated *before* resolution too, in `_validate()`
  (`switchboard/cli.py:289-290`): `validate.line(w, "--with", max_len=validate.MAX_PROMPT)`
  — this catches a raw literal instruction (an unknown `--with` value) that's already too
  long or multi-line, before it's even looked up against the plugin directory.
- No validation that a named plugin file exists — an unrecognized name is deliberately
  treated as a literal instruction (see §3).

### Existing plugin files — what each one does

All six live in `defaults/plugins/` (shipped; no repo-local ones exist in this worktree's
`.switchboard/plugins/`, confirmed empty by directory listing). None are currently bound
to any role — `defaults/plugins.toml` ships both `all` and `[roles]` empty
(`defaults/plugins.toml:29-33`), so all six are **`--with`-only** today; nothing pulls
them in automatically.

| file | summary |
|---|---|
| `adversarial.md` (`defaults/plugins/adversarial.md:1-8`) | Reviewer stance: assume the work is flawed, cite `file:line` for every objection, distinguish real breaks from style preference, end with a mandatory `PASS` or `REVISE` verdict line. |
| `ask-dont-guess.md` (`defaults/plugins/ask-dont-guess.md:1-11`) | Stop-and-ask triggers: a tool/command failing twice, genuine task ambiguity, being about to do delegated work yourself, or an irreversible action (push/merge/delete/rewrite history). Tells the agent to use `sb ask human` — **note: this text is stale**, since `broker.py` refuses `ask` targeted at the human outright (`switchboard/broker.py:1027-1033`) and the correct verb is `sb block`; see "sharp edges" below. |
| `evidence.md` (`defaults/plugins/evidence.md:1-7`) | Reporting discipline: every codebase claim must cite `file:line`; say "I did not check X" rather than imply verification; distinguish what was run from what was inferred. (This is, notably, close to the standing instruction this very investigation was run under.) |
| `own-files.md` (`defaults/plugins/own-files.md:1-8`) | Multi-agent file-ownership discipline: edit only assigned files, never "while I'm here" a neighboring file, never revert/reformat another agent's work, re-read a file that changed under you. |
| `report-bug.md` (`defaults/plugins/report-bug.md:1-9`) | If the agent hits a bug in switchboard itself, don't silently work around it: append an entry to `notes/BUGS.md` (what ran, expected, actual, exact error), keep going with the real task, `sb ask human` only if fully blocked. |
| `verify.md` (`defaults/plugins/verify.md:1-9`) | Pre-`sb done` checklist: run `python3 -m unittest discover -s tests` and confirm it passes; add a regression test for new behavior; report honestly if failures are pre-existing rather than silently fixing unrelated things. |

---

## 3. `sb delegate --with X` handling

### Flag definition

`switchboard/cli.py:121-123`:
```python
d.add_argument("--with", dest="with_", action="append", default=[], metavar="PLUGIN",
               help=f"prompt plugin from {_plugin_dir_help()} (repeatable); "
                    f"an unknown value is used as a literal instruction")
```
Repeatable (`action="append"`), so `--with a --with b` collects `["a", "b"]`.

### How plugin text reaches the spawned agent's prompt

Full path, `switchboard/cli.py:473-490` (`_dispatch`, `cmd == "delegate"`):

```python
names = plugins_mod.for_role(b.repo, args.role, args.with_)
with_ = [validate.line(p, "plugin text", max_len=validate.MAX_PROMPT)
         for p in plugins_mod.resolve(names, b.repo)]
name = b.delegate(args.task, role=args.role, as_prompt=args.as_prompt,
                  name=args.name or _derived_name(db, args.role),
                  model=args.model, with_=with_,
                  cleanup=cleanup, me=me)
```

1. `plugins.for_role(repo, role, extra=args.with_)` (`switchboard/plugins.py:80-91`)
   resolves the full ordered list of **plugin names** for this call — every-agent
   bindings, then this role's bindings, then the caller's `--with` values, each layer
   appending and de-duplicating (`if n not in out: out.append(n)`).
2. `plugins.resolve(names, repo)` (`switchboard/plugins.py:94-110`) turns each name into
   actual **prompt text**: a matching file's flattened contents, or — if no file matches —
   the name itself passed through verbatim as a literal instruction. This is where "an
   unknown value is used as a literal instruction" (the CLI help text, `cli.py:123`) is
   implemented: nothing distinguishes a typo'd plugin name from an intentional inline
   instruction; both just become prompt lines.
3. Each resolved line is validated again (see §2) and the resulting list `with_` (list of
   strings) is passed straight through to `Broker.delegate(..., with_=with_, ...)`.
4. Inside `Broker.delegate` (`switchboard/broker.py:867-948`), the full system prompt is
   assembled as a list and `with_` is simply the **last** section, appended verbatim:
   ```python
   prompts = [
       self._protocol(),
       self._say("spawn.identity", name=name, role=role, parent=me),
   ]
   if ws:
       prompts.append(self._say("spawn.workspace", workspace=ws, path=where))
   if as_prompt:
       prompts.append(as_prompt)
   elif r.prompt:
       prompts.append(r.prompt)
   prompts.extend(with_)                                    # <- broker.py:907
   ```
   `prompts` (a `list[str]`) is passed to `self.h.start_agent(name, pane, prompts=prompts,
   model_args=...)` (`switchboard/broker.py:935-937`) — herdr receives each string as a
   separate `--append-system-prompt` argument (implied by validate.py's comments,
   `switchboard/validate.py:15-16`; the actual herdr call construction is in
   `switchboard/herdr.py`, not reproduced here since it's outside this doc's file-format
   scope, but the *contract* — a list of single-line strings, each becoming one system
   prompt append — is fully determined at this call site).

### Precedence / ordering vs `--role` and `--as`

Exact assembly order (`switchboard/broker.py:897-907`, reproduced above):

1. **Protocol** — always first, always present (`self._protocol()`).
2. **Identity fragment** — `spawn.identity`, always present (name/role/parent).
3. **Workspace fragment** — `spawn.workspace`, only if the child is in a named workspace.
4. **Either** `as_prompt` (if `--as` was given) **or** the role's own `prompt`
   (`r.prompt`, from role file/config) — mutually exclusive, `--as` wins outright and
   **replaces** the role's prompt entirely rather than adding to it.
5. **Plugins** (`with_`), always last, appended as N separate strings (one per resolved
   name/literal), each already itself flattened to one line.

So plugins never precede or interleave with the role prompt — they are strictly
appended after everything else, meaning in the assembled context they read as the
final, most-recent instructions (recency bias in an LLM system prompt would tend to
weight them highly, though that's an inference about model behavior, not something
verified in this codebase).

Note `--role` and `--as` interact at step 4 only; `--with` accumulation (which plugin
names get resolved) happens **before** any of this in `plugins.for_role`, and does not
see or depend on whether `--as` was given — an ad-hoc `--as` prompt still gets the role's
normal plugin *bindings* (`for_role` looks up `per_role.get(role, ())` using the literal
`--role` value regardless of `--as`), even though the role's own written `prompt` is
discarded in favor of `as_prompt`.

### Unknown `--with` values

As above (§3.2 step 2): an unrecognized name is not an error. `plugins.resolve()`
(`switchboard/plugins.py:108-109`) appends it to the output list as-is:
```python
else:
    out.append(n)
```
It is then validated as ordinary prompt text (`validate.line`, `MAX_PROMPT`=8000 chars,
no newlines, no control chars) and appended to the spawned agent's system prompt exactly
like a resolved plugin file would be. This is documented behavior, called out both in the
CLI help (`cli.py:123`) and in the `plugins.py` module docstring (`switchboard/plugins.py:25-26`):
"a one-off instruction still works without creating a file for it."

### Inheritance by grandchildren

**Not inherited.** Nothing in `Broker.delegate` threads a parent's `with_` (or its
resolved prompt list at all) onto any child that agent later spawns. Each `sb delegate`
call independently recomputes `plugins.for_role(b.repo, args.role, args.with_)` from
scratch using only:
- the repo's shipped+override `all` bindings,
- the **new child's own** `--role` value's bindings,
- the **new child's own** `--with` flags on that specific call.

A grandchild spawned by a child that received `--with adversarial` gets `adversarial`
only if the grandchild's own `sb delegate` call also names `--with adversarial` (or its
own role is separately bound to it in `plugins.toml`). There is no propagation mechanism
of any kind — no environment variable, no stored per-agent plugin list, nothing in the
`agents` table schema (`switchboard/store.py:128-147`) records which plugins/prompts an
agent was spawned with at all; that information exists only transiently in the
`prompts` list handed to `herdr.start_agent` and is never persisted.

---

## 4. Role prompts

### Where they live

Three layers, most general first (`switchboard/config.py:299-322`, module docstring at
`switchboard/roles.py:1-17`):

```
defaults/roles/*.md          shipped, one markdown file per role
<repo>/.switchboard/roles.toml    this repo's field-level overrides, single file
<repo>/.switchboard/roles/*.md    this repo's own role files, same format as shipped
```

Filenames/dirnames from `defaults/settings.toml:18-19`: `roles_file = "roles.toml"`,
`roles_dir = "roles"`.

### File format (role files)

TOML front matter, fenced with `+++` (not `---`, deliberately — `---` is a markdown
horizontal rule and so ambiguous; see `switchboard/config.py:57-59`), then the prompt body
as plain markdown. Example, `defaults/roles/reviewer.md:1-13`:

```markdown
+++
model   = "default"
cleanup = "close"
+++

<!-- comment, stripped on flatten -->

Review critically. State clearly whether it passes, and list concrete problems.
```

Parsed by `config.front_matter()` (`switchboard/config.py:235-251`) — a file with no
`+++` fence at all is legal too and is treated as all-prose (`switchboard/config.py:243`),
making a bare one-line role file valid. Fields recognized: `model` (a *tier* name, never
a raw model id — `switchboard/roles.py:39` and its comment), `cleanup` (`"close"` or
`"keep"`). The body, if non-empty after `config.flatten()`, becomes the role's `prompt`
field; an override file that is front-matter-only leaves the shipped prompt untouched
(`switchboard/config.py:348-351`).

### Merging

`config.roles()` (`switchboard/config.py:299-322`): shipped markdown loaded first
(`_roles_from_dir(defaults_dir()/"roles")`), then `<repo>/.switchboard/roles.toml`
entries are merged **field-by-field** on top (`merge(out.get(name, {}), cfg)` —
`switchboard/config.py:321`), then `<repo>/.switchboard/roles/*.md` merged on top of
that. Field-by-field merge means `[reviewer] model = "strong"` in a repo's `roles.toml`
changes only the tier, leaving `cleanup` and `prompt` exactly as shipped
(`switchboard/roles.py:15-16` docstring; `switchboard/config.py:309-310`).

Five shipped roles, all in `defaults/roles/`: `designer.md`, `orchestrator.md`,
`researcher.md`, `reviewer.md`, `worker.md`. Summarized: designer (`strong` tier, kept
open — `defaults/roles/designer.md`), orchestrator (`default` tier, kept, the single
role used at every delegation scope from `sb start` down to a sub-orchestrator's own
children — `defaults/roles/orchestrator.md`), researcher (`cheap` tier, closed —
`defaults/roles/researcher.md`), reviewer (`default` tier, closed, verdict mandatory —
`defaults/roles/reviewer.md`), worker (`default` tier, closed, the fallback role for both
"no `--role` given" and "an undefined `--role` name" — `defaults/roles/worker.md`).

### Loading and unknown roles

`roles.load(repo)` (`switchboard/roles.py:68-75`) builds `Role` objects from the merged
dict, each carrying a reference to the loaded model `Tiers` table.
`roles.get(roles_dict, name)` (`switchboard/roles.py:78-90`) is the lookup an unknown
`--role` value goes through: if the name isn't in the merged dict, it inherits the
`fallback_role`'s (`vocabulary.fallback_role = "worker"`, `defaults/settings.toml:68`)
`model`, `cleanup`, and `prompt` fields **but keeps its own name** — so `--role
archaeologist` spawns an agent literally named/labeled `archaeologist` that behaves
exactly like `worker` in every other respect (tier, cleanup, prompt).

### How role prompts compose with plugins

Already covered in full in §3's "assembly order" — the short version: the role's own
`prompt` field is one single, fixed position in the assembled system prompt (position 4
of 5, and only present if `--as` was NOT given), always **before** any plugin text and
never merged with it beyond simple list concatenation.

### The exact system-prompt assembly order

Restated for completeness, this is the definitive answer to "how is the whole system
prompt for an agent assembled" (`switchboard/broker.py:897-907`):

```
1. protocol                         config.protocol(repo) — flattened defaults/protocol.md
                                     or repo's .switchboard/protocol.md (REPLACES, no merge)
2. spawn.identity                   "You are agent '{name}', role '{role}'. Your parent is '{parent}'."
3. spawn.workspace   [conditional]  only if spawned into a named workspace
4. as_prompt OR role.prompt         --as text wins outright; else the role's own prompt
5. with_ (N entries)                each resolved --with plugin, appended in resolution order
```

Each of these five "prompts" is handed to herdr as a **separate list element**
(`h.start_agent(name, pane, prompts=prompts, ...)` — `switchboard/broker.py:935-937`),
each independently already flattened to a single line before it's added to the list (the
protocol via `config.protocol()`'s own `flatten()` call, `switchboard/config.py:367`; the
`spawn.*` fragments via `config.prompt()` → `prompts()`'s per-entry flatten,
`switchboard/config.py:388-389`; the role prompt via `_roles_from_dir`'s flatten,
`switchboard/config.py:347`; plugin/literal entries via `plugins.resolve()`'s own
`flatten()` call, `switchboard/plugins.py:105`). Nothing joins these five strings into one
big string in Python — that concatenation, if any, happens on herdr's/the CLI's side via
however many `--append-system-prompt` flags are passed.

---

## 5. Adjacent extension surface

### Hooks

**Not implemented in code.** `notes/HOOKS.md` is a design/research note (not
wired into `switchboard/`), and its own text flags itself as partially wrong and
superseded (`notes/HOOKS.md:1-26`) — it discusses using `claude --settings <file>` (not
`--bare`, which would skip hooks) to inject a session-scoped Stop hook, but this describes
a *future, unimplemented* mechanism, not current behavior. `grep -rn hook
switchboard/*.py` found no hits — confirmed no hook system exists in the shipped Python
today.

### Config files (`.switchboard/*`)

All resolved by `config.py`'s `[paths]` table (`defaults/settings.toml:12-25`), each
`<name>` below relative to `<repo>/.switchboard/` (`paths.repo_dir`,
`defaults/settings.toml:14` — the one setting that must live in the shipped file only,
since it names the directory settings themselves are read from):

| path | purpose | layering |
|---|---|---|
| `roles.toml` | field-level role overrides | merges field-by-field onto `defaults/roles/*.md` |
| `roles/*.md` | this repo's own/overriding role files | merges onto the above two |
| `models.toml` | tier→(provider, model, effort) overrides | merges onto `defaults/models.toml` and the global per-user layer (see §7-adjacent, `models.py`) |
| `plugins.toml` | plugin bindings (`all`, `[roles]`) | joins (array-join) onto `defaults/plugins.toml` |
| `plugins/*.md` | this repo's own plugin files | **not merged** — repo file of the same stem replaces the shipped one; repo can add new stems freely |
| `protocol.md` | full replacement agent protocol | **replaces**, not merged, `defaults/protocol.md` |
| `prompts.toml` | `[spawn]`/`[notify]` fragment overrides | merges entry-by-entry onto `defaults/prompts.toml` |
| `settings.toml` | paths/vocabulary/limits/timeouts/etc. | merges table-by-table onto `defaults/settings.toml` |

Plus one file **outside** `.switchboard/`: `<repo>-parent>/.git/agentflow/config.json` —
see store paths below; not markdown/TOML, JSON, and not part of the `config.py` layering
system at all (it's read/written by `store.py` directly).

### Env vars

Found via `grep -rn os.environ switchboard/*.py`:

| var | read at | purpose |
|---|---|---|
| `CLAUDE_CODE_SESSION_ID` | `switchboard/broker.py:215, 256` | identifies the calling agent in `whoami()`/`_claim_session()` — injected into every Claude Code session by the provider CLI itself |
| `HERDR_PANE_ID` | `switchboard/broker.py:224` | fallback identity lookup when no session id is set yet — injected into every herdr-spawned pane |
| `HERDR_WORKSPACE_ID` | `switchboard/broker.py:857` | 3rd-priority fallback (of 4) for "which herdr workspace does a child belong in" |
| `SWITCHBOARD_DEFAULTS` (`config.ENV_DEFAULTS`, `switchboard/config.py:47`) | `switchboard/config.py:74` (`defaults_dir()`) | replaces the shipped `defaults/` directory wholesale — used by the test suite, and documented as "the escape hatch for shipping a different baseline to a team" (`defaults/README.md:44`) |
| `SWITCHBOARD_MODELS_CONFIG` (`models.ENV_GLOBAL_CONFIG`) | `switchboard/models.py:237` | overrides the per-user global models file path (default `~/.config/switchboard/models.toml`) |
| `NO_COLOR` | `switchboard/board.py:57` | disables ANSI color in the board view — standard convention, unrelated to plugins/config layering |

### Where sb stores state — global vs. repo vs. worktree, precisely

Three distinct locations, each with a distinct scope:

1. **The operational store (sqlite)** — `switchboard/store.py:78-79`:
   ```python
   def db_path(cwd=None) -> Path:
       return repo_root(cwd) / _STORE_DIRNAME / "state.db"
   ```
   `repo_root()` (`switchboard/store.py:44-59`) is `git rev-parse --git-common-dir`,
   anchored absolute — i.e. **the shared `.git` directory**, which is the *same physical
   location* from every worktree of a repo (`_STORE_DIRNAME = "agentflow"`,
   `defaults/settings.toml:36`). So the sqlite store — the `agents`/`messages`/`events`
   tables (schema at `switchboard/store.py:127-174`) — is **one file per repo**, shared
   across the main checkout and every worktree, on purpose: "a top-level orchestrator on
   the main checkout and its children in worktrees must share one store or parent links
   do not survive" (`switchboard/store.py:33-38`). This store is explicitly disposable —
   dropped and recreated wholesale on any non-additive schema change
   (`switchboard/store.py:190-218`), with a live-agent guard to avoid pulling the rug out
   from under a running workflow (`switchboard/store.py:279-316`).
2. **Local JSON config beside the store** — `switchboard/store.py:82-107`
   (`config_path`/`read_config`/`write_config`): `<repo_root>/agentflow/config.json`,
   same shared `.git`-relative location as the sqlite file, but deliberately **not** a
   table inside it — "the database is disposable by design and gets dropped on a schema
   change, whereas this must survive that" (`switchboard/store.py:85-87`). Currently holds
   exactly one key, `main_checkout`, written once by `sb init` (`switchboard/broker.py:323-334`,
   `store.write_config`) and read by `main_checkout()` (`switchboard/store.py:110-120`) to
   find "where the true config files live" — i.e., this is what lets a worktree find the
   main checkout's `.switchboard/` directory to symlink from (see `link_config` below).
3. **The repo's own config layer**, `<repo>/.switchboard/` — this is **per-worktree on
   disk**, but made effectively single-copy via symlinks: `Broker.link_config()`
   (`switchboard/broker.py:276-303`) is called before anything spawns into a worktree
   (`switchboard/broker.py:909`, inside `delegate`) and symlinks `CLAUDE.md` and
   `.switchboard` (`LINKED_CONFIG = config.setting("paths.linked_config")` →
   `defaults/settings.toml:41`, `linked_config = ["CLAUDE.md", ".switchboard"]`) from the
   main checkout into the worktree, if the worktree doesn't already have real files there.
   Symlinks are excluded from `git status` via `.git/info/exclude`
   (`switchboard/broker.py:305-321`) since they're "local config, not committed." So there
   is exactly one true `.switchboard/` per repo (the main checkout's), and every worktree
   sees it via symlink unless a worktree author deliberately puts a real file/dir there to
   diverge (which `link_config` will not clobber — `switchboard/broker.py:293`, `dst.exists()`
   check).
4. **Global, per-user** — the one layer outside any repo: `~/.config/switchboard/models.toml`
   (default; overridable via `SWITCHBOARD_MODELS_CONFIG`), sitting between shipped tiers
   and a repo's own `models.toml` in the tier-resolution chain
   (`switchboard/models.py:14-16` docstring; `defaults/settings.toml:30`). This is the
   **only** global per-user config file in the system — everything else in `.switchboard/`
   is repo-scoped (shared via the symlink trick above, never truly global).
5. **Transcripts** — not written by switchboard at all: Claude Code's own on-disk
   transcript, found by `store.transcript_path()` (`switchboard/store.py:668-678`) at
   `~/.claude/projects/<slugified-cwd>/<session_id>.jsonl`, read but never written by
   `sb`.

### How sb discovers the repo/worktree it is in

- `store.repo_root(cwd)` (`switchboard/store.py:44-59`): `git rev-parse
  --git-common-dir`, resolved absolute against `cwd` — the **shared** `.git`, identical
  from any worktree of the same repo. Used exclusively for locating the shared store.
- `store.worktree_root(cwd)` (`switchboard/store.py:62-75`): `git rev-parse
  --show-toplevel` — **this** worktree specifically. This, not `repo_root()`, is what
  `cli.py:381` uses to construct the `Broker`'s `repo` attribute
  (`repo = store.worktree_root()`, with the comment "THIS worktree, not the main checkout
  ... which is deliberately identical from every worktree" at `switchboard/cli.py:379-380`)
  — i.e. all the `.switchboard/` config-layer reads described above resolve relative to
  the **current worktree's** root, which (via the symlink trick) usually just re-finds the
  main checkout's files anyway.
- Both are plain `subprocess.run(["git", ...])` calls with no herdr involvement — sb's
  repo/worktree discovery is entirely independent of herdr's own idea of "workspace."

### Relation to herdr

herdr is a separate, external CLI/adapter (`switchboard/herdr.py`) that switchboard
shells out to for everything about *panes, agent processes, and workspaces* — it is "the
only module that knows herdr exists" (`switchboard/herdr.py:1-7`). Concretely:
switchboard's own concept of "workspace" (a named worktree + herdr workspace + lead
agent, `switchboard/broker.py:58-63`) is a **switchboard-level abstraction built on top
of** a herdr workspace id (`workspace_id` column, `switchboard/store.py:137-140`) plus a
git worktree/branch of the same name; herdr owns pane lifecycle (`create_tab`,
`create_worktree`, `open_worktree`, `start_agent`, `close_pane`, etc., all called via
`Broker._call_adapter` at `switchboard/broker.py:651-658`) and reports agent state
changes back to switchboard's sqlite store via `on_event` callbacks wired at
`switchboard/cli.py:378`. herdr's own binary compatibility is pinned/verified:
`[herdr] min_version = "0.8.0"` (`defaults/settings.toml:249`), checked by `sb doctor`.
herdr has no concept of switchboard's roles or plugins at all — it only ever receives a
flat list of prompt strings and model CLI flags at `start_agent` time
(`switchboard/broker.py:935-937`).

---

## 6. CLI architecture

### Subcommand registration

Plain `argparse`, built fresh on every invocation in `build_parser()`
(`switchboard/cli.py:75-251`). No plugin/entry-point discovery of subcommands — every
verb is a literal `sub.add_parser(...)` call in one function, wrapped by a local `cmd()`
helper (`switchboard/cli.py:97-100`) that also tracks which names should show in
`--help` (`visible: list[str]`) versus hidden ones (`board`, via
`cmd("board", hidden=True)` — `switchboard/cli.py:115`).

Agent-facing verbs (7): `delegate`, `ask`, `tell`, `inbox`, `done`, `block`, `status`.
Human-facing / operational verbs (~10): `start`, `init`, `doctor`, `cleanup`, `restore`,
`interrupt`, `inspect`, `wait`, `log`, `plugins`, `models`, `workspace` (this last has its
own nested subparser, `wsub`, for `workspace new` — `switchboard/cli.py:197-209`).

`--json` is available both globally (`p.add_argument("--json", ...)`,
`switchboard/cli.py:77`) and per-subcommand via a shared `common` parent parser
(`switchboard/cli.py:87-89`) that every `cmd()`-built subparser inherits
(`parents=[common]`) — engineered specifically so both `sb --json <cmd>` and `sb <cmd>
--json` work (comment at `switchboard/cli.py:79-86`), using `argparse.SUPPRESS` as the
subcommand-level default so it only ever *sets* the flag, never resets it.

### Where the code lives / module layout

Flat package, no subpackages:

```
switchboard/
  __init__.py
  cli.py         argparse + dispatch (the only module every invocation touches)
  broker.py      M3 — the whole agent-facing contract (delegate/ask/tell/done/block/...)
  herdr.py       M2 — the only module that knows herdr's CLI exists
  store.py       M1 — sqlite, the single source of truth; modules "meet" here, never call each other directly
  config.py      the only module that reads config files (TOML/markdown layering)
  plugins.py     plugin discovery/binding/resolution (thin, built on config.py)
  roles.py       role loading/resolution (thin, built on config.py)
  models.py      model-tier resolution (provider/model/effort)
  validate.py    pure input validation, no I/O beyond reading config for limits
  status.py      read-side joins of store + herdr (status/inspect/wait rendering)
  output.py      terminal/transcript reading helpers (used by status.py's inspect)
  board.py       the human-only live TUI/board view
```

The module docstrings explicitly label the M1/M2/M3 architecture (store/herdr/broker) and
state the rule "modules never call each other, they meet here [store.py]"
(`switchboard/store.py:1-9`). `plugins.py` and `roles.py` sit above `config.py` as thin,
domain-specific readers; `cli.py` is the only place that imports and coordinates all of
them together (`switchboard/cli.py:28-36`).

### Dynamic / extensible dispatch — existing precedent

There is exactly **one** precedent for "vocabulary is data, not code" extended to
runtime-open sets, and it is *not* CLI verbs — it's role names, plugin names, and tier
names:

- **Roles**: `roles.get()` (`switchboard/roles.py:78-90`) explicitly accepts any string
  as `--role`, falling back field-by-field to the `fallback_role`'s definition while
  keeping the caller's own name. This is the closest thing to "open dispatch" in the
  codebase, and it is deliberately **not** a lookup-or-error — see `switchboard/roles.py:1-4`,
  "Vocabulary is data (C12) — there is no closed set, and a role that isn't defined still
  works with defaults."
- **Plugins**: same openness, one level further — an unrecognized `--with` value isn't
  even given a fallback definition, it's used as literal text (§3).
- **Model tiers**: `ModelSpec` resolution treats an unknown tier name as a raw model id
  passed straight to the provider (`switchboard/roles.py:61-65` comment: "An unknown
  tier name passes through as a model id").

**CLI subcommands themselves are the opposite of this** — a fixed, hardcoded `argparse`
tree with **no** dynamic registration, no plugin-discovery mechanism (no `entry_points`
scanning, no directory of Python files auto-imported, nothing resembling
pytest/click-plugin style extension), and no way for a third party to add a new `sb
<verb>` without editing `cli.py` directly. `build_parser()` is a single ~180-line
function; adding a subcommand means adding a call inside it and a branch inside
`_dispatch()` (`switchboard/cli.py:415-639`, one long `if cmd == "...":` chain, terminated
by `return 2` for anything unmatched at `switchboard/cli.py:639`).

### What would make adding third-party subcommands easy or hard

Hard, currently:
- `build_parser()` and `_dispatch()` are both single monolithic functions in one file;
  there's no registry object, decorator, or discovery loop a third party could hook into
  without patching `cli.py` itself.
- `_validate()` (`switchboard/cli.py:254-341`) is a third parallel `if cmd == "...":`
  chain that every new verb must also extend — validation is not colocated with a verb's
  definition or dispatch, it's a third place to touch.
- No Python entry-point / plugin-loading mechanism exists anywhere in the package (no
  `importlib.metadata.entry_points()` calls, no dynamic `import` of anything outside
  `switchboard/` itself, confirmed by the module list in §6 above and the absence of any
  packaging metadata — see §8).

Easy, as precedent to build from:
- The config-layering system (`config.py`) already solves "shipped defaults + per-repo
  override, merged" generically and well, and is reused identically by five different
  concerns (roles, plugins, prompts, settings, protocol) — a sixth kind of pluggable
  *data* (not code) would fit this pattern cleanly.
- Every subcommand handler already receives the same three objects (`args`, `b: Broker`,
  `db`, `h: Herdr`) via `_dispatch(args, b, db, h)`, so a hypothetical dynamic-dispatch
  layer would have a stable, small interface to call into.

---

## 7. Persistence layer

Answered in detail across §5 (state locations) and here directly:

- **DB**: sqlite3, one file, `<shared .git>/agentflow/state.db`
  (`switchboard/store.py:41, 78-79`). WAL mode (`PRAGMA journal_mode=WAL`,
  `switchboard/store.py:202`) because "many short-lived `sb` processes writing" is the
  normal access pattern (`switchboard/store.py:24-26`). `busy_timeout` set from
  `timeouts.database = 10.0` (`defaults/settings.toml:191`).
- **Schema**: three tables, no ORM, raw SQL, full text at `switchboard/store.py:127-174`:
  - `agents` (name PK, parent, role, task, state, session_id, cwd, workspace,
    workspace_id, terminal_id, pane_id, seq, cleanup, created_at, ended_at) — indexed on
    `session_id` and `parent`.
  - `messages` (id PK autoincrement, from_agent, to_agent, kind ∈ {ask,tell,done}, body,
    reply_to → messages.id, created_at, read_at, delivered_at) — indexed on
    `(to_agent, read_at)`, `(to_agent, delivered_at)`, `reply_to`.
  - `events` (id PK autoincrement, agent, kind, payload JSON, created_at) — indexed on
    `(agent, id)`. This is the append-only debug log (`sb log`).
  - Plus a bare `meta` table (`key TEXT PRIMARY KEY, value TEXT`,
    `switchboard/store.py:205`) used for two unrelated things: `schema_hash` (schema
    versioning) and `board_pane:<name>` (which pane holds a human's open board view,
    `switchboard/broker.py:488-513`).
- **No migrations.** Explicitly: "There are no migrations. Everything in here is
  operational state, so on a schema change we simply drop and recreate — unless agents
  are live" (`switchboard/store.py:192-195`). A schema-hash comparison
  (`switchboard/store.py:176, 207-218`) decides additive-vs-destructive on `connect()`;
  additive changes get `ALTER TABLE ADD COLUMN` (`switchboard/store.py:242-268`),
  anything else triggers `_reset()` (drop + recreate, `switchboard/store.py:271-316`),
  guarded against wiping a live workflow by checking herdr's own live-agent list
  (`_herdr_alive()`, `switchboard/store.py:318-329`), overridable with `--force` via `sb
  doctor --reset-store --force` (`switchboard/cli.py:174-178, 418-426`).
- **Nothing about plugins, roles, or prompts is persisted in this store at all.** The
  `agents` table's `role` column records the role *name* a delegate call used (a plain
  string), but not which tier that resolved to, not the role's prompt text, not the
  plugin list, not the assembled system prompt — none of that is durable anywhere once
  the agent has spawned. (The one exception: `task`, the literal task string, is stored
  and re-readable, `switchboard/store.py:132`.)

### Could a functional module reuse it, and what would that cost?

- **Reuse is structurally easy at the SQL level**: it's a single unguarded sqlite
  connection (`store.connect()`, `switchboard/store.py:190-218`) any in-process code can
  query directly (no ORM abstraction to work around), and `events` in particular is
  already a generic `(agent, kind, JSON payload)` append log designed to take arbitrary
  keys (`store.log_event(db, *, kind, agent=None, **payload)` —
  `switchboard/store.py:638-650`) — a new module could `log_event(db, kind="my_thing",
  ...)` today with zero schema changes.
- **The cost of going further** (a genuinely new table, e.g. to persist an agent's
  resolved plugin list): every schema change is either additive (safe, but a NOT NULL
  column needs a literal default per `_migrate_additive`'s check,
  `switchboard/store.py:260-261`) or destructive (triggers the whole live-agent-guarded
  reset dance described above) — there is no independent versioning per subsystem; **all
  three tables share one schema hash** (`_SCHEMA_HASH = hashlib.sha256(SCHEMA.encode())`,
  `switchboard/store.py:176`, computed over the *entire* `SCHEMA` string), so a new
  module's table addition bumps the hash and forces the same reset-or-migrate decision
  for the whole store, not just its own table. A functional module wanting a fourth table
  would need to add it to the one shared `SCHEMA` string in `store.py` — there's no
  extension point for a module to register its own table independently.
- **The store is explicitly documented as disposable** (`switchboard/store.py:6-8`): "The
  only durable data (learnings) lives in JSON files, so this database is disposable by
  construction." (Note: no `learnings`-related JSON files or code were found in this
  worktree via the file listing in the initial `find`; this sentence in the module
  docstring may describe a planned or removed feature — not verified further, flagging
  rather than asserting.) Anything a new module stores in this sqlite file should be
  genuinely disposable/operational, not something that must survive a schema reset.

---

## 8. Packaging / install

- **No `pyproject.toml`, `setup.py`, or `setup.cfg`** anywhere in the repo root (checked
  directly — none exist). This is **not** an installable Python package in the
  `pip install` sense; there is no packaging metadata at all.
- **Entry point**: `bin/sb`, a plain executable Python script:
  ```python
  #!/usr/bin/env python3
  import sys, os
  sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
  from switchboard.cli import main
  raise SystemExit(main())
  ```
  It works by inserting the repo root onto `sys.path` at runtime and importing
  `switchboard.cli` directly — i.e. `sb` only runs correctly when `bin/sb` is executed
  from (or symlinked/PATH-added from) a checkout of this exact repository. There is no
  installed/copied version separate from the source tree.
- Running `sb` therefore requires: this repo cloned somewhere, `bin/sb` on `PATH` (or
  invoked by full/relative path), and the `switchboard/` package importable relative to
  it — no virtualenv packaging, no version pinning, no dependency declarations found
  (the only imports used across the modules read are stdlib: `argparse`, `json`,
  `sqlite3`, `subprocess`, `tomllib`, `pathlib`, `dataclasses`, `re`, `time`, `os`, `sys`,
  `hashlib`, `inspect` — no third-party runtime dependency was observed in any file read
  for this investigation).

### What this permits for a functional module

Given no packaging metadata exists at all:
- **Shipping inside the `sb` package** would mean adding a new `switchboard/<name>.py`
  module and wiring it into `cli.py`'s `build_parser()`/`_dispatch()`/`_validate()` by
  hand (see §6) — there is no plugin-loading indirection to hook into instead; "inside the
  package" and "editing `cli.py`" are currently the same thing.
- **As a separate installable** (its own PyPI-style package) is not precedented by
  anything in this repo — there's no `entry_points` mechanism switchboard itself defines
  or consumes (confirmed: no `importlib.metadata` usage anywhere in `switchboard/*.py`),
  so a separate package could not currently register itself as an `sb` subcommand or
  plugin without switchboard *first* growing some discovery mechanism (an entry-point
  group, a scanned directory of Python files, etc.) — none exists today.
  presence today.
- **As files in a repo** (i.e., markdown/TOML content only, no Python) is exactly what
  the existing `.switchboard/` layering already supports well: roles, plugins, prompts,
  settings, protocol are all "just files a repo drops in," discovered and merged
  automatically with zero code changes needed per-repo (§5's config-file table is the
  complete list of what's pluggable this way today). This is the **only** one of the
  three shipping models the current codebase actually supports without modification.

---

## Constraints and sharp edges a redesign must not break

1. **No newlines, ever, in anything that becomes an agent argument.** This is a herdr
   hard constraint (`invalid_agent_argument`), not a switchboard preference — it's why
   plugin/role/protocol files are all authored multi-line and flattened before send
   (`switchboard/config.py:216-232`, `switchboard/validate.py:11-19`). Any new
   prompt-contributing surface must flatten the same way or reuse `config.flatten()`.

2. **Plugin *files* are intentionally not layered from `defaults/` into every repo —
   only bindings are.** (`switchboard/plugins.py:14-19`, `defaults/README.md:31-34`) A
   redesign that starts auto-merging shipped plugin files into every repo would silently
   reverse this "no forced-in default behaviour" guarantee — it's a deliberate,
   documented choice, not an oversight.

3. **Unknown `--with` values are literal instructions, not errors.** (`switchboard/plugins.py:94-110`,
   `switchboard/cli.py:123`) This is explicitly documented, user-facing behavior
   ("throwaway customization needs no file at all" — `switchboard/plugins.py:25-26`).
   Breaking it (e.g., by validating `--with` names against known plugins) would break a
   currently-supported one-off workflow.

4. **Every schema change to the sqlite store is all-or-nothing across all three tables**
   (one shared `_SCHEMA_HASH` — `switchboard/store.py:176`), and a non-additive change
   requires either no live agents or `--force`. A new persistence need should either fit
   the additive-migration path cleanly (new nullable/defaulted columns) or accept the
   live-agent-guarded reset semantics; it cannot get its own independent versioning.

5. **`agents.name` is the concurrency arbiter for spawns** (`switchboard/store.py:384-416`
   docstring) — claims happen via `INSERT OR IGNORE` racing on the primary key, *before*
   herdr is asked to do anything. Any new module that also wants to "claim" a name/slot
   must respect this same claim-before-act ordering or reintroduce the exact race
   documented as previously costing ~1-in-25 workspace opens.

6. **The protocol replaces, everything else in `.switchboard/` merges/joins.** Only
   `protocol.md` is whole-file-replace (`switchboard/config.py:360-367`); roles/settings/
   prompts merge field-by-field, plugin *bindings* array-join with `"!reset"` as the
   explicit escape hatch (`switchboard/config.py:170-211`). A redesign introducing new
   config surfaces should pick one of these two existing merge semantics rather than a
   third, undocumented one.

7. **No plugin/role/prompt data is persisted per-agent.** Once an agent is spawned, the
   assembled system prompt is gone from switchboard's own state — only `role` (name) and
   `task` survive in the `agents` row. A redesign that wants to answer "what plugins did
   agent X actually get" after the fact has no current data source for that; it would
   need a new column/table (subject to constraint #4).

8. **`--with` accumulation currently ignores `--as`.** Plugin bindings for a role apply
   even when `--as` discards that role's own written prompt (§3, "Precedence"). Worth
   flagging as a possible inconsistency to deliberately keep or deliberately fix, not
   silently change.

9. **The `own-files.md` / multi-agent-editing plugins assume file-level ownership
   discipline is purely a prompt-level social contract** — there is no enforcement
   mechanism (no locking, no git-level ownership check) anywhere in the codebase. A
   redesign must not accidentally imply otherwise.

10. **`bin/sb` has zero packaging** — no version pin, no dependency declarations, works
    only via a hardcoded relative `sys.path.insert`. Any redesign that assumes `pip
    install`-style discoverability (entry points, installed package metadata) is
    assuming infrastructure that does not exist yet and would need to be built first.

11. **The `ask-dont-guess.md` shipped plugin is currently self-contradictory with
    `broker.py`**: it tells agents to run `sb ask human`, but `Broker.ask()` explicitly
    refuses any target that resolves to the human
    (`switchboard/broker.py:1026-1033`, raising `ValueError` pointing at `sb block`
    instead). This is a pre-existing bug/staleness in shipped plugin content, not
    something introduced by this investigation — flagged here since a redesign touching
    plugin content should not propagate it.
