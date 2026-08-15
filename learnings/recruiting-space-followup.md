# Why the recruiting agent didn't land in the `recruiting` herdr space

Investigate-only follow-up. Read-only: `main-11`'s live transcript
(`/Users/andrew/.claude/projects/-Users-andrew-Code-switchboard/8ac71494-4b17-43b0-b9c7-32e23381af77.jsonl`,
session id `8ac71494-4b17-43b0-b9c7-32e23381af77`) and the live switchboard store
(`/Users/andrew/Code/switchboard/.git/agentflow/state.db`, sqlite). Code checked against
this checkout (`switchboard/broker.py`, `switchboard/cli.py`, `switchboard/herdr.py`,
`switchboard/store.py`).

## 1. What main-11 actually did

`main-11` is a top-level orchestrator (`sb start`) checked out at
`/Users/andrew/Code/switchboard` itself (agents row: `workspace=main-11`,
`workspace_id=w17A`, `cwd=/Users/andrew/Code/switchboard`).

It ran a recruiting-discovery task for Andrew entirely inside the switchboard repo at
first (writing `recruiting/*.csv` there), then, on Andrew's instruction, **moved the
recruiting files out to a brand-new, separate git repo at `/Users/andrew/Code/recruiting`**
and `git init`'d it there (own commit, no remote). This is a different repo from
switchboard — it has never been `sb init`'d.

main-11 then tried to spin up a diagnostic agent rooted in that new repo, and hit the
wall itself. Verbatim from its own transcript:

> "`--workspace` only joins an existing switchboard workspace, and the recruiting repo
> isn't one. Let me check whether there's any way to root an agent elsewhere."
>
> "No way to root a child in an arbitrary repo — `--workspace` only joins workspaces that
> already exist in switchboard, and the recruiting repo was never `sb init`'d. I'll spawn
> a normal child and point its task at that repo instead."

So main-11 did **not** attempt to target any herdr space by name — it correctly diagnosed
that `--workspace` (switchboard's only placement flag) can't reach an un-`sb init`'d repo
at all, gave up on rooting the child there, and instead spawned an ordinary child in its
own tree with the target repo's path only in the task text. The exact command (from the
transcript, `main-11`'s `Bash` tool call):

```
./bin/sb delegate "Work in the git repo at /Users/andrew/Code/recruiting (NOT the
switchboard repo). ..." --role worker --name recruiting-probe
```

No `--workspace` flag. This is the `recruiting-probe` agent Andrew sees truncated as
`recruiting-pr…` in the herdr UI.

main-11 reported this accurately to Andrew afterward too: "**You can't root a child agent
in another repo.** `sb delegate` has a `--workspace` flag, but it only joins workspaces
that already exist in switchboard, and the recruiting repo was never `sb init`'d."

**No mention anywhere in the transcript of the `recruiting` herdr space** Andrew later
created — it postdates this session's work and was never referenced or targeted.

## 2. Where `recruiting-probe` actually landed, and why

From `state.db`:

```
name              parent   role    state  workspace         workspace_id  branch
recruiting-probe  main-11  worker  done   recruiting-probe  w1BN          recruiting-probe
```

`events` for it starts with `fork`:

```json
{"parent": "main-11", "workspace": "recruiting-probe", "branch": "recruiting-probe",
 "path": "/Users/andrew/.herdr/worktrees/switchboard/recruiting-probe",
 "base": "origin/main", ...}
```

So without `--workspace`, `sb delegate` **forked a brand-new git worktree of the
switchboard repo**, branch `recruiting-probe`, and opened that as its own herdr
workspace. Code path:

- `switchboard/cli.py:825-838` — the `delegate` command. `join = b.join_workspace(args.workspace) if args.workspace else {}`. Since no `--workspace` was passed, `join` is `{}` and `b.delegate(...)` runs with no placement override, which (per its docstring at `cli.py:830-833`) means it "inherits the caller's workspace or forks, as it always has."
- `switchboard/broker.py:3033` (`delegate`) → for a role like `worker` with no inherited/bound workspace it calls into `_attach_workspace` to fork a new one (the `create` path).
- `switchboard/broker.py:2233-2290` (`_attach_workspace`) — `create=True`, no existing checkout for branch `recruiting-probe`, so it runs the `create` step: `self._call_adapter("create_worktree", branch, base=forked_from, cwd=str(self.repo))` (`broker.py:2270-2272`). `self.repo` is the switchboard repo (the store's own `repo_root()`, `switchboard/store.py:46-61`) — there is no other repo in scope at all.
- `switchboard/herdr.py:425-445` (`create_worktree`) — calls herdr's `worktree create --branch recruiting-probe --base origin/main --cwd <switchboard repo>`. Its own docstring states the mechanism plainly: **"this already opens the checkout as a workspace and groups it with the parent repo"** (`herdr.py:433-434`). That grouping-by-parent-repo is herdr's own behavior, not something switchboard chooses or can override — switchboard passes no space/group identifier at all, only `--branch`, `--base`, `--cwd`, and optionally `--label` (a display name, see `herdr.py:439-440`, `rename_workspace` at `herdr.py:468-469`).

herdr grouped the new `recruiting-probe` workspace with whatever herdr space already
holds the switchboard repo's other worktree-based workspaces — the `switchboard` space
Andrew sees containing `worker-9`, `reviewer-14`, `researcher-14`, `researcher-15`, and
`recruiting-probe`. All of those are forked worktrees of the *same* switchboard repo, so
herdr clusters them together by repo identity, regardless of what each agent's task is
about.

**The one-sentence reason:** `recruiting-probe` is a worktree of the switchboard repo
(there was no other repo switchboard could fork it from), and herdr automatically groups
every worktree-workspace of one repo into one space — so it landed in the `switchboard`
space, the same place every other switchboard-repo child lands, with no path in the code
that could have put it in `recruiting` instead.

## 3. What the empty `recruiting` space is

No row for a workspace named `recruiting` exists anywhere in switchboard's `workspaces`
or `agents` tables (checked both; only `recruiting-probe` matches `%recruit%`). So this
space is **not** something switchboard created, touched, or has any record of — it is
purely a herdr-side object Andrew made directly in the herdr UI, holding herdr's own
default `main` root pane and nothing switchboard ever put there.

This confirms, specifically for this incident, the starting hypothesis — but the
mechanism is more precise than "switchboard never resolves a space by label": **switchboard
has no concept of a herdr "space" as an addressable target at all.** Its own placement
vocabulary (`--workspace <name>` in `cli.py:139`, resolved in `broker.py:1259` via
`store.known_workspace`) only matches names in switchboard's *own* `workspaces` table —
rows it itself created by forking or opening a worktree of the repo it's running in.
`join_workspace` never calls out to herdr to search for a space by label, id, or any
other handle; there is no code path where a herdr space is looked up at all. So:

- There is **no lookup-by-label against herdr's space model** anywhere in this codebase.
- There is also **no lower-level "attach to herdr space X" primitive** switchboard could
  have used and simply didn't call — `herdr.py`'s `create_workspace` (`373-384`) and
  `create_worktree`/`open_worktree` (`425-466`) accept only `label`, `cwd`, `branch`/`path`,
  and `base` — never a space or group id. If herdr's own CLI (`herdr workspace create` /
  `herdr worktree create`) supports joining a specific existing space by id, switchboard's
  adapter does not expose or pass that; I did not check herdr's own CLI/source for a flag
  since it's outside this repo, so I can't rule out that herdr itself has one that
  switchboard simply never wires up. That distinction (herdr has no such concept at all,
  vs. herdr has one and switchboard doesn't use it) is unresolved — everything above only
  establishes that switchboard, on this side, has nothing.

## 4. Can a human pre-create a space and land agents in it today?

**Not through anything switchboard exposes.** There is no flag, env var, or config in
this codebase for "put this new workspace in herdr space X." The only two space-shaping
levers that exist are:

- `--workspace <name>` on `sb delegate`, which *joins an already-switchboard-known
  workspace* (one switchboard itself created earlier) — not a herdr space by any name.
- `--label` at creation / `sb workspace rename` afterward (`herdr.py:468-469`, wraps
  `herdr workspace rename`) — renames the *workspace's* display label, not which space it
  groups under.

So: pre-creating a herdr space by hand, as Andrew did, has no effect on where a future
`sb delegate`/`sb start` lands — that's decided by (a) which repo you're running `sb` in
(worktree children always fork within that repo and inherit whatever space herdr clusters
that repo's worktrees under) and (b) `sb start`, which creates its own standalone bare
space every time (`create_workspace`, `herdr.py:373-384` — no join option there either).
There is no way today to say "put this new agent under space `recruiting`."

## Bottom line for Andrew

- `recruiting-probe` isn't misplaced by a bug in resolving a name — it never had a name to
  resolve. `sb delegate ... --name recruiting-probe` (no `--workspace`) always forks a new
  worktree of the repo you're running switchboard in, and herdr's own `worktree create`
  groups that worktree into whatever space already holds that repo's other worktrees. The
  actual recruiting work now lives in a **separate, un-`sb init`'d repo**
  (`/Users/andrew/Code/recruiting`) that switchboard has no workspace concept for at all.
- Targeting a pre-made herdr space is not possible today — switchboard has no code path
  that even attempts it, confirmed by reading every workspace-placement function
  (`cli.py:825-851`, `broker.py:1259-1296`, `broker.py:2233-2290`, `herdr.py:373-466`).
- If Andrew wants agents actually living in the `recruiting` repo/space, main-11 already
  named the fix correctly in its own report: that repo needs its own `sb init` and its own
  `sb start`, which makes it a separate tree, not children of `main-11`.
