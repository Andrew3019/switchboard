# BUILD-PLAN.md — closing the gap between switchboard and DESIGN-TRUTH

Handoff for the top orchestrator running this work. Phases 1 and 2 are built and merged.
Phases 3, 4 and 6 are built on their own branches and unmerged; phase 5 was still being
built when phase 6 finished. Rewritten 2026-08-11 on `main` (`d31ae87`), folding in
`audit/phase3-scope.md`; phase 6's section corrected in place on `phase6-prompts`.

**This file is derived and disposable.** It dies when the gaps close. `DESIGN-TRUTH.md` is
the only thing that outlives it — everything below exists to make one of its entries true.
Each claim here was true at the commit named beside it; correct this file in place when
you find it wrong.

---

## What phases 1 and 2 already made true

Do not re-scope, re-audit, or re-fix any of this. All of it is on `main` and pinned by
tests in `tests/test_broker.py` unless noted.

- **A spawn arrives or fails loudly.** A task that never lands is a recorded failure, not a
  reported success (`test_a_task_that_never_arrives_fails_the_spawn_loudly`,
  `test_a_spawn_that_exhausts_its_retries_leaves_a_recorded_failure`). The old ritual of
  eyeballing `sb inspect` for `$0.00` after every fan-out is obsolete.
- **All system prompts are delivered**, in one joined `--append-system-prompt`
  (`tests/test_herdr.py::test_every_prompt_is_delivered_in_ONE_flag`). Every symptom once
  blamed on agents ignoring the protocol was a pre-fix spawn that never received it.
- **A blocked agent stays blocked, and Andrew's answer reaches it.** Sibling mail, a
  child's `done`, and a stale doorbell no longer cancel a block
  (`test_a_siblings_mail_does_not_cancel_a_block`, `test_a_childs_done_does_not_cancel_its_parents_block`,
  `test_a_stale_doorbell_does_not_cancel_a_block`); held mail is released once he answers.
  Answering by typing into the pane clears the block, via `whoami` → `_revive`
  (`test_answering_in_the_pane_clears_the_block_and_releases_its_mail`).
- **A finished agent stays reachable.** A root's `done` is surfaced to the human because
  nothing else would (`test_a_root_agents_done_is_announced_because_nothing_else_will`);
  name binding loss is its own recorded failure rather than a silently unreachable agent.
- **`sb cleanup` explains refusals** instead of reporting `closed: (nothing)`.
- **Children fork from the parent's branch and run their own checkout's build.**
  `broker._pin_sb` puts the spawning checkout's `bin/sb` on the agent's PATH and reads back
  where it resolved, refusing the spawn if it cannot (`audit/sb-path-pin.md`).
- **Concurrent spawns are safe** — a fan-out of six starts six (`tests/test_fork_lock.py`,
  `audit/phase1-acceptance*.md`).
- **The human path works**: block/answer as above, root `done` announced, and the board and
  `sb inspect` are his surfaces.

## Hazards still live

1. **No agent argument may contain a newline** — herdr refuses it outright
   (`herdr.py:431-438`, `validate.py:113-141`). Long briefs go in a file; the task says
   "read this file".
2. **Your own `sb` is not your worktree's.** `sb` on PATH is a symlink into the main
   checkout, so it runs `main`'s code whatever branch you have out. Spawned agents are
   pinned; you are not. Drive a clone's own `./bin/sb` from inside that clone.
---

# Phase 3 — messaging — **built** (branch `phase3-messaging`)

Scoped in full, read-only, at `audit/phase3-scope.md` (branch `scope-phase3`, `d6b0604`) —
that document carries the file/line evidence for every item below and is worth reading
before starting any of them.

Every item below is built and merged onto `phase3-messaging`. The evidence for each is in
`audit/`, named beside it.

| # | what it now does | state |
|---|---|---|
| 3.1 | `sb tell` has three delivery modes — **next turn** (the default), **when idle** (`--when-idle`), **interrupt** (`--interrupt`). A `tell` to a busy agent now rings anyway and lands at its next tool-call boundary; the in-flight tool call finishes. Under the old when-idle default the same message waited for the whole turn — five and a half minutes when it was last timed. | **done** (`audit/phase3-tell-modes.md`) |
| 3.2 | The `sb interrupt` verb is gone; it is `sb tell --interrupt`, with the same escape keypress and cancel wrapper. | **done** |
| 3.3 | Every message carries `[sb: from <name>]` — doorbell text, inline interrupt body and `sb inbox` output all use the same tag. | **done** |
| 3.4 | Hold when-idle mail until a block is answered. | **done** — landed with phase 1/2 |
| 3.5 | The reconciler (`Broker.reconcile`, hidden verb `sb reconcile`) pings any agent whose turn ended without a report. Three exemptions: awaiting-task, blocked/finished (never `stalled`), and a parent with live children. One ping per stall, not per cycle. | **done** (`audit/phase3.5-scope.md`) |
| 3.5a | `sb tell --needs-reply` records that the sender is waiting; the recipient's `sb inbox` names the sender and says to answer at some point without stopping what it is doing. The sender never waits. | **done** (`audit/phase3.5a-scope.md`) |
| 3.6 | `sb ask` is gone — verb, `broker.ask`'s poll loop, and every mention in the shipped prompts. `--needs-reply` is what replaced it. | **done** |
| 3.7 | The collector notices its own source has changed on disk and exits, so the next tick runs the code that is on the checkout rather than the code it started with. Detection latency is up to ~45s by design. | **done** (`audit/phase3.7-scope.md`) |
| 3.8 | A `Stop` hook (`bin/sb-stop-hook`, `switchboard/hooks.py`) refuses a turn that ends without `sb done` or `sb block`, installed via `--settings` on every spawn and restore. Exempt: an agent awaiting its task, and a parent with live children. | **done** (`audit/phase3.8-scope.md`, `HOOKS.md`) |

**3.1's open question was settled by experiment, not by argument.** `agent prompt` **queues
at the tool-call boundary; it does not interleave** — three 90-second single tool calls,
none cut short, the text delivered at the boundary after each
(`audit/phase3-delivery-primitive.md`). That is what makes *next turn* buildable from this
primitive, and it is why the default could change safely.

**What is not proved** carries into phase 4 and is worth reading before touching this code:
multi-message ordering while an agent is busy; next-turn against very short or nested tool
calls; interrupt against an already-idle agent; the stop hook's awaiting-task and
live-children exemptions and its pane-id fallback (pinned by store logic, never a live run);
the collector's staleness check as a real held doorbell under the new rule (it was proved as
restart-with-new-code), and an edit racing an in-flight flush. `sb doctor` does not display
the reconciler's counters — a one-line display gap, reported and deliberately left.

---

# How phases 4 to 6 start

Each of the phases below is bullets, not a specification. What made phases 1 and 2 land was
a **read-only scoping pass first**, on the phase's own branch: turn every bullet into a
pass/fail test against the code as it reads today, record what is already fixed, what is
unbuilt, what each fix touches, what must be sequenced, and what needs a decision from
Andrew. `audit/phase1-scope.md`, `audit/phase2-scope.md` and `audit/phase3-scope.md` are
the shape. Expect that pass to close some items outright — phase 3's found four already
done — and to grow others.

# Phase 4 — removals — DONE (branch `phase4-removals`, stacked on phase 3)

Cheap, mechanical, and it unblocks phase 6: the prompts cannot be rewritten while they
still name flags that are supposed to be gone. Scoped in `audit/phase4-scope.md`, built
and proved in `audit/phase4-build.md`.

- **Done.** `--keep`, `--ephemeral`, `--include-kept` (and its `--all-idle` alias),
  `--leave-children`, `--no-board` (on both `sb start` and `sb workspace new`) and focus as
  a flag (`sb start --no-focus`, `sb workspace new --focus`) no longer parse. `sb start`
  always focuses; nothing else focuses; every sb-made view is split with the board.
- **Done, as write-paths rather than a collapse.** Nothing writes `agents.cleanup` any
  more — not the CLI, not `_top`, not `_spawn_lead`, not `_adopt`, and `Role.cleanup` and
  its `default_cleanup` setting are gone. The COLUMN and its read-side gate stay: live
  rows already carried `'keep'`, written automatically rather than by opt-in, and
  collapsing the column would have swept them. Such a row still behaves exactly as it did
  — held back by a sweep, closed when named. All five shipped role prompts stopped naming
  the flags; nothing else in them changed, because phase 6 owns the rewrite.
- **Done.** `sb wait` is gone, with `status.wait_for` and its three settings keys. The
  human inbox was already gone and was left alone.
- **Done, after phase 5** (branch `phase4-workspace-new`, stacked on phase 5). `sb
  workspace new` is deleted — the verb, `Broker.workspace_new`, and the `_spawn_lead` /
  `_adopt` / `_result` machinery under it, with `vocabulary.workspace_role`,
  `vocabulary.lead_suffix` and the `spawn.workspace_task` prompt. Its two remaining halves
  are covered: a top's `sb delegate` mints the space (the child's `--name` is the
  workspace, the branch and the checkout), and `sb delegate --workspace <name>` joins one
  that exists. `sb workspace list` and `sb workspace close` are untouched. Two guards the
  verb held moved to `_fork_for`, because nothing else was holding them: a workspace
  mid-teardown is refused, and so is a name a bare space already owns. Written up in
  `audit/full-stack-verification.md`.
  - **Not covered, deliberately:** the no-name form (`sb workspace new` with no argument,
    which laid a workspace over the checkout you were standing in) and `--base`. The first
    is a second minting path, which is the thing phase 5 exists to end; the second is
    answered by the fork rule — a fork starts from the parent's branch, or `origin/main`
    when that branch is main.

# Phase 5 — structure — DONE (branch `phase5-structure`, stacked on phase 4)

Scoped in `audit/phase5-scope.md`, diagnosed live in `audit/phase5-spawn-placement.md`,
built and proved in `audit/phase5-build.md`.

5.1 and 5.2 turned out to be one fix rather than two. The fork rule keyed on worktree
POSSESSION (`has_worktree(me)`), which coincides with top-ness for every agent that
happens to exist and is not the same fact — a non-root, worktree-less row delegated in an
isolated clone and its child forked a whole new space, exactly as a top's would. Adding
the column alone would have changed nothing, since nothing read it.

- **Done.** `agents.is_top`, written by `_top` and by no other path. Rows that predate the
  column are backfilled once from `parent IS NULL AND branch IS NULL` — provably the shape
  only `sb start` has ever produced, checked against all 252 live rows (7 roots match, no
  non-root does). An unstamped row is not treated as ordinary: that would silently demote
  every real top.
- **Done.** The fork rule reads the stamp (`Broker.mints_space`), not `has_worktree`. A
  top's spawn gets a new space and worktree; anyone else's is a tab in the caller's space,
  and its whole subtree stays there. The human and a caller with no row still fork — they
  have no space to lend, and the alternative is spawning into somebody's own checkout.
- **Done.** `delegate` is refused unless the caller's role carries `delegate = true` — a
  FIELD on the role, set only by `orchestrator.md`, never a check against the literal role
  name, which breaks the moment a role is renamed or added. Enforced in the broker, so
  `sb workspace new` goes through it too. Live audit at ship time: 8 non-orchestrator-role
  agents had spawned children historically, all ended, none with a live child — the
  refusal cut nothing off mid-task.
- **Done.** Tree boundary on the five verbs that were global: `tell`, `status`, `inspect`,
  `log`, `restore`. Five, not the six above — `sb ask` was deleted in phase 3. Scoped to
  the caller's TOP's whole tree, so siblings stay visible to each other; `cleanup` keeps
  its own tighter descendants rule. The board is NOT scoped, and neither is the human.
- The role PROMPTS still do not mention any of this. Deliberate: phase 6 owns the prompt
  rewrite, and the refusal message says what to do instead in the meantime.
- `sb workspace new` was still here when phase 5 shipped. It is gone now: see phase 4's
  last item, built on `phase4-workspace-new` on top of this branch.

# Phase 6 — prompts and shipping — **DONE** (branch `phase6-prompts`)

Scoped in `audit/phase6-scope.md` (branch `scope-phase6`), built and proved in
`audit/phase6-build.md`. Based on `phase5-structure` at `7847b84`, which was still
byte-identical to `phase4-removals` when this started — so in practice phase 6 stacks on
phase 4 and phase 5 lands beside it, not under it. That turned out to be safe: the scoping
pass found no item here depends on phase 5, and none of the six touched a line phase 5 is
scoped to change. The ordering note below was about avoiding a second pass over the same
files, not a real dependency.

- **6.1 Done.** `defaults/protocol.md`'s escalation sentence now names all five of
  DESIGN-TRUTH's sanctioned reasons — three of which reached no shipped prompt at all —
  and keeps "a tool fails twice" as the concrete form of being blocked on a command.
  **Nothing was contradicted after all.** The scoping pass read "an instruction is
  ambiguous" as a contradiction and proposed narrowing it; Andrew overruled that and kept
  it. The prompts therefore teach SIX reasons where `DESIGN-TRUTH.md:142-145` lists five.
  That is deliberate and only he can close it, by adding the sixth to that file.
- **6.2 Done.** The formatting half — concise, skimmable, bullets, lists, sections — is
  stated once in the protocol, beside the numbered-questions half that was already there.
  Not repeated per role: five copies drift.
- **6.3 Done.** `[spawn] roles` in `prompts.toml`, filled by `Broker.delegate` from the
  merged role table. Proved by adding a role to a clone as a file and finding it in a real
  agent's system prompt with nothing else edited. Names only — no `Role` schema change.
- **6.4 Done.** `sb presets <name> --apply` pastes the preset into the caller's own session
  as a message (a store row, the `[sb: from …]` tag, `_ring` at next-turn), not as printed
  output. No confirmation step. All sessions are told the verb exists, not just
  orchestrators. The self-addressed message the scoping pass flagged as unexercised was
  checked: schema-legal, and marked collected so it does not come back through the sender's
  own inbox. One residual noted in the build doc — `put_message` clears `awaiting_task`.
- **6.5 Done, to every role rather than to orchestrators**, per Andrew, and so it lives in
  the protocol — the only text all five roles share. Note it is the DEFAULT shape: this
  repo's own `house-rules` preset overrides it with "commit, never push, never PR, the
  orchestrator integrates", and a later preset beating the protocol is the layering working.
- **6.6 Done.** `orchestrator.md` assigns disjoint files at split time, with the shared
  worktree stated as the reason. Serialising overlap stays as what handles the rest.

---

## What is left

Phase 6 was the last phase in this plan, so this file has nearly done its job. What it
does **not** get to claim is that `DESIGN-TRUTH.md` is now entirely true of the code:

- **Phase 5 was still in flight** when this was written. Until it lands and merges, 5.1–5.4
  are open: nothing stamps a top orchestrator, `delegate` does not branch on it, a bare
  agent can still spawn, and every tree can see every other.
- **The block reasons now outnumber the doc's**, as above — the code and prompts are ahead
  of `DESIGN-TRUTH.md` by one reason, which is a gap in the doc rather than in the build.
- **`sb workspace new` is still there.** Phase 4 left it deliberately, for phase 5 to
  remove once space creation is covered.
- **No phase verified obedience, only presence.** Every prompt rule in phase 6 is pinned by
  a containment check. Whether agents actually block for the right reasons, format for a
  human, or assign files up front is a judgement from watching real runs, and nothing here
  substitutes for it.
- **This file has never been a full audit of `DESIGN-TRUTH.md`.** It closes the gaps the
  phase-1 scoping found. Anything that document says which was never scoped into a phase is
  neither built nor known to be broken — it was simply never looked at, and a fresh
  read-through against the code is the honest next step before declaring the gap closed.

## Ordering rationale

Phase 3 before 4 so nothing is deleted before its replacement exists. Phase 4 before 6 so
prompts are not rewritten twice. Phase 5 before 6 for the same reason — the prompt should
explain a rule the code already enforces. Within phase 3, every deletion waits on the mode
that replaces it. In the event phase 6 ran alongside phase 5 rather than after it, and no
item collided; the rationale held for phases 3 and 4 and was slack for 5.
