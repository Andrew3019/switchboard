# Adversarial review of the Windows-support plan — final report

**Artifact:** `notes/windows-support/native-port-plan.md` (branch `lead-windows-support-plan`).
*(Path corrected 2026-08-22: this reviewed the **native-port** plan, which then lived at `notes/windows-support-plan.md` and is now `notes/windows-support/native-port-plan.md`. The file at `notes/windows-support-plan.md` today is the WSL2 plan, which this did NOT review.)*
**Procedure:** the `adversarial` preset — one standing proposer, a fresh single-lens reviewer each
round, run sequentially. **Round count: hit the 4-round cap.**

## Did it converge?
No clean convergence — **every one of the 4 rounds still found real, verified defects**, so I ran
to the cap rather than to a quiet round. But the trend is the right one: findings went from
"a whole subsystem was missed" (R1) to "point-level design/breakdown gaps" (R4). The plan's
**structure held throughout** — the 7-phase dependency graph and all four settled decisions
(D1–D4) survived every lens; no round found any of D1–D4 *unsafe*. So the cap here means "a deep
port with many surfaces," not "a broken plan."

Plan committed across `d2c4807 → 623f29c` on this branch (one commit per round). All reviewer
findings were **accepted only after the proposer re-verified each against real code / real psutil
on the Mac** — several reviewer claims were measured, and one reviewer fix was corrected because it
would itself have regressed macOS (see R4).

## What each round changed
- **R1 — inventory completeness.** The six source audits never looked in `defaults/`. Found the
  plans plugin's own `import fcntl` + flock (a 6th–8th lock site) that dies silently on Windows,
  taking the merge-gate surface with it — and Phase 1's exit gate was *green over it*. Also: F9 was
  a ~20-site encoding class, not 2 lines; the V6 verdict was **wrong** (CPython discards
  `start_new_session` on Windows → the elected collector isn't detached; Ctrl-C in the electing
  pane kills the fleet's only collector).
- **R2 — zero-regression / psutil blast radius.** §5's blanket "the POSIX side is a verbatim
  extraction" was **false for 5 changes, 2 of which change macOS behaviour today**:
  `stdout.reconfigure(encoding=utf-8)` silently flips POSIX from surrogateescape to strict (re-breaks
  the exact glyph/hook failure it exists to fix); psutil has no `ps pcpu` equivalent so fleet CPU%
  goes 0.0 forever; the close-gate's two-phase read is a **load-bearing liveness re-check**, not
  redundant. Now a per-item regression table + 6 no-regression pins runnable on macOS today.
- **R3 — phase ordering / testability honesty.** Code-phase graph is sound, but 3 exit criteria
  were satisfiable while the feature was dead; **herdr-on-Windows is assumed by Phases 3/3b/6 and
  every V-item but established nowhere**; and adding psutil turns the **existing** ubuntu/macOS CI
  legs red (tests.yml has no install step today).
- **R4 — build model / seam coherence.** Two of four new seams had design holes. The sharpest:
  `procscan` had **no rule for a cwd psutil refuses to read**, and the gap failed toward
  **deletion** — `sb workspace close` could destroy a checkout someone is standing in (every other
  D1 rule fails toward *refusal*). Now scoped so an owned / unreadable-ownership process fails to
  refusal, foreign-user refusals stay out of scope (guarding against a measured 195/490 macOS
  processes that refuse `cwd()`). Also: `lockfile` blocking-mode has no Windows implementation
  (`msvcrt` raises where POSIX waits) → new D6; Phase 1 must decompose **by file, not fix-class**
  (else broker.py/board.py get 3–4 concurrent writers).

## Still open — 5 Phase-0 items, all needing Andrew, none of them coding
Now a decision table at the top of §1 of the plan. Implementation should not start until these
are answered; **H1 first — it can moot the rest**.

| item | question | if guessed wrong |
|---|---|---|
| **H1** | Does herdr run natively on Windows and make a pane? | Phases 1/2/4/5 pass their gates and switchboard still spawns nothing. Largest unproven claim in the doc. |
| **H2** | Does herdr's API report a pane's shell family? | B5 (`_ready_pane`) redesign; wrong dispatch = `SbUnpinned` on spawns. |
| **D5** | How does a plugin reach the new `lockfile` module? | B7 stays blocked; today's one-module contract doesn't allow the import. |
| **D6** | What does `blocking=True` mean on Windows + per-site lock expiry? | **State corruption** — guessing `_minting`'s expiry = two agents minting the same plan id. |
| **D4a** | Symlink-fallback: append to `linked`? how is a copied `CLAUDE.md` classified? | **Data loss** — `mine` deletes a possibly-genuine file, or a mis-classified copy makes every Windows worktree uncloseable. |

**D6's per-site expiry and D4a's file classification are the two that corrupt state / lose data if
guessed instead of decided.**

## Bottom line
The plan is now hardened and honest (its own §5 "what is unproven" is accurate). I'd take it to
implementation — **but only after Andrew answers the 5-item §1 table**, H1 first.

## Detail
Per-round evidence (every `file:line`, command, and measurement):
- `.switchboard/notes/reviewer-inventory-completene-inventory-gaps.md`
- `.switchboard/notes/reviewer-zero-regression-psutil-blast-radius.md`
- `.switchboard/notes/reviewer-phasing-testability-phase-ordering.md`
- `.switchboard/notes/reviewer-port-sequencing-worktree-model-and-seams.md`
- `.switchboard/notes/proposer-windows-plan-round{1,2,3,4}-reply.md`
