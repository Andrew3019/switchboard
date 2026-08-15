# A dispatcher can be adopted as a repo's group parent — proved live, and the fix is in herdr

Written on branch `worker-27`, on top of `worker-26`. Everything here was checked against
code and reproduced against the live herdr (0.8.0), not inferred. The two investigation
notes this builds on (`researcher-29:notes/dispatcher-home-and-space.md`,
`researcher-17:notes/recruiting-space-followup.md`) were treated as untrusted; where this
note repeats them it is because the claim was re-checked here.

## 1. What was proved, live

The mechanism, in one line: herdr adopts a repo group's parent by taking the **first**
already-open workspace whose cwd resolves to that repo, the moment the repo's first
worktree agent appears — and a dispatcher's workspace qualifies.

- `find_parent_workspace_by_key` (`/Users/andrew/Code/herdr/src/app/api/worktrees.rs:427`)
  is a `Vec::position` over all workspaces, matching either an already-stamped
  `worktree_space` **or** a live `git_space()` (the cwd-derived
  `cached_git_space`, `src/workspace.rs:189`). First index wins, whichever branch matched.
- `ensure_source_parent_membership` (`worktrees.rs:380`) then **stamps**
  `worktree_space` onto that workspace — permanently. It runs on every worktree
  create/open.
- A dispatcher's home is a plain `herdr workspace create --cwd <repo>`
  (`switchboard/herdr.py:373`, called from `Broker._top`, `broker.py:1001`), so it has a
  `git_space` for the repo and is a candidate like any other pane.

**Reproduction** (isolated `git clone` of this repo in a scratch dir, driving the live
herdr with exactly the two calls switchboard issues; no agents spawned, everything torn
down afterwards):

1. `herdr workspace create --label sbtop27 --cwd <clone> --no-focus` → workspace `w1CF`,
   **no `worktree` block**. This is byte-for-byte what `sb start` issues for a dispatcher.
2. `herdr worktree create --branch probe27 --base origin/main --no-focus --cwd <clone>` →
   the first worktree child, byte-for-byte what `sb delegate` issues.
3. `herdr workspace get w1CF` → **now carries** `worktree: {repo_key: <clone>/.git,
   is_linked_worktree: false, ...}`.

The dispatcher became the repo's group parent. Not "might" — observed.

Corroboration from the live store, unprompted: workspace `sbtop9f2` (`w1BT`) — another
agent's leftover clone dispatcher, created by a real `sb start` — is stamped with a
`worktree` block for its clone's repo key, with a linked worktree `worker-1` nested under
it. The full switchboard path produces the same outcome as the reproduction above.

### The two cases the task asked about

Both tested in the same run:

- **Two dispatchers on one repo.** The second one (`sbtop27b`) stayed unstamped after a
  further worktree child was created. The first dispatcher already holds the membership
  and sits earlier in the list, so it keeps winning. Result: one dispatcher silently doing
  double duty as "the repo space", a second dispatcher standing alone next to it — not the
  model.
- **Dispatcher started outside a git checkout.** `sbtopNG` (cwd = a plain scratch dir)
  never got a `worktree` block and cannot: `git_space_metadata` returns `None`, so it is
  not a candidate at all. This case is already correct, and stays correct under any fix.

## 2. Why the fix is not on switchboard's side

Eligibility is decided entirely by fields herdr derives for itself from a workspace's cwd.
Switchboard has no way to say "not me":

- `workspace create` takes `cwd`, `label`, `env`, `focus` and nothing else
  (`src/api/schema/workspaces.rs:8`, `src/cli/workspace.rs:41`). There is no group,
  space, or opt-out parameter to pass.
- `workspace report-metadata` sets display tokens, not membership.
- The dispatcher's cwd cannot be moved off the repo: Andrew has confirmed a dispatcher's
  home is the directory `sb start` was run from, and `_refuse_outside_main_checkout`
  (`broker.py:899`) pins that to the main checkout.

The one lever switchboard does have is **ordering** — make sure some non-dispatcher
workspace for the repo exists, and sits earlier in the list, before the dispatcher's is
created. I did not build it, deliberately:

- It is not ineligibility. Close that anchor pane and the dispatcher is adopted on the
  next worktree child. The task asked for a demonstration that adoption *cannot* happen;
  an ordering trick cannot give one.
- It re-implements in code the accident we are removing — "a human pane happened to be
  open first" becomes "switchboard opened a pane first".
- It would create an idle pane per repo that nobody asked for, and would misfire on any
  repo that already has a dispatcher open (the ensure call would adopt *that* dispatcher).

So: no switchboard code change for this. Change 1 ships as this note.

## 3. The herdr change, sized

Separate repo, separate branch — not started here, because proving it live means building
herdr from a cold `target/` and replacing the server the live fleet is currently running
on. That is not a change to make underneath a running fleet.

Three edits, all small:

1. `WorkspaceCreateParams` (`src/api/schema/workspaces.rs:8`) gains a bool, e.g.
   `standalone` — plus the `--standalone` flag in `src/cli/workspace.rs:41`'s arg loop and
   its usage line.
2. `Workspace` (`src/workspace.rs`) persists it alongside `cached_git_space`.
3. `find_parent_workspace_by_key` (`src/app/api/worktrees.rs:427`) skips workspaces
   carrying it. Note it must skip on **both** arms of the `||`, not just the `git_space`
   one, or a workspace stamped before the flag existed keeps winning.

Switchboard's side is then one flag in `Herdr.create_workspace` (`herdr.py:373`) — but it
cannot land before a herdr release carries the flag, because the current herdr CLI exits 2
on an unknown option and that would break `sb start` outright.

Worth deciding at the same time: what happens to workspaces already stamped wrongly (the
live `sbtop9f2` shape). Nothing un-stamps a workspace today, so a fix is forward-looking
only unless herdr also learns to drop a membership.

## 4. Cross-repo dispatch (change 2)

Built, and deliberately small: `defaults/roles/dispatcher.md` now carries a stopping rule.
A dispatcher that notices work belongs in another repo does not dispatch and does not
guess — it writes the question in its chat and calls `sb block`, and starts nothing until
answered. Two tests in `tests/test_roles.py` pin it.

**What was NOT built, and why.** "Root a child in another repo" is not a modest change:

- The store is per repo (`<repo>/.git/agentflow/state.db`, `store.repo_root`). An agent in
  another repo lives in a different store, so parentage, `sb tell`, `sb status`, `sb board`
  and cleanup all stop crossing to it. That is a multi-store fleet, not a flag.
- DESIGN-TRUTH already forecloses the shape anyway: another top's entire tree is invisible
  across the boundary, and only a human may create a top (`sb start` is refused for
  agents, `cli._agent_caller`). So a cross-repo child could not report back to the
  dispatcher that asked for it even if it could be spawned.

So the honest answer to "that repo then gets set up and gets its own space" is: Andrew runs
`sb init` and `sb start` in it, and it becomes its own tree. The prompt says exactly that
rather than implying a capability that does not exist.

**Note the collision with change 1:** a fresh repo set up this way has no human pane open
on it, so its brand-new dispatcher is precisely the case that gets adopted as the repo's
group parent. Change 2's happy path walks straight into change 1's bug.

## 5. DESIGN-TRUTH

Nothing here makes an entry stale. Worth flagging instead that the model this work is built
on — one space per repo plus one space per dispatcher, and a dispatcher's home being the
directory `sb start` was run from — is confirmed in Andrew's task brief and appears nowhere
in `DESIGN-TRUTH.md`. Someone with the authority to add entries may want to.

## 6. Unproven

- **Behaviour of the new prompt.** The text is proved delivered — it renders as one flat
  3071-character line in `roles.load()["dispatcher"].prompt`, which `Broker.delegate`
  appends verbatim (`broker.py:3138`). Whether a dispatcher facing a real cross-repo task
  actually stops and blocks is not testable here, and was not observed.
- **The herdr fix.** Described, not written and not run.
- Nothing was tested about un-stamping an already-adopted workspace.
