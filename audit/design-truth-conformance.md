# DESIGN-TRUTH conformance audit

Audited against `main` @ `0a0fa4f` (1148 tests passing), from a read-only worktree on branch
`design-truth-audit`. Every `DESIGN-TRUTH.md` entry is checked in turn against the current
code: verdict first, evidence after. No code was changed to produce this; `DESIGN-TRUTH.md`
itself was not touched.

Verdicts used: **honoured** (code matches the claim), **not honoured** (code contradicts or
fails to implement the claim), **partly** (some of the claim is true, some isn't — the split
is spelled out), **not code-checkable** (a taste/intent statement with nothing to falsify).

---

## Critical user journeys (CUJs)

**Starting work — `sb start` makes a new bare space, no worktree, top orchestrator.**
Honoured. `Broker.start` (`switchboard/broker.py:832-850`) always routes through `_top`
(`broker.py:899-982`), which never calls `create_worktree` and spawns via
`h.create_workspace(name, cwd=str(self.repo))`. `is_top=True` is stamped only there
(`broker.py:965-973`).
Test: `sb start`, then `git worktree list` — no new entry for it; `sb workspace list` shows
no checkout/branch for the top.
Pinned by: `tests/test_broker.py::test_start_creates_the_top_orchestrator_as_a_root`,
`tests/test_workspace.py::test_start_creates_no_branch_and_no_worktree`.

**Anything that might need code changes gets a workspace/worktree; unclear scope gets an
orchestrator named `<name>-lead`.**
Partly. The worktree-granting mechanism is code-enforced (see spawn-landing entry below).
The `<name>-lead` naming convention is **not** derived or enforced anywhere —
`Broker._unique_name` (`broker.py:3222-3226`) produces `<role>-<n>`, and nothing checks a
lead's name ends in `-lead`. DESIGN-TRUTH's own wording ("can be called") reads as
permissive, so this may not be a real gap — flagging only because "can be called" is
ambiguous between "convention" and "the code should generate it."

**Only `sb start` creates a top; `is_top` stamp (not the prompt) drives `sb delegate`'s
branching; a bare agent's delegate is refused outright.**
Honoured. Stamp write: `broker.py:965-973`, comment states it is set "HERE and nowhere
else." Stamp read: `Broker.is_top` (`broker.py:2511-2523`) reads the `agents.is_top` column
only. Branch point: `Broker.mints_space` (`broker.py:2525-2542`). Bare-agent refusal:
`Broker._refuse_bare_delegate` (`broker.py:646-671`), keyed on the role's `delegate` field,
not the role's name.
Test: create an agent with `role="worker"`, call `delegate` as that agent — raises
`ValueError` ("does not spawn"), no row/pane created.
Pinned by: `tests/test_structure.py::TopStampTest`,
`tests/test_structure.py::BareAgentCannotDelegateTest` (including
`test_bareness_is_a_field_on_the_role_not_the_role_s_name`, which proves it isn't a
string check on `"worker"`).

**Only a human may create a top orchestrator; `sb start` is refused for agents.**
Honoured — and this is a genuinely new, implemented control (docstrings cite "confirmed
2026-08-11"). `cli.py:779-790` refuses `start` when `_agent_caller(me)` resolves non-None.
`_agent_caller` (`cli.py:509-539`) checks both a known store row **and**
`CLAUDE_CODE_SESSION_ID`/`CLAUDECODE` env markers, closing the specific hole ("three
unwanted top orchestrators in one afternoon" per comment) where an agent in a fresh clone
has no store row at all.
Test: `HERDR_PANE_ID=<agent's pane> sb start` → exit 1; `CLAUDE_CODE_SESSION_ID=x sb start`
in an empty store → same refusal.
Pinned by: `tests/test_structure.py::OnlyAHumanStartsATopTest`.
Side effect not in DESIGN-TRUTH: this also refuses a **human** running `!sb start` from
inside their own Claude Code session (the env markers can't distinguish that from an
agent) — a deliberate fail-closed trade-off the doc doesn't mention.

**A fork that fails refuses the spawn and tells the parent, never falls back to Andrew's own
checkout; `sb start` inside a worktree is refused, naming the main checkout.**
Honoured. `ForkFailed` (`broker.py:216-241`) is raised, not degraded, on every failure path
in `_fork_for` (`broker.py:2803-2871`). Worktree refusal:
`Broker._refuse_outside_main_checkout` (`broker.py:852-878`), called first in `start`.
Pinned by: `tests/test_broker.py::test_start_inside_a_worktree_is_refused_and_names_the_main_checkout`,
`test_an_unanswerable_main_checkout_does_not_refuse`.

**Spawn landing: only the top ever creates a space — "(This has not been the case.)"**
Honoured now; the parenthetical documents a fixed historical bug, not a live gap. Before the
fix, fork-vs-tab was decided by worktree possession rather than the `is_top` stamp — those
coincided in practice until a worktree-less non-top agent (deep in a tree) delegated and its
child incorrectly minted a new space. Fixed by switching the check to `mints_space`, which
reads `is_top` exclusively (`broker.py:2525-2542, 2968-2996`, citing `audit/phase5-spawn-placement.md`
by name in a comment).
Test: top → lead (forks) → sub-orchestrator (tabs) → grandchild (tabs) — exactly one
`create_worktree` call across the whole tree, all three non-top agents share one `workspace`.
Pinned by: `tests/test_structure.py::WorktreeIsNotTopnessTest` (four tests, explicitly named
for the bug), docstring: "The phase-5 bug, pinned."
**Recommendation for Andrew:** the parenthetical is now describing a resolved bug, not an
open one — consider whether the entry should be edited to say so (not something this audit
can do itself).

**A worktree belongs to a space, not an agent; a lead's spawns share it; a bare agent gets
its own; the sole exception is a 100%-clear read-only task using no worktree at all.**
Partly. The first three clauses are solid and tested (see spawn-landing entry above for the
sharing proof). The **read-only exception has no implementing code path**: the fork
decision (`broker.py:2996`) is unconditional whenever `inherited and mints_space(me)` —
there's no flag, no branch on task content, no way for a top's spawn to land with zero
worktree. `sb delegate --workspace <name>` can only join an *existing* worktree space; it
explicitly refuses to join the top's own bare space (`Broker.join_workspace`,
`broker.py:1203-1236`, `"a bare space with no checkout of its own"`).
Test: from a top, `sb delegate "read this file" --role researcher` with no `--workspace` —
`git worktree list` gains an entry every time regardless of task content.
Fix size: small-to-medium. Either a new `--no-worktree`-style escape hatch on `delegate`, or
relaxing `join_workspace`'s bare-space refusal for a caller asserting read-only intent.
Touches `broker.py` (`delegate`, `join_workspace`, `_fork_for`), `cli.py`'s delegate
argparse, plus new tests. **Question for Andrew:** is this a real gap, or was the exception
quietly abandoned in favor of "every spawn gets a worktree, always"? The comment trail
argues *against* ever writing into the top's own checkout, so this may be deliberate.
Recommended answer: treat it as abandoned (drop the exception from DESIGN-TRUTH) unless a
concrete read-only use case is pushing for it.

**While work runs, the top orchestrator is idle, not monitoring; persists until Andrew
closes it.**
Honoured. A top with a live child is explicitly exempted from the "stalled" signal that
would otherwise trigger a reconciler nudge (`status.py:707-720, 806`, comment: "an
orchestrator that ended its turn because the protocol told it to... has done exactly what
was asked of it"). Nothing auto-closes a top when children finish — `cleanup` only acts on
an explicit caller/name, and an agent cannot close its own pane.
Test: spawn top → long-running child → run `sb reconcile` repeatedly — top never receives a
stall ping while the child is `working`/`blocked`.
Pinned by: `tests/test_structure.py::test_a_waiting_orchestrator_is_not_stalled_but_a_told_one_is`,
`test_a_parent_with_a_live_child_is_left_alone`.

**When work finishes: cascading done/block reporting, lead pushes PR and summarizes without
closing itself, bare agent under top pushes/opens own PR, block always goes to human not
parent, cleanup only after resolution.**
Partly. The store-level mechanics are code-enforced and tested: worker→parent `done`
reporting (`broker.py:3359-3430`), block always surfacing to the human never the parent
(`broker.py:3432-3482`, no `_ring` to `parent` anywhere in `block()`), an agent cannot close
its own pane, cleanup never lifts the live-descendants gate even under `--force`
(`broker.py:3517-3531`, pinned by `test_nothing_at_all_closes_over_a_live_child`,
`test_force_does_not_close_a_parent_over_its_live_child`).
The **PR-push/open/summarize cascade is protocol-only** — switchboard has no git/`gh`
logic of its own; it's delivered as prompt text (`defaults/protocol.md:169-173`) that an
agent could, in principle, ignore. There is zero code enforcing "a lead pushes before
closing" or "a bare agent opens its own PR." This is very likely intentional (state lives
in the store; git actions belong to agents) — flagging so nobody mistakes it for a
DESIGN-TRUTH claim the code backs up mechanically.
Test (code-enforced half only): lead with a live child calls `sb done` — parent sees it;
`sb cleanup <lead>` from its parent refuses with the live-descendants message until the
child closes.

### Unconfirmed assumptions found in code (CUJs area) — not in DESIGN-TRUTH at all

- `sb start --name` on an existing, still-running top **hands it the task** rather than
  erroring or creating a new one (`broker.py:924-950`). DESIGN-TRUTH's "Starting work" entry
  describes only the create path, not this reuse/dedup behavior.
- A row with neither `pane_id` nor `session_id` (dead-spawn wreckage) is silently replaced
  rather than triggering a name-collision error, both for `_top` and `delegate`
  (`broker.py:924-939, 3067-3078`, "THE NAME-REUSE CARVE-OUT").
- An unknown caller (no store row at all) is treated the same as a top for `mints_space`
  purposes, and is *not* refused delegate rights either — both deliberate "don't guess"
  choices (`broker.py:2522-2542`, `646-663`) with no DESIGN-TRUTH counterpart.
- Concurrent `sb delegate` calls from the same top serialize on a single `git worktree add`
  at a time via `_fork_lock` (`broker.py:2237-2260`) — a real latency-affecting guarantee,
  undocumented.
- `same_tree()` returns `True` (lets a message through) when the target name doesn't
  resolve in the store at all, on the theory a typo shouldn't learn about tree boundaries —
  a scope-adjacent judgment call nowhere confirmed by Andrew (see Scope section below too).

---

## Product decisions — General

**If it needs to be known, it is known at spawn (tailored by agent/role).**
Honoured. `broker.py:3012-3030` assembles per-spawn prompts: protocol + identity + role
list, then workspace context if placed in a named workspace, then the role's own prompt,
then preset bindings resolved per-role (`presets.py:151-163`).

**How herdr talks to Claude — types into chat box, presses enter; message looks identical
to Andrew typing; half-written text rides along; queued mid-turn, delivered next turn;
interrupt = escape then direct injection.**
Honoured. `herdr.py:496-522` (`prompt`) matches this exactly per its own docstring, cited as
measured behavior. `herdr.py:721-729` implements escape-then-send for interrupt.

**Every sb message prefixed `[sb: from <name>]`, same channel as Andrew, prefix is the only
disambiguator.**
Honoured. `broker.py:136-151` (`tag`) produces exactly this string; `defaults/prompts.toml`
notes the mark is added "in code, so that overriding the wording here cannot drop the mark."

**switchboard is personal, for now.**
Not code-checkable / confirmed by absence only. No `user_id`/`tenant`/`auth`/login concept
anywhere in `store.py`'s schema or `switchboard/*.py`. This is Andrew's stated intent, not
a mechanism — nothing to falsify either way.

**Role list lightly audited, generated from roles themselves, never hardcoded.**
Honoured. `broker.py:3022`: `self._say("spawn.roles", roles=", ".join(sorted(self.roles)))`.
`roles.py:72-94` confirms an open, file-backed vocabulary with a fallback role, not a closed
enum.
Test: drop `.switchboard/roles/foo.md` into a repo, spawn any agent, `sb inspect` its system
prompt — `foo` appears with zero code changes.

**Model tier set in config, doesn't matter much.**
Honoured, with a caveat worth noting. `defaults/models.toml` resolves tiers via layered
TOML, no model name hardcoded in Python. "Doesn't matter much" isn't code-checkable as a
judgment, but only one provider (`claude`) is actually wired
(`[providers] wired = ["claude"]`) even though the code is structured for more — see
unconfirmed-assumptions below.

**Failure detection: parent told minimally; retries and half-finished-work handling are all
deferred; known hole — a dead agent's edits sit unowned in a shared worktree.**
Partly. Detection exists but is **passive, not active**: when herdr stops reporting an
agent past a grace period, the row is set to `state='failed'`
(`status.py:970-1007, 126-136`) — visible to the parent only if it looks (via `sb
status`/board), not pushed to it. DESIGN-TRUTH's phrasing ("telling the parent") reads as
active notification; the code delivers passive visibility only. Retries: correctly absent
at the task level (only herdr-call-level retries exist, e.g. `SPAWN_ATTEMPTS`). Half-finished
work: **the flagged hole is still real** — no reassignment/ownership-transfer/lock exists
for a dead agent's edits in a shared worktree; `sb workspace close` refuses to delete an
unmerged branch (a safety net on explicit close) but does nothing for a live sibling
working alongside orphaned edits.
Test: kill an agent's pane out-of-band (not via `sb done`/`sb block`), wait past the grace
period, `sb status` shows `failed` — confirm whether the parent is pinged or must notice on
its own (currently: must notice). Leave a dead agent's uncommitted edit in a shared
worktree, spawn a sibling into the same space — nothing warns it.
**Question for Andrew:** is "the parent is told" satisfied by passive board visibility, or
does it need an active ping? Recommended answer: passive visibility is probably fine for now
given "we can start with just telling the parent" reads as low-bar — but the wording in
DESIGN-TRUTH implies more than what's built, worth a one-line clarification either way.

**How many spaces/agents alive at once is fine as-is — no hard cap.**
Honoured. No `max_agents`/`max_spaces`/count-based cap found anywhere; `defaults/settings.toml`'s
`[limits]` section caps only string lengths as "smell detectors," not counts.

**Not too many hard rules — reconciler catches the general idle-unreported case.**
Honoured. `broker.py:4409-4466` (`reconcile`) is keyed off a general `stalled` predicate, not
a per-case rule list.

**Reconciler runs on a loop (maybe same as `sb board`), pings the agent itself (not the
parent) unless awaiting instructions.**
Honoured, precisely. `collector.py:256-301` (`run_reconciler`) fires on the same tick as the
doorbell. `broker.py:4409-4466` pings `self._nudge(a.name, ...)` — the agent, never the
parent, exactly as documented in a comment citing DESIGN-TRUTH by line number. The
`awaiting_task` exemption is implemented (`status.py:745-756`). Two additional, consistent
exemptions exist beyond the doc's one (blocked/done states excluded by definition; a
live-children exemption for a correctly-waiting parent) — additions, not contradictions.

**Human-facing output concise/skimmable/well-formatted, with the "what/result/questions"
shape.**
Honoured — correctly a prompt-level claim, not code-enforced. `defaults/protocol.md`'s final
block is near-verbatim the DESIGN-TRUTH wording. `validate.py` only enforces length/shape on
the separate `block` `why` bookkeeping field, not on chat-message formatting.

**Avoid blocking unless really needed — listed exceptions.**
Honoured, but the source is **stale by one item, and the code says so itself**.
`defaults/protocol.md`'s escalation list includes DESIGN-TRUTH's five reasons **plus a
sixth** ("if an instruction is ambiguous"), with a comment in protocol.md stating explicitly
that Andrew was asked and confirmed this sixth reason, and that "DESIGN-TRUTH's list is the
thing that is short by one, not this sentence."
**Question for Andrew:** should "an instruction is ambiguous" be added to DESIGN-TRUTH's
blocking-exceptions entry? Recommended answer: yes — the code comment claims this was
already confirmed by Andrew in conversation, so it's a transcription gap in DESIGN-TRUTH
rather than a new decision, but per this audit's own rules only Andrew can make that
addition.

### Unconfirmed assumptions found in code (General area) — not in DESIGN-TRUTH at all

- **Multi-provider scaffolding**: `models.toml`'s `[providers] wired = ["claude"]` and
  `models.py`'s `wired_providers()` imply a planned (but nonexistent) second provider
  (e.g. Codex). Not mentioned anywhere in DESIGN-TRUTH.
- **Stop-hook gate**: a hook enforcing "every turn ends in `sb done` or `sb block`" is baked
  into every spawn (`hooks.py`, `herdr.py:441-456`) — a real, load-bearing enforcement
  mechanism the failure-detection and protocol sections of DESIGN-TRUTH never discuss.
- **Collector self-restart on source change** (`collector.py:333-397`) — a running collector
  can silently restart mid-session when its own source changes. Operationally significant,
  undocumented.
- **`GONE_STATE = "failed"` reuses the closed `working|blocked|done|failed` vocabulary**
  (`status.py:124-136`) for *observed* failure (herdr goes silent), and there is no distinct
  self-reported failure verb (`sb fail` does not exist). DESIGN-TRUTH's "we should detect
  failures" doesn't distinguish self-reported vs. observed, and only the observed path is
  built.

---

## Product decisions — Orchestrators

**The top orchestrator is everything: scope is its whole tree; job is to orchestrate
worktree/orchestrator/workspace creation.**
Not code-checkable — a framing statement, not a testable mechanism.

**Small, single-agent-doable task → bare agent; otherwise orchestrator. Top spawning a
bare agent directly skips extra layers.**
Honoured. The fork rule (`broker.py:2967-2996`) is role-agnostic — any role a top spawns
gets its own space directly. `_refuse_bare_delegate` (`broker.py:646, 2951`) stops a bare
(worker) agent from delegating further, so the chain genuinely terminates there.

**Any orchestrator can spawn discovery/scout/research agents to improve its decisions.**
Honoured. No code restricts which roles an orchestrator may spawn;
`defaults/roles/orchestrator.md:44-47,134` instructs exactly this pattern.

**A lead's children share its worktree, so the lead assigns disjoint files and serialises
overlap.**
Partly — the sharing half is code-enforced (worktree-per-space, proved by the spawn-landing
tests above); the "assigns disjoint files, serialises overlap" half is **100% prompt
discipline**, not code. `defaults/roles/orchestrator.md:141-146` instructs this in words;
nothing in `broker.py`/`store.py` detects or blocks two children writing the same file.
Test showing the gap: spawn two children of a non-top orchestrator with tasks that write
the same file — nothing detects or blocks the collision.
Fix size (if code enforcement is wanted): moderate — new feature, not present today.

**A workspace orchestrator's job is to coordinate review; there is no prompt for that yet.**
**Not honoured — stale, contradicted by newer code.** `defaults/presets/adversarial.md` is
exactly a review-coordination procedure (sequential proposer/reviewer/rotating-lens/
convergence), reachable via `sb presets adversarial`, and explicitly referenced from the
orchestrator role prompt (`defaults/roles/orchestrator.md:129-131`). Separately, there is no
longer a distinct "workspace orchestrator" role at all — the current role file's own header
states "THE orchestrator role — there is only one, deliberately," used identically at every
level.
Test: `sb presets adversarial` prints a full review-coordination procedure, directly
disproving "no prompt for that yet."
**This needs Andrew's attention**: either the entry is now stale and should be
updated/removed, or the *premise* (a workspace-orchestrator-only review flow, distinct from
what any orchestrator can run) was abandoned in favor of a role-agnostic preset. Recommended
answer: mark this entry superseded — the adversarial preset already does what was being
asked for, just without the role split the original entry implied.

**The orchestrator prompt is mostly good already.**
Not code-checkable — a taste judgment. Worth noting only that `defaults/roles/orchestrator.md`
carries its own changelog-style comments citing "six failures observed in one evening's real
runs," implying substantial rewriting since this entry — if the entry predates that rewrite
it may itself be stale, though it isn't falsifiable either way.

**Top and workspace orchestrators must be differentiated by something other than the
prompt.**
Honoured. `store.py:158-171`'s `agents.is_top` column, stamped only by `_top()`
(`broker.py:965-973`), is a DB-level stamp structurally distinct from any prompt text, read
by `mints_space()` to branch spawn behavior.

---

## Product decisions — Scope

**Siblings visible to each other; another top's tree entirely invisible; cross-tree `tell`
etc. blocked; no requirement to separate subtrees within one top's tree.**
Honoured. `broker.py:682-767` (`top_of`, `same_tree`, `require_same_tree`) keys scope by
root ancestor only (whole tree, not sub-branch), so nothing enforces separation *within* one
top's tree, matching "not something we have to do."
Test: two agents under different tops attempting `sb tell` — raises `ValueError` naming the
boundary. Two agents under the same top, different branches — `sb tell` succeeds.

**Only agents have scope constraints; the board is shared and Andrew crosses freely.**
Honoured. `broker.py:741-744`: `if me == HUMAN or target == HUMAN or me == target: return
True`.

**Agents the top spawns directly are owned by it and answer to it; they can talk to each
other but shouldn't.**
Partly. Ownership/reporting (`agents.parent`, the `identity` prompt fragment) is
code-enforced. The "shouldn't talk to peers" half is **prompt-only, unenforced**: `tell()`
only checks `require_same_tree`, never a parent/child relationship — any two agents in the
same tree, siblings or cousins, can `sb tell` each other freely today.
Test: two sibling leaves under the same top `sb tell` each other directly — succeeds;
nothing restricts `tell` to parent-child pairs.

### Unconfirmed assumptions found in code (Scope area) — not in DESIGN-TRUTH at all

- An unknown caller (no store row) is treated as a top for space-minting purposes — same
  item noted under CUJs; relevant here too since it's a scope-adjacent decision.
- `same_tree()` lets a message through when the target name doesn't resolve at all (a typo
  isn't told it hit a boundary) — a real security/scope judgment, unconfirmed by Andrew.
- Cycle-safety defensively built into every tree walk (`_root_of`/`top_of`,
  `status._tree`) implies the schema doesn't actually *guarantee* a DAG at the DB level —
  an unstated structural assumption.

---

## Product decisions — Interface

**Every sb-made view is a split pane with `sb board`.**
Honoured. `_open_board` (`broker.py:948, 980, 3120`) is called from every spawn path; no
`--no-board` flag exists anywhere in `cli.py`.

**`sb board` stays as-is: full tree with nest structure, archived agent collapsed, clicking
a name focuses.**
Honoured. `status.py:1268-1332` collapses sealed archived subtrees; `board.py:287-307`
renders nested depth; click→focus at `board.py:534-543`.

**The click sometimes fails; diagnosed cause is character-count row measurement vs.
terminal-column width, so a wide character (emoji/CJK) wraps a row and shifts every row
below it.**
Diagnosis confirmed accurate; **the bug is still open, not fixed.** `board.py:281-353`
(`layout`, `_visible_len`, `_fit`) all use plain Python `len()`/character-count padding and
truncation — no `wcwidth`/`unicodedata.east_asian_width` anywhere in the repo (confirmed by
grep, zero hits). `_fit`'s own comment states the invariant "no line may ever wrap," but the
enforcement doesn't account for display width, so it can't actually guarantee that for wide
characters. `tests/test_board.py` only covers ASCII overlong strings — no wide-character
test exists.
Test: an agent name/task string containing an emoji or CJK sequence long enough that its
rendered width exceeds terminal columns while its Python `len()` stays within budget — the
row wraps in a real terminal and every click below it resolves to the wrong agent.
Fix size: small-to-medium — swap character counting for a `wcwidth`-based width function in
`layout()`, `_visible_len`, and `_fit` (about 5 call sites in `board.py`), plus a new wide-
character test case.

**`sb start` focuses the pane; nothing else ever focuses on spawn; clicking a name is
navigation and does focus.**
Honoured. `_focus` (`broker.py:1193-1198`) is called only from the two `_top()` paths, never
from `delegate()`. The board's click handler calls a separate `focus()` mechanism
(`board.py:380-392, 542`) independently.

**When something needs Andrew, the board shows it, and `sb block`.**
Honoured, as far as the (self-admittedly vague/deferred) entry goes. `board.py:181-215`
(`wants_you`, `note()`) surfaces `needs_human`/`gone`/`stalled` states with a leading marker
and a `BLOCKED — <reason>` note.

### Unconfirmed assumptions found in code (Interface area) — not in DESIGN-TRUTH at all

- `board.glyph()`'s specific state-precedence ordering (gone > blocked > stalled/drift >
  finished > alive-unknown > working) is a real, opinionated ranking DESIGN-TRUTH never
  states, though loosely consistent with "board shows what needs you."
- The reviewer role/preset split (plain-English verdict lives in the role;
  strict PASS/REVISE token lives in the `adversarial` preset) is a real architectural
  decision with no DESIGN-TRUTH entry — same code area as the stale "no review prompt yet"
  finding above.

---

## Product decisions — Commands

**`sb inspect` should show more tail, "like 100 lines."**
**Not honoured** (the brief's known example, confirmed). `cli.py:303-304` defaults `-n` to
`status_mod.DEFAULT_LINES`, which reads `display.output_lines`
(`status.py:1668`) — set to **40** in `defaults/settings.toml:368`. The same single setting
also feeds `herdr.py:74` (`READ_LINES`) and `output.py:50` — one knob, three readers, all at
40, none near 100.
Test: `sb inspect <agent>` with no `-n` — count lines in the terminal section, will be ≤40.
Fix size: trivial — bump `output_lines` in `defaults/settings.toml` (consider whether
`herdr.py`/`output.py` should keep 40 and only `inspect` moves to ~100, since they currently
share one knob — that's a scope question, not a size question).

**`status._unanswered` and `store.pending_ask` — the "owed"/"waiting on" `sb inspect`
panels.**
**Not honoured / structurally dead** (the brief's second known example, confirmed and
extended). Both query `messages.kind='ask'` (`status.py:1766-1781`, `store.py:1568-1577`).
Every `put_message` call site in the codebase (`broker.py:3276, 3347, 3400, 3904`) passes
only `kind="tell"` or `kind="done"` — nothing writes `"ask"` anymore, because `sb ask` is
gone (see Explicitly rejected, below). These feed directly into `sb inspect`'s rendered
output as the `owed`/`waiting_on` sections (`status.py:1753-1754, 1815-1830`). No code path
can ever populate them going forward; only a store with pre-removal rows could show
anything, and that will empty out over time regardless.
Test: `sb inspect` will never show a non-empty "owed"/"waiting on" section sourced from
current activity, however long the system runs.
Fix size: small cleanup — delete `_unanswered`, `Detail.owed`/`waiting_on`,
`store.pending_ask`, `store.reply_to_ask` (also dead, zero call sites per the rejected-list
audit below), and their rendering — or repurpose the space for `needs_reply` tracking,
which is the actual live "waiting for an answer" mechanism today (`messages.needs_reply`,
`cli.py:917-919`).

**`sb delegate` figures out where a spawn lands rather than the caller passing flags.**
Honoured. The fork rule (`broker.py:2968-3003`) derives placement from `mints_space(me)`
(the `is_top` stamp), not from any caller-supplied flag.

**The orchestrator handles cleanup itself, aggressively; cleaning up an orchestrator always
cleans its children.**
Partly. Self-sweep (`sb cleanup` with no names, from inside a subtree) is genuinely
recursive over all descendants (`broker.py:3540-3558`) and role prompts push agents to "use
it constantly." But **naming an orchestrator explicitly from outside it does not cascade**
to its children — `cleanup(names=[...])` only closes the named row, and is refused outright
if that orchestrator has any live descendant; finished-but-still-open descendant panes are
not auto-closed by naming the parent.
Test: `sb cleanup <orchestrator>` with a still-working child → refused. With only
finished-but-open children → the orchestrator closes, children's panes stay open until
separately swept.
Fix size: doc nuance — DESIGN-TRUTH's sentence reads true only for the self-sweep case, not
named/external cleanup.

**`sb done` keeps the agent open; always when-idle delivery; this is how an idle top learns
a child finished.**
Honoured. `broker.py:3394-3430` never touches herdr's idle/binding state; always rings the
parent via `mode=WHEN_IDLE` (`broker.py:3419-3420`), hardcoded, no flag.

**Cleanup closes agents/tab/space/worktree if everything else is closed; work is usually
pushed first.**
Partly. `sb cleanup` only ever closes agent panes/tabs — never workspaces or worktrees. Space
+ worktree teardown is a **separate command**, `sb workspace close`, which does gate on
"everything else closed" and does delete the worktree/branch (refusing an unmerged branch).
"Pushed before deletion" is **not code-enforced** — the only backstop is git's own
unmerged-branch refusal, which is weaker than "pushed" (an unmerged-but-pushed branch and an
unmerged-and-never-pushed branch are treated identically).
Fix size: doc-only clarification (two commands, not one), or a real feature if a single
"clean up everything, deleting worktrees too" verb is actually wanted.

**`sb status` is not for Andrew — only `sb board` is.**
Partly — **unenforced, unhidden**, unlike `board`. `board` is hidden from `--help` and
hard-refused for a non-agent caller (`cli.py:114, 772-775`). `status` has neither: it's
listed in `sb --help` and runs freely for a human.
Test: `sb --help` lists `status`; `sb status` as Andrew succeeds and prints the tree.
Fix size: small, if this is meant as a hard boundary — hide it and/or refuse the human
caller, matching `board`'s pattern. As shipped, it reads as a stated preference, not a gate.

**`tell` only; no agent ever waits; `--needs-reply` inserts a static prompt, not a wait.**
Honoured. `broker.py:3230-3285` docstring is explicit that `sb ask` is gone for this reason;
`--needs-reply` only appends a fixed line to `sb inbox` output (`cli.py:917-919`) and
doesn't change `tell()`'s fire-and-forget return.

**`sb tell` has three delivery modes: next-turn (default), when-idle, interrupt — with the
documented held/blocked-agent nuance.**
Honoured. `cli.py:153-167` for the flags, `broker.py:4193-4287` (`_ring`) for the mechanics.
A blocked agent's mail is held for every mode except the human's own reply
(`broker.py:4266-4270`), matching "a reply is never buried under it."

**`sb tell` is for agents only, both ways round — Andrew doesn't use it, can't address a
human.**
Partly. The recipient side is enforced (`broker.py:3256-3264` refuses `HUMAN` as a target —
"the human has no mailbox"). The **sender side is not enforced** — `tell()` has no `if me ==
HUMAN: raise` guard, unlike `done()`/`block()` which both explicitly refuse a human caller.
Nothing stops Andrew from running `sb tell` directly today.
Test: `sb tell w1 "..."` typed by a human succeeds; `sb tell human "..."` from any agent
fails.
Fix size: small, if sender-side enforcement is actually wanted rather than "he just doesn't
happen to use it."

**Blocking: full message in the agent's own chat first, then `sb block` with a short `why`
that Andrew never sees.**
Honoured — correctly prompt-level, backed by a code-level length cap
(`validate.reason`) that refuses a report-length `why`. `defaults/protocol.md` and
`defaults/roles/orchestrator.md` both spell out the two-step protocol near-verbatim to the
DESIGN-TRUTH wording, and `cli.py`'s own success message reinforces it.

**After Andrew answers a block, the agent just continues; typing into the pane clears it.**
Honoured. `broker.py:570-617` (`_revive`) flips `blocked`→`working` and logs
`unblocked (answered_in_pane)` the moment any `sb` command runs from a revived pane.

**A parent is not told that its child blocked.**
Honoured. `block()` (`broker.py:3432-3482`) only surfaces to the board, never rings the
parent — contrast directly with `done()`, a few dozen lines away, which explicitly does ring
the parent.

**A lead may only clean up a blocked child if it reads the block as stale — not a hard
rule.**
Consistent with "not a hard rule," but effectively **unwritten guidance** rather than
operative: the `--force` escape hatch exists (skips the live-descendant gate for a *named*
agent), but no prompt text anywhere (`defaults/roles/orchestrator.md`, `defaults/protocol.md`)
currently instructs an orchestrator on judging staleness before force-closing a blocked
child — grepped for "stale" near "blocked," no hits.
Not a contradiction — but "we will see how it plays out" implies this was meant to
eventually get guidance, and it hasn't yet.

**`sb inspect` shows more tail, ~100 lines.** See the known finding above — not honoured.

**`sb restore` is gone if the worktree is gone; the push is the recovery path, not
restore.**
Honoured, closely matching the doc's own wording. `broker.py:3795-3814` explicitly checks
worktree existence and names the branch as the recovery path, citing the exact bug this
closes (herdr silently substituting `$HOME`).

**`sb inbox --peek` stays; once read, never resurfaces.**
Honoured. `cli.py:171-172`, `broker.py:3287-3297` — `mark=not peek` on the read path.

**A workspace forks from `origin/main` by default.**
Honoured. `_inherited_base()` (`broker.py:2873-2902`) falls back to freshly-fetched
`origin/main` exactly when the parent checkout is on `main`/base or detached; otherwise
inherits the parent's own branch — a comment cites this exact DESIGN-TRUTH sentence.

**Merging needs Andrew's explicit approval; default ship shape is branch/push/PR/URL in
summary.**
Honoured — prompt-level, as expected (switchboard has no merge verb at all;
`defaults/roles/orchestrator.md` and `defaults/protocol.md` both state the rule near-
verbatim).

**`sb workspace new` is deleted.**
Honoured. `cli.py:264-291` — `workspace` subparsers are only `list` and `close`; the two
guards `new` used to hold moved into `_fork_for`.

**`sb log` is not for Andrew, but stays.**
Honoured for "stays," but shares `sb status`'s unenforced-hiding caveat: not `hidden=True`,
listed in `--help`, freely callable by a human. As written this reads as convention, not a
gate — same as `status` above.

**`sb presets` needs list/read/apply; apply pastes the prompt in as a message; known to all
sessions.**
Honoured. `cli.py:210-217` for the three modes; `apply_preset()`
(`broker.py:3299-3355`) writes a real `put_message` row and rings via `NEXT_TURN`, citing
the exact DESIGN-TRUTH lines in its docstring.

**`sb models` is fine as is.**
Honoured — no conflicts found in `cli.py:1008-1031`.

**Andrew will never call spawn/lifecycle commands himself, other than `sb start`; his
surfaces are board, his own session, and `sb inspect`.**
**Not (fully) enforced** — overstates what the code actually gates. Only `start` is
human-vs-agent gated in the direction the entry describes (agents refused). `sb delegate` is
explicitly *not* refused for a human (`_refuse_bare_delegate` returns immediately for
`me==HUMAN`). `sb done`/`sb block` **are** refused for a human. `sb tell` (sender side) and
`sb cleanup` are both callable by a human today, and `cleanup` explicitly branches
`if me == HUMAN: scope = every agent` as a first-class supported path — described in a
comment as intentional (a human sweeping the whole fleet), not an oversight.
Test: as a human, `sb delegate` and `sb cleanup` (no name) both succeed; `sb done`/`sb
block` both fail with "is for agents."
Fix size: doc correction (name which verbs are actually enforced vs. merely conventional),
or a real enforcement pass across `delegate`/`tell`/`cleanup` if a hard boundary was
intended.

### Commands/flags with no DESIGN-TRUTH mention at all

A large, real surface undocumented by the design doc — worth Andrew's attention as a batch,
since some of it (like the plugin system) is a first-class subsystem, not an edge case:

- The entire `sb plugin` namespace (`cli.py:225-232, 1005, 1198-1331`) — list/verb dispatch,
  audience gating, `.switchboard/plugins.toml`.
- `sb doctor` (`--reset-store`, `--force`) — the whole degraded-store recovery story.
- `sb workspace list` and `sb workspace close --yes/--resume` — only "`new` is deleted" is
  documented; the surviving verbs and their flags aren't.
- `sb cleanup --dry-run` / `--force` (the named-agent override escape hatch).
- `sb delegate --with` (preset/plugin-fragment binding) and `--model` (per-spawn tier
  override).
- `sb status --active/--live/--needs-me/--mine/--archived` flags.
- `sb inspect --events` (separate from the `-n` tail-lines claim).
- `sb log --agent`, `-n` filtering flags.
- `--json` on every command, universal, mechanically noted in the `cli.py` module docstring
  as MCP-server prep but never mentioned in DESIGN-TRUTH.
- Hidden-but-real verbs: `sb board` (human-only, hidden), `sb flush` (doorbell tick, hidden),
  `sb reconcile` (stall-detection tick, hidden), retired `sb plugins` (hidden, loudly refuses
  and points at `presets`/`plugin`).
- `sb start --name` "return to it instead of starting another" reuse behavior.
- The `_agent_caller` environment-marker double-check inside `sb start`'s refusal.

---

## Explicitly rejected

All seven items checked both statically (argparse subparser/argument enumeration) and
dynamically (live invocations producing the expected argparse errors). **All seven are
genuinely gone** — this section of DESIGN-TRUTH is fully true and needs no re-audit next
time.

- **The human inbox.** Genuinely gone. `sb inbox` as a human returns a fixed refusal
  ("you have no inbox — agents that need you BLOCK...", `cli.py:889-902`), not a mailbox. No
  separate human-inbox table/store exists.
- **`sb ask`.** Genuinely gone as a command — no subparser choice for it; live invocation
  (`python3 -m switchboard.cli ask foo bar`) produces `invalid choice: 'ask'`, exit 2.
  Residue (not a contradiction, but worth a cleanup note): `store.pending_ask`/
  `store.reply_to_ask` remain as dead code (zero call sites), and `kind='ask'` remains a
  legal-but-unwritten value in the CHECK constraint (`store.py:1399`) — this is exactly the
  dead-code pairing flagged under the `sb inspect` panels finding above.
- **`sb wait`.** Genuinely gone — no subparser, confirmed live (`invalid choice: 'wait'`,
  exit 2). `broker.tell()`'s docstring states directly: "no agent ever waits on another
  agent."
- **`sb interrupt` as a verb.** Genuinely gone as a top-level command — only reachable as
  `sb tell --interrupt` (`cli.py:163-166`), confirmed live.
- **`--keep`, `--ephemeral`, `--include-kept`, `--leave-children`.** Genuinely gone — zero
  matches as argparse arguments anywhere; `cleanup`'s real argument list is only `name`,
  `--force`, `--dry-run`. Confirmed live: `sb cleanup --keep` → "unrecognized arguments."
- **`--no-board`.** Genuinely gone — zero matches as a flag anywhere in `cli.py`.
- **Focus as a flag.** Genuinely gone/correctly scoped — no `--focus` argument on any
  subcommand (confirmed live on `tell`); `_focus()` is called unconditionally from exactly
  the two `sb start` paths and nowhere else.

---

## Open / undecided

Structurally consistent with its own framing: the section states "Nothing open" and lists
no actual open questions — only a note that the sole former item (the top/workspace
orchestrator mechanism) was resolved 2026-08-09 and moved into Product decisions. No defect
found; nothing to re-audit here beyond what's already covered under Orchestrators/CUJs
above (the `is_top` stamp mechanism, confirmed honoured there).

---

## Summary of what's fully true and pinned (no re-audit needed)

- The entire **Explicitly rejected** list (7/7).
- Top-stamp mechanics: only `sb start` creates a top, `is_top` drives fork-vs-tab, bare
  agents can't delegate, humans-only `sb start` (`tests/test_structure.py::TopStampTest`,
  `BareAgentCannotDelegateTest`, `OnlyAHumanStartsATopTest`, `WorktreeIsNotTopnessTest`).
- Fork-failure refusal, worktree-outside-refusal, `origin/main` default base.
- `sb done`'s when-idle delivery and its effect on an idle top.
- `sb tell`'s three delivery modes and the blocked-agent-hold nuance.
- Block/unblock lifecycle: block never rings the parent, revive-on-any-command clears it,
  cleanup never lifts the live-descendants gate even under `--force`.
- `sb workspace new` deletion, `sb restore`'s worktree-gone refusal, `sb inbox --peek`.
- `sb presets` list/read/apply semantics.

## What's not honoured — ranked by how surprising/costly it is

1. **The `owed`/`waiting_on` `sb inspect` panels are structurally dead** for all current and
   future activity, not just currently empty — a residue of `sb ask`'s removal that nobody
   finished cleaning up. Small fix, but actively misleading in the meantime (the panels
   render, they just can never show anything real again).
2. **`sb inspect`'s tail is 40 lines, not ~100** — the brief's other known example. Trivial
   fix, but a `display.output_lines` knob shared by three unrelated readers means "just bump
   it" needs a scope decision about whether inspect should get its own setting.
3. **The workspace-orchestrator-review entry is stale**, contradicted by the now-existing
   `adversarial` preset and the collapse of "workspace orchestrator" into a single
   role-agnostic orchestrator. This is the clearest case in the whole audit of DESIGN-TRUTH
   describing a world the code has since moved past.
4. **The board's wide-character row-wrap bug is still open** — diagnosed accurately in
   DESIGN-TRUTH, but nothing in the code fixes it (no `wcwidth` anywhere in the repo).
5. **The "read-only task uses no worktree at all" exception has no code path** — every
   top-spawned child gets a worktree, unconditionally, regardless of task content.
6. Several "Andrew never calls X" / "X is not for Andrew" claims (`sb status`, `sb log`,
   spawn/lifecycle commands generally, `sb tell` sender-side) describe conventions the code
   doesn't actually gate — `board` and `start`/`done`/`block` are the only commands with real
   human/agent enforcement; `status`, `log`, `delegate`, `tell` (sender), and `cleanup` are
   all freely human-callable today.
7. Two "assigns disjoint files" / "peers shouldn't talk" claims are **prompt discipline
   with zero code backing** — not wrong, but worth knowing these are trust-the-agent, not
   trust-the-system, guarantees.
8. The **PR-push/open/summarize cascade** on work completion is entirely prompt-level —
   switchboard has no git/`gh` code of its own. Likely intentional, flagged so it isn't
   mistaken for a mechanical guarantee.

## Questions collected for Andrew (each with a recommended answer)

1. The "(This has not been the case.)" parenthetical in the spawn-landing CUJ now describes
   a fixed, regression-tested bug. Update the entry to drop the parenthetical, or leave it as
   historical color? **Recommended: drop it** — the bug it flags is closed and pinned by
   `WorktreeIsNotTopnessTest`.
2. Is the "100%-clear read-only task uses no worktree" exception still wanted, given no code
   path implements it and the comment trail argues against ever writing into the top's own
   checkout? **Recommended: drop the exception from DESIGN-TRUTH** unless there's a concrete
   read-only use case motivating it — building it is a real, non-trivial feature otherwise.
3. Should "an instruction is ambiguous" be added as a sixth reason to block, matching what
   `defaults/protocol.md`'s own comment says Andrew already confirmed in conversation?
   **Recommended: yes**, this reads as a transcription gap, not a new decision — but only
   Andrew can add it per this file's own rules.
4. Is the workspace-orchestrator-review entry meant to be superseded by the `adversarial`
   preset now that there's only one orchestrator role? **Recommended: yes, mark it
   superseded** — the thing it was waiting for now exists, just shaped differently than the
   entry implied.
5. Is "the parent is told" about a failure satisfied by passive board visibility (current
   behavior), or does it need an active ping? **Recommended: passive is probably fine as
   originally scoped** ("we can start with just telling the parent"), but the wording implies
   more than what's built — worth a one-line clarification.
6. Several "not for Andrew" command claims (`status`, `log`, lifecycle commands generally)
   aren't code-enforced. Should they become hard gates (like `board`), or are they meant as
   soft conventions? **Recommended: leave as soft conventions** — hard-gating `sb status`
   would remove a debugging tool Andrew may reasonably want during development, and nothing
   in the audit suggests he's been confused by their availability.

---

*Every claim above was checked against code actually read at the cited file:line locations
on `main`@`0a0fa4f`, or against a passing test named at the cited location. Where a claim is
inherently a prompt/protocol-level behavior rather than a code mechanism, that's stated
explicitly rather than left implied.*
