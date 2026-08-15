# How switchboard builds and delivers an agent's prompt, and where a second CLI would plug in

Investigation only, no code changed. All claims cited `file:line`. `DESIGN-TRUTH.md` is the
only trusted doc; everything else (comments, `research/*.md`) is context, not fact, unless
checked against code — noted below where it wasn't checkable against code.

## 1. Where the prompt text lives, and composition order

Every fragment is markdown on disk, flattened to one line at spawn time
(`config.flatten`, `switchboard/config.py:261-277` — strips HTML comments, drops
headings, turns bullets into `; `-separated clauses, collapses whitespace). Flattening
exists only because of a downstream constraint, not a choice: herdr refuses a newline
in an agent argument (`switchboard/herdr.py:544-555`).

`Broker.delegate` (`switchboard/broker.py:3200-3400`) is the one place every spawn
passes through (`sb start`, `sb delegate`, `sb workspace new` — see comment at
`broker.py:3031-3034`), and it assembles the `prompts` list in this exact order
(`broker.py:3287-3308`):

1. **Protocol** — `self._protocol()` (`broker.py:556-558`) → `config.protocol()`
   (`config.py:441-448`). Shipped text is `defaults/protocol.md`; a repo's own
   `.switchboard/protocol.md` *replaces* it wholesale (no merge — a protocol assembled
   from two halves is called out as unreadable, `config.py:444-447`).
2. **Identity fragment** — `spawn.identity` from `defaults/prompts.toml`, filled with
   name/role/parent (`broker.py:3289`, via `_say`/`config.prompt`, `broker.py:560-566`,
   `config.py:474-489`).
3. **Role list** — `spawn.roles`, the sorted list of every known role name, generated
   from the merged role table, never a hardcoded string (`broker.py:3294-3300`).
4. **Workspace fragment** — `spawn.workspace`, only if the agent has a workspace
   (`broker.py:3302-3303`).
5. **Disposition** — either the caller's literal `--as` text, or the role's own prompt
   (`r.prompt`, loaded by `roles.load`/`config.roles`) (`broker.py:3304-3307`).
6. **Preset/plugin bindings** — `self._resolve_bindings(role, with_)`
   (`broker.py:3308`, `broker.py:3021-3052`), itself layered most-general-first:
   repo-wide bindings → this role's bindings → the caller's `--with` names
   (`presets.py:178-189`, `presets.for_role`). Each name resolves to either a preset
   file's text, a plugin fragment (`@name` → `plugins.fragment`, clipped to a budget —
   `presets.py:216-255`), or a literal passthrough string.

Role definitions themselves are layered `defaults/roles/*.md` → repo
`.switchboard/roles.toml` → repo `.switchboard/roles/*.md`, field-by-field
(`config.py:380-403`, `roles.py:72-79`). A role names a **tier**, never a model id or
provider (`roles.py:27-29,39`) — model resolution is a separate concern (§3).

Presets/plugin bindings are layered shipped → `.switchboard-shared/presets.toml`
(committed, travels with the repo) → `.switchboard/presets.toml` (machine-local, joined
not replaced) (`config.py:495-513`, `presets.py:170-189`).

Everything in the list above is joined with a single space into one string
(`herdr.py:514`) and written to a **file**, not passed as an argument — see §2.

## 2. How a new agent session is launched

`Herdr.start_agent` (`herdr.py:517-598`) calls `herdr agent start <name> --kind <kind>
--pane <pane_id> --timeout <ms> -- <agent_args>`. `agent_args` is built as
(`herdr.py:557-580`):

```
--permission-mode <PERMISSION_MODE>      # "auto", defaults/settings.toml:479
--settings <hooks-settings-path>         # from hooks.stop_hook_args(), see §3
<model_args>                             # e.g. ["--model","opus","--effort","high"]
[--resume <session_id>]                  # only on restore, see §4
--append-system-prompt-file <path>       # the composed prompt, see below
```

`kind` defaults to `AGENT_KIND = "claude"` (`defaults/settings.toml:475`,
`herdr.py:37`) — this is the string herdr's own `agent start --kind` takes to know what
binary/integration it is dealing with; it is the one place herdr itself is told the
agent's *kind*.

**The prompt travels as a file, not an argument.** `Herdr._prompt_flags`
(`herdr.py:473-515`) writes the joined prompt text via `write_prompt_file`
(`herdr.py:131-155`) to
`<store_dir>/prompts/<agent-name>.txt` (`PROMPT_DIRNAME`, `herdr.py:120-129`, under the
shared `.git`, one file per agent, rewritten per spawn, deleted on `sb cleanup`
via `forget_prompt_file`, `herdr.py:158-168`). The flag handed to the provider CLI is
`--append-system-prompt-file <path>` — **this is a Claude Code flag name**, hardcoded.
The comment at `herdr.py:473-515` documents *why*: a canonical-mode shell tty truncates
a typed argument at `MAX_CANON` (1024 bytes measured), so the 12KB prompt has to arrive
as a short file-path argument instead; and Claude Code only honours the *last*
`--append-system-prompt` flag it is given if you tried to pass one per fragment
(measured, `herdr.py:507-513`), which is why it's one write, one flag.

Model tier → CLI flags: `ModelSpec.cli_args()` (`models.py:132-150`) emits
`["--model", <alias>, "--effort", <level>]` — again Claude-Code-specific flag names
(`--model` takes an alias like `sonnet`/`opus`; `--effort` takes
`low|medium|high|xhigh|max`, `defaults/models.toml` bottom). `wired_providers()`
(`models.py:73-77`, `defaults/models.toml` `[providers] wired = ["claude"]`) is the one
place that says only `claude` has a backend — an unwired provider raises
`ModelConfigError` at resolution time (`models.py:139-143`), before any spawn is
attempted.

`--permission-mode auto` (`defaults/settings.toml:479`, `herdr.py:38,557`) is also
Claude-Code-specific vocabulary — the comment at `defaults/models.toml` (haiku note)
says this flag runs a model-dependent classifier deciding what still needs human
approval, verified against real behaviour (haiku blocks, opus doesn't, same command).

Per-repo settings participate via: `.switchboard/roles.toml` /
`.switchboard/roles/*.md` (role prompts + tiers), `.switchboard/protocol.md`
(protocol override), `.switchboard/presets.toml` + `.switchboard/presets/*.md` +
`.switchboard-shared/` equivalents (preset bindings/text), `.switchboard/models.toml`
+ `~/.config/switchboard/models.toml` (tier table), `.switchboard/plugins.toml`
(plugin enablement) — all merged over the shipped `defaults/` per `config.py`'s
documented merge rules (tables merge, scalars replace, arrays join —
`config.py:17-35`). `CLAUDE.md` itself is explicitly **not** part of this path — see §3.

## 3. What is Claude-Code-specific in the launch path

- `--append-system-prompt-file`, `--permission-mode`, `--model`, `--effort`,
  `--settings`, `--resume` — all literal Claude Code CLI flags
  (`herdr.py:557-580`, `models.py:132-150`).
- The **protocol deliberately bypasses `CLAUDE.md` entirely** — comment at
  `broker.py:101-110` gives the reason: a `~/.claude/CLAUDE.md` would leak into every
  ordinary Claude session on the machine, and a repo `CLAUDE.md` would leak into every
  ordinary session in that repo and is often a tracked file switchboard must not touch.
  So the protocol travels as a system prompt fragment generated fresh at every spawn,
  never as a file an agent is told to read.
- **Hooks**: `hooks.stop_hook_args()` (`hooks.py:165-176`) writes a per-checkout
  Claude Code settings JSON (`hooks.py:91-162`) wiring `UserPromptSubmit` and `Stop`
  hooks — Claude Code's own hook-event names — to `bin/sb-activity-hook` and
  `bin/sb-stop-hook`. This is the mechanism behind `sb done` enforcement (the Stop gate,
  `hooks.py:272-321`) and the working/idle turn signal (`hooks.py:241-269`). Comment at
  `hooks.py:38-42`: verified against the real CLI that `--settings <file>` fires the
  hook and `--bare` would skip hooks outright — so `start_agent` never passes `--bare`
  (`herdr.py:562-565`).
- **Session identity**: `CLAUDE_CODE_SESSION_ID` is a Claude-Code-set environment
  variable, read in three places — `Broker.whoami` (`broker.py:603`),
  `Broker._claim_session` (`broker.py:839`), and the hook payload's `session_id`
  fallback in `hooks._agent_row` (`hooks.py:181-200`, prefers the session id, falls back
  to `HERDR_PANE_ID`). `cli.py:516` also checks `CLAUDE_CODE_SESSION_ID` /
  `CLAUDECODE` as the two env markers that say "a Claude Code session is running this
  command" (`cli.py:519-549`, `_agent_caller`), used to refuse `sb start`/`sb delegate`
  from inside a Claude Code pane run against the wrong store.
- **Transcript format and location**: `store.transcript_dir` hardcodes
  `~/.claude/projects/<sanitized-cwd>/` (`store.py:1709-1719`) and
  `store.transcript_path` looks for `<session_id>.jsonl` there (`store.py:1722-1732`).
  `output.read_transcript`/`_render_record` (`output.py:202-273`) parse Claude Code's
  own JSONL transcript record shape (`type: user|assistant`, `message.content` as
  string or a list of `{type: text|tool_use|tool_result}` parts). `output.task_arrived`
  (`output.py:138-182`) also depends on this shape and on Claude Code appending the
  submitted prompt to the transcript ~1s after submission (measured, comment there) —
  this is the delivery-confirmation proof used by `Herdr.deliver` (see §4).
- The bundled **herdr `claude` integration must stay uninstalled** — `Herdr.check`
  (`herdr.py:320-335`) refuses to run if it's installed, because it claims pane-session
  ownership and makes herdr silently drop switchboard's own state writes
  (`report_state`/`report_session` docstrings, `herdr.py:941-1036`). `herdr agent start
  --kind claude` is a *different* thing from that integration — it's herdr's own
  provider-agnostic spawn primitive with `claude` as one supported kind
  (`AGENT_KIND` setting, `defaults/settings.toml:475`); herdr's `--kind` vocabulary for
  other providers wasn't inspected here (herdr is a separate binary — see
  `herdr.py:1-11` "the only module that knows herdr exists").

## 4. Message delivery, interrupt, and restore

All of it goes through the `Herdr` adapter, which shells out to the `herdr` binary
(`herdr.py:213-214`); switchboard itself has no direct pane/socket access.

- **`sb tell` (next-turn, default)** → `Herdr.prompt` (`herdr.py:600-626`) →
  `herdr agent prompt <name> <text>`. Per the docstring (measured 3x) and
  DESIGN-TRUTH (`DESIGN-TRUTH.md:119-125`, confirmed 2026-08-09): herdr pastes the text
  into the pane's chat box and presses enter — the same channel as literal human
  typing, indistinguishable to Claude except for the `[sb: from <name>]` tag
  (`broker.py:137-154`). It queues behind any in-flight tool call and is delivered at
  the next turn boundary.
- **Delivery confirmation** — `Herdr.deliver` (`herdr.py:628-723`) doesn't trust herdr's
  own status read (a workspace-trust dialog can eat the prompt while herdr's status
  still moves, `herdr.py:645-655`, measured 3-of-4 spawns). It prefers a `proof`
  callback — `output.task_arrived`, reading Claude Code's transcript — and falls back to
  polling herdr's `agent get` for a fresh `working` transition
  (`_running_turn`, `herdr.py:828-837`) when no transcript proof is available yet.
- **`--interrupt`** → `send_keys(name, "esc")` first (cancels the live turn), then a
  fresh `prompt` call (`herdr.py:880-888`, `Herdr.send_keys` docstring). `esc` is
  called out as "the canonical Escape key name" per herdr's own CLI help — not
  Claude-Code-specific wording, but nothing here confirms *what* pressing escape means
  to a non-Claude CLI.
- **`--when-idle`** holds the ring until the target has no turn left, per
  `TELL_MODES`/comment (`broker.py:117-134`).
- **`sb restore`** (`Broker.restore`, `broker.py:4496-4604`) calls `start_agent(...,
  resume=a["session_id"])`, which appends Claude Code's own `--resume <session_id>`
  flag (`herdr.py:575-576`). It depends on the store already holding a
  `session_id` — itself only ever populated from `CLAUDE_CODE_SESSION_ID`
  (`broker.py:839-849`, `report_session`, `herdr.py:1022-1036`) or from what
  `agent.session_id` herdr's own `agent start` call returned
  (`Agent.from_json`, `herdr.py:195-207`, reading `d["agent_session"]["value"]`).
- **Readiness/idle/done detection** rests on two independent signals that both assume
  Claude Code's I/O behaviour:
  1. herdr's own terminal-scraping status (`idle|working|blocked|unknown`,
     `herdr.py:82-84`) — DESIGN-TRUTH doesn't cover its internals, and a comment in
     `hooks.py:9-13` notes herdr infers it by matching Claude's spinner glyphs in the
     terminal title, and that a Claude Code point release once changed those glyphs and
     broke it for every pane on the machine.
  2. switchboard's own turn signal, written by the `UserPromptSubmit`/`Stop` hooks
     (`hooks.py:16-18,241-269`) — entirely Claude-Code-hook-shaped, see §3.
  Both `status.py`'s stall/reconciler logic and `Herdr.deliver`'s proof lean on these
  two signals interchangeably depending on availability; neither was designed with a
  second CLI's status/hook vocabulary in mind.
- **Exit/`done` detection** is not a herdr concept at all (herdr has no `done` state —
  `report_state` docstring, `herdr.py:980-982`: "the enum is idle|working|blocked|unknown;
  herdr derives 'done' itself (idle + unfocused)"). Reporting is entirely a switchboard
  convention (`sb done`) enforced by the Stop-hook gate in §3, not by anything herdr or
  a provider CLI natively understands.

## 5. Where a second CLI agent type would have to plug in

Not asked to design this, but naming *where the seams already are*, since it bears
directly on scope:

- `models.py` — `wired_providers()` / `[providers] wired` is the one declared gate; a
  tier's `provider` field is already free-form config, just refused at resolution if
  unwired (`models.py:73-77,139-143`).
- `Herdr._prompt_flags` and `Herdr.start_agent` — the `--append-system-prompt-file`,
  `--permission-mode`, `--model`/`--effort` flag *names* are hardcoded Claude Code
  flags, not provider-conditioned (`herdr.py:473-598`).
- `hooks.py` — the whole Stop-gate/turn-signal mechanism is Claude-Code
  `hooks.json`-shaped (`UserPromptSubmit`/`Stop`, `--settings`, `--bare` avoidance).
- Session identity: `CLAUDE_CODE_SESSION_ID`/`CLAUDECODE` env vars, in `broker.py`
  (×2) and `cli.py`.
- Transcript: `store.transcript_dir`'s hardcoded `~/.claude/projects/...` path and
  `output.py`'s JSONL record parser.
- `herdr agent start --kind <kind>` already takes a `kind` string
  (`AGENT_KIND` setting) — whether herdr itself has other kinds wired was not checked;
  that lives inside the `herdr` binary, outside this repo.

Unverified / out of scope for this pass: herdr's own `--kind` vocabulary and internal
status-detection code (it's a separate binary, `herdr.py:1-11`); whether Codex's CLI
has equivalents for `--append-system-prompt-file`, `--settings`/hooks, `--resume`, or a
session-id env var — this file doesn't assert anything about Codex's own behaviour.
A `research/` directory in this repo already contains write-ups comparing Codex/Gas
Town's approach to some of these questions (e.g. `research/06-agent-comms.md`,
`research/07-gastown-github.md`) — untrusted, not checked against switchboard's code,
but flagged here as existing prior art someone already gathered.
