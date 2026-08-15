# Ghost rows: the fix, and why it is not the fix that was recommended

Follows `notes/qa-ghost-repro-isolated.md` (the reproduction) and
`notes/researcher-ghost-fix-shape.md` (the recommended shape). Scope: the
name/identity matching in `status.collect` only.

## 1. The recommended fix is a no-op on this herdr

The shape recommended was: refuse a name match when the two `session_id`s disagree.
Both sides do carry the field — but **herdr's side is always empty**. `agent list`
returns no `agent_session` key at all on herdr 0.8.x, so every `Agent.session_id`
built from that path is `""` and a session-only guard can never fire.

Observed, not inferred — every agent herdr listed on this machine:

```
issues                    w1E7:p1  session ''  term_659190a0890d3c99
github-issues             w1FS:p1  session ''  term_6591c6425345ad39
...                                            (9 of 9, all session '')
```

and the raw record has no such key (`agent get <name>` likewise):

```json
{"agent":"claude","agent_status":"idle","cwd":"...","name":"issues",
 "pane_id":"w1E7:p1","terminal_id":"term_659190a0890d3c99","workspace_id":"w1E7", ...}
```

## 2. What is compared instead

`terminal_id`, with `session_id` kept beside it for the day herdr reports one.

- present on **every** agent herdr lists, and unique per agent (9 distinct ids for
  9 agents, one per tab);
- herdr documents it as the STABLE handle, unlike `pane_id`, which changes on a
  pane move — a live agent could disagree with its own row and be read as dead, so
  `pane_id` is deliberately not used;
- our side writes it at the only two moments a row can acquire a pane,
  `broker._spawn` and `broker.restore`;
- 459 of this store's 463 rows carry one (read-only count against the live store).

The guard fires on **disagreement only**. Either side blank → the name match stands,
which is what shipped; a row mid-spawn has neither id yet and is covered by
`SPAWN_GRACE`, not by this.

## 3. Live before/after, in an isolated clone

Two clones under the session scratchpad, each with its own store (`store.repo_root()`
is `git rev-parse --git-common-dir`). Clone A holds a row `ghostfix-3` that died four
days ago; clone B runs a live agent of the same name via the ordinary `sb delegate`.
Same store, same stranger, only `status.py` swapped between runs.

```
=== BEFORE ===                          === AFTER ===
ghostfix-3  alive=True  archived=False  ghostfix-3  alive=False  archived=True
board draws:  board-A                   board draws:  board-A
              ghostfix-3                              Collapsed(count=1)
```

Through the real collector and the real `panel/snapshot.json` every board reads
(`collector.run(max_ticks=2)` → `panel.read`):

```
BEFORE   board-A False False            AFTER   board-A False False
         ghostfix-3 True False                  Collapsed(depth=1, count=2)
         Collapsed(depth=1, count=1)
```

The never-confirmed-dead half, with a control row that has no live namesake — both
`working`, unended, already 300 s absent (5× the 60 s grace), one reap-path collect:

```
=== BEFORE ===                                  === AFTER ===
ghostfix-3  working  absent_since=None          ghostfix-3  failed  ended_at set
ghostfix-9  failed   ended_at set               ghostfix-9  failed  ended_at set
```

Before, the collision threw the remembered absence away and the row stayed `working`
forever; after, it is confirmed dead like its control. No change to `_confirmed_gone`
was needed — it was being fed a lie.

## 4. Not touched, and what is left

- **`broker`'s own bare-name matching** (`_alive`, `_fill_agent_caches`/`_end_still_holds`,
  `h.get_agent(name)` at `broker.py:3494`) is unchanged — out of scope here, and another
  agent was landing on that path. Worth knowing which way each currently errs:
  `_end_still_holds` fails CLOSED on a collision (a stranger in the list makes cleanup
  REFUSE to close the row), so the collision does not make cleanup close the wrong local
  row. What remains unexamined is the close itself, which herdr resolves **by name** — a
  `--force` close of a colliding name is the near-miss reported against another clone's
  live worker, and it is not addressed by this change.
- Old stores with no `terminal_id` column degrade to the bare-name match (read
  defensively; a reader cannot migrate the store).
- Two rows both mid-spawn, before either side has any id, are still matched by name.
- Teardown: clone B's agent closed with `sb cleanup`, its leftover git worktree removed
  by hand, both clones deleted. No `pkill`. The live store was opened read-only, once,
  for the 459/463 count.
