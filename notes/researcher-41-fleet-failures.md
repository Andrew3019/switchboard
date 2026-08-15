# SCOUT — fleet-level failures above any single lead

Read-only investigation. Sources: `notes/`, `learnings/` (untrusted — report what they
claim, not fact), `git log` on `main` (~120 commits scanned), `DESIGN-TRUTH.md` (trusted).

## 1. Two parallel note directories exist right now, one of them un-indexed — worst finding

`notes/` and `learnings/` both exist in this checkout today. `notes/README.md` (the
directory's own index, itself subordinate to `DESIGN-TRUTH.md`) says nothing about
`learnings/` at all — it is invisible to the one map that exists. Confirmed by directory
listing: `learnings/` has 34 files, `notes/` has 18, and 11 filenames are shared between
them.

Two of the shared files are byte-identical, independently produced: `board-mockup-nogaps.md`
(1311 lines in both) and, by inspection of the merge diffs, `board-mockup.md`. These came
from two sibling branches — `worker-36` (put its 34 session notes under `learnings/`,
merged as PR #42, commit `8ca3d12`) and `worker-35` (put a near-identical set under
`notes/`, merged as PR #43, commit `0f89e9c`) — merged 83 seconds apart by Andrew. Neither
branch could see the other's directory choice; nothing reconciled them after either merge
landed.

24 files exist **only** in `learnings/` and are cited nowhere in `notes/README.md`:
`researcher-37-why-so-many-worktrees.md`, `worktree-per-level.md`, `role-vocabulary.md`,
`top-orchestrator-role.md`, `scout-naming-report.md`, `verify-bracket.md`, several
`reviewer-*` and `board-*` files, etc. `DESIGN-TRUTH.md` itself never mentions
`learnings/` — grepped, zero hits. These are findings that were written, merged to main,
and then structurally lost: nothing points at them and the trusted index doesn't know they
exist.

A single lead could not have caught this: `worker-35` and `worker-36` were sibling
branches spawned independently, each correctly following what it believed the convention
was, and the collision was only visible once both were merged onto `main` by whoever holds
merge authority — a step no lead performs for another lead's branch.

## 2. DESIGN-TRUTH citation re-aiming, twice, from independent merges

`DESIGN-TRUTH.md` is cited by line-range from six files (`broker.py`, `cli.py`,
`validate.py`, several `tests/test_*.py`, `defaults/roles/lead.md`). Two separate commits
exist purely to repair those citations after an unrelated merge silently shifted every
line number below its insertion point:

- `dd34dbb` (2026-08-14): inserting the "worktree-per-level" answer shifted everything
  below it by 17 lines.
- `7dc0fea` (2026-08-14, later same day): a second merge inserted the "Human-facing
  output" section 56 lines earlier than where citations expected it, because an entry
  above it had *also* shrunk by 7 lines in the same merge. The commit message for
  `7dc0fea` is explicit that the regression test, `tests/test_design_truth_refs.py`, "only
  checks that a range starts and ends on entry boundaries, and a 56-line shift lands on
  plenty of those" — i.e. the test is known to be unable to catch this class of bug in
  general, only some instances of it. 18 of 24 citation sites needed correction that time;
  6 escaped only because they happened to sit above the insertion point.

This is a structural hazard, not a one-off: any branch that both edits `DESIGN-TRUTH.md`
and any branch that cites it by line number will silently desync the moment either merges
ahead of the other, and the test suite is documented (by Andrew, in the fix commit itself)
as only partially able to detect it. No single lead could see this while editing its own
branch — the desync is only created by the *order* two unrelated merges land in, which is
decided above both leads.

## 3. A design answer that had to be re-asked because the record already contradicted itself

`dd34dbb`'s diff shows `DESIGN-TRUTH.md` had, until that commit, an "open" entry saying
"whether every level really gets a worktree of its own" was undecided — while a separate,
already-**confirmed** entry a few lines above (`DESIGN-TRUTH.md:164` as cited in
`notes/issue-worktree-granularity.md`) already asserted "a lead's children share its
worktree." The document held both the settled answer and a note saying the same question
was still open, at the same time, until an investigation forced the contradiction to be
resolved. `notes/issue-worktree-granularity.md` states this plainly: "he had earlier
described every level as isolated, and has said plainly that he meant the code's way" —
i.e. Andrew had given two different descriptions of the same rule at two different times,
and it took a live proof (a top spawning a lead spawning two workers, observed to share
one worktree) to settle which one the code actually followed. Whether a single lead could
have caught this: no — a lead reading its own confirmed entry has no way to know an
"open" entry elsewhere in the same document silently contradicts it; that requires reading
and reconciling the whole document, which is exactly what `notes/issue-worktree-granularity.md`
and the DESIGN-TRUTH-consistency convention exist to force, and evidently did not happen
until this pass.

## 4. Worktrees and workspaces are never actually cleaned up, contradicting a confirmed DESIGN-TRUTH entry

`notes/issue-worktrees-never-deleted.md` (dated 2026-08-14, filed as GitHub issue #41)
reports that `DESIGN-TRUTH.md:229` confirms cleanup "closes the entire space and deletes
the worktree if everything else is closed too," but `Broker.cleanup` never calls
`workspace_close` — grepped, zero occurrences of `worktree`/`workspace_close` in its body.
The only call site of `workspace_close` in the package is the manual `sb workspace close`
CLI command. Measured at the time: 102 worktrees on disk (536 MB), 207–211 recorded
workspaces, **zero** with `retired_at` set — i.e. the close path has never once completed
successfully in this repo's history, and the gap is invisible to any single lead because
no lead's own task ever exercises the cleanup path end-to-end (each lead cleans its own
children's panes, which is a different, working code path from workspace/worktree
deletion). This is drift between a confirmed DESIGN-TRUTH entry and the code that only an
outside audit could surface.

## What I did not find strong evidence for

- No commit message or note describes a real file-content merge conflict between two
  agents editing the same file concurrently (`notes/issue-worktree-granularity.md` says
  the same: "no collision between siblings editing the same file has ever been observed
  in this repo... that is the record's silence, not a failed attempt to provoke one").
- No clear case of one agent overwriting another's uncommitted work mid-task (stale
  context) — the closest is the citation-shift bug above, which is a *post-merge*
  desync, not a live collision.
- I did not find a repeated identical question asked of Andrew across two branches other
  than the worktree-per-level contradiction in #3 above.

## Ranking by damage

1. **#1 (duplicate/orphaned note directories)** — largest, ongoing right now: 24 findings
   effectively invisible to the trusted index, plus a large duplicated file landed twice.
2. **#2 (citation re-aiming)** — recurring, structural, and self-documented as only
   partially caught by tests; will keep happening as long as line-numbered citations into
   a growing document coexist with concurrent branches editing it.
3. **#3 (contradictory design answer)** — one incident, but it shows the trusted document
   itself briefly held two answers to the same question.
4. **#4 (cleanup never firing)** — real and confirmed-vs-code drift, but slow-burn (disk
   usage) rather than acute, and already filed as issue #41.
