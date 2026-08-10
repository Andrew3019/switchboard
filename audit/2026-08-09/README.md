# Audit of 2026-08-09 — switchboard against DESIGN-TRUTH

Raw findings from the read-only audit that produced `BUILD-PLAN.md`. Kept because the
evidence is `file:line` specific and expensive to regenerate; **the plan is what you
act on**, this is what you check it against.

- Six groups covering all 52 entries of `DESIGN-TRUTH.md` — 65 checkable claims,
  11 SATISFIED, 31 PARTIAL, 22 BROKEN, 0 UNVERIFIED.
- Run by six sub-orchestrators, each fanning out to its own auditors, all read-only.
- `DESIGN-TRUTH.md` was the only trusted document; every other doc in the repo was
  treated as untrusted, and code comments were verified against the code.

| file | group |
|---|---|
| `1-placement.md` (+ `1-part-a/b/c`) | spawn and placement — spaces, tabs, worktrees, focus, board split |
| `2-messaging.md` (+ `2a/2b/2c`) | delivery modes, tell, inbox, done, prefix |
| `3-lifecycle.md` (+ `3-part-a/b/c`) | cleanup, restore, blocked children, reconciler, the finish CUJ |
| `4-human.md` (+ `4a/4b/4c`) | block, inspect, board, status, output rules |
| `5-roles.md` | roles, prompts, presets, scope boundaries, what an agent knows at spawn |
| `6-removals.md` (+ `6-a/b/c`) | the rejected list — is any of it actually gone |
| `CONSOLIDATED.md` | totals and the two findings the reconciler verified personally |

**Two caveats.** Verdicts were taken against `worker-2` at `a9dd319`, byte-identical to
`main` on every file cited. And these are snapshots — once a phase of `BUILD-PLAN.md`
lands, the file:line references here go stale. They are evidence of what was true on
2026-08-09, not a live map.
