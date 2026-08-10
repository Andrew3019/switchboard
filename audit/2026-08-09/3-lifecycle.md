# Audit group 3 — LIFECYCLE AND CLEANUP

Audited tree: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch `worker-2`,
HEAD `a9dd319`). Trusted source: `DESIGN-TRUTH.md` in that tree, and source files only
(`switchboard/*.py`, `bin/sb`, `defaults/*`). All other docs treated as untrusted.

**Two-checkout caveat, resolved.** The `sb` on PATH is
`/Users/andrew/.local/bin/sb` → `/Users/andrew/Code/switchboard/bin/sb`, a *different*
checkout on `main` @ `caa6d20`. All three auditors ran `diff -q` on every file they cited
(`broker.py`, `cli.py`, `store.py`, `status.py`, `board.py`, `collector.py`, `herdr.py`,
`defaults/protocol.md`, `defaults/prompts.toml`, `defaults/settings.toml`,
`defaults/roles/orchestrator.md`) and found them **byte-identical between the two trees**.
So live runtime behaviour observed through main's `sb` is valid evidence for the audited
worktree, and local `main` fixes nothing reported below.

**Verdict counts:** SATISFIED 1 · PARTIAL 5 · BROKEN 2 · UNVERIFIED 0.

| # | Entry (DESIGN-TRUTH line) | Verdict |
|---|---|---|
| 1 | Orchestrator handles cleanup itself, aggressively (196) | PARTIAL |
| 2 | Cleanup closes agents/tab/space, deletes worktree; push first (206) | PARTIAL |
| 3 | `sb restore` is gone if the worktree is gone (248) | **BROKEN** |
| 4 | A parent is not told that its child blocked (239) | SATISFIED |
| 5 | A lead may clean up a blocked child only if the block reads stale (242) | PARTIAL |
| 6 | A reconciler runs on a loop (111) | **BROKEN** |
| 7 | Detect failures, start by telling the parent (102) | PARTIAL |
| 8 | CUJ "When work finishes", end to end (58) | PARTIAL |

Full per-entry evidence lives in the three part reports, which this file summarises without
loss of the citations that matter:
`/tmp/sb-audit-3-part-a.md` (cleanup, teardown, restore),
`/tmp/sb-audit-3-part-b.md` (blocking, finishing chain),
`/tmp/sb-audit-3-part-c.md` (reconciler, failure detection).

---

## The three sharpest gaps

1. **`sb restore` on a deleted worktree reports success and comes back in the wrong
   directory.** Nothing checks the recorded cwd still resolves (`broker.py:3156`), and
   herdr silently substitutes `$HOME` for a missing `--cwd` (measured live:
   `herdr tab create --cwd /nonexistent/...` returned `"cwd":"/Users/andrew"`). Switchboard
   then sets `state='working'` and prints `restored <name>` (`broker.py:3172-3179`,
   `cli.py:894`). The design *accepts* losing restore; the code pretends it worked.

2. **The reconciler does not exist.** The detection predicate is exact and already built —
   `status.py:466` `stalled = running and alive and herdr-idle and not awaiting_task` — but
   nothing ever pings a stalled agent. The only 2-second loop (the collector) is
   deliberately read-only with `reap=False` (`collector.py:13,112`), so the one process that
   ticks is architecturally forbidden from acting, and there is no ping string in
   `defaults/prompts.toml`. Live `sb status`: 13 stalled agents, oldest quiet 15h59.

3. **The finishing chain ends in silence at the top.** A root agent has no parent, so its
   `sb done` writes no mail and surfaces to no human (`broker.py:2832-2838`), and no prompt
   anywhere tells a top orchestrator to `sb block` instead — the single orchestrator role
   text tells every tier to report "to your parent through `sb done`"
   (`defaults/roles/orchestrator.md:195`).

---

## Entry 1 — "The orchestrator handles cleanup itself, and it should do this aggressively" (196)
**PARTIAL.** The instruction is genuinely in the prompt
(`defaults/roles/orchestrator.md:147` "Use it constantly, as part of the job rather than a
tidy-up at the end"; the keep-only-two rule at :150-153), and cleanup scope really is the
caller's subtree (`broker.py:2960`). But "cleaning up an orchestrator always cleans its
children" holds only for the no-names sweep (`broker.py:2969-2971`); naming an orchestrator
closes only that row.

- `sb cleanup <name>` does not cascade to that agent's finished descendants — a named close
  should sweep the subtree beneath it (`broker.py:2969`).
- `--leave-children` (`cli.py:238-241`) closes a parent and deliberately orphans live
  children — reconcile with the entry or rename it to say it orphans them.

## Entry 2 — "Cleanup closes the agents, the tab, the space and deletes the worktree…" + push first (206)
**PARTIAL.** Agents close (`broker.py:3055-3069`), the tab goes when its last pane does
(agent pane + board pane, `broker.py:3064`, `_close_board` at `744-747`), and the space
closes as a herdr side effect (verified live: created a probe workspace, closed its only
pane, it vanished from `herdr workspace list`). Worktree deletion is real
(`broker.py:1829-1878` `git worktree remove`, then `git branch -d` at `1389`) and the
"everything else closed" precondition is stronger than the design states
(`broker.py:1468,1478,1583`, gate run twice at `1329-1334`). What is missing is the trigger
and the push.

- Nothing tears down a workspace/worktree when its last agent closes: `workspace_close` has
  exactly one caller, `cli.py:879` — a human typing `sb workspace close`.
- No prompt or role text tells any agent `sb workspace close` exists, so the aggressive-
  teardown story has no actor.
- Nothing pushes and nothing warns about unpushed commits: no `git push` and no
  unpushed-work check anywhere in `switchboard/`, `defaults/`, `bin/`. The commit-level
  guard `_inventory_gate` (`broker.py:1509-1546`) covers dirty trees only; committed-but-
  unpushed work survives merely because `git branch -d` refuses an unmerged branch
  (`broker.py:1389`, reported at `cli.py:951-953`).
- Agents are told to commit before `sb done` (`defaults/protocol.md:106-107`) but never to
  push.
- `switchboard/herdr.py` has no close-workspace call — teardown relies on undocumented herdr
  behaviour (auto-closing an empty workspace).

## Entry 3 — "`sb restore` is gone if the worktree is gone" (248)
**BROKEN** — not because restore survives, but because it fails dishonestly. See sharpest
gap 1. Restore depends on a `session_id` (`broker.py:3131`) and the recorded cwd
(`broker.py:3156`), and the session transcript is bucketed by cwd
(`store.py:1443-1444`), so a home-directory restore resumes into the wrong bucket with no
context.

- `restore` must check the recorded cwd resolves and refuse with "its worktree is gone — the
  work is in branch X" (`broker.py:3156`).
- Guard `_tab_for` (`broker.py:2340`) against herdr's silent `$HOME` substitution — every
  caller inherits this, not just restore.
- Refuse restore for an agent whose workspace row is retired; `_refuse_retiring`
  (`broker.py:3146`) only covers the in-flight teardown, because `store.retire_workspace`
  clears the mark (`store.py:1079-1083`).
- Qualify the unconditional "`sb restore` brings an agent back" in
  `defaults/protocol.md:115` and `defaults/roles/orchestrator.md:148` — the same orchestrator
  is told to be aggressive about deleting exactly what restore needs.

## Entry 4 — "A parent is not told that its child blocked" (239)
**SATISFIED.** `block()` (`broker.py:2871-2904`) sets state, pushes herdr state for its own
pane, notifies the human desktop (`_surface` → `h.notify`, `broker.py:3464-3468`) and logs —
no `put_message`, no `_ring`, no parent lookup, against `done()` at `2864-2868` which does
both. Docstring at `broker.py:2872`: "never to the parent." The stated justification holds:
the board shows it (`board.py:200-201`, glyph at `166`, `blocked_why` from the event log at
`status.py:474,643-653`).

## Entry 5 — "A lead may only clean up a blocked child if it reads the block as stale" (242)
**PARTIAL.** A blocked child is never swept — `blocked` is absent from
`states.finished = ["done","failed"]` (`defaults/settings.toml:130` → `broker.py:86`,
gate at `3001-3003`). But the refusal is silent and the rule is untaught.

- Naming a blocked child is skipped by a bare `continue`: observed live,
  `sb cleanup --dry-run <name>` → `would close: (nothing)` with no reason
  (`broker.py:3001-3003`, `cli.py:866-870`).
- No `cleanup_held` log line when the state gate skips a named agent — that log covers only
  the live-descendants gate (`broker.py:2995-2998`).
- `--force` closes a blocked child silently: the "say it out loud" branch only fires for
  `state == WORKING` (`broker.py:3019-3027`). Observed live: `closed: audit-sim-block`.
- The stale-only exception appears in no prompt any agent receives — the orchestrator is
  told an unconditional keep rule (`defaults/roles/orchestrator.md:149-151`), and `grep -rn
  stale defaults/ switchboard/roles.py` finds nothing relevant.

## Entry 6 — "A reconciler runs on a loop" (111)
**BROKEN.** See sharpest gap 2. Detection is exact and already built; the acting half does
not exist. Neither loop can act: `board.main()` only calls `refresh(sup)`
(`board.py:352-367,502-541`) and the collector is read-only by design
(`collector.py:13,110-112`). The nearest thing to the ping is a suggestion *printed to a
human* (`status.py:1139-1140`).

- Build the reconciler: select rows where `AgentStatus.stalled` (`status.py:466`) and ping
  each — no new detection work needed.
- Decide where the loop lives: the collector's `readonly`/`reap=False` is load-bearing
  (`collector.py:13`), so this needs a writable process or an explicitly carved write path.
- Add the ping text as a `[notify]` key in `defaults/prompts.toml` (only `mail`,
  `mail_question`, `child_done` and the interrupt exist today, `prompts.toml:61-95`).
- Address the ping to the stalled agent via `_ring`/`put_message` (`broker.py:3401+`), not
  the parent.
- Add re-ping suppression (`last_nudged_at` or an event check) so a stalled agent is not rung
  every 2 s.
- Add a configurable idle threshold (`[timeouts] stall_nudge_after`-style) so a nudge is not
  sent the instant a turn ends.

## Entry 7 — "We should detect failures, and can start with just telling the parent" (102)
**PARTIAL.** Deaths *are* detected and recorded: `status.py:544 _record_gone` flips the row
to `failed` and logs a `gone` event (`status.py:568-577`), from the signal at `status.py:467`
debounced 60 s by `_confirmed_gone` (`status.py:501`, `timeouts.gone_confirm_grace`). Live
`sb status` shows `failed` rows no agent ever reported. The parent is never told.
Retry and half-finished-work are explicitly deferred and are **not** counted as gaps.

- `_record_gone` sends no mail and no ring — add `store.put_message(kind="failed", …)` to the
  dead agent's parent so it lands in `sb inbox`.
- Add a `[notify] child_failed` doorbell beside `child_done` so a parent whose turn ended is
  woken by a death as it is by a completion.
- Make detection run without a human: the write is gated on `reap` (`status.py:489`) and the
  only continuous process passes `reap=False` (`collector.py:112`), so an unwatched fleet
  records no deaths at all.
- Known hole, current status: nothing notices a dead agent's leftover edits. The only dirty-
  tree check is `_ignored_weight` (`broker.py:1087-1115`) at workspace close — human-
  triggered, per-workspace, attributing nothing to an agent. Exactly as the design predicted.

## Entry 8 — CUJ "When work finishes", end to end (58)
**PARTIAL overall.** The plumbing is right; two of six clauses are behaviours no agent is
ever asked for.

| Clause | Verdict | Key evidence |
|---|---|---|
| Worker reports done, parent sees it | SATISFIED | `broker.py:2861-2868` mail + `_ring`; doorbell text `prompts.toml:82` |
| (supporting) `sb done` keeps agent open, "when idle" delivery | PARTIAL | never closes a pane (`broker.py:2856-2869`); but "when idle" is a poll — `_ring` defers on busy (`3426-3428`) and the held doorbell only fires when some other process runs `flush_pending` (`3304-3325`, "stand-in for an events daemon"); no per-message mode column exists |
| All children done → orchestrator reports done or blocks | PARTIAL | cohort waiting is stated (`orchestrator.md:64-66`); the done/block fork is not — only a prohibition at `:193-195` |
| That done, top orchestrator blocks | **BROKEN** | root `done` writes no mail (`broker.py:2832-2838`); no prompt tells the top to block |
| Lead cleans children, pushes PR, summarizes, does not close itself | PARTIAL | cleanup + self-exclusion enforced (`broker.py:2992-2993`) and stated (`orchestrator.md:153`); "pushes the PR" appears in no prompt |
| Bare agent pushes and opens its own PR; top blocks for it | **BROKEN** | no prompt mentions push or PR; a bare agent's fragments are identical to any worker's (`broker.py:2548-2556`) |
| Block resolved → agent finishes, reports done, parent cleans up | SATISFIED | `_unblock_if_needed` (`broker.py:3439-3461`); `done` → `FINISHED` → cleanup (`broker.py:3001-3013`) |

- Orchestrator prompt: state the finishing fork — cohort complete → `sb done` if fully
  complete, `sb block` if the human's input is needed to finish.
- Add a top-only instruction: a root orchestrator must `sb block` to report, because `sb
  done` from a root reaches nobody.
- Add the push/PR duty to the prompt chain, for a lead and for a bare agent under the top.
- `_ring` must not unblock a blocked target for a `done`/mail doorbell: `_unblock_if_needed`
  (`broker.py:3429,3439-3461`) sets a blocked parent back to `working`, contradicting
  DESIGN-TRUTH:~224 "a blocked agent is not idle".
- An idle top with no other `sb` traffic is never woken: held doorbells flush only when some
  other process runs a command (`broker.py:3304-3310`).

---

## Seen in passing (outside this group, one line each)
- `cleanup` marks a force-closed row `done` even when the pane close FAILED
  (`broker.py:3040-3054`).
- `sb delegate` handed a throwaway child its task but the text sat unsubmitted in the Claude
  input box for 5+ minutes — a spawn-delivery problem.
- `sb status --needs-me` lists three agents with mail "never announced to it, oldest 12–16 h"
  — an undelivered-doorbell backlog (`waiting_to_be_rung`).
- `sb board` is a hidden CLI verb (`cli.py:121`) that refuses to run for an agent
  (`cli.py:699`), though DESIGN-TRUTH names it as the loop a reconciler might share.

## Process notes
- Three child auditors (`audit3-cleanup`, `audit3-finish`, `audit3-reconciler`), disjoint
  areas, all closed. One simulation agent `audit-sim-block` was spawned by the blocking
  auditor and removed with `sb cleanup --force`; no panes, worktrees or branches left behind,
  and the repo worktree is clean. Nothing in the repo was modified.
