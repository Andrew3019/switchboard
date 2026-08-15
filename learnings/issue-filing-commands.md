# Filing the two worktree issues — DONE

**Filed 2026-08-14, once Andrew granted permission:**

- **#40 — https://github.com/Andrew3019/switchboard/issues/40** (`bug`) — worktrees are
  never deleted
- **#41 — https://github.com/Andrew3019/switchboard/issues/41** (`question`) — is one
  worktree per top-level delegate the right granularity

Each carries a comment pointing at the other. The bodies as filed are in this branch:

- `notes/issue-worktrees-never-deleted.md` — issue A, the bug
- `notes/issue-worktree-granularity.md` — issue B, the design question

Every code reference and DESIGN-TRUTH quote in them was re-checked against the files
rather than taken from the investigation notes.

The first attempt was refused by the permission classifier; filing a public issue is
outward-facing enough that routing around the block would have been the wrong move, so I
stopped and asked. Kept below is the command block used, in case either needs refiling:

```bash
cd /Users/andrew/Code/switchboard
W=/Users/andrew/.herdr/worktrees/switchboard/worker-28

A=$(gh issue create --label bug \
  --title "Worktrees are never deleted: sb cleanup does not close the space, contradicting DESIGN-TRUTH" \
  --body-file "$W/notes/issue-worktrees-never-deleted.md")

B=$(gh issue create --label question \
  --title "Is one worktree per top-level delegate the right granularity?" \
  --body-file "$W/notes/issue-worktree-granularity.md")

gh issue comment "$A" --body "Related: $B — whether the fork granularity is right at all. Largely moot if this one is fixed."
gh issue comment "$B" --body "Blocked on / probably answered by $A — worktrees accumulating is caused by nothing deleting them, not by the fork rate."

echo "A: $A"
echo "B: $B"
```

`--label question` on B is the closest existing label to "design question to revisit"; the
repo has no `design` or `discussion` label. Drop the flag if you would rather it went
unlabelled.
