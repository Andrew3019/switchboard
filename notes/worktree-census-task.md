# Task: live census of every worktree that exists right now

Read-only. Change nothing, delete nothing, commit nothing, create no worktrees or agents.
Do not run `sb cleanup`, `sb workspace close`, or any git command that writes.

Andrew's question: how many worktrees do we actually have right now, what state are they in,
and which gaps in switchboard's cleanup model explain why they are still there.

## What to gather

For the switchboard repo (`/Users/andrew/Code/switchboard`, worktrees live under
`/Users/andrew/.herdr/worktrees/switchboard/`):

1. Every worktree git knows about — `git worktree list` from the main checkout.
2. Every workspace switchboard knows about — `sb workspace list` (and note which source each
   row comes from: store vs git).
3. Every agent alive or closed per workspace — `sb status`, and the store if needed.
4. Any directory under the worktrees root that neither git nor switchboard lists (true orphans).

## For each worktree, establish

- its branch, and whether that branch has an upstream / has been pushed
  (`git log @{u}..HEAD` or equivalent — unpushed commits are the dangerous case);
- whether it is merged into `main` (local `git branch --merged`, and check the remote/PR state
  with `gh pr list --state all --head <branch>` if a remote branch exists);
- whether the working tree is dirty or has untracked files;
- date of its last commit, and how old the worktree is;
- how many agents are attached and how many of those are still alive;
- what the commits actually contain — real code changes, or only notes/docs/audit artifacts.

## What to conclude

Classify every worktree into one of:
- **live** — agents still working there;
- **safely deletable** — merged or pushed, no live agents;
- **would lose work if deleted** — commits that exist nowhere but that directory;
- **stale artifact** — only docs/notes, no live agents, old;
- **orphan** — on disk but unknown to switchboard, or unknown to git.

Then say, per class, which specific gap in the cleanup model left it in that state — e.g. no
automatic sweep, no merge check, no push check, no staleness rule, no orphan detection.

## Reporting

Do NOT write a file and do NOT commit. Put the whole thing in your `sb done` summary: the counts
first, then the per-worktree table in plain text, then the per-class gap attribution. It will be
read by a person, so keep it tight and skimmable. Be exact about numbers.
