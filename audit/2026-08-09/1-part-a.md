# Audit A — spawn placement and routing (read-only)

Auditor: `reviewer-1`, under `audit-1`. Workspace `worker-2`
(`/Users/andrew/.herdr/worktrees/switchboard/worker-2`). Nothing was changed; nothing was
spawned. Evidence is source, plus the live store at
`<repo>/.git/agentflow/state.db` read through `switchboard.store`.

Only `DESIGN-TRUTH.md` was treated as authoritative. No other doc is cited as evidence.

## Verdicts

| # | Entry | Verdict |
|---|-------|---------|
| 1 | Starting work — `sb start` = new *bare* space on main, a top orchestrator | **PARTIAL** |
| 2 | Anything that might need code changes → workspace/worktree (+ orchestrator, `<name>-lead`) | **PARTIAL** |
| 3 | Where each spawn lands | **PARTIAL** |
| 4 | `sb delegate` figures out where a spawn lands | **PARTIAL** |
| 5 | The `<name>-lead` naming convention | **SATISFIED** |

Counts: 1 SATISFIED, 4 PARTIAL, 0 BROKEN, 0 UNVERIFIED.

---

## 1. "Starting work." — PARTIAL

**What holds.**

- `sb start` always makes a *new* top: `Broker.start` (`switchboard/broker.py:395-413`)
  calls `_top` with `_next_top_name()`, which never reuses a name
  (`broker.py:509-522`). Reuse only happens with an explicit `--name`.
- The space is **bare**: `_top` calls `self.h.create_workspace(name, cwd=str(self.repo))`
  (`broker.py:474`), and `Herdr.create_workspace` is `workspace create --label`, whose
  docstring and argument list contain no worktree at all (`switchboard/herdr.py:282-293`).
  The top is then spawned with `delegate(..., role=MAIN, workspace=name,
  workspace_id=wsid, cwd=str(self.repo))` (`broker.py:484-486`) — note `branch` is not
  passed, so `agents.branch` stays NULL, which is the store's definition of "no worktree"
  (`Broker.has_worktree`, `broker.py:1026-1040`).
- It is a **top orchestrator**: role `MAIN` = `orchestrator`
  (`defaults/settings.toml:80`), parent NULL because `me == HUMAN`
  (`broker.py:1355`).

Live confirmation — four tops in the store, all with `parent=None`, `branch=None`, each in
its own workspace id:

```
main    parent=None role=orchestrator ws=main    wsid=None branch=None cwd=/Users/andrew/Code/switchboard
main-2  parent=None role=orchestrator ws=main-2  wsid=w0   branch=None cwd=/Users/andrew/Code/switchboard
main-3  parent=None role=orchestrator ws=main-3  wsid=w16  branch=None cwd=/Users/andrew/Code/switchboard
main-4  parent=None role=orchestrator ws=main-4  wsid=w1D  branch=None
```

**What does not hold — "on main".** The space is laid over
`store.worktree_root()`, i.e. *whatever checkout `sb start` was typed in*, not the recorded
main checkout. `cli.py:547` sets `repo = store.worktree_root()` (its own comment says "THIS
worktree, not the main checkout"), `Broker` keeps it as `self.repo`, and `_top` passes it
as the workspace `cwd`. `store.main_checkout()` exists and is recorded by `sb init`
(`store.py:122-129`, written at `broker.py:389`) but is used only by `link_config`
(`broker.py:343`) — never by `start` or by forking.

This is not cosmetic. Every fork runs `create_worktree(..., cwd=str(self.repo))`
(`broker.py:732-733`), and herdr refuses to create a worktree when that cwd is a linked
worktree. Two such failures are in the event log verbatim:

```
fork_failed  acc-kid  [workspace_unavailable] ... {"code":"linked_worktree_source",
  "message":"New and open worktree actions start from the repo parent workspace."}
fork_failed  latency-fork-probe-1786170443  (same error, parent "human")
```

So a `sb start` typed inside a worktree produces a top whose children can never get
worktrees; `_fork_for` swallows the error and returns None (`broker.py:1237-1240`), so the
children spawn silently treeless in the top's bare space. I did not reproduce this end to
end (that needs a real spawn); the two log rows are the same call failing for the same
reason.

**Second, smaller gap.** If `create_workspace` fails, `_top` logs and falls through to a
plain tab in whatever workspace is current (`broker.py:479-486`) — the top then has no
space of its own. Deliberate ("rather than not starting"), but it means "always a new bare
space" is best-effort.

### Gaps
- `sb start` lays the top's bare space over the *current* checkout, not the recorded
  `main_checkout`, so a `sb start` typed in a worktree puts the top in the wrong place.
- Forks inherit that wrong cwd, and herdr refuses `worktree create` from a linked worktree
  (`linked_worktree_source`), so every child of such a top silently gets no worktree.
- `_fork_for` swallows a failed fork (log only) — the child spawns treeless and nothing
  tells the parent.
- A failed `create_workspace` degrades `sb start` to a tab in someone else's space.

---

## 2. "Anything that might need code changes." — PARTIAL

**Worktree part: satisfied, and then some.** THE FORK RULE (`broker.py:1294-1319`) is
`if inherited and not self.has_worktree(me): forked = self._fork_for(name, parent=me)`. It
is role-agnostic by design (comment at `broker.py:1296-1299`), so *every* child of a top —
worker, reviewer, researcher — gets its own worktree, whether or not it will write. That
over-satisfies the entry rather than missing it, and it is deliberate; DESIGN-TRUTH's own
"only a 100%-read-only task skips the worktree" exception is not implemented (out of my
slice, noted only).

Live: `main-4` (bare) → `worker-2` got `branch=worker-2`, `wsid=w1E`, path
`/Users/andrew/.herdr/worktrees/switchboard/worker-2` (event `fork`, id 11655).

**Orchestrator-with-it part: judgement only, and generic.** Nothing in code routes on
"small and clear enough for one agent end to end". The decision lives entirely in the
orchestrator prompt, which says it per part of the parent's own task — "a worker when one
agent can carry it to done, another orchestrator only when that part is itself multi-step"
(`defaults/roles/orchestrator.md:127-131`). That is the *lead's* splitting rule, not the
top's "does this line of work need a lead at all" rule, and the top gets the identical
prompt (one orchestrator role, `settings.toml:76-80`). There is no separate top prompt and
no mechanism differentiating the two — DESIGN-TRUTH already lists that as open.

**`<name>-lead` on this path: absent.** When the top spawns a lead the ordinary way
(`sb delegate --role orchestrator`), the name comes from `_derived_name` /
`_unique_name` and is `orchestrator-1`, `orchestrator-2`, … (`cli.py:461-476`,
`broker.py:1386-1390`). `-lead` is only produced by `sb workspace new` (see §5).

### Gaps
- No prompt tells the top the "small and clear → one bare agent; otherwise a lead" rule; it
  gets the generic per-part splitting paragraph written for a workspace lead.
- The top's route to "workspace + lead" is `sb workspace new`, which no agent is ever told
  exists (see §5), so in practice the top uses `sb delegate` and the lead gets a generic
  `orchestrator-N` name.
- The worktree is unconditional: a read-only child of a top also forks one, so
  DESIGN-TRUTH's read-only exception has no implementation.

---

## 3. "Where each spawn lands." — PARTIAL

Four of the five clauses verified, one flatly unimplemented.

**(a) `sb start` = new bare space + orchestrator** — holds; see §1.

**(b) Top spawns a bare agent = new worktree/space** — holds. Fork rule at
`broker.py:1311`; the top's `has_worktree` is False because its `branch` is NULL.
Live: `main-4` (wsid `w1D`) → `worker-2` (wsid `w1E`, branch `worker-2`).

**(c) Top spawns an orchestrator = same thing** — holds; the fork rule does not read the
role. Live: `main` (bare) → `workspace-model-lead` (wsid `wJ`, branch `workspace-model`);
`main` → `plugins-redesign-lead` (wsid `wH`, branch `plugins-redesign`).

**(d) An orchestrator spawning anything = new tab in the same exact space; the subtree
stays in that one space** — holds. On the inherited path with a parent that has a worktree
there is no fork; the child gets the parent's workspace name and branch
(`broker.py:1284-1292`) and a tab in the parent's workspace id (`_tab_for`,
`broker.py:1133-1161`, via `_parent_workspace_id`, `broker.py:1100-1131`). Live, two levels
deep in both directions:

```
workspace-model-lead  wsid=wJ  branch=workspace-model
  wm-model     (orchestrator) wsid=wJ  branch=workspace-model
    store-split (implementer) wsid=wJ  branch=workspace-model
worker-2 (worker, wsid=w1E, branch=worker-2)
  audit-1    (orchestrator)   wsid=w1E branch=worker-2
    reviewer-1 (me)           wsid=w1E branch=worker-2
```

**(e) "…and that agent cannot spawn other agents" (of a bare agent under the top) — NOT
IMPLEMENTED, and violated in production right now.** There is no capability gate anywhere:
`sb delegate` is registered unconditionally (`cli.py:123-137`), `Broker.delegate` checks
role for nothing but its prompt and model (`broker.py:1279`), and the protocol every agent
receives hands the verb to all of them — "To delegate: `sb delegate "<task>" --role <role>`"
(`defaults/protocol.md:112`). That is deliberate in the protocol's own note: the older "do
not spawn agents of your own" was removed as "flatly wrong for an orchestrator"
(`protocol.md:29-32`), and it was replaced with a rule about *work*, not about capability.

The audit you are reading is the violation: `worker-2` is a plain `worker` forked by the
top `main-4`, and it spawned `audit-1` (orchestrator, event id 16978), which spawned
`reviewer-1/2/3`. Three levels below a bare agent that DESIGN-TRUTH says cannot spawn at
all. (The space rule survived it — the whole subtree stayed in `w1E` — so what broke is the
capability clause, not the placement clause.)

**(f) "Only the top ever creates a space" — bypassable.** `sb workspace new` creates a
herdr workspace, a git worktree and a lead, and has no caller check at all: `cli.py:844-848`
dispatches straight into `Broker.workspace_new` (`broker.py:580-647`), which takes `me` only
to attribute the spawn. Any agent at any depth may call it. It is also the only path that
produces a `-lead` name, so the one command that implements §5 is the same command that
breaks this clause.

Also: because the fork rule keys on "parent has no worktree" rather than "parent is the
top", any *non-top* agent that ends up without a worktree — e.g. one whose fork failed as in
§1 — will itself create new spaces for its children. Read from `broker.py:1311` +
`_fork_for`; I found no live instance of this (the six treeless non-top rows in the store
have no children, and predate the `branch` column being populated), so this one is inferred
from code, not observed.

### Gaps
- Nothing prevents a bare agent under the top from spawning: no role/capability check in
  `delegate`, and `protocol.md` hands `sb delegate` to every agent regardless of role.
- `sb workspace new` creates a space and is callable by any agent at any depth — "only the
  top ever creates a space" has no enforcement.
- The fork rule keys on "parent has no worktree", not "parent is the top", so any treeless
  agent (e.g. after a failed fork) starts creating spaces too.

---

## 4. "`sb delegate` figures out where a spawn lands" — PARTIAL

**What holds.** There is no `--fork`, `--here`, `--tab`, `--worktree` or `--space` flag:
`sb delegate --help` shows `--role --as --with --name --workspace --model --keep
--ephemeral` and nothing else. Placement is derived — inheritance plus the fork rule
(`broker.py:1282-1319`) — and the second clause is satisfied outright: because the rule is
role-agnostic, the top spawning `--role orchestrator` and the top spawning `--role worker`
both produce a space, verified live (`workspace-model-lead` with `wJ`; `worker-2` with
`w1E`).

**What does not.** `--workspace NAME` *is* a caller-passed placement flag
(`cli.py:132-134`, resolved by `Broker.join_workspace`, `broker.py:649-684`, and spliced in
as `delegate(..., **join)` at `cli.py:700-704`). It is narrow — join-only, never creates,
and explicitly refuses a bare space (`broker.py:663-672`) — so it may well be within the
spirit of the entry, but it is literally the caller saying where the spawn lands, and it
was used in production: `teardown-lead-2` has a `workspace_join` event (id 12668, workspace
`teardown-fix`, `w1M`) and no fork of its own.

Alongside it, `sb workspace new` is a whole caller-driven placement command (see §3f), and
`Broker.delegate` takes `workspace`, `branch`, `workspace_id`, `cwd` and `pane` keywords
(`broker.py:1272-1276`) — internal callers only, not reachable from the CLI, so not a gap in
itself.

### Gaps
- `sb delegate --workspace <name>` is a caller-passed placement flag; decide whether it
  survives the entry or should be derived some other way.
- `sb workspace new` is a second, caller-driven placement path with different rules from
  the fork rule.

---

## 5. The `<name>-lead` naming convention — SATISFIED

Implemented, correct, and used. `Broker.workspace_new` derives
`lead = agent or f"{_slug(name)}{LEAD_SUFFIX}"` (`broker.py:625`), `LEAD_SUFFIX = "-lead"`
comes from config rather than a literal (`broker.py:79`, `defaults/settings.toml:105`), and
`_slug` (`broker.py:183-195`) makes a branch name legal as an agent name and truncates by
exactly `len(LEAD_SUFFIX)` first, so the suffix can never push the name past herdr's 32
characters.

Live: `audit-cleanup-lead` and `split-fix-lead` each have a `delegate` event immediately
followed by `workspace_open ... created: true` (ids 10478/10480 and 11414/11416) — i.e.
both names were derived by `sb workspace new`, not typed.

**Caveat, not a gap against this entry** (entry 2 says the lead "*can* be called
`<name>-lead`", which is permissive): the convention is reachable only through
`sb workspace new`, and no agent is ever told that command exists. It appears in
`defaults/roles/orchestrator.md:8`, which is inside the HTML comment block spanning lines
5-99, and HTML comments are stripped before a prompt is flattened
(`switchboard/config.py:62`, `242-258`). `defaults/protocol.md` never mentions it. So every
`-lead` name in the store other than those two came from a human or agent typing `--name`
by hand (e.g. `teardown-lead-2`, spawned by plain `delegate` — event 12688).

---

## Method / limits

- Read: `switchboard/cli.py`, `switchboard/broker.py`, `switchboard/herdr.py` (workspace and
  worktree calls), `switchboard/store.py` (roots, worktree_root, live_roots),
  `switchboard/roles.py`, `switchboard/config.py` (comment stripping),
  `defaults/settings.toml`, `defaults/protocol.md`, `defaults/prompts.toml`,
  `defaults/roles/*.md`.
- Ran: `sb --help`, `sb delegate --help`, `sb start --help`, `sb workspace new --help`,
  `sb status --json`, and direct read-only SQL against the store.
- Did **not** run: any spawning command, `sb workspace new`, or anything mutating. No
  `audit-sim-*` agents were created, so nothing needed cleaning up.
- Not checked: `sb cleanup` / teardown behaviour, board placement, the reconciler, and the
  read-only-task exception to the worktree rule — all outside this slice.
- Inferred rather than observed, and marked as such above: the linked-worktree fork failure
  chain in §1 (the two `fork_failed` rows are the same herdr refusal, but not from a
  `sb start`-in-a-worktree run), and the treeless-non-top propagation in §3.
