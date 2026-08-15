# Why a dispatcher gets its own herdr space today, and what its home actually is

Read-only investigation. No source edited. Everything below was checked against code
(switchboard at `/Users/andrew/.herdr/worktrees/switchboard/researcher-29`, herdr at
`/Users/andrew/Code/herdr`) and against the live herdr store via `herdr workspace list`
(read-only CLI call, no agents created/killed). `DESIGN-TRUTH.md` is treated as ground
truth; everything else, including the two "untrusted" notes named in the task, is
verified independently below rather than relied on.

## The one-line answer

The "established" premise in the task — "herdr groups agents by the underlying git
repository they share, computed on the fly" — is **not quite what the code does**, and
that inaccuracy is exactly what resolves the tension. herdr's sidebar/API grouping does
not recompute "which repo is this cwd in" for every workspace on every render. Each
`Workspace` carries an explicit, persisted field,
`worktree_space: Option<WorktreeSpaceMembership>`
(`/Users/andrew/Code/herdr/src/workspace.rs:35-41,191`), and grouping reads *only* that
field — never a live git lookup — at render/API time
(`/Users/andrew/Code/herdr/src/ui/sidebar.rs:341`,
`/Users/andrew/Code/herdr/src/app/creation.rs:507-515`, which is what
`herdr workspace list`'s `"worktree"` key literally is).

That field is written in exactly one production code path: the worktree-open/create API
handlers in `/Users/andrew/Code/herdr/src/app/api/worktrees.rs`. Nothing else in the
non-test codebase ever assigns it — I grepped every `worktree_space = Some(` site
(`grep -rln "worktree_space = Some" src`) and traced each one; all sites outside
`app/api/worktrees.rs` are `#[cfg(test)]` fixtures (`app/git_refresh.rs:380,398`,
`app/mod.rs:4734,4742`, etc.). There is also no periodic job that re-derives it —
`app/git_refresh.rs`'s periodic refresh only touches the *cached* branch/ahead-behind/
label fields, never `worktree_space` (confirmed by reading every non-test fn in that
file).

A `sb start` dispatcher's herdr workspace is created via
`Herdr.create_workspace()` (`switchboard/herdr.py:373-384`), which calls herdr's plain
`workspace create --cwd <path>` — a call that **never touches
`app/api/worktrees.rs`** and therefore never stamps `worktree_space`. Contrast
`Herdr.create_worktree()` / `open_worktree()` (`switchboard/herdr.py:425-466`), which
call `worktree create` / `worktree open` — the only calls that do. The docstring at
`herdr.py:433-434` even says so directly: "Note this already opens the checkout as a
workspace and groups it with the parent repo, so a separate `workspace create` is
unnecessary" — i.e. the two herdr calls are deliberately different in exactly this way,
and switchboard picks the ungrouped one for dispatchers on purpose (see next section for
why).

So: a dispatcher's workspace has no `worktree_space`, herdr's grouping reads only
`worktree_space`, therefore a dispatcher never groups with the repo's space — not
because herdr is examining its cwd and deciding it's different, but because grouping
never looks at its cwd at all once the workspace exists un-stamped.

## Confirmed live, not just in source

`herdr workspace list` (read-only) on the live store right now shows, among others:

- `"switchboard"` (workspace `wZ`) — **has** a `"worktree"` block:
  `checkout_path: /Users/andrew/Code/switchboard`, `repo_key: .../.git`,
  `is_linked_worktree: false`.
- `worker-9`, `reviewer-14`, `worker-24`, `researcher-29`, etc. — each **has** a
  `"worktree"` block with the same `repo_key`, so they render nested under
  `"switchboard"` in the sidebar.
- `main-11`, `main-15`, `board-fix` — **no `"worktree"` key at all** in the JSON. Their
  cwd is the very same `/Users/andrew/Code/switchboard` main checkout, but they carry no
  membership, so they render as their own separate top-level entries — exactly what
  Andrew described seeing.

This matches the source-level story exactly: three bare dispatcher workspaces, all with
the *same underlying git repo* as `switchboard`, none of them grouped with it, because
none of them were ever run through the worktree-open/create path that stamps membership.

## How a bare workspace *can* still end up "adopted" as the repo's parent — and why it hasn't been here

`ensure_source_parent_membership` (`app/api/worktrees.rs:380-405`), run every time a
worktree agent is created, first looks for an *existing* workspace to serve as the
group's parent via `find_parent_workspace_by_key` (`worktrees.rs:427-435`). That lookup
checks two things per candidate, in this order per `Vec::position`'s first-match
semantics: (a) does it already carry `worktree_space` for this repo key, or (b) does its
**live, on-the-fly** `git_space()` (i.e. cwd resolved to a repo, computed fresh — the
"on the fly" mechanism the task's premise describes) match this repo key *and* is it not
itself a linked worktree. Whichever workspace matches first (by position in
`self.state.workspaces`, i.e. creation order) is adopted as parent and gets
`worktree_space` stamped onto it right there (`worktrees.rs:396-399`), if it didn't
already have it.

This is the one place the "computed on the fly" idea from the task brief is real — but
it only fires as a **one-time adoption at worktree-creation time**, on whichever
qualifying workspace happens to sit earliest in the list, never as a continuous
regrouping of everything.

In the live repo, `"switchboard"` (`wZ`) is Andrew's own primary pane, opened first (it
is workspace `#1` in the list), before any dispatcher or worktree agent existed. The
first time any worktree agent was ever spawned for this repo, `wZ` was almost certainly
the first cwd-matching, non-linked candidate found by `find_parent_workspace_by_key`, so
it absorbed the membership and became the repo's permanent group anchor. Once `wZ`
carries `worktree_space`, `find_parent_workspace_by_key`'s first branch (`ws.worktree_space()`
match) resolves to `wZ` on every subsequent worktree creation, so later bare dispatcher
workspaces are never even considered — they're simply never asked.

## Point 3: is this a tension, or a different mechanism?

It's a different mechanism, not a contradiction once traced through — but it is
**fragile**, not a designed guarantee. Nothing in switchboard or herdr enforces "the
first workspace ever opened on a repo is a human's plain pane, not a dispatcher." If it
had been a dispatcher instead (see next section), that dispatcher — not a
switchboard-owned "repo space" — would have been the one adopted as the repo's group
anchor, and it would stop looking like "its own dispatcher space" in the UI from that
point on.

## Point 4: what would have to change for Andrew's stated model to hold as a guarantee

Today: "one space per repo, one space per dispatcher" holds by **circumstance** — Andrew
happens to always have had a plain, non-dispatcher pane open on each repo before any
worktree agent was spawned there, so that pane absorbs the parent-membership role and
dispatchers stay clean. It is not guaranteed by any code path, and I found no code that
special-cases `is_top`/dispatcher workspaces to keep them out of
`find_parent_workspace_by_key`'s candidate search.

If it must hold unconditionally, the smallest fix I can see (not yet designed, no code
change made — this is sizing only): `find_parent_workspace_by_key`'s candidate matching
would need to skip workspaces that are dispatcher homes, so a bare `sb start` workspace
can never be adopted as a repo's group parent. herdr has no concept of "this bare
workspace is a dispatcher" today — that's purely switchboard's `agents.is_top` bit, which
herdr never sees. So this is a two-repo change, not a one-liner:
- herdr would need either a way to mark a workspace as "never adopt me as a group
  parent," or switchboard would need to pre-create/guarantee a plain (non-dispatcher)
  repo-anchor workspace before any dispatcher's `workspace create` call, mimicking what
  Andrew's manual habit currently does by accident.
- Alternatively, accept the current behavior as good enough in practice (it has held so
  far) and only fix it if/when it's actually observed breaking — cheaper, but explicitly
  a "works by habit" state, not a guarantee.

I'm not sizing the actual implementation further than that — it depends on which of
those two directions Andrew wants, which is a design call, not a research one.

## Point 2: what a dispatcher's working directory actually is

Exactly "the directory `sb start` was run from," confirmed at the code level, not
inferred:
- `Broker.__init__`: `self.repo = repo or Path.cwd()` (`switchboard/broker.py:510`) —
  literally the process's cwd when `sb` was invoked.
- `sb start` refuses to run anywhere except the recorded main checkout
  (`Broker._refuse_outside_main_checkout`, `broker.py:899-925`): if `self.repo` (resolved)
  isn't equal to the stored `main_checkout`, it raises rather than proceeding, and the
  error message tells the user to `cd` to the main checkout first. So in practice a
  dispatcher's home is always exactly the repo's main checkout root, never a worktree,
  never an arbitrary subdirectory that merely happens to be inside the repo.
- The dispatcher's herdr workspace is created with `cwd=str(self.repo)`
  (`broker.py:1001`), so herdr's pane genuinely sits in that same directory — it is not a
  separate synthetic location.
- It writes nothing there via switchboard itself beyond `sb`'s own bookkeeping
  (`store.write_config({"main_checkout": ...}, self.repo)`, called from
  `Broker.main_checkout_here` at `broker.py:873`, a different call path than `_top`). The
  documented intent is explicit: "a top-level orchestrator does no writes"
  (`herdr.py:377`, `broker.py:883-884`) — but this is a convention enforced by what the
  dispatcher is told to do, not a technical restriction. Nothing stops a dispatcher's own
  agent process from writing into the main checkout; it shares the exact same directory
  the human's own terminal and every other bare-space pane on that repo use.

## Point 5: known breakage modes

1. **Two dispatchers on the same repo, no prior plain pane.** If a repo's very first
   herdr workspace is a dispatcher (e.g. a fresh repo where `sb start` is the first thing
   ever run, with no human pane opened beforehand), that dispatcher will be adopted as
   the repo's group parent the first time any worktree agent is spawned under it
   (`ensure_source_parent_membership`/`find_parent_workspace_by_key`, as above). A second
   dispatcher started later on the same repo stays ungrouped and separate, so the UI ends
   up with one dispatcher silently doing double duty as "the repo space" and a second,
   genuinely separate dispatcher space next to it — not the clean "one repo space + one
   space per dispatcher" Andrew described. I did not reproduce this live (would require
   creating agents, out of scope for a read-only task) — this is traced from source, not
   observed.
2. **Dispatcher started from a directory that is not a git checkout at all.** herdr's
   `git_space_metadata(cwd)` (used by `git_space()`/`discover_workspace_git_identity`)
   returns `None` for a non-git directory, so such a workspace can never be adopted as
   anyone's parent and never has anything to group with — it just stays its own space
   forever. That's not broken relative to Andrew's model; it's actually the simple case
   the model already describes correctly. Separately, `_refuse_outside_main_checkout`
   (`broker.py:908-911`) explicitly *skips* its "must be the main checkout" check when no
   main checkout is recorded for that path (e.g. `sb init` was never run there) — so
   `sb start` is not blocked in a non-git directory; it will happily create a bare
   dispatcher space there, standing alone, matching the model with no tension.

## What is NOT yet verified

- I did not create or destroy any herdr workspace, agent, or git worktree to directly
  reproduce breakage mode 1 (two dispatchers, first one adopted as repo parent) — the
  task requires read-only, no spawning. The mechanism is traced through source
  (`ensure_source_parent_membership`, `find_parent_workspace_by_key`) with high
  confidence, but the actual UI outcome in that specific scenario is inferred from code,
  not observed live.
- I did not check whether `Vec<Workspace>` ordering (used by `.position()` in
  `find_parent_workspace_by_key`) is strictly creation-order under all conditions
  (e.g. after a workspace close-and-reopen churns indices). The "wZ opened first, so it
  wins" explanation for the live store is very likely but not proven beyond what the
  current live listing shows.
