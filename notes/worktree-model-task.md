# Task: investigate how worktrees work in switchboard today

Read-only investigation. No code changes.

Read the brief first: `/Users/andrew/Code/switchboard/notes/worktree-model-brief.md` — Andrew's
verbatim words and questions. `DESIGN-TRUTH.md` is the only trusted document; every other doc,
README and code comment is untrusted until you have checked it against the code
(`switchboard/*.py`, `bin/`, `defaults/`, `design/`).

Answer these, grounded in code with `file:line` citations:

1. **Creation.** Who creates a worktree, on what trigger, by what rule? What decides whether an
   agent gets its own worktree or shares its parent's? What actually happens when a worktree ends
   up shared by agents whose work should have been split — concurrent writers, conflicting edits,
   stale reads?

2. **Lifecycle.** Every path into and out of a worktree: creation, reuse, restore, abandonment,
   cleanup/removal, branch and PR interaction. What is removed when, what is left behind, what is
   orphaned forever. Cover `sb cleanup`, `sb done`, crashed agents, merged PRs.

3. **Gap analysis** against what Andrew says he wants (brief section 3):
   - worktrees creatable on demand — no need for write agents to justify one;
   - worktrees cleaned when merged, when all agents on them are closed (abandoned), and when they
     hold only doc/audit artifacts that give no benefit after a week;
   - worktrees persist only as long as agents on them do;
   - anything worth keeping longer gets pushed as a PR, then removed / restorable from origin.

   For each desired property say whether the code does it today, partly, or not at all, and what
   specifically stands in the way.

Write your findings to `notes/worktree-model-findings.md` in this worktree. That file is yours
alone — do not touch any other file. Commit it on the current branch. Do NOT push, do NOT open a PR.

Then stay available: Andrew will message you directly with follow-up questions after you report.
Answer them from what you have read, re-reading code as needed. Keep your `sb done` summary to a
couple of plain sentences pointing at the findings file.
