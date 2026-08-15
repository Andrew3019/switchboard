## The question

Switchboard mints a new git worktree for every top-level delegate. Is that the right
granularity?

**This is a design question to revisit, not a bug.** The investigation that raised it found
the rule is implemented exactly as DESIGN-TRUTH describes and is cheap to run. It is filed
so it can be forgotten about rather than re-derived.

## The rule, as it stands

`Broker.delegate` (`switchboard/broker.py:3033`), and the "THE FORK RULE" comment block at
`broker.py:3069-3104`:

- A new worktree and space is minted **only** when `mints_space(me)` is true
  (`broker.py:2581`) on the inherited path — i.e. the caller passed no explicit
  `workspace=`. `mints_space` reads the `is_top` stamp written by `sb start` and nothing
  else: not the role, not whether the caller already holds a worktree.
- Everyone else's `delegate` — an orchestrator's, a lead's — puts the child in a **tab in
  the caller's own space**: same worktree, same checkout.
- `_fork_for` (`broker.py:2904`) names the branch and the worktree after the agent,
  verbatim, and forks from the parent's branch if it has one, otherwise from a freshly
  fetched `origin/main`.

This matches DESIGN-TRUTH, confirmed 2026-08-09:

> **Only `sb start` ever creates a top orchestrator — that is the only path.** … a top's
> spawn gets a new space and worktree, anyone else's gets a tab in the caller's space.
> (`DESIGN-TRUTH.md:42`)

> **A worktree belongs to a space, not to an agent.** (`DESIGN-TRUTH.md:63`)

> **A lead's children share its worktree, so the lead assigns disjoint files and serialises
> anything that overlaps.** (`DESIGN-TRUTH.md:164`)

## Why it is not obviously wrong

- **It is cheap.** One timed `git worktree add`: **0.157 s**. Disk is ~5.2 MB per worktree
  on average (536 MB across 102 of them), of which git's own bookkeeping in
  `.git/worktrees` is 3.9 MB — about 0.7%. Neither number justifies changing the rule on
  its own.
- **It isolates the one case nothing else covers.** Below a top, a lead already coordinates
  its children by assigning disjoint files, which DESIGN-TRUTH states explicitly. The
  worktree boundary is doing real work only between *sibling tops* — two unrelated
  `sb start` trees, or two independent things being done at once — where no lead exists to
  serialise anything.
- **It is a confirmed entry.** DESIGN-TRUTH's rule about contradicting a confirmed entry is
  to stop and ask, so changing the fork rule needs Andrew's explicit sign-off rather than a
  PR.

## What is not recorded

DESIGN-TRUTH records the *rule* and its *consequence*, not a rationale. Grepping it for
"isolat", "concurrent" and "conflict" returns **zero hits** — concurrent-write safety is
the obvious motive and is consistent with everything else in the file, but it is an
inference, not something stated. If it is in fact the reason, it is worth Andrew confirming
so it can be written down instead of assumed.

Nor is there any evidence in the code or in DESIGN-TRUTH of a concurrent-write incident
that this granularity was tuned in response to, so there is no record of a coarser or finer
cut ever having been seriously compared against this one.

## Largely moot if the cleanup bug is fixed

The thing that made this question feel urgent — a hundred-odd worktrees lying around — is
not caused by the fork rate. It is caused by nothing ever deleting them: **96 of the ~103
checkouts on disk belong to spaces where every agent already finished**, 101 of 102 are
clean, and 57 are already merged. Fix the cleanup gap and the accumulation stops,
regardless of how eagerly the rule forks.

So this issue should be treated as **blocked on, and probably answered by**, the cleanup
issue. If worktrees are closed automatically when a space finishes, one worktree per
top-level delegate costs 0.157 s and a few MB for the lifetime of that space, and there is
nothing left to revisit.

## Options considered, if it is revisited anyway

- **Keep as is.** Zero work, zero new risk.
- **Fork less eagerly** — require stronger evidence of concurrent-write risk instead of
  forking for every top-level delegate. Directly contradicts the confirmed DESIGN-TRUTH
  entry above, so it needs Andrew to reopen that entry first. Large.
- **Share one worktree more broadly**, relying on file-ownership discipline instead of a
  directory boundary. Same gate, deeper: it removes the isolation the whole
  worktree-per-space model rests on. Larger.

## Source

Investigation notes: `notes/researcher-37-why-so-many-worktrees.md` on branch
`researcher-37`. Every code reference and DESIGN-TRUTH quote above was re-checked against
the files directly for this issue.
