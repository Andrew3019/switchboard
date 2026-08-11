# BUILD-PLAN.md — closing the gap between switchboard and DESIGN-TRUTH

Handoff for the top orchestrator running this work. Phases 1 and 2 are built and merged;
what remains is phases 3 to 6. Rewritten 2026-08-11 on `main` (`d31ae87`), folding in
`audit/phase3-scope.md`.

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
- `sb workspace new` is deleted once phase 5 covers space creation. Untouched here beyond
  its two flags.

# Phase 5 — structure

- **5.1** `sb start` is the only path that creates a top orchestrator. Stamp it there.
- **5.2** `sb delegate` branches on that stamp: a top's spawn gets a new space and worktree;
  anyone else's gets a tab in the caller's space. This is the mechanism that makes top and
  workspace orchestrators different — not the prompt, which only explains it. Today they
  share a role name, a byte-identical prompt, and no code branches on it.
- **5.3** A bare agent's `delegate` is refused outright. Nothing enforces this now: any
  agent at any depth can spawn, and could create a space.
- **5.4** Tree boundary: another top's whole tree is invisible. `tell`, `ask`, `status`,
  `inspect`, `log` and `restore` are all global today — only `cleanup` checks scope.
  Siblings inside one tree stay visible to each other.

# Phase 6 — prompts and shipping

Last, because it describes behaviour the earlier phases must first make true.

- **6.1** The block rules and the five reasons an agent may block — three are missing from
  every prompt and one is contradicted.
- **6.2** Human-facing output must be concise, skimmable, bulleted, questions numbered with
  a recommended answer. Taught nowhere today.
- **6.3** Every agent is told at spawn what roles exist, generated from the roles
  themselves, never hardcoded. Nothing lists them today.
- **6.4** `sb presets` gains list / read / apply-to-this-chat; applying pastes the prompt in,
  the same path as any message. Only orchestrators are told presets exist.
- **6.5** Shipping work: branch named for the workspace, push, open the PR, URL in the
  summary. Merging needs Andrew's explicit approval — a prompt rule for now, no merge verb,
  and no agent merges without asking. None of this appears in any prompt.
- **6.6** A lead assigns disjoint files across its shared worktree and serialises overlap.

---

## Ordering rationale

Phase 3 before 4 so nothing is deleted before its replacement exists. Phase 4 before 6 so
prompts are not rewritten twice. Phase 5 before 6 for the same reason — the prompt should
explain a rule the code already enforces. Within phase 3, every deletion waits on the mode
that replaces it.
