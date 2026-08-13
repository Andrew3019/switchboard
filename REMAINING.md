# REMAINING.md — what is still untrue of `DESIGN-TRUTH.md`

Every phase of the old `BUILD-PLAN.md` is built and merged, so that file has been deleted
and this one replaces it. Where the plan worked from the phase-1 scoping pass and guessed
at the rest, this works from a full conformance audit: `audit/design-truth-conformance.md`
(branch `design-truth-audit`, `af01c42`), which checked every `DESIGN-TRUTH.md` entry
against `main` @ `0a0fa4f` — 1148 tests passing. It found all seven explicitly-rejected
items genuinely gone, most journeys and decisions honoured and pinned by tests, and about
ten places where the code and the design record still disagree. Four of those ten have
since been closed by merges that landed after the audit was taken — two by `small-fixes`
(PR #20), the board's wide-character bug by `board-widechar` (PR #22) and the failure ping
by `failure-pings` (PR #24). They are recorded as finished below rather than listed as
gaps. **That leaves six, and none of them is code:** every one is a decision only Andrew
can make.

**This file is derived and disposable.** It dies when the gaps close. `DESIGN-TRUTH.md` is
the only thing that outlives it. Every claim here was true of `main` @ `0a0fa4f`; it was
re-checked against `main` @ `71bec8a` (1157 tests passing) on 2026-08-12 and revised where
a merge had closed something. Correct this file in place when you find it wrong, and say
which commit you checked against.

The audit is the source for everything below. Nothing here was re-derived from the code
except where it says so.

---

## What is finished — do not re-audit

Taken from the audit's own "fully true and pinned" list, compressed:

- **The entire "Explicitly rejected" section, 7 of 7.** The human inbox, `sb ask`,
  `sb wait`, `sb interrupt` as a verb, `--keep`/`--ephemeral`/`--include-kept`/
  `--leave-children`, `--no-board`, and focus-as-a-flag are all genuinely gone — checked
  statically and by live invocation. (The audit found one piece of `sb ask` residue still
  standing; `small-fixes` has since removed it — see below.)
- **Top-stamp mechanics.** Only `sb start` creates a top, only a human may run it, the
  `is_top` column (not the prompt, not worktree possession) drives fork-vs-tab, and a bare
  agent's `delegate` is refused on a field of its role rather than its name. Pinned by
  `TopStampTest`, `OnlyAHumanStartsATopTest`, `WorktreeIsNotTopnessTest`,
  `BareAgentCannotDelegateTest`.
- **Spawn placement.** A lead's children share its worktree; exactly one worktree per
  space across a whole tree. The phase-5 bug DESIGN-TRUTH's parenthetical describes is
  fixed and regression-tested.
- **Fork failure refuses rather than degrading**, `sb start` inside a worktree is refused
  and names the main checkout, and a workspace forks from `origin/main` by default.
- **`sb done`** keeps the agent open, always delivers when-idle, and is how an idle top
  learns a child finished — and an idle top is not treated as stalled.
- **`sb tell`'s three delivery modes** and the blocked-agent hold, including that the
  human's own reply is never buried.
- **Block lifecycle.** Block never rings the parent, any `sb` command from the pane clears
  it, and cleanup never lifts the live-descendants gate even under `--force`.
- **`sb workspace new` deletion**, `sb restore`'s worktree-gone refusal, `sb inbox --peek`,
  `sb presets` list/read/apply.

Five more items are closed, and these are the only claims here checked against the code
rather than taken from the audit:

- **The reconciler no longer nudges a seconds-old agent before its task arrives** — the one
  item the old plan left open. `status.py:770` adds a `starting` guard whose comment names
  that exact symptom, and `stalled` now depends on it.
- **`sb inspect`'s "owed" and "waiting on" panels are gone**, along with
  `status._unanswered` and `store.pending_ask`/`reply_to_ask`. They were structurally dead:
  they selected `messages.kind='ask'`, and nothing has written that kind since `sb ask` was
  deleted, so they could only ever match rows older than the removal — and the action they
  printed was false of every one of those rows. Closed by `small-fixes` (PR #20); the audit
  had it as a code gap.
- **`sb inspect` shows about 100 lines of tail, not 40.** `defaults/settings.toml` moves
  `display.output_lines` from 40 to 100, which is what the record asks for. All three
  readers of that knob move together — `status.py` (`inspect`), `herdr.READ_LINES` and
  `output.py` — deliberately, so the tail that exists to be read and the tail that is read
  are one number rather than two that can disagree. Closed by `small-fixes` (PR #20); the
  audit had it as a code gap, and this also settles what was its open question 7.
- **The board measures rows in terminal columns, not characters.** This was the audit's
  last open code gap: one emoji or CJK sequence wrapped a row and shifted every click
  below it. `board.py`'s `_visible_len`/`_pad`/`_fit`/`_clip` now measure and truncate in
  columns, on glyph boundaries, from `unicodedata.east_asian_width` — no new dependency.
  Closed by `board-widechar` (PR #22), pinned by
  `LayoutTest.test_a_wide_character_row_does_not_wrap_and_the_rows_below_it_still_map`
  and two neighbouring cases.
- **A recorded failure actively pings the parent.** `status._record_gone` writes a
  `kind='failed'` message to the dead agent's parent alongside `state='failed'`, and the
  ordinary doorbell carries it — held while the parent is mid-turn, held while it is
  blocked, and once per death, because the write is conditional on the row still being
  `working`. Closed by `failure-pings` (PR #24), pinned in `tests/test_status.py` and
  `tests/test_broker.py`. The audit had this as a decision, its question 5 ("passive board
  visibility, or an active ping?"); the code has since answered *active*, so it is no
  longer Andrew's to decide.

---

## Gaps that are code work

**None.** The audit found three. Two were `sb inspect` and were closed by `small-fixes`
(PR #20); the last was the board's wide-character measurement, closed by `board-widechar`
(PR #22). Everything below this line is a decision, not a build.

---

## Gaps that are a decision, not a build

These are places where the code and `DESIGN-TRUTH.md` disagree and **no code needs to be
written unless Andrew says so**. Each one is either a doc correction only he can make, or
a feature that does not exist and may never have been wanted. They are listed here so
nobody mistakes them for a build queue.

- **The "100%-clear read-only task uses no worktree" exception has no code path.** Every
  top-spawned child gets a worktree, unconditionally, whatever its task says
  (`broker.py:2996`), and `--workspace` explicitly refuses to join the top's bare space
  (`broker.py:1203-1236`). Building it is a real feature (`delegate`, `join_workspace`,
  `_fork_for`, argparse, tests); dropping the exception is a one-line doc edit. Question 2.
- **"Not for Andrew" is a convention, not a gate.** Only four verbs are enforced at all,
  and they point in both directions: `board` (hidden, and refused for an *agent*),
  `sb start` (refused for an agent, and for a human typing from inside a Claude Code
  session, since nothing there tells them apart), and `done`/`block` (refused for a
  human). `status`, `log`, `delegate`,
  `tell` (sender side) and `cleanup` are all freely human-callable today — and `cleanup`
  branches deliberately on `me == HUMAN` to sweep the whole fleet. Either the doc names
  which verbs are really gated, or there is an enforcement pass. Question 6.
- **The workspace-orchestrator-review entry is stale.** It says there is no prompt for
  review coordination yet; `defaults/presets/adversarial.md` is exactly that, reachable
  via `sb presets adversarial` and cited from the orchestrator role. There is also no
  longer a distinct "workspace orchestrator" role — one role, used at every level.
  Question 4.
- **The spawn-landing parenthetical describes a fixed bug.** "(This has not been the
  case.)" now documents history, not a live defect. Question 1.
- **The prompts teach a sixth reason to block** ("if an instruction is ambiguous") that
  DESIGN-TRUTH's list does not carry. `defaults/protocol.md`'s own comment says Andrew
  confirmed it in conversation, and that the doc is the thing short by one. Question 3.
- **Two doc nuances, no code implicated.** Cleanup "always cleans its children" is true of
  the self-sweep (`broker.py:3540-3558`) but not of naming an orchestrator from outside
  it. And cleanup does not close spaces or worktrees at all — `sb workspace close` does,
  as a separate verb, and its backstop is git's unmerged-branch refusal, which is weaker
  than "pushed first".

## Rules that are prompt discipline, with no code behind them

Not gaps, and nothing here needs building — but they are trust-the-agent guarantees, not
trust-the-system ones, and reading DESIGN-TRUTH without this note implies otherwise:

- **A lead assigns disjoint files and serialises overlap.** Instructed at
  `defaults/roles/orchestrator.md:141-146`. Nothing detects or blocks two children writing
  the same file.
- **Peers can talk but shouldn't.** `tell()` checks only `require_same_tree`; any two
  agents in one tree may message each other freely.
- **The push/PR/summarize cascade on finishing.** Switchboard has no git or `gh` logic of
  its own; this is prompt text (`defaults/protocol.md:169-173`). Almost certainly
  deliberate — state lives in the store, git actions belong to agents.
- **`<name>-lead` naming.** `_unique_name` produces `<role>-<n>`; nothing enforces the
  suffix. DESIGN-TRUTH's "can be called" reads as permissive, so this is probably not a
  gap at all.
- **Judging a blocked child's block as stale before force-closing it.** `--force` exists;
  no prompt anywhere tells an orchestrator how to judge staleness. DESIGN-TRUTH's "we will
  see how it plays out" implies guidance was meant to follow, and it has not.

---

## Questions for Andrew

Five, all from the audit, each with the audit's recommended answer. Two of the audit's
seven have since been answered by code rather than by Andrew, and are not repeated here:
whether `display.output_lines` should move for all three of its readers (`small-fixes`
moved the shared knob), and whether a failure needs an active ping (`failure-pings` built
one). The numbering below is the audit's, with 5 struck out, so a reference to "question
6" still finds the same question.

1. **The "(This has not been the case.)" parenthetical in the spawn-landing entry now
   describes a fixed, regression-tested bug. Drop it, or keep it as historical colour?**
   *Recommended: drop it* — closed and pinned by `WorktreeIsNotTopnessTest`.
2. **Is the "100%-clear read-only task uses no worktree" exception still wanted?** No code
   implements it, and the comment trail argues against ever writing into the top's own
   checkout. *Recommended: drop the exception from DESIGN-TRUTH* unless a concrete
   read-only case is pushing for it — otherwise this is a real feature built for nobody.
3. **Should "an instruction is ambiguous" be added as a sixth reason to block?**
   *Recommended: yes* — `defaults/protocol.md`'s comment says you already confirmed it, so
   this is a transcription gap rather than a new decision. Only you can add it.
4. **Is the workspace-orchestrator-review entry superseded by the `adversarial` preset,
   now that there is only one orchestrator role?** *Recommended: yes, mark it superseded*
   — the thing it was waiting for exists, shaped differently than the entry implied.
5. ~~**Is "the parent is told" about a failure satisfied by passive board visibility, or
   does it need an active ping?**~~ **Answered by code**, in the direction the audit did
   not recommend: `failure-pings` (PR #24) built the active ping. Nothing to decide.
6. **Should the "not for Andrew" claims (`status`, `log`, lifecycle verbs, `tell`'s sender
   side) become hard gates like `board`, or stay soft conventions?** *Recommended: soft
   conventions* — hard-gating `sb status` would remove a debugging tool you may want, and
   nothing suggests their availability has confused anyone. Then the doc should say so.

---

## Two things the audit surfaced that are neither gap nor question

Recorded so they are not lost, not proposed as work:

- **A batch of real command surface has no DESIGN-TRUTH entry at all** — the whole
  `sb plugin` namespace, `sb doctor`, `sb workspace list`/`close` and their flags,
  `cleanup --dry-run/--force`, `delegate --with/--model`, `status`'s filter flags,
  `inspect --events`, `log`'s flags, universal `--json`, the hidden verbs (`board`,
  `flush`, `reconcile`), and `sb start --name`'s reuse behaviour. Some of it, the plugin
  system in particular, is a first-class subsystem rather than an edge case.
- **A set of load-bearing assumptions live only in code comments** — the stop-hook gate
  that enforces every turn ending in `done` or `block`, multi-provider scaffolding with
  one provider wired, the collector's self-restart on source change, `_fork_lock`
  serialising concurrent worktree creation, the dead-spawn name-reuse carve-out, an
  unknown caller being treated as a top, and `same_tree()` letting an unresolvable name
  through. The audit lists each with file and line.
