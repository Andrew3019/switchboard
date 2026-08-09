# Options for fixing switchboard's teardown and state tracking

An audit established what is broken. This document says how it should be
fixed. It covers all sixteen gaps, grouped into the four clusters that share
a fix, and answers the one question the human left deliberately open.

Everything below was re-verified against HEAD `f1193d0`, not against the
audit's `e52f905` line numbers. Where `f1193d0` moved the ground, that is
called out rather than papered over.

Read the first two sections for the decision. Read the rest for the argument.

---

## A. How aggressive should teardown be allowed to be?

**Recommendation: teardown is a separate, explicit, destructive command. It
refuses unless nothing live is in the checkout directory *and* the worktree
holds nothing the human has not seen. It never happens as a side effect of
`sb cleanup`. A bare workspace, which has no checkout of its own and where
nothing is destroyed, takes a separate path that runs none of that.**

Both halves of that sentence are deliberately weaker than the obvious
formulation. "Every agent recorded against the workspace is finished" is a
claim about a record, in a codebase whose central defect is that this exact
record goes wrong, guarding an operation whose real scope is a directory. And
"the worktree is clean" is not the same statement as "there is nothing to
lose": the files most likely to be unrecoverable are precisely the ones
`git status` does not print. The shape of the command below is built around
those two corrections.

### Why this is a real question and not just under-specification

`cleanup()`'s docstring is a promise users already act on: *"closing costs
only the pane. Session, summary, messages and the on-disk transcript all
survive, and `sb restore` brings the agent back"* (`broker.py:1644-1645`).
That promise is accurate today — `cleanup()` closes a pane, writes
`state='done'`, clears `pane_id`, and touches nothing else
(`broker.py:1638-1750`). It becomes false the moment worktree removal
appears anywhere on that call path.

Worktree removal is not one decision but two, and they can disagree:
`git worktree remove` destroys uncommitted changes or refuses on a dirty
tree; `git branch -d` refuses on unmerged commits and `-D` does not. A
workspace can be worktree-clean and branch-unmerged, or the reverse.

And a workspace is not one agent's property. The lead and its children share
one `workspace_id` (`broker.py:1341`), and `join_workspace`
(`broker.py:649+`) lets agents attach independently of the lead. Closing the
lead's pane says nothing about whether the workspace is done. Any rule has
to reason about the last agent out, not about the agent that happened to
trigger the check.

### The rejected option: prune automatically once the last agent is out

The tempting version is to fold removal into `cleanup()`: when the close
that just succeeded leaves zero un-finished agents under that
`workspace_id`, remove the worktree and delete the branch as a trailing step,
gated on a clean tree. It costs no new verb and nothing accumulates.

It is rejected on three grounds, and the first is decisive.

**Blast radius.** It puts an irreversible git operation behind a code path
that runs with no name and no confirmation — the no-`names` sweep branch at
`broker.py:1691-1695` iterates every finished agent in scope. A bug in the
"is this really the last one" query, or a race between two concurrent
sweeps from different agents in the same workspace, removes a worktree out
from under someone about to reuse it. Unlike every other failure in this
audit, that one is not recoverable; `sb restore` brings back a pane, not
uncommitted work.

**Silent contract change.** `sb cleanup` is in muscle-memory use, and
`f1193d0` made it the routine way abandoned orchestrators get closed. Giving
it destructive git behaviour without a new verb changes what a habitual
command does, for functionality that deserves its own name.

**Testability.** The destructive step would have to be proven safe against
every existing `cleanup()` gate simultaneously — force, dry-run,
leave-children, sweep-versus-named — which is exactly the function where
audit findings #1, #5 and #6 already live. A separate command has one
precondition and one set of side effects.

The audit's own sketch assumed a gated, opt-in command. Nothing found since
argues the other way.

### The shape of the command

`sb workspace close <name>`, by name only. Its design goal is not "delete the
workspace once the records say it is empty" but "make sure a person has seen
everything that is about to stop existing." Everything below follows from
that.

**Identity and gate scope are two different keys, and conflating them was the
mistake of the last two rounds.** The `workspaces` table (Wave 3) is keyed on the
workspace **name**. The checkout path is a recorded *attribute* of that named
workspace, nullable, and it is what the destructive gate is scoped to. Round 1
was right that destruction must be scoped by a directory; round 2 was right that
`workspace_id` is not a function of a checkout; both then wrongly concluded that
the record's identity had to be the same key as the gate's scope. It does not.
Identity is about a workspace — the thing the person names and retires. Scope is
about a directory — the thing that gets destroyed. The full argument, and why
this supersedes round 2's "keyed on the checkout path", is in Group A.

**Where the path comes from.** The `workspaces` table carries the checkout path
as a recorded fact, written when the workspace is created, and the destructive
command must refuse — loudly, by name — when it cannot resolve one. (A NULL path
is not an unresolvable path: NULL is how a bare workspace is represented, and the
bare path below never reaches this rule.) The existing idiom must not be copied.
`_recorded_path` (`broker.py:1008`) reads a `cwd` off an agent row keyed on the
workspace *name*, which is tier 4, the exact lookup this document forbids Group A
from using for membership; and its one caller does

```python
where = Path(self._recorded_path(ws) or self.repo)   # broker.py:1324
```

whose fallback is the human's primary checkout. A teardown that copies that
shape aims `git status` and `git worktree remove` at the main repo whenever a
path is unrecorded. Git happens to refuse there (`fatal: '.' is a main working
tree`), but the cleanliness check would already have been evaluated against the
wrong tree and the subsequent `git branch -d` still fires against a branch
chosen by name. There is no `or self.repo` in this command, and no fallback of
any kind: an unresolvable path is a refusal.

**And that refusal is the whole population unless the table is backfilled.**
Every workspace on this machine — all twenty-one of them — predates the table,
so none has a recorded path and "refuse when unresolvable" refuses everything,
permanently. A command that is inert against the entire existing state is not
conservative, it is absent. The table therefore arrives with a one-time
backfill, run once at migration time, that derives a checkout path per workspace
name from the `cwd` of its agent rows — one table row per name, so the four bare
orchestrators over the primary clone backfill as four distinct rows rather than
collapsing into one. A workspace whose rows carry a NULL `branch` backfills with
a NULL path, because that is what bare means: no checkout of its own. This is
deliberately the same lookup shape
this document forbids Group A from using for *membership*, and the distinction
is the point: deciding at every call which rows belong to a workspace by
matching a name is a standing invitation to tier-4's failure mode, whereas
populating a column once, at a known moment, from the only evidence that exists
is an ordinary migration. `store._backfill_branch` (`store.py:415-427`) is the
precedent — it reconstructs `branch` for pre-column rows from `cwd` and takes
the same `cwd` argument `_reconcile` already threads through. What makes the
distinction safe is the second half of the rule: **a backfilled path is never
trusted as a live fact.** At every use it is re-validated — the directory must
still exist and must still be a worktree of this repo — and a path that fails
re-validation is treated exactly like an unrecorded one. The backfill supplies a
candidate; git supplies the truth.

**What the gate is scoped to.** The gate is scoped to the *checkout path*, not
to `workspace_id`. It refuses if any non-finished row anywhere has a `cwd`
under that path, whatever its `workspace_id`, and a NULL `workspace_id` cannot
exempt a row from that test because the test never reads the column. This is
the point where the design has to follow its own instinct. Two workspace ids
can sit over one checkout — `_parent_workspace_id`'s docstring
(`broker.py:1108-1118`) records that happening, as "how a child of `main`
landed in w1, the OTHER workspace over that same checkout" — so enumerating
one id's rows and finding them all finished says nothing about who else is in
the directory. The destruction is scoped by a directory; so is the gate.

**"Under that path" means path components, not a string prefix, and the caller
is excluded.** Round 4 found both halves of this unspecified, and both fail on
this machine's actual layout. Worktrees are siblings in one directory and their
names nest as strings: `.../worktrees/switchboard/adv-r4` is a prefix of
`.../worktrees/switchboard/adv-r4-concurrent`, so a prefix match gates the
shorter name forever on rows belonging to the longer one. Containment is decided
on resolved path components — both sides resolved, then compared segment by
segment — never on `str.startswith`. And the gate must exclude the caller: an
agent working in workspace W that is told to close W runs the command from a
shell whose cwd is under W's checkout, and its own `agents` row is non-finished
*because it is running this command*. Both halves of the gate see it and the
general path refuses for the most obvious way anyone will invoke it — the same
self-reference section A already diagnoses for bare workspaces ("there is
essentially always another orchestrator: the one that typed the command"), which
the bare path solves by not running the gate at all. Here it is solved by
exclusion: the caller's own `agents` row and the caller's own process tree do not
count against the gate. Nothing else is excluded.

**And a gate made only of records is not enough.** Add one live observation:
a herdr pane still open in that workspace, or a process whose cwd is under the
path. Records here are exactly what this document spends four groups fixing,
and a destructive gate should not rest entirely on them while they are still
being repaired. The rule when the observation cannot be made is that the gate
**refuses**: unknown is not empty. That mirrors `_alive`'s own comment,
"`None` is 'cannot tell', not 'nobody is running'" (`broker.py:1004-1006`), and
it is the specific answer to the correlated-outage case — both liveness polls
call the same herdr, so an outage longer than `GONE_CONFIRM_GRACE` marks every
agent in a workspace `failed` at once, and Wave 2's debounce makes that rarer
without making it independent. A gate that refuses on "cannot tell" survives
that; a gate that reads a wall of `failed` rows as "empty" does not.

**But refuse-on-unknown only covers a herdr that is down, and the failure this
codebase actually records is a herdr that is up and has forgotten.** Round 4 is
right that these are different, and the difference is the whole gate. `broker.py:1135-1139`:
*"A RECORDED id, though, outlives the herdr that issued it: ids are handed out
per herdr run, so a row written before a restart names a workspace that is simply
gone."* A restarted herdr answers *successfully* with a smaller world.
`list_agents()` returns fewer names, so `alive` is `False` rather than `None`,
`gone` is true (`status.py:401-402`), and after `GONE_CONFIRM_GRACE` every row in
the workspace reads `failed` — which is in `FINISHED`. The records half of the
gate then passes, and nothing was ever "unknown", so refuse-on-unknown never
fires. `status.py:337-339`'s three-agents-failed-during-startup comment is the
same shape at smaller scale.

The consequence is a change of role, and it has to be stated as one: **under that
interleaving the live cwd observation stops being a second opinion and becomes
the half that decides.** It therefore gets the same specification as the rest of
the gate rather than being named in passing:

- **How it enumerates.** Processes whose cwd is under the checkout path, found
  with `lsof` — this is macOS, there is no `/proc` to walk. The candidate set is
  every process, not only ones switchboard knows about; a human's editor has no
  `agents` row and is exactly who this half exists to protect.
- **What it does when it cannot enumerate** — `lsof` missing, non-zero, timing
  out, or returning output the parser does not understand — is **refuse**, and
  that refusal is mandatory rather than best-effort. This is the branch that
  decides the outcome when herdr has forgotten, so a silent fall-through to
  "nothing live" is the one failure that turns a confidently wrong record into a
  deletion.
- **The herdr half is a corroborator, not a substitute.** A successful herdr
  answer never licenses skipping the cwd observation, precisely because a
  successful answer is what a restarted herdr gives.

Nobody has run this on macOS yet; that is recorded in the open-questions section
at the end rather than assumed away.

**What counts as clean.** Not `git status --porcelain`. Plain porcelain does
not list gitignored files, and `git worktree remove` deletes them anyway —
git's own cleanliness check is blind to them too, so git's refusal is not a
backstop. This repo widens that blind spot on purpose: `.gitignore` ignores
`/.switchboard/` and `/.claude/`, and `Broker._exclude` (`broker.py:364-375`)
writes `LINKED_CONFIG` names into `.git/info/exclude` under the docstring "Keep
the symlinks out of `git status`." A real `.env`, a real
`.claude/settings.local.json`, a local override someone made in a worktree
precisely because it was never meant to be committed — all invisible to the
obvious check and all destroyed by the removal.

"Refuse if dirty" therefore cannot be the rule, because in this repo most
worktrees are ignored-dirty always and a rule that always refuses is a rule
nobody keeps. Two tiers instead:

- **Tracked-dirty or untracked content: refuse outright**, as before. This is
  work git can see, and a human can commit or stash it before asking again.
- **Ignored content: classify it.** An entry that is a symlink switchboard
  itself planted is safe — removal unlinks the symlink and the target survives
  in the main checkout, which was tested rather than assumed. Anything else
  ignored is user content, and it must be inventoried and shown to the human,
  with the command proceeding only on explicit confirmation.

That classification is implementable rather than a flag flip for one specific
reason: switchboard planted those exclude entries itself. `LINKED_CONFIG` plus
`_exclude`'s own writes plus `/.switchboard/` and `/.claude/` in `.gitignore`
are a list the code owns, so it can tell its own furniture from the human's
belongings. Without that the honest design would be "show the human every
ignored path every time," which is the sort of prompt people learn to dismiss.

**Bare workspaces have no teardown at all, and the destructive gate must not run
for them.** A bare workspace is one with no checkout of its own — it sits over
the original clone, and the schema records it by leaving `branch` NULL ("BARE: a
place to work with no checkout of its own"), a distinction the code already
respects in `store.workspace_branch`, `Broker._recorded_path` and
`_workspace_id`'s `workspace_bare` branch. This document previously spoke as
though every workspace had a worktree; it does not, and on this machine four
workspaces are bare — `main`, `main-2`, `main-3` and `main-4`, all NULL
`branch`, all recording `/Users/andrew/Code/switchboard`. Four of the eight herdr
spaces open right now are exactly these, and `f1193d0` made them the
fastest-accumulating kind in the system, since every bare `sb start` mints
another one.

Every destructive step is wrong for them, and the ignored-content inventory is
worse than wrong: run in the primary checkout it prints the human's own
`.switchboard/` and `.claude/` as material about to be destroyed, for an
operation that could not destroy them if it tried.

**The rule: a bare workspace gets a retired mark and nothing else, on a separate
code path that never evaluates the path gate.** Concretely: check that *this
workspace's own* agent rows are finished, close its own panes, write the retired
mark, stop. No path gate, no live-observation-in-the-directory test, no
inventory, no confirmation prompt, no `git worktree remove`, no `git branch -d`.
There is nothing to lose, so there is nothing to guard and nothing to show.

**Sharing the gate with the worktree case was a real bug, not a tidiness
complaint.** The path gate refuses if anything non-finished sits under the
checkout path. For a bare workspace that path is the human's primary clone —
where the human sits, where every other bare orchestrator sits, and where the
agent running the command usually sits. So `sb workspace close main-2` would
refuse because `main-3` is live in a directory nobody is deleting, and there is
essentially always another orchestrator: the one that typed the command. A guard
protecting a directory from deletion, applied to an operation that deletes
nothing, refuses the only operation available, permanently. That is why the bare
path is specified separately rather than as a set of skipped steps inside the
general one.

**And this is drift, recorded as such.** The first draft's gate was "refuses if
any agent recorded against that `workspace_id` is not FINISHED" (v1, commit
`052da31`), which for `main-2` reads `main-2`'s own rows and passes. That test
was correct for the bare case. Round 1's hardening — correct, and still correct,
for worktrees — replaced it wholesale and silently removed the bare case's only
working path. The own-rows test comes back here, scoped to the case it was right
for.

Retiring is the entire operation for a bare workspace, and it is still worth
having, because "this orchestrator is finished" is a fact worth recording whether
or not a directory goes with it.

**What this fixes downstream.** Group B's pick for the idle-orchestrator finding
routes "retire an idle, never-assigned lead or orchestrator" to this command.
Until the bare path exists, that routing fixes the STALLED *label* and nothing
else: the command it hands the removal to could never complete for an
orchestrator, so `sb cleanup <name> --force` would remain the only exit — which
is the exact complaint the finding raises. With the bare path, the finding
genuinely closes.

**And a refusal rolls the retiring mark back — but only the holder's own mark.**
The two-phase write below is meant to survive a *crash*, not to be a lock left
behind by an ordinary "no." Only a crash may leave the mark set; every refusal —
the gate, the inventory confirmation, an unresolvable path — clears the mark
before returning. Without that rule a refusal would leave a mark that
`workspace_new` is specified to refuse to join, locking a live workspace's name
out of itself over a command that did nothing. A directory that is already gone
remains a resumable state; a refusal is not a state at all. (An earlier version
of this paragraph used `sb workspace close main-2` refusing on `main-3` as the
illustration and called that refusal correct. It is not correct — it is the bug
the bare path above exists to fix — so the illustration is retired along with it.
The rollback rule stands on its own for the worktree case.)

Round 4 found the unqualified form of that rule actively harmful, and the
qualification is not cosmetic. **A rollback fires only when the rolling-back
process is the recorded owner of the mark, and it never restores a snapshot
captured earlier.** Written as "restores the previous state," the rule lets a
losing invocation clear the winner's mark — unmarking a workspace in the middle
of the winner's destructive phase, which is exactly the window `workspace_new`'s
refusal exists to close — and lets a loser's rollback write back a snapshot taken
before the winner finished, erasing a completed `retired_at` for a workspace
whose directory is already gone. Both are ordinary lost updates. The rollback is
a conditional clear of the row this process claimed, not a restore of remembered
state.

**A worktree whose directory is already gone is the safest case, not an unknown
one.** The cleanliness check runs `git status --porcelain --ignored` in the
checkout path, and in a directory that no longer exists git exits fatal. Read
through the refuse-on-unknown rule that is a permanent refusal — which would
make the single largest and most obviously safe category of mess on this machine
the one category the command can never touch: five removed worktrees accounting
for 55 of the 101 agent rows, with five orphan branches still pointing at them.
Nothing can be lost there, because nothing is there. So it is its own small
path, not a degenerate case of the main one: confirm no non-finished row records
a `cwd` under the path, then deregister *that worktree by name* and
`git branch -d`, which refuses an unmerged branch on its own. No inventory, no
confirmation — the same reasoning as bare, arrived at from the other direction.
The refuse-on-unknown rule keeps its full force where it belongs, which is a
directory that exists and cannot be read.

**Never a bare `git worktree prune`.** An earlier version of this paragraph said
"`git worktree prune`", and that is a scope error on every invocation, not a race:
`prune` is repo-global. Round 4 verified it in a throwaway repo with two prunable
worktrees — one bare `git worktree prune`, no `--expire`, removed both. So
`sb workspace close old-thing` would deregister every prunable worktree in the
repo, including one another agent has just gated and is about to close by name,
and including one the human could still have recovered with `git worktree repair`
after moving a directory. The gate is evaluated for one path; the action must be
taken against that path. Use `git worktree remove` for the named path (which
targets exactly it, and is the same verb the general path uses), and reach for
`prune` only after confirming it is the sole prunable entry — which is more work
than just naming the path, so in practice: never.

**Ordering: check, then stop, then re-confirm, then delete.** An earlier version
of this rule read "stop, then check, then delete", and that ordering had a bug:
it closed the workspace's panes *before* evaluating the gate, so a refusal left
the panes closed, the command reporting failure, and nothing retired. The person
loses their panes and gets nothing for them. The gate is cheap and read-only, so
it goes first:

1. **Evaluate the gate** — records under the checkout path, plus the live
   observation, refusing on unknown. Nothing has been touched yet, so a refusal
   costs nothing but the message.
2. **Close the panes** for that workspace's agents and *confirm* them stopped.
3. **Re-confirm the gate**, now that the panes are down — this is the check that
   catches anything that arrived during step 2, and it is the one that authorises
   destruction.
4. **Delete**: `git worktree remove`, then `git branch -d`, then the retired
   mark.

Deleting a directory around a process still running in it is not an exotic state
here — it is precisely the one "Where the designs collide" (#1) constructs, where
a forced close during a herdr outage marks rows `done` with `pane_id=None` while
the panes may still be alive. Step 3 is what step 2 exists to make true, and
destruction is still the last step, not the first. The first evaluation does not
make the second redundant; it makes the *cheap* answer available before anything
irreversible or even inconvenient has happened.

**Re-entrancy: ship the state before the destruction, inside the command too.**
Section A's staging argument applies within a single invocation. The retiring/
retired write is a pure state write with no disk consequence, so it is
committed *first*: the workspace is marked retiring, then the destructive steps
run, then it is marked retired. A command that dies midway must be resumable —
a directory that is already gone is a resumable state, not an error and not a
permanent refusal. The alternative is a workspace whose directory is gone,
whose rows still read live, and which the intended verb can never close again.

**Concurrency, without a lock.** Between the check and the removal, another
agent can legitimately run `sb workspace new W` or `sb delegate --workspace W`
and land a lead in the directory about to be deleted. The race is real. A lock
is still the wrong fix, because `workspace_new`'s docstring
(`broker.py:592-597`) advertises the opposite posture deliberately — "safe to
call concurrently. Nothing here is exclusive: another agent or a human may be
in this workspace already, and that is a normal state, not a conflict" — and
adding a lock primitive to enforce exclusion on one path teaches the rest of
the codebase a rule it does not otherwise follow. Reuse the state already being
added instead: because the retiring mark is committed before anything
destructive happens, `workspace_new` and `--workspace` simply refuse to join a
workspace marked retiring. That is exclusion built out of a record the design
needs anyway.

**But a mark used for exclusion needs an owner and an atomic claim, and round 4
is right that the design gave it neither.** Two agents told to tidy up both run
`sb workspace close W`. A evaluates the gate and writes the mark; B evaluates the
gate — nothing was specified to check `retiring` here — and writes the mark too,
as a plain UPDATE that no-ops because it is already set. A closes W's panes,
re-confirms, sees B's live process in the directory, and refuses — clearing the
mark. Between that clear and B's removal the workspace is unmarked, so
`workspace_new W` and `sb delegate --workspace W` are free to land a lead in the
directory B is about to delete, and B's re-confirmation already happened before
that window opened. The residual-race argument below assumes the mark stays set
for the whole destructive phase; here the loser cleared the winner's mark.

The fix is the shape this codebase already writes down. `store.claim_agent`
(`store.py:638-655`): *"the claim has to BE the insert: a `get_agent(...) or
create_agent(...)` check-then-act is two statements with a race between them, and
it lost that race about once in twenty-five workspace opens."* Applied here, in
three parts:

- **Claiming the mark IS the conditional write.** `UPDATE workspaces SET
  retiring = ... WHERE name = ? AND retiring IS NULL`, with `rowcount` as the
  arbiter. One row updated means you hold it; zero means somebody else does.
  There is no separate read.
- **The mark records who holds it**, not merely that it is held — the claiming
  agent's name, so a rollback can ask whether it is the owner. Rollback fires
  only when the owner matches, and it is a conditional clear of that row, never a
  restore of a snapshot captured earlier.
- **`sb workspace close` itself refuses a workspace already marked retiring.**
  The design specified that refusal for `workspace_new` and `--workspace` and
  never for the command that sets the mark, which is the one place two invocations
  actually collide.

**This is not a reversal of round 1's refusal of a lock primitive.** No lock file
is added, no lock verb, no exclusive resource for the rest of the codebase to
learn. `workspace_new` keeps its non-exclusive posture and agents keep joining
workspaces freely. What changes is that the one write the design was already
making becomes atomic and owned — the pattern the store uses for agent claims,
applied to the row it is claiming. Round 1's objection was to teaching the
codebase a general exclusion mechanism it does not otherwise follow; this teaches
it nothing it does not already do in `claim_agent`.

The residual race is the window between reading the retiring flag and
persisting the new agent row: a spawn that passes the check microseconds before
the mark lands still gets in. That is acceptable because it is bounded and
because it does not defeat the gate — the new row is in the directory, so the
path-scoped gate and the live observation both see it, and the teardown refuses
rather than deleting around it. A lock would close the window; the gate makes
what falls through it non-destructive, which is the property that matters. That
argument holds only while the mark stays set for the whole destructive phase,
which is precisely what the owned claim above buys.

**Confirmation, when it is demanded.** Typing the branch name back is not a
confirmation. For a workspace with a worktree, workspace name *is* branch name
(`_attach_workspace`: `branch = name`, `broker.py:715`) — the bare case above is
the exception, and there the answer is that no confirmation is demanded at all
because nothing is destroyed. So the token asks the human to retype the string
they typed one argument earlier on the same command line; it asserts nothing
new and scripts as trivially as a boolean. The confirmation must echo
information the command line does not contain — the count and a sample of what
will be lost, from the ignored-content inventory above — and it should only be
demanded when that inventory is non-empty. A prompt that fires when there is
nothing to lose is a prompt people learn to answer without reading, which
spends the one moment of attention this command gets.

**On success:** `git worktree remove`, then `git branch -d` and never `-D` (an
unmerged branch simply stays, which is a far cheaper failure than losing
commits — and cheaper still than assumed, since a deleted branch's tip
survives in the reflog), then the retired mark.

**Reopening a retired workspace clears the mark.** `workspace_new` given the name
of a *retired* workspace reopens it: the `retired_at` fact is cleared and the
workspace is live again. Retirement is a record of end-of-life, not a tombstone
that blocks the name. That is what lets "retired" and "fresh" be distinguishable
— the whole point of the record — without making a retired name unusable, and it
is the answer to the question this document previously left unanswered. The
*retiring* mark is the opposite and stays the opposite: `workspace_new` refuses
to join it, because retiring means a destructive command is mid-flight. Retired
is a past tense; retiring is a lock.

**The human has no vote unless the design gives them one.** "Every agent
recorded against this `workspace_id` is finished" counts agents, and humans
have no row. A person sitting in a worktree with an editor open, having just
closed out the agents that were helping them, satisfies that gate completely —
and what they lose is exactly the uncommitted-and-ignored material the first
tier cannot see. This is stated as a design goal rather than left implied: the
ignored-content inventory and the live-process observation are the two places
where a person who never appears in the store gets to say no.

### Staging, and why the state comes first

Group A's preferred framing is worth keeping: ship the *state* before the
*destruction*. Marking a workspace retired is a pure state write with no
disk consequences, and it is required regardless of which destructive design
eventually lands — you cannot ask "has this workspace really finished, or is
it merely quiet" without a durable fact to ask. Building it first means the
"last agent out" detection is exercised in production, harmlessly, before
any irreversible operation depends on it being correct.

### What stays manual, said plainly

Three parts of the original ask end up unautomated, two of them deliberately and
permanently. They are stated here in the person's own terms rather than left to
be inferred from the sequencing.

- **Real worktree removal waits for Wave 4.** Until then, a worktree whose
  directory still exists is removed by hand. What ships earlier is the diagnosis
  (`sb workspace list`) and the already-gone prune. This is a delay, not a
  refusal — but Wave 4 is the largest item in the document and it may be a long
  delay. See below for what the person does get in the meantime.
- **Unmerged branches are never deleted.** `git branch -d` refuses them and the
  design never falls back to `-D`. On this machine the five orphan branches are
  merged into `main` and the already-gone prune clears them, but `audit-cleanup`,
  `fix-options-2` and the three `adv-*` branches are unmerged and will stay
  forever unless a human deletes them. That is a deliberate trade — losing
  commits is worse than accumulating refs — and it means "nothing removes
  branches" is only half fixed.
- **Agent rows and events are never purged.** Retire, never delete. Here that is
  101 rows and 11752 events that stay. The reason is in "Where the designs
  collide" (#2): Group C's D1 guard resolves a finished agent's identity by
  reading its `done` row, so deleting rows reintroduces the bug in a new shape.
  Also deliberate, also permanent, and also a piece of the ask that ends
  unfixed.

To make the second of those actionable rather than merely disclosed,
`sb workspace list` should report unmerged orphan branches — branches left behind
by a workspace whose worktree is gone, which `-d` will refuse — so a human can
decide by hand which ones are safe to force-delete. The command does not delete
them; it just stops them being invisible.

**What the person gets before Wave 4, on the state actually here.** The
already-gone prune clears five orphan branches and 55 of the 101 agent rows. The
bare path retires four of the eight herdr spaces open right now. Between them,
Waves 1–3 clear most of the visible accumulation on this machine without any of
Wave 4's machinery. That is the honest measure of shipping the non-destructive
waves first — not "the diagnosis only."

### What it costs if this is too conservative

Worktrees and branches accumulate. Nothing reclaims disk, and someone still
runs `git worktree list` and prunes by hand — which is exactly today's
situation, so the downside of being wrong here is that part of the problem
stays unfixed, not that anything breaks. That claim was too comfortable in its
first form and the backfill above is what earns it back: without a backfill the
honest statement is not "part of the problem" but *all* of it, forever, since
every workspace that exists today would be unresolvable and the command would
only ever act on workspaces created after it ships. `sb workspace list` (Wave 3) makes
that manual pass cheap and targeted rather than archaeological. If
accumulation turns out to hurt in practice, an opt-in `--prune-worktrees`
flag on the explicit command, or a `sb workspace gc` that only ever acts on
already-retired workspaces, is a strictly additive follow-up. The reverse
mistake — discovering a race in the sweep destroyed uncommitted work — has
no follow-up.

---

## B. Sequencing: four waves and a prerequisite

The waves are ordered by dependency, not by importance. Wave 1 items are
independent of everything and should ship on their own. Wave 2.5 was added by
the second review round: it is a store capability, not a feature, it blocks wave
3 absolutely, and it is worth building whether or not the rest of this document
is.

### Wave 1 — ship immediately; cheap, and nothing depends on them

**1. The workspace-id poisoning bug from `f1193d0`. This is the single most
urgent item in the set.** `_tab_for` detects a dead `workspace_id`, purges it
from every row that held it (`broker.py:1156-1158`), and falls back to a
plain tab. But `delegate()` computed `wsid` *before* calling `_tab_for`
(`broker.py:1341-1342`) and then writes that already-proven-dead id straight
onto the new row (`broker.py:1358`). The spawn that detects and purges the
dead id immediately re-plants it. Every later child inherits it via
`_parent_workspace_id` tier 1, repeats the same failed herdr call, and
re-poisons the next row — and when the chain bottoms out on a row with no id,
tier 4's name-derived guess (documented at `broker.py:1108-1111` as "how a
child of `main` landed in w1, the OTHER workspace over that same checkout")
gets persisted as though it were fact. It is corrupting the join key that
Waves 3 and 4 depend on, and it is corrupting it now.

**2. The mail/interrupt guard for a finished agent (D1), *with* the
`pane_not_found` branch (A2), and with the one-time backlog sweep.** A message to
an agent that has already called `sb done` is written, never delivered, and
retried by `flush_pending` on every future `sb` command anyone runs, forever.

A2 was in Wave 2 in the previous sequencing, and that contradicted the document's
own conclusion. Group C's second correction establishes that `cleanup`'s unread
gate `continue`s before the close is attempted, so A2's branch is unreachable for
exactly the rows that jam — "so the two fixes have to land together." Building in
wave order with them split leaves `split-fixer`-shaped rows jammed after Wave 2,
which is the thing both fixes exist to stop. They move together, here.

The one-time sweep of the existing mail backlog belongs with D1, in this wave.
D1's guard only stops *new* ring attempts; the eight unseen messages already on
disk for `done` agents keep retrying until something clears them. It was
specified and then placed in no wave; it is placed now.

**3. Stop labelling never-assigned idle leads as STALLED.** A predicate
change only; nothing about what gets swept changes. `f1193d0` made this
routine rather than rare — every bare `sb start` now mints a fresh top-level
orchestrator that exhibits the shape.

All of these are small, self-contained, and block nothing.

### Wave 2 — the trust layer

Everything later keys off "is this agent really finished." That answer has to
become trustworthy before anything destructive consults it.

- **Liveness debounce and a narrow repair pass in the reap path.** Stop a single
  absent reading from writing a permanent `failed` verdict; repair a row that has
  been absent past every grace window, so a dead agent does not stay wrong
  forever because nobody happened to look. The repair write happens on any `sb`
  command that already reaps — **not** in the collector, which holds a read-only
  connection and cannot write at all (see Group B, where round 4 overturned the
  original pick).
- **The remaining cleanup close-loop fixes.** Log a distinct event when force
  kills a live agent; log loudly when the forced path commits "closed"
  bookkeeping despite the underlying close failing. (The `pane_not_found` branch
  moved to Wave 1 with D1 — see above.)
- **Spawn-failure bookkeeping.** This wave owns it, and the ownership question
  below is answered rather than open: writing a verdict when a spawn exhausts its
  retries is a liveness-verdict rule, so it belongs beside the liveness work and
  not in Group C. What has to be settled as one decision is "persist a `failed`
  husk" versus "log-only", including the name-reuse carve-out a husk needs.
- **The herdr write-path fixes.** Raise `StateWriteDropped` on a vanish that
  follows a `working`/`blocked` report; add a cheap cached integration check
  at the two `report_state` call sites.

### Wave 2.5 — teach the store to add a table without destroying itself

**This was not in the original sequence and it is now a hard prerequisite for
Wave 3.** Adding a table is the one schema change `store._reconcile` cannot
apply in place: `_deficit` (`store.py:441-443`) classifies a missing table as
`blocking` rather than `addable`, `_reconcile` answers a non-empty `blocking`
with `_reset`, and `_reset` drops `agents`, `messages` and `events`. The
codebase already says this in as many words, in `plugins.py:606-608`: "A
plugin's table is the one shape of schema change that cannot be migrated in
place, and the store's answer to it is to drop `agents`, `messages` and
`events`."

This was verified against a copy of the real store, not reasoned about: append a
`workspaces` `CREATE TABLE` to `store.SCHEMA` and run the real
`_deficit`/`_reconcile`. With the fleet live, `_reset` raises `LiveAgentsError`,
`_reconcile` catches it, and all rows survive. With the fleet drained — the
ordinary state of this machine between sessions — the same call took 101 agents,
254 messages and 11752 events to 0, 0, 0. **The live-fleet guard postpones the
wipe; it does not prevent it.** It would fire on the first `sb` command run from
any worktree after the fleet goes quiet, including during development, since
every worktree of this repo shares one store.

The capability: a missing *table* whose columns are all nullable is `addable`,
not `blocking`. `_reconcile` creates it inside the existing "nothing is
blocking" branch and then runs a `_BACKFILLS`-style populate, exactly as it
already does for a newly ALTERed column (`store.py:335-344`). The nullable
restriction is what keeps this honest — it is the same test `_deficit` already
applies to columns, for the same reason, so the rule stays one rule rather than
two.

**Three further requirements, all found by round 4, all first-class parts of this
wave rather than notes for the implementer.**

**1. `_reset` must derive the set it drops from the schema, because otherwise the
fourth table bricks the store.** `_reset` drops a hardcoded three tables and then
re-runs the *whole* `SCHEMA` (`store.py:529-531`, `468-474`):

```python
for t in ("agents", "messages", "events"):
    db.execute(f"DROP TABLE IF EXISTS {t}")
_create(db)                      # db.executescript(SCHEMA)
```

Append a fourth table and `executescript` hits a `CREATE TABLE` for a table that
was never dropped. This was verified against the real `_reset(force=True)` with a
`workspaces` table appended to `SCHEMA`, and **the outcome depends on where in
`SCHEMA` the new table is declared, which is not the sort of thing a design may
leave to be noticed**:

- **Declared after the three:** the script recreates `agents`, `messages` and
  `events`, then raises `OperationalError: table workspaces already exists`. The
  three tables are left recreated and *empty*, and the exception escapes `_reset`,
  escapes `_reconcile` (which catches only `LiveAgentsError`) and escapes
  `connect()`.
- **Declared before the three:** the script raises on the first statement, so
  `agents`, `messages` and `events` are dropped and never recreated. The store is
  left holding **only** the `workspaces` table and every later `connect()` fails
  identically. That is a permanent brick of every `sb` command on the machine,
  recoverable only by deleting the store by hand.

The trigger is multi-actor by construction: `_reset` fires on the first `sb`
command run from any worktree after the fleet drains, and `sb doctor
--reset-store` reaches the same code by name. So `_reset` derives its drop list
from `SCHEMA` itself — every table the schema declares, dropped before `_create`
runs — and the declaration order of the new table stops mattering. Statement
order deciding between "silently emptied" and "permanently bricked" is the reason
this is specified here rather than left as an implementation detail.

**2. The DDL must be idempotent and the loser must not escape `connect()`.** Two
processes that both computed the deficit before either acted is not exotic; it is
the ordinary state of this machine. The loser gets `table workspaces already
exists`, or `duplicate column name`, or `database is locked` if it arrives
mid-transaction, and there is no `try` anywhere on that path. `connect()`'s own
docstring is the standard: *"nothing decided here may be able to stop a fleet from
draining itself."* So: `CREATE TABLE IF NOT EXISTS`, and the addable path catches
already-exists and duplicate-column rather than letting them out. Today's exposure
is one nullable column per release; this design adds `absent_since` *and* a table
*and* a backfill.

**3. The backfill's completion is its own recorded fact, never inferred from the
schema hash.** `CREATE TABLE` autocommits — verified: `in_transaction` is `False`
immediately after it — so the create and the backfill are two transactions, and a
second connection sees the table the instant it exists and none of the backfilled
rows until commit. That gives an interleaving with no crash required beyond an
ordinary kill: A creates the table and starts backfilling; B connects, finds
nothing missing, stamps `meta.schema_hash` as current and commits; A dies
mid-backfill and its rows roll back. End state: the table exists, it is empty, and
the hash says the store is current — so `_reconcile` short-circuits on the hash
for every later process and **the one-time backfill never runs again**.
`sb workspace close` then hits "refuse when the path is unresolvable" for every
workspace that predates the table, permanently. That is exactly the "inert against
the entire existing state is not conservative, it is absent" failure the backfill
was added to prevent, reached by an interleaving instead of an omission. The fix
is the `claim_agent` shape once more: the backfill records *that it completed* as
a fact of its own, and a process that finds the table present but the backfill
unrecorded runs it.

**Its cost, stated plainly: this changes the most dangerous code in the store.**
`_deficit`/`_reconcile`/`_reset` is the path that can cost someone every row
they have. So it does not ship on unit tests alone — it must be proven against a
copy of the real database, and the reproduction above is precisely that test,
run in reverse: the same script, on the same store copy, with the fleet drained,
must end at 101/254/11752 rather than 0/0/0.

It is also worth more than this design. `plugins.py:606-608` documents the same
limitation as the reason a plugin may not keep anything in `state.db`; the
capability lifts that restriction too, which is why it gets its own place in the
sequence rather than being buried inside Wave 3.

### Wave 3 — the workspace end-of-life representation

A real `workspaces` table **keyed on the workspace name**, carrying a nullable
checkout path, `retired_at` and a retiring mark that records its owner (round 4:
the mark is claimed by conditional write and a rollback checks the owner, so
"who holds it" is part of the schema, not an implementation detail), plus
`sb workspace list` to find orphans. There is no first-class workspace entity today — `workspace_branch` and
`known_workspace` (`store.py:698-721`) both derive "the workspace" by
grouping `agents` rows. A retired workspace and a fresh one are the same row
shape.

The key has now changed twice, and the second change supersedes the first. Round
2 moved it off `workspace_id`, correctly: `workspace_id` is not a function of a
checkout — on this machine `w16` names two different checkouts, one of them the
human's primary non-worktree clone, and the actively working `fix-options-2`
workspace has no `workspace_id` at all. Round 2 then moved it onto the checkout
path, which fixed that collision and created a worse one. The argument is in
Group A; the short form is that four bare workspaces share one path, so one row
would hold all four. The name is the key. The path is an attribute.

This still depends on Wave 1's poisoning fix, though for a weaker reason than
before: the key no longer reads the column, but retirement bookkeeping and the
row-grouping behind `sb workspace list` still do, and they are worth nothing
while spawns are actively writing dead and guessed ids.

**`sb workspace list` enumerates from the union of three sources, not from git
alone:** `git worktree list`, the `workspaces` table, and the distinct workspace
names in `agents`. Each source knows something the others do not.

- Only git knows about a worktree no agent was ever recorded in, and reporting
  exactly that orphan is a large part of the command's purpose;
  `/Users/andrew/.herdr/worktrees/switchboard/fix-options` is on disk right now
  with zero agent rows.
- Only the table knows about a workspace with no worktree and no rows — including
  every retired one.
- Only `agents` knows about a workspace that exists but predates or escaped the
  table.

An earlier version of this rule said the command "starts from `git worktree list`
and joins the table — not the other way round." That was right about the failure
it named and wrong as a complete rule, because bare workspaces are not worktrees:
`git worktree list` shows the primary checkout once, so `main`, `main-2`,
`main-3` and `main-4` cannot appear as four things from the git side, and under
round 2's path key they could not appear as four rows from the table side either.
The diagnostic that exists to find what has accumulated would have been blind to
four of the eight spaces open right now. Keying on the name (above) is what makes
bare workspaces *representable*; enumerating from the union is what makes the
list actually ask for them.

The command is sold as the diagnostic that today requires cross-referencing
`git worktree list` against the store by hand, so it has to hold every side of
that cross-reference: worktrees with no rows, rows whose worktree is gone, bare
workspaces with neither, and the branches left behind by any of them — including
the unmerged ones `-d` will refuse to delete.

**The already-gone path ships here, not in Wave 4.** Deregistering a worktree
whose directory no longer exists and deleting its branch is specified in section A
as its own small path, and it needs none of Wave 4's machinery — no inventory, no
confirmation, no destruction of anything that exists. It is the cheapest real
win available on this machine (55 rows, five branches) and it should not wait
behind the full destructive command. It carries one hard constraint from section
A that survives into this wave because this is where the code lands: the
deregistration names the one path, and a bare repo-global `git worktree prune`
never appears in it.

It should surface, per workspace, two things beyond the rows: the weight of
ignored content in the checkout (what `git status --porcelain --ignored` finds
that is not switchboard's own symlinks, and how much of it there is), and
whether anything is live in that directory. Those are the two facts Wave 4's
gate is built on, and until Wave 4 exists, manual pruning is the answer — so
the person doing it by hand should be told the same things the command would
have checked. It also gets both signals exercised, read-only, before anything
destructive depends on them.

### Wave 4 — the destructive workspace-close command

Needs all the earlier waves, for three separate reasons:

- it hooks off the cleanup close loop, so it needs Wave 2's *confirmed*-gone
  branch rather than a second, independently-evolving "is this agent really
  closed" test;
- its "is every agent in this workspace finished" gate is only as good as the
  liveness verdicts behind it — a false `failed` from Wave 2's unfixed bug
  makes teardown believe a workspace is empty when it is not;
- it needs somewhere to record that a workspace is retired — and now also the
  checkout path, and a retiring mark that `workspace_new` refuses to join —
  none of which exists before Wave 3.

**Wave 4 got more expensive as a result of the first adversarial review, and
that strengthens the staging argument rather than weakening it.** What was
three bullets is now a path recorded as fact, a gate scoped to a directory
rather than an id, a live observation with a refuse-on-unknown rule, an
ignored-content classifier that knows switchboard's own furniture from the
human's, a check-stop-reconfirm-delete ordering, a re-entrant two-phase state
write, and a confirmation built from an inventory. That is a substantially larger
piece of work than the rest of the document's items put together. It is also
the only item whose failure mode is unrecoverable, and every one of those
additions was found by reading the design rather than by losing someone's
`.env`. Waves 1–3 are non-destructive and were cleared on this axis; they
should not wait behind Wave 4's new weight, which is exactly what staging them
separately buys.

**And the fourth round added more of the same.** An owned, atomically-claimed
retiring mark with an ownership-checked rollback; a `lsof`-based cwd enumeration
with a mandatory refusal when it cannot be made; caller-exclusion and
component-wise path containment; and `git worktree remove` by name rather than a
repo-global prune. None of that is optional and none of it is small. Wave 4 is now
comfortably the largest single item in this document, and the case for shipping
waves 1–3 without it is correspondingly stronger.

**The second review round moved weight the other way, into Wave 3.** What was
described as the cheap, obviously-safe wave — "just a small table" — turned out
to contain the single most dangerous change in the document, because the table
cannot arrive without changing `_reconcile`. Wave 3 is no longer the warm-up for
Wave 4; it is the piece that needs proving against a copy of the real database.
Waves 1 and 2, meanwhile, were cleared a second time on a second axis — they
change predicates and error handling and read nothing they assume to be clean,
and `absent_since` is a nullable column, which is the *safe* shape of schema
change here. They should ship without waiting for any of this.

### Tab teardown is not work, and the experiment that says so

This document previously deferred the whole tab item on an untested precondition
— "check first, with a throwaway herdr experiment, whether a tab actually
outlives its last pane closing." The experiment has now been run, twice, against
live herdr on this machine: a workspace `w1H` was created, a second tab `w1H:t2`
added, and that tab's only pane closed — `t2` was gone from `herdr tab list`.
Then `w1H:p1`, the workspace's last pane, was closed, and the whole workspace was
gone from `herdr workspace list`.

**herdr collapses a tab when its last pane closes, and collapses a workspace when
its last tab closes.** Two things follow, and both close items rather than
deferring them:

- **The tab item is not work.** No `tab_id` column, no `close_tab` call, no wave.
  A tab is a container that does not outlive its contents, and the pane path
  already handles the contents. The audit's fix sketch for it is retired.
- **A worktree-backed herdr space also collapses for free**, once the workspace's
  agents' panes are closed — which the ordering rule above does anyway, at step
  2, before anything is deleted. That is why no `close_workspace` wrapper appears
  anywhere in this design either.

The design proposed neither wrapper before this experiment, and that was right by
accident rather than on purpose. It is now on purpose, with the reason stated:
the wrappers would be code that does nothing.

### The ownership question, now answered

**Spawn-failure bookkeeping sat between two groups. It goes to the liveness
group, in Wave 2.** When a spawn exhausts herdr's retries, `delegate`'s except
path hard-deletes the claim row (`broker.py:1365-1373`), so the failure leaves no
`failed` verdict and no trace on the board — real herdr effort was spent and
failed loudly, and the evidence is discarded. The desired end state is that
the row carries a `failed` verdict rather than being deleted or left
`working`.

Group B leaned toward the cheaper "keep the delete, always log the failure
event by name," explicitly deferring to Group C on the grounds that "does a
row survive its own end, and in what form" is Group C's question. Group C's
mail fix does not need rows to persist past their end, so it did not answer.
Neither group owned it, and it must not be built twice under two names. **It is
assigned here: the liveness group, in Wave 2**, because writing a verdict when a
spawn exhausts its retries is a liveness-verdict rule and nothing else. What that
owner must settle, as one decision rather than two, is "persist a `failed` husk"
versus "log-only", including the name-reuse carve-out a husk needs
(`claim_agent`'s `INSERT OR IGNORE` at `store.py:649-655` requires the name
to be free; `_spawn_lead` already has husk-handling to mirror at
`broker.py:906-908`).

One caveat on the evidence: the live incident that raised this could not be
reproduced. `delegate`'s except path looks correct on paper, so the observed
`working` row may have been seen mid-retry — which is correct behaviour
during `SPAWN_GRACE` — rather than left behind. That changes which fix is
needed: if the row genuinely survives, that is a bug in shipped code; if it
was a mid-flight observation, the real gap is that nothing tells a
backgrounded caller the spawn eventually failed. Confirm which before
building.

---

## Group A — teardown and workspace end-of-life

**The problem in a sentence.** Nothing anywhere removes a worktree, deletes a
branch, or purges a workspace's rows; there is no way to list workspaces or
find orphans; and a retired workspace is indistinguishable from a fresh one.

Verified at HEAD, all still true:
`grep -rn "worktree remove\|worktree prune\|rmtree\|close_workspace\|remove_workspace\|delete_workspace" switchboard/`
returns zero hits. `herdr.py` has `create_worktree` (`herdr.py:329-349`) and
`open_worktree` (`herdr.py:351-365`) with no counterpart. The `agents` schema
(`store.py:140-168`) has no `tab_id` — and, per the herdr experiment recorded in
section B, does not need one, because a tab does not outlive its last pane.
`cli.py:243-245` registers
`workspace new` and no other verb. `workspace_new`'s idempotency check
(`broker.py:622-634`) asks only whether the lead row exists and is alive —
there is no flag anywhere meaning "deliberately retired."

`f1193d0` did not touch teardown but changed the shape of the problem: every
bare `sb start` now mints a new name and opens a new herdr workspace
(`broker.py:580-647`), so this group's fix has to collect workspaces nobody
created with `sb workspace new`. And `_tab_for` (`broker.py:1133-1161`) can
now legitimately NULL a `workspace_id` on a row that used to have one, so
"NULL" no longer implies "old row predating the column."

**The candidates and the argument** are in section A above. The pick is the
staged form: retired-marking first as a pure state write, then the explicit
destructive command. Automatic pruning inside `cleanup()` is rejected.

**How end-of-life should be represented.** A `retired_at` fact on the
workspace, not on any agent row. The first round settled *that* much; the second
round reopened both of the choices underneath it, because the shape this
document proposed — a `workspaces` table keyed by `workspace_id` — is wrong
twice over. Adding any table wipes the store (Wave 2.5), and the key itself does
not work. The third round then showed that round 2's replacement key does not
work either.

**Why `workspace_id` does not work.** It is not a function of a checkout. On this
machine `w16` is recorded against two different directories at once — `main-3` in
`/Users/andrew/Code/switchboard`, the human's primary non-worktree clone, and
`revise-design` in the `fix-options-2` worktree — so a table with one `checkout`
column per id cannot represent it at all, and whichever path a backfill picked
would be wrong for half its rows. In the other direction, `fix-options-2` itself
— six rows, actively working, the workspace this document was written in — has no
`workspace_id`, so a table keyed that way could not enumerate it. The mechanism
is `_tab_for`'s bulk clear followed by the next spawn re-deriving an id from a
lower tier, and the store records it happening twice: two `workspace_gone`
events, `wG` and `w18`, on consecutive days.

**Why the checkout path does not work either — and this supersedes round 2.**
Round 2's fix was to key the table on the checkout path. That removed one
collision and introduced a worse one, which nothing re-tested at the time: a bare
workspace has no checkout of its own, so *all* bare workspaces over one clone
share one path. There are four here — `main`, `main-2`, `main-3` and `main-4`,
all recording `/Users/andrew/Code/switchboard` with a NULL branch. A table keyed
on the path holds one row for all four, and every consequence is fatal to the one
operation the design grants a bare workspace:

- `retired_at` for `main-2` is `retired_at` for `main`, `main-3` and `main-4`.
  Retiring one retires all four.
- The retiring mark is worse than useless: `workspace_new` refuses to join a
  workspace marked retiring, so retiring `main-2` locks three live orchestrators
  out of their own workspace.
- The one-time backfill derives one key for four workspaces at migration time.

This is not a corner. `f1193d0` made every bare `sb start` mint a fresh top-level
orchestrator, so bare workspaces are the fastest-accumulating kind in the system,
and four of the eight herdr spaces open right now are exactly these. They are
what the person watches piling up. Round 2's key gives them nothing, and does it
while the *same revision* introduced the case.

**The fix is to stop conflating two things.** Identity and gate scope are not the
same key and never had to be:

- **Identity: the workspace name.** It is what the person types. It is unique by
  construction — the same name always means the same workspace. Four bare
  orchestrators are four names. And an id that is not a function of a checkout
  never enters into it.
- **Gate scope: unchanged — the checkout path, plus a live observation.**
  Destruction is about a directory; identity is about a workspace. Round 1 and
  round 2 were each right about their own half and wrong only in assuming one key
  had to serve both.

**Candidate A — a `workspaces` table keyed on the workspace name**, carrying the
retiring mark *and its owner*, `retired_at`, and the checkout path as a nullable
recorded attribute, delivered through the new store capability of Wave 2.5 and populated
by a one-time backfill. **NULL path is exactly how a bare workspace is
represented**, which is not a workaround but the honest model: a bare workspace
genuinely has no checkout of its own, and the schema already says so by leaving
`branch` NULL. The thing being retired is identified by name; the thing being
destroyed is identified by path; a workspace with nothing to destroy simply has
no path, and the destructive machinery never runs for it.

**Candidate B — no new table: a nullable `retired_at` column on `agents`.** This
is the safe addable shape, it needs no change to `_reconcile`, and it is the
fallback the second review round itself suggested. **Rejected**, for two
reasons. First, Group A's original objection still stands and the second round
gave it no new answer: "the workspace is retired" becomes an AND over N rows
that can drift, so a missed `UPDATE ... WHERE workspace_id=?` leaves a workspace
half-retired and reopening has to clear a flag on every row rather than flip
one — and the `WHERE` clause is over the very column just shown not to be a
function of a checkout. Second, and decisively: a workspace with zero agent rows
has nowhere to put the column. That is not hypothetical either — the
`fix-options` worktree is on disk right now with no rows at all, and it is
exactly the orphan `sb workspace list` exists to report. Under B it could never
be listed and never be retired.

**Pick: A**, and its real cost is stated rather than absorbed: it means changing
`_reconcile`, the most dangerous code in the store, so it must be proven against
a copy of the real database before it ships. The reviewer is right that the tidy
option was the destructive one. The answer is to make adding a table
non-destructive — which pays for itself beyond this design, since
`plugins.py:606-608` documents the same limitation blocking plugin tables — not
to give up on modelling a workspace as a thing.

**Cost if the staging is wrong.** If the retired state and the removal step
would always have shipped together anyway, the cost is one extra column and a
slightly more indirect code path — a removal step checking a flag someone
else set rather than computing the condition inline. Cheap. The asymmetry
against the alternative is the whole argument.

---

## Group B — liveness

### A single bad reading marks a live agent `failed`

**The problem.** `status._record_gone` (`status.py:428-458`) writes
`state='failed'` off one `h.list_agents()` snapshot the moment
`gone = running and alive is False and not spawning` holds
(`status.py:401-402`), from `collect()` with `reap=True` — the default that
every short-lived `sb` command uses (`status.py:314`). There is no retry.
`broker._end_still_holds` (`broker.py:1907-1925`) is a second *poll*, not a
second sample gating the first write, and it runs later against a row already
marked `failed`. Both polls call the same herdr; a bad stretch and both agree
and both are wrong. `status.py:337-339`'s own comment records this happening:
three agents marked failed during startup.

**Candidate A — debounce across invocations.** Port `ask()`'s existing vanish
detector (`broker.py:1486-1503`) into the store: an `absent_since` column,
set the first time a row computes `gone` without being written, cleared the
moment the agent reappears, with `_record_gone` firing only once the row has
been absent past a window.

**Candidate B — retry inside one `collect()` call.** Have the process about
to write re-poll herdr a couple of times with a short sleep first, mirroring
`herdr.start_agent`'s attempts/backoff loop (`herdr.py:435-450`) on the read
side.

**The argument.** A adds a nullable column and a comparison in a path every
`sb` command runs; B adds no schema but adds latency, and a board refreshing
every 2s (`board_refresh = 2.0`, `defaults/settings.toml:291`) doing two or
three herdr calls per tick per absent row is a materially heavier polling
load — which collides directly with Group D's write-path concerns. A is
trivially testable with a fake clock, the way `test_status` already pins
`SPAWN_GRACE`; B needs a mocked multi-call subprocess boundary and controlled
sleep. A is adjacent to a debounce shape the codebase already has; B has no
precedent on the read side.

**Pick: A**, expressed as a wall-clock grace window rather than a call count.
`collect()` has no sleep loop, so "N polls" means "N separate `sb`
invocations," which could be seconds or hours apart and therefore means
nothing. A new `GONE_CONFIRM_GRACE` on the order of the existing 60s
`gone_grace` — not `SPAWN_GRACE`'s 282s, which guards a different question.

**Cost if wrong.** Too short reproduces today's bug in smaller form; too long
means a genuinely dead agent sits `working` for longer, which is the *next*
finding's failure mode. The two constants have to be chosen and tested
together.

### A dead agent is invisible for ~4.7 minutes, then wrong forever

**The problem.** While `spawning` is true — `session_id is None` and within
`SPAWN_GRACE ≈ 282s`, derived from herdr's retry worst case at
`status.py:123-136` — `gone` is forced false (`status.py:402`). That is
correct for a row mid-spawn-retry, but a pane a human closes inside that
window is neither `gone` nor `stalled` (the code says so at
`status.py:378`). Worse, nothing self-corrects afterwards: `collect()` runs
only when invoked, and the one process that ticks unattended always passes
`reap=False` (`collector.py:111`, load-bearing per its own docstring). A row
nobody looks at again sits `working` indefinitely.

**Candidate A — give the collector a narrow repair tick.** The collector
already ticks every 2s while a board is open, already holds the `flock`-
elected singleton, and is already the one process trusted with `store` writes
(`collector.py:9-11`).

**Candidate B — a standalone background sweep**, independent of any board,
so staleness is bounded even between sessions — the collector exits within
`collector_idle_exit = 60s` after the last panel closes
(`collector.py:193-205`), so today nothing ticks at all between sessions.

**The argument, and why it is now moot.** A reused a trusted process and had an
existing test harness (`tests/test_readonly.py`'s `CollectorTick`); B needs a new
process with its own lifecycle and its own answer to "how do I get invoked when
nobody's board is open." That comparison never mattered, because **A is
impossible as specified.**

**Round 4 killed candidate A on a fact, not a race.** The collector cannot
write. `collector.py:105-106` calls `store.connect(..., readonly=True)`, and
`_connect_readonly` opens `mode=ro` (`store.py:305-311`), where *"every write,
DDL included, raises `sqlite3.OperationalError: attempt to write a readonly
database"*. This document argued the pick from `collector.py:9-11` — which says
where the `store` import is *allowed* — and never mentioned `readonly=True`, which
is the binding constraint. The consequence is not subtle: `snapshot()` wraps the
whole collect in `except Exception` and returns
`None, f"could not read the tree: {e}"` (`collector.py:104-113`), so a repair
write would make **every panel on the machine print
`could not read the tree: attempt to write a readonly database` every couple of
seconds instead of a board.**

So the choice is a new one, between two ways of putting the write somewhere it
can happen:

- **A′ — keep the collector read-only and move the repair write into the reap
  path.** Any `sb` command that already reaps (`collect(reap=True)`, the default
  for every short-lived command, `status.py:314`) does the repair. **Pick this.**
- **A″ — give the panel a writable connection.** **Refused**, and the reason is
  worth recording rather than left as taste: it re-arms exactly the hazard
  `_connect_readonly` exists to prevent. That docstring names the collector as
  *"the likeliest migrator in the tree, running whatever `SCHEMA` string it
  happened to import at startup"* — an hours-old process is the one guaranteed
  stale-code actor in the fleet. Today a writable collector could ALTER a column.
  **Once Wave 2.5 ships it could `CREATE TABLE` and run a one-time backfill
  against a store that newer code is using**, and per Wave 2.5's own F4 argument a
  stale process finishing a migration is how the backfill gets recorded as done
  when it is not. The half-deployed-waves problem lives in exactly this process.

**A′ also resolves a writer/reader split that was in the design and nobody had
noticed.** `absent_since` was to be set by whichever process "computes `gone`
without writing," but in `status.collect` the only write is `_record_gone`, gated
on `consulted and reap` (`status.py:419-421`). Inside that gate the collector
(`reap=False`) never stamps, so the rows it was supposed to repair never
accumulate absence in its view; outside it, the collector writes on every tick and
breaks the panel as above. The debounce writer and the debounce reader were
specified as two different processes with incompatible permissions. Under A′ they
are one: the stamp and the repair both live in the reap-gated path, in a process
that can write.

**The cost, stated honestly rather than absorbed.** A′ closes the gap for any
machine where somebody runs `sb` commands, which is the normal state of a working
fleet. It does *not* close it for a machine with a board open where nobody runs an
`sb` command: there, repair waits until someone does. That is strictly worse than
the collector tick this document originally promised, and it is the price of the
collector genuinely not being able to write. Candidate B — the standalone sweep —
is what would close it unconditionally, and it is worth building later if "a board
is open and nothing else runs for a long time" turns out to be a real usage
pattern; nothing suggests it is today. Note that the original argument for A over
B ("A closes it for the common case of a board being open") no longer describes
what A′ does; A′ closes it for the common case of *someone using `sb`*, which is a
different and, on this machine, more frequent event.

Fold in the constants question here, since it is the same family.
`GONE_GRACE = 60.0` (`defaults/settings.toml:222`, used only by `ask()`'s
debounce) and `SPAWN_GRACE`'s 282s are independently tuned with nothing
keeping them in sync. They answer genuinely different questions — how long a
claim looks like a spawn in progress, versus how long an `ask` target must
stay unlisted before giving up — so they should not become one constant. But
`GONE_GRACE` must never end up shorter than the window in which a
legitimately spawning agent looks absent, or `ask()` abandons a target that
simply has not finished spawning. A one-line assertion at config-load time is
cheap insurance; a shared derivation is not needed.

**Cost if wrong.** Too broad a repair scope and an ordinary `sb` command ends a
live agent's turn off a stale grace window — the same hazard the collector's
`reap=False` guarantee names, now in a process that can actually commit it, which
is an argument for keeping the scope at "continuously absent past the debounced
window" and nothing else. Too narrow and staleness persists between "row went
absent" and "somebody ran `sb`." Either failure is recoverable with
`sb cleanup --force` and `sb restore`; it reintroduces a UX problem, not
corruption.

### An idle lead reads STALLED forever, and `f1193d0` made that routine

**The problem.** `stalled = running and alive and hstate in IDLE_LIKE`
(`status.py:401`) has no exception for a lead or top-level orchestrator that
has simply finished its turn and is waiting. `_spawn_lead` passes
`cleanup="keep"` (`broker.py:916`), and `cleanup()`'s two sweep gates —
`state not in FINISHED` (`broker.py:1723`, never true, since the lead never
calls `sb done`) and `cleanup != "close"` (`broker.py:1731`, also always
true) — are both closed. The only exit is naming the agent *and* `--force`,
which lifts every other safety gate along with it.

`f1193d0` widened this: `_top` now calls `delegate(..., cleanup="keep", ...)`
unconditionally on every bare `sb start` (`broker.py:485-492`), and
`running_tops` (`broker.py:415`) only builds a hint string that nothing
branches on (`cli.py:680-687`). So every bare `sb start` not followed by real
work leaves the same unsweepable idle shape — for `main`-role top-level
agents too, once per invocation rather than once per workspace.

**Candidate A — stop computing `stalled` for "waiting for its first real
instruction."** Track "has this agent ever been given anything beyond its
spawn placeholder" as its own bit. Once flagged, the agent is ordinary and
stalled-eligible like any other.

**Candidate B — make provably-idle leads sweepable by a plain `sb cleanup`**,
a third path into the close loop bypassing both gates without touching
`--force`'s meaning.

**Candidate C — treat it as a teardown problem**: accept STALLED-forever as
the correct display for "nobody has decided this is finished," and fix it
with a workspace close verb.

**The argument.** A is narrowest — it changes what gets *labelled*, never
what gets swept, and it is a pure predicate change testable against fixed
rows. B changes `cleanup`'s actual close behaviour, in the exact function
where findings #1, #5 and #6 live, and its hard test is the negative one: a
genuinely stuck agent has the same `state='working'`, `hstate='idle'`
signature that `_spawn_lead` produces on purpose, so proving the bypass will
not sweep it is proving something the liveness data cannot distinguish. C
touches nothing and delivers nothing until Group A ships.

**Pick: A**, extended to cover `f1193d0`'s widening — the same bit for the
`main`-role top-level orchestrator, not only workspace leads. This is where
the design departs from the audit's narrower sketch, because `f1193d0` moved
the ground. It deliberately does *not* make these agents plain-sweepable;
that is Candidate C's job and belongs in Group A's teardown verb. Group A
should treat "retire an idle, never-assigned lead or orchestrator" as one of
the things `sb workspace close` does, rather than leaving `--force`-by-name
as the permanent answer.

**And that routing only works because of Group A's bare path.** An idle top-level
orchestrator lives in a bare workspace, so under the design as it stood before
round 3 — one gate, scoped to the checkout path, for every workspace — the
command this pick hands the removal to could never have completed for one of
them: it would refuse on some other orchestrator live in the primary clone, every
time. This pick would then have fixed the STALLED *label* and nothing else, and
`sb cleanup <name> --force` would have stayed the only exit, which is exactly the
complaint. With Group A's separate bare path, the routing is real.

**Cost if wrong.** The "never assigned real work" bit is coupled to the
placeholder strings in `defaults/prompts.toml:52` and `sb start`'s
equivalent (`broker.py:481`), so it needs a shared constant rather than two
copies of a literal, or it goes stale when a prompt changes. If it drifts,
the old STALLED noise returns — annoying, not destructive, since nothing here
touches `cleanup`.

### Should "genuinely stuck" be told apart from "benign idle"?

**Partially, and only as a byproduct of the previous fix.** `status.py:14-16`
documents the no-repair policy explicitly — "we deliberately do NOT repair
it... surfacing beats guessing" — and one predicate serves both cases.

Once benign idle stops reading STALLED and gets an honest label of its own,
STALLED means exactly one thing: an agent that was given real work and went
quiet without finishing. That is already trustworthy.

**Do not split it further.** The sub-causes — `sb done` itself failing, a
state write silently dropping, or an agent that really stopped — are
indistinguishable from the liveness join; herdr reports `idle` in every case.
Finer categories without new underlying signal are guessing dressed as
precision, which is what `status.py`'s stated principle warns against. A
"confidence score" for STALLED adds a data surface with nothing to assert
against, and exists mainly to make a false positive tolerable rather than
remove it.

**The no-repair policy itself should not change.** Auto-clearing STALLED is
indistinguishable from silently discarding a parent's still-outstanding wait
on that agent's work.

**Cost if wrong.** If some benign idle shape survives the fix, STALLED stays
partly untrustworthy and the temptation to bolt on a second signal returns.
That fallback should be revisited after real STALLED reports have been
observed, not designed speculatively now.

---

## Group C — cleanup's own behaviour, and identity after `sb done`

All of part one is in `Broker.cleanup`, `broker.py:1634-1745`. The audit's
line numbers drifted; the bugs are all still present.

One piece of new leverage: `herdr.py:191-208` now parses the stderr JSON
envelope on a nonzero exit and surfaces its `code` instead of collapsing
everything to `cli_failure`. `pane_not_found` is a real, already-used code
(`tests/test_output.py:131,161,255`, `tests/test_inspect.py:271`), so "the
pane doesn't exist" is now a branchable fact. Nothing in `switchboard/`
branches on `HerdrError.code` except `broker.py:1149`, so a second branch
collides with nothing.

### A hand-closed pane sticks forever under an ordinary sweep

If a human closes the tmux pane, `close_pane` (`broker.py:1732-1734`) throws,
`broker.py:1735-1737` logs `cleanup_failed` and `continue`s without `force`,
`pane_id` stays set, and every later sweep repeats it forever.

**A1 — proactive:** call `h.pane_ids()` (`herdr.py:318-323`, already used
elsewhere) once at the top of the candidate loop and skip the close for any
candidate whose pane isn't listed. **A2 — reactive:** branch on
`HerdrError.code == "pane_not_found"` at the existing catch site and treat it
as a confirmed close.

**Pick: A2.** A1 costs an extra herdr round trip, needs `pane_ids()` added to
the `FakeHerdrAPI` fixture, and still has a race — the pane can close between
the probe and the call — so it would end up layered on top of A2 rather than
replacing it. A2 reads the outcome of the call `cleanup` already makes.

**Cost if wrong.** If herdr uses `pane_not_found` for refusals other than
"this pane id is gone" — no evidence of that in switchboard's usage or tests,
though herdr's own source was not read — a plain sweep could mark a row
`done` while its pane is still open, leaving an orphaned pane with no handle.
Narrower and cheaper than today's permanently stuck row, and it is the same
trust `broker.py:1149` already places in a different herdr code.

### `--force` cannot tell stuck from busy, and logs nothing distinct

Under `force`, every gate is skipped including `state not in FINISHED`
(`broker.py:1719-1720`), so a `working` agent mid-write is closed
identically to a wedged one. The only event logged is
`kind="cleanup", forced=force` (`broker.py:1744`) either way. `f1193d0`-era
work did narrow *who* can be hit — `force` now requires an explicit name
(`broker.py:1686-1688`), so a sweep can no longer force-kill anything — but
nothing changed for what happens to a busy agent once named.

**B1 — observability only:** check `a["state"] == "working"` at the moment
force closes and log a distinct event kind, exactly the pattern
`cleanup_held` already uses for "why is that one still here." **B2 —
behavioural:** send an interrupt-style `esc` first (as `interrupt` does,
`broker.py:1874-1880`) to try for a clean stop before yanking the pane.

**Pick: B1.** It is the literal fix for what is described as broken, changes
no herdr call sequencing, and cannot break an existing assertion about what
force does. B2 adds a call, a settle sleep, and a new failure surface (what
if `send_keys` errors on a half-dead agent — does force still proceed?) for a
problem stated as one of detection, not gentleness.

**Cost if wrong.** None structural. If the real ask is "don't let force kill
busy agents so easily," B1 does not deliver it — but it does not make B2
harder to add later.

### The forced path commits "closed" bookkeeping when the close failed

`broker.py:1735-1737`'s `if not force: continue` means that under `force`,
execution falls out of the `except` block straight into
`store.set_state(..., "done")` and `update_agent(..., pane_id=None)`
(`broker.py:1738-1743`), unconditionally. A forced close against a pane that
genuinely could not be closed still marks the row `done` and discards the one
reference to that pane. **This is the genuine design fork in this half.**

**C1 — conditional commit:** only commit under `force` when the outcome is
confirmed (call succeeded, or A2's `pane_not_found` applies). Any other error
leaves the row untouched and logs a distinct event. **C2 — unconditional
commit, honest logging:** keep the contract, log the discrepancy distinctly
rather than leaving it implied by a generic `cleanup_failed` plus
`cleanup(forced=True)` pair.

**Pick: C2.** C1 is more correct in the narrow sense — the store never
asserts a pane is gone unconfirmed — but it changes what `--force`
*guarantees*. Its own docstring frames it as the override that always works
("force lifts every safety gate... naming it IS the confirmation",
`broker.py:1651-1656`), and under C1 someone force-closing a genuinely stuck
agent during a herdr blip finds the row still stuck and has to run it again.
The finding is not "force sometimes fails to close"; it is "force commits
success bookkeeping silently when it isn't success." C2 removes the silence
without touching the guarantee.

**Cost if wrong — and this one should be read before accepting the pick.**
During a real herdr outage, force-closing a batch marks every row `done` with
`pane_id=None` while the tmux panes may still be alive: orphaned, unreachable
through the store, with no `pane_id` left for anything to act on. That is the
trade. `--force` should not be scripted in a loop during a herdr incident
without a human checking the new distinct event afterwards. It is also the
seam where this pick meets Group A's teardown gate — see "Where the designs
collide."

### Mail and `sb interrupt` after `sb done`

The brief marked this observed, not code-traced. It was reproduced against
the existing `FakeHerdrAPI` fixture with a throwaway script: create a
lead/child pair, call `Broker.done(me="child")`, make herdr return
`agent_not_found` for that name (what a real Claude Code process does once
its turn ends), then `tell` and `interrupt` the child as the lead.

Observed directly:

- `tell()` returns normally, no error to the caller. The message row sits
  with `delivered_at=NULL` and shows in `store.undelivered(db)`.
- Two `ring_failed` events land — one from `tell`'s `_ring`, one from
  `flush_pending`'s retry on the very next store touch.
- `interrupt()` raises `Undeliverable`, exactly as reported.

The trace: `Broker.done` (`broker.py:1554-1584`) sets `state='done'` and
pushes an idle report but never clears `pane_id` and never tells herdr the
name is retiring. `tell` (`broker.py:1394-1434`) never checks the target's
state, writes the message unconditionally, and calls `_ring`. `_ring`
(`broker.py:1976-2008`) catches the `HerdrError`, logs `ring_failed`, and
returns `False` unforced. `flush_pending` (`broker.py:1935-1971`), which runs
at the start of *every* `sb` invocation by *anyone* (`cli.py:552-556`),
re-attempts the same doomed ring forever — its design assumes the target
eventually comes back and runs a command, which a `done`'d agent never will.
`interrupt` (`broker.py:1855-1884`) swallows the `send_keys` failure but then
calls `_ring(force=True)`, which does raise.

**One consequence not in the audit:** the never-delivered, never-read message
keeps `store.unread_for` (`store.py:839-854`) reporting it, so `cleanup`'s
"unread mail would be lost" gate (`broker.py:1728-1729`) refuses to close
that row even on a plain sweep — for mail nobody can ever read. A `done`'d
agent someone tried to reach becomes stuck behind the same `--force` path as
a hand-closed pane, for an unrelated reason.

**D1 — guard before sending:** look up the target row first; if
`state in FINISHED` (`broker.py:85`, already imported) with no confirmed-live
pane, skip the ring entirely — the message is still written, just never
attempted. For `interrupt`, refuse immediately with a plain message rather than
surfacing herdr's `agent_not_found` as `Undeliverable`.

**Correction, from the second review round: the guard does not belong at `tell`
and `interrupt`.** This document claimed that guarding those two call sites
means "`flush_pending` stops retrying a call certain to fail." It does not.
`flush_pending` (`broker.py:1935-1971`) goes through neither call site — it
re-derives its work list from `store.unseen` and calls `_ring` itself, so a
write-time guard leaves every message already on disk retrying forever. That
backlog is not theoretical: eight unseen messages are sitting for `done` agents
right now, and `ring_failed` events are still accruing today, 3208 of them.
**The guard belongs where the ring happens** — at `_ring`, or equivalently in
`flush_pending`'s work-list derivation — which covers `tell` and `interrupt` for
free. And because the guard only stops *new* attempts, D1 also needs a one-time
sweep of the existing backlog; nothing in the design provided one.

**D2 — reactive:** keep attempting delivery, but when `_ring` gets
`agent_not_found` for a target with no realistic path back, mark that message
terminally undeliverable so `flush_pending` stops retrying it and readouts
can show "this will never be delivered."

**Pick: D1.** One guard clause at two call sites, using state already loaded
and imported, fixing both halves of the finding with no new message-store
concept or event taxonomy. D2 covers a case D1's state check cannot — an
agent that dies *without* calling `sb done`, whose row isn't `FINISHED` yet —
but that is a liveness question, not an identity-after-finishing one, and D2
alone does not fix `interrupt` at all, since `interrupt` never goes through
`flush_pending`. **D2's mechanism should be handed to the liveness group**
rather than reinvented under a second name: "a definitive herdr failure
should become a terminal, surfaced verdict rather than a silent infinite
retry" is the same instinct as the liveness debounce.

D1 is safe against the one edge case worth naming, but not for the reason this
document gave, and round 4 is right that the sequential reading is what made the
old argument look sound. `whoami`'s `_revive` (`broker.py:296-306`) flips a
`FINISHED` row back to `working` when the agent runs `sb` again — and the
ordering is the opposite of what was claimed. `cli.main` calls `b.flush_pending()`
at `cli.py:552-556`, *before* dispatch; `_revive` runs later, inside `whoami()`
during the command. So in the reviving agent's own process the row still reads
`done` when `flush_pending` runs, D1's guard skips the ring, and **the invocation
this document said delivers the mail is the one invocation that cannot.**

The correct statement is delay, not loss: the message stays written and unseen,
and delivery waits for the next `sb` anyone runs — which in a live session is
soon and in a quiet one is not. D1 is still safe (nothing is dropped, the row is
still there to be found), but "picked up on that very invocation" was wrong and is
withdrawn.

**Cost if wrong.** D1 misfires only if a `FINISHED` row can legitimately be
rung — no such path was found; `_revive` is the only way back to `working`
and it fires only when the agent itself runs `sb`. The realistic cost is that
`interrupt` becomes stricter: targeting a name that just reported done gives
an immediate plain refusal instead of a herdr-flavoured `Undeliverable`,
which is a clearer failure, not a worse one. No message data is ever lost.

**A second correction, and this one was a factual error about A2.** This
document told whoever implements D1 that the unread-mail-blocks-the-sweep
consequence above "is a `cleanup` problem that A2 addresses," and not to solve
it in the same change. That is wrong, not merely optimistic. In `cleanup`
(`broker.py:1715-1745`) the unread gate `continue`s *before* the close is ever
attempted, so A2's `pane_not_found` branch is unreachable for exactly these
rows — the row never gets as far as the call whose error A2 branches on.
`split-fixer` is in that state on this machine now (`state=done`, a live
`pane_id`, one unseen message) and is closable by neither a plain sweep nor A2.

What actually closes it: a finished agent's unread mail must bounce or route
rather than jam its row forever — which is D1's territory, not A2's. So the two
fixes have to land together, and the instruction above is reversed: D1's
implementer owns this consequence.

---

## Group D — the herdr write path, and the small items from `f1193d0`

### A dropped state write onto a vanished agent is never flagged

`Herdr.report_state`'s read-back verification (`herdr.py:576-591`) raises
`StateWriteDropped` only when the agent is still visible and its state
mismatches — `if got is not None and got.state not in equivalent`
(`herdr.py:583`). If the agent has vanished by the time the verify runs,
`got is None` and the function returns silently, treating a write that may
have no-opped as confirmed. The API lies in both directions: a stale seq and
a session-owner conflict both return ok (`herdr.py:566`). Only two call sites
exist (`broker.py:2029`, `2046`); only `_push_state` verifies, and it already
catches and logs `state_dropped` (`broker.py:2046-2050`) without propagating.

**A — raise whenever `got is None`.** Simplest, and changes no control flow
since the only real caller logs and continues. But `report_state` cannot
express "done" — herdr derives that itself from an unfocused idle pane
(`herdr.py:566-568`) — so an agent that reports `idle` and exits, the
ordinary end of a life, would log `state_dropped` every single time, diluting
the one event that exists to mark a genuinely stale board.

**B — raise when `got is None` and the reported state was not `IDLE`.** The
function already special-cases `IDLE` two lines earlier
(`equivalent = {state, "done"} if state == IDLE else {state}`,
`herdr.py:582`) for exactly the reason that `idle` is what an agent sends
moments before disappearing. Nothing transitions from `working`/`blocked`
straight to gone without an intervening `idle`/`done`, so a vanish right
after a `working`/`blocked` report is the corruption signal the exception
exists for.

**Pick: B.** Two lines, reusing the file's own model rather than inventing
one, targeting the suspicious case instead of every vanish.

**Cost if wrong.** If agents die mid-`working` more often than the lifecycle
implies — a human closing a pane mid-turn, which is the exact scenario this
whole audit is about — B produces `state_dropped` events that really mean
"agent died," overlapping the liveness findings. Log noise, not a correctness
regression, and distinguishable after the fact by whether the row was marked
failed around the same time.

### The bundled-integration conflict check never runs automatically

**Corrected from the audit's framing.** `Herdr.check()` (`herdr.py:229-244`),
whose docstring says "fail loudly at startup rather than mysteriously
mid-run," is called from exactly one place in the tree: `sb doctor`'s success
branch (`cli.py:633`). `main()` (`cli.py:504-561`) never calls it. It is not
"checked once at startup and never again" — it does not run automatically at
all. If a conflicting `claude` integration is installed, every command's
state writes look successful and are not, for the whole session.

**A — call it in `main()`** right after `h = Herdr(...)` (`cli.py:544`), so
every command pays for it and hard-fails as `check()` already does. Matches
the documented intent, one line. Costs a subprocess spawn on every `sb`
invocation and introduces a hard failure for commands that write no state at
all — `sb status`, `sb log` — which were never at risk.

**B — cache with a TTL in the store**, mirroring how `schema_deficit`
surfaces a persistent degraded banner (`cli.py:632-637`), warning rather than
blocking. New persistence and a new degraded-state class for a problem whose
blast radius is two call sites.

**C — cache per-process on `Broker`** (the pattern `_ws_ids`/`_alive_cache`
already use), check lazily the first time either `report_state` site actually
fires, and log a distinct event instead of hard-failing.

**Pick: C.** Proportionate to where the risk lives, costs a subprocess only
in processes that actually attempt a state write, and matches the "log and
continue" posture the file already takes one line away for
`StateWriteDropped` — while leaving `check()` in `doctor` as the loud,
deliberate diagnosis it reads as.

**Cost if wrong.** If the real failure mode is "the session is silently
useless the moment the integration appears," a log event still needs a human
to notice it; someone could burn a whole session before spotting it, where
Candidate A would have stopped them at the first command. That is the direct
trade.

### Clearing a dead workspace id poisons every later row — the Wave 1 item

The mechanism is in section B. What matters for the design:

`_tab_for`'s bulk clear is *correct* — it is an honest "we don't know
anymore" for the rows it touches. The bug is that `_tab_for` has no way to
tell its caller "I fell back, don't record this," so `delegate` writes the
pre-call `wsid` (`broker.py:1341` → `1358`) and `_spawn_lead` does the same
with `ws["workspace_id"]` (`broker.py:913-918`). Note the comment at
`broker.py:1357`: "Recorded, not re-derived later: this is the id its own
children inherit."

`restore()` (`broker.py:1825-1850`) already does the right thing — it calls
`_tab_for` and rewrites only `pane_id`, `terminal_id`, `ended_at` and
`state`, never `workspace_id`, so a restoring row correctly keeps the NULL
the clear gave it. **The fix is making `delegate` and `_spawn_lead` behave
the way `restore` already does**, not inventing anything.

**Candidate 1 — stop writing values just proven or suspected wrong.** Change
`_tab_for` to return `(pane_id, effective_workspace_id)` and have the two
callers record the corrected value. Separately, have `_parent_workspace_id`
mark a tier-4 (name-derived) answer as unconfirmed, and have the single write
site persist only ids from tier 1/2/3 or a workspace created moments earlier
— never a name-derived guess, never an id `_tab_for` just rejected.

**Candidate 2 — a background reconciliation pass** re-validating every row's
`workspace_id` against herdr's live registry. Covers a broader class of
staleness but is new machinery that overlaps the liveness group's work, is
hard to test deterministically (it needs simulated drift over time, not one
bad call), and does not stop the bug firing between passes.

**Pick: 1.** The truth already exists — in `_tab_for`'s clear and in
`restore`'s already-correct non-write. It just fails to travel three lines to
the write site. It is also never worse than today: a row left with
`workspace_id=None` instead of a wrong guess falls through to the next tier,
which is what the tier system is for.

**Cost if wrong.** Nothing new can break. Worst case some rows keep hitting
the ambiguous tier-4 guess repeatedly instead of it sticking as though
verified — no worse than today, just not fully solved.

**The deeper point, worth carrying into Wave 3.** `_tab_for`'s dead-id
detection and `_parent_workspace_id`'s four-tier "what do we actually know"
model are two halves of one question: is this workspace id still real. Only
one half is currently honest about uncertainty. The write site should be the
single place that decides what is fact worth persisting, rather than that
judgement being scattered across three call sites that each trust a local
variable.

**Riding along in the same patch:** `_tab_for` clears the store
(`broker.py:1156-1158`) but not `self._ws_ids` (`broker.py:1082`), the
per-`Broker` cache `_workspace_id()` fills and reads
(`broker.py:1076-1094`). Within one invocation, a second lookup of the same
workspace name returns the already-dead id from cache, retries `_tab_for`,
and fails identically. Real, but self-limiting — one process rarely resolves
the same name twice, and the cost is a wasted round trip and a duplicate
`workspace_gone` log line, not a wrong outcome. One line, evicting by value
in the same except-branch, for the same reason: stop handing out an id just
proven dead.

### The stale docstrings — cosmetic, with one exception

`_running_tops` became `running_tops` (`broker.py:415`); the old name
survives in docstrings at `broker.py:986`, `broker.py:990`,
`broker.py:1918`, `store.py:745`, and a comment at
`tests/test_broker.py:1264`. Three are a zero-risk rename.

The fourth is not. `broker.py:986-990`, inside `_alive_or_unknown`'s
docstring, justifies its fail-open posture by saying that guessing "dead"
risks "spawning a second orchestrator on top of a live one" which
`running_tops` fails open to avoid. That is no longer true for unnamed
`sb start`, which now always spawns another orchestrator regardless
(`broker.py:411-413`) — `running_tops`'s own docstring says as much two lines
away ("Nothing branches on this any more," `broker.py:427`). It *is* still
true for the one path that still calls `_alive_or_unknown`: `_top`'s
named/restore branch (`broker.py:459`, `sb start --name X`), where guessing
wrong really does risk resuming a live session in a second pane. So this one
needs its reasoning re-scoped to the named/restore path, not just a rename,
or the doc keeps teaching the next reader a justification that no longer
matches the code it documents.

---

## Where the designs collide

Two picks genuinely pull against each other, and one shared assumption needs
a decision before Wave 3. These are stated rather than quietly resolved.

**1. `--force`'s unconditional commit versus teardown's "every agent
finished" gate.** Group C picked C2: keep `--force`'s documented contract
that the row always ends `done`, and make the failed-close case loud rather
than silent. Group A's teardown command then gates destruction on "every
agent recorded against this `workspace_id` is FINISHED." Under C2, a batch
force-close during a herdr outage marks rows `done` while their panes may
still be alive — which is precisely a state where teardown's gate passes and
the workspace is not actually empty. C2's cost-if-wrong and Wave 4's
precondition are the same event, seen from two directions.

This does not invalidate either pick, and section A now answers it: the
teardown gate consults something stronger than `state == 'done'`, because it
consults the directory. A batch of rows marked `done` during a herdr outage
still has panes and processes with a cwd under the checkout path, and the live
observation sees them; when herdr is the thing that is down, the observation
cannot be made, and the refuse-on-unknown rule refuses. C1's conditional commit
does not need revisiting for this. What remains true and worth keeping in the
implementer's head: **`done` does not mean confirmed-gone** under C2, so
nothing in Wave 4 may treat it that way.

Round 4 sharpened where the weight in that answer actually sits. Refuse-on-unknown
handles a herdr that is *down*; a herdr that has *restarted* answers successfully
with a smaller world, so the rows read `failed`, `failed` is `FINISHED`, and
nothing is unknown. In that case the directory observation is not a corroborator
of the records — it is the only half still correct. Which is the same conclusion
from the other side: the reason `done` may not be treated as confirmed-gone is
that the live observation, not the record, is what has to carry the decision.

**2. Teardown purging rows versus mail routing and spawn-failure evidence.**
Group A's command must **retire** a workspace's rows, not purge them. Group
C's D1 guard resolves a `done` agent's identity by reading its row; deleting
rows out from under it reintroduces the same class of bug in a different
shape. The same argument applies to the spawn-failure question: if that lands
as a persisted `failed` husk, teardown must not be the thing that deletes it.
Retire, never delete, is the rule that keeps all three consistent.

**3. `workspace_id` as the authoritative join key.** Group A's last-agent-out
query assumed it (per the schema comment at `store.py:158-161`), and Group
D's fix makes the column *more* honest by leaving it NULL rather than
recording a guess — which is correct, and which also means more NULLs. Those
rows are not attributable to a workspace by id at all. Group A's design must
not fall back to deriving membership from the workspace *name* to compensate:
that is tier 4, the exact lookup whose own docstring records how a child of
`main` landed in the wrong workspace. A row with a NULL `workspace_id` is
"membership unknown" — which, for a destructive gate, means refuse rather than
assume absent.

The first adversarial round pushed this further, and section A now reflects it:
for the *destructive* gate the column is not consulted at all. NULL is
fail-safe, but the same code path that produces NULLs also produces confidently
*wrong* non-NULL ids — `_tab_for`'s bulk clear (`broker.py:1156-1158`) empties
the bucket, the next spawn re-derives an id from a lower tier and persists it,
and a row that lands on the wrong id is invisible to the refuse-on-NULL rule.
Fail-safe and fail-open come out of one mechanism. A gate scoped to the
checkout path sidesteps the whole column.

The second round pushed this one step further, and Group A now reflects it: the
same argument that disqualifies `workspace_id` from the destructive gate
disqualifies it from being the workspace record's *key*, because one live id
spans two checkouts and one live workspace has none. It survives as a join key
for grouping an existing workspace's agent rows in readouts, where being wrong
is visible and recoverable — not as the identity of the workspace itself.

The third round corrected where that argument landed. Round 2 concluded that
because the gate is scoped to the checkout path, the record should be keyed on it
too. That inference is the error: the gate's scope and the record's identity
answer different questions, and the path is a bad identity for the same reason
`workspace_id` is a bad one — it is not unique per workspace. Four bare
workspaces share one. The record is keyed on the **name**; the gate stays scoped
to the **path**; the path lives on the record as a nullable attribute, and its
being NULL is what marks a workspace as having nothing to destroy.

Two further overlaps are consistent rather than colliding, but should not be
built twice: Group D's `state_dropped` (which will now fire for a dying
agent, not only a corrupted write) and the liveness verdicts need to agree in
the log rather than defining two independent "something is wrong with this
agent" signals; and Group C's `pane_not_found`-as-terminal handling is the
same instinct as the liveness debounce — one bad signal from herdr should not
flip a permanent verdict without corroboration — so the two should at least
agree on naming.

---

## What the review rounds settled

### Round 1 — the harm lens

The first adversarial review was run against this document through a single
lens: what the design can destroy that a person cannot get back. It judged
waves 1–3 safe and wave 4 not safe as specified. Its two high-severity factual
claims were reproduced independently before any of this was written. This
section records what was accepted and what was refused, so later rounds spend
their attention on new ground rather than on ground already walked.

**Accepted, and now argued in the sections above:** the ignored-file blind spot
and its two-tier replacement for "refuse if dirty"; gating on the checkout path
plus a live observation instead of on `workspace_id`, with unknown refusing;
the checkout path as a recorded fact with no `or self.repo` fallback; stop and
confirm-stopped before deleting (round 3 moved the cheap gate ahead of the stop,
which does not disturb the rule that nothing is deleted before a confirmed stop);
the human's lack of a vote, answered by the
inventory and the live observation; re-entrancy with the state write committed
first; and a confirmation that echoes what the command line does not already
contain.

**Accepted in substance, refused in mechanism: the concurrency lock.** The race
between the check and the removal is real and the fix is not a lock. The
argument is in section A: `workspace_new` advertises non-exclusivity as a
deliberate posture (`broker.py:592-597`), so a lock introduced for one path
teaches a rule the rest of the codebase does not follow, and the retiring mark
this design already needs gives the same exclusion for free. The residual race
and why it is tolerable are stated there too.

**Refused: a backfill or reconciliation pass over rows already carrying a
poisoned `workspace_id`, as a prerequisite for wave 4.** The review is right
that Wave 1 stops new bad writes without repairing old ones, and right that "no
worse than today" stops being an acceptable standard the moment an `rm -rf`
reads the column. But the second clause is what the refusal turns on: once the
destructive gate is scoped to the checkout path plus a live observation, the
poisoned column is no longer what the destroy decision reads. A migration is
not a safety prerequisite for something that never consults the migrated data.

The residual, stated honestly rather than argued away: wave 3's retirement
bookkeeping *does* still read that column, so poisoned rows can still make
retirement bookkeeping wrong — a workspace marked retired while a row that
belongs to it sits under another id, or the reverse. Reconciliation stays what
it was in Group D: a broader, harder-to-test candidate that lost to a narrower
fix, to be revisited on evidence rather than pre-emptively.

**That concession was too small, and the second round is right about it.** Round
1 concluded the poisoned column left "only reversible bookkeeping" wrong. The
correction, made here rather than quietly rewritten above: `workspace_id` is not
a function of a checkout, so it was never a sound primary key for a workspace
record at all — one live id spans two directories and one live workspace has no
id. That is a modelling error in wave 3, not a bookkeeping error in wave 4, and
it is why the table stopped being keyed on `workspace_id`. (Round 2 replaced it
with the checkout path; round 3 replaced *that* with the workspace name — see the
round-3 entry below.) The refusal of a
*backfill over poisoned ids* still stands, for the reason given above: the
destructive gate does not read the column. What did not stand was the claim that
nothing else important did.

**What the review tested and cleared**, which changes the risk picture and is
worth carrying forward so nobody re-checks it:

- `git worktree remove` does not follow the symlinks `link_config` plants back
  into the main checkout — the symlink is unlinked and the target survives.
  That is what makes section A's ignored-content classification safe.
- A deleted branch's tip survives in the reflog, so `git branch -d`'s failure
  mode is cheaper than this document originally claimed. The irreversibility
  lives in the worktree, not the branch.
- `git branch -d` does refuse an unmerged branch (`error: the branch 'feat2' is
  not fully merged`), so the never-`-D` rule has a real backstop.
- `git worktree remove` refuses a main working tree (`fatal: '.' is a main
  working tree`), which bounds — but does not excuse — the `or self.repo`
  fallback trap.

**Not covered by that round**: herdr's own source, whether it has a
worktree-removal path of its own and what it does; `git worktree remove` under
submodules or a locked worktree (neither appears in this repo); and everything
outside the harm lens.

### Round 2 — the legacy-state lens

The second review asked a different question: does this design survive the state
already on this machine — 101 agent rows across 21 workspaces, five removed
worktrees, three bare workspaces, a mail backlog and a poisoned column already in
the data. It judged waves 1 and 2 clean and **wave 3 a blocker**. The blocker
was reproduced independently, against a copy of the real store, before any of
this revision was written.

**Accepted, and now argued in the sections above:**

- **The blocker itself.** Wave 3's table cannot be added without `_reconcile`
  dropping `agents`, `messages` and `events`. This produced Wave 2.5 — the store
  migration capability — as a prerequisite, and it is the reason wave 3 is no
  longer the cheap wave.
- **The key was wrong too**, independently of the migration: `workspace_id` is
  not a function of a checkout. Round 2's replacement was the checkout path,
  which is also what the destructive gate is scoped to. **Round 3 overturned that
  replacement** — the diagnosis stands, the new key does not; the table is keyed
  on the workspace name and the path is a nullable attribute. See the round-3
  entry below for why.
- **The inert-on-everything problem.** With no backfill the command refuses
  forever, for all 21 workspaces, which is the entire population. A one-time
  path backfill cures it. The reviewer's distinction is accepted as drawn: a
  name-keyed `_recorded_path` lookup is forbidden for *membership* and
  acceptable for a *one-time* path backfill — provided the backfilled path is
  re-validated at every use and never trusted as a live fact.
- **Bare workspaces**, which the design had no word for and four of which exist
  here (round 2 counted three; `main-4` has since been minted, which is the
  point). A bare workspace has no teardown at all, only a retired mark. Round 3
  found that the design stated this rule and then made it unimplementable — see
  below.
- **A refusal rolls the retiring mark back**; only a crash may leave it set. The
  reviewer flagged this as an unresolved ambiguity rather than observed
  behaviour, and it is now closed.
- **An already-gone worktree is the safest case, not an unknown one**, and it
  ships in wave 3 as its own small path.
- **`sb workspace list` must start from `git worktree list` and join**, or it
  structurally cannot report the orphan it exists to report. (Right about that
  failure; round 3 widened it to a union of three sources, because a git-first
  enumeration is blind to bare workspaces.)
- **Two factual errors about groups C and D**, corrected in place rather than
  softened: the D1 guard does not cover `flush_pending`, and A2 does not address
  the unread-mail-blocks-the-sweep consequence because the unread gate
  `continue`s before A2's branch is reachable.

**Refused: re-specifying wave 3 as columns on `agents`** — the reviewer's own
suggested fallback. The reasons are Group A's candidate B: retirement becomes an
AND over N rows that can drift, and a workspace with zero agent rows could never
be listed or retired. The reviewer is right that the tidy option was the
destructive one; the answer is to make adding a table non-destructive, not to
stop modelling a workspace as a thing.

**What that round tested and cleared**, worth carrying forward:

- **The path-scoped destructive gate is vindicated by real data.** `main`,
  `main-2` and `main-3` are three workspace names, two workspace ids and one
  NULL over a single directory. An id-scoped gate would have found `main`'s rows
  all finished and passed while two orchestrators were live in that directory.
  The path-scoped gate sees them.
- **"No `or self.repo` fallback" is load-bearing.** Five rows record the primary
  checkout as their `cwd`; a resolver that fell back would aim the cleanliness
  check and the branch delete at the human's main clone.
- **The ignored-content classifier works on real worktrees.** Five were checked;
  every one shows `!! .switchboard` and in each it is a symlink to switchboard's
  own furniture, exactly as assumed. Only one had anything else. So the
  confirmation prompt fires on roughly one worktree in five, not on every one —
  the "prompt people learn to dismiss" failure this document worried about does
  not materialise.
- **Waves 1 and 2 read nothing they assume to be clean**, and `absent_since` is
  a nullable column, which is the safe shape of schema change here.

### Round 3 — the does-it-deliver lens

The third review asked the plainest question available: if this were built
exactly as written, would the person get what they asked for. Not safety, not
migration, not schema mechanics — those were the first two rounds. Its verdict:
twelve of the sixteen gaps genuinely close, four are partial, every partial is in
Group A, and three of the four have one root cause — the bare workspace.

Two of its load-bearing claims were reproduced independently before any of this
revision was written: the herdr collapse experiment (a tab closed with its last
pane; a workspace closed with its last tab) and the four bare workspaces sharing
one path with a NULL branch.

**Accepted, and now argued in the sections above:**

- **The worst finding: round 2's key collides on bare workspaces.** Four of them
  share one checkout path, so one row would hold all four, retiring one would
  retire all four, and the retiring mark would lock three live orchestrators out
  of their own workspace. The fix separates identity from gate scope: the table is
  keyed on the workspace **name**, the checkout path becomes a nullable
  attribute, and NULL is how a bare workspace is represented. **This supersedes
  round 2's "keyed on the checkout path"**, which is corrected in place above
  rather than quietly rewritten. The gate is unchanged — still the path plus a
  live observation. Round 1 and round 2 were each right about their own half.
- **The destructive gate must not run at all for a bare workspace.** The design
  already ruled that nothing is destroyed for one, so a guard protecting a
  directory from deletion was refusing the only operation available, forever,
  because another orchestrator is live in a directory nobody is deleting — and
  there is always another orchestrator, usually the one running the command. The
  bare path is now specified separately: own agents finished, own panes closed,
  retired mark, stop. Recorded as **drift**: v1's own-rows test was correct for
  this case and round 1's hardening removed it without noticing.
- **The ordering bug in the general path.** As written, panes were closed and
  confirmed stopped *before* the gate was evaluated, so a refusal left the panes
  closed, the command reporting failure, and nothing retired. Now: cheap gate
  first, then stop panes, then re-confirm, then delete.
- **`sb workspace list` was structurally blind to bare workspaces.** It now
  enumerates from the union of `git worktree list`, the `workspaces` table, and
  the distinct workspace names in `agents`.
- **Tabs and worktree-backed spaces are not work, and now say why.** The
  experiment retires the `tab_id` column and the close call outright.
- **A2 moves into Wave 1 beside D1**, since the document's own Group C
  correction concludes they must land together. D1's one-time backlog sweep is
  placed with D1 in Wave 1; spawn-failure bookkeeping is placed in Wave 2 with
  the liveness work and the ownership question is answered rather than left open.
- **The disclosures.** What stays manual is now stated in the person's terms:
  worktree removal waits for Wave 4, unmerged branches refuse `-d` and stay
  forever, rows and events are retired and never purged (because D1 reads a
  `done` row). `sb workspace list` should report unmerged orphan branches so a
  human can decide by hand.
- **What `workspace_new` does with a *retired* name**, which the document never
  answered: it reopens it and clears the mark. Retirement is a record of
  end-of-life, not a tombstone that blocks the name.

**Refused: re-adding herdr `close_workspace` / `close_tab` wrappers**, which the
audit's finding #1 asked for and which this round noted the design had never
argued away. The experiment is the argument: herdr collapses a tab when its last
pane closes and a workspace when its last tab closes, so the wrappers would be
code that does nothing.

**Refused: moving worktree removal earlier in the sequence.** The disclosure is
accepted; the reordering is not. Round 2 proved wave 3's table cannot be added
without wave 2.5, and shipping destruction ahead of the store work that makes it
recordable is exactly the trade this document exists to argue against. What the
round is right about is that the person should be *told* — so they are, above,
including what they do get before wave 4 on the state actually here: the
already-gone prune clears five orphan branches and 55 rows, and the bare path
covers four of the eight spaces open right now. Waves 1–3 deliver most of the
visible accumulation. Disclosure is the answer, not reordering.

**What that round tested and cleared**, worth carrying forward:

- **herdr collapses its own containers.** A tab does not outlive its last pane; a
  worktree-backed space does not outlive its last tab. This is why no tab or
  space teardown code appears anywhere in this design.
- **Four bare workspaces, one path.** `main`, `main-2`, `main-3`, `main-4` all
  record `/Users/andrew/Code/switchboard` with a NULL branch.
- **The manual-close walkthrough.** A hand-closed pane, tab, window/space, whole
  terminal application, or raw `git worktree` removal each leave the design in a
  correct state — the pane and worktree cases being the two the person has
  actually hit.

**Still open after three rounds:** herdr's own source; test strategy; the Group
B/C/D picks on their own merits, which no lens has examined; and whether
`git worktree remove` leaves a herdr space behind when the directory goes without
its panes being closed first — the design closes panes first, so the tested path
holds, but the out-of-order case is untested.

**Where the sixteen gaps stand after this revision.** All four of round 3's
partials were in Group A and all four are addressed here: gap 3
(`sb workspace list` blind to bare) by the union enumeration; gap 4 (retired vs
fresh) by the name key plus the reopen rule; gap 11 (idle orchestrator
unsweepable) by the bare path that Group B's routing depends on; and gap 1
(nothing removes worktrees / branches / rows) *as far as it is being addressed at
all* — worktree removal still lands in Wave 4, and unmerged branches and store
rows are still never reclaimed, now disclosed rather than implied. Gap 1 is the
one that closes by decision rather than by code, and the decision is stated where
the person can see it.

### Round 4 — the concurrency lens

The fourth and final review asked what breaks when more than one thing happens at
once. Its verdict: waves 1 and 3's read-only diagnostics survive the lens, Wave
2's collector pick is **impossible as specified**, and Wave 4's exclusion
mechanism was a mutex with no owner that any losing invocation released. Three of
its eight findings are not races at all but flat contradictions with code this
document cites, which is the more embarrassing half.

Its load-bearing claims were reproduced independently before this revision was
written: the collector's read-only connection and the panel error it produces;
`_reset` with a fourth table, in **both** statement orders, giving an emptied
store one way and a permanently bricked one the other; `CREATE TABLE` autocommitting
so create and backfill are two transactions; and one bare `git worktree prune`
removing two prunable worktrees at once.

**All eight findings accepted, and now argued in the sections above:**

- **F1 — the retiring mark had no owner and every refusal released it.** Claiming
  the mark is now the conditional write itself (`UPDATE ... WHERE retiring IS
  NULL`, `rowcount` as arbiter), the mark records who holds it, rollback fires
  only for the owner and never restores an earlier snapshot, and
  `sb workspace close` refuses a workspace already marked retiring. **This is not
  a reversal of round 1's refusal of a lock primitive** — no lock file, no lock
  verb, no new exclusion rule for the codebase to learn; it is `claim_agent`'s
  existing pattern applied to the row being claimed.
- **F2 — the process the design handed the repair write to cannot write.**
  `collector.py:105-106` connects read-only, and `snapshot()`'s blanket
  `except Exception` would turn the failure into "could not read the tree" on
  every panel, every couple of seconds. The repair moves into the reap path;
  a writable collector is refused, because with Wave 2.5 shipped the one
  guaranteed stale-code process in the fleet could `CREATE TABLE` and run a
  backfill against a store newer code is using. This also resolves the
  `absent_since` writer/reader split the round found.
- **F3 — `_reset` cannot rebuild the store once a fourth table exists.** Folded
  into Wave 2.5 as a first-class part of it: `_reset` derives its drop set from
  `SCHEMA`. The brick result is quoted there because the difference between
  "silently emptied" and "every `sb` command dead until someone deletes the store
  by hand" is decided by where in `SCHEMA` the new table happens to be declared,
  which is not something an implementer should have to notice.
- **F4 — create-and-backfill is two transactions and a racing process stamps the
  hash.** Idempotent DDL, the loser's "already exists" / "duplicate column" caught
  rather than escaping `connect()`, and the backfill's completion recorded as its
  own fact instead of inferred from the schema hash — otherwise the one-time
  backfill silently never runs and the command is inert for every pre-existing
  workspace, the precise failure it was added to prevent.
- **F5 — `git worktree prune` is repo-global.** The already-gone path names its
  one worktree and uses `git worktree remove`; a bare `prune` would deregister
  worktrees another agent has gated and is about to close by name.
- **F6 — refuse-on-unknown covers a herdr that is down, not one that is up and
  has forgotten.** A restarted herdr answers confidently with a smaller world,
  every row reads `failed`, `failed` is `FINISHED`, and nothing was ever unknown.
  The live cwd observation therefore stops being a second opinion and becomes the
  half that decides, so it is now specified as such — `lsof`, not `/proc`, and
  refusal is mandatory when the enumeration cannot be made.
- **F7 — the gate refused on the caller.** The caller's own row and process tree
  are excluded, and containment is decided on resolved path components, since
  sibling worktree names nest as strings.
- **F8 — `flush_pending` runs before `_revive`.** D1's revival argument is
  corrected in place: the invocation the document claimed delivers the mail is the
  one that cannot. Delay, not loss.

**What that round confirmed the design already prevents**, which narrows what is
left and is recorded so nobody re-derives it:

- **Two concurrent `workspace_new` on one name** — already safe, and not because
  of anything here: `_attach_workspace`'s open-then-create either way leaves both
  callers holding the same id because *"the loser's failure is exactly 'it already
  exists'"* (`broker.py:706-711`), and the lead claim is an atomic insert on a
  primary key.
- **The spawn that slips through the retiring mark** — the residual-race argument
  in section A is right: the new row is in the directory, both halves of the gate
  see it, step 3 refuses. That window is genuinely non-destructive, *as long as
  the mark stays set*, which is what F1's owned claim is for.
- **check → stop → re-confirm → delete** — the reordering closes the window it
  claims to, for anything a record or a live process can show. F1 and F6 are about
  actors that window cannot see, not about the ordering being wrong.
- **A half-done `sb cleanup a b`** — `cleanup` computes `held` for every candidate
  before closing anything (`broker.py:1698-1707`), so a named agent is refused
  before the first pane goes.
- **A herdr hiccup reaping the table** — `_record_gone` stays gated on
  `consulted` (`status.py:419-421`), which nothing here touches.

**One correction to the review itself, and it argues for the document's own
rule.** The round reported the shared store as holding 0 agents, 0 messages and 0
events, and concluded that every population figure in this document — 101 rows,
11752 events, 21 workspaces, 55 rows under removed worktrees, five orphan
branches, eight unseen messages, four bare workspaces — no longer describes this
machine. That is wrong, and it was checked. The path it read,
`/Users/andrew/Code/switchboard/.switchboard/state.db`, is a decoy; the store
`repo_root()` actually resolves to is `.git/agentflow/state.db`, which holds 107
agents, 12359 events and 267 messages right now, all intact. Every figure this
document argues from still stands, and the already-gone prune still clears what it
says it clears.

The incident is worth its own line, because it is evidence for the rule rather
than against it: **a careful reviewer, reading source and running queries, still
read the wrong store because it guessed at a path instead of resolving one.** That
is the same failure this document forbids in `_recorded_path`'s `or self.repo`
fallback and in "an unresolvable path is a refusal" — and here it cost a review
one section. A person can make that mistake and lose an argument; a destructive
command makes it and aims `git worktree remove` at the wrong directory.

What survives from that observation, restated correctly: the Wave 3 backfill's
only input is `agents.cwd`, it runs exactly once, and its input is not durable —
which is a real dependency on nothing having wiped the store between the migration
shipping and the first `sb` that runs it. Per F3 and F4 that is not a free
assumption, which is exactly why both are folded into Wave 2.5 rather than left as
notes.

---

## What remains open or unproven

Four rounds of review have closed a lot. This section records what they have not,
because the document is now long enough that an unstated gap reads as a settled
one. Everything here is a known hole, not a discovered one.

- **The live cwd observation is load-bearing and untested on this platform.**
  F6 made it the half of the gate that decides when herdr is up and has
  forgotten. Nobody has run `lsof` for this purpose on this machine, checked what
  it costs, checked what it prints for a process whose cwd is a deleted
  directory, or written the parser that the refuse-on-failure rule depends on
  recognising as broken. The most safety-critical component in Wave 4 is the one
  with the least evidence behind it.
- **herdr's behaviour across a restart is inferred, not read.** F6's whole
  scenario rests on `broker.py:1135-1139`'s comment about ids not outliving a
  herdr run. Nobody has read herdr's source or watched what `agent list`
  returns immediately after a restart — whether it is an empty success, a partial
  one, or an error. The difference decides whether refuse-on-unknown catches this
  after all. `status.py:337-339`'s three-agents-failed-at-startup comment is the
  only evidence, and it is indirect.
- **Wave 2.5's migration is proven only in the negative.** The wipe was
  reproduced against a copy of the real store and the brick was reproduced in both
  statement orders. The *corrected* version — schema-derived drops, idempotent
  DDL, a separately recorded backfill completion — has never been built, never
  been run, and never been tested against anything. Wave 2.5 is currently a
  specification whose only demonstrated property is that its absence is fatal.
- **The backfill's only input is `agents.cwd`, and it is not durable.** It runs
  exactly once, its source is a column this document spends Wave 1 fixing the
  writers of, and anything that empties or resets the store between the migration
  shipping and the first `sb` that runs it leaves the backfill permanently
  unperformed — after which `sb workspace close` refuses every pre-existing
  workspace forever. F4's recorded-completion fact makes that detectable; nothing
  makes it recoverable except re-running the backfill by hand.
- **Group A's key has changed three times in three rounds, and no reviewer has
  seen the current one.** `workspace_id` (v1) → checkout path (round 2) → name
  with the path as a nullable attribute (round 3). Round 4's lens was concurrency
  and it did not re-examine the key. Each previous version looked settled to the
  round that produced it, and each was overturned by the next round on a case it
  had not considered — bare workspaces, in the most recent instance. The current
  key is the one this document argues hardest for and the one with the least
  adversarial scrutiny.

Carried forward from earlier rounds and still true: herdr's own source is unread;
there is no test strategy; the Group B/C/D picks have never been examined on their
own merits by any lens; and whether `git worktree remove` leaves a herdr space
behind when the directory goes *without* its panes being closed first is untested
— the design closes panes first, so the tested path holds, but the out-of-order
case does not.

---

## What to build first

The workspace-id poisoning fix. It is small, it is already corrupting data
every time a workspace id goes stale, it makes the store's join key
trustworthy, and Wave 3's entire design rests on that column meaning
something.
