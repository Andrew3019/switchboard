# Code scout: which paths let a parent's row go dead/archived while a child is still alive

Task: `notes/scout-dead-parent-code.md`. READ-ONLY, nothing changed. Read the two
`board-ghost-sessions` notes (`researcher-ghost-fix-shape.md`,
`qa-ghost-repro-isolated.md`) and `DESIGN-TRUTH.md` in full.

**Note on the brief**: the task pointed me at `notes/dead-parent-live-children-brief.md`
in this worktree as required reading. That file does not exist — checked directly at
`/Users/andrew/.herdr/worktrees/switchboard/dead-parent-rows/notes/`, and `git log --all
--diff-filter=A` finds no commit on any branch that ever added it. I proceeded without it,
working from the code, `DESIGN-TRUTH.md`, and the two ghost-session notes instead. Flagging
this to the parent rather than guessing at what it might have said.

## What "archived" actually means (this reframes the whole question)

`AgentStatus.archived` (`status.py:609-638`) is **not** about `state` at all:

```
return self.alive is False and self.age >= SPAWN_GRACE
```

It is purely "herdr does not have this pane, and it's old enough for that to mean
something." The docstring says this explicitly: *"It does not read `state`. Not
`finished`, not `gone`, not `blocked`."* So a row can be `archived` while `state` is still
`working` (nobody ever called `sb done`), and a row can have `state=done` or `state=failed`
while its pane is still open and it is *not* archived.

This matters because the task's phrasing ("dead/archived/failed/done") bundles two
independent things: **state** (what the agent or the store believes happened) and
**pane presence** (what makes a row draw as archived / collapsible). Only pane-loss
produces the board symptom Andrew is asking about. So the real question is: what makes a
parent's *pane* disappear from herdr while a child's pane is still there?

## Path 1 — `sb done`: no check, and correctly so

`Broker.done` (used by `cli.py:955`) only writes `state`. Per `cli.py:959-962`, when a
child is still `working` underneath, the parent is told explicitly: *"still working
underneath you... nothing will close your pane while they run."* `sb done` never touches
`pane_id` or calls `close_pane` — DESIGN-TRUTH.md:381 confirms this is deliberate: **"`sb
done` keeps the agent open. It is just a status update... which then decides whether to
close it."**

So `sb done` cannot by itself put a parent's row in the archived state at all — the pane
stays open regardless of children. **Not a path.** No check for live children is needed
here because nothing here can close a pane.

## Path 2 — `sb cleanup` / force-close: gated, and (on current `main`) unliftable

`Broker.cleanup` (`broker.py:3823-4202`) computes `live_descendants` for every named
candidate *before* closing anything (`broker.py:3905-3914`) and refuses outright — as a
`ValueError`, before any row is touched — if a named parent has any. The refusal text:
*"still working underneath: ...  Close them first: the subtree closes from the leaves
up."* A bare sweep (no names) silently skips such rows the same way, logging
`cleanup_held`.

`live_descendants` (`broker.py:4336-4374`) is stated as **the invariant switchboard
maintains by construction**: *"an agent whose pane is closed has no descendant whose pane
is still working... Everything that closes a pane on purpose asks here now, so the
invariant holds by construction rather than by nobody having tried yet."*

On the code as it stands at `HEAD` (`f881131`), the docstring for the gate says plainly:
*"nothing lifts this one — `force` does not, and there is no flag that does."* I verified
this in the actual loop body (`broker.py:4046-4052`): the `held` check runs unconditionally
for every candidate, `force` is never consulted in it, and there is no other code path in
`cleanup` that calls `close_pane` without first passing this gate.

**This is not the source of the bug, and the code says so of itself.** `sb cleanup`
(named, swept, or forced) cannot end a parent's pane while a child's pane is open, full
stop, on `main` right now.

### Dependency note: this gate is about to change shape, not weaken

There is unmerged work — `force-closes-descendants`, merged into `integrate-force-cleanup`
at `ecae6ad` (not an ancestor of my `HEAD`, so not yet on `main` as I read it) — that
changes `--force <name>` to *cascade*: it now closes the whole subtree leaves-first, then
the named row (`broker.py` diff, new `_leaves_up`). This does **not** create a new way to
leave a live child under a dead parent: the docstring for the new behavior is explicit that
closing happens in reverse-BFS order so `live_descendants` is empty by the time the parent
is reached — *"the invariant... was true at every single step."* It only removes the
manual "go close each child by hand first" step. I did not run this branch's tests myself;
I'm reading the diff and its own stated invariant. Since this is landing concurrently,
treat this section as provisional — worth re-checking once it merges, but it doesn't change
the conclusion below.

## Path 3 — crash / reap / `_record_gone` in `status.py`: the one real hole, and it's named twice in the code as unfixable from here

`live_descendants`'s own docstring names the gap explicitly (`broker.py:4364-4371`):

> **"What this cannot cover, and nothing can: a parent's pane that simply dies** — a
> crash, a closed tab, a herdr restart (route A1). There is no caller there to refuse, so
> the invariant is a property of what switchboard *does*, not of what the world does to
> it... The board draws it as an ordinary archived row with its live children under it,
> which is the honest picture and not a special case."

`status._record_gone` (`status.py:1069-1176`), the function that turns "herdr doesn't have
this pane any more" into `state=failed` after `GONE_CONFIRM_GRACE`, says the identical
thing from the read side (`status.py:1072-1074`):

> *"Nothing else closes a row that died abnormally — a crash, a pane closed from the
> outside, a herdr restart, a reboot — because the only writers of an end are the agent's
> own `sb done` and a `sb cleanup` that gates on the row being finished..."*

Neither function checks for live children, and by design neither *could*: `_record_gone`
is recording a fact that has already happened (the pane is gone) via a read path, not
deciding to end anything. There is no hook at "a pane just disappeared" to intercept —
switchboard only ever learns about it on the next `collect()` tick, well after the fact.

**This is the one genuine path**, and it is two things bundled together, both outside
`sb`'s control entirely:
- A parent's underlying process crashes (OOM, segfault, herdr/terminal restart) while a
  sibling tab/process in the same space survives.
- A human closes the parent's specific pane/tab directly (not via `sb cleanup` — e.g.
  closing one tab in a terminal multiplexer) while leaving a child's tab open.

I could not verify from the code how often either actually happens — that's process/OS
behavior, not something `status.py`/`broker.py` can tell me. Whether "closing one tab
directly" is even a normal thing Andrew does, versus something that only happens via crash,
I don't know; that's a question for the evidence-side scout or for Andrew.

## Path 4 — the pane dying under an agent (general case)

Same mechanism as Path 3, just stated as its own item since the task asked separately: any
process death of the parent's pane that isn't preceded by `sb done`/`sb cleanup` lands here.
`_record_gone` is the sole place anything is ever written for it, and it inherently cannot
distinguish "the parent legitimately died" from "the parent should have wound down its
children first" — it only sees an absence.

## A look-alike, not the same bug: the ghost/name-collision issue

`board-ghost-sessions`' two notes describe a **different** mechanism that produces a
superficially similar board oddity: a long-dead row (`state=failed`, `ended_at` days old)
reads back as `alive=True` because `status.collect`/`Herdr.list_agents()` match by bare
name only, globally across every fleet on the machine (`status.py:748,800`,
`herdr.py:890-892`), with no `workspace_id`/store scoping. That makes an *unrelated* fleet's
live agent of the same name resurrect a row that should be archived, and even clears its
gone-confirmation debounce (`qa-ghost-repro-isolated.md` §3, reproduced live).

That's the opposite direction from this task (a dead row wrongly drawn *alive*, not a dead
parent wrongly drawn *with a live child*), it needs cross-fleet name collision to trigger,
and it's already being fixed on that branch (a `session_id`-disagreement guard at
`status.py:800`, per `researcher-ghost-fix-shape.md` §1). It cannot compound with Path 3
above to hide it — Path 3 is single-store, no other fleet needed, and reproduces with zero
collision. I'm noting it only because the task pointed me at it and because a symptom-level
description ("old row visible on the board") could conflate the two if someone isn't
looking at the mechanism.

## What DESIGN-TRUTH says (or doesn't) about whether Path 3 is deliberate

`DESIGN-TRUTH.md` never states "a parent may end with live children" as a rule in those
words. What it does establish, which is consistent with Path 3 being the accepted/expected
gap rather than an oversight:

- `DESIGN-TRUTH.md:93-97`: cleanup/closing is explicitly a *human or lead* decision made
  after the fact, never automatic on state change — *"a lead cleans up its children...it
  does not close itself."* There's no rule anywhere that a parent's death should proactively
  reap/close its children, or vice versa.
- `DESIGN-TRUTH.md:343`: *"`sb board` stays as it is right now... an archived agent shows
  collapsed, which it already does."* — general "leave the board alone" statement, already
  the basis for Andrew's decision that display doesn't change.
- `live_descendants`'s and `_record_gone`'s own docstrings (both in-code, both cited above)
  are the closest thing to an authoritative statement that this specific gap — a pane dying
  outside `sb`'s knowledge — is a known, accepted, unavoidable limit of the design, not a
  bug in `cleanup` or `_record_gone`. Both were written by whoever last touched those
  functions, not by Andrew directly, so I'd treat them as strong evidence of intent rather
  than a DESIGN-TRUTH-grade confirmation.

## Ranking, and what would make it rare

1. **Path 3/4 (parent's pane dies outside `sb` — crash or a directly-closed tab) is the
   only real path**, and by a wide margin: it's the *only* mechanism in the code that can
   put a parent's pane in a "gone, child still alive" state at all. Paths 1 and 2 are both
   provably closed on current `main` (a check exists and is unconditional; `sb done` never
   touches panes).
2. Because it's an external event switchboard can't intercept, the smallest fix is not a
   guard on write — there's no write to guard, `_record_gone` only observes. The available
   levers, smallest to largest:
   - **Doc-only**: state the "route A1" gap as accepted behavior in DESIGN-TRUTH.md
     (currently it's only in two function docstrings, not in the trusted doc), so future
     readers don't treat every occurrence as a bug to chase. Size: one paragraph.
   - **A warning, not a guard**: when `_record_gone` (or a periodic sweep) writes `failed`
     for a row that turns out to have live descendants, log a distinguishing event (today's
     `gone` event doesn't say this) so it's queryable/countable how often this actually
     happens, without changing behavior. Size: a few lines in `_record_gone`, one new event
     kind.
   - **A nudge to the human, not automatic cleanup**: since `live_descendants`'s docstring
     already says the honest picture is "draw it as an ordinary archived row with its live
     children under it," and Andrew has decided display stays as-is, the next-smallest lever
     is making it easy to *act* on — e.g. `sb board` or `sb status` already draws it; the
     open question is whether an operator has an easy one-shot way to close the live
     children so the parent can be swept too. `--force`'s upcoming cascade (Path 2's
     dependency note) is exactly that lever, already in flight on another branch — I'd
     recommend not duplicating it.
3. I would **not** recommend trying to prevent Path 3 itself (detecting/reaping crashed
   panes proactively) — that's a much bigger change (active process monitoring instead of
   passive herdr polling) for a case the code already argues is inherently unrecoverable
   information (nothing calls switchboard when a pane dies).

## What I could not determine

- How often Path 3 actually fires in practice (crash vs. a human directly closing one tab)
  — that's usage data / evidence, not something the code says. Left to the evidence-side
  scout.
- Whether the missing `dead-parent-live-children-brief.md` would have narrowed or changed
  this scope — I don't know what it would have said.
- Whether `force-closes-descendants`/`integrate-force-cleanup` has already landed on `main`
  by the time this is read — I checked it was not an ancestor of `f881131` at the time I
  read it, but another agent is actively landing cleanup changes per the task background.
- I did not verify herdr/terminal-multiplexer semantics (whether closing one tab in a
  window can leave sibling tabs alive, vs. the whole window closing together) — that's
  outside this repo's code, and would materially affect how likely "human closes one pane
  directly" is as the dominant sub-case of Path 3.
