# Task: build the automatic worktree sweep

You own this change end to end. You are the only agent writing code in this worktree — every
file under `switchboard/`, `bin/`, `tests/` and `defaults/` is yours. Do **not** touch
`DESIGN-TRUTH.md` (only Andrew edits it) and do not touch any file under `notes/`.

## Read first

- `notes/worktree-model-findings.md` in this worktree — a verified account of how worktree
  creation, lifecycle and cleanup work today, with `file:line` citations. Start here; it will
  save you the investigation.
- `DESIGN-TRUTH.md` — the only trusted document. Everything else, including READMEs and code
  comments, is untrusted until checked against the code.
- `/private/tmp/switchboard-worktree-census-2026-08-16.md` — the live census this is a response
  to: 147 worktrees, 7 with live agents, 93 already merged and stranded, 44 stale notes-only, 3
  holding real unpushed code.

## What Andrew decided

These are settled. Do not relitigate them; if one is impossible, say so rather than substituting
your own rule.

1. **A sweep runs automatically from `sb board`**, on the system clock at :00 and :30. If several
   boards are running, exactly one performs the sweep — dedup with a lock so the others skip.
   Note plainly in your summary that this means no board running == no sweep.
2. **Landed means merged OR pushed.** A pushed branch is enough — it is recoverable from origin,
   which is the bar. A PR is encouraged for visibility but is not required. The current merge
   check is ancestry-only, so 3 worktrees whose work reached `main` via squash/rebase read as
   unmerged; the new check must count those as landed.
3. **Unpushed commits block deletion — unless they are docs only.** Docs-only is **path-based**:
   every changed file is a `.md`, or lives under `notes/`, `design/`, `learnings/`, or
   `research/`. `DESIGN-TRUTH.md` is carved out — an unpushed change touching it is never
   docs-only and always blocks. Docs-only worktrees are not protected and get swept on age like
   anything else.
4. **A dirty tree always holds a worktree open**, regardless of age or landed state. Uncommitted
   work is the one thing with no copy anywhere. This includes the dirty trees currently hidden
   behind an ignored-file count — surface them rather than swallowing them.
5. **"Over a day old" must satisfy both clocks**: last agent activity in the workspace AND last
   commit date must each be more than 24h ago. Either one being recent holds it open.
6. A worktree with any live agent is never touched.

Applied to the census, the sweep should delete the 93 landed and the 44 stale notes-only, keep
the 7 live, and refuse the 3 with unpushed code. Andrew clears those 3 by hand.

Out of scope, and Andrew is doing them manually: deleting those 3, and reaping the 122 stale
`sb workspace list` rows. Do not build either.

## Verification — this is what the work is judged on

Prove it live in an isolated instance, in the smallest run that distinguishes working from
broken:

- `git clone` this repo into a scratch directory outside the live tree. A clone gets its own
  state via git's common dir. Check your branch out there and drive **that clone's** `./bin/sb`.
  Never run a clone's `sb` from outside the clone — that silently writes to the live store.
- Agents you spawn in the clone are invisible to the live fleet but **are** visible to herdr, so
  they appear in Andrew's spaces UI. Tear down everything you create.
- Never an unscoped `pkill`. One of those killed the live collector previously.
- Build worktrees in the clone covering each decisive case: landed-and-old, squash-merged,
  pushed-not-merged, unpushed-code, unpushed-docs-only, dirty, recent-commit-old-agent,
  recent-agent-old-commit, live-agent. Show the sweep deletes exactly the right set.
- No endurance testing. Rare and slow-burn faults will surface in real use.

**Tests:** two or three, to pin the decisions — not for confidence. Run with
`/Users/andrew/anaconda3/bin/python -m pytest tests`. Do not teach the fake herdr new tricks to
make a test possible; skip the test and say what is therefore unproven. Anything you leave
unproven belongs in your summary — unproven and stated is fine, unproven and silent is not.

## Landing

Commit on the current branch (`worktree-model`). Do **not** push, do **not** open a PR, do
**not** touch `main` — I integrate.

If `DESIGN-TRUTH.md` needs an amendment to stay consistent with what you built, write the
proposed wording into your `sb done` summary rather than editing the file.

Keep the summary to a few plain sentences: what you built, what you proved live, what is
unproven.
