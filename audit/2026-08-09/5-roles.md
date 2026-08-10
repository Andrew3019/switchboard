# AUDIT GROUP 5 — roles, prompts, and what an agent knows at spawn

Audited against `/Users/andrew/.herdr/worktrees/switchboard/worker-2/DESIGN-TRUTH.md`, the
only trusted document. Every other doc in the repo, and `defaults/*` itself, was treated as
an artifact under audit. Read-only throughout: no repo file was changed, nothing staged,
nothing committed; all findings live under `/tmp`.

**Which tree was read.** The `sb` on PATH is `/Users/andrew/Code/switchboard/bin/sb` — a
different checkout (branch `main`, HEAD `caa6d20`) from the worktree under audit (branch
`worker-2`, HEAD `a9dd319`). The only difference between the two is DESIGN-TRUTH.md itself
(`git diff --stat` = one file, 308 insertions), so the code that runs is the code that was
read, and local `main` fixes none of what is called broken below. Two auditors independently
noticed `sb presets --json` resolving into the PATH checkout's `defaults/`; the contents are
identical in both.

Four auditors covered disjoint slices: spawn-time knowledge/roles/models (part A), `sb
presets` (part B), orchestrator prompt text and top-vs-workspace differentiation (part C),
and enforced topology — routing, ownership, cross-tree visibility, shared worktrees (part D).
Where an entry has both a prompt half and a code half, both were graded and the entry takes
the worse of the two.

---

## Verdicts

**SATISFIED 4 · PARTIAL 7 · BROKEN 3 · UNVERIFIED 0**

| # | Entry (DESIGN-TRUTH.md) | Verdict | Part |
|---|---|---|---|
| 1 | "If it needs to be known, it is known at spawn." (75-80) | **PARTIAL** | A |
| 2 | The role list is fine "as long as it is known that there are roles, and what roles there are" (96-97) | **BROKEN** | A |
| 3 | "Which model an agent gets is set in config" (99) | **SATISFIED** | A |
| 4 | "`sb models` is fine as it is." (267) | **SATISFIED** | A |
| 5 | "`sb presets` needs a parameter to list, and one to apply the prompt to the current chat or just read it… known to all sessions." (263-266) | **PARTIAL** (read ✓, list partial, apply BROKEN, all-sessions BROKEN) | B |
| 6 | "The orchestrator prompt is mostly good already." (150) | **PARTIAL** | C |
| 7 | "A workspace orchestrator's job is to orchestrate other agents"; review coordinated by it; no prompt for it yet (146-148) | **SATISFIED** (design predicts the absence; the absence is what is there) | C |
| 8 | "Top and workspace orchestrators must be clearly differentiated… some mechanism other than the prompt" (152-153) | **BROKEN** | C |
| 9 | "A lead's children share its worktree, so the lead assigns disjoint files" (143-144) | **PARTIAL** (worktree sharing works; the prompt never says to assign disjoint files) | C + D |
| 10 | "Like any orchestrator, it can spawn discovery or scout or research agents" (140-141) | **SATISFIED** (stated in the prompt, and the role set is genuinely open) | C + D |
| 11 | "A small task a single agent can do end to end goes to a bare agent; otherwise an orchestrator" (135-138) | **PARTIAL** | C + D |
| 12 | "Agents the top spawns directly are owned by it… can talk to each other, but they should not" (165-167) | **PARTIAL** (ownership and the permission are right; no shipped text carries the "should not") | C + D |
| 13 | "Siblings are not invisible to each other; any other top orchestrator's entire tree is invisible" (157-160) | **BROKEN** | D |
| 14 | "Only agents have the scope constraints. The board is shared." (162-163) | **PARTIAL** | D |

---

## The three sharpest gaps

**1. There is no tree boundary. (entry 13, BROKEN.)** Design says an agent cannot reach into
another top orchestrator's tree at all. In the code, `sb cleanup` is the single verb that
checks; `tell`, `ask`, `status`, `inspect`, `log`, `restore`, `interrupt` and `delegate
--workspace` are all global. Proven by running, not inferred: from inside one tree, `sb
inspect` on an agent belonging to a different top returned its full task text, working
directory and event history, and a plain `sb status` counted all 170 agents across all four
trees on this machine. The root cause is one function — name resolution is global
(`broker.py:407`) and the read verbs are never told who is asking.

**2. Nothing anywhere distinguishes a top orchestrator from a workspace orchestrator.
(entry 8, BROKEN.)** Both resolve to the same role name in `defaults/settings.toml`, the
composed system prompt for a top, a workspace lead and a sub-orchestrator is byte-identical
apart from the substituted name, parent and workspace, and no line of Python branches on
role at all. So neither the prompt half nor the non-prompt half of "clearly differentiated"
exists today. Design records the *choice of mechanism* as an open question, so this is
reported as state, not solved — but note one live consequence: a top orchestrator is told
"everything you and your children do belongs there", which is false, because each of its
children is forked a worktree of its own.

**3. A preset can be read but never applied, and most agents never learn presets exist.
(entry 5, two of four requirements BROKEN.)** `sb presets` only prints to the caller's own
terminal; nothing injects a preset's prompt into a live chat, cannot target another agent
or the human, and never touches the prompt-injection machinery that `sb interrupt` already
uses. And "known to all sessions" is simply false: only the orchestrator role file mentions
presets, so workers, researchers, reviewers and QA agents never hear of them.

Close behind, and the same shape as #3: **no prompt, no verb and no `--role` help ever
lists what roles exist** (entry 2, BROKEN) — the one listing-shaped surface,
`sb presets --json`, names three of the five and omits `worker` and `orchestrator`.

---

## What went wrong with the process

- Nothing blocked the audit. All four auditors finished, all read-only, git clean.
- One auditor's role file told it to write detail into `notes/` inside the checkout; the
  brief said `/tmp` only. It followed the brief and flagged the conflict — worth fixing, as
  a read-only instruction and a role default should not disagree.
- Two things are read-and-reasoned rather than exercised, and are marked as such in part A:
  whether `claude --resume` re-applies an appended system prompt, and the model-config layer
  merge (no machine-local `models.toml` exists to exercise it).
- The audit itself produced a piece of evidence for entry 11: this workspace's own root is a
  `worker`-role agent that currently has 15 children including six orchestrators, which is
  exactly the "a bare agent cannot spawn other agents" rule going unenforced.

---
---


# Part A — spawn-time knowledge, roles, and models

Auditor: reviewer-4. Tree read: `/Users/andrew/.herdr/worktrees/switchboard/worker-2`.
All Python run with `PYTHONPATH=<that worktree>`; all `sb` runs are the PATH checkout, which
the orchestrator has already established is the same code.

## Verdicts at a glance

| # | Entry | Verdict |
|---|-------|---------|
| 1 | "If it needs to be known, it is known at spawn." (DESIGN-TRUTH.md:75-80) | **PARTIAL** |
| 2 | "The role list is lightly audited and fine as it is" (DESIGN-TRUTH.md:96-97) | **BROKEN** |
| 3 | "Which model an agent gets is set in config, and does not really matter." (:99) | **SATISFIED** |
| 4 | "`sb models` is fine as it is." (:267) | **SATISFIED** |

---

## Method: how I reconstructed the composed spawn prompt

`Broker.delegate` is the ONE composition site (broker.py:2545-2558):

```
prompts = [ self._protocol(),
            self._say("spawn.identity", name=, role=, parent=) ]
if ws:        prompts.append(self._say("spawn.workspace", workspace=, path=))
if as_prompt: prompts.append(as_prompt)
elif r.prompt: prompts.append(r.prompt)
prompts.extend(self._resolve_bindings(role, with_))
```

That list is handed to `Herdr.start_agent(prompts=...)` (broker.py:2603-2605), which joins it
with a single space into ONE `--append-system-prompt` flag (herdr.py:436-437).

Both other spawn entry points route through `delegate`, so there is no second composition to
drift from this one:
- `Broker._top` (`sb start`) → `self.delegate(first, role=MAIN, ...)` at broker.py:582-585.
- `Broker._spawn_lead` (`sb workspace new`) → `self.delegate(first, role=role, ...)` at
  broker.py:2113-2118.

I reconstructed the composed text by calling those exact functions:

```
PYTHONPATH=. python3 -c "
from pathlib import Path
from switchboard import broker as B, config, roles as R
repo=Path('.').resolve()
b=B.Broker.__new__(B.Broker); b.db=None; b.repo=repo
b.roles=R.load(repo); b._protocol_override=config.protocol_override(repo)
for role in ['worker','reviewer','qa','researcher','orchestrator','madeup']:
    r=R.get(b.roles,role)
    ps=[b._protocol(), b._say('spawn.identity',name='x-1',role=role,parent='p'),
        b._say('spawn.workspace',workspace='ws',path='/tmp/ws')]
    if r.prompt: ps.append(r.prompt)
    ps.extend(b._resolve_bindings(role,()))
    ..."
```

Output (fragment count / total chars / keyword presence):

```
worker        5 frags  4475 ch   plugin=True  preset=False  role-list=False
reviewer      6 frags  5107 ch   plugin=True  preset=False  role-list=False
qa            7 frags  5633 ch   plugin=True  preset=False  role-list=False
researcher    6 frags  5038 ch   plugin=True  preset=False  role-list=False
orchestrator  5 frags  9422 ch   plugin=True  preset=True   role-list=False
madeup        5 frags  4475 ch   plugin=True  preset=False  role-list=False
```

("plugin=True" is ONLY the string `sb plugin report-bug` inside the bound `@report-bug`
fragment — see entry 1 gap 3. It is not a statement that plugins exist.)

**Live corroboration.** My own system prompt as `reviewer-4` contains, in order: the protocol
text, `You are agent 'reviewer-4', role 'reviewer'. You report to 'audit-5'...`, the workspace
fragment for `worker-2`, the reviewer role prose, the `@report-bug` fragment, then the
`evidence` preset. That is exactly the reconstruction above for `role=reviewer`, including the
`all`-before-role binding order from `presets.for_role` (presets.py:174-179). The
reconstruction is not a model of the composition; it is the composition.

---

## Entry 1 — "If it needs to be known, it is known at spawn." — PARTIAL

### What IS delivered (verified)

- **The protocol reaches every agent, on every path.** `PROTOCOL_LINE = config.protocol()`
  (broker.py:99), overridable per repo via `Broker._protocol` (broker.py:307-309). This repo
  has no `.switchboard/protocol.md`, so the shipped `defaults/protocol.md` is what ships.
- **Identity and parent** (`prompts.toml [spawn] identity`), always.
- **Workspace fragment**, only when the agent is placed in a named workspace
  (broker.py:2552-2553) — which is correct: it is the concurrency rule, and it is only true
  for agents in a shared checkout.
- **Role prompt**, or `--as` text in its place (broker.py:2554-2557).
- **Per-role bindings work.** Verified in the run above: reviewer picks up `evidence`, qa picks
  up `verify`+`evidence`, worker picks up neither. Source: `defaults/presets.toml [roles]`,
  resolved by `presets.for_role` (presets.py:168-179), called from
  `Broker._resolve_bindings` (broker.py:2410-2414).

### sb verbs named in the composed text

Named to every agent (from `defaults/protocol.md`): `inbox`, `tell`, `ask`, `done`, `delegate`,
`status`, `cleanup`, `restore`, `block`. Plus `sb plugin report-bug ...` via the bound fragment.

`sb --help` lists 20 verbs:
`start delegate ask tell inbox done block status presets plugin models init doctor cleanup
workspace restore interrupt inspect wait log`.

Never named to a non-orchestrator agent: **`presets`**, `models`, `workspace`, `init`,
`doctor`, `interrupt`, `inspect`, `wait`, `log`, `start`. Of those, `inspect`/`wait`/`log`/
`start`/`interrupt`/`init`/`doctor` are human surfaces per DESIGN-TRUTH.md:263-265 and their
absence is correct. `presets` is the one that contradicts design (gap 1).

### Gaps

1. **`sb presets` is never mentioned to any non-orchestrator agent.** DESIGN-TRUTH.md:262-264
   says presets "must be known to all sessions". `grep -n "preset" defaults/protocol.md
   defaults/prompts.toml defaults/roles/{worker,reviewer,qa,researcher}.md` returns nothing;
   the only hit in any shipped prompt is `defaults/roles/orchestrator.md:140-143`. So a
   reviewer or qa agent is never told the `adversarial` procedure — or any other preset —
   exists. Fix by putting one clause naming `sb presets` / `sb presets <name>` in
   `defaults/protocol.md`.

2. **Nothing tells an agent that PLUGINS exist as a category, or how to see which it may
   call.** The only occurrence of the word in any composed prompt is inside the bound
   `@report-bug` fragment, which names its own verb. `sb plugin list` is never named. An agent
   therefore cannot discover the `todo` plugin (or any future one) even where it is enabled.
   Fix by naming `sb plugin list` once in the protocol, or by having the spawn layer inject
   the enabled-plugin names.

3. **Plugin advertisement is per-role by MECHANISM but flat by DATA.** The filtering is real:
   bindings are keyed by role in `defaults/presets.toml [roles]` and applied by
   `presets.for_role` (presets.py:174-179); `plugins.py:303-311` reads the same table to report
   which roles each plugin is bound to. But the shipped data binds the only enabled plugin to
   `all` (`defaults/presets.toml`: `all = ["@report-bug"]`), so today every agent gets exactly
   the same plugin text. `sb plugin list` confirms:
   `report-bug 1.0.0 ok [enabled, @report-bug bound to every agent]` /
   `todo 1.0.0 not enabled`. Design says "not every plugin for every agent"; with one enabled
   plugin this is not yet violated, but nothing exercises the per-role path for plugins.
   No fix needed now — this is a "the mechanism is there, it is untested in anger" note.

4. **Fragment boundaries are erased at delivery.** herdr.py:437 joins the fragments with a
   single space into one flag. The protocol's last sentence and the identity line's first run
   together as one paragraph. Verifiable in my own system prompt, where the reviewer role text
   and the `@report-bug` fragment abut with no separator. Fix by joining with a separator
   (`" — "` or `" | "`), not a bare space; newlines are not available (herdr rejects them,
   herdr.py:409-415).

5. **`defaults/roles/worker.md` and `defaults/protocol.md` duplicate the same two rules.**
   protocol.md's editing comment states worker.md "was deleted" and that its scope/hand-back
   rules were folded into the protocol. worker.md exists (54 lines, restored in commit
   146240a) and its prompt re-states both: "carry it to done and do nothing beyond it… report
   it rather than fixing it" against the protocol's "Do the task you were given and nothing
   beyond it: something else you notice on the way gets reported, not fixed". Every worker
   pays for both. Fix by deciding which file owns the rule and cutting it from the other, and
   correcting the stale comment block at the top of `defaults/protocol.md`.

6. **Restore re-spawns with NO system prompt at all.** `Broker.restore` calls
   `self.h.start_agent(name, pane, resume=a["session_id"], model_args=spec.cli_args())`
   (broker.py:3163-3164) — no `prompts=`, so no `--append-system-prompt` is passed. Whether
   `claude --resume` re-applies the original appended system prompt is something **I did not
   test** and cannot assert either way. If it does not, a restored agent has lost the entire
   protocol, which would make "known at spawn" false for every restored agent. Fix: verify it,
   and if it does not carry over, pass the recomposed prompts on the restore path.

---

## Entry 2 — "as long as it is known that there are roles, and what roles there are" — BROKEN

The first half holds; the second half is met nowhere.

**Roles exist — stated.** `defaults/protocol.md:112`: ``To delegate: `sb delegate "<task>"
--role <role>`…``. So an agent knows the flag and knows roles are a thing.

**What the roles ARE — stated nowhere.**

- Nothing in any prompt enumerates them.
  `grep -rn -- "--role" defaults/` returns three hits: protocol.md:112 (the flag, no list) and
  worker.md:32-33, which mention `--role archaeologist` / `--role interviewer` as EXAMPLES OF
  UNDEFINED roles — actively misleading as a source for what exists.
- Nothing in the code injects the list.
  `grep -rn "roles.keys\|role_names\|list(self.roles)\|available_roles" switchboard/` → no
  matches.
- It is not discoverable at runtime. There is no `sb roles` verb (`sb --help`, 20 verbs, above),
  and the argparse entry carries no help text and no choices:
  ```
  $ sb delegate --help
    --role ROLE
  ```
  Contrast `--model`, which does list its vocabulary
  (`--model MODEL   cheap | default | standard | strong, or a model id (see: sb models)`),
  built dynamically by `_model_help` at cli.py:70-78. The same treatment for `--role` does
  not exist.

**The one accidental partial surface**, and it is wrong: `sb presets --json` emits a `roles`
key (cli.py:835). Run:
```
$ sb presets --json
{"presets": ["adversarial","evidence","verify"], "all": ["@report-bug"],
 "roles": {"researcher": ["evidence"], "reviewer": ["evidence"], "qa": ["verify","evidence"]}}
```
That names 3 roles. The actual set is 5 — `roles.load()` returns
`['orchestrator','qa','researcher','reviewer','worker']`. `worker` (the default AND the
fallback) and `orchestrator` are both missing, because the key lists roles that have preset
BINDINGS, not roles that exist. An agent reading it to find out what to delegate as would
conclude it cannot spawn a worker.

### Gaps

1. No prompt fragment names the defined roles; add one built from `roles.load()` keys, or a
   static line in `defaults/protocol.md`, so an agent that may delegate knows what to ask for.
2. `sb delegate --role` has empty help while `--model` lists its vocabulary; give `--role` the
   same dynamic help via a `_role_help` mirroring `_model_help` (cli.py:70-78).
3. There is no verb that lists roles (no `sb roles`); the only listing-shaped surface,
   `sb presets --json`'s `roles` key, omits `worker` and `orchestrator` and must not be read
   as the role list.

---

## Entry 3 — "Which model an agent gets is set in config" — SATISFIED

Chain established end to end, every link read and every link exercised.

**role file → tier.** `defaults/roles/<name>.md` TOML front matter sets `model = "<tier>"`
(e.g. `defaults/roles/worker.md:1-3` → `model = "default"`). `roles.Role.model` is documented
and used as a TIER name only (roles.py:38, `# a TIER name, not a model id`). A role file with
no tier falls back to `[vocabulary] default_tier` in `Role.__post_init__` (roles.py:44-51).

**tier → provider/model/effort.** `Role.spec(override)` → `models.Tiers.resolve()`
(roles.py:53-66). Table layered `defaults/models.toml` → `~/.config/switchboard/models.toml`
→ `<repo>/.switchboard/models.toml`, merged PER TIER by `models._layer` (models.py:212-222)
and loaded by `models.load` (models.py:225-244).

**config layers actually in play here:** `~/.config/switchboard/models.toml` does not exist
(`ls: No such file or directory`), and `<worktree>/.switchboard/models.toml` is entirely
comments and sets nothing. So the resolved table is the shipped one. Layering is therefore
**read and reasoned, not exercised by live data** — I did not write a config file to test the
override, being read-only.

**→ CLI flags.** `ModelSpec.cli_args()` (models.py:135-152) emits `--model` / `--effort` /
`extra_args`, and raises `ModelConfigError` for an unwired provider before anything spawns.

**→ the spawn layer.** `broker.py:2603-2605`:
`self.h.start_agent(name, pane, prompts=prompts, model_args=r.spec(model).cli_args())`, and
`herdr.py:417-418` appends those flags verbatim after `--permission-mode`. herdr never sees a
tier name (herdr.py:401-407).

**Resolution run:**
```
$ PYTHONPATH=. python3 -c "...roles.load / spec..."
roles defined: ['orchestrator','qa','researcher','reviewer','worker']
  orchestrator tier=default  cleanup=close -> []
  qa           tier=default  cleanup=close -> []
  researcher   tier=cheap    cleanup=close -> ['--model','sonnet','--effort','medium']
  reviewer     tier=default  cleanup=close -> []
  worker       tier=default  cleanup=close -> []
override strong on researcher: ['--model','opus','--effort','high']
override unknown tier 'zzz'  : ['--model','zzz']
unknown role 'madeup'        : tier=default, []
resolve(None)                : ModelSpec(tier='default', provider='claude', model=None, ...)
```

- **Per-role tiers work.** `researcher` really resolves to sonnet/medium; nobody else does.
- **`sb delegate --model` works.** The override goes through the same table
  (`Role.spec(override)`, roles.py:66) — `--model strong` on a researcher yields opus/high,
  i.e. the override brings its EFFORT with it rather than only swapping the model.
- **Unknown tier degrades sanely.** `Tiers.resolve` passes an unrecognised name through as a
  model id against the default provider (models.py:181-186), so `--model zzz` becomes
  `--model zzz` and the provider CLI decides. No crash, no silent default.
- **Unknown role degrades sanely.** `roles.get` falls back to `[vocabulary] fallback_role`
  (= `worker`), keeping the requested name (roles.py:78-89).
- **Unwired provider fails loudly and early**, at resolution not at spawn:
  ```
  ModelConfigError: tier 't' asks for provider 'codex', which has no backend yet (wired: claude)
  ```

### One defect found here (does not change the verdict)

`sb delegate --model <tier>` is **not persisted, and is lost on restore.** The `agents` table
has no model or tier column (store.py:140-171 — `role`, `cleanup`, `branch`, etc., no model),
and `Broker.restore` re-resolves from the ROLE alone: `spec = roles_mod.get(self.roles,
a["role"]).spec()` (broker.py:3160). So an agent spawned as
`sb delegate --role reviewer --model strong` comes back on the reviewer's own `default` tier
after a close/restore, silently. The comment two lines above it (broker.py:3157-3159) says a
restored agent must not "silently come back on the provider CLI's default model" — it does not,
but it does silently come back on a different tier than it was spawned with. Fix: store the
resolved tier on the row at spawn and prefer it in `restore`.

Verdict stays SATISFIED because the design entry is about model choice coming from config,
which it does; this is a build task, not a contradiction of the entry.

---

## Entry 4 — "`sb models` is fine as it is." — SATISFIED

`sb models` uses the same resolver the spawn path does — not a parallel implementation.
cli.py:841-864: `tiers = models_mod.load(b.repo)`, then `tiers.resolve(n)` per name and
`s.cli_args()` for the flags column. That is literally what `Role.spec()` returns and what
`delegate` passes to herdr.

```
$ sb models
  cheap       claude    --model sonnet --effort medium
  default     claude    (provider default)
  standard    claude    (provider default)
  strong      claude    --model opus --effort high

$ sb models --json
{"default_provider":"claude","tiers":{"cheap":{"provider":"claude","model":"sonnet",
"effort":"medium","cli_args":["--model","sonnet","--effort","medium"],"error":null},
"default":{...,"cli_args":[],"error":null},"standard":{...,"cli_args":[],"error":null},
"strong":{"provider":"claude","model":"opus","effort":"high",
"cli_args":["--model","opus","--effort","high"],"error":null}}}
```

Matches the resolver exactly: `cli_args` per tier is identical to the `spec().cli_args()`
values printed in the entry-3 run. The two visually-empty rows are disambiguated as the code
comment claims — `(provider default)` for a deliberate no-flags tier, and a per-row
`UNAVAILABLE — …` for an unwired provider, which is reported per row rather than taking the
whole listing down (cli.py:853-861). I did not exercise the UNAVAILABLE row through the CLI
(it needs a config edit); I exercised the exception it formats directly, shown in entry 3.

Two facts about the output, neither a defect against "fine as it is": it lists only DEFINED
tiers, so the unknown-name passthrough is not visible in it; and it is repo-scoped
(`models_mod.load(b.repo)`), so it is the right answer for the repo you run it in.

---

## Build tasks extracted (one line each)

1. `defaults/protocol.md` never names `sb presets`, but DESIGN-TRUTH.md:262-264 says presets must be known to all sessions; add a clause naming `sb presets` / `sb presets <name>`.
2. No composed prompt names the defined roles; inject the `roles.load()` key list at spawn, or state it in `defaults/protocol.md`.
3. `sb delegate --role` has empty argparse help while `--model` lists its vocabulary; add a `_role_help` mirroring `_model_help` (cli.py:70-78).
4. `sb presets --json`'s `roles` key lists only roles with bindings (3 of 5, missing `worker` and `orchestrator`); either name it `bindings_by_role` or make it the real role list.
5. Nothing names `sb plugin list`, so an agent cannot discover any plugin beyond the one whose fragment it was handed; name it once in the protocol.
6. herdr.py:437 joins prompt fragments with a bare space so their boundaries vanish; join with a visible separator instead (newlines are rejected, herdr.py:409-415).
7. `defaults/roles/worker.md` re-states the protocol's scope and hand-back rules, so every worker pays twice; cut one, and fix `defaults/protocol.md`'s comment claiming worker.md was deleted.
8. `Broker.restore` (broker.py:3163) passes no `prompts=` — confirm whether `claude --resume` re-applies the appended system prompt, and pass the recomposed prompts if it does not.
9. `sb delegate --model <tier>` is not recorded on the agent row, so `Broker.restore` (broker.py:3160) silently brings the agent back on its role's tier; store the resolved tier and prefer it on restore.

## Things I did NOT check

- Whether `claude --resume` re-applies a previously appended system prompt (task 8 above).
- Live model-config layering: no global or repo `models.toml` sets anything on this machine, so
  the layer merge is read-and-reasoned, not exercised with real data.
- I spawned no agents; every prompt above is reconstructed from the composition functions plus
  my own live system prompt.
- Out of scope by brief and untouched: how `sb presets` lists/applies/reads (B), the content
  and quality of the orchestrator prompt (C), sibling visibility and message scoping (D).

---
---

# Task B — `sb presets` — audit findings

Auditor: reviewer-5. Read-only. Worktree `/Users/andrew/.herdr/worktrees/switchboard/worker-2`.

## The entry under audit (DESIGN-TRUTH.md:263-265)

> **`sb presets` needs a parameter to list, and one to apply the prompt to the current
> chat or just read it.** Picking a preset should inject a prompt. This must be known to
> all sessions. — confirmed 2026-08-09

## OVERALL VERDICT: PARTIAL

One of the four requirements is fully met (c, read). One is met in capability but not in
the form asked for (a, list). Two are not met at all — (b) nothing anywhere applies a
preset to a live chat, and (d) only one of five roles is ever told presets exist.

| # | Requirement | Verdict |
|---|---|---------|
| a | a parameter to list | PARTIAL |
| b | a parameter to apply the prompt to the current chat | BROKEN |
| c | a parameter to just read it | SATISFIED |
| d | must be known to all sessions | BROKEN |

## The real command surface

Established by running it, not by reading the help text:

```
$ sb presets --help
usage: sb presets [-h] [--json] [name]
positional arguments:
  name        print this preset instead of listing
options:
  -h, --help  show this help message and exit
  --json      machine-readable output
```

That is the entire surface. `--list` and `--apply` are rejected by the top-level parser
(`sb: error: unrecognized arguments: --list` / `--apply`, rc=2). Only one positional is
accepted (`sb presets adversarial evidence` → rc=2). Defined at `switchboard/cli.py:184-185`;
dispatched at `switchboard/cli.py:812-836`.

```
$ sb presets
  adversarial     
  evidence         [researcher, reviewer, qa]
  verify           [qa]
rc=0

$ sb presets --json
{"presets": ["adversarial", "evidence", "verify"], "all": ["@report-bug"],
 "roles": {"researcher": ["evidence"], "reviewer": ["evidence"], "qa": ["verify", "evidence"]}}
```

---

## (a) "a parameter to list" — PARTIAL

Listing happens when the verb is called with **no** argument (`cli.py:826-835`, the branch
after `if args.name:`). There is no `--list` and no `list` subword. So listing is a side
effect of the bare verb, exactly the shape the design entry says it should not be.

The capability itself is present and works, and `--json` gives a machine-readable form of
the same listing. What is absent is the parameter. Whether that matters depends on reading
"parameter" strictly; I am reporting the fact and letting the design owner decide.

Gap: listing is the argument-less form of the verb, not a parameter; design asks for a
parameter. Fix by adding an explicit `--list` (or a `list` positional) that produces the
same output, keeping the bare verb as an alias.

## (b) "a parameter to apply the prompt to the current chat" — BROKEN

**Nothing in switchboard injects a preset into any live chat session.** I checked every
path:

- `switchboard/presets.py` (all 343 lines) has five public functions — `available`,
  `flatten`, `text`, `bindings`, `for_role`, `resolve`. `text()` reads a file and returns
  a string (`presets.py:159-171`). None of them send anything anywhere.
- `cli.py:812-836` is the whole `presets` dispatch. Both branches end in `_emit(...)`,
  which prints to this process's stdout. Nothing else.
- The only injection of preset text into an agent is at **spawn time**:
  `Broker._resolve_bindings` (`broker.py:2382-2412`) resolves `for_role(repo, role, extra)`
  and the result becomes part of the new agent's system prompt. `extra` is `--with`
  (`sb delegate --help`: `--with PRESET`). That is a *new* chat, not the current one.

**The "model reads the tool output" question, answered directly.** When an agent runs
`sb presets adversarial`, the text is written to that agent's own stdout and arrives as
tool output in its context. That is the only mechanism there is. It is *not* injection into
the chat session in the sense the design entry means: it is not a system-prompt line, it is
not a message in the store, it is not delivered by herdr, it is ordinary tool output that
the model may or may not act on and that decays out of context like any other tool result.
It also cannot be aimed anywhere — it lands in whichever process ran the command and
nowhere else. `sb presets <name>` alone does not tell the agent to *adopt* the text; the
prose in `adversarial.md` happens to read as an instruction, which is what makes it feel
like it applied.

**Can apply target another agent's chat?** No. There is no argument for a target
(`cli.py:184-185` — one optional positional, `name`, which is the preset name). No caller
of `presets_mod` passes an agent name.

**Does the machinery exist?** Yes, and presets uses none of it. `herdr.prompt(name, text)`
(`switchboard/herdr.py:457-471`) puts text into a live agent's turn — the docstring records
it was re-verified injecting at +13s into a 60s turn. `Broker.interrupt`
(`broker.py:3184-3225`) uses it to put an instruction inline on the wire, and `sb tell`
rings the same doorbell with the payload held in the store. So "put this prompt into that
running session" is a solved problem in this codebase; `sb presets` simply never calls it.
`sb interrupt --help` and `sb tell --help` take a free-text message and have no preset flag,
so there is not even an indirect route short of the caller pasting the text by hand.

**Does it work for the human's own session?** No, and it structurally cannot. herdr's
`prompt` addresses a registered *agent* by name; the human's Claude session is not one.

Gaps:
- `sb presets` has no apply path at all; add e.g. `sb presets <name> --apply [agent]` that
  routes the prose through `Broker.interrupt`/`herdr.prompt` for a named agent.
- Applying to the caller's *own* chat has no mechanism even in principle — an agent cannot
  address itself through herdr. Decide whether "current chat" means "the tool output is
  enough" (then the design entry should say so) or needs a real self-injection path.
- Applying to the human's own session is impossible via herdr; if it is in scope it needs a
  different mechanism entirely.

## (c) "a parameter to just read it" — SATISFIED

`sb presets <name>` prints one preset and applies nothing. Verified:

```
$ sb presets adversarial
# adversarial

A procedure you run, not a mood. ...
rc=0
```

Implementation: `cli.py:813-823` → `presets.text()` (`presets.py:159-171`) →
`config.prose()` (`config.py:254-265`), which strips HTML comments and stops — it does not
flatten. The 44-line `<!-- -->` editor's note at the head of `defaults/presets/adversarial.md`
is correctly absent from the output; the printed body starts at `# adversarial` and is
readable prose with its paragraph structure intact.

Error path is good: `sb presets nosuch` → `sb: no preset 'nosuch' (have: adversarial,
evidence, verify)`, rc=1 (`cli.py:815-822`).

`--json` composes with a name: `sb presets adversarial --json` returns
`{"preset", "path", "text"}`.

**`sb presets adversarial` prints cleanly and is self-contained** — this is the one other
agents are told to run, and it holds up. Six paragraphs: what it is, keep one proposer,
run rounds with a fresh reviewer and a new lens each time, stop on convergence, hard cap of
four rounds, then report. It references no other file and needs no other file. One caveat:
it is written entirely to an orchestrator ("spawn a NEW reviewer", "report as you would any
cohort"), so an agent that cannot delegate gets a procedure it cannot run — the file says
this is deliberate (it is pointed at from `orchestrator.md` only).

## (d) "This must be known to all sessions" — BROKEN

Only **one** of five roles is ever told presets exist.

`grep -rn "sb presets" defaults/` returns exactly two source locations:
- `defaults/roles/orchestrator.md:140-143` — "## Procedures you can look up … `sb presets`
  lists them and `sb presets <name>` prints one … `sb presets adversarial` is the procedure".
- `defaults/presets/adversarial.md:39` — inside the HTML comment, so it is stripped and
  reaches nobody.

What that means per session type:

| Session | Told presets exist? | Evidence |
|---|---|---|
| `sb start` top orchestrator | **Yes** | `Broker._top` delegates with `role=MAIN` (`broker.py:583`); `MAIN = config.setting("vocabulary.main_role")` (`broker.py:52`) resolves to `orchestrator` (verified by importing config) |
| any other orchestrator | **Yes** | same role file |
| worker (the default role) | **No** | `defaults/roles/worker.md` never mentions presets; `vocabulary.default_role` = `worker` |
| researcher | **No** | `defaults/roles/researcher.md` — no mention |
| reviewer | **No** | `defaults/roles/reviewer.md` mentions "the preset" only in editor prose about verdict formats; no `sb presets` |
| qa | **No** | `defaults/roles/qa.md` — discusses its own bindings, never the command |
| an agent with no role / an unknown role | **No** | falls back to `worker`, which has no prompt at all (`protocol.md` editor note, lines 19-27) |
| the human's own session | **No** | `protocol.md` lines 6-8 state the protocol is injected at spawn and never written to disk, so "ordinary Claude sessions … never see it"; `sb init` "writes no CLAUDE.md" (`cli.py`) |

**`defaults/protocol.md` — the one text every single agent pays for — never mentions
presets.** I read all 122 lines. It names `sb inbox`, `tell`, `ask`, `done`, `delegate`,
`status`, `cleanup`, `restore`, `block`. Not `presets`.

Direct evidence from this audit: I am a `reviewer`. My own system prompt carries the
`evidence` preset's text (flattened with `; ` separators — "Report only what you actually
verified. ; Point at your evidence precisely enough…") and the `@report-bug` plugin
fragment. So presets *were* injected into me. Nothing in my prompt tells me presets are a
thing, that `sb presets` exists, or that `adversarial` is available to read. I only know
because this task told me.

Residual discoverability: `sb --help` lists the verb ("presets — list available presets, or
print one"). That is discovery by a reader who already thinks to look, not "known to all
sessions".

Gaps:
- `defaults/protocol.md` has no sentence naming `sb presets`; add one line so every spawn
  learns procedures are lookable-up (costs one clause on every spawn — that is the
  trade-off the design entry is asking to make).
- The human's own session cannot be told anything by design (protocol is spawn-only, `sb
  init` writes no CLAUDE.md); if "all sessions" includes the human, a different channel is
  needed and none exists.

---

## Also established

### What actually ships

`defaults/presets/` contains exactly three files: `adversarial.md`, `evidence.md`,
`verify.md`. `available()` (`presets.py:129-144`) reads `config.defaults_dir()/presets`
first, then the repo's own directory, with the repo's `<name>.md` replacing the shipped one.
This worktree has **no** `.switchboard/presets/` directory, so all three resolve to the
shipped files — confirmed by `sb presets adversarial --json`, whose `path` is
`/Users/andrew/Code/switchboard/defaults/presets/adversarial.md`.

Bindings, resolved by importing this worktree's code:

```
$ PYTHONPATH=. python3 -c "from pathlib import Path; from switchboard import presets as p; print(p.bindings(Path('.')))"
(('@report-bug',), {'researcher': ('evidence',), 'reviewer': ('evidence',), 'qa': ('verify', 'evidence')})
```

`defaults/presets.toml` sets `all = ["@report-bug"]` and the three `[roles]` entries.
This repo's `.switchboard/presets.toml` sets `all = []` and an empty `[roles]`, so it adds
nothing — the shipped layer is the whole answer here.

### What the `[researcher, reviewer, qa]` annotations mean

They are rendered at `cli.py:828-831`: for each preset file, the tag lists the roles whose
binding list contains that name. So `evidence [researcher, reviewer, qa]` means "these three
roles get this preset automatically at spawn". `adversarial` has an empty tag because it is
bound to nothing, which `defaults/presets.toml` and `adversarial.md` both say is deliberate.

### Is that role scoping enforced? No — it is descriptive only.

Two independent proofs:

1. `for_role` (`presets.py:186-196`) only *adds*: `every + per_role.get(role) + extra`.
   Nothing rejects a preset for a role. Verified by running it:
   ```
   worker with --with verify      -> ['@report-bug', 'verify']
   worker with --with adversarial -> ['@report-bug', 'adversarial']
   ```
   A `worker` can be spawned with `verify`, which the listing tags `[qa]`.
2. `sb presets <name>` has no role check at all (`cli.py:813-823`). Any agent of any role
   can read any preset. I am a `reviewer` and read `adversarial`, tagged for nobody.

An unknown role gets only the `all` list (`for_role(repo, 'nonsense')` → `['@report-bug']`)
— it does not error.

### One cosmetic dead branch

`cli.py:830` computes `" [every agent]" if n in every`, but `every` is `('@report-bug',)`
— a plugin fragment — while `n` iterates preset *file* stems. A `@`-prefixed name can never
equal a file stem, so as shipped that tag is unreachable. It would light up if a repo bound
a bare preset name in `all`. Not a bug against the design entry; noted because it makes the
listing silently unable to show the every-agent layer as currently configured.

---

## Process notes

- Nothing was written outside `/tmp`. No repo file changed, nothing staged, nothing
  committed, no agents spawned.
- My reviewer role tells me to write detail to `notes/<agent>-<topic>.md` in the checkout;
  the task brief says findings go only in `/tmp/sb-audit-5/part-b.md`. I followed the brief.
- `sb presets --json` resolves paths into `/Users/andrew/Code/switchboard/defaults/`, i.e.
  the PATH checkout, not this worktree — expected per the common brief, and the
  `defaults/presets/` contents are identical in both.

---
---

# Part C — orchestrator prompts, and top vs workspace differentiation

Auditor: reviewer-6. Read-only. Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2`.
All `file:line` references are that worktree unless stated. Commands were run with
`PYTHONPATH=/Users/andrew/.herdr/worktrees/switchboard/worker-2`.

## Verdicts at a glance

| # | Entry (DESIGN-TRUTH.md) | Verdict |
|---|---|---|
| 1 | "A workspace orchestrator's job is to orchestrate other agents and stuff." (146-148) | SATISFIED (design predicted no prompt; there is none) |
| 2 | "The orchestrator prompt is mostly good already." (150) | PARTIAL |
| 3 | "Top and workspace orchestrators must be clearly differentiated…" (152-153) | BROKEN |

---

## The evidence everything below rests on: the composed prompt

`Broker.delegate` is the single place every spawn passes through, and the system prompt it
builds is exactly five fragments, in this order (`switchboard/broker.py:2548-2558`):

```
prompts = [ self._protocol(),                                  # defaults/protocol.md
            self._say("spawn.identity", name, role, parent) ]  # prompts.toml:28
if ws:  prompts.append(self._say("spawn.workspace", ws, path)) # prompts.toml:39
if as_prompt: ... elif r.prompt: prompts.append(r.prompt)      # defaults/roles/<role>.md
prompts.extend(self._resolve_bindings(role, with_))            # presets/plugins
```

I reconstructed that list for the three cases the brief names, using this worktree's own
`config`, `roles` and `presets` modules (the same calls `delegate` makes), and diffed them:

- **top** — as `_top` spawns it (`broker.py:582`): `role=MAIN`, `name='main'`, `me=HUMAN`,
  `workspace='main'`, `cwd=<repo>`.
- **workspace lead** — as `_spawn_lead` spawns it (`broker.py:2112`): `role=WORKSPACE_ROLE`,
  `name='worker-2-lead'`, parent `main`, `workspace='worker-2'`, cwd the worktree.
- **sub-orchestrator** — an ordinary `sb delegate --role orchestrator` under a lead.

Result: **all three are five fragments, and the diff is only the substituted `{name}`,
`{parent}`, `{workspace}` and `{path}`.** The protocol fragment, the role prompt and the
`@report-bug` plugin fragment are byte-identical across all three. Preset bindings for
`orchestrator` resolve to `['@report-bug']` in every case.

Corroboration from a live spawn: my own system prompt (agent `reviewer-6`) is exactly this
shape — protocol, identity, workspace, role prompt, `@report-bug` — which is what a real
`delegate` produced, not a reconstruction.

---

## Entry 1 — "A workspace orchestrator's job is to orchestrate other agents and stuff" — SATISFIED

Design says outright: *"There is no prompt for that yet, so nothing about how it runs is
anchored here."* That prediction is correct, and the tree is consistent with it.

- There is exactly one orchestrator prompt file: `defaults/roles/orchestrator.md`.
  `ls defaults/roles` → `orchestrator.md qa.md researcher.md reviewer.md worker.md`. No
  workspace-lead, lead, or top variant, shipped or repo-local (`.switchboard/roles.toml`
  sets nothing, and there is no `.switchboard/roles/`).
- `defaults/settings.toml:80` `main_role = "orchestrator"` and `:95`
  `workspace_role = "orchestrator"` — the same role name for both, deliberately (the
  comment at `settings.toml:76-79` says so).
- The composed diff above: a lead's prompt carries no sentence a top's does not.
- Does the shipped text say a workspace orchestrator's job is to orchestrate other agents?
  Generically yes — `defaults/roles/orchestrator.md:101`, "You are an orchestrator. Your job
  is to get other agents to do the work" — but it is said of *every* orchestrator, not of a
  workspace one.
- Does any shipped text say **review is coordinated by it**? No. The only mention of
  coordinating a review is `orchestrator.md:142-143`, which tells *any* orchestrator that an
  adversarial review is a procedure it runs itself (`sb presets adversarial`). Nothing ties
  review to the workspace layer.

Graded SATISFIED because design predicts the absence and the absence is what is there. It
is not evidence that anything works — only that nothing has been written yet.

## Entry 2 — "The orchestrator prompt is mostly good already" — PARTIAL

What the agent actually receives is above. Graded against the four prompt-text truths:

**(a) "it can spawn discovery or scout or research agents … to improve its decisions"
(140-141) — SATISFIED, and stated as the first move.**
`orchestrator.md:111-115`: "If you do not already understand the task well enough to split
it well, your first move is to spend one agent finding out — a scout whose whole job is to
come back and tell you how the thing is shaped." Reinforced at `:120` ("put a reviewer on
each").

**(b) "A lead's children share its worktree, so the lead assigns disjoint files and
serialises anything that overlaps" (143-144) — PARTIAL.**
- The *serialise* half is in the prompt: `orchestrator.md:122-123`, "Serialise anything that
  writes the same files, because parallel writers conflict and you will pay for it in
  merges."
- The *assign disjoint files* half is **not** in any fragment. The word "disjoint" appears
  zero times in the orchestrator prompt (counted programmatically over the loaded role
  prompt), and no sentence instructs the orchestrator to partition files up front. The only
  neighbouring instruction is reactive (serialise the overlap), not preventive.
- The *premise* — children share the worktree — is not in the orchestrator role prompt at
  all: "worktree" and "workspace" both occur zero times in it. The nearest statement is the
  separate workspace fragment, `defaults/prompts.toml:39-46`: "Everything you and your
  children do belongs there … it is shared."

**(c) small task → bare agent, otherwise an orchestrator (135-138) — SATISFIED.**
`orchestrator.md:128-130`: "decide for each part who runs it: a worker when one agent can
carry it to done, another orchestrator only when that part is itself multi-step and needs
its own breakdown", plus "Never spawn an orchestrator for the whole of your task". Design's
"without interruption" qualifier is not spelled out; the substance of the rule is.

**(d) "They can talk to each other, but they should not" (165-167) — ABSENT.**
No shipped prompt text says this, in any form. `grep -rin "sibling\|each other\|one another"
defaults/` returns one hit, a code comment in `settings.toml:374` about something else. The
protocol teaches the opposite affordance with no discouragement attached:
`defaults/protocol.md:102-103`, "`sb tell <who> \"<msg>\"` sends a message (<who> is `parent`
or an agent name)" and "`sb ask <who>` sends to another agent and WAITS".

## Entry 3 — "Top and workspace orchestrators must be clearly differentiated, and some mechanism other than the prompt must make that true as well" — BROKEN

Neither half holds today. Not the prompt, and not any other mechanism.

**Is top-vs-workspace represented as distinct things at spawn time? No.**
- One role for both: `settings.toml:80` and `:95` both resolve to `"orchestrator"`.
  `_top` spawns `role=MAIN` (`broker.py:582`); `_spawn_lead` spawns `role=role`, defaulted
  to `WORKSPACE_ROLE` at `broker.py:821`. Same string.
- No flag, no computed property. `grep -rn 'role ==\|role !=\|role in (\|role"\] ==\|
  role"\] in' switchboard/*.py` returns **nothing** — no code anywhere branches on an
  agent's role. The constant `MAIN` is used in exactly two places
  (`grep -rn 'MAIN' switchboard/*.py`): `broker.py:582` (spawn with it) and `broker.py:510`
  (`running_tops`, which reads `store.live_roots(db, MAIN)`).
- The only thing that identifies a top is `store.live_roots` (`switchboard/store.py:951-967`):
  `WHERE parent IS NULL AND role=?`. It is derived at read time, from parenthood, and its
  sole consumer is the informational list `sb start` prints (`broker.py:506-508`).

**Does the composed prompt differ? No.** See the diff above — identity/workspace
substitutions only.

There is exactly one shipped string that differs between the two paths, and it is not part
of the system prompt: the placeholder *first task* when the caller supplied none —
`spawn.start_task = "Await my instructions."` (`prompts.toml:55`) versus
`spawn.workspace_task = "Await instructions for this workspace."` (`prompts.toml:58`),
selected at `broker.py:581` and `broker.py:2110`. It is delivered as the agent's first user
turn (`broker.py:2646`, `self.h.prompt(name, task)`), it is overwritten whenever a real task
is given, and neither sentence says anything about what kind of orchestrator the agent is.

**Is there any non-prompt mechanism? Only one, and it differentiates the *workspace*, not
the agent.**
- Permitted verbs: none gated. `sb --help` lists 19 verbs and no code checks role, so a top
  and a lead may run exactly the same commands.
- Cleanup disposition: identical — both spawn with `cleanup="keep"` (`broker.py:583`,
  `broker.py:2113`). Confirmed live: rows `main`…`main-4` and every `*-lead` row all carry
  `cleanup='keep'`.
- Board / status rendering: role is a display column only (`status.py:978`, `:989`,
  `:1293`); nothing renders a root differently.
- The store: a top's space is **bare** and a lead's is a **worktree**. Live rows from
  `/Users/andrew/Code/switchboard/.git/agentflow/state.db` (read-only query): the four roots
  `main`, `main-2`, `main-3`, `main-4` all have `parent=NULL`, `branch=NULL`,
  `cwd=/Users/andrew/Code/switchboard`; their `workspaces` rows have `checkout=NULL`. Every
  `*-lead` row has `branch` set and its workspace has a real checkout path.
- That store difference has exactly one behavioural consequence, and it is real: the fork
  rule at `broker.py:2530-2532` asks `has_worktree(me)` (`broker.py:2224-2231`, which reads
  `agents.branch`). Verified live: `has_worktree('main-4')` → `False`,
  `has_worktree('worker-2')` → `True`. So a top's children each fork their own worktree,
  while a lead's children inherit its one. But this follows from the space being bare — any
  orchestrator standing in a bare space gets it — not from anything that knows the agent is
  "the top".

**A concrete falsehood this produces in the top's prompt.** Because the fragment is chosen
by "is there a workspace" and not by which kind, a top orchestrator is told
(`prompts.toml:39-46`, composed): *"You are working in workspace 'main' at
/Users/andrew/Code/switchboard. Everything you and your children do belongs there."* Its
children do not: `delegate` forks each of them into a new workspace and branch of their own
(`broker.py:2530-2536`), because `has_worktree('main-4')` is False. The sentence is true for
a lead and false for a top, and the same text is sent to both.

I did not check whether the top orchestrator's *own* stated job (DESIGN-TRUTH 128-130 —
orchestrating the creation of worktrees, orchestrators and workspaces) is enforced anywhere;
that is topology, not prompt text. I do report the prompt-text fact: the orchestrator role
prompt never mentions `sb workspace new`, a worktree, a workspace or a lead — those four
words occur zero times in it.

Note: DESIGN-TRUTH.md:305-307 records the mechanism itself as an open question not to be
solved now, so nothing below proposes one.

---

## Gaps, one line each (build-task shaped)

For entry 2 (PARTIAL):

1. `defaults/roles/orchestrator.md:122` tells the orchestrator to serialise overlapping
   writes but never to assign disjoint files up front, which design (143-144) states as the
   lead's actual move; fix by adding the preventive half to the "Plan, then re-plan" section.
2. No prompt fragment tells an orchestrator that its children land in *its* worktree — the
   premise design gives for the disjoint-files rule; fix by stating it where the rule is,
   in `defaults/roles/orchestrator.md`, rather than leaving it to `prompts.toml`'s workspace
   fragment which says only that the workspace is shared.
3. Design (165-167) says directly-spawned siblings should not talk to each other, and no
   shipped text says so while `defaults/protocol.md:102-103` teaches `sb tell <agent name>`
   and `sb ask` with no caveat; fix by adding the "should not" clause where the two verbs
   are introduced.

For entry 3 (BROKEN):

4. `defaults/settings.toml:80` and `:95` resolve `main_role` and `workspace_role` to the same
   `"orchestrator"`, so nothing at spawn time records which kind an orchestrator is; fix by
   recording the distinction as data (a column, a flag, or two role names) — the *mechanism*
   choice is DESIGN-TRUTH's open question at 305-307 and is not proposed here.
5. The composed system prompt is identical for a top, a lead and a sub-orchestrator apart
   from name/parent/workspace substitution (`broker.py:2548-2558`), so even the prompt half
   of "clearly differentiated" is unmet; fix by making the role prompt (or a fourth
   fragment) say which layer the agent is on.
6. `prompts.toml:39-46` tells a top orchestrator "Everything you and your children do belongs
   there", which is false for a top because `broker.py:2530-2532` forks each of its children
   a worktree of their own; fix by choosing the workspace fragment on bare-vs-worktree
   (`Broker.has_worktree`) rather than on whether a workspace name exists.
7. No code path anywhere branches on role (`grep 'role ==' switchboard/*.py` → no hits), so
   there is no routing, verb-gating, cleanup or rendering difference to hang the non-prompt
   mechanism on today; recorded as the current state, not as a fix.

## What I did not check

- Whether messaging scope, worktree sharing, ownership or bare-agent routing are *enforced*
  (task D). I report only what the prompt text says.
- `sb presets` behaviour and plugin/model resolution (tasks A and B). I observed only that
  `presets.for_role(repo, 'orchestrator', ())` returns `['@report-bug']`.
- I spawned nothing and mutated nothing; every store read was opened `mode=ro`.

---
---

# PART D — enforced topology: routing, ownership, visibility, shared worktrees

Auditor: reviewer-7 (child of audit-5). Read-only. Nothing in the repo was changed.
Source read: `/Users/andrew/.herdr/worktrees/switchboard/worker-2/switchboard/*.py`.
Live store read: `/Users/andrew/Code/switchboard/.git/agentflow/state.db` (168 agent rows,
4 top orchestrators — a real multi-tree picture, so almost nothing needed simulating).

Verdicts: **1 BROKEN, 2 PARTIAL, 3 SATISFIED.**

| # | Entry | Verdict |
|---|---|---|
| 1 | bare agent vs orchestrator; where a spawn lands | **PARTIAL** |
| 2 | a lead's children share its worktree | **SATISFIED** |
| 3 | an orchestrator can spawn arbitrary roles | **SATISFIED** |
| 4 | single-parent ownership; siblings may talk | **SATISFIED** |
| 5 | another top's tree is invisible / unreachable | **BROKEN** |
| 6 | only agents are scoped; the board is shared | **PARTIAL** |

---

## The live tree (evidence used throughout)

`python3` against the store, printing `agents.parent` as a tree with
`workspace`/`branch`/`workspace_id`:

```
main   [orchestrator] ws=main   br=None   (bare)
  plugins-redesign-lead [orchestrator] ws=plugins-redesign br=plugins-redesign wsid=wH
    plugin-redesign     [orchestrator] ws=plugins-redesign br=plugins-redesign wsid=wH
      design-a … verify-design  (16 agents, ALL ws=plugins-redesign br=plugins-redesign wsid=wH)
  prompt-work    [worker]  ws=prompts  br=prompts  wsid=wX   + 11 children, all wsid=wX
main-2 [orchestrator] ws=main-2 br=None wsid=w0
  scout-cleanup  [researcher] ws=scout-cleanup br=scout-cleanup wsid=w11
  teardown-lead-2[orchestrator] ws=teardown-fix br=teardown-fix wsid=w1M + 28 children, all w1M
main-3 [orchestrator] ws=main-3 br=None wsid=w16
main-4 [orchestrator] ws=main-4 br=None wsid=w1D
  worker-2 [worker] ws=worker-2 br=worker-2 wsid=w1E
    audit-1 … audit-6 [orchestrator] + ~30 descendants — ALL ws=worker-2 br=worker-2 wsid=w1E
```

Four separate top orchestrators, one shared store, one shared `agents` table.

---

## 1. "A small task … goes to a bare agent; otherwise, an orchestrator" — PARTIAL

(DESIGN-TRUTH.md:135-138, mechanics at :42-46, `delegate` figures placement out at :192-194)

### What is right

**Placement is inferred, and the rule is the parent's worktree, not the child's role.**
`broker.py:2514-2532` — "THE FORK RULE": `if inherited and not self.has_worktree(me):
forked = self._fork_for(name, parent=me)`. `has_worktree` (`broker.py:2224-2231`) reads
`agents.branch` from the store. A top orchestrator's space is bare (`branch IS NULL`), so
every child of a top forks a new worktree/space; anything with a branch lends it.

**Proven live, and it is role-agnostic exactly as the design says.**
- `scout-cleanup` is a **researcher** (a bare worker, not an orchestrator) spawned by top
  `main-2`, and it got its own space: store row `ws=scout-cleanup br=scout-cleanup
  cwd=/Users/andrew/.herdr/worktrees/switchboard/scout-cleanup`, with event id 10398
  `fork {"parent":"main-2","workspace":"scout-cleanup","branch":"scout-cleanup",
  "path":"…/worktrees/switchboard/scout-cleanup","base":"origin/main"}`.
- `worker-2` (role **worker**, parent top `main-4`) likewise: event id 11655
  `fork {"parent":"main-4","workspace":"worker-2","branch":"worker-2",…}`. I am running
  inside that worktree now.
- Top-spawned **orchestrators** take the same path: `teardown-lead-2` → `ws=teardown-fix`,
  `plugins-redesign-lead` → `ws=plugins-redesign`.

So "top spawns a bare agent = new worktree/space" and "top spawns an orchestrator = same
thing" both hold in code and in the live store.

(`sb-guard` and `workspace-debug`, children of `main` with `ws=main br=None`, are NOT
counter-evidence: created 2026-08-07 17:36 and 18:53, and the fork rule landed
2026-08-07 19:21:32 — `git log -1 -S"THE FORK RULE" -- switchboard/broker.py`.)

### What is wrong

**(a) "That agent CANNOT SPAWN OTHER AGENTS" is enforced NOWHERE.** `Broker.delegate`
(`broker.py:2479-2647`) never reads the caller's role or the caller's row at all except to
inherit workspace/branch; `roles.Role` (`roles.py:36-65`) has fields `name`, `model`,
`cleanup`, `prompt` and no spawn capability; the CLI's `delegate` branch
(`cli.py:719-737`) passes `me=me` straight through with no check. `grep -rn "cannot
spawn\|may not spawn\|no children" switchboard/` returns nothing.

Live counterexample, not a simulation: **`worker-2` has role `worker`, was spawned
directly by top `main-4` into its own space, and has 15 direct children including six
orchestrators** (`audit-1` … `audit-6`), which in turn have ~30 of their own. `sb status`
draws the whole thing. A bare agent spawning a fleet is what actually happens today.

**(b) The bare-vs-orchestrator choice IS a caller flag.** `cli.py:125`
`d.add_argument("--role", default=broker_mod.DEFAULT_ROLE)`. Nothing about the task is
inspected; the parent types `--role orchestrator` or `--role worker`. DESIGN-TRUTH:192-194
is specifically about *where a spawn lands*, and that part is genuinely inferred — but
there is no mechanism at all connecting "small task, one agent end to end" to the choice.

**(c) `--workspace` is a caller placement flag that bypasses the fork rule.**
`cli.py:132` + `cli.py:729` (`join = b.join_workspace(args.workspace)`), and
`broker.py:2504` `inherited = workspace is None` — a named workspace turns the fork rule
off (`broker.py:2527-2531`, "Only on the INHERITED path"). Live consequence: `main-2`
spawned **two** direct children into **one** space — `audit-cleanup-lead` and `audit-lead`,
both `ws=audit-cleanup br=audit-cleanup wsid=w14`, delegate events id 10478 and 10468 both
carrying `"workspace": "audit-cleanup"` and **no** accompanying `fork` event. Two
independent children of a top sharing one worktree contradicts "top spawns X = new
worktree/space".

### Gaps (one line each)

- `Broker.delegate` (broker.py:2479) never checks the caller's role, so an agent spawned as a bare worker can spawn a whole subtree; fix by refusing delegation when the caller's row is a non-orchestrator role (or by recording a `can_spawn` fact on the row at spawn time) rather than only asking for it in prompt text.
- `sb delegate --workspace <name>` (cli.py:132, broker.py:2504/2527) lets a caller override placement and skip the fork rule, which is how `audit-lead` and `audit-cleanup-lead` ended up sharing one worktree under one top; fix by refusing `--workspace` for a caller with no worktree of its own (a top), so only inheritance or a fork can place a top's child.
- Nothing maps "small, clear, one agent end to end" to bare-vs-orchestrator — it is purely `--role` typed by the caller (cli.py:125); fix by deciding whether that judgement stays the parent's (then say so and drop the DESIGN-TRUTH:192-194 reading that delegate decides) or becomes a delegate-side input.

---

## 2. "A lead's children share its worktree" — SATISFIED

(DESIGN-TRUTH.md:143-144, :49-51)

**Where the path comes from.** `delegate` inherits: `broker.py:2504-2512` —
`inherited = workspace is None`; `ws = self._workspace_of(me)`; `branch =
self.worktree_branch(me)`. Where the child actually runs: `broker.py:2541-2546`
(`cwd` → `self._recorded_path(ws)` → `self.repo`), recorded on the row at
`broker.py:2581-2589` (`cwd=str(where), workspace=ws, branch=branch`). The herdr tab goes
into the parent's workspace id, not whatever has focus: `_parent_workspace_id`
(`broker.py:2298-2338`) and `_tab_for` (`broker.py:2340-2379`).

**A child of a lead genuinely reuses the lead's worktree, and a sub-orchestrator's whole
subtree stays in that one space** — live, from the store:

- `worker-2` (br=worker-2, wsid=w1E) → `audit-1`…`audit-6` (role orchestrator) → their
  children. Every one of the ~37 rows in that subtree reads `ws=worker-2 br=worker-2
  wsid=w1E`. My own spawn event: id 17464 `delegate {"parent":"audit-5","role":"reviewer",
  "workspace":"worker-2"}` — a **delegate** event with **no fork** event beside it.
- Three-level case in another tree: `plugins-redesign-lead` → `plugin-redesign`
  (orchestrator) → 16 workers, all `wsid=wH`.
- Same again at `workspace-model-lead` → `wm-model` (orchestrator) → 4 implementers, all
  `wsid=wJ`.

**The "assigns disjoint files / serialises overlaps" half is not a code property** and
nothing in `switchboard/` attempts it — no locking, no per-file ownership. That is
correct as read (it is an instruction to the lead), but worth stating plainly: the shared
worktree is real and unguarded, which is the same hole DESIGN-TRUTH:104-106 already names
for a dead agent's edits.

### Two things adjacent to this that are not yet biting

- Some rows carry a workspace but `branch IS NULL` (`design-patch`, `phase1-split`,
  `verify-design`, `wm-land`, `write-design`). `has_worktree` reads `agents.branch`
  (`broker.py:2231`), so **any child of such an agent would fork out of its lead's space**
  — breaking "the whole subtree stays in one space". None of those five has children, so
  it has not happened yet. Latent, real.
- `join_workspace` (`broker.py:902-938`) has no tree check — see entry 5.

---

## 3. "It can spawn discovery or scout or research agents or whatever" — SATISFIED

The role set is **open at the delegate boundary**. `roles.get` (`roles.py:78-90`): an
unknown name returns a `Role` carrying that name with the fallback role's tier, cleanup
and prompt. `delegate` calls it unconditionally (`broker.py:2499`) and never validates
against a list. The module docstring's claim (`roles.py:4-5`, "there is no closed set")
checks out against the code.

Ran it:

```
$ ls defaults/roles/ → orchestrator.md qa.md researcher.md reviewer.md worker.md
$ PYTHONPATH=. python3 -c "…roles.load / roles.get…"
defined roles: ['orchestrator','qa','researcher','reviewer','worker']
roles used in store: ['architect','builder','implementer','orchestrator','researcher','reviewer','worker']
used but UNDEFINED: ['architect','builder','implementer']
unknown role resolves -> wombat-whisperer tier default cleanup close prompt? True
```

So three roles with **no definition file at all** — `architect`, `builder`, `implementer`
— have been spawned successfully and repeatedly in this store (`design-c` and
`archived-rows` as architect, `doc-sweep` and `land-rebase` as builder, `fork-rule` and
`store-split` as implementer). That is the entry demonstrated live, not inferred.

---

## 4. Ownership is single-parent; top-spawned siblings can talk — SATISFIED

**Single-parent in the data model.** `agents.parent` is one nullable column
(`store.py:_wanted`/`_table_ddl`; visible in every row I printed). There is no join table
and no second owner. `children_of` (`store.py:939`) is `WHERE parent=?`; `_descendants`
(`broker.py:3114-3120`) walks that one edge. `delegate` writes it once, at
`broker.py:2582`: `parent=(None if me == HUMAN else me)`. A top's direct children have
`parent='main-4'` and nothing else points at them.

**They answer to it.** `done` (`broker.py:2850-2869`) addresses the summary to
`a["parent"]` and rings only that agent. `block` (`broker.py:2871-2904`) deliberately does
not touch the parent.

**They CAN talk to each other, and the design says they should be able to.** `tell`
(`broker.py:2670-2711`) resolves the name (`_resolve`, `broker.py:407-411` — `parent`
keyword or a literal name), writes the row, rings. No sibling check, no ownership check.
Historic proof from the store, no simulation needed: messages id 8 and id 12,
`workspace-model-lead → plugins-redesign-lead` and back, both direct children of top
`main`. Design says they can and merely should not — so this is **correct**, and adding a
block here would be the deviation.

Small note, not a verdict: `tell` does not check the target exists (`ask` does, at
`broker.py:2746-2749`). A typo'd name writes a row nobody will ever read and exits 0.

---

## 5. "Any other top orchestrator's entire tree is invisible" — BROKEN

(DESIGN-TRUTH.md:157-160: *"Across that boundary agents cannot `sb tell` or anything
else."*)

**There is no tree boundary anywhere except in `cleanup`.** The store is global —
one `agents` table, one `messages` table, one `events` table, keyed by name only
(`store.py:880` `get_agent` = `WHERE name=?`). Name lookup is global everywhere.

Per verb, checked one at a time:

| verb | scoped? | where |
|---|---|---|
| `sb tell` | **no** | `broker.tell` broker.py:2670-2711 — `_resolve` then `put_message`; no predicate on the target's tree |
| `sb ask` | **no** | `broker.ask` broker.py:2737-2755 — existence check only (`store.get_agent`), no tree check |
| `sb status` | **no** | `status.collect` status.py:402 `SELECT * FROM agents`; `mine` is an **opt-in flag** (cli.py:171, cli.py:805), default `None` |
| `sb inspect` | **no** | cli.py:902-909 → `status_mod.inspect(db, h, args.name, …)`; `me` is never passed |
| `sb log` | **no** | cli.py:917-922 → `store.recent_events(db, agent=args.agent, …)`; no caller identity at all |
| `sb restore` | **no** | `broker.restore` broker.py:3122-3182 — the signature has no `me` parameter; cli.py:892 calls `b.restore(args.name)` |
| `sb interrupt` | **no** | `broker.interrupt` broker.py:3184-3226 — takes `me` only to stamp the message row; cli.py:897 calls `b.interrupt(args.name, args.text)` |
| `sb delegate --workspace` | **no** | `broker.join_workspace` broker.py:902-938 — refuses a bare space and a nonexistent one, never asks whose tree it is |
| `sb cleanup` | **YES** | `broker.cleanup` broker.py:2956-2968 — `scope = self._descendants(me)` for an agent, and a name outside it raises `"not yours to clean up"` |

So exactly one of nine verbs has the check. **The missing check belongs at
`Broker._resolve` (broker.py:407-411)**, which is the one funnel `tell` and `ask` both
pass through and which today does nothing but expand the literal `parent`; and at the
entry of `restore` / `interrupt` / `inspect` / `log`, none of which take a caller identity
to check with.

**Run, from inside tree `main-4`, as `reviewer-7`:**

1. Cross-tree **inspection** — succeeded:
```
$ sb inspect scout-cleanup
scout-cleanup  (researcher)  child of main-2
  task       AUDIT ONLY — do not change any code …
  workspace  scout-cleanup
  cwd        /Users/andrew/.herdr/worktrees/switchboard/scout-cleanup
  RECENT EVENTS  1d01h ago fork {"parent":"main-2", …}
```
`scout-cleanup` is a child of top `main-2`. I am in `main-4`'s tree. Full task text,
workspace, cwd and event history all returned.

2. Cross-tree **log** — succeeded: `sb log --agent scout-cleanup -n 5` returned that
agent's `fork`, `delegate` and `cleanup` events.

3. Cross-tree **status** — succeeded: `sb status` reports `170 agents · 21 alive` (every
agent in every tree, `+135 archived`) and its NEEDS YOU block names agents from the other
two trees outright:
```
NEEDS YOU
  fix-options-2   1 never announced to it, oldest 12h40  →  sb inspect fix-options-2   (tree main-2)
  split-fixer     4 never announced to it, oldest 16h09  →  sb inspect split-fixer     (tree main-3)
  board-teardown  1 never announced to it, oldest 15h21  →  sb inspect board-teardown  (tree main-3)
```

4. Cross-tree **tell** — succeeded. Executed against a **copy** of the real store so the
live store was not written to, driving the real `Broker.tell` with a stub herdr:
```
$ cp <state.db> $SCRATCH/copy.db
$ PYTHONPATH=. python3 -c "… b.tell(['main-2'], 'audit probe: cross-tree tell', me='reviewer-7') …"
  _ring called for main-2
tell returned message ids: [333]
stored row: {'from_agent':'reviewer-7','to_agent':'main-2','kind':'tell','body':'audit probe: cross-tree tell'}
```
`reviewer-7` (tree `main-4`) addressed `main-2`, the **root of another tree**: accepted,
persisted, doorbell rung. No refusal path exists to hit.

I did not exercise a cross-tree `restore` or `interrupt` — both are genuinely destructive
to a live foreign agent, and the absent-`me` signatures at broker.py:3122 and broker.py:3184
are the evidence. The store also contains **zero** cross-tree messages historically (I
checked all 342 rows in `messages` by resolving each endpoint to its tree root), so nobody has
tripped this by accident yet — it is unenforced, not merely un-noticed.

### Gaps

- `Broker._resolve` (broker.py:407) resolves any name globally, so `sb tell`/`sb ask` cross tree boundaries freely; fix by resolving against the caller's own tree root and refusing a target under a different root.
- `sb inspect` and `sb log` (cli.py:902, cli.py:917) never receive `me`, so any agent reads any other tree's task text, cwd, transcript and event history; fix by threading `me` in and filtering to the caller's tree (with the human, `me == HUMAN`, exempt).
- `status.collect` (status.py:402) is global and `--mine` is opt-in (cli.py:805), so an agent's default `sb status` is the whole machine; fix by making the caller's tree the default scope for an agent and leaving the global view to `sb board`.
- `Broker.restore` (broker.py:3122) and `Broker.interrupt` (broker.py:3184) take no caller scope, so an agent can revive or interrupt an agent in another top's tree; fix by taking `me` and applying the same tree check `cleanup` already applies.
- `Broker.join_workspace` (broker.py:902) will place a child into any tree's worktree by name; fix by refusing a workspace whose agents live under a different tree root.

---

## 6. "Only agents have the scope constraints. The board is shared." — PARTIAL

**The board half is right.** `sb board` is human-only and gated in code, not merely hidden:
`cli.py:690-703` — `if me != broker_mod.HUMAN: print("sb: board is a human-only view; you
are '<name>'."); return 1`, with `whoami()` resolving by session id or pane id so anything
with an agent row is refused. And it shows everything: the panel reads a snapshot from
`collector.py:112`, `status_mod.collect(db, Herdr(), reap=False)` — no `mine`, no filter,
so the tree it draws is every root in the store. Andrew does cross freely.

**The other half fails, from the other direction.** The sentence is an asymmetry — board
unscoped, agents scoped — and agents are not scoped either. Everything in entry 5 applies:
an agent's `sb status`, `sb inspect`, `sb log`, `sb tell`, `sb ask`, `sb restore`,
`sb interrupt` all reach across trees. `cleanup` is the single exception. So the board is
shared as designed, but it is not the *only* shared surface, which is what the entry
claims.

### Gap

- The board's global view is correct (cli.py:690, collector.py:112) but is not distinguished from an agent's, because agents are unscoped too; fix by landing the entry-5 scoping and leaving `board` — and the human's `me == HUMAN` path — explicitly exempt.

---

## Process notes

- Nothing in the repo was modified. No `git stash`, nothing staged, no commit.
- One simulation, and it wrote to a **copy** of the store in the scratchpad, never the
  real one: the cross-tree `tell` above. No `audit-sim-*` agents were spawned by me, so
  there are no panes, worktrees or branches to clean up. (`audit-sim-block`, visible in
  `sb status`, belongs to another auditor — not mine.)
- The store is at `/Users/andrew/Code/switchboard/.git/agentflow/state.db` (the main
  checkout's), shared by every worktree — worth knowing, since it is why "the store is
  global" is a machine-wide fact and not a per-worktree one.
- I did not test cross-tree `sb restore` or `sb interrupt` by running them; both would
  have hit a live foreign agent. Marked as code-evidence only above.
