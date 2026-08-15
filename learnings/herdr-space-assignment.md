# herdr space assignment — investigation

Read-only. Nothing edited except this file. Grounded in the code at
`switchboard/herdr.py`, `switchboard/broker.py`, `switchboard/cli.py`,
`defaults/settings.toml`, `DESIGN-TRUTH.md`, and a read-only query of this
checkout's own store (`/Users/andrew/Code/switchboard/.git/agentflow/state.db`).

## 1. What the code actually does today

There are exactly two ways a herdr *space* (workspace) comes into being, and both
create a brand-new one — neither ever looks up or attaches to an existing herdr
workspace by its display label.

- **`Herdr.create_workspace(label, ...)`** (`switchboard/herdr.py:373-384`) — calls
  `herdr workspace create --label <label>`. Used only from `Broker._top`
  (`switchboard/broker.py:1001`, the handler for `sb start`), which is the *only*
  path that mints a bare space and stamps the new agent `is_top=1`
  (`switchboard/broker.py:1012-1020`, and confirmed as the sole path in
  `DESIGN-TRUTH.md:42-47`). The label is always the new orchestrator's own agent
  **name** — `sb start`'s `--name`, or the auto-picked `main`, `main-2`, `main-3`, …
  (`Broker._next_top_name`, `switchboard/broker.py:1044-1063`, driven by
  `vocabulary.main_name = "main"` in `defaults/settings.toml:98`). There is no
  "topic" or "project" name anywhere in this path — only the orchestrator's own
  identity.

- **`Herdr.create_worktree(branch, ...)`** (`switchboard/herdr.py:425-445`) — calls
  `herdr worktree create --branch <name> --base <base>`, and per the comment at
  `herdr.py:433` "already opens the checkout as a workspace and groups it with the
  parent repo." This is reached from `Broker._fork_for`
  (`switchboard/broker.py:2904-2962`), whose branch/workspace name is **always the
  new agent's own name** (`herdr.py:2905`: "the branch is the agent's NAME... no
  prefix and no suffix"). `_fork_for` runs `cwd=str(self.repo)` — the repo this `sb`
  process is standing in — so every worktree-space it creates is grouped, by herdr
  itself, under whatever herdr already calls the workspace over that repo's primary
  checkout.

**The fork rule** (`Broker.delegate`, `switchboard/broker.py:3069-3104`,
`Broker.mints_space`, `switchboard/broker.py:2581-2598`): a spawn mints a new
space+worktree of its own only when the caller is a **top** (`is_top` stamp,
set only by `_top`) or is the **human** or is an unrecognised caller. Everyone
else's spawn — an ordinary orchestrator delegating, a workspace lead delegating —
gets a **tab inside the workspace it already inherited** (`Broker._tab_for`,
`switchboard/broker.py:2708-2747`), via `Broker._parent_workspace_id`
(`switchboard/broker.py:2666-2706`), which resolves "where does this child belong"
purely by asking **where the live parent already is** (recorded `workspace_id` →
herdr's live answer for the parent's pane → the `HERDR_WORKSPACE_ID` env var → last,
a name-based guess it explicitly does not trust enough to record). None of these
four tiers ever consults a human-chosen label.

Net effect, confirmed against this checkout's own store:
- Bare top orchestrators are `main`, `main-2` … `main-15` — one bare herdr space
  each, named for themselves (`select name, checkout from workspaces where checkout
  is null` → only `main*` rows).
- Every worktree-backed agent (worker, researcher, sub-orchestrator, lead) has a
  **workspace named after itself**, e.g. `researcher-16`, `worker-23` — never a
  shared name. Confirmed: `select distinct workspace from agents` lists dozens of
  per-agent names and nothing generic.
- No workspace or agent row in this store is named `switchboard` or `recruiting`
  anywhere, ever.

So "descendants land in a `switchboard` space" is not something switchboard's code
asks for or names. The most consistent explanation, from the `herdr.py:433` comment,
is that herdr's own UI **groups** every worktree-space under the workspace already
covering that repo's primary checkout — and this repo's own primary-checkout
directory is literally named `switchboard`, so herdr's default label for that one
workspace is `switchboard`. Everything forked with `--cwd` pointing at this repo
therefore visually nests under it in herdr's sidebar, independent of who spawned it
or whether it is a top. **I could not verify this last step by driving herdr's UI
myself** (read-only investigation, no herdr commands run) — it is inferred from the
code comment and the observed naming, not directly observed.

## 2. Why `recruiting` did not capture anything

Two independent reasons, both borne out by the code and by the empty store query:

1. **Nothing in the switchboard codebase ever resolves a workspace by a
   human-supplied label.** `create_workspace` and `create_worktree` are always
   *create*, never *find-or-attach-by-label* — read the full bodies at
   `herdr.py:373-384` and `herdr.py:425-445`; neither takes nor checks an existing
   herdr workspace id passed in from outside. The only *lookup* functions
   (`Broker._workspace_id`, `switchboard/broker.py:2633-2664`, and
   `Broker._attach_workspace`, `switchboard/broker.py:2233-2291`) resolve a name
   against **switchboard's own store** (`store.known_workspace`,
   `store.workspace_branch`) or against a **git branch/worktree** of that same
   name (`_checkout_of`, `herdr worktree open --branch <name>`) — never against an
   arbitrary herdr workspace's display label. A space Andrew created directly
   through herdr (not through `sb`) has no row in switchboard's store and, being
   bare, has no branch/worktree either, so both lookup paths come up empty for it.
2. **Space names are always derived from the agent's own name/branch**, never from
   a task topic (`_fork_for`'s "the branch is the agent's NAME", `broker.py:2905`,
   and `_top`'s `create_workspace(name, ...)`, `broker.py:1001`, where `name` is
   the orchestrator's own `--name`). Confirmed empirically: this store has no agent
   or workspace ever named `recruiting` at all — recruiting-related agents (if run
   through this same switchboard codebase, possibly in a different repo/checkout I
   don't have access to from here) would have landed wherever their actual parent
   already was, under whatever name *that* parent had, never under a
   pre-existing `recruiting` label.

**Is there any way for a human to pre-create a space and have agents land in it?**
Not through any mechanism I found. `sb start --name recruiting` would try to
*create* a fresh bare space labelled `recruiting` (and would conflict/refuse if the
name is already recorded as taken — `Broker._name_held_by`, `broker.py:1070-1089` —
but that check is against switchboard's *own* store, not against herdr's live
workspace list, so a herdr-native `recruiting` space it doesn't know about
wouldn't even trigger the refusal; it would just mint an unrelated second
`workspace create --label recruiting` in herdr). `sb delegate --workspace
recruiting` is documented (`cli.py:139-142`) as "join this EXISTING workspace" —
but "existing" there means one **switchboard itself already created and recorded**
(the docstring: "a workspace is opened by a top orchestrator delegating: the
child's `--name` is the workspace's name"), which a directly-herdr-created space
never is.

## 3. Feasibility of nesting descendants under their own top orchestrator instead
   of one flat `switchboard` grouping

This is largely **already the code's behaviour**, and confirmed as the intended
design in `DESIGN-TRUTH.md:56-60` ("only the top ever creates a space: a
sub-orchestrator a lead spawns is a tab in the lead's space, and its whole subtree
stays in that one space"). Concretely, every agent a **top** (or the human)
directly spawns already gets its own dedicated herdr workspace, named for itself
(`_fork_for`) — it is not literally sharing one flat space with everything else.
What is shared is only herdr's own **visual grouping**: every worktree-backed space
forked with `--cwd` on this repo nests under this repo's primary-checkout
workspace in herdr's UI (see part 1) — and that grouping parent happens to be
labelled `switchboard` because that's this repo directory's name, not because of
any policy switchboard enforces.

If what's wanted is each *top-level orchestrator's own subtree* grouped under a
herdr-visible node named for *that orchestrator* rather than for the repo
directory, here is what would have to change and the risks:

- **What would change.** `_fork_for`/`create_worktree` calls `herdr worktree
  create --cwd <repo>` (`broker.py:2952`, `herdr.py:436`) — the `--cwd` is what
  determines which repo's checkout, and hence (per the `herdr.py:433` comment)
  which parent grouping herdr assigns the new workspace to. There is no flag in
  `herdr.py`'s `create_worktree`/`create_workspace`/`open_worktree` to name an
  arbitrary parent-for-grouping directly — grouping is inferred by herdr from the
  repo relationship, not requested. So achieving "grouped under the top
  orchestrator's own space" rather than "grouped under the repo's primary
  checkout" would need either (a) a herdr feature/flag that isn't in this adapter
  today, or (b) restructuring so each top orchestrator's worktree area is treated
  by herdr as its own distinct "repo root" for grouping purposes — unclear from
  this code alone whether herdr's grouping model supports that at all (herdr
  itself is opaque past its CLI; this adapter is "the only module that knows herdr
  exists", `herdr.py:1-11`, and does not expose a grouping-parent option).
- **Rough size.** Small if herdr already exposes a "group under this workspace"
  flag on `worktree create`/`workspace create` that this adapter just isn't
  passing (a few lines in `herdr.py` + `broker.py:2952`). Open-ended if it
  requires a different herdr command shape or isn't supported by herdr's
  workspace model at all — that can't be answered without checking herdr's own
  CLI/API surface, which I did not do (out of scope for a code-only read of this
  repo; herdr's binary was not invoked).
- **The ordering problem the task called out.** `create_workspace`/`create_worktree`
  both happen at the moment the top orchestrator's own space is minted
  (`Broker._top`, `broker.py:1001`), i.e. before the orchestrator has done
  anything — so the top's own name is already known at that point (it's `sb
  start --name X`, or the auto-picked next `main-N`) and is available to use as a
  grouping key immediately. The harder ordering problem would only bite for
  **renames**: `Broker._open_worktree` already has a live bug pattern here — it
  renames a workspace unconditionally when re-opening it, and a documented
  incident (`broker.py:2440-2443`) shows opening `main` clobbered a workspace
  labelled `switchboard` down to `main`. Any scheme that groups children under a
  parent's *current* label would need every rename to also correct every
  descendant's grouping, or a stable id-based grouping key instead of a label —
  which is exactly the same "confirmed vs guessed" id problem
  `_parent_workspace_id` already exists to solve (`broker.py:2666-2706`).
- **Orphans and cleanup.** Not obviously worse than today: `sb workspace close`
  already reasons about orphan checkouts vs. retired workspace rows vs. escaped
  herdr workspaces (`cli.py:269-282`) at the *worktree* level; grouping is purely
  a herdr-UI-display concern layered on top of workspace identity, so retiring a
  top and its subtree would still go through the same per-workspace close/retire
  path it does now — the grouping label would just need to be torn down or
  re-pointed alongside it, which is new surface area but not a new category of
  bug beyond the rename hazard above.

**Bottom line:** the flat single `switchboard` grouping isn't a deliberate design
choice in switchboard's own code — it's a side effect of every worktree fork using
this repo's own directory as `--cwd`, combined with herdr's own (inferred, not
directly observed) habit of grouping child workspaces under the workspace that
already covers that `--cwd`. The "each top gets its own space" half of Andrew's
intended design is already true today. Getting descendants grouped under *their own
orchestrator's* label instead of the repo's would need either an unexplored herdr
grouping flag or a different id-based (not label-based) grouping key to avoid the
same rename hazard already on record in this file (`broker.py:2440-2443`) — genuinely
unknown without checking what herdr itself supports past this adapter's current
calls, which this investigation did not do.
