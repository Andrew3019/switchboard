# reviewer-28 — adversarial review of `_forked_under` (commit 8494b3f)

Lens: does `_forked_under` select the WRONG set of spaces (over-reach / under-reach)?
Nothing else was reviewed — recursion, reporting and concurrency were explicitly out of scope.

## Verdict

**One real over-reach. Everything else I probed is correct.** The cascade is not "the spaces
this workspace's children forked" as `_forked_under`'s docstring
(`switchboard/broker.py:1922-1928`) and `_closed`'s (`:2100-2102`) both claim — it is *every
workspace any transitive descendant is FILED under*. Those coincide only while no descendant
has ever been placed into an existing space by name.

## Finding 1 — CONFIRMED over-reach: a sibling top's forked space is deleted

`_forked_under` (`switchboard/broker.py:1934-1941`) returns the descendant *rows*;
`_close_empty_spaces` (`:4634-4638`) then keys on `a["workspace"]` for each of them. A row's
`workspace` is not necessarily a space its subtree minted: `sb delegate --workspace <name>`
resolves through `join_workspace` (`:1557`), which files a child under an *existing* space
opened by somebody else — and the docstring there says that is exactly what people type when
a fork was refused because the branch is already checked out. So a descendant of `main-2` can
carry `workspace=lead-9`, a space forked by `main-3`'s child.

Scenario, run live (probe, not committed):

```
main-2 (bare, done)                 main-3 (bare, LIVE)
 └ lead-1  workspace=lead-1          └ lead-9  workspace=lead-9  (done, clean)
    └ worker-x workspace=lead-9   <- joined via --workspace
```

`self.b.workspace_close("main-2", me=HUMAN)` returned

```
spaces: ['lead-1', 'lead-9']   spaces_refused: []
lead-9 checkout still on disk: False
workspaces row lead-9: retired_at set, checkout NULL
```

`lead-9`'s worktree was deleted and its workspace retired by a close aimed at `main-2`, while
`main-3` — the top that owns it — is untouched and still registered.

No downstream gate catches it, and by design none can: `_space_ready` (`:4682`) refuses the
primary checkout, dirty content, unfinished rows under the path and live processes. A finished
child's clean space passes all four — that is precisely the case the cascade was built to
close. The gates cannot distinguish "clean idle space this subtree minted" from "clean idle
space another subtree minted", because the only thing that distinguishes them is the
parentage `_forked_under` was supposed to encode and then discards.

Same mechanism, worse target: the human's own worktree is a *linked* worktree, not the
primary, so `_space_ready`'s primary refusal does not cover it. It is protected only by
`_my_spaces`' `os.getcwd()` (`:4659-4680`) — i.e. only when the close is typed from inside it.
A descendant joined into Andrew's working space plus a `sb workspace close main-2` typed from
the main clone is the same deletion.

Severity: needs the join to have happened, so not the default path. But it is silent, it is
the one unrecoverable command in the codebase, and the docstring asserts it cannot happen.

Narrowing that would match the stated intent: take a candidate's workspace only when the row
is that space's namesake (`a["name"] == a["workspace"]`) — every forked space is named for the
child that forked it (`_fork_for`, `:3274`), so nothing intended is lost and the joined
foreign space drops out. Reviewer's suggestion; I did not implement it.

## What I probed and found CORRECT

- **Grandchild / deeper forked spaces are reached.** `main-2 → lead-1 → sub-2`, each with its
  own space: `spaces: ['lead-1', 'sub-2']`, both worktrees gone. `_descendants` (`:4997`) is
  transitive, and `children_of` (`store.py:1144`) has no state filter, so *finished* children
  are still found — which matters, because every child in the target scenario is finished.
- **Rows survive to be read.** `retire_workspace` (`store.py:1323`) touches only `workspaces`;
  `_stop_panes` (`:2489`) only closes panes. The only `DELETE FROM agents` is `drop_agent`
  (`store.py:1078`), used to undo an unclaimed name. A spawn that fails after `_fork_for`
  leaves a husk row with `parent` set (`:3574-3586`), so its orphaned space *is* reachable.
  Running `_forked_under` after retire/stop is safe.
- **Primary checkout.** Descendant filed under a workspace whose checkout is the primary:
  `spaces_refused: [('primary-alias', "its checkout IS this repository's primary working
  tree")]`, repo intact.
- **Two names over one directory.** A live agent filed under a second name over `lead-1`'s
  checkout: both `lead-1` and `alias` refused by `_records_gate`, directory intact. (Both
  refusals are reported, which is duplicate output — reporting lens, not mine.)
- **Degenerate inputs.** Bare workspace with no agent rows → `spaces: []`, no error. Descendant
  with `workspace` NULL → skipped by `if w and ...` in `_close_empty_spaces`, no error.
- **Sibling tops cannot be descendants of each other.** `sb start` goes through `delegate` with
  `me=HUMAN`, which stores `parent=None` (`:3536`), so every top is a root.
- **Nested bare space.** Skipped silently by `checkout is None`; unreachable anyway, since only
  `is_top` mints spaces and only `_top` stamps `is_top` (`:1291-1298`).

## Method

`tests/test_workspace_close.py` passes (70). Scenarios above run from a scratch probe built on
`CloseHarness` (real git, fake herdr) at
`/private/tmp/claude-501/.../scratchpad/probe_forked_under.py`; printed output quoted verbatim.
No code changed. I did not run any of this against a real herdr fleet.
