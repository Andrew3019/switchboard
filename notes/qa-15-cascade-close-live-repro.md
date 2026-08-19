# QA: live isolated-clone proof of dispatcher cascade-close (commit 8494b3f)

Verifies p-11 step s-56, brief `.switchboard/briefs/qa-live-repro/brief.md`.

## Method note: why not `sb start`/`sb delegate`

The brief's literal method (spawn a real dispatcher via `sb start`, delegate real children)
is refused for any agent caller by design: `cli.py:571 _agent_caller`, added in `b0f5973`
(before this fix), fails closed on any command bearing `CLAUDE_CODE_SESSION_ID`/`CLAUDECODE`
— which every Claude Code process carries, including a QA agent driving an isolated clone.
Its own docstring names this exact clone-based verification convention and says it is
deliberately still refused, because the CLI cannot tell a deliberate isolated run from an
accidental one, and an agent accidentally spawning real top-level orchestrators is the
incident this guard exists to stop. Bypassing it (env-stripping, or calling
`Broker.start()`/`delegate()` directly) would recreate the exact real running-process risk
the guard prevents, just through a different door — not attempted.

Instead: real herdr (`h.create_workspace`, `Broker._fork_for` → real
`create_worktree`), real git worktrees, real sqlite store rows, all written the same way
`sb start`/`sb delegate` write them (same broker/store calls) — skipping only
`Herdr.start_agent` (launching an actual autonomous Claude process), which is irrelevant to
what closing a workspace does. The command actually under test, `sb workspace close`, was
run for real via the real CLI throughout.

## Setup — isolated clone

`git clone` of `/Users/andrew/Code/switchboard` into a scratch dir, checked out
`fix-orphaned-dispatcher-children` (`4e81d60`). `sb doctor` confirmed the clone's store was
its own (`.../sb-qa-clone/.git/agentflow/state.db`), never the live one. All commands run
via `cd "$CLONE" && ./bin/sb ...`.

## Proof

Built `qa15-dispatcher` (bare, `is_top=1`), forked two children `qa15-clean` and
`qa15-dirty` (each its own real herdr worktree workspace, matching the FORK RULE at
`broker.py:3474`), marked all three `state=done`. Dropped `qa15-scratch.tmp` (gitignored,
`*.tmp`) into `qa15-dirty`'s checkout.

```
$ ./bin/sb workspace close qa15-dispatcher
closed 1 pane(s): qa15-dispatcher
retired qa15-dispatcher — no checkout of its own, so nothing was deleted
  closed space(s): qa15-clean
  kept space qa15-dirty: /Users/andrew/.herdr/worktrees/sb-qa-clone/qa15-dirty holds 1
  ignored file(s) that git will not miss and the removal WILL delete: qa15-scratch.tmp.
  Nothing has been touched. `sb workspace close qa15-dirty --yes` deletes them with the
  checkout.
```

Confirmed on disk/registry, not just from the message:
- `qa15-clean`: gone from `git worktree list`, directory deleted, workspace row `retired`.
- `qa15-dirty`: still in `git worktree list`, directory intact, `qa15-scratch.tmp` still
  there, workspace row `ok` — kept, not destroyed, exactly as claimed.
- `qa15-dispatcher`: retired, nothing to delete (bare).

This proves items 1–3 of the brief: before the fix a finished child's forked space was
silently orphaned by `sb workspace close <dispatcher>`; after the fix the same command
closes it, and a dirty child space is refused and reported, never destroyed.

One incidental real finding, unrelated to this fix: a synthetic dispatcher's bare
workspace can be adopted by herdr as the repo's "worktree group parent" (pre-existing,
already documented in `notes/dispatcher-space-and-cross-repo.md`), which made the first
`sb workspace close` attempt fail with a herdr `confirmation_required` error until the
panes were closed directly via `herdr pane close` first. Not a switchboard bug and not
part of what this fix changes; noted here only because it shaped how the fixture had to
be built.

## Not proven

**Item 4 (optional old-vs-main comparison) — not completed.** Attempting it caused an
incident (below); I stopped rather than retry it. So there is no live before/after run on
this task, only the root-cause note's static analysis (already trusted separately) plus
the live proof of the new behavior above.

## Incident during the optional step, now resolved

A second fixture-setup script for the old-vs-new comparison was run without first `cd`-ing
into the scratch clone. `store.connect()`/`store.worktree_root()` fall back to
`os.getcwd()`, which was still my own live agent workspace
(`/Users/andrew/.herdr/worktrees/switchboard/fix-orphaned-dispatcher-children`) — its
`git rev-parse --git-common-dir` resolves to the **live** production store
(`/Users/andrew/Code/switchboard/.git/agentflow/state.db`), not the clone's. This wrote a
real row `qa15b-dispatcher` (bare, `is_top=1`, `state=done`, no children — the next step
failed before any were created) and opened a real herdr workspace `w1MN` there.

I could not close it myself: `sb workspace close qa15b-dispatcher` from my own pane was
refused by the Claude Code auto-mode permission classifier, and `sb inspect
qa15b-dispatcher` reported it as another dispatcher's tree, invisible across the scope
boundary. Blocked for a human (Andrew ran the close). Verified after: `workspaces` row
`retired_at` set, `w1MN` no longer in `herdr workspace list`. Nothing else was touched by
the mistake — no worktree/checkout was ever created for it, and the clone's own store never
received the stray row.

## Teardown — confirmed complete

- Clone's three `qa15-*` workspaces: all `retired`, `qa15-dirty` explicitly deleted with
  `--yes`, `qa15-clean`/`qa15-dispatcher` had nothing to delete (bare/already-removed).
  `git worktree list` in the clone shows only its own checkout.
- Scratch clone directory and helper scripts: deleted (`rm -rf`).
- Live-store leak (`qa15b-dispatcher`): retired by Andrew, confirmed via
  `workspaces.retired_at` and absence from `herdr workspace list`.
- My own live checkout: `git status` clean throughout, never touched by any of this.
