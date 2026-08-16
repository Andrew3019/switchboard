# Scout: prompt/preset/role, board hook & prose-to-cut

Read-only mapping for the "plans" plugin implementation plan. Spec: `design/PLANS-AND-STEPS.md`.
No code was edited.

## 1. Presets

- Module: `switchboard/presets.py`. Bodies live in markdown files, one per preset:
  - shipped: `defaults/presets/<name>.md` (e.g. `adversarial.md`, `evidence.md`, `verify.md`)
  - repo-committed: `<repo>/.switchboard-shared/presets/<name>.md` (this repo's `house-rules.md`
    lives here)
  - machine-local: `<repo>/.switchboard/presets/<name>.md`
  - `presets.available()` (presets.py:127-142) layers all three dirs, later replaces earlier by
    filename stem. `sb presets` lists the union.

- **Bindings** (which presets get auto-attached) are separate from preset files:
  `defaults/presets.toml` → `<repo>/.switchboard-shared/presets.toml` → `<repo>/.switchboard/presets.toml`,
  each with an `all = [...]` list and a `[roles]` table, all APPENDING (presets.py:170-189,
  `config.preset_bindings`). This repo's `.switchboard-shared/presets.toml:19` sets
  `all = ["house-rules"]` — that's how house-rules reaches every agent.

- **Injection at spawn**: `Broker.delegate` (broker.py:3316) builds the system prompt as an
  ordered list — `self._protocol()`, `spawn.identity`, `spawn.roles`, `spawn.workspace`,
  then `r.prompt` (the role file's prose), then `self._resolve_bindings(role, with_)`
  (broker.py:3391-3407). Presets are always LAST, appended after the role prompt.
  `presets.resolve()` (presets.py:192-230) turns each binding name into flattened text
  (`config.flatten`, one line, `;`-joined bullets).

- **Applied to an already-running agent**: only via `sb presets <name> --apply`
  (cli.py:210-217, `Broker.apply_preset`, broker.py:3757). This is **self-service only** — an
  agent reads `sb presets <name>` (or `--apply`) and pastes the procedure into its OWN session
  as a message from itself to itself (broker.py:3757-3781). There is **no path for a parent (or
  anyone else) to push a preset onto a running child** — no such verb exists. `presets.text()`
  (presets.py:151-167) is the read path `--apply` and plain `sb presets <name>` both use.

- **"A preset that exists only for steps to name" (not offered to spawns)** — representable
  today, but only by convention, not enforcement:
  - Ship the `.md` file (makes it *nameable*, via `sb presets <name>` / `--apply` / `--with`).
  - Simply never add a binding for it in any `presets.toml` (`all` / `[roles]`) — then it is
    never auto-attached to a spawn.
  - **Gap**: nothing stops a human or an agent from typing `sb delegate --with <name>` and
    attaching it to a spawn anyway — `presets.resolve()` treats every preset file identically
    regardless of how the caller reached it (presets.py:192-230). There is no flag on a preset
    file (front-matter or otherwise) marking it "read-only, do not bind at spawn". If the plans
    plugin wants a preset that is *structurally* spawn-only, that check does not exist and would
    need to be added — right now it's purely "don't write a binding for it, and hope nobody
    types `--with`".

## 2. Roles

- Module: `switchboard/roles.py`. Bodies: `defaults/roles/<name>.md` (dispatcher, lead, qa,
  researcher, reviewer, worker), overridable per-repo via `<repo>/.switchboard/roles.toml`
  (field overrides) and `<repo>/.switchboard/roles/*.md` (whole files), merged field-by-field
  (`config.roles`, roles.py:72-79).
- Each role file has TOML front-matter (`model`, `delegate`) then prose. Prose is flattened
  the same way as protocol/presets (`config.flatten`) — see `config.front_matter` (config.py:294).
- Assembly into spawn: `r.prompt` is inserted into the prompt list in `Broker.delegate` right
  after `spawn.workspace` and before presets (broker.py:3403-3407: `if as_prompt: … elif
  r.prompt: prompts.append(r.prompt)`).
- **Files needing edits per the spec**:
  - `defaults/roles/lead.md` — "survives with cuts rather than a rewrite" (spec: design/PLANS-AND-STEPS.md:403-405).
    Its "Plan, then re-plan" section (lead.md:179-189) is the thing the spec says a lead can
    treat as already satisfied once plan-making exists (spec line 55-57) — this is prose, not
    a prohibition, so nothing here currently blocks or contradicts a plans plugin; it just
    needs trimming once basic steps exist.
  - `defaults/roles/worker.md` — needs an edit for the "sole worker counts as lead" case (spec:
    design/PLANS-AND-STEPS.md:154-157: *"its role has to say so: the worker role otherwise
    tells it to carry one task and do nothing beyond it, which reads as a reason not to."*).
    Current worker.md:59-73 says exactly that: *"You are given one task: carry it to done and
    do nothing beyond it… If the task turns out to be bigger than one agent, say so to your
    parent rather than taking it on or spawning agents of your own."* — this is the sentence
    the spec means, and it will need a carve-out for plan-authoring-as-sole-worker.
  - No merge/push/approval language exists in `worker.md` or `dispatcher.md` themselves (I
    grepped both) — the merge-gate prose-to-cut lives in `protocol.md`, `house-rules.md` and
    `DESIGN-TRUTH.md` only (see §4).

## 3. Board / rendering

- Renderers: `switchboard/board.py` (plain-text fallback, `layout()` at board.py:639) and
  `switchboard/richboard.py` (the `rich`-based board, `layout()` at richboard.py:509). Both are
  called with the same `snap` (a `status.Snapshot`) and both independently walk
  `status.display_rows(snap.agents, ...)` to get an ordered list of rows to draw
  (board.py:706, richboard mirrors it).
- **Rows are exclusively `status.AgentStatus` or `status.Collapsed`** — there is no third row
  kind. `AgentStatus` (status.py:405) carries `depth`, `workspace`, `parent`, plus liveness
  fields (`alive`, `state`, `herdr_state`, `stalled`, `gone`, `turn`, `idle`, `idle_excuse`,
  `blocked_why`) — all populated by `status.collect()`.
- **Worktree grouping**: NOT depth-based. `richboard.group_runs()` (richboard.py:427-449)
  groups *consecutive rows sharing the same `.workspace` string* — a run breaks whenever
  `row.workspace` changes, regardless of depth (a depth-1 child with its parent's own
  workspace is a separate case the comment calls out explicitly). `board.py`'s plain renderer
  does the analogous grouping via `_starts_group`/`group_runs` reused from richboard
  (board.py:582, `_is_group`/`_starts_group` reference `richboard.group_runs`-style logic).
  The bracket/gutter drawing is `richboard.gutter_column()` (richboard.py:455-495).
- **Liveness read**: rows already carry it — `AgentStatus.alive` / `.stalled` / `.gone` /
  `.display_state` (status.py:495, a computed property) — assembled once per snapshot by
  `status.collect()` (status.py:999). Nothing in board.py/richboard.py talks to herdr directly;
  they only read fields already on the row. A plans hook that wants "is this step's owning
  agent alive" would read the **same** `AgentStatus` row (by agent name) rather than inventing
  a second liveness channel — this matches spec line 128-130 ("plans never store liveness…
  always read from the agent, never copied onto the step").
- **Extension point today: none.** `layout()` in both renderers is a single function that
  emits `(text, owner)` row tuples directly from `status.display_rows()`'s output — there is no
  callback, registry, or plugin lookup anywhere in board.py or richboard.py. `plugins.py`'s
  own docstring lists `board` among the *zero-cost* CLI verbs (plugins.py:23-25) — that's just
  `sb board` the command, unrelated to any rendering hook; plugin code is never imported by the
  board today.
- **Exactly where a "render plans under this worktree" hook would slot in**: inside the
  per-row-run loop, immediately after a worktree's `group_runs` run is identified and before/
  after its member agent rows are emitted — i.e. right where `richboard.layout()` iterates
  `window` and calls `_row()` per agent (richboard.py ~783-853) and where `board.layout()`'s
  equivalent loop does the same (board.py: the `for a, brk in window:` loop, ~810-850). Both
  renderers would need: (a) a way to ask "does workspace X have plans, and what are their
  step summaries" without importing plugin code (violates the "no verb that spawns imports
  plugin code" isolation plugins.py:31-35 argues for, though board isn't a spawn verb so this
  specific rule may not bind it — still, today NOTHING in board.py imports `plugins`), and
  (b) extra emitted lines per workspace group, sized into `costs`/`_max_top` window-fitting
  math (board.py:706-729, `_row_budget`/`costs` arithmetic) since that math currently assumes
  1 or 2 lines per row and would need to account for N extra plan lines per group.
- Confirms the design doc's own claim (design/PLANS-AND-STEPS.md:513-515): *"the board needs a
  hook for it… rendering plans under their worktree is the one thing the plugin cannot do from
  outside, so the board grows an extension point."* This is accurate — there is nothing to
  reuse, a hook must be added from scratch in both board.py and richboard.py (they do not share
  a row-emission function, so it's two call sites, not one).

## 4. The prose that gates replace — exact quotes, file:line

### (a) `defaults/protocol.md` (the injected system prompt; source of `PROTOCOL_LINE`)

Lines 236-241 (prose section, i.e. below the `-->` at line 201; wrapped-for-humans form —
flattened to one line at spawn):

> Work that ships has a default shape: a branch named for your workspace, push it,
> open the pull request, and put its URL in your summary. Pushing and merging are your
> parent's call, not yours — an explicit instruction from your parent, in your task or
> your inbox, is what authorises either, and your parent may be an agent or the human.
> Never merge without that say-so; there is no merge verb. If you have not been told,
> ask the parent that would have to decide it, and if that is the human, stop and ask.

This is the "never merge without your parent" + shipping/push/PR block. It sits between the
`sb tell`/`sb delegate` paragraphs and the "delegate" verb paragraph.

### (b) `.switchboard-shared/presets/house-rules.md` (the `house-rules` preset, bound to `all`)

Lines 87-92 ("**Landing work.**" section):

> **Landing work.** Commit on your own branch. By default the lead integrates: do not
> push, open a pull request, merge or touch `main` unless your parent told you to. If it did,
> that instruction is your authority — follow it.
>
> - Anything you left unproven belongs in your summary. Unproven and stated is fine; unproven
>   and silent is not.

The push/PR/merge/main prohibition is the first sentence-and-a-half of that section; the
"anything you left unproven" bullet is unrelated (verification reporting) and should NOT be
cut — only the "do not push, open a pull request, merge or touch main" clause is part of the
three-approvals prose the merge gate replaces.

### (c) `DESIGN-TRUTH.md`

Three separate passages name the "three approvals" (create PR / merge / cleanup) and the
merge-without-asking rule:

1. **Lines 92-104** ("When work finishes"):
   > Once all of its children are done, that lead either reports done or blocks, depending on
   > whether the task is fully complete: fully complete, report done; Andrew's input needed to
   > finish it, block. Once that is done it reports done, and the dispatcher blocks. A lead
   > cleans up its children, pushes the PR if relevant, and summarizes — it does not close
   > itself, since cleaning a lead takes its children and it still has to report. A dispatcher
   > hands work to a lead or to a single worker, and where a worker is directly under it, that
   > agent pushes and opens its own PR if it was told to; the dispatcher blocks for it either
   > way, since being told his work has landed is the one report a dispatcher makes.

2. **Lines 416-426** ("The lead handles cleanup itself…"):
   > Cleaning up a lead always cleans its children. What stays open below a dispatcher is
   > still decided by the person watching the board, and never by the dispatcher sweeping on
   > its own judgement — what changes is that the dispatcher carries that decision out. It
   > closes children when Andrew tells it to, and when a child reports its task fully done it
   > may ask him to approve closing it.

3. **Lines 532-538** ("Pushing and merging are decided by the parent…") — the canonical
   statement, and the one most directly superseded by the merge gate:
   > **Pushing and merging are decided by the parent, which may or may not be a human.** An
   > agent can push if its parent says so; a lead can push if the dispatcher says so; any
   > agent can merge if Andrew tells some dispatcher and it passes that instruction down. So
   > it is never merge without asking your parent. The default shape of shipping work is
   > branch named for the workspace, push, open the PR, and put its URL in the summary. —
   > confirmed 2026-08-12, superseding the 2026-08-09 rule that merging needed Andrew's own
   > explicit approval and that no agent merges without asking first

The "three approvals" language (create PR / merge / cleanup as three separate Andrew sign-offs)
is spread across passages 1 and 2 above — DESIGN-TRUTH does not state them as a clean numbered
list anywhere; they are the PR-push clause (passage 1), the cleanup-approval clause (passage 2),
and the merge-authorisation clause (passage 3). A future edit trimming this to a pointer at the
merge gate will need to touch all three passages, and per the project's own consistency-pass
rule (`design-truth-consistency-pass` memory), that edit must re-read the whole file rather than
just append a note — DESIGN-TRUTH.md is Andrew-only to edit regardless.

**Order dependency confirmed by the spec itself** (design/PLANS-AND-STEPS.md:507-511): the merge
gate cannot ship before these three cuts land, because right now an agent running the gate would
read it telling them to merge alongside three texts telling them never to merge without asking —
exactly the contradiction that split four agents' behavior in the incident DESIGN-TRUTH:110-117
describes.

## 5. Where the protocol/system prompt is authored

- **Source file**: `defaults/protocol.md` — prose, HTML-commented rationale above a `-->` line,
  then the actual prompt text (protocol.md:203-308, "# The switchboard protocol" heading is
  itself stripped by `flatten`).
- **Repo override**: `<repo>/.switchboard/protocol.md` REPLACES (not merges with) the shipped
  one — `config.protocol_override()` (config.py:458-460), consumed by `config.protocol()`
  (config.py:441-448: `flatten(protocol_override(repo) or _shipped_protocol())`).
- **Loaded into the running process**: `switchboard/broker.py:124` —
  `PROTOCOL_LINE = config.protocol()`, a module-level constant computed once at import.
- **Per-broker override support**: `Broker.__init__` also captures
  `self._protocol_override = config.protocol_override(self.repo)` (broker.py:608), and
  `Broker._protocol()` (broker.py:626-628) prefers that flattened override over the module-level
  `PROTOCOL_LINE` — this is what makes the override testable/patchable without reimporting.
- **Injected at spawn**: `Broker.delegate` puts `self._protocol()` as the FIRST element of the
  `prompts` list (broker.py:3400-3402), ahead of identity, roles-list, workspace, role prompt,
  and presets, and it's `--append-system-prompt-file`'d to herdr (per protocol.md:11-14's
  comment) rather than passed as a task argument.
- **This is where the "one trigger line to every agent at spawn" (the plans-exist trigger, spec
  line 148-152) most likely lands** — `defaults/protocol.md`, appended as its own short sentence,
  since it is the one text guaranteed to reach every spawn regardless of role and preset
  bindings. Alternative: a new universal preset bound in `all` (like `house-rules` or
  `report-bug`/`suggestions`) — but the spec explicitly says the trigger "travels at spawn, even
  though the instruction does not" (spec line 148), which matches the protocol/every-agent
  reach better than a preset (presets can be reset with `"!reset"` per-repo, per
  `defaults/presets.toml:13-15`, so a preset-based trigger could be silently dropped by a repo's
  own bindings — the protocol cannot be reset that way, only replaced wholesale).

## Design assumptions the code does not yet support (flagged for the plan)

1. **No board hook exists at all.** Confirmed in §3 — this is not a small gap, it's building an
   extension point from nothing, in two separate renderers (board.py and richboard.py do not
   share row-emission code), plus adjusting the scroll/window-fit math in both
   (`_max_top`/`_row_budget`/`costs`) to account for variable-height plan blocks per workspace.
2. **"Preset that exists only for steps to name" has no enforcement mechanism.** It's
   achievable by convention (don't bind it) but nothing stops `--with <name>` attaching it to a
   spawn anyway — see §1. If the plans plugin needs this to be a hard guarantee rather than a
   convention, that's new code in `presets.py`/`presets.toml` schema, not something that exists
   today.
3. **The merge gate is hard-blocked on three separate prose edits landing first** (protocol.md,
   house-rules.md, DESIGN-TRUTH.md — §4), confirmed by the spec's own text and by a real
   documented incident of agents disagreeing when the two sources conflicted.
4. **Presets cannot be pushed to a running agent by anyone but itself** — `apply_preset` is
   self-only. If a plan/step design wants a lead or a gate to inject a preset into an
   already-running child, that verb does not exist yet.
