# Adversarial review of the cascade-close fix — lead-1 synthesis

**Verdict: converged CLEAN at the 4-round cap. The fix is sound to land, with one open item (below). Plan step s-57 ticked.**

## What the artifact is now

Five commits on `fix-orphaned-dispatcher-children`, on top of the original `8494b3f`:

- `30c1e62`, `5e060f3`, `227c3c3`, `bae8691`, `65d9c00`

Behaviour: `sb workspace close <bare orchestrator>` now also closes the worktree spaces
its children forked — but only spaces **this** subtree minted, only when **empty**, retiring
the bare row **last** so a crash mid-cascade is retryable, and **reporting** every space it
deleted or kept.

Full test suite: **1531 passed, exit 0** (re-run by lead-1, not taken on the proposer's word).

## The four rounds — one blind reviewer per lens, one proposer defending throughout

| Round | Lens | Outcome |
|---|---|---|
| R1 | `_forked_under` selection | **Defect**: deleted spaces another *live* orchestrator's child forked (reached via `delegate --workspace` join). Fixed — narrowed to namesake rows. |
| R2 | recursion / deletion-safety | **2 defects**: crash mid-cascade orphaned the rest *permanently* (retire ran first); and it deleted a done parent's space while a grandchild still worked. Both fixed. |
| R3 | reporting / CLI | **3 defects**: contradictory "nothing was deleted" headline; under-counted pane total; a space silently dropped from the report when the human stood inside it. All fixed. |
| R4 | blast-radius on shared cleanup/sweep | **CLEAN** — proved `sb cleanup` and the half-hourly sweep do not regress (identical output main-vs-HEAD). 3 latent nits, all addressed. |

- **6 real defects** found and fixed.
- **4 objections rejected** with reasons: sweep-policy delta (cleanup's gate, not sweep's);
  nested-bare-space skip (correct by design); a pre-existing 2-names-1-directory case
  (out of scope); one cosmetic shared gate sentence.

## Open item — decide before merge (s-58 / s-59)

**None of the 5 review-driven fixes has a real-herdr run.** Every repro is the unit harness
(real git, real gates, **fake herdr**). qa-15's live-clone proof (`6f5c14d`) predates all
five fixes, so **s-56's isolated-clone verification is now stale** relative to the code that
will land. The R1 and R2 fixes changed real deletion targets and retire-ordering — exactly
what a live clone would exercise.

**Recommendation:** re-run s-56 (live-clone proof) against HEAD before opening the PR. Cheap,
and it closes the one thing this review could not: proof against a real herdr.

## Where the detail lives

- Per-round reviewer findings: `notes/reviewer-28-forked-under.md`, `reviewer-29-cascade-recursion.md`,
  `reviewer-30-cascade-reporting.md`, `reviewer-31-scope-discipline.md`.
- The proposer's per-round concede/rebut reasoning is captured in those commits' messages and
  its (now closed) session; the substance is in the reviewer notes and commit messages.
