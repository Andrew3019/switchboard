# One command to recover everything a herdr restart took out

Design and code-reading only. No state-changing `sb` command was run; the live
fleet was only queried through
`file:/Users/andrew/Code/switchboard/.git/agentflow/state.db?mode=ro`. All line
numbers are against `/Users/andrew/Code/switchboard` at `cafc7c8` (the tip of
`main` at the time of this scout).

## 1. What `sb restore` does today, end to end

`switchboard/broker.py:4566` (`Broker.restore`), reached from
`switchboard/cli.py:1131` (`b.restore(args.name, me=me)`, `me` always
`b.whoami()` from `cli.py:795`). One agent, one call — `cli.py:303-304`
declares exactly one positional argument, no batch form.

Order of checks, all read from `restore()`'s body:

1. **Tree boundary** (`broker.py:4577-4578`) — `require_same_tree(me, name)`,
   skipped only when `me is None` (an internal caller, not the CLI).
2. **Row exists** (`4579-4581`) — `KeyError` if not.
3. **Has a `session_id`** (`4582-4583`) — `ValueError` otherwise. This is the
   session-id gap the companion task owns; noting only where it bites: it is
   checked before anything else, so a row with no session id never even
   reaches the workspace/pane logic below.
4. **Not already alive in herdr** (`4584-4592`).
5. **Workspace not mid-teardown** (`4597`, `_refuse_retiring`,
   `broker.py:2217`).
6. **Resolves where to land** (`4599-4605`): `workspace_id` first from the
   *call's* `workspace` argument (always `{}` from the CLI — `cli.py:1131`
   never passes one), then the **recorded** `agents.workspace_id` column,
   then only as a last resort `self._workspace_id(a["workspace"])` (a fresh
   herdr lookup by workspace **name**).
7. **Checkout must exist on disk** (`4617-4625`) — `Path(where).is_dir()`.
   Refuses by name and points at the git branch instead if not. This is the
   "worktree gone" precondition; already covered by DESIGN-TRUTH.md:437-439
   and confirmed for the 5 crash-cohort candidates in
   `herdr-restore-list.md`.
8. **Opens a fresh pane** (`4628`, `_tab_for`) and readies it (`4634`,
   `_ready_pane`); a failure closes the tab it just made rather than leaving
   an orphan (`4635-4640`).
9. **Starts Claude Code with `--resume <session_id>`** on the role's
   original tier flags (`4645-4655`).
10. **Rewrites the row** (`4656-4657`, `4669-4671`): new `pane_id`/
    `terminal_id`, `ended_at=NULL`, `state='working'`, `turn=NULL` (turn is
    deliberately cleared, never restored — a stale `working` edge would hold
    the agent's mail forever, per the comment at `4658-4668`).
11. Logs a `restore` event (`4673`).

**Nothing here walks a subtree.** Restoring a parent does not restore its
children; each name is its own call, and nothing checks the parent is alive
first (`herdr-restore-list.md` §3 confirms this by reading the same
function). The only sane order is externally imposed: parents before
children, so a restored child's mail has somewhere live to land.

## 2. What identity a restored pane can actually be given — and what can't be recovered

**Pane/terminal id: confirmed not recoverable, and the schema says so at
rest.** `store.py:180-181`: `terminal_id` is commented "STABLE herdr handle"
but `pane_id` "NOT stable across pane move; debugging only". Neither
survives a herdr *restart* — `_tab_for`'s own docstring (`broker.py:2925`)
states plainly "ids are handed out per herdr run" — so `terminal_id`'s
stability is scoped to *moves within one herdr run*, not across a restart. A
restored agent always gets a brand-new pane; `restore()` writes the new id
back at `4656-4657` and never claims otherwise.

**Workspace/space: NOT currently recoverable, and this is the one finding
worth flagging loudest.** `sb restore`'s workspace resolution
(`4603-4604`) prefers the **recorded `workspace_id` column** over
re-resolving the workspace by name — and that recorded id was assigned by
the *previous* herdr run. `_tab_for` (`broker.py:2922-2961`) then tries
`create_tab(cwd=..., workspace=<stale id>)`, which herdr answers with
`workspace_not_found` after a restart (per the same docstring, and per the
existing test `test_a_vanished_workspace_costs_the_placement_not_the_spawn`,
`tests/test_broker.py:3361-3368`, and its restore-specific twin
`test_restore_survives_a_vanished_workspace_too`, `tests/test_broker.py:3392`).
On that error, `_tab_for` clears the dead id from **every** row holding it
(`2951-2954`) and falls straight through to `self.h.create_tab(cwd=str(cwd))`
— a **bare tab, wherever herdr currently has focus** (`2961`). It does *not*
retry by resolving `a["workspace"]` (the name, e.g. `"github-issues"`) through
`self._workspace_id`, even though that name is right there on the row and
`_workspace_id` (`2847-2878`) is exactly the function that does a live,
by-name herdr lookup. That fallback exists in `restore()`'s own workspace
resolution line (`4604`) but is only reached when the recorded id is already
empty — which after a fresh spawn it never is, so in practice it is dead code
for the restore-after-restart path specifically.

Net: **today, restoring after a herdr restart puts the agent in a random
unnamed tab, not back in its named space**, even though switchboard *does*
still know the space's name and *could* re-resolve it. This is a real gap
between what's stored and what's used, not a missing test — the vanished-id
behavior itself is intentional and tested; only its use inside `restore()`
specifically (never falling back to the name) is untested and, on the
evidence above, wrong for this task's stated goal ("into the same herdr
space... it came from").

**What genuinely cannot be recovered, full stop:** the pane's own
scrollback/terminal content before the restart (herdr's live PTY state,
confirmed in-memory-only per `notes/herdr-recovery-scout-design.md` §1); any
tool call in flight with no final result flushed to the Claude Code
transcript; the exact screen layout/split arrangement a human had arranged
(herdr's `session.json` records *its own* layout, but that's a separate
recovery herdr already does on its own restart — see
`herdr-recovery-scout-live.md` §4 — not something `sb restore` touches or
needs to).

**Open question I could not resolve from code alone, worth a live check
before a worker builds this:** does the *specific `workspace_id` string* that
herdr assigned in the previous run always 404 after a restart, or does
herdr's own `session.json` replay (confirmed to reload 12/14 workspaces
intact per the live scout, §4-5) sometimes hand back the *same* id? The
`_tab_for` docstring and the passing test both assert "ids are per herdr
run," which I'm taking as authoritative, but nobody has restarted herdr
mid-test with a real recorded id to watch it 404. If it turns out herdr
*does* sometimes preserve the id, the fix below (re-resolve by name whenever
the recorded id fails) is still correct and merely redundant in that case —
so this doesn't change the design, only its urgency.

## 3. Fixing the space-placement gap (in scope for "same space it came from")

The fix is small and localized: `restore()`'s workspace resolution
(`broker.py:4603-4604`) should fall back to `self._workspace_id(a["workspace"])`
**after** `_tab_for` reports the recorded id dead, not only when the recorded
id was empty to begin with. Concretely, one of:

- Pass the id through, but have `_tab_for` (or a `restore`-specific wrapper
  around it) retry once with a **name**-resolved id when `workspace_not_found`
  fires, before falling all the way through to a bare tab. This changes
  shared code (`_tab_for` is also used by ordinary spawns), so the safer
  version is:
- Give `restore()` its own two-step call: try the recorded id via `_tab_for`;
  if it comes back with `workspace_id == ""` (the "dead id, degraded to bare"
  signal `_tab_for` already returns at `2961`) **and** `a["workspace"]` is a
  known name, re-resolve `self._workspace_id(a["workspace"])` and retry
  `_tab_for` once more with that. If the by-name lookup also comes up empty
  (space genuinely gone, e.g. herdr never recreated it), keep today's
  behavior — bare tab, not an error, exactly as `DESIGN-TRUTH.md`'s "the
  placement is a preference, not a condition of the spawn" already holds for
  ordinary spawns.

This is the one code change in `switchboard/` that a worker would need beyond
the one-shot command itself — everything else below is orchestration on top
of what `restore()` already does correctly.

## 4. What the one command should be

### Name and shape

`sb restore --sweep` (reusing `sb restore`'s own verb, the way `sb cleanup`
with no name is already "every eligible agent in scope" — `broker.py:3877`,
`"With no names, every finished one in the caller's scope."` — is the closest
existing precedent for a bare-name-optional sweep verb). Concretely:
`sb restore --sweep [--dry-run] [--yes]`, with `sb restore <name>` continuing
to mean exactly what it means today (unchanged, no batch semantics folded
into the single-name form).

### Selection rule

Not `absent_since IS NOT NULL` — that column is a **transient debounce
value**, cleared the moment a row's absence is either confirmed (flips to
`state='failed'`, `ended_at` set — `status.py:1193-1196`, `_record_gone`) or
contradicted (agent seen again). `GONE_CONFIRM_GRACE` is 60 seconds
(`defaults/settings.toml:270`), and confirmation happens automatically,
unattended, off `sb reconcile` on the collector's own timer
(`collector.py:122-123`, `RECONCILE_GAP=10s` floor / `RECONCILE_SWEEP=600s`
ceiling; `cli.py:651-672` — `reconcile` is "the only unattended path that
reaps"). I confirmed this live, read-only, against the very cohort the
background docs identified: at scout time, 5 of the 7 crash-cohort agents no
longer had `absent_since` set at all — 2 (`auto-mode-dialog`,
`close-paths-identity`) were already `state='done', ended_at` set (restored
by hand and finished since), `github-issues`/`codex`/`codex-support` were
`working`/`blocked` with no `ended_at` (restored and alive), and the one
unrestorable-by-name row (`wording`) had already flipped to
`state='failed', ended_at` set entirely on its own, with `absent_since` back
to NULL. In other words: by the time a human is likely to actually run a
recovery command (more than a minute after noticing), most of the crash
cohort has *already* self-confirmed to `state='failed'` with `ended_at` set.
`absent_since` is the signal for *detecting* the moment; it is the wrong
column to *select on* minutes later.

The selection query should be:

```sql
SELECT * FROM agents
WHERE state = 'failed'
  AND ended_at BETWEEN :window_start AND :window_end
  AND session_id IS NOT NULL AND session_id != ''
ORDER BY created_at;   -- see ordering below
```

with `:window_start`/`:window_end` a short band (a couple of minutes is
plenty, per the observed ~30s gap between `absent_since` and confirmed
`ended_at` in the live cohort) around the *first* `ended_at` timestamp found
in that state, auto-detected rather than typed by hand: take the newest
`ended_at` among `state='failed'` rows with no session id (the truly
unrestorable ones always get confirmed structurally, since `restore()` can
never clear them) as one anchor, or — cleaner — just cluster on `ended_at`
values within `GONE_CONFIRM_GRACE + RECONCILE_GAP` (~70s) of each other,
the same clustering the background scout did by hand on `absent_since`. This
also naturally covers the case where the sweep runs *before* `reconcile` has
caught up (rows still mid-debounce, `absent_since` set, `ended_at` still
NULL) — the query should be a union of both:

```sql
SELECT * FROM agents
WHERE ended_at IS NULL
  AND absent_since IS NOT NULL
  AND session_id IS NOT NULL AND session_id != ''
UNION
SELECT * FROM agents
WHERE state = 'failed'
  AND ended_at >= :recent_cutoff
  AND session_id IS NOT NULL AND session_id != '';
```

`:recent_cutoff` = "since the sweep command started minus a few minutes of
slack," not a fixed clock time — this is what makes the command need no
argument at all: it always means "whatever crashed recently and hasn't been
dealt with," not "restore everything that has ever failed" (that would also
try to resurrect ordinary crashed work from days ago, which is `sb restore
<name>`'s job on purpose, one at a time, with a human deciding).

Rows with no `session_id` are **never** silently dropped — they're excluded
from the restore list but must be **named in the report** (see §6), exactly
as `herdr-restore-list.md` did by hand for `probe-identity`/`wording`.

### Ordering

Parents before children, matching `herdr-restore-list.md` §4's manual
ordering and the reasoning in §1 above (a child's mail needs a live parent
pane to land in). Concretely: sort the candidate set by tree depth (walk
`parent` pointers to root, as `_root_of`/`_parentage` already do at
`broker.py:917-930`), root-first; siblings/independent trees can run in any
order or in parallel — `herdr-restore-list.md` §4 already noted steps within
different trees are independent.

### Idempotency

Running it twice must be a no-op the second time, and this falls out of
`restore()`'s own preconditions for free: check 4 (`_alive(name)`,
`broker.py:4584-4592`) already refuses a restore of something already
running, so a second sweep pass over the same candidate list just gets a
per-agent "already running — nothing to restore" and moves on. The sweep
wrapper's contract: never raise the whole command on one agent's refusal —
catch each `restore()` call, record success/refusal/error per row, continue
the batch. (This mirrors `Broker.cleanup`'s own per-candidate
`refused`/`closed` result shape, `broker.py:3930-3933`, `CleanupResult`.)

### What it prints

One line per candidate, in the order attempted: `restored <name>` /
`already running, skipped <name>` / `no session id, cannot restore <name>
(branch: <branch or "none recorded">)` / `checkout gone, cannot restore
<name> (branch: <branch>)` / `restore failed: <name>: <error>`. End with a
one-line summary count. `--dry-run` prints the same classification without
calling `restore()` at all — useful precisely because this command is meant
to run unattended-ish, right after a scary event, and a human will want to
see the list before committing.

## 5. Who may run it

**Must be run by the human, or relaxed with real thought about blast
radius — and I don't think it should be relaxed.** `require_same_tree`
(`broker.py:968-982`) is the guard, and `same_tree` (`951-966`) special-cases
exactly one identity that crosses freely: `me == HUMAN`
(`config.setting("vocabulary.human")`, `broker.py:60`). Every other caller —
any agent, in any tree — is confined to `same_tree(me, target)`, which for
an agent means "same root." The crash cohort in the observed incident spans
**two entirely separate trees** (`github-issues` and `codex`, both roots,
neither a descendant of the other — `herdr-restore-list.md` table). No agent
running inside either tree could restore the other tree's agents even one at
a time today, let alone in a sweep; `herdr-restore-list.md` §3 states this
outright: "none of us in this tree can restore any of them."

A crash cohort is, by construction, likely to span multiple trees — a herdr
restart doesn't respect tree boundaries, it takes out whatever panes existed
at that moment across every root the human had running. So a sweep that
tried to work from inside any one agent's identity would systematically
under-restore: it would only ever recover its own tree, silently leaving
siblings' trees for someone else to notice and run their own sweep — which
defeats "one command."

I don't think the fix is to relax `require_same_tree` for this path. The
restriction exists so that an agent — code running with model judgment, not
a person — cannot reach into a tree it wasn't given, and "there was a crash"
is not a reason to lift that: a compromised or confused agent inside *any*
tree could trigger a herdr-adjacent event (or just claim one happened) and
use a relaxed sweep as a sanctioned way to touch every other tree's agents.
The correct shape is the one `Broker.cleanup` already uses for its own
`me == HUMAN` branch (`broker.py:3942-3946`): **the sweep command itself
checks `me == HUMAN` and, only in that branch, scopes across
`SELECT * FROM agents` instead of `self._descendants(me)`.** Concretely:

```python
def restore_sweep(self, *, dry_run=False, me=None) -> "RestoreSweepResult":
    me = me or self.whoami()
    scope = (self.db.execute("SELECT * FROM agents").fetchall() if me == HUMAN
             else self._descendants(me))
    candidates = _select_crash_cohort(scope, ...)
    ...
    for row in _parents_first(candidates):
        try:
            self.restore(row["name"], me=None)   # me=None: already scoped, don't re-check tree
```

Note `me=None` on the inner `restore()` call, exactly as the module comment
at `broker.py:4573-4576` already documents for "an internal caller" — the
tree check has already been done once, at the scope level, by construction
(an agent's `_descendants(me)` can never contain a name outside its own
tree), so a second `require_same_tree` per row would be redundant, not
extra-safe.

**Consequence for the CLI:** if the human runs `sb restore --sweep` from a
plain terminal (not inside any agent's pane), `whoami()` resolves to `HUMAN`
(`broker.py:625`) and the sweep sees the whole store — every crashed tree,
in one command, which is exactly what was asked for. If an agent runs it,
it only ever recovers its own subtree — correct, and consistent with every
other scoped verb in the codebase, but worth stating plainly in the command's
own `--help`: **this only recovers everything if a human runs it.** An
agent-run sweep is real and useful (a lead recovering its own crashed
children) but is not "the one command that brings back everything" the task
asked for — only the human's invocation is.

## 6. Failure modes

| Case | Behavior | Where it's already handled |
|---|---|---|
| Worktree gone | `restore()` refuses that one row by name, names the branch; sweep continues, reports it in the summary, never treats it as a batch-fatal error | `broker.py:4617-4625`, unchanged |
| Transcript gone | Not separately checked by `restore()` at all — `--resume <session_id>` is handed to Claude Code, which owns finding its own transcript. If it can't, that surfaces as a `start_agent` exception, caught at `4649-4655` (tab closed, no orphan), and the sweep records it as a per-row failure, not a crash of the whole sweep | `broker.py:4646-4655` |
| Workspace retiring | `_refuse_retiring` (`2217`) raises before a tab is opened; same per-row handling | `broker.py:4597` |
| Agent already live | Precondition 4 refuses cleanly; this is what makes a second sweep run idempotent | `broker.py:4584-4592` |
| No `session_id` recorded | Excluded from the selection query outright (§4); must still be named in the report, not silently dropped, per the task's own instruction not to solve that gap here | `broker.py:4582-4583`, `store.agent_branch` |
| herdr not up yet | Every `_alive`/`_tab_for`/`start_agent` call goes through `self.h`, which raises `HerdrError` on an unreachable herdr; the sweep should catch this **once, at the top**, not per-row (a herdr that isn't up yet fails identically for every candidate) and refuse the whole sweep with one clear message rather than N identical per-row failures. `_agent_states()`'s own doc comment (`broker.py:4735-4736`) is the right model here: "None is emphatically NOT 'nobody is running': it is 'we cannot tell.'" A sweep must not read "herdr unreachable" as "nothing to restore" | `broker.py:4728-4743`, and the `HerdrError` paths through `_tab_for`/`start_agent` |
| Two people running it at once (or a human sweep racing an agent's own scoped sweep on an overlapping row) | Not separately guarded, and doesn't need to be beyond what already exists: `restore()`'s "already alive" check (§ above) means the second runner's attempt on a row the first already restored comes back a clean, reported "already running, skipped" — no double-spawn, no orphaned pane, no error surfaced as fatal. The one real race is between the two `_tab_for` calls if both racers reach an *unrestored* row within the same moment (before either write lands) — SQLite's own serialization inside a single `sb` process's transaction is not a cross-process lock here, so in the narrow window between "checked `_alive`" (4584) and "wrote the new pane_id" (4656) two concurrent `sb restore <same-name>` calls could both pass the liveness check and both spawn a pane for the same name. This is a pre-existing race in `sb restore` itself, not something the sweep introduces — worth a live check, not something to fix as part of this task |

## 7. Tests that would pin it

Following this codebase's own test style (`tests/test_broker.py`, one
behavior per test, named as a sentence):

1. **`test_restore_sweep_run_by_the_human_crosses_every_tree`** — two
   separate root trees, each with a crashed agent (mirroring the real
   incident's `github-issues`/`codex` split); `me=HUMAN`; assert both get
   restored in one call. This is the test that would have caught today's gap
   directly, and is the one the task cares about most.
2. **`test_restore_sweep_run_by_an_agent_only_reaches_its_own_tree`** — same
   two-tree setup, `me=<agent in tree A>`; assert tree A's row is restored
   and tree B's is left completely untouched (no attempt, no error raised
   about it) — pins the deliberate under-scoping from §5 rather than letting
   it regress into either a silent skip *or* a `require_same_tree` exception
   that kills the whole sweep.
3. **`test_restore_sweep_is_a_noop_on_a_second_run`** — restore a crashed
   cohort once, then call the sweep again on the same store state; assert
   every row comes back "already running, skipped" and nothing is spawned a
   second time. Pins idempotency directly rather than trusting it as a side
   effect of `_alive`.
4. (If the §3 workspace-placement fix ships alongside this) **`test_restore_after_a_dead_workspace_id_lands_back_in_the_named_space`**
   — set up a row with a `workspace_id` that `create_tab` answers
   `workspace_not_found` for (reusing the existing `_workspace_gone` helper,
   `tests/test_broker.py:3350-3359`), but where `self._workspace_id(name)`
   (stubbed, as `test_restore_brings_an_agent_back_to_its_recorded_workspace`
   already does at `3341-3346`) resolves the **name** to a *different*, live
   id; assert the restored tab lands in the name-resolved id, not a bare
   tab. This is the test that's currently missing and that would have
   caught the gap in §2.

## Summary of what changes in `switchboard/`

- **New**: a `restore_sweep` method on `Broker` (near `restore()`,
  `broker.py:4566`) and a `--sweep`/`--dry-run` pair of flags on the
  `restore` subcommand in `cli.py` (near `303-304`, `1130-1132`).
- **Changed**: `restore()`'s workspace-resolution fallback (`4599-4605`,
  interacting with `_tab_for` at `2922-2961`) needs the by-name re-resolve
  described in §3, or the sweep faithfully reproduces today's "lands in a
  random tab" behavior instead of fixing the thing the task is about.
- **Unchanged**: `require_same_tree`/`same_tree` (`951-982`) — the sweep
  respects them by construction (query scope, not a bypass), never edits
  them.

## What I could not determine from code alone

- Whether a herdr restart truly always invalidates a previously-recorded
  `workspace_id`, or whether `session.json`-based restore sometimes hands
  the same id back (§2's open question) — would need a live herdr restart
  with a real recorded id watched through `create_tab`.
- The actual cross-process race window in step 4 of the failure-mode table
  (two concurrent `sb restore <name>` calls on an unrestored row) — plausible
  from reading `_alive`→write ordering, not exercised live or in the existing
  test suite as far as I found.
