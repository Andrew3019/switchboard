# #4 command-surface redesign — proposal (for Andrew's decision)

Built on the scout map (`notes/plans-cmdsurface-scout.md`). Andrew's target model: lead
inits/copies a plan (command returns a path) → edits the JSON directly → an sb-side thing
"builds"/validates it → the small mutation verbs go away so editing is a conscious act.

## The one thing the scout changes about the plan

Andrew's "sb-only hook that watches an edit and validates it unprompted" **does not exist and
would be new file-watch infrastructure** — the plugin's module docstring treats "nothing
watches" as deliberate design, not a gap. BUT the board's existing draw-time seam
(`board_lines`) already reads the plan files every few seconds and **draws defects in red**
(it's how the board-UI change we just shipped surfaces a missing display/dep). That is,
functionally, the "hook that flags problems" — already built, already used. So we don't need
new infra; we need to (a) route the removed verbs' guards into that same defect check, and
(b) add an on-demand `validate` verb for a conscious "did my edit break anything" check.

## Proposed design (my recommendation)

1. **Remove the sugar verbs:** `assign`, `checkpoint`, `rework`, `gate`, `skip`, `dep`.
   Keep `tick` and `note` (frequent, small, write the changelog for you — GUIDE already says
   these two are the only ones worth typing) and the load-bearing minting/composition verbs
   (`create`, `add-step`, `name-step`, `template use`) + all read verbs. Nothing downstream
   depends on the removed verbs (no teardown coupling — scout §5).

2. **Move the removed verbs' guards into read-time validation** so removal loses no checking.
   Today these live ONLY inside the verb handlers and are re-checked nowhere:
   - `dep`: an edge to a nonexistent / cross-plan / self step,
   - `gate`: a gate on an already-done step,
   - `checkpoint`: a newline in a ref.
   Fold them into `_defects` (the WARN door the board draws red) — never into `_check` (the
   REFUSE door), so a hand-edit is flagged, never bricked. Result: the board's existing
   every-few-seconds redraw surfaces them automatically = the "build/validate hook" Andrew
   described, using the seam that already exists.

3. **Add `sb plugin plans validate <id>`** — on-demand, wraps the already-written
   `_check` + `_defects` + catalogue checks and prints what's wrong. Cheap (no new machinery).
   This is the conscious "check my edit" command, for when no board is open.

4. **Make `create` / `template use` print the plan's file path** (`p-<n>.json`) so the lead
   knows exactly what to open and edit. Small — the data's already in hand. (Only meaningful
   post-migrate, which is now done.)

5. **No file-watch.** The board redraw + on-demand `validate` cover it; true edit-watching is
   new infra the codebase deliberately avoids.

6. **DESIGN-TRUTH updated after** (Andrew's instruction): drop/retune the `gate` ("gates as
   exit conditions") and `skip` ("a skip is a state, never an absence") entries and note the
   thinner verb surface. Separate doc edit, after the code lands.

## Decisions I need from Andrew

- **Q1 — how far to cut?** Recommend removing `assign`/`checkpoint`/`rework`/`gate`/`skip`/`dep`
  (keep `tick`+`note`+minting+reads). Narrower option: just `gate`+`skip` (what he named).
  Wider: also drop `note`. Which line?
- **Q2 — the hook.** Confirm "board already red-draws defects + a new on-demand `validate`
  verb" is what he wants, and we do NOT build edit-watching file-watch infra. (Recommend yes.)
- **Q3 — guards.** OK to move the removed guards (gate-on-done, dep-resolves, checkpoint-
  newline) into the WARN/red-draw door rather than a hard refusal? (Recommend yes — refusing
  would make a hand-edited file brittle, which is the opposite of the goal.)

## Q4 — remove the plans lock altogether? (Andrew asked)

The plugin sets `LOCK = True`, so every command takes an exclusive flock on
`<state_dir>/.lock` for its whole (millisecond) duration. What removing it costs:

- **Reads: safe to drop entirely.** Per-file writes are atomic (temp + `os.replace`), so a
  reader never sees a torn file. No lock needed to read.
- **Writes: two races appear without a lock.**
  1. *Lost update* — two agents read-modify-write the SAME `p-<n>.json` concurrently, one
     clobbers the other. Mitigated by the design principle "one writer per plan (the worktree
     owner)"; the realistic case is a lead + its child touching the same plan at once. The
     append-only seal catches a changelog that *shrank*, not two independent appends where
     one is lost.
  2. *Id-mint collision* — two concurrent `create`/`add-step` read the same `next_step` and
     mint duplicate ids. `_check` catches it on the *next* read (refusing one file), but
     that's corruption caught late, not prevented.

**Options:**
- (a) Drop the lock entirely; accept rare races (id collisions caught by `_check`, lost
  updates guarded only by the one-writer convention). Simplest, small real risk.
- (b) Drop the coarse lock; keep a SHORT lock only around **id minting** (the 4 minting
  verbs). Reads + `tick`/`note`/hand-edits go fully concurrent; only the rare mint
  serialises. **Recommended.**
- (c) Make minting filesystem-atomic (create `p-<n>.json` with `O_EXCL`, retry on collision)
  for lock-free plan ids; global step-id uniqueness still needs a small scheme.

**Honest note:** plans commands are infrequent and hold the lock for milliseconds, so the
lock costs almost nothing in practice — removing it is more about matching the per-file model
than fixing a measured bottleneck. **Recommend (b)** if we remove it: it delivers the
concurrency the per-file split implied, with the least risk. **Q: (a), (b), or leave as-is?**

## Also folded into this PR — drop vowel-deletion from the display guidance (Andrew)

Andrew: "remove the vowel deletions for the display name. its way too much." The GUIDE and the
missing-display refusal message (`_SHORTEN` / `_no_display`, with the `invstgt` example)
currently push middle-vowel stripping. Soften to: shorten by abbreviating and cutting words
the title already implies — short but READABLE, no vowel-mangling. Replace the `invstgt`-style
example with a readable one (e.g. "list every claim…" → "list claims").

**Doc debt to clear in the #4 DESIGN-TRUTH follow-up** (both slipped through / were out of
scope earlier):
- `DESIGN-TRUTH.md` line ~425 still says "abbreviating and dropping middle vowels where that
  helps" — PR #123 merged before the vowel redirect reached the worker. Remove the vowel
  phrase here too.
- `design/PLANS-AND-STEPS.md` ~198-204 still carries the old "optional / falls back to its
  name clipped" wording — stale after the required-display change. Update it.

---

Once he picks Q1-Q4, this is one more PR (remove verbs + harden `_defects` + `validate` verb +
path printing + vowel-guidance softening + lock change), then a DESIGN-TRUTH follow-up.
