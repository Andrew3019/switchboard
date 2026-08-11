# FEATURES.md — what switchboard does

This is the maintained inventory of switchboard's features. It is derived from reading
`switchboard/*.py` and `defaults/*` directly, and from `DESIGN-TRUTH.md`, which is the
record of the decisions behind them — not from `PLAN.md`/`POC.md`/`PRINCIPLES.md`, which
describe intent and are known to be partly stale or retracted. Entry point for
everything below: `bin/sb` → `switchboard.cli.main()` (there is no pip install; the repo
is not packaged, `bin/sb` just puts the repo root on `sys.path`).

Verified by reading cli.py, broker.py, status.py, store.py, output.py, board.py,
panel.py, collector.py, hooks.py, live.py, config.py, models.py, roles.py, presets.py,
plugins.py, validate.py, herdr.py, plus every file under `defaults/`.

## Agent-facing verbs (the ones in `defaults/protocol.md`)

Six, by cli.py's own count: `delegate`, `tell`, `inbox`, `done`, `block`, `status`. The
protocol also names `sb cleanup`, `sb restore` and `sb presets` — an orchestrator sweeps
its own finished subtree, and any agent may read a written-down procedure — but those are
documented under **Human-facing verbs**, which is where they started.

### `sb delegate <task> [--role] [--as] [--with] [--name] [--workspace] [--model]`
Spawns a child agent in its own pane to do a task independently; the caller does not
wait for it — it ends its turn and is woken (doorbell) when the child calls `sb done`.
The child's pane is split once and **`sb board`** opened in the smaller half, so every
agent lands with the tree beside it (see **`sb board`**).
- Entry point: `cli.py:752-778` → `Broker.delegate` (`broker.py:2925-3168`)
- Depends on: `roles.get` (role → tier, prompt and `delegate` right),
  `presets.for_role`/`resolve` (`--with`), `models.Tiers.resolve` (`--model`),
  `store.claim_agent` (race-safe name claim), `herdr.start_agent`, `herdr.deliver`
- **Where the spawn lands is worked out here, not passed in.** A caller stamped
  `is_top` (only `sb start` writes that stamp) forks the child a new branch, worktree
  and herdr workspace named after the child; anyone else's spawn is a tab in the
  caller's own workspace, and so is that spawn's whole subtree (`Broker.mints_space`,
  `_fork_for`). The human, and a caller with no agent row, fork too — they have no space
  to lend. A fork that fails **refuses the spawn** (`ForkFailed`) rather than falling
  back to the caller's checkout, and an existing branch of that name is refused
  (`BranchTaken`).
- A fork starts from the **caller's own branch**, or from `origin/main`
  (`[vocabulary] base_branch`) when the caller is standing on main or on a detached HEAD
  (`_inherited_base`). There is no `--base`: it went with `sb workspace new`. Uncommitted
  work does not travel, and the parent is told on stderr how many files stayed behind.
- `--workspace <name>` joins a workspace that **already exists** and never creates one
  (`Broker.join_workspace`); a bare space, or a name nobody has opened, is an error
  naming the path that does open one.
- **A role that may not delegate is refused** (`_refuse_bare_delegate`). The right is the
  `delegate` field on the role, never a check against the role's name; only
  `defaults/roles/orchestrator.md` sets it. The refusal names the roles that do have it,
  generated from the role table, and tells the caller to hand the job back with `sb done`
  instead of growing a tree under itself.
- The spawn is not done until the task is confirmed to have landed in the child's own
  transcript (`herdr.deliver`, `output.task_arrived`). Unconfirmed is not failed: a name
  is still returned, with a caveat, when the child has plainly taken a turn
  (`_took_a_turn`); nothing at all to show for it raises `TaskUndelivered`.
- Status: working; has tests specifically covering name-claim races
- `--with` takes a preset name, `@<plugin>` for a plugin's fragment, or any other string,
  which is passed through as a literal instruction. `@` is a **reserved prefix**: an
  `@<name>` that does not resolve fails rather than passing through. See **Presets** for
  the three rules and for which failures are fatal.
- Config: `defaults/roles/*.md`, `defaults/models.toml`, `defaults/presets.toml`,
  `defaults/presets/*.md`, `defaults/prompts.toml [spawn] identity/roles/workspace`

### `sb tell <who...> <message> [--needs-reply] [--when-idle | --interrupt]`
Sends a message to one or more agents and returns immediately — in all three delivery
modes. No agent ever waits on another agent; there is no verb that does, and `sb ask`
was deleted for exactly that reason. Refuses `human` as a target (no mailbox to write
to) and points the caller at `sb block`.
- **Three delivery modes**, one choice with three answers (argparse enforces the
  exclusivity):
  - *next turn* — the default, no flag. The doorbell rings immediately; herdr's
    `agent prompt` queues rather than interleaves, so the in-flight tool call finishes
    and the text is waiting at the boundary after it.
  - *when idle* (`--when-idle`) — the ring is held while the target is mid-turn and
    fired by `flush_pending` once it is free. What every message did before modes
    existed, and what `sb done`'s poke to a parent still uses.
  - *interrupt* (`--interrupt`) — `esc` to cancel the turn, a settle delay, then the
    instruction itself on the wire (`Broker._interrupt`). Its text travels inline, so it
    must be one line; the other two modes only ring a fixed doorbell and may be as long
    and as multi-line as the sender likes.
- `--needs-reply` records that the sender is waiting. It changes what the **recipient**
  reads — `sb inbox` appends `[notify] needs_reply`, naming the sender and asking for an
  answer at some point — and nothing about the sender, who still returns immediately.
- Every message carries `[sb: from <name>]` (`broker.tag`): doorbell text, inline
  interrupt body and `sb inbox` output all use the same tag, so nothing sb sends can be
  mistaken for the human typing.
- Refused across the tree boundary (`require_same_tree`), before any row is written.
- Entry point: `cli.py:780-836` → `Broker.tell` (`broker.py:3223-3278`)
- Depends on: `store.put_message`, `Broker._ring` (message is deferred, not lost, if the
  target is mid-turn or blocked — see **deferred delivery** below)
- Status: working. The CLI's report names who has *not* been reached yet and why —
  waiting, `UNREACHABLE` (herdr lost the name binding, so no doorbell will ring again),
  or finished with its pane closed.
- Config: `defaults/prompts.toml [notify] mail/interrupt/needs_reply`,
  `settings.toml [timeouts] interrupt_settle`

### `sb inbox [--peek]`
Reads all of the calling agent's unread messages in one batched call and marks them
read, unless `--peek`. Each message is printed with the same `[sb: from <name>]` tag the
doorbell used; one sent with `--needs-reply` gets an extra line under it saying who is
waiting. Human callers get a fixed explanatory string — humans have no mailbox, and the
string says so and points at the board.
- Entry point: `cli.py:838-871` → `Broker.inbox` → `store.unread_for`
- Status: working

### `sb done <summary>`
Reports the calling agent finished. The summary is delivered to the parent's mailbox
(`[done] ` prefix) if it has one, and the parent's doorbell is rung **when idle** — a
child finishing is not news worth cutting into the parent's own turn, and a fan-out of
five would otherwise poke it five times. A root agent has no parent and the human has no
mailbox, so its summary is a record (event log, done row, `sb inspect`) plus a desktop
notification, because the top of a tree finishing is the one event that ends a run.
Nothing is reported to herdr, and that silence is load-bearing: any `pane report-agent`
replaces the pane's named agent rather than annotating it, so a `done` that pushed `idle`
made the agent permanently unreachable by name. Reporting done with children still
working is legal — a parent that delegated must have a legal way to end its turn — but it
is named back to the caller and logged as `done_with_live_children`; `sb cleanup` will
not close the pane while they run.
- Entry point: `cli.py:873-882` → `Broker.done` (`broker.py:3352-3423`)
- Depends on: same doorbell mechanism as `tell`
- Config: `settings.toml [vocabulary] done_prefix`, `defaults/prompts.toml [notify]
  child_done`

### `sb block <why>`
The only way an agent reaches a human. Ends the turn, records `state=blocked` in the
store, pushes a desktop notification, and shows up in `sb status --needs-me` and on the
board until a human answers. Nothing is reported to herdr here either, for `done`'s
reason and more sharply: the one verb whose purpose is "stop and get a human" must stay
answerable by name.
- The `<why>` is **one short line for the board and is delivered to nobody** — what a
  human actually reads is the agent's own chat, through `sb inspect`. `validate.reason`
  refuses an over-long reason and its error repeats the two steps: write the whole thing
  in the chat first, then block with one line. `[limits] block_reason` is the cap.
- Two things clear a block, and both are the human: `sb tell <agent> "..."` from them
  rings and unblocks (`_unblock_if_needed`), and typing straight into the pane restarts
  the agent, whose next `sb` command clears the block (`_revive`). No other agent's mail
  clears it — when-idle mail is held until the block is answered, so the answer is never
  buried under it.
- A parent is not told that its child blocked.
- Entry point: `cli.py:884-895` → `Broker.block` (`broker.py:3425-3475`)
- Status: working

### `sb status [--active/--live] [--needs-me] [--mine] [--archived]`
The whole agent tree as one join of store state against herdr's live pane state,
flagging drift: **STALLED** (store says working, herdr says idle/done, and `sb done` was
never called — but never for an agent nobody has given work to yet, which is idle for the
only reason it could be; `agents.awaiting_task`, set at spawn and cleared by the first
message), **GONE** (the pane closed under it — self-heals by writing `state=failed`, and
only after herdr has failed to list the row continuously past
`status.GONE_CONFIRM_GRACE`, so one short `agent list` cannot end a live agent),
**UNDELIVERED** (mail the target cannot know about — the doorbell never rang for it,
usually because the target was mid-turn, and the target has not read it of its own accord
either).
- **Scoped to the caller's tree.** An agent sees its own top's whole tree — siblings
  included — and no other top's; the human is bounded by nothing (`cli._scope`,
  `Broker.tree_of`). `--mine` narrows further to the caller's own subtree; the flag can
  only ask for less.
- `--archived` draws archived agents individually instead of collapsing fully-archived
  subtrees to one line. Not a filter, and `--json` always carries every row whatever the
  flags say.
- Entry point: `cli.py:897-910` → `status.collect`/`status.render`
  (`status.py:411`, `status.py:1065`)
- Depends on: `store` (agents/messages/events tables), single batched `herdr.list_agents`
  call
- Status: working
- Config: `settings.toml [states]` groupings, `[limits] task_clip`,
  `[display] show_archived`

## Human-facing verbs

### `sb init`
Pins the current repo for switchboard: writes `main_checkout` into the store's
`config.json` (`store.write_config`) and excludes linked config from `git status`. Writes
no `CLAUDE.md` — the protocol is delivered as a system prompt only, not a repo file.
- Entry point: `cli.py:715-720` → `Broker.init` (`broker.py:812-823`)

### `sb start [task] [--name]`
Starts a top-level orchestrator agent in a bare herdr workspace of its own, laid over the
current checkout — bare meaning no worktree of its own, because a top-level orchestrator
does no writes. Always another one: run with no args it takes the next free name (`main`,
`main-2`, …) and never reuses or restores an existing orchestrator — it names the ones
still running so you can get back to them. `--name` is the way back: an existing name
returns to that orchestrator, restoring it if its pane was closed, and hands it the task.
- **This is the only path that creates a top orchestrator, and it stamps one:**
  `delegate(..., is_top=True)` is written here and nowhere else (`_top`), and the fork
  rule and the tree boundary both read that stamp rather than the prompt or the role.
- **Refused from inside a worktree**, naming the main checkout to run it from: a top's
  space is laid over the checkout `sb` was run in, so starting one in somebody's worktree
  would put it, and everything it delegates that cannot fork, on that agent's branch.
- It focuses the pane it started. Nothing else focuses on spawn, and nothing can ask for
  it — there is no focus flag. The board is opened beside it and cannot be declined.
- Entry point: `cli.py:739-750` → `Broker.start`/`Broker._top` (`broker.py:825-975`)
- Depends on: `store.live_roots`, `herdr.create_workspace`/`start_agent`,
  `board.open_beside` (auto-fires here — see **`sb board`**), `config.prompt`
  (`[spawn] start_task`)
- Status: working, with detailed handling for concurrent `sb start` calls
- Config: `settings.toml [vocabulary] main_role/main_name`, `defaults/prompts.toml
  [spawn] start_task`

### `sb doctor [--reset-store [--force]]`
Health check: confirms the `herdr` binary is present, at a compatible version, and that
no conflicting herdr integration is installed. `--reset-store` drops and recreates the
sqlite schema; refuses if any agent is currently live, unless `--force`.

It is also the only verb that imports **every** plugin, which is what it is for. It
separates plugin **problems** (will not import; targets an unsupported `API`) from plugin
**notices** (an orphaned state directory, a plugin loaded from the repo rather than from
`defaults/`, pre-rename `plugins.toml`/`plugins/` spellings). Problems clear `--json`'s
`ok`; notices do not. Neither changes the **exit code**, which is 1 only when herdr itself
fails — a broken plugin is a report, not a failed health check. Nothing under a state
directory is ever deleted: `doctor` prints the `rm -rf` and the human runs it or does not.

It also prints one line about the **panel**: whether the snapshot every pane is drawing
is fresh, read off the counters the collector already writes into its snapshot file
(`panel.doctor_line`), so it costs no store write. It does not display the reconciler's
counters.
- Entry point: `cli.py` `doctor` branch → `Herdr.check` / `store.reset` /
  `_doctor_plugins` → `plugins.load_all`/`plugins.orphans`/`presets.deprecations`
- Status: working. The store has no migration system by design, and the hash is only a
  cache key: what the store actually lacks is read off `PRAGMA table_info`. Nullable
  columns are ALTERed in and a whole missing table whose columns are all nullable is
  created and backfilled; only a gap no existing row can be given (a `NOT NULL` column
  with no literal default) forces the full drop/recreate, which is then deferred rather
  than refused while agents are live (`store.connect`/`_reconcile`/`_deficit`). See
  `BUGS.md` #4 for the case where this deadlocked running agents.
- Not checked: whether a plugin imports `switchboard` internals. `design/PLUGIN-REDESIGN.md`
  §4.6 asserts this check; it is deliberately not built, and §4.6 says why.
- Config: `settings.toml [herdr] min_version`

### `sb cleanup [name...] [--force] [--dry-run]`
Closes finished agents' panes — never their history; `sb restore` brings a closed agent
back. With no names, sweeps the caller's own subtree (or everything, for a human). Four
layered safety gates: must be finished with no unread mail it could still read — mail for
an agent that has finished and whose name no longer binds holds nothing, since nothing can
ever announce or read it, and the row would otherwise jam forever; an end that no agent
reported (`failed`, by `status._record_gone`) is re-checked against `agent list` and left
alone if herdr still has the agent **or cannot be asked**; `--force` lifts those two but
only alongside an explicit name, since naming an agent is the confirmation; and **no agent
is closed while a descendant is still `working` or `blocked`** — the invariant that an
agent with no pane has no live children under it. Nothing lifts the last one, `--force`
included, because it is a fact about agents the caller did not name; the way out is to
close the subtree from the leaves up.
Closing an agent also closes the **`sb board`** pane opened beside it
(`Broker._close_board`), so no empty tab is left behind — never a board another live
agent is on, and a board already closed by hand is not an error.
- Entry point: `cli.py:982-1007` → `Broker.cleanup` (`broker.py:3485-3698`)
- Status: working. The disposition flags are gone (`--keep`, `--ephemeral`,
  `--include-kept`, `--leave-children`): cleanup is the orchestrator's and it always
  takes the children. The store's per-agent `cleanup` column and its gate survive so that
  a row written before the flags went keeps behaving exactly as it did — held back by a
  sweep, closed when named. **Nothing writes that column any more**, so for every agent
  spawned since, it is `close` and the gate never fires.
- Every gate that holds a row back records its reason and logs `cleanup_refused`. A named
  agent is refused before anything at all is closed; a sweep prints its notable refusals,
  bounded to five with a tail line.

### `sb workspace` — two halves, and no `new`
A workspace is one named place to work: one git worktree, one herdr workspace, one
branch, however many agents. **`sb workspace new` no longer exists**; a space is minted
by exactly one path, a top orchestrator's `sb delegate` (the child's name is the
workspace, the branch and the checkout), and joined by `sb delegate --workspace <name>`.
What is left of the verb is the read half and the teardown half below, which are the
human's. Two guards the deleted verb held moved into `_fork_for`: a workspace mid-teardown
is refused, and so is a name a bare space already owns.

### `sb workspace list`
Every workspace this repo has and what stands in the way of each one ever going away —
the cross-reference that otherwise means reading `git worktree list` against the store by
hand. Built from the **union** of three sources — git's worktrees, the `workspaces` table,
and the distinct workspace names on agent rows — because none of them is a superset of the
others: only git knows a checkout no agent was ever recorded in, only the table knows a
retired workspace with neither checkout nor rows, and only `agents` knows a workspace that
predates or escaped the table. Bare workspaces are why git cannot be the starting point:
`git worktree list` reports the primary checkout once, so four orchestrators laid over it
are four names and one line. Per workspace it answers what somebody tidying up is actually
deciding on — the recorded path and which verdict it gets (`ok`/`absent`/`unusable`, or
`retired`/`bare`), how many agent rows it has and how many are unfinished, whether it is
retired or currently being closed and by whom, the branch a safe delete would have to get
past and whether that branch is unmerged, the weight of ignored content a removal would
take with it, and whether anything is live under the path. `UNKNOWN` in the live column is
not the same cell as "clear": a scan that could not be made is not the answer "nobody is in
there", and printing them the same way is how a person comes to believe the wrong one.
- Entry point: `cli.py:1009-1012` → `Broker.workspace_list` (`broker.py:1237-1285`), rendered
  by `cli._workspace_listing`
- Depends on: `store.all_workspaces`/`get_workspace`/`checkout_verdict`/
  `workspace_fill_gap`, `live.scan`/`live.is_under` (`switchboard/live.py`), `git worktree
  list --porcelain`, `git status --porcelain --ignored`
- Status: working, and read-only by design — one `lsof` scan serves the whole listing,
  since asking twenty times would be twenty different snapshots of the machine. This is
  where the two signals `sb workspace close` is gated on get exercised somewhere being
  wrong costs a wrong line of text. `tests/test_workspace_list.py`, `tests/test_live.py`
- Note: an incomplete `workspaces` backfill is said first, above the table
  (`store.workspace_fill_gap`), because a listing built on partial records is not the whole
  story and reads exactly like one that is.

### `sb workspace close <name> [--yes] [--resume]`
Ends a workspace's life and destroys its checkout when it has one — a separate, explicit
verb, never something another command does on the way past. Three routes, chosen by what
the recorded path resolves to and never by a flag, and the two cheap ones are their own
code rather than the destructive one with steps skipped. A workspace with **no checkout of
its own** is retired and nothing else — no path gate, no live observation, no inventory, no
git at all, since nothing there can be lost and the directory it was laid over is the
human's own clone; its only gate is that its own agent rows are finished. One whose
directory is **already gone** is deregistered — by name, never a repo-global `git worktree
prune`, which would take every prunable checkout in the repository with it — and its branch
safely deleted when anything can name that branch. A checkout **still on disk** takes the
destructive route, which is check → stop the panes → check again → delete: the second
evaluation is what authorises the deletion, because it sees what arrived while the panes
were coming down, and the first exists so a refusal costs only its message rather than
somebody's panes. That second check waits, briefly and boundedly, for the panes it has just
closed to leave the process table — measured rather than assumed, an idle shell and a shell
with an ordinary child are gone before the scan lands, but a process that catches the hangup
and winds down over half a second is still there every time, which is the shape of an agent
shutting down cleanly and would otherwise be the one refusal that costs a person their
panes. It is a delay and never an exemption: the pids of those panes still count, so
anything still in the directory when the wait expires refuses exactly as it always did, and
a scan that could not be *made* refuses on the spot rather than being retried. An
unresolvable path is a refusal and never a fallback to the repo root.

A name with **no record of its own but a checkout git knows about** is recorded first and
then takes whichever of the three routes its path earns — that is exactly the case `sb
workspace list`'s three-source union exists to surface, and listing something no verb can
close is half a feature. Being adopted buys it no trust: the path is re-validated to choose
the route, and the gate, the inventory, the confirmation and the primary-checkout refusal
all run as they would for a workspace that had a row all along.

Almost all of the command is the refusing, and refusing is the ordinary outcome rather than
the exception. It refuses any unfinished agent row whose cwd sits under the checkout —
component-wise, never as a string prefix, since sibling checkout names nest as strings —
minus the caller's own row; any process actually sitting in the directory, ours or not,
minus the caller's own process tree; work git can see, outright, because that is work a
person can commit or stash and ask again (ignored content is classified against
switchboard's own symlinks instead, and only *unrecognised* ignored content demands `--yes`,
quoting a count and a sample); the repository's primary checkout, by an explicit rule
rather than by letting git object at the last step, when the inventory has already listed
the human's `.env` and the panes are already closed; and a workspace already being taken
apart. The one people find surprising is that it also refuses when it **cannot tell** what
is running: herdr's `agent list` has no failure branch, so a restarted herdr answers an
empty success that reads identically to an empty workspace — unknown is not empty, and a
scan that cannot be made is a mandatory refusal. The scan that *can* be made has a limit of
its own, said here rather than papered over: an unprivileged `lsof` omits every process the
caller does not own and still exits 0, so what it really answers is "nothing of **mine** is
in that directory", and a root-owned daemon or a `sudo`-run editor sitting in the checkout
is invisible to the gate about to delete around it. Widening that means elevated
privileges, and narrowing the refusal to match what it can see would mean lying. The
retiring mark is claimed before
anything is destroyed and released by every refusal after it, so only a crash can leave one
behind; a mark that is set discloses its owner and when it was claimed, and the refusal
names `--resume` unless that owner is confirmed *live* — which re-runs the whole command
from the start rather than inheriting a dead invocation's findings. Not "confirmed gone",
and the difference is the whole point: an owner nobody can adjudicate is the ordinary case
rather than the exotic one, since a human holds no agent row and so can never be confirmed
gone, and a human is the likeliest caller of a destructive command. Under the stricter rule
a mark left behind by a person's crashed teardown was reachable by no flag and no caller at
all, the name refused by every other verb as well. What must never happen is a live mark
being taken *automatically*, and a flag somebody types is the opposite of automatic — so an
unadjudicable owner is offered it and a confirmed-live one is still refused it. Everywhere
else in this command, cannot-tell still reads as live.

Three things it deliberately never does, all settled decisions approved by the human rather
than unfinished edges. An unmerged branch is never force-deleted — `git branch -d` and
never `-D` — so it simply stays, forever, until a person decides otherwise; the command
says so out loud, because somebody who does not know that is somebody who thinks the
cleanup finished. It never guesses which branch that `-d` is aimed at either: the branch is
the one a row recorded, else the one git's registry reports for that checkout, looked up
before the deregistration takes that entry away — never the workspace's own name, which
looks like the same fact only because a fork names the branch after the workspace. When
nothing names a branch, none is deleted and the output says exactly that, which is different
news from a branch kept because it is unmerged: a person told the second goes looking for a
branch, and a person told the first knows there was never one to find. That is deliberately
not a refusal — the only state it could fire in is one where retiring destroys nothing and
refusing would strand the name in a row no verb could ever retire, and the cost of not
refusing is one orphan branch a person can see and delete. And old agent records are never
reclaimed: retiring a workspace closes panes and clears the recorded path, and every row,
summary, message and transcript survives.
- Entry point: `cli.py:1014-1020` → `Broker.workspace_close` (`broker.py:1420-1476`) →
  `_adopt_orphan`/`_close_bare`/`_close_gone`/`_close_checkout`, rendered by
  `cli._workspace_closed`
- Depends on: `Broker._gate`/`_records_gate`/`_inventory_gate`/`_live_under` and
  `live.processes_in`, `Broker._stop_panes` (herdr `release_agent`/`close_pane`, plus the
  agent's **`sb board`** pane), `Broker._branch_for` over `store.workspace_branch` and `git
  worktree list`, `store.checkout_verdict`/`record_workspace`/`claim_retiring`/
  `release_retiring`/`retire_workspace`, `git worktree remove <path>` and `git branch -d`
- Config: `settings.toml [timeouts] teardown_settle` (how long the second check waits for
  closed panes to leave) and `teardown_settle_poll`
- Status: working. Its "is this owner really gone" question is asked of the same trust
  layer `sb cleanup` uses rather than re-derived, and herdr keeps its veto in the one
  direction it can be trusted in: a name it lists right now is running, whatever the row
  says. `tests/test_workspace_close.py`

### `sb restore <name>`
Brings a closed agent back with full context via herdr `--resume`, into a fresh tab in
its recorded workspace, on the model tier it was originally spawned with. The restored
pane is pinned to the spawning checkout's `bin/sb` and carries the Stop hook, exactly as
a fresh spawn does.
- **Refused when the checkout is gone**, naming the branch the work is on instead: herdr
  silently substitutes `$HOME` for a `--cwd` that does not exist, so restoring into a
  removed worktree used to report success and put a live agent in the human's home
  directory. Restore is gone once the worktree is; the push is the recovery path.
- Also refused for an agent that is already running, into a workspace mid-teardown, and
  across the tree boundary.
- Entry point: `cli.py:1022-1025` → `Broker.restore` (`broker.py:3748-3848`)
- Status: working

### `sb inspect <name> [-n] [--events]`
Everything about one agent in one call: task, state + drift diagnosis, workspace/pane/
cwd/session, unread and undelivered mail, its last `sb done` summary, recent events, and
a tail of its terminal output. Refused across the tree boundary before anything is read —
it is the widest read in the CLI and takes a bare name.
- Entry point: `cli.py:1027-1037` → `status.inspect`/`status.render_detail`
  (`status.py:1344`, `status.py:1420`), which calls `output.read_output`
- Depends on: `output.py` (reads the live herdr pane, falling back to the on-disk Claude
  Code JSONL transcript if the pane is gone), `store.transcript_path`
- Status: working. Subsumes a former `sb output` verb — that verb no longer exists;
  `output.py` is called directly by `inspect` now.
- The two "unanswered in both directions" blocks (`status._unanswered`) select
  `messages.kind = 'ask'`, and nothing writes that kind any more — `sb ask` is gone and
  `tell` writes `tell`. They can only ever match rows older than the removal.
- Config: `settings.toml [display] output_lines/events`, `[limits] output_clip`

### `sb log [--agent] [-n]`
Prints recent rows from the append-only `events` table. Debugging only. An agent sees
only its own tree's events, plus the ones that name no agent — a store-wide failure
belongs to the machine, not to somebody's tree.
- Entry point: `cli.py:1039-1051` → `store.recent_events`

### `sb presets [<name>] [--apply]`
With no argument, lists available preset files and which roles/bindings use them. Naming
one **prints its prose** instead — unflattened, comments stripped — which is how a preset
that is bound to nothing gets read at all. Read-only and load level 1 (no plugin import),
so an agent can run it mid-turn.

`--apply` is the third thing: it pastes the named preset into the **caller's own session**
as a message rather than printing it — a store row, the `[sb: from <name>]` tag, and
`_ring` at next-turn (`Broker.apply_preset`). Command output is something an agent read; a
message is something it was told, and only the second is durable, framed as an instruction
and visible in `sb inspect`. There is no confirmation step. A human has no session to
paste into and is told so; `--apply` with no name is a usage error rather than a silent
listing.
- Entry point: `cli.py:912-952` → `presets.available`/`presets.bindings`/
  `presets.text`, `Broker.apply_preset` (`broker.py:3292-3348`)
- Config: `defaults/presets.toml`, `defaults/presets/*.md`, repo's
  `.switchboard/presets.toml` and `.switchboard/presets/*.md`
- Note: the naming form exists because of `adversarial` — see **Presets** below. An
  unknown name exits 1 and lists the ones that do exist.
- Lists preset **files** only. A plugin fragment bound with `@<name>` has no file to glob,
  so it gets no row here even though it is injected into every spawn it is bound to;
  `sb plugin list` is where those bindings show up. Two commands, one question — worth
  knowing before concluding from `sb presets` alone that nothing is being injected.

### `sb plugin list`
Lists every plugin this repo can see, with its `VERSION`, its status
(`ok` / `not enabled` / `incompatible` / `broken`) and its bindings. Each import is wrapped
per plugin, so a broken one is a row saying so rather than a traceback; `SB_DEBUG=1` adds
the tracebacks after the table.
- Entry point: `cli.py` `plugin` branch → `_plugin_list` → `plugins.load_all`
- Config: `defaults/plugins.toml`, repo's `.switchboard/plugins.toml`, both plugin roots
- Note: two plugins ship — `report-bug` (enabled and bound to every agent) and `todo`
  (present but **not enabled**, the shipped example of available-without-being-enabled).

### `sb plugin <name> <verb> …`
Runs a command a plugin declared. The top-level parser takes the rest as `REMAINDER`; the
plugin's own arguments are parsed by a subparser sb builds from what its `register()`
declared, so `--help`, flag-level errors and `--json` are sb's throughout. sb creates the
state directory, takes an exclusive `flock` around the handler, enforces the command's
`audience`, and logs one event per dispatch.
- Entry point: `cli.py` `_validate_plugin` (resolve, import, parse) → `_plugin_run`
- Depends on: `plugins.must_load`/`build_parser`/`state_dir`/`locked`/`run`,
  `store.repo_root` (repo identity), `store.log_event`
- Status: working — `sb plugin report-bug …` dispatches out of the box; `sb plugin todo …`
  does not until the repo enables it. `tests/test_plugins.py` exercises the contract and
  `tests/test_shipped_plugins.py` the two that ship
- Config: `settings.toml [paths] plugins_dir/plugins_file/user_state/store_dirname`

### `sb plugins` — retired
This verb listed prompt fragments; the word "plugin" now means code, so the verb split in
two. It is still *registered* — hidden from `sb --help`, but present — so that typing it
gets a sentence naming both replacements (`sb presets` for prompt text, `sb plugin list`
for code plugins) and exit 2, rather than an argparse usage dump that names neither. Kept
for one release, then removed. The `--json` key was renamed from `plugins` to `presets` at
the same time so the two payloads cannot be confused.

### `sb models`
Prints the resolved tier → (provider, model, effort, CLI flags) table for this repo,
marking any tier "UNAVAILABLE" if its provider has no backend wired.
- Entry point: `cli.py:957-980` → `models.load`/`models.Tiers.resolve`/
  `models.ModelSpec.cli_args`
- Config: `defaults/models.toml`, `~/.config/switchboard/models.toml`, repo's
  `.switchboard/models.toml`

### `sb board` — hidden, human-only
A clickable live view of the agent tree (glyphs, click-to-focus, scroll), periodically
refreshed. It is a **renderer**: it holds no database handle and does not import `store`
at all, reading the snapshot one elected collector publishes (see **The panel**). Its only
side effect is `herdr agent focus` when a human clicks an agent.
- Entry point: `cli.py:114` (registered `hidden=True`, so it does not appear in
  `sb --help`) → `broker._open_board` / `board.main`/`board.open_beside`
  (`switchboard/board.py`)
- Depends on: `panel.py` (the published snapshot), `herdr.split_pane`/`focus`/`pane_ids`
- Status: **working and reachable — not dead code.** Two ways in: (1) `sb board` is a real
  subcommand — `cli.py:724-737` dispatches it, gated to refuse any caller `whoami()`
  resolves as an agent; (2) `Broker.delegate` calls `_open_board` → `board.open_beside` on
  every spawn, so each agent — top orchestrator, workspace lead or delegated child — opens
  with a board beside it. There is no declining it: `--no-board` is gone, and every
  sb-made view is split with the board. `_top` asks a second time, which is a no-op when
  the board is already up and is what covers a restored agent. The board is the SMALL pane
  (`board.BOARD_SHARE`, a third of the width): what a human reads is the agent's own
  session. Note herdr's `--ratio` is the share kept by the pane being split, so
  `open_beside` passes `1 - share`. The pane switchboard opened is a pane switchboard takes
  away: `sb cleanup` closes it with the agent (`Broker._close_board`), which is what keeps
  a session from filling with empty tabs now that every agent has one. It is deliberately
  absent from `--help` and from `defaults/protocol.md` — hidden from agents on purpose, not
  orphaned. `tests/test_board.py` exercises it, and `scripts/05-mouse.py`/
  `scripts/06-board.py` are kept as the proof-of-concept record the maintained version was
  built from.
- Config: `settings.toml [display] board_refresh/board_chrome`, `NO_COLOR` env var

### `sb flush` and `sb reconcile` — hidden, machinery
Neither is vocabulary, so neither appears in `sb --help` or in `defaults/protocol.md`, and
an agent is not taught them. Both are what the collector's loop runs so the fleet does not
depend on somebody typing a command:
- `sb flush` is the doorbell tick with nothing after it. Every `sb` invocation flushes
  before it dispatches; this is that and only that, so mail held back while its target was
  mid-turn gets announced on a timer.
- `sb reconcile` runs `Broker.reconcile` in a short-lived process on current code. It
  never raises out to the caller — a failure on an unattended timer is a line in the event
  log, not a traceback nobody reads.
- Entry point: `cli.py:591-607`. Both are load level 0.

## Not verbs, but load-bearing

### Deferred message delivery ("the doorbell")
`Broker._ring` and `Broker.flush_pending`, run at the top of every `sb` invocation
(`cli.py:585-589`) and on the collector's own timer. The doorbell carries no payload — the
message is in the store — and what a mode decides is only what happens to a target that is
mid-turn: *when-idle* holds the ring (`ring_deferred`) until `flush_pending` fires it,
*next-turn* rings anyway (`agent prompt` queues at the tool-call boundary rather than
interleaving, measured against three 90-second single tool calls), *interrupt* rings anyway
and its caller has already sent `esc`. Underlies `tell`, `done`, `block` and
`sb presets --apply`; surfaced to humans in `sb status`/`sb inspect` as `UNDELIVERED`.

A **blocked** agent is not idle, so every mode but interrupt is held for it — the one
exception being the human's own answer (`answer=True`), which is the only ring that clears
a block. Without that rule a sibling's unrelated mail put a stopped agent back to
`working` and buried the answer it was waiting for.

The flush and both readouts ring/count on the same predicate — un-announced AND unread —
so mail an agent read proactively while mid-turn drops out of all three rather than being
chased forever. An agent that has finished and lost its name binding is not rung at all,
and its backlog is stamped so nothing retries it forever. Nothing is discarded — the
message is still in the store and `sb restore` brings back an inbox that holds it. Unknown
is never gone: the guard needs a positive answer from herdr, so a herdr outage cannot
silence a live fleet.
- Entry point: `broker.py` `Broker._ring` (`4164`), `Broker.flush_pending` (`4011`)

### The Stop gate — a turn cannot end without a report
`switchboard/hooks.py` plus `bin/sb-stop-hook`. Every spawn and every restore is handed
`--settings <file>` naming a per-repo JSON that installs a `Stop` hook; only agents
switchboard spawns ever see it, and no file of the human's is written or read. The hook
prints `{"decision": "block", …}` and the agent gets another turn with a reason telling it
to call `sb done` or `sb block`.

Everything about it fails **open**: a caller it cannot resolve, a store it cannot open, a
payload it cannot parse and any exception at all let the turn end. Three legitimate ends
without a report are exempt — an agent still holding its placeholder task
(`awaiting_task`), a parent with a live child (logged as `stop_gate_waived`, because that
is the one exemption that could hide a real silent finish), and an agent that has already
reported. **An agent is stopped once per silence**, not repeatedly: the cap is read from
the event log (`stop_gate_blocked` newer than any `done`/`blocked`), because the CLI's own
`stop_hook_active` flag is scoped to one stop-chain and anything that pokes the agent
starts a new one.
- Entry point: `hooks.stop_gate`/`hooks.run`, `hooks.settings_file`/`stop_hook_args`,
  called from `Herdr.start_agent`

### The reconciler — one ping to an agent that went quiet
`Broker.reconcile` (`broker.py:4380`), triggered by the collector every `RECONCILE_GAP`
seconds and swept every `RECONCILE_SWEEP`. It pings every agent `status` already calls
`stalled` — row says `working`, herdr says alive and idle, not still awaiting its task —
with `[notify] stalled`: your turn ended without a report, run `sb done` or `sb block`, and
this is asked once.

**The ping goes to the agent, never to its parent**: the agent is the only party that knows
whether it is finished, stuck, or wrong about having finished. Three exemptions, and no
more: blocked and finished agents are never `stalled` at all, `awaiting_task` is exempt,
and a parent with a live child is waived (logged) for the Stop gate's reason. **Once per
stall**: a second ping needs the agent to have done something since the last one, with
`REPING_GAP` (600 s) underneath as a backstop. It deliberately does not use `_ring` —
that marks the whole mailbox announced, which would lose an announcement this nudge never
made — and it logs against no agent, so the ping cannot reset the idle clock it reads.

### The panel — one collector, many renderers
`switchboard/panel.py` (renderer half) and `switchboard/collector.py` (collecting half).
One elected process per repo — elected by an `flock` it holds for its whole life —
collects the tree every `[display] board_refresh` seconds and publishes
`Snapshot.as_dict()` (`sb status --json` verbatim) to `panel/snapshot.json`; every pane
reads that file. Polling goes from O(N) to O(1), but cost is not the reason it exists:

    A RENDERER IMPORTS `status` AND NOT `store`.

`store.connect()` re-stamps `meta`, CREATEs and ALTERs tables, and rebuilds the store
outright when something missing can be given to no existing row. The split makes
"39 of 40 panes cannot write" a fact about which modules are loaded rather than a claim
somebody has to keep defending — checked statically and at runtime by
`tests/test_panel.py::RendererImports`.
- The collector connects `readonly=True` and collects with `reap=False`, because it
  outlives the code it started with: it must not migrate a schema or end an agent's turn
  on stale rules.
- **It restarts itself when its own source changes.** Every `SOURCE_CHECK_GAP` (45 s) it
  hashes `switchboard/*.py`; a difference from what it started with makes it exit, and the
  next renderer starts a replacement with a fresh import. Being version-stale is safe for
  the store and was never safe for the decisions — the doorbell rule it runs is
  `status.py`'s, and a fix sitting on disk while the old rule kept running cost about four
  hours of held mail.
- **It cannot become a daemon nobody owns.** Renderers stamp `panel/demand` as they draw,
  and it exits once nothing has looked for `[panel] collector_idle_exit` seconds.
- It is also what rings the doorbell and what triggers the reconciler, and it does both by
  **spawning `sb`** — this checkout's `bin/sb`, not whatever the pane's PATH resolves — so
  the write is made by code running now and the collector keeps its two invariants.
- A failing tick keeps the last good snapshot, bumps `errors`, and leaves `collected_at`
  alone, so the age every pane prints keeps growing rather than holding a wrong answer
  still. `sb doctor` reads those counters.

### Identity resolution
`Broker.whoami` (`broker.py:530`) resolves the calling agent from the
`CLAUDE_CODE_SESSION_ID` or `HERDR_PANE_ID` env vars that switchboard injects into every
spawned pane. A finished agent that calls `sb` again is auto-"revived" to `working`.
- Depended on by: every agent-facing verb (it's how `sb` knows who's calling)

### Structure: who may spawn, and who may see whom
Three rules, all in `broker.py`, all read off data rather than off names:
- **Only `sb start` creates a top orchestrator**, stamping `agents.is_top`.
  `Broker.mints_space` reads that stamp, so a top's `sb delegate` forks a new space and
  worktree and everyone else's spawn is a tab in the caller's own space. It used to read
  worktree possession, which coincides with top-ness for the agents that happen to exist
  and is not the same fact.
- **A role without `delegate = true` may not spawn** (`_refuse_bare_delegate`).
- **The tree boundary.** `top_of`/`tree_of`/`same_tree` walk the parent chain to its root
  and answer "which top's tree is this". `tell`, `status`, `inspect`, `log` and `restore`
  are all bounded by it; `cleanup` keeps its own tighter descendants rule. Siblings stay
  visible to each other, agents the human spawned straight from a terminal are one group,
  and the human — and the board — cross freely. The refusal says it is a boundary, so it
  cannot be mistaken for a typo.

### Config linking into worktrees
`Broker.link_config` (`broker.py:765`) symlinks `CLAUDE.md`/`.switchboard` from the
main checkout into each new worktree, so config is not duplicated per-worktree, and
excludes the symlinks from `git status` via `.git/info/exclude`.
- Depended on by: every spawn that forks a worktree (`Broker.delegate`)

### Layered config (`defaults/` → `.switchboard/`)
`config.py` merges layers, most-general first: `defaults/` (shipped, complete on its own),
then — for presets — `<repo>/.switchboard-shared/` (the repo's **committed** config, see
below), then `<repo>/.switchboard/` (that repo's machine-local differences only). Merge
rules (`config.merge`, `config.py:215`), applied per file type:
- Tables merge key-by-key (overriding one field of a role/tier leaves the rest).
- Scalars replace outright.
- Arrays join (base items, then override's new items, de-duped) — unless the override
  array's first element is `"!reset"`, which discards the base instead.
- `roles`: three sources merged field-by-field: `defaults/roles/*.md` →
  `<repo>/.switchboard/roles.toml` → `<repo>/.switchboard/roles/*.md`
  (`config.roles`, `config.py:380`).
- `models`: `defaults/models.toml` → `~/.config/switchboard/models.toml` (or
  `$SWITCHBOARD_MODELS_CONFIG`) → `<repo>/.switchboard/models.toml`, per-tier
  (`models.load`, `models.py:230`) — the only layering with a global per-user middle tier.
- **The committed layer, `.switchboard-shared/`.** It exists because `.switchboard/`
  cannot travel: it is gitignored, and in a worktree it is a symlink git refuses to track
  through — so a repo's own rules for its own agents reached nobody who cloned it, least
  of all a throwaway clone. Presets are the two things layered through it today: bindings
  (`config.preset_bindings`, shipped → shared → local) and preset **files**
  (`presets.available`, same order). Its name, like `.switchboard`'s, is read from the
  *shipped* settings only.
- `presets.toml` bindings join shipped + shared + repo's (`config.preset_bindings`). Preset
  **files** are layered by name out of `defaults/presets/*.md`, and a later layer's
  `presets/<name>.md` replaces the earlier one of that name. The shipped
  bindings are **not** empty (`all = ["@report-bug"]` plus a `[roles]` table), so a repo
  that adds one is adding to those rather than starting from nothing. The pre-rename
  `.switchboard/plugins/` and `plugins.toml` are still read when a repo has not moved them
  (`config.path_for_legacy`).
- `plugins.toml` enablement (`enabled = [...]`) joins shipped + repo's
  (`config.plugin_enablement`); plugin *packages* are layered by name out of
  `defaults/plugins/<name>/`, a repo's directory replacing a shipped one of that name
  wholesale. `plugins.toml` carries both meanings during the transition — `all`/`[roles]`
  are pre-rename preset bindings, `enabled` is plugin enablement — and the keys are
  disjoint, so a file holding both parses correctly as both.
- `protocol.md` is the one exception to "join": a repo's `.switchboard/protocol.md`
  **fully replaces** the shipped one (`config.protocol`, `config.py:441`), rather than
  merging.
- `prompts.toml`/`settings.toml` merge entry-by-entry / table-by-table.
- `[paths] repo_dir` and `[paths] shared_dir` (the names `.switchboard` and
  `.switchboard-shared` themselves) are read only from the *shipped* `settings.toml` — a
  repo cannot use its own settings file to relocate its own settings directory
  (`settings.toml:8-9`, `config.py:78-102`).
- `SWITCHBOARD_DEFAULTS` env var replaces the whole `defaults/` directory (used by tests).
- Reads are cached by `(path, mtime_ns, size)` (`config.py:147-195`).
- Entry point: `switchboard/config.py`
- Depended on by: nearly everything — roles, models, presets, prompts, protocol,
  timeouts/paths/vocabulary settings all resolve through this layer

### The store
Sqlite schema for agents/messages/events/workspaces (`switchboard/store.py`). No migration
system: the store is compared against what this code needs, column by column. Nullable
columns are added in place, and so is a whole missing table whose columns are all nullable
— each with a one-time backfill, recorded so it cannot be skipped. Only a gap that no
existing row can be given forces a full drop/recreate; that is deferred while agents are
live (the old store stays open and degraded, and the next `sb` after the fleet drains
rebuilds it) and can be demanded outright via `sb doctor --reset-store --force`.
- Depended on by: every verb above

### The herdr adapter
`switchboard/herdr.py` wraps the external `herdr` CLI (pane/workspace management, agent
liveness, prompt injection). Nearly every verb above calls into it. `sb doctor` checks it
directly.

## Presets
Called "prompt plugins" until the word was needed for code that runs: a preset is markdown
and cannot run, a plugin is Python and can.

Three preset *files* ship (`defaults/presets/*.md`) and `defaults/presets.toml` ships the
bindings for them:

| preset | bound to | what it is |
|---|---|---|
| `evidence` | `researcher`, `reviewer`, `qa` | report only what you verified, and point at it precisely enough to be checked |
| `verify` | `qa` | find how *this* repo runs its checks and run them before reporting done — it deliberately names no command |
| `adversarial` | **nothing** | a procedure an orchestrator runs: one long-lived proposer, a fresh reviewer with an unrepeated lens each round, sequentially until nothing changes or four rounds are up |

Plus `all = ["@report-bug"]`, the one fragment every agent carries whatever its role.

Shipping a file only makes a preset available; a binding is what makes it applied. The
mechanism (`presets.available`/`bindings`/`for_role`/`resolve`/`text`) is wired into

This paragraph was wrong twice before, in both directions, and the correction is worth
keeping visible: it once said preset files ship *inert with zero shipped bindings* while six
files shipped and, later, while two bindings shipped. The claim to check when this changes
again is not "does anything ship" but "which of the two lists is non-empty" — they move
independently and always have.
`sb delegate --with`, `sb presets`, and `sb presets <name> --apply`, which pastes one into
a running agent's own session. An unrecognized `--with` name is treated as a literal inline
instruction, not an error.

Preset files layer in three: shipped, then the repo's committed `.switchboard-shared/
presets/`, then its machine-local `.switchboard/presets/`. A repo's own house rules
therefore travel with a clone, and a later fragment beating the protocol — this repo's own
`house-rules` overrides the shipped shipping rule — is the layering working rather than a
contradiction.

`adversarial` is the case that shaped `sb presets <name>`. It is bound to nothing on
purpose: it was a reviewer's disposition, which made every review adversarial and made
"run an adversarial review of this" impossible to *say*, since there was no procedure
anywhere. Now the orchestrator role points at it by name and the orchestrator reads it
when the job comes up, so an occasionally-used procedure is not paid for on every spawn
that might one day want it. It is also the one preset whose layout matters — it is read as
prose, never flattened.

One notation covers both kinds of prompt text, in `presets.toml` and in `--with` alike,
and the `@` sigil says which is meant (`presets.resolve`). Three rules, in order:

| the name | what happens |
|---|---|
| `@<name>` | that plugin's `agent.md`, or a failure — the `@` prefix is reserved, and never passes through as a literal |
| a bare name matching no preset file but matching an enabled plugin | an error naming the sigil: `'todo' is a plugin fragment — write '@todo'` |
| any other bare name | unchanged — preset file if one matches, otherwise a literal instruction |

**Failure is asymmetric for `@<name>` and only for it.** A fragment named explicitly (it is
in `delegate`'s `extra`, i.e. `--with`) that will not resolve is an error; one that arrived
from a binding is skipped with a line on stderr and a `fragment_skipped` event, because
delegation must not fail over a half-installed plugin. A name in both counts as explicit.
The bare-name error is not asymmetric: an unresolvable `@name` is a fact about this
machine, while a bare plugin name is wrong in the file wherever it is read.

## Plugins
A plugin is a Python package sb imports — `defaults/plugins/<name>/` or a repo's
`.switchboard/plugins/<name>/`, holding an `__init__.py` that defines `register(reg)`. It
owns a CLI verb and a directory of durable state.

**Two plugins ship**, and `defaults/plugins.toml` is `enabled = ["report-bug"]` — one on,
one off. `todo` is present and available but not enabled and not bound: it is the shipped
example of the three states being separately settable, and turning it on is one line.
Default-on for `report-bug` is the single-user assumption spent deliberately, not an
oversight; the reasoning and the trigger to reverse it are in `design/PLUGIN-REDESIGN.md`
§11 item 8.

| plugin | `SCOPE` | ships | what it is |
|---|---|---|---|
| `report-bug` | `user` | enabled, bound to every agent | files a markdown bug report per machine rather than per repo, so it is findable from anywhere. Carries a bounded tail of the filing agent's session. |
| `todo` | `repo` | available only | a deliberately dumb shared list, per repo identity, shared across worktrees. Humans and agents use the same CLI. |

Three states, separately settable: **available** (present in either root), **enabled**
(listed in `plugins.toml` — its commands dispatch and it gets a state directory), **bound**
(`@<name>` listed in `presets.toml` — its `agent.md` is flattened and appended to the spawn,
riding the existing `with_` list in resolution order with no slot of its own).

Two plugins ship, and between them they demonstrate all three states:

| plugin | scope | state |
|---|---|---|
| `report-bug` | `user` (`LOCK = False`) | enabled in `plugins.toml`, and bound to every agent by `all = ["@report-bug"]` — an agent that works around an sb bug silently costs everyone after it more than the bug did |
| `todo` | `repo` (`LOCK = True`) | available only. It was enabled and bound and came off both: the fragment is paid on every spawn forever and a shared list repays that only if somebody is actually working from it. One line in either file turns each half back on |

Enabling and binding stay separate precisely so "use `sb plugin todo` myself without taxing
every spawn" is a thing you can say.

A fragment is capped at `[limits] plugin_fragment = 4000` characters, against
`text = 40000` for traffic and `prompt = 80000` for presets and role prompts. Over-budget
text is truncated at a word boundary with a `fragment_truncated` event, never rejected: a
chatty plugin must not break spawning.

The load model is the load-bearing part. Four levels, and the assignment of verbs to them
is fixed and tested (`tests/test_plugins.py::IsolationTest`):

| level | operation | verbs |
|---|---|---|
| 0 | nothing | `status`, `done`, `tell`, `inbox`, `block`, `log`, `cleanup`, `inspect`, `init`, `restore`, `board`, `models`, `flush`, `reconcile` |
| 1 | glob the roots, merge `plugins.toml` | `presets` |
| 2 | + read `<plugin>/agent.md`, flatten | `delegate`, `start` |
| 3 | + import, call `register()` | `plugin list`, `plugin <name> …`, `doctor` |
| 4 | + invoke one handler | `plugin <name> <verb>` only |

`workspace` is above level 0 and spawns nothing: what is left of it reads and tears down.
The test asserts the level-0 list is the whole verb set minus the others, so a verb added
later without a level lands at 0, which is the point. The collector's two triggers, `flush`
and `reconcile`, are level 0 deliberately — they run unattended on a timer and must not be
able to reach plugin code.

**No verb that spawns imports plugin code.** A plugin with a `SyntaxError`, or one that is
`raise SystemExit(3)` at module scope, cannot break `sb delegate` or `sb start`, because
those verbs read a markdown file and stop — and the broken plugin's fragment still reaches
the prompt, since sb was never going to run the code behind it.

State is a directory sb creates and never reads inside:
`<shared .git>/agentflow/plugins/<name>/` for `SCOPE = "repo"` (byte-identical from every
worktree, the same repo identity `state.db` uses), or
`~/.local/state/switchboard/plugins/<name>/` for `SCOPE = "user"`. sb takes an exclusive
`flock` around each handler call unless the plugin sets `LOCK = False`. Nothing goes in
`state.db`.

What a handler is handed is the contract, and so is what it is not: `Context` carries
`api`, `name`, `state_dir`, `repo`, `worktree`, `agent`, `json` — no `Broker`, no store
handle, no spawn authority. `Context`, `Result` and the parsed args are all
JSON-serialisable, which keeps a future out-of-process hatch open without building one.
- Entry point: `switchboard/plugins.py`
- Design of record: `design/PLUGIN-REDESIGN.md` §4–§7; §11 lists what it knowingly does not
  do, including one item (§4.6's internals-import check) that is deliberately **not built**
  rather than deferred — the cheap implementation would pass the only violation it exists
  to catch.

## Roles
`defaults/roles/*.md` — front matter (`model`, and `delegate` where it is granted) plus a
markdown body used as the spawned agent's prompt. Five ship:

| role | tier | delegate | purpose |
|---|---|---|---|
| `orchestrator` | default | **yes** | delegates only, never does work itself; used at every scope (`sb start`, workspace leads, sub-orchestrators). Owns cleanup policy, assigns disjoint files at split time because its children share its worktree, and runs the `adversarial` procedure by name |
| `worker` | default | no | one task, carried to done, nothing beyond it; the default role and the fallback for any undefined one |
| `reviewer` | default | no | reads the work and gives a verdict, led with in plain words |
| `qa` | default | no | runs the work and finds out whether it actually behaves — evidence about behaviour, as against the reviewer's judgement about code |
| `researcher` | cheap | no | investigates and writes findings to a file; the only role on the `cheap` tier |

**`delegate` is a role FIELD, and only `orchestrator` has it.** Any other role's
`sb delegate` is refused outright, in the broker, so every door into a spawn goes through
the same check. It is a field rather than a name check because vocabulary is data: a repo
that renames the leaf role, or adds its own, would slip past `role == "worker"`. It
defaults to `false`, so a role nobody thought about is a leaf.

`cleanup` is no longer a role field anywhere, and nothing writes the store's per-agent
column either: cleanup is the orchestrator's job and it always takes the children.

No shipped role is on `strong`. `designer` was, and the fact it rested on — design is one
of the places a better model pays — is real; what did not follow was pinning a tier to a
role, when `sb delegate --model strong` buys the same thing per call without every spawn
of that kind paying for it.

`worker` is `[vocabulary] default_role` and `fallback_role`: a plain `sb delegate` with no
`--role` produces a `worker`, and `--role archaeologist` inherits `worker`'s fields while
keeping its own name. Its prompt file was deleted once and restored: the two rules it
carried (do only what you were asked; hand back what is too big) are universal and now sit
in `defaults/protocol.md` as well, but with no role file the last substantial thing a leaf
agent read before its task was a plugin fragment about filing bugs. Position is why it is
back, not novelty — the assembly order is protocol → identity → roles-that-exist →
workspace → role → presets → task.

Every spawn is also told **which roles exist**, generated from the merged role table and
never hardcoded (`[spawn] roles`), so a repo that adds a role file appears there with
nothing else edited.

## Model tiers
`defaults/models.toml`: `cheap` (sonnet, **medium** effort), `default` (no pin — CLI default),
`standard` (explicit legacy alias of `default`, kept for backward config compatibility,
not a bug), `strong` (opus, high effort). Only `claude` is a wired provider; `codex` is a
config field placeholder with no backend behind it yet.

`cheap` is still cheap the same *way* — sonnet, with effort as the dial — but at medium
rather than low, because its one consumer changed underneath it: an orchestrator's first
move is now to spend a researcher on understanding a task before splitting it, so the tier
picked for "one of five parallel readers, none of them load-bearing" became the tier every
subsequent split depends on. No tier uses haiku, and that is a measured decision rather
than a preference: `--permission-mode auto` runs a model-dependent classifier, and haiku's
stops for a human on ordinary shell commands.

## Verbs that no longer exist
Each was removed on purpose, and each has one replacement:

| gone | what to use |
|---|---|
| `sb ask` | `sb tell --needs-reply`. No agent waits on another agent |
| `sb wait` | nothing. An agent ends its turn and is woken by the doorbell |
| `sb interrupt` | `sb tell --interrupt`, a delivery mode rather than a verb |
| `sb workspace new` | a top orchestrator's `sb delegate` mints a space; `sb delegate --workspace <name>` joins one |
| `sb output` | `sb inspect`, which reads `output.py` directly |
| `sb plugins` | `sb presets` for prompt text, `sb plugin list` for code |

The flags that went with them are gone too: `--keep`, `--ephemeral`, `--include-kept`,
`--leave-children`, `--no-board`, `--no-focus`, `--focus`, and `sb workspace new`'s
`--base`.

## Overlaps worth knowing about (not bugs)
- **The three `tell` modes**: all three return immediately. *Next turn* reaches a busy
  agent at its next tool-call boundary, *when idle* waits for its turn to end, *interrupt*
  cancels the turn. Only interrupt changes what the target is doing.
- **`block` vs `tell`**: `tell` is agent→agent and never waits; `block` is the only way to
  reach a human. There is no `tell human` — it is refused, pointing at `block`.
- **`inspect` vs the old `output`**: `sb output` no longer exists as its own verb;
  `output.py` is called directly by `inspect`.
- **`sb models` vs `sb presets`**: deliberately kept as two separate answers to "what
  vocabulary does this repo have."
- **The Stop gate vs the reconciler**: the hook prevents the ordinary silent finish at the
  moment it happens; the reconciler names the agent that stayed silent anyway. Each fires
  once, and each waives a parent with live children.

## Known issues
See `BUGS.md` for the full write-ups. As of the last entries there: `Broker._adopt`
race (**FIXED**), herdr `wait` sending the wrong `--until` value and spinning CPU
(**FIXED**, both in the adapter), a schema change that deadlocked running agents
(**FIXED**, and adding a table no longer costs the store either — `BUGS.md` #4 says which
narrower shape still forces a rebuild), and `sb wait` returning success early
(**NOT REPRODUCIBLE** — and that verb has since been deleted, so #5 describes code that is
no longer here).

## Keeping this current
The cheapest rule that will actually survive delegated agents who haven't read this
file: **treat a `FEATURES.md` update as part of the definition of done for any change
that adds, removes, or changes the behavior of an `sb` verb or a `defaults/` file** —
the same way a change isn't done without its test passing. Put one line to that effect
in `defaults/protocol.md` (or wherever the orchestrator role's prompt lives), since that
is the one document every agent actually reads before doing anything. Don't rely on a
human periodically re-auditing — the auditor should be whoever's PR touched the surface
this file describes, at the moment they touch it, because that's the only point where
the cost of writing it down is smaller than the cost of finding out later it's stale.
