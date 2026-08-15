# How switchboard names agents and workspaces

Read-only scout. No code changed.

## 1. Where `main` comes from

`main` is not a string literal in the code — it's a config value. `switchboard/broker.py:64` reads
`MAIN_NAME = config.setting("vocabulary.main_name")`, which resolves to `"main"` from
`defaults/settings.toml:98`. Likewise the top-level role name (`orchestrator`) is
`vocabulary.main_role` (`defaults/settings.toml:94`), and the default child role
(`worker`) is `vocabulary.default_role` (`defaults/settings.toml:101`).

**This already answers "can it be custom": yes, today, no code change needed.** Every
repo can override it by dropping a `[vocabulary] main_name = "whatever"` into
`<repo>/.switchboard/settings.toml` — `switchboard/config.py:320-326` (`settings()`)
merges shipped defaults with that file, table by table. See the comment at
`defaults/settings.toml:1-6` describing this merge. What it does *not* give you is a
name that's dynamically derived per-repo (e.g. "always the repo's directory name") —
that would take a small code change (see §5), since today it's one fixed string per repo,
set once in that repo's own settings file.

`sb start` (unnamed) calls `broker.py:897` → `self._next_top_name()`, which only
falls back to `MAIN_NAME` if that name has never been used (`broker.py:1058-1059`).
`sb start --name X` skips the counter path entirely and calls `_top(X, task)` directly
(`broker.py:895-896`) — so a custom name is *already* a first-class argument, not a
retrofit.

Child agents from `sb delegate` work the same way: `broker.py:3054`,
`name = name or self._unique_name(role)` — the role name (default `worker`, or
whatever `--role` was given) is the prefix, and `_unique_name` (`broker.py:3329-3333`)
appends the first free integer. `worker-23` means role `worker`, and 23 is just "the
first number nobody's used yet," not literally "22 workers ran before this one" (see §2).

## 2. Why the number never resets

Both counters (`_next_top_name` for tops, `_unique_name` for delegate) do the same
thing: start at a number and linearly probe `store.get_agent(db, f"{prefix}-{n}")`
until they find one that returns `None` (`broker.py:1058-1063` and `:3329-3333`). It is
**not** a persisted counter value — there's no "next_id" cell anywhere. It's re-derived
every time by asking "has this literal name ever been claimed," which is a question
about history, not about who's currently running.

The reason it climbs and never resets: agent rows are **never deleted** once an agent
has actually run. `switchboard/store.py:1059-1062` (`drop_agent`) does a real
`DELETE FROM agents`, but it's called from exactly two places in `broker.py` (lines 985
and 3178), and both are narrowly scoped to **husks** — rows left behind by a spawn that
never got a pane or session (`_spawn_husk`, `broker.py:3316-3327`). A normal agent that
actually ran and finished — even one that's long done, failed, or whose workspace was
closed — keeps its row forever, with `state` moving through `working → done/blocked/
failed` (`store.py:145`) but the row itself persisting. `_next_top_name`'s own docstring
says this explicitly (`broker.py:1044-1056`): "Free means *never used*, not merely
not-running... Reusing a finished orchestrator's name would file two unrelated agents,
with two unrelated histories, under one name."

So `main-14` doesn't mean 13 are currently alive — it means 13 earlier names
(`main`, `main-2` .. `main-13`) were claimed at some point in this repo's history,
whether they're still running, long done, or their workspace was torn down and forgotten.
The counter is global to the repo's store (`switchboard/store.py:90`, `state.db` lives
under the repo's `.git`, shared by every worktree of that repo), not per-session or
per-day.

`_name_free` (`broker.py:1065-1068`) also checks workspace records, not just agent rows —
`sb workspace new main-3` mints a workspace called `main-3-lead` for its lead agent, and
that used to be invisible to the top-name counter (a real bug the docstring at
`broker.py:1052-1056` describes being fixed). Today both tables are consulted, so a name
used by *either* an agent row or a workspace row (bare or worktree, per
`_name_held_by`, `broker.py:1070-1089`) counts as taken — except a **retired**
workspace, which frees its name back up for reopening (`_name_held_by` returns `None`
when `row["retired_at"]` is set, `broker.py:1084-1085`).

## 3. What else depends on the name

The name is not just a label — it's load-bearing in three other places:

- **Git branch.** `_fork_for` (`broker.py:2904-2925`) uses the agent's name as the
  branch name verbatim: "No prefix and no suffix: the name is already unique
  (`agents.name` is the primary key), already legal as a branch, and already short."
  An existing branch of that name is refused outright (`_branch_exists` /
  `BranchTaken`, `broker.py:2943-2944`) rather than reused. This means a custom name
  must be a legal git branch name (no spaces, no most punctuation).
- **herdr workspace/session label.** `create_workspace(label, ...)` (`herdr.py:373-384`)
  is called with the agent name as `label`, and herdr's `workspace create --label`
  is how the space shows up in Andrew's spaces UI. herdr's namespace is
  **machine-global**, not per-repo (confirmed in
  `.switchboard-shared/presets/house-rules.md:49-52`: "herdr is machine-global, so
  they do appear in Andrew's spaces UI"). Switchboard's own uniqueness check
  (`_name_free`) only queries *this repo's* `state.db` (`store.py:90`, scoped under
  that repo's `.git`) — so two different repos could independently pick the same
  custom top-level name and never collide in switchboard's own bookkeeping, but
  *could* collide in herdr's global label space. Today this risk barely exists because
  every repo defaults to the shared literal `main` + a rising counter (`main-2`,
  `main-3`, ...), which functionally namespaces the label by requiring a running
  count. A feature that lets any repo pick an arbitrary custom string just for its
  own `main` (e.g. every repo picks the same short word) reopens that collision.
- **Store primary key.** `agents.name` is the table's primary key
  (`store.py:141`), and `claim_agent` uses `INSERT OR IGNORE`
  (referenced at `broker.py:3169`, `store.claim_agent`) — so within one repo's
  store the name is the sole identity of an agent row, and workspace names
  (`workspaces` table, `store.py:299`) are checked as a second, related namespace
  by `_name_held_by`.
- **Directory names.** Not directly by code — the worktree checkout path is
  whatever herdr/git puts it at for a branch of that name (this repo's own worktrees
  live at `.../switchboard/<name>`, as seen in this very checkout's path). Since the
  branch *is* the name, the worktree directory effectively is too.

## 4. Does `sb start`/`sb workspace` already take a name argument?

Yes. `sb start --name <X>` is documented and implemented as the primary way to control
naming (`broker.py:879, 888-890, 895-896`) — the docstring says explicitly that this
is now the "come back to a specific one" spelling, replacing old unnamed-resume
behavior. Nothing in `_top` or `delegate` assumes the top-level prefix is literally the
string `"main"` — everywhere the code needs that name it reads `MAIN_NAME` from config
(`broker.py:64`), never a hardcoded literal. I did not find any hardcoded `"main"`
string used for naming/branching logic in `broker.py` (`grep` for `"main"` /
`'main'` only turned up an unrelated comment at `broker.py:2443`).

## 5. How hard would a fully dynamic custom-name option be?

**Per-repo fixed custom name (e.g. "always call it `switchboard-lead`"): already done.**
Set `vocabulary.main_name` in that repo's `.switchboard/settings.toml`. Zero code
changes.

**Derived-from-repo-name default (e.g. auto-pick the repo's directory name instead of
the literal `"main"`), with no manual per-repo config step:** small, localized change.
`_next_top_name` (`broker.py:1044-1063`) would need to compute its base string from
`self.repo` (e.g. `self.repo.name`) instead of always reading the flat `MAIN_NAME`
setting, when no repo-level override is present. The counter/probe logic (`_name_free`
loop) doesn't need to change at all — it already takes any base string. Main things to
get right:
  - **Legality as a git branch name.** A raw directory name may contain characters
    that are illegal or awkward in git branches (spaces, `.`, leading `-`, etc.) — would
    need the same slugging git branch names generally need.
  - **herdr collisions across repos.** As in §3, two repos with the same directory
    name (a common `dotfiles`, `api`, `web`, etc.) would now default to the same
    herdr label instead of the shared, less-likely-to-collide literal `"main"`. This is
    the main new risk this change introduces — worth checking against herdr's actual
    label-collision behavior before shipping (I did not test this; I only confirmed
    from documentation that the namespace is machine-global).
  - **Restore/cleanup**, which key off the stored `name`/`workspace` fields, not off
    where the value came from — I did not find anything in the restore/cleanup paths
    (`broker.py` cleanup logic) that assumes the name is literally `"main"`, so this
    should be unaffected either way.

I have not exercised any of this live (read-only scout) — the above is from reading
`broker.py`, `store.py`, `herdr.py`, `config.py`, and `defaults/settings.toml` only.
