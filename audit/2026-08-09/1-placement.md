# Audit group 1 — SPAWN AND PLACEMENT

Switchboard's real state against `DESIGN-TRUTH.md`, which was the only document treated as
authoritative. No other doc in the repo was used as evidence of how anything works.

Audited tree: `/Users/andrew/.herdr/worktrees/switchboard/worker-2`, branch `worker-2`,
HEAD `3b58c53`. Read-only throughout — no code or docs changed, no agents spawned to test,
nothing cleaned up that was not ours.

Run by `audit-1` across three auditors on disjoint slices: spawn routing (`reviewer-1`),
worktrees and spaces (`reviewer-2`), panes and focus (`reviewer-3`). Their full reports,
with all `file:line` evidence, are at `/tmp/sb-audit-1-part-a.md`, `-part-b.md`, `-part-c.md`.

---

## Verdicts

| # | DESIGN-TRUTH entry | Verdict |
|---|--------------------|---------|
| 1 | **Starting work** — `sb start` = new bare space on main, a top orchestrator | **PARTIAL** |
| 2 | **Anything that might need code changes** — workspace/worktree, plus a lead unless small and clear | **PARTIAL** |
| 3 | **Where each spawn lands** — only the top ever creates a space; a bare agent cannot spawn | **PARTIAL** |
| 4 | **A worktree belongs to a space, not to an agent** | **PARTIAL** |
| 5 | **`sb delegate` figures out where a spawn lands** rather than the caller passing flags | **PARTIAL** |
| 6 | **A workspace forks from `origin/main` by default** | **SATISFIED** |
| 7 | **`sb start` focuses the pane; nothing else ever focuses on spawn** | **PARTIAL** |
| 8 | **Every single sb-made view is a split pane with `sb board`** | **BROKEN** |
| 9 | **The `<name>-lead` naming convention** | **SATISFIED** |

**Counts: 2 SATISFIED · 6 PARTIAL · 1 BROKEN · 0 UNVERIFIED.**

One caveat on entry 8. It is BROKEN on the branch audited, but local `main` already carries
three unmerged commits (`e8e5c70`, `d38425f`, `713a1f4`) that fix most of it; `reviewer-3`
verified against the live session that agents spawned by the installed `sb` do get a board
pane. On `main` that entry is PARTIAL, not BROKEN. Nothing else in this group differs
between the two branches.

---

## The three sharpest gaps

**1. A bare agent can spawn, and any agent can create a space.** DESIGN-TRUTH says an agent
the top spawns directly cannot spawn other agents, and that only the top ever creates a
space. Neither is enforced anywhere: there is no capability check in `delegate`
(`broker.py:1279`), the protocol hands `sb delegate` to every role regardless
(`defaults/protocol.md:112`), and `sb workspace new` creates a herdr workspace, a git
worktree and a lead with no caller check at all (`cli.py:844-848` → `broker.py:580-647`).
This very audit is the violation: `worker-2` is a plain worker, and it spawned `audit-1`,
which spawned three reviewers — three levels below where spawning is meant to stop. The
placement half survived it (the whole subtree stayed in one space), so what is missing is
the capability gate, not the routing.

**2. A fork that fails drops a writing agent into Andrew's own checkout, silently.**
`_fork_for` swallows any herdr error and returns `None` (`broker.py:1235-1240`); `delegate`
then falls through to the parent's bare space over the primary checkout
(`broker.py:1321-1326`). Only a line in the event log records it — the parent is not told
and the agent does not know. Two live triggers for it exist. `sb start` lays the top's space
over whatever checkout it was typed in rather than the recorded main checkout
(`cli.py:547`), and herdr refuses to create a worktree from a linked worktree — two such
`fork_failed` rows are already in the event log. Separately, in a `master`-based repo the
fallback base resolves to a `main` that does not exist, so the fork fails for that reason
too (proved by running `_fork_base` against throwaway repos).

**3. Rejected flags are still on the command line, and one spawn path still gates the board
on role.** `--no-board` survives on both `sb start` and `sb workspace new`
(`cli.py:113`, `cli.py:256`), and `sb workspace new --focus` survives (`cli.py:255`) — that
is "focus as a flag" on a spawn path that is not `sb start`, and it is reachable by any
agent. On the audited branch `delegate` opens no board at all, and `workspace_new` opens one
only when the lead's role is orchestrator (`broker.py:639`). `sb restore` opens no board on
either branch.

---

## Gaps in full, by entry

Each line is meant to stand alone as a build task.

### 1. Starting work — PARTIAL

The space is genuinely new, genuinely bare (no `create_worktree`, `branch` left NULL), and
genuinely a top orchestrator with `parent=None` — confirmed in source
(`broker.py:395-413`, `:474`, `:484-486`, `herdr.py:282-293`) and against four live tops in
the store. What fails is "on main".

- `sb start` lays the top's bare space over the *current* checkout, not the recorded `main_checkout`, so a `sb start` typed inside a worktree puts the top in the wrong place (`cli.py:547`; `store.main_checkout()` exists at `store.py:122-129` but is used only by `link_config`).
- Forks inherit that wrong cwd, and herdr refuses `worktree create` from a linked worktree (`linked_worktree_source`), so every child of such a top silently gets no worktree (`broker.py:732-733`).
- `_fork_for` swallows a failed fork into a log line — the child spawns treeless and nothing tells the parent (`broker.py:1237-1240`).
- A failed `create_workspace` quietly degrades `sb start` to a tab in someone else's space (`broker.py:479-486`).

### 2. Anything that might need code changes — PARTIAL

The worktree half is satisfied and then some: the fork rule is role-agnostic by design
(`broker.py:1294-1319`), so every child of a top gets its own worktree. The judgement half
has no implementation.

- No prompt tells the top the rule "small and clear → one bare agent, otherwise a lead"; it receives the generic per-part splitting paragraph written for a workspace lead (`defaults/roles/orchestrator.md:127-131`, one shared orchestrator role at `settings.toml:76-80`).
- The top's route to "workspace plus lead" is `sb workspace new`, which no agent is ever told exists, so in practice the top uses `sb delegate` and the lead gets a generic `orchestrator-N` name (`cli.py:461-476`, `broker.py:1386-1390`).
- The worktree is unconditional, so DESIGN-TRUTH's read-only exception has no implementation (see entry 4).

### 3. Where each spawn lands — PARTIAL

Four of the five clauses hold and were confirmed live two levels deep in both directions:
`sb start` gives a bare space plus orchestrator; the top spawning either a bare agent or an
orchestrator produces a new space (`broker.py:1311`); and an orchestrator's spawns are tabs
in the same space, with the subtree staying there (`broker.py:1284-1292`, `_tab_for` at
`:1133-1161`). The fifth clause is unimplemented.

- Nothing prevents a bare agent under the top from spawning: no role or capability check in `delegate` (`broker.py:1279`, `cli.py:123-137`), and `defaults/protocol.md:112` hands the verb to every agent.
- `sb workspace new` creates a space and is callable by any agent at any depth — "only the top ever creates a space" has no enforcement (`cli.py:844-848`, `broker.py:580-647`).
- The fork rule keys on "parent has no worktree" rather than "parent is the top", so any treeless agent — for instance one whose fork failed — starts creating spaces of its own (`broker.py:1311`). Inferred from code; no live instance found.

### 4. A worktree belongs to a space, not to an agent — PARTIAL

The sharing rule itself is right and well covered: a child inherits its parent's workspace
and branch, and forks only when the parent has none (`broker.py:1294-1312`), with
`has_worktree` reading a stored fact rather than guessing (`broker.py:1026-1040`). Live, all
four agents of this audit sit on one branch and one checkout, and 376 workspace tests pass.

- The read-only exception does not exist: `broker.py:1294-1299` states the opposite in so many words, and `sb delegate` has no flag to decline a worktree.
- A failed fork silently drops a would-be writer into the human's main checkout, recorded only as an event-log row (`broker.py:1235-1240`, `:1321-1326`).
- The worktree is stored per agent row, never per space — there is no workspaces table, and the space-level answer is derived from the oldest row that happens to carry a branch (`store.py:148-161`, `store.py:698-709`, `broker.py:1008-1024`).
- That divergence has actually occurred: two live workspaces hold both branch-set and branch-NULL rows, and any NULL row makes that agent's children fork a new worktree instead of staying put. No current code path was found that produces it, so treat it as unexplained history rather than a live regression.
- Nothing anywhere ever tears a worktree down: `cleanup` closes panes and sets state only (`broker.py:1638-1750`), and 14 stale worktrees are on disk now. (This also contradicts the separate cleanup entry, which belongs to another group.)

### 5. `sb delegate` figures out where a spawn lands — PARTIAL

Placement is genuinely derived — there is no `--fork`, `--here`, `--tab`, `--worktree` or
`--space` flag, and the second clause holds outright, since the role-agnostic rule means the
top spawning an orchestrator and the top spawning a worker both produce a space
(`broker.py:1282-1319`, confirmed live).

- `sb delegate --workspace <name>` is a caller-passed placement flag, narrow (join-only, never creates, refuses a bare space) but literally the caller saying where the spawn lands, and used in production (`cli.py:132-134`, `broker.py:649-684`).
- `sb workspace new` is a second, caller-driven placement path with different rules from the fork rule.

### 6. A workspace forks from `origin/main` by default — SATISFIED

`origin/main` is the literal default at every layer — settings, both broker constants, the
attach path, `workspace_new`, `create_worktree`, and the `--base` flag
(`settings.toml:111`, `broker.py:80`, `:587`, `:700`, `herdr.py:41`, `:329`,
`cli.py:253-254`) — and it is fetched on the spot before each fork rather than read stale
(`_fork_base`, `broker.py:748-786`). Fallbacks when `origin` or `origin/main` is missing are
deliberate and flagged into the event log.

- One latent defect, not verdict-changing: the local fallback ref is never checked to exist, so in a `master`-based repo the fork base resolves to a non-existent `main` and the fork fails — after which the swallowed-fork gap above hides it. Proved by running `_fork_base` against three throwaway repos.

### 7. `sb start` focuses; nothing else focuses on spawn — PARTIAL

Default behaviour is correct. `sb start` focuses (`broker.py:397`, `:469`, `:493`,
`herdr.py:503-505`); there are only two focus call sites in the whole package, the other
being the board click, which the entry explicitly permits (`board.py:364-375`); and every
spawn-adjacent herdr call passes `--no-focus` explicitly (`herdr.py:267`, `:290`, `:308`,
`:340`, `:359`), so neither `delegate` nor the fork nor the board split steals focus.

- `sb workspace new --focus` is the rejected "focus as a flag" on a spawn path that is not `sb start`, and any agent can reach it — remove it and the two `_focus` calls it feeds (`cli.py:255`, `broker.py:588`, `:633`, `:646`).
- Judgement call: `sb start --no-focus` lets the one command that must focus decline to; the entry states `sb start` focuses without qualification (`cli.py:112`).

### 8. Every sb-made view is a split pane with `sb board` — BROKEN

On the audited branch `_open_board` has three call sites and none is `delegate`, so every
agent an orchestrator spawns lands in a bare pane — the common case, not an edge. A board
beside the parent does not help, because children are placed with `create_tab` and panes
belong to tabs. Local `main` fixes the two largest parts of this and is unmerged here.

- `delegate` opens no board (`broker.py:1379`); port main's `_open_board(name, agent.pane_id or pane, cwd=str(where))` in before the prompt.
- `workspace_new` gates the board on `role == MAIN` (`broker.py:639`), so a non-orchestrator workspace lead gets none; main has already reversed this.
- `restore` puts an agent in a fresh tab with no board — still true on main (`broker.py:1800`, `cli.py:849`).
- `--no-board` is on the rejected list but still exists on two verbs, along with the `board: bool` params it feeds (`cli.py:113`, `cli.py:256`, `broker.py:397`, `:435`, `:589`).
- A herdr failure inside `_open_board` means no board and no event — a bare `except Exception: return` (`broker.py:544-552`); main logs the refusal case but keeps the swallow.
- There is no `_close_board`, so once every agent has a board, cleanup must take the board pane with the agent or leave an empty tab behind on every close.

### 9. The `<name>-lead` naming convention — SATISFIED

Implemented, correct and used: `workspace_new` derives `lead = agent or f"{_slug(name)}{LEAD_SUFFIX}"`
(`broker.py:625`), the suffix comes from config rather than a literal (`broker.py:79`,
`settings.toml:105`), and the slug truncates by exactly the suffix length first so the name
can never exceed herdr's 32 characters. Two live agents were confirmed to have had their
names derived rather than typed.

- Caveat, not a gap against this entry, which is permissive ("*can* be called `<name>-lead`"): the convention is reachable only through `sb workspace new`, which no agent is ever told exists — its only mention sits inside an HTML comment block that is stripped before prompts are flattened (`config.py:62`, `:242-258`), and `protocol.md` never mentions it.

---

## Noted but out of this group's scope

Passed along rather than investigated, since they belong to other audit groups:

- `sb ask` and `sb wait` are still live verbs; `sb delegate` still has `--keep` and `--ephemeral`; `sb cleanup` still has `--include-kept` and `--leave-children`. All four are on the explicitly-rejected list.
- Nothing ever deletes a worktree, which contradicts the cleanup entry and is why `sb restore` never actually loses one.

## Method and limits

Evidence is source plus the live store read through `switchboard.store`, `sb --help` and
per-verb help, `sb status --json`, `git worktree list`, the existing workspace test suite
(376 tests, passing), and `_fork_base` run against throwaway repos. No spawning or otherwise
mutating command was run, so no `audit-sim-*` agents were created and nothing needed cleaning
up. Two claims are inferred from code rather than observed and are marked as such above: the
linked-worktree fork-failure chain in entry 1, and treeless-non-top space creation in entry 3.
Not covered here, by scope: cleanup and teardown behaviour, the reconciler, mail and doorbell
delivery, and the board's own contents.
