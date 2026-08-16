# worktree-model — findings (draft, being extended)

Grounded in code at HEAD (`cafc7c8`) of `/Users/andrew/.herdr/worktrees/switchboard/worktree-model`,
which mirrors `/Users/andrew/Code/switchboard`. All citations verified by direct read unless
marked "per subagent read" (a parallel deep-read of broker.py, cross-checked against comments
per the untrusted-docs rule).

## 1. Creation

**Who creates a worktree, and on what rule.**

The only fork rule is `Broker.mints_space` (`switchboard/broker.py:2795-2812`):

```
if agent == HUMAN: return True
row = store.get_agent(...)
if row is None: return True   # unknown caller, no space to lend
return bool(_column(row, "is_top"))
```

`is_top` is a one-way stamp written only by `_top` (`sb start`, `broker.py:1116`) and
backfilled historically as `parent IS NULL AND branch IS NULL` (`store.py:611`). Nothing else
ever sets it (`store.py:158,171,979-1053` — `is_top` only appears as a column and as a
parameter threaded from `_top`/`delegate`).

`delegate()` (`broker.py:3247-3325`) checks `mints_space(me)` **only on the inherited-workspace
path** (no explicit `--workspace` given): if true, it calls `_fork_for` (`broker.py:3118`),
which creates a brand-new git worktree + herdr workspace, branch named for the new agent.
If false, the child is a tab in the caller's existing space/worktree/branch — full stop.

So: **worktree-or-shared is decided entirely by whether the direct caller is a top** (only
ever a dispatcher spawned by `sb start`), never by role, never by "does this agent write",
never by a request the agent itself can make. A `researcher` or `worker` spawned directly by
a top gets an isolated worktree; the same role spawned by a lead shares the lead's worktree
unconditionally. This is a comment-documented, deliberate design (`broker.py:3290-3310`:
"Role-agnostic... 'it will not write' is a claim about the future"), matching DESIGN-TRUTH's
"Not every level gets a worktree of its own" and the fallback named there — "a lead choosing
isolated worktrees for a particular fan-out... it is not built and is not proposed"
(DESIGN-TRUTH.md:299-301).

**What happens when a shared worktree should have been split.** There is no detection or
guard at all. `broker.py:284-302` / DESIGN-TRUTH is explicit: "no collision between siblings
editing the same file has ever been observed... nothing prevents one." The only mitigation is
social/prompt-level — "A lead's children share its worktree, so the lead assigns disjoint
files and serialises anything that overlaps" (DESIGN-TRUTH.md:284-285) — enforced by nothing
in code. Concurrent writers, conflicting edits, and stale reads inside one shared worktree are
all possible and structurally unguarded; the design's own answer is "this is accepted."

## 2. Lifecycle

**Creation** — `_fork_for` (`broker.py:3118`, called from `delegate`, `broker.py:3319`):
mints a new branch named for the child agent, a new herdr workspace, a new git worktree via
`_call_adapter("create_worktree", ...)` (`broker.py:2485`), serialized by a per-repo
`_fork_lock` (`broker.py:2507-2530`) so concurrent spawns don't race `git worktree add`.

**Reuse / joining** — `sb delegate --workspace <name>` or a lead's own spawns land in the
existing worktree by name; resolved through `_attach_workspace` (`broker.py:2449` area) and
`_open_worktree` (`broker.py:2643`) which attaches to an *already-existing* checkout (never
mints a second one over the same directory — git forbids two worktrees on one checkout,
`broker.py:2646-2648`).

**Restore** — `Broker.restore` (`broker.py:4569` area). Brings a *closed agent* back into its
recorded worktree, provided: the agent has a `session_id`, it isn't already alive, its
workspace isn't mid-teardown (`_refuse_retiring`), and — critically — **the checkout directory
still exists on disk** (`broker.py:4611-4620`: `if not Path(where).is_dir(): raise ValueError`).
Once the worktree is deleted, restore is permanently gone for every agent that worked there —
this is DESIGN-TRUTH's "`sb restore` is gone if the worktree is gone... the push is the
recovery path for the work, not restore" (DESIGN-TRUTH.md:437-439), and the code enforces
exactly that boundary, no more and no less.

**Abandonment / crash handling** — no worktree-level detection exists. What exists is
agent-level: the reconciler (`broker.py:5339`, `reconcile()`) pings idle/stalled agents but
never touches worktrees or calls cleanup. Separately, `given_up_on` (`broker.py:4005-4082`,
inside `cleanup`) recognizes a row switchboard's own turn-tracking gave up on (a crashed
session that never reported an end) and treats it as eligible for closing **as an agent row**
— this is what lets `sb cleanup` reclaim a crashed agent's pane. But nothing walks disk for
worktrees with no live agent and no row at all; an orphan checkout git can see but the store
never recorded is only ever surfaced passively, in `sb workspace list`'s "git"-sourced rows
(`broker.py:1517-1522`), never acted on automatically.

**Cleanup / removal** — `Broker.cleanup()` (`broker.py:3874-4295`), invoked *only* by
`sb cleanup` (`cli.py:1076`) — nothing else in the codebase calls it (verified: only call site
of `.cleanup(` outside its own definition is `cli.py:1076`). It:

1. Closes agents whose state is `done`/`failed`-reconfirmed, or whose turn switchboard gave
   up on (never anything still `working`/`blocked`, without `--force`).
2. Then, as of the block at `broker.py:4200-4295` (`_close_empty_spaces`), retires and
   **deletes the worktree** of any space whose every agent just got closed by that same
   sweep — this is the "and deletes the worktree if everything else is closed too" behavior
   DESIGN-TRUTH names, and the code comment (`broker.py:4200-4203`) states this is a
   *newly-added* trigger: "not one workspace in this repo's history carried `retired_at`,
   because `workspace_close`'s only caller in the package was the CLI verb a person types by
   hand."
3. The deletion path (`_space_ready` → `_gate`, `_inventory_gate`, `_records_gate`,
   `broker.py:4448-4492`) gates ONLY on: (a) no unfinished agent rows under the checkout, (b)
   no live OS processes in the directory, (c) git sees no dirty/untracked files, (d) unknown
   *ignored* files require `--yes` confirmation (interactively; a sweep never asks, so ignored
   content silently holds the space open, `broker.py:4451-4453`). **There is no check for
   whether the branch is merged, pushed, or has an open PR** — `_space_ready`'s own docstring
   says so explicitly (`broker.py:4451-4454`): "What a clean, committed, *unmerged* branch
   does NOT do is hold it... aggressive cleanup destroys `sb restore` and that is accepted."
4. Branch deletion uses `git branch -d` (never `-D`) inside `_finish` (`broker.py:1938`): an
   unmerged branch simply fails to delete and is left behind, orphaned, with its worktree
   already gone. Its commits survive only in the reflog and on the branch ref itself (if not
   deleted) — recoverable by hand, not through any `sb` command.

**What is left behind / orphaned forever:**
- An unmerged/unpushed branch whose worktree got swept: branch ref survives (`-d` refused it),
  its worktree directory does not, and `sb restore` is permanently unavailable for anything
  that ran there.
- Ignored-but-real files (e.g. an actual `.env`, not switchboard's own furniture) block an
  automatic sweep silently rather than orphaning — `_inventory_gate` refuses without `--yes`
  during a sweep, so these are safe but require a human to notice and run `sb workspace close
  <name> --yes` by hand.
- A bare space (dispatcher's own, no checkout) is *always* skipped by `_close_empty_spaces`
  (`broker.py:4386-4388`) — never deleted by cleanup, only ever by the human via `sb workspace
  close`.

**Merged-PR interaction** — none found anywhere in `broker.py` or `cli.py`. There is no code
that checks GitHub/git-remote merge status of a branch and reacts to it. The only
merge-adjacent signal in the whole codebase is informational: `sb workspace list`'s `unmerged`
field (`broker.py:1563-1566`, built from `_branch_facts()`), shown to a human deciding whether
`sb workspace close` is safe — it is not consulted by `cleanup()`'s automatic sweep at all.

## 3. Gap analysis against Andrew's brief (section 3)

**(a) "Worktrees creatable on demand — no need for write agents to justify one."**
**Not done.** Creation is gated solely on `is_top` (§1). A lead cannot request an isolated
worktree for one child needing a genuine split — no command or code path exists for it.
DESIGN-TRUTH names this exact fallback as "not built and not proposed"
(DESIGN-TRUTH.md:299-301). This is the opposite framing of what's in code today anyway: the
current rule was never about "does this agent write" — it's about tree position (top vs
not-top) — so there's no "justify a worktree" gate to remove; there's a *complete absence* of
any on-demand path outside the top-spawns-a-child-of-a-dispatcher shape.

**(b) "Worktrees cleaned when merged."**
**Not done, and structurally the opposite in one respect.** No merge check exists in the
automatic path at all (§2, point 3-4). Worse for the stated intent: an *unmerged* branch's
worktree is deleted just as readily as a merged one, the instant its agents are all closed and
the tree is clean — merge status has zero bearing on whether the directory survives. Only the
branch *ref* gets a weak, accidental protection (`-d` refuses unmerged), and only after the
worktree — the actually recoverable, editable copy — is already gone.

**(c) "...when all agents on it are closed (abandoned)."**
**Done**, and is in fact the *only* trigger that exists. `_close_empty_spaces` deletes a
worktree exactly when every agent in its space has been closed by the same `cleanup` sweep
(§2, point 2). This is the one property of Andrew's wishlist the code already implements
faithfully — though it's manually triggered (`sb cleanup`), never automatic (no cron/reconciler
calls it).

**(d) "...when it holds only doc/audit artifacts that give no benefit after a week."**
**Not done — no such concept exists anywhere.** No file-content classification, no
staleness/age-based logic of any kind touches worktree cleanup. `_inventory_gate` only
distinguishes git-tracked-dirty vs git-ignored files, for a totally different purpose (loss
prevention on delete, not "is this content worth keeping"). Nothing reads commit content, diff
size, or file types to decide a worktree is "just docs."

**(e) "Worktrees persist only as long as agents on them do."**
**Mostly matches the code's actual behavior** — see (c). The one place it diverges: a
worktree with zero live agents but *dirty* git state (uncommitted work) is correctly held open
by `_inventory_gate` (good — it won't silently eat uncommitted work). But a worktree with zero
live agents, clean git state, and an unpushed, unmerged, *fully committed* branch is deleted
exactly as fast as a merged one — so "persists only as long as agents do" is true, but it
overshoots what Andrew describes in (f) below: nothing stands between "agents are gone" and
"directory destroyed" to check the work was actually saved anywhere durable first.

**(f) "Anything worth keeping longer gets pushed as a PR, then removed / restorable from
origin."**
**Not enforced at all.** No code path checks `git log @{u}..HEAD` / any push status before
`_deregister` removes a worktree. The design intent ("Work is usually pushed before its
worktree is deleted", DESIGN-TRUTH.md:388-389) is a **protocol convention** — an instruction to
agents in their spawn prompt — not a gate broker.py enforces. If an agent forgets, or is closed
by a sweep before it pushes, the work is gone beyond the reflog on whoever's local machine
still has it (which for these worktrees is nobody's, since the worktree itself is what's
deleted). This is the sharpest gap: the "restorable from origin" half of Andrew's model
requires push to happen before cleanup can safely run, and nothing ties those two together.

## Summary table

| Desired property | Status | What stands in the way |
|---|---|---|
| (a) on-demand creation, no write-justification | Not built | Fork rule keyed to `is_top` only; no request path for a lead/non-top to mint an isolated worktree |
| (b) cleaned when merged | Not built | No merge-status check anywhere in `cleanup()`; unmerged and merged branches are deleted identically |
| (c) cleaned when all agents closed | **Built** | `_close_empty_spaces`, triggered only by explicit `sb cleanup` |
| (d) cleaned when doc/audit-only & stale (~1wk) | Not built | No content classification, no age-based logic exists |
| (e) persists only as long as agents do | Matches, with one gap | Clean+agentless worktrees die regardless of push/merge state — no floor under "gone" |
| (f) kept-longer work goes through a pushed PR first | Not enforced | Push-before-delete is a prompt convention only; no code gate ties cleanup to push status |

## Additional citations (cross-checked by a second independent read of broker.py)

- `_fork_for` (creation): `broker.py:3119-3186`. Branch = child's own name; guards only
  branch-name collision (`BranchTaken`) and a mid-teardown space (`_refuse_retiring`) — no
  file/content awareness at all.
- `_attach_workspace` (open-or-create join): `broker.py:2447` area — if the named branch is
  already checked out somewhere, attaches rather than minting a second worktree (git itself
  refuses two checkouts of one branch).
- `_open_worktree`: `broker.py:2643`.
- `_fork_lock`: `broker.py:~2508-2530`, serializes concurrent `git worktree add` calls
  repo-wide to avoid a documented race on branching from `origin/main`.
- `_close_empty_spaces`: `broker.py:4364-4423` (this investigation's earlier line numbers for
  the same block, `4200-4295`, were off by a version drift between the two reads — same
  function, confirmed identical logic both times).
- `_deregister` (`git worktree remove`): `broker.py:2403-2445`.
- Local `git branch --merged <base>` (`_branch_facts`, `broker.py:~1618,1633`) is used
  **only** to annotate `sb workspace list`'s informational `unmerged` field
  (`cli.py:~1242`) for a human — never consulted by the automatic `cleanup()` sweep. This is
  a second, independent confirmation of the central finding in gap (b).
- No scheduled/background sweep exists anywhere: `cleanup()` and `workspace_close()` only
  run synchronously off a typed `sb cleanup` / `sb workspace close`. The reconciler
  (`broker.py:5339`) pings idle *agents* to get them to report done/blocked; it never calls
  `cleanup()` or touches a worktree. So even the one property the code does implement —
  "cleaned when all agents are closed" — never fires on its own; it fires only the next time
  someone happens to run `sb cleanup`.
- One versioning note: `broker.py`'s own comment at the top of `_close_empty_spaces`
  (`~4371-4372`) states this auto-delete-worktree-on-last-agent-closed behavior is a
  relatively recent addition — "not one workspace in this repo's history carried
  `retired_at`" before it, because the only caller used to be the human-typed
  `sb workspace close`. Worth flagging since it is the one property from Andrew's wishlist
  that already exists in code.
