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
3. **A running collector executes the code it started with**, for as long as any panel
   stays open — so a doorbell fix can be on disk and not in the process ringing it. This is
   item **3.7**, and it caused a four-hour mail delay on 2026-08-11.

## Open question for Andrew — decides how 3.1 is built

`DESIGN-TRUTH.md:96-97` says that while Claude is working, a message is **queued** by
Claude's own system and delivered on the next turn. That is the premise the whole *next
turn* mode rests on. But `Herdr.prompt()`'s docstring (`herdr.py:480-494`) says of the only
ring primitive `sb` has: **"This INTERLEAVES. It does not queue."** — a poke handled at
+13s inside a turn that ran to +63s — and `_ring`'s own comment agrees
(`broker.py:4150-4153`).

If it interleaves, *next turn* as specified is not buildable from this primitive: dropping
the busy-gate yields "land inside whatever tool call is running", i.e. an interrupt without
the cancellation. It is possible DESIGN-TRUTH describes the human-typed path (characters
into the real terminal) rather than `agent prompt`'s API call; nothing distinguishes them
today.

**The live test that settles it** (minutes, in an isolated clone): send text via
`agent prompt` to an agent that is *mid-tool-call*, not between steps, and read whether it
interleaves or waits. Do this before sizing 3.1. Never resolve it by editing
`DESIGN-TRUTH.md`.

---

# Phase 3 — messaging

Scoped in full, read-only, at `audit/phase3-scope.md` (branch `scope-phase3`, `d6b0604`) —
that document carries the file/line evidence for every item below and is worth reading
before starting any of them.

| # | what | state | size |
|---|---|---|---|
| 3.1 | `sb tell` gains three delivery modes: **next turn** (default), **when idle**, **interrupt**. Only *when idle* exists (`broker.tell` → `_ring` defers while `_busy`). *Next turn* cannot be lifted out of `sb interrupt`: that verb bundles a forced ring with an escape keypress and a cancel-your-work wrapper, and no non-cancelling variant exists. **Pass:** a `tell` to a busy agent lands at its next step boundary with the in-flight tool call completing. | gated on the open question above | large, unsized |
| 3.2 | Delete the `sb interrupt` verb once it is a mode — never before. **Pass:** `sb interrupt` no longer parses *and* the capability still works through `tell`. | after 3.1 | tiny |
| 3.3 | Every sb message carries `[sb: from <name>]`. Nothing is marked today; the four `[notify]` strings name no sender, and `sb inbox` uses a different shape (`cli.py:853`). **Pass:** doorbell text, inline interrupt body and inbox output all carry the same tag. | ready; touches the same `_say` call sites as 3.1 | medium |
| 3.4 | Hold when-idle mail until a block is answered. | **done** — landed with phase 1/2 | zero |
| 3.5 | The reconciler: ping any agent that is idle, not blocked, not done, not awaiting task. Detection is exact (`status.AgentStatus.stalled`) and nothing acts on it. **Pass:** an agent whose turn ended without `done` or `block` is pinged within one cycle. | independent of 3.1; land after 3.7 (shared file) | medium-large |
| 3.5a | `--needs-reply` does not exist in any form — no flag, no store column, no prompt text — despite 3.5 being scoped to "also cover" it. Build it as its own small step first rather than discovering its size inside 3.5. | ready | small, from zero |
| 3.6 | Remove `sb ask`. Live and still taught (`protocol.md:124`); `broker.ask` blocks the caller in a poll loop, which DESIGN-TRUTH forbids. **Pass:** it does not parse and no shipped prompt mentions it. | after 3.1 | small |
| 3.7 | **The collector runs stale code.** One collector per repo holds an `flock` for its whole life and never re-checks its own source; only every panel going quiet for 60s ends it. A day-old process keeps ringing the doorbell with pre-fix logic. Caused a ~4h mail delay on 2026-08-11; no filed bug report. **Pass:** after a doorbell fix lands on the running checkout, the next tick behaves per the new code. | ready, own subsystem | small-medium |
| 3.8 | **Nothing enforces that an agent reports before its turn ends** — see below. | ready | see below |

**3.8 — reporting is not enforced.** `sb done` is asked for by the protocol and enforced by
nothing, so an agent can end its turn silently and its work stays invisible until a human
notices. That happened four times on 2026-08-11. `PRINCIPLES.md:118-134` (C6) already names
this as the fix — "a `Stop` hook that blocks completion until a report is emitted beats
'please report when done'" — and says v0 does not honour it; `PLAN.md`'s D2 records the
hook as still unbuilt. `HOOKS.md` carries the corrected mechanics: `claude --settings <file>`
merges the hook into that session only, and **not** `--bare`, which skips hooks entirely.
Nothing in the tree passes `--settings` today (`herdr.start_agent`'s `agent_args`,
`herdr.py:440-460`, is where it would go). This is not 3.5: the reconciler notices a silent
finish afterwards, the hook prevents it. **Pass:** an agent that tries to end its turn
without `sb done` or `sb block` is stopped and told to report.

**Decisions needed:** 3.1's live test (above), and for 3.7, what "the collector's code
changed" should mean — commit hash, file signature, or something scoped per worktree, given
that worktrees of one repo share a git common dir.

**Run order.** 3.7 first, in parallel with getting the two decisions. 3.5a and 3.8 any time
— neither depends on anything else here. Then, one owner for the whole `broker.py`
tell/interrupt/ask cluster: 3.1 + 3.3 together, then 3.2, then 3.6. 3.5 proper after 3.7
and 3.5a.

---

# How phases 4 to 6 start

Each of the phases below is bullets, not a specification. What made phases 1 and 2 land was
a **read-only scoping pass first**, on the phase's own branch: turn every bullet into a
pass/fail test against the code as it reads today, record what is already fixed, what is
unbuilt, what each fix touches, what must be sequenced, and what needs a decision from
Andrew. `audit/phase1-scope.md`, `audit/phase2-scope.md` and `audit/phase3-scope.md` are
the shape. Expect that pass to close some items outright — phase 3's found four already
done — and to grow others.

# Phase 4 — removals

Cheap, mechanical, and it unblocks phase 6: the prompts cannot be rewritten while they
still name flags that are supposed to be gone.

- `--keep`, `--ephemeral`, `--include-kept`, `--leave-children`, `--no-board`, and focus as
  a flag are all still live CLI options.
- `keep`/`ephemeral` are persisted state: a store column, a settings default, a field on
  every role, and all five shipped role prompts tell agents to use them.
- `sb wait` and the human inbox: the inbox is genuinely gone; `sb wait` is not.
- `sb workspace new` is deleted once phase 5 covers space creation.

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
