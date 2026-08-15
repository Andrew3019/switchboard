# Worktree indicators and visual grouping on the board

Investigation only, per `notes/task-worktree-grouping.md`. No product code changed.
`DESIGN-TRUTH.md` is the only trusted document; everything else here (including my own
earlier assumptions) was checked against the code and the live store, not taken on faith.

## TL;DR

A "workspace" here already means "one git worktree + one herdr workspace + one lead
agent" (`broker.py:71`, and `sb workspace`'s own help text: "workspaces (worktree + herdr
workspace + lead)"). **The fork rule** (`Broker.delegate`, `broker.py:3069-3097`) means a
new workspace is minted *only* when the caller is a top-level orchestrator (`is_top`, or
the human); every other delegate is "a tab in the caller's own space, and so is that
spawn's whole subtree" (`mints_space`, `broker.py:2581-2598`). So:

- **Ordering (part 2) is already true.** `status._tree` (`status.py:1337`) is a plain
  parent-before-children walk, siblings in creation order. Since a workspace can only
  begin at a "child of a top" edge, and the walk visits a subtree contiguously before
  moving to the next sibling, every agent in one workspace is *already* contiguous on the
  board. I could not find a single counter-example in this repo's entire agent history
  (361 rows, see below) — nobody has ever used `sb delegate --workspace <name>` to jump a
  child into a workspace other than its parent's.
- **Visual grouping (part 3) is already there, and already lines up with workspace
  boundaries.** `board._starts_group` (`board.py:340-352`) draws a blank line above every
  row at depth 0 or 1 — i.e. above every root and every direct child of a top. That is
  *exactly* where a new workspace can begin. The board groups by workspace today; it just
  never says the word.
- **An indicator (part 1) is the only genuinely missing piece, and in the common case it
  would be pure noise.** A forked workspace is named after the agent that was forked into
  it (`_fork_for` takes `name` as the workspace name; nobody in this repo's history has
  ever overridden that with `--workspace`). So at the row that begins a group — the one
  place an indicator would be new information — the workspace name and the agent name are
  the same string, every single time, in every real example I could find.

**My recommendation: don't add a workspace column or a per-row marker.** The one thing
worth adding is much smaller — see "Recommended" below.

## What a workspace actually is, with evidence

`git worktree list` right now (main checkout) shows ~90 linked worktrees, one per
workspace name, living at `~/.herdr/worktrees/switchboard/<name>`. `sb status --json` on
my own subtree confirms the model directly:

```
depth  name            parent      workspace
0      board-fix       -           board-fix
1      researcher-22   board-fix   researcher-22
1      researcher-23   board-fix   researcher-23
1      researcher-24   board-fix   researcher-24
1      researcher-25   board-fix   researcher-25
1      researcher-26   board-fix   researcher-26
1      researcher-27   board-fix   researcher-27
1      worker-25       board-fix   worker-25
1      researcher-30   board-fix   researcher-30
1      worker-28       board-fix   worker-28
1      researcher-31   board-fix   researcher-31
1      researcher-32   board-fix   researcher-32   ← me
```

`board-fix` is a top (`sb start`'d), so every one of its direct children forked its own
worktree — `mints_space` is true only for a top or the human, and it's read from every
delegate call, not just the first. `sb status`'s own wide table already carries a
WORKSPACE column and shows the same thing: at depth 1 the workspace name is character-for-
character the agent's own name.

To see whether this holds below depth 1, and whether an explicit `--workspace` join ever
diverges an agent from its parent's workspace, I read the *entire* store
(`.git/agentflow/state.db`, 361 rows, spanning this repo's whole build history — plugin
redesign, the workspace model itself, status-board work, the teardown fixes, the
`main-2`..`main-15` generations, all the way to `board-fix`). I compared every agent's
workspace to its parent's:

```
plugins-redesign-lead (ws=plugins-redesign)   child of main        (ws=main)
workspace-model-lead  (ws=workspace-model)    child of main        (ws=main)
status-board          (ws=status-board)       child of main        (ws=main)
...
worker-2              (ws=worker-2)           child of main-4      (ws=main-4)
audit-1               (ws=worker-2, depth 2)  child of worker-2    (ws=worker-2)  ← same
reviewer-1            (ws=worker-2, depth 3)  child of audit-1     (ws=worker-2)  ← same
teardown-lead-2       (ws=teardown-fix)       child of main-2      (ws=main-2)
stage6a-table         (ws=teardown-fix, d3+)  child of teardown-lead-2 (ws=teardown-fix) ← same
```

**Every one of the ~150 divergences in the whole history happens at a "child of a top"
edge.** Every deeper descendant — and some chains go 4-5 levels deep, e.g.
`workspace-model-lead → wm-model → store-split`/`fork-rule`/`join-workspace` — inherits its
ancestor's workspace unchanged. Not one row in this store's history shows an agent whose
workspace differs from its parent's *without* that parent being a top. That means the
"explicit `--workspace` join elsewhere in the tree" case the task worried about (which
really would scatter one workspace's agents non-contiguously, and really would defeat
indentation) is a real code path (`broker.py:3091-3093`, `join_workspace` at
`broker.py:1259`) but has **never actually been exercised** in this repo's history. It's a
theoretical risk, not an observed one.

## Ordering: does grouping fight the tree?

No, for the reason above: a workspace boundary can only open where a group boundary
(depth ≤ 1) already opens, so "group by workspace" and "walk the tree" produce the *same*
row order today, given the fork rule holds. Only the never-yet-used `--workspace` join path
could break this — an agent placed by name into a workspace three hops away from its
parent would show up in the tree at its parent's position but belong, workspace-wise, to a
group already closed higher up the screen. Nothing currently defends against that; nothing
has ever needed to.

## The cost of an indicator

`board.layout`'s row is one fixed-width prefix — `glyph label state age` — plus whatever
of `detail_bits` fits after it, lowest priority first (marker, then mail, then task/summary
tail — `board.py:281-306`). At 67 columns there is usually room for exactly one detail bit.
A dedicated WORKSPACE column (as `sb status`'s wide table already has) would cost
`max(len(workspace name))` columns *on every row*, competing directly with the state word,
the age, and the one detail bit the row already fights for. Given the finding above — that
the workspace name equals the row's own label at the one row that would make it new
information, and is silently inherited (and already indented under) at every row below
that — this is width spent to redraw information already on screen.

## Designs considered

**A — Workspace column, always shown** (what `sb status`'s wide table already does):

```
 ● board-fix          idle       1m
 ● researcher-22 done      1h12  researcher-22
 ● researcher-23 done      37m   researcher-23
 ◐ worker-25     blocked   22m   worker-25      ← BLOCKED closed your righ…
 ● worker-28     done       1m   worker-28
```
Cost: a whole column, ~13 more chars at depth 1 in this fleet — and it says nothing the
label doesn't already say. Rejected: pure redundancy in the observed-common case, and it
directly steals width from the marker/mail/task tail that the row already can't fully show.

**B — Colour bar / glyph in the gutter, one per workspace:**
```
 ▏● board-fix
 ▐● researcher-22  done      1h12
 ▐● researcher-23  done      37m
 ▌● worker-25      blocked   22m   ← BLOCKED closed your righ…
```
Cost: 1-2 columns, cheap. But a terminal has ~6-8 reliably distinct colours and this fleet
alone has run 90+ concurrent workspaces — the bar would recycle colours within one screen
and imply a false distinction (two different-coloured-but-actually-identical groups, or
worse, two workspaces that happen to land on the same colour reading as one). Rejected:
colour is the wrong encoding for an unbounded-cardinality label; `_starts_group`'s blank
line already encodes "boundary here" without needing to *distinguish* which group, which is
the only thing colour would add and the thing it does worst.

**C — Mark only the rows whose workspace differs from their own depth-1 ancestor's**
(nothing drawn in the overwhelmingly common case; a short tag only on the rare divergent
row):
```
 ● board-fix          idle       1m
   researcher-22  done      1h12
   researcher-23  done      37m
   worker-25      blocked   22m   ← BLOCKED closed your righ…
     ↳ sub-agent   working    4m   [ws: teardown-fix]     ← only if it diverges
```
Cost: near zero on the common path (the `if ws != ancestor_ws` check costs nothing to
compute, since `status.collect` already returns `workspace` per row; drawing costs a detail
bit only when true). This is the one design that adds information rather than restating it,
and it's cheap because the case it lights up has never yet happened in this repo — meaning
it would sit dark on every real screen today, and immediately flag the one shape of tree
`_starts_group`'s depth-based grouping doesn't already handle correctly.

## Recommended

**Design C, and only if you actually want to defend against the join case — otherwise
nothing.** The one reason that decides it: the tree's existing shape (contiguous DFS +
`_starts_group`'s depth-≤1 breaks) already delivers ordering and visual grouping by
workspace, for free, in every example this repo's history contains; the only thing left to
add is a safety net for the one divergence path (`--workspace` join to an existing,
different workspace) that the code allows but nobody has used. That's worth a few lines
guarded by `workspace != <depth-1 ancestor's workspace>` — genuinely small, genuinely not
speculative since the code path is real — but it is not urgent, and a plain workspace
column (Design A) or colour bar (Design B) would be adding UI weight to solve a problem the
tree doesn't currently have.

If Andrew's actual itch is "I want to see which branch/worktree an agent is in without
`sb inspect`-ing it," that's better served by putting the workspace name in `sb inspect`'s
detail view (which already has the room) than by spending board width on every row.

## Not prototyped

I did not touch `scripts/board_mockup.py`. The investigation's own conclusion — the tree
already groups by workspace, the one open gap is a defensive check for a path nobody
exercises — isn't a "one design is obviously right and small" case in the sense the task
meant (a UI feature to build); the small thing is a guard clause, not a rendering change
worth prototyping speculatively in a file another agent may be actively iterating on
(`worker-28`, last commit `93705b0` at the time I checked).

## Sources checked directly

`switchboard/broker.py` (`delegate`, `mints_space`, `has_worktree`, `join_workspace`,
`_fork_for`, the workspace comment block at the top), `switchboard/status.py` (`_tree`,
`collect`, `AgentStatus`), `switchboard/board.py` (`layout`, `_starts_group`, `detail_bits`,
`glyph`), `switchboard/cli.py` (`workspace` subcommands), the live store at
`.git/agentflow/state.db` (361 agent rows, full history), `git worktree list`, `sb status`
and `sb status --json` on the live fleet, and `notes/board-inventory.md` on branch
`researcher-30` for the row-field/width reference.
