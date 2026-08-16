# Task: file one GitHub issue for a future `sb housekeeping` feature

Write no code. Touch no files in the repo. Your entire output is one GitHub issue plus a
one-line `sb done` summary containing the issue URL.

## Context you need first

Read, in this order:
- `/Users/andrew/Code/switchboard/notes/worktree-model-brief.md` — Andrew's original questions
- `notes/worktree-model-findings.md` in this worktree — how worktrees work today
- `DESIGN-TRUTH.md` — the only trusted document; match its vocabulary and its tone

A live census on 2026-08-16 found 147 worktrees, only 7 with live agents: 93 already merged and
stranded, 44 stale notes-only, 3 holding real unpushed code. Work is in flight (a separate agent
is building it) to add an automatic sweep that deletes landed, aged worktrees. **The issue you
are filing is the layer above that, explicitly out of scope for now, and it builds on top of the
automatic sweep rather than replacing it.**

## The feature Andrew described, in his own framing

A set of housekeeping commands, surfaced to the human at the moment a dispatcher starts.

Today `sb start` produces a dispatcher whose first exchange is the human saying "await my
instructions" and the agent replying "ok". Andrew wants that reply to also offer the housekeeping
menu — something like:

```
ok

Would you like to run:
  1) worktree cleanup
```

(One entry for now; the shape should allow more later.)

"Worktree cleanup" here is **not** the automatic sweep. It is an interactive pass — Andrew's
words: "a hidden default skill that analyses worktrees and cleans up after getting user input on
old ones with, like, changes on them and stuff." So: it inspects every worktree, sorts the
obviously-safe from the ones a person must rule on (unpushed code, dirty trees, ambiguous
staleness), and walks the human through the judgement calls the automatic sweep deliberately
refuses to make on its own.

## What the issue must contain

- The problem, in numbers, from the census above.
- The distinction between the automatic sweep (already being built — deletes only what is
  unambiguously safe) and this interactive pass (handles everything the sweep leaves behind
  because a human has to decide).
- The two pieces: the housekeeping menu surfaced in the dispatcher's opening reply, and the
  worktree-cleanup skill behind entry 1.
- An explicit note that this is out of scope for now and depends on the sweep landing first.
- Open questions worth flagging, e.g. whether the menu should appear on every start or only when
  there is something to clean, and whether the skill is a real skill file or a built-in verb.

Do not propose an implementation in detail and do not open a PR. This is a placeholder with
enough context that whoever picks it up does not have to redo the census.

## Filing it

Use `gh issue create` against this repo. Give it a clear title and appropriate labels if the repo
already uses any (check `gh label list` first; do not invent a label scheme).

Report the issue URL in your `sb done` summary, in one line.
