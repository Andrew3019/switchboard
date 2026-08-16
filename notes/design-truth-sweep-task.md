# Task: record the worktree sweep in DESIGN-TRUTH.md

Andrew has explicitly authorised this edit. `DESIGN-TRUTH.md` is normally his file alone; this
one change is sanctioned. Treat it with that weight.

**You own exactly one file: `DESIGN-TRUTH.md`.** Another agent is working on `switchboard/` and
`tests/` in this same worktree at the same time — do not touch any file but that one, and do not
touch anything under `notes/`.

## What changed in the system

PR #74 on branch `worktree-model` adds an automatic worktree sweep. Read these before writing a
word:

- `/private/tmp/switchboard-sweep-report-2026-08-16.md` — what was built and proved
- `notes/worktree-model-findings.md` — how worktrees worked before this
- `notes/sweep-rebase-reproof.md` — the rebase and live re-proof
- `switchboard/sweep.py` — the code itself, which is the authority over any of the above

The behaviour, in short: a board sweeps twice an hour, at :00 and :30 on the system clock; exactly
one board per tick; no board running means no sweep. A worktree is deleted only when it has a
live agent (no), a dirty tree (no), unpushed non-docs commits (no), and has been quiet over 24h
on both clocks — last agent activity and last commit. Landed means merged **or** pushed, decided
three ways: tip on a remote, patch-equivalent upstream, or commit subject in the base's history.
Docs-only is path-based — every changed file a `.md` or under `notes/`, `design/`, `learnings/`,
`research/` — with `DESIGN-TRUTH.md` carved out so a change to it always blocks. Every deletion
goes through `sb workspace close`, gates unchanged. Ignored files do **not** hold a worktree back
(`sweep.ignored_content_holds = false`), a decision Andrew confirmed. The live-process gate is
deliberately left alone.

## How to write it

**This is a consistency pass over the whole document, not an append.** Read `DESIGN-TRUTH.md`
end to end first. The sweep contradicts or dates several things already in it — at minimum the
existing statements about worktrees only being cleaned by a human-typed command, about `sb
restore` and when it is lost, and about work being pushed before a worktree is deleted being a
convention rather than a rule. Find every such place and leave the document true and coherent,
rather than adding a new paragraph that argues with an old one.

Match the document's existing voice, structure and level of detail exactly. Do not invent a new
section style. Where it stamps confirmations with a date, use **2026-08-16**.

A proposed wording exists, as a starting point only — improve it, and place it where it belongs:

> **A board sweeps the fleet's worktrees twice an hour, at :00 and :30.** A worktree goes only
> when nothing is left to lose: no live agent, nothing git can see uncommitted, its commits
> merged or pushed — or the only unpushed ones docs-only, which DESIGN-TRUTH.md is never part of
> — and quiet for over a day on both clocks, last agent activity and last commit. Exactly one
> board sweeps per tick, and no board running means no sweep. Every deletion is
> `sb workspace close`'s, gates and all.

Write only what the code actually does. If the report and the code disagree, the code wins and
you tell me about the discrepancy.

## Landing

Commit on `worktree-model`, that one file, one commit. **Push** — the PR is open and this belongs
in it. Do not merge, do not touch `main`.

Report in a few plain sentences: what you added, and specifically which existing passages you had
to change or delete because the sweep made them untrue.
