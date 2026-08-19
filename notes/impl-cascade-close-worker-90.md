# Implement cascade-close (A.2) — worker-90 report

Commit `8494b3f` on `fix-orphaned-dispatcher-children`. Full suite: **1523 passed**.

## What changed
- `switchboard/broker.py:1903-1908` — `_close_bare`, after retiring the bare space, runs
  cleanup's own `_close_empty_spaces` over the subtree; the returned dict now carries
  `spaces` / `spaces_refused`.
- `switchboard/broker.py:1910-1943` — new `_forked_under(name)`: the workspace's own rows
  -> `_descendants`, so the cascade is scoped by PARENTAGE, not workspace name (holds for
  any bare workspace, not only one whose top happens to share its name).
- `switchboard/broker.py:_closed()` — gained `spaces`/`spaces_refused`, present-and-empty
  on all three routes.
- `switchboard/cli.py:1200-1206` and `_workspace_closed` — `closed space(s): ...` /
  `kept space X: ...` lines in cleanup's own wording; JSON gets `{name, reason}` shape.

No new "is it safe to delete" logic: every gate, inventory and confirmation is
`workspace_close`'s, unchanged. `_unfinished_in`'s deliberate `WHERE workspace=?` scoping
untouched; `_close_checkout` untouched; no A.1 live-children refusal added.

## Tests
`tests/test_workspace_close.py::BareCascadeTest`, 3 tests:
- finished child's clean forked space is closed too (was orphaned before);
- dirty child space is kept and reported, not destroyed — dispatcher still retires;
- live child's space still holds itself, unchanged.

## Unproven
- No live isolated-clone repro (that is the QA step, not this one).
- Fake-herdr tests exercise the store/git side only; real herdr deletion of a forked
  child space is untested here.
- Deep chains (a grandchild that is itself a top and forks its own space) have no test,
  though `_forked_under` walks the full descendant tree.
