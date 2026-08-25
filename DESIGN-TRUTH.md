# DESIGN-TRUTH.md — what Andrew has actually confirmed

The confirmed design truth for switchboard. Critical user journeys, product decisions,
and the things that have been ruled out — held to a much higher bar than any other doc
in this repo, because everything else may be inferred and this may not.

## The rules of this file

**Everything in here is confirmed by Andrew himself. Nothing enters it any other way.**

- **Agents must not add, edit, reword, or "improve" entries.** Only Andrew adds entries —
  or an agent transcribing something Andrew said verbatim in that same conversation.
- **No inference.** Extrapolation, "this seems consistent with", something read out of
  the code or git history, and conclusions another agent reached are all disallowed. An
  entry is a thing Andrew said, not a thing that follows from what he said.
- **Read this file first when building here, and do not contradict it.** If a task looks
  like it requires contradicting an entry, stop and ask Andrew rather than proceeding.
- **Absence is not a decision.** If something is not in this file it is undecided, not
  free. An unconfirmed assumption gets flagged as one — never silently baked in.
- **If in doubt, leave it out.** Uncertain or half-remembered items do not go in. A thin
  file that is entirely true is the point; a fuller file that is partly guessed is worse
  than no file.
- **Every addition triggers a pass over the whole file.** Whoever writes an entry then
  re-reads all of it and leaves it consistent: contradictions resolved, overlapping
  entries merged, anything redundant removed. Where two statements disagree, the newest
  one wins and the older goes — and Andrew is told what was dropped.

**`design/PLANS-AND-STEPS.md` is the only other file held to this bar.** It carries these
same rules — only Andrew edits it, nothing arrives by inference, absence is not a decision —
for one subject: plans, steps and templates. That file is where the detail of that subject
lives, and this file stays the authority wherever the two meet, so the entries under Plans
below are what it is read against. Every other doc, README and code comment in the repo
stays untrusted until checked against the code. — confirmed 2026-08-18

Entry format: one short claim, plus the date it was confirmed.

---

## Critical user journeys (CUJs)

**Starting work.** On some terminal in a repo, I call `sb start`. It makes a new bare
space on main — bare meaning no worktree of its own; forking from `origin/main` is what
a workspace does. This is a dispatcher, and its home is the repo's main checkout: `sb
start` lays the space over the directory it was run in, and it is refused anywhere but the
main checkout, so in practice those are the same place. (The refusal is skipped, never
guessed, when the main checkout cannot be established at all.) — confirmed 2026-08-09,
the dispatcher's home confirmed 2026-08-14, corrected against the code 2026-08-14

**Anything that might need code changes.** It gets a workspace/worktree, and a lead with
it — which is also what such an agent was already being called, `<name>-lead` — unless the
whole of it plainly fits one agent, in which case the dispatcher may hand it to a single
worker in the same setup instead. Whether a part of the work underneath a lead is small
and clear enough for one agent end to end stays that lead's judgement to make. — confirmed
2026-08-09, the role named `lead` and the routing judgement below it moved to it
2026-08-14, the dispatcher's own lead-or-worker choice 2026-08-15

**Only `sb start` ever creates a TOP — that is the only path.** Being a top is stamped at
that moment, and `sb delegate` still branches on the stamp: a top's spawn gets a new space
and worktree, anyone else's gets a tab in the caller's space unless that spawn asks for
isolation. A bare agent's delegate is refused outright. That stamp, not the prompt, is what
decides where an agent's children land by default. What an agent may do *itself* is a
different question, and the answer to it is no longer the role alone: a role is a TEMPLATE
that seeds a live per-agent capability set, and that set is what every gate reads — see
Capabilities and isolation below. Dispatcher and lead are still two roles with two prompts,
not one role told its scope. — confirmed 2026-08-09, the second half confirmed 2026-08-14,
corrected against the merged capability and isolation code 2026-08-23

**The dispatcher ROLE is not gated, and saying "only `sb start` makes a dispatcher" would
be false.** `dispatcher` is a name `--role` takes like any other, the roles fragment every
agent gets advertises it, and a lead that types it spawns a child holding the dispatcher
prompt with no stamp and a parent above it — verified by running it. What stops that is
the lead prompt saying it is not one of its options, which is the same answer given
everywhere else here: enforcement of what a dispatcher is and does was rejected, so the
prompt is the mechanism. The two halves are separate and both true — top-ness is stamped
and ungettable any other way, and the role that goes with it is only asked for. —
confirmed 2026-08-14

**Only a human may create a top; `sb start` is refused for agents.** The refusal is on
that one command, so what an agent cannot do is create a top — asking for the dispatcher
role at `sb delegate` is a different act and is not refused, per the entry above. The
refusal is hardcoded and there is no capability string standing for it, so no grant can
reach it — see Explicitly rejected. — confirmed 2026-08-11, narrowed to what the refusal
actually covers 2026-08-14, the non-grantability said out loud 2026-08-23

**A fork that fails refuses the spawn and tells the parent.** It never falls back to
Andrew's own checkout. `sb start` run inside a worktree is refused too, naming the main
checkout to run it from. — confirmed 2026-08-09

**Where each spawn lands.** `sb start` = new bare space + dispatcher. A dispatcher spawns
a bare agent = new worktree/space and agent, and that agent does not spawn other agents
unless something above it granted `spawn`. A dispatcher spawns a lead = same thing. A lead
spawning anything = new tab in the same exact space, unless that spawn asks for isolation.
So by default a sub-lead a lead spawns is a tab in the lead's space, and its whole subtree
stays in that one space — but the dispatcher is no longer the only agent that can create
one. — confirmed 2026-08-09, the grant and isolation exceptions corrected against the
merged code 2026-08-23

**A worktree belongs to a space, not to an agent.** Everything in a lead's space shares
that lead's worktree, since a lead's spawns are tabs in it by default. A bare agent gets
its own worktree because it gets its own space, and so does a child spawned with
`--isolation own`: isolation mints a space, it never gives one agent a private tree inside
somebody else's. — confirmed 2026-08-09, read-only exception dropped 2026-08-12, isolation
added 2026-08-23

**Work heading for a change that will land gets a plan.** That is the whole trigger, and
small is not exempt: a one-line docs change bound for a PR gets a plan, only a short one.
Everything else runs without one — investigation, questions, scouting, review-only work,
anything a single agent answers and reports, and everything a dispatcher does. Investigation
produces a plan rather than living inside one: the plan is written once the outcome is known
and there is a path from what was found through to a merged PR, and investigation is a step
only where it is one piece of an already-shaped job. Every agent is told that one line at
spawn even though the plan-making instruction itself is not carried there — knowing plans
exist is not the same as knowing when to make one, and an agent left to infer the second will
not. What a plan is, and who writes it, are under Plans below. — confirmed 2026-08-18

**While the work runs.** The dispatcher is just idle. It should not be monitoring. It
persists until Andrew closes it. — confirmed 2026-08-09

**When work finishes.** It depends who is done and who is reporting it. A worker that is
done reports done, and its parent lead sees it. Once all of its children are done, that
lead either reports done or blocks, depending on whether the task is fully complete:
fully complete, report done; Andrew's input needed to finish it, block. Once that is done
it reports done, and the dispatcher blocks. A lead cleans up its children, pushes the PR
if relevant, and summarizes — it does not close itself, since cleaning a lead takes its
children and it still has to report; where its children were isolated, folding their
branches in with `sb merge` comes before it pushes anything. A dispatcher hands work to a
lead or to a single
worker, and where a worker is directly under it, that agent pushes and opens its own PR if
it was told to; the dispatcher blocks for it either way, since being told his work has
landed is the one report a dispatcher makes. Once a block is resolved the agent finishes
and reports done, and the parent cleans up — a lead on its own judgement, a dispatcher on
Andrew's. The plans plugin can override how work lands: where a plan is running, its merge
gate decides pushing, opening the PR and merging, on one approval — see the entry on
pushing and merging below. — confirmed 2026-08-09, the dispatcher's report restated
2026-08-14, the lead-or-worker spawn and the dispatcher's cleanup 2026-08-15, the plans
plugin's merge-gate override 2026-08-17

**A follow-up on a child's report is a handoff, not another relay.** A parent may report a
child's work once; it may not become the channel for the conversation about it. "When work
finishes" above still governs the first time a child's completion reaches me — the
dispatcher or lead writes a short line in the child's own words and blocks, or folds it
into a synthesis. What changes is anything after that: if I come back wanting more on a
piece of work already reported — explain it further, defend it, walk me through the
reasoning — that belongs to the child, not to whoever first told me about it. The parent
restores the child if needed, tells it what to explain and to `sb block` once it has, then
reports itself done and steps aside. I talk to the child directly from there; when I am
done with it, it reports done to its own parent as usual. — confirmed 2026-08-16

---

## Product decisions

### General

**If it needs to be known, it is known at spawn.** An agent needs to know a thing exists
and that it can call it — not specifically how to use it; it can then go in and poke it.
Agents cannot be trusted to take the initiative and work out what is available. What
needs to be known differs by agent and by role: not every plugin for every agent. Put
what is needed at spawn for now; we can clean up and prune later, but we want to get
things working first. The pruning now has a mechanism and has partly happened: a
reminder-shaped rule is delivered at the turn it applies to rather than bought at spawn by
every agent — see the guidance ledger below — while anything that must be true from turn
one still travels in the spawn prompt. — confirmed 2026-08-09, the ledger's carve-out
2026-08-23

**How herdr actually talks to Claude.** It types into the chat box and presses enter, so
a message from sb arrives looking exactly like one Andrew typed — they are the same
thing to Claude. If Andrew is halfway through typing when a message is sent, the
half-written text goes along with it, because sb pastes and hits enter. While Claude is
working, a message is queued by Claude's own system and delivered on the next turn.
Interrupt is pressing escape on the chat window, which interrupts the model, and then
the message goes in directly without waiting. — confirmed 2026-08-09

**Every sb message is prefixed so it is clearly an sb message**, and the prefix can
carry more — the sender agent's name and the like: `[sb: from <name>]`. The channel is
the same as Andrew typing; the prefix is what tells them apart. — confirmed 2026-08-09

**switchboard is personal, for now.** — confirmed 2026-08-09

**The role list is lightly audited and fine as it is** — as long as it is known that
there are roles, and what roles there are. Every agent is told at spawn what roles exist,
and that text is generated from the roles themselves, never hardcoded. — confirmed
2026-08-09

**Which model an agent gets is set in config, and does not really matter.** — confirmed
2026-08-09

**We should detect failures, and can start with just telling the parent that it has
failed.** How detection works, whether anything retries, and what becomes of
half-finished work are all deferred for now. One known hole to be aware of while it is
deferred: a dead agent's half-finished edits sit in the worktree its whole space shares —
or in its own, if it was spawned isolated — and nobody owns them. — confirmed 2026-08-09,
the isolated case named 2026-08-23

**How many spaces and agents are alive at once is fine as it is right now.** — confirmed
2026-08-09

**There should not be too many hard guidelines and rules.** The reconciler catching the
general case is worth more than a rule for each one — e.g. a reply that was asked for and
never came surfaces through the idle state, and pinging either agent or a parent is
enough for them to notice and chase it. — confirmed 2026-08-09

**A reconciler runs on a loop — maybe the same loop `sb board` runs on.** If an agent is
idle and neither blocked nor done, it pings that agent to say it should probably report
done or blocked, unless it is awaiting instructions. The ping goes to the agent itself
rather than to its parent, because the agent has more context on what its true status
is. That is how we avoid stale idle agents. — confirmed 2026-08-09

**Agents should avoid blocking unless it is really needed** — a genuine, big,
behaviour-changing design question; being blocked on running some command; being
explicitly told to block; an ambiguous instruction; going back and forth with the agent
itself; or finished work that needs Andrew's input or approval to complete. — confirmed
2026-08-09, ambiguous instruction confirmed 2026-08-12

### Human-facing output

*Who reads it decides whether these rules apply — not which command carried it, and not
where in a task it happens. Covered: the message written before `sb block`, a reply to
something Andrew typed, a write-up or progress update he asked for in the pane, any back
and forth with him, and an `sb done` summary whose parent is him — a top orchestrator's
always is. His words on the session write-up that prompted this: "that was just a summary
i asked for the entire session, not sb done, but same should apply". Not covered: what
only another agent reads — `sb tell`, a summary a parent agent reads, task text sent to a
child. — confirmed 2026-08-14*

**Skimming it is the test.** Andrew skims. He is not fixating word by word checking that
each claim is correct; he is trying to get the idea. So a message passes if skimming it
conveys the right idea, and fails if he has to reread it word by word to get there —
however accurate it is. This is the primary rule and the rest serve it. Prefer bullets,
lists, nested lists and diagrams — things that can be visually skimmed — and break into
sections where it helps. One idea per bullet: a second independent point is a second
bullet, not the same one stretched with a dash or a semicolon. And several short items that
belong side by side — PRs, files, names — get a line each, or a table where they share the
same fields, never one crowded line. — confirmed 2026-08-14, superseding the 2026-08-09
rule that listed what a message must say; one idea per bullet and no crowded lines
confirmed 2026-08-16

**Skimming happens down the message, not along the line, so the message needs places for
the eye to stop.** The complaint was two halves — "too much line wrapping, not enough
spacing" — and devices are only the first. What is wrong with a wall is the wall: runs
that never break, paragraphs that wrap into a slab, one idea running into the next with
no gap. Length that cannot be cut can still be broken up, and whitespace is what makes a
long message survivable rather than decoration. A property the message has to have, never
a layout — which supersedes "without overdoing the spacing". — confirmed 2026-08-14

**What goes in is decided by the reader's next move, not by a checklist.** If removing
something would not change what he does next, cut it. There is no ordered list of things
to include: a list of inclusions with nothing saying when to leave something out gets
optimised for completion instead of for the reader. — confirmed 2026-08-14

**Restating the task stays, at one sentence.** It reorients him, so it is
unconditional — not "if the context is unclear" — and it is stated once. Instructing it
in seven separate places across the protocol and role files is what turned one sentence
into a ritual paragraph. — confirmed 2026-08-14

**A message that ends in a block closes with "Where we are now".** Its own header, one line
under it, twenty words at most and the header not counted: what the overall task or topic
is, and what stage that topic is at — investigating, designing, waiting on a decision,
implementing, verifying. It is a different job from the restatement above, which says what
was asked and not where the work stands, and it sits at the end because that is the last
thing read before the turn ends. — confirmed 2026-08-16

**Compression is checked for meaning, not only for size.** A real failure: "a child forks
from the branch its parent is on" was shortened to "only when the parent has its own
worktree" — a different rule, and one that carved out the exact case causing the bug
being reported. Andrew would have approved it and the bug would have survived. The danger
is the skimmed idea being wrong, not a word being imprecise. — confirmed 2026-08-14

**Options must be comparable without re-reading, and the seam between what is being asked
and what is recommended must be visible without reading either.** Three options each
written in a different shape made him parse each one separately instead of comparing
them; options that differ in content but not in shape compare at a glance. This is a
property the message has to have, not a layout to copy. — confirmed 2026-08-14

**Telegraphic register is allowed on scaffolding, and it is the smaller lever.** Andrew
reads faster in clipped, "caveman" phrasing and wants it partially applied. Drop
articles, copulas, hedges and filler freely. Never drop a preposition, a comparative, or
any word doing disambiguating work — `a`/`the` where it distinguishes, `will`/`may`,
`and`/`or`. Real breakages: "raise gone_grace 287s" does not say to 287 or by 287; "waits
5 min declaring a target gone" lost its `before`; "child forks parent branch" has three
readings. Shape is a bigger lever than register — which is worth saying, because it stops
agents reaching for register first. — confirmed 2026-08-14

**Almost none of this may be turned into something to copy.** No template, no worked
example, no "here is what a good one looks like". The two exceptions are the length aim
below and the one section named above, "Where we are now"; there is no other fixed section
list and nothing else to reproduce. Anything an agent can pattern-match and reproduce
collapses every message into one shape and gets gamed on length instead of judgement. —
confirmed 2026-08-14, the two exceptions 2026-08-16

**A rough length aim, not a limit to hit.** Bullets run short — a plain fact in around ten
words, something genuinely more tangled up to about twenty — judged by feel, not counted or
labelled. This trades away the airtight version of the entry above, because the stated cost
of no aim at all (bullets Andrew cannot skim) is worse than the cost of a loose aim
occasionally drifting long. What it does not trade away: nothing here is a template, a
worked example, or a category to sort a bullet into before writing it. It is the same
instruction Andrew gives by hand — "depends how complex, sometimes ten words, sometimes
twenty" — asked of the agent instead of decided for it. — confirmed 2026-08-16

### Dispatchers and leads

**The hierarchy, and what a dispatcher sits above.** A dispatcher is above spaces and
worktrees and repos — its scope is the whole of its own tree — though in practice it is
usually specific to one repo. Below it is a lead in a worktree of its own — or a single
worker in that same worktree of its own, where the whole job fits one agent — then another
lead or worker below that, to no fixed depth: unlimited levels are allowed,
but stupid levels of it are not wanted and have not been observed. The dispatcher's scope
is a placement and a capability set, not only a prompt: it is above the worktrees and it
does not hold the right to write files git tracks — see the entry on its fixed set below.
— confirmed 2026-08-09, hierarchy restated 2026-08-14, what a dispatcher spawns being a
lead or a worker 2026-08-15, the capability half 2026-08-23

**One space per repo, and one space per dispatcher.** That is what the herdr UI should
show: a single space for each repo, a single space for each dispatcher, and everything
else nested under a repo. — confirmed 2026-08-14

**Where that model can bend, and it is deliberately left bending.** herdr picks one pane
already sitting in a repo's folder to serve as that repo's group parent. A dispatcher's
home is in that folder, so a dispatcher is a candidate like any other pane. In practice
Andrew's own manually opened pane on the repo has always been picked first, so dispatchers
have stayed separate — the other outcome has been seen once, in a throwaway clone, and
never in the live fleet. If a dispatcher were picked, that repo's space would *be* the
dispatcher, and every worktree agent for the repo, including other dispatchers' children,
would nest inside it. Nothing breaks functionally; the view is muddled. The only real fix
is a small flag in herdr, which Andrew has chosen not to take; the alternative of moving
dispatchers outside the repo would mean separating a dispatcher's home from the repo it
dispatches into, which `sb start` does not support today. So this is a known limitation,
not pending work. — confirmed 2026-08-14

**A dispatcher relays; it does not interpret.** Its job is basically to relay Andrew's
words to the new agent that will own them, and to orchestrate the creation of the
worktrees, workspaces and agents that takes — without assuming too much, and without adding
instructions of its own about
how the work should be approached. Whether a piece of work is to be carried end to end, or
investigated with the questions brought back first, is his to say and not the dispatcher's
to guess. If that is unclear, it does not start: it asks him to clarify intent before
dispatching. Choosing a lead or a worker is a judgement about the shape of the tree and is
no licence to interpret: it picks who runs the work, never what the work is. (This is
relaying the *task* downward, untouched — a different thing from relaying a child's
*answer* back upward, which "A follow-up on a child's report is a handoff" above now
covers, and which is not always the right move.) — confirmed
2026-08-14, widened from leads to whichever agent it hands the work to 2026-08-15; it still
supersedes the 2026-08-09 rule that the top spawns scout or research agents to improve its
own decisions, which is a lead's judgement now, while the other rule it superseded —
routing a small, clear task straight to a single agent — is back on the terms of the `sb
delegate` entry

**A delegation brief goes to `.switchboard/briefs/<name>/brief.md`.** A task argument
cannot carry a newline, so a dispatcher or lead relaying an ask longer than one line writes
it to a file and spawns with a one-line task naming the job and that path. That directory
is gitignored and symlinked into every worktree, so the brief stays off `main` and the one
path reads the same from the child's tree as from the writer's. It used to be `notes/`,
which is tracked — about 48 briefs were committed to `main` in two weeks as a side effect.
Convention in the prompts, with no `sb delegate` flag behind it. — confirmed 2026-08-16

**Work that belongs in another repo is a question, not a spawn.** A dispatcher that
notices it asks Andrew and starts nothing — it never puts an agent in that repo, because
nothing can (see Open: real cross-repo dispatch does not exist). The handover, when there
is one, runs through him and not through a spawn: he sets that repo up and starts its own
dispatcher there, and that tree is not below this one. This is a separate thing from the
grouping limitation above, and the two should not be run together: here the work was in a
repo switchboard had never been set up in, and an agent with no way to root a child there
forked a worktree of *this* repo instead and appeared in this repo's space. Nothing was
adopted by anything; an agent was simply in the wrong repo. — confirmed 2026-08-14, the
handover reworded 2026-08-14 so it cannot be read as a spawn the dispatcher performs

**A lead's children share its worktree, so the lead assigns disjoint files and
serialises anything that overlaps.** That is the default and stays the common case. Where
it is not wanted, the lead spawns the child with `--isolation own` and folds its branch
back with `sb merge` once it finishes — see Capabilities and isolation below. — confirmed
2026-08-09, the isolation escape hatch built and named 2026-08-23

**Not every level gets a worktree of its own — the shared model is the one Andrew
means, and it is what the code already does.** A dispatcher's children each get a
worktree and a space of their own; below that, a lead's children are tabs sharing the
lead's worktree and branch, and so is everything under them. He had earlier described
every level as isolated, and has said plainly that he meant the code's way. Proved live
and not merely read: a top-level agent spawned a lead, that lead spawned two workers,
and the lead and both workers ended up with the same workspace, branch and directory —
one worktree for the whole subtree, differing only by pane. It was ever in doubt because
everything Andrew had watched was spawned by a top, which forks a worktree per child
under either model, so observation alone could not tell the two apart. What stays
genuinely unknown: no collision between siblings editing the same file has ever been
observed in this repo — that is the record's silence, not a failed attempt to provoke one.
What has changed is that the fallback named then is now built. A lead may choose an
isolated worktree for a particular spawn, and that is exactly the shape it was described
in: a per-spawn escape hatch asked for one child at a time, not an isolated-by-default
rebuild. Shared is still the default for everyone below the top. — confirmed 2026-08-14,
the escape hatch built 2026-08-23

**A lead's job is to orchestrate other agents and stuff.** Review is coordinated by it.
— confirmed 2026-08-09

**A lead can spawn discovery or scout or research agents or whatever, to improve its
decisions and actions.** — confirmed 2026-08-09

**The lead prompt is mostly good already.** It is the old orchestrator prompt, carried
through the split. — confirmed 2026-08-09

**Dispatcher and lead must be clearly differentiated, and some mechanism other than the
prompt must make that true as well.** The mechanism is the `is_top` stamp, which decides
where each one's children land, and — since the capability migration — the two sets the
templates seed, which genuinely differ: the top holds no `write-tracked`, a lead holds it
and `fork`. Past that, the prompt is the mechanism and is judged enough — see Explicitly
rejected. — confirmed 2026-08-09, prompt-is-enough confirmed 2026-08-14, the capability
half 2026-08-23

**`orchestrator` is retired as a role name.** It survives only as a config alias for
`lead`, resolving all the way through — so a stale `--role orchestrator` gets a lead
rather than falling through to the fallback role, whose template holds no `spawn` and so
cannot delegate at all. — confirmed 2026-08-14, the wording read off the capability
templates 2026-08-23

### Capabilities and isolation

*What an agent may DO, and where its children land. Both used to be read off the role name
and the `is_top` stamp; both are now live per-agent state. The stamp survives and still
decides placement by default — the entries above under CUJs are what these are read
against. — confirmed 2026-08-23*

**Capabilities are a live per-agent set, and a role is only the template it is seeded
from.** The retired shape was one bool per role (`delegate = true/false`), which answered
exactly one question and would have needed a second field for every rule after it. Now
every gated action is a capability STRING checked through one function, so adding a rule
means adding a string rather than another refusal function beside the gate. Four strings
ship — `spawn`, `fork`, `write-tracked` and `dispatch` — and the first three are the ones
with a gate site today; `dispatch` is seeded and grantable vocabulary with nothing checking
it yet. The set is open-ended and a repo may add to it. A
spawn NARROWS and never widens: a child is seeded with its role template intersected with
what its spawner may pass down, so nobody reaches past their own ceiling by spawning
something more capable and driving it by `sb tell`. The one exception is the top, which
seeds its children from the full template even for capabilities it does not itself hold,
because commissioning fully-capable leads while holding none of their rights is precisely
its job. What the role name still decides on its own is the prompt, the model tier, and how
far the agent may tune its own reminders. — confirmed 2026-08-23, against the merged code

**The top dispatcher's capability set is fixed, and it holds no `write-tracked`.** It is
the one bundle that is not data: not editable by a repo's role files, not derived from any
mutable row, and never the target of a grant. It holds `spawn`, `dispatch` and `fork` —
`fork` because forking is what a top is for, having no space of its own to lend — and it
does not hold the right to write files git tracks, because it works over a person's own
main checkout. This is the placement half of the dispatcher, not the role half: a non-top
agent given the `dispatcher` role is an ordinary agent with that prompt and that template's
own bundle, which is a different thing and is the entry above on the role not being gated.
— confirmed 2026-08-23, against the merged code

**`sb grant` is how an agent gets a capability it was not seeded with.** One shot and
lifetime-scoped: there is no revoke and no expiry, `cleanup` ends the grant and `restore`
starts a fresh lifetime from the stored seed. The refusals are the design — an unknown
capability string is refused rather than written down, a grant never targets the granter, a
grant reaches only inside the granter's own subtree, the top is never a target, and a
granter may only hand on what it holds or may itself pass down. `--delegable` splits those
two: the recipient's children are seeded with the capability while the recipient still may
not use it, which is what lets a read-only researcher equip the writers below it without
becoming a writer. The subtree rule is an admission check at the moment of granting and not
an invariant anything maintains: a later promote may lift a granted agent under a lead that
never authorized it, and what carries that residual is `sb who-holds` and the divergence
marker on the agent's row rather than a re-check — `sb status` draws that marker in the
ROLE column, on the agent and on everything above it. — confirmed 2026-08-23, against the
merged code

**Isolation is asked for per spawn, and `sb merge` is the way back off it.** `sb delegate
--isolation own|shared` decides whether a child gets a worktree and branch of its own.
`shared` is the default, and `own` needs `fork`, which the lead template carries — so a
lead arrives able to isolate a child that needs it, and its ordinary spawns are unchanged.
Three rules decide placement, in order: a workspace named outright wins, otherwise a caller
with no space to lend forks anyway, otherwise what the spawn asked for. `sb merge <child>`
folds one finished child's branch into the caller's own branch, in the caller's own
checkout, called as each child finishes rather than saved up. It is assembly and not
landing: it never pushes, never touches `main` and opens no pull request, so it clears no
gate and bypasses none, and one PR at the end survives for free because every child folds
into the same branch. It refuses on a dirty checkout rather than stashing, since a lead's
shared children are working in that same checkout and their uncommitted work is not the
caller's to move. A real conflict spawns one integrator for that one merge, and the caller
carries on with the next child against the result. — confirmed 2026-08-23, against the
merged code

**An agent's parent is mutable, and `sb done --preserve-children` is the one thing that
moves it.** `parent` is read through a thin resolver at the point of use, so `done` mails
and `cleanup` scopes on whoever an agent reports to now rather than on a copy of the state
at spawn. Promote re-homes an agent's live children onto its own parent in the same
transaction as its own report: they rise one level and the promoter drops out of the chain.
The case it is for is an agent that finds the job is bigger than it was given — a
researcher spawns the lead the work actually needs, hands its findings over as the brief,
and finishes with `--preserve-children`. It takes no capability and there is no topology
capability string at all, because it re-homes your own children onto your own parent and
those children were already that parent's descendants: nobody gains authority over anybody
new, and the promoter gives up its own reporting line as part of finishing. The one refusal
is structural rather than a permission — the top may not promote, since that would leave
its children parentless and unhook the fleet from the row everything else resolves against.
It is a different thing from the reporting handoff under CUJs, which moves a conversation
and leaves the tree where it is. — confirmed 2026-08-23, against the merged code

**Guidance is a ledger of situational rules, delivered at the turn they apply to.** A rule
is data — `defaults/guidance.toml`, joined with a repo's own and re-read every turn, so an
edit reaches agents already running — keyed by role, by the `sb` verb just run, by the
agent's live capability set, and by deterministic facts the store can be asked about. There
is no free-text condition and nothing that asks a model whether a situation applies. It
rides the `UserPromptSubmit` hook that already exists, so it reaches an agent that never
talks to sb at all, and when nothing matches nothing is printed. It is SUBTRACTIVE: a rule
that moves here is deleted from the spawn prompt, because a rule in both places is paid for
twice and drifts. Reminder-shaped rules move; identity and orientation prose does not,
since it has no later turn to wait for and must be true from turn one. A ledger that only
grows is the failure mode, so rows are pruned against how often they have actually changed
what an agent did. — confirmed 2026-08-23, against the merged code

**`sb configure` tunes how loudly an agent is reminded, and never what it may do.** It is
self-directed and has no target: one agent cannot configure another by any path. Its bound
is a ceiling its ROLE template sets — the role and not the parent, deliberately, because
`parent` is mutable and a promote above an agent must not silently change what that agent
may do to its own reminders. Nobody above can lift it either; the way past it is a person
editing the role template, which is one decision about every agent of that role. The
setting vocabulary is closed, which is how "no self-widening by any path" is enforced: a
capability string is simply not a setting name, so `sb configure spawn true` is refused in
the same breath as a typo. Safety-category rules are delivered whatever anybody has
configured. — confirmed 2026-08-23, against the merged code

**`write-tracked` is one instance of a repo-configurable side-effect class, not a rule of
its own.** `[capabilities.side_effects]` names the capability strings that stand for an
action producing a side effect sb mediates, and says which sb-mediated boundary each is
checked at: `sb merge` refuses a child that does not hold it, `sb done` only flags. A repo
whose dangerous act is a deploy rather than a tracked edit mints its own string there and
gets the same gate, the same subtree-scoped grants and the same fail-closed path with no
structural change anywhere. It is NOT a security control and must not be built as one:
there is no filesystem chokepoint anywhere in sb, so every instance of the class is a
post-hoc check on the sanctioned path, and an agent with its own `git` can push a branch by
hand. — confirmed 2026-08-23, against the merged code

### Plans

*When a plan exists at all is a CUJ, above. What one is, and who may touch it, is here. How
a plan lands its work is under Commands, in the entries on pushing, merging and cleanup. The
detail behind all of it lives in `design/PLANS-AND-STEPS.md`.*

**Plans, steps and templates — three words, and no others were available.** A **step** is
the unit: what an agent owns, what gets ticked, what carries a try count and notes. A **plan**
is a group of steps with an identity of its own, a worktree, a changelog and a kept record —
a DAG, semi-structured, changeable at any time, and interpreted by an agent rather than
executed by anything; there is no workflow engine around it. A **template** is a preconfigured
plan in the ordinary sense of the word: a starting point that is copied and then edited as the
job needs, with nothing linking the copy back to it. `task` was taken — it is already the
agent's own task — and so was `preset`, which is already prompt text injected at spawn. —
confirmed 2026-08-18

**Only the worktree's owner writes to a plan's shape.** That is the lead of the worktree, or
the sole worker standing in as one where there is no lead — standing in for this and nothing
else, since planning the work you were given is how the task is carried rather than work you
took on. Shape is the steps, their order, their owners, the gates and the deps. A child that
wants any of it changed asks its parent and does not edit the file itself. One writer is what
makes a file that is edited by hand safe, and it is the only thing that does. — confirmed
2026-08-18

**Ticking a step is not a shape edit.** Any agent ticks the step it did, and is trusted to
tick that one and no other. An agent that reports back without ticking leaves the tick to the
lead, which does it on the report — or, where the step is not actually done, does something
else about it instead. — confirmed 2026-08-18

**A dispatcher is never involved in a plan.** It does not plan one, own one, tick one or read
one. It relays work and orchestrates the creation of agents and worktrees, which is the same
scope as "A dispatcher relays; it does not interpret" above: a plan belongs to a worktree, and
worktrees are below it. — confirmed 2026-08-18

**Every step carries a short display name for the board, and so does the plan.** A step's
name is a sentence and a board cell is a few columns, so a step named "list every claim the
document makes about the code" is authored with a display like "list claims" — as short as it
can be made, abbreviating and cutting words the title already implies — short but readable,
not vowel-stripped. It is required on every step, not optional: a cell with no display drew
the name clipped mid-clause and the informative half was the half cut, so the board was
unreadable until it was authored. It pairs with the
name exactly — a named step's display lives in its definition and an edit to it reaches every
plan naming that step; an on-the-fly step's lives on the step. A plan carries its own display
too, longer than a step's since it owns the whole header line, and a display *version* of the
title rather than an abbreviation of it; the board draws it instead of the title, and a plan
authored without one falls back to its title. There is no per-cell clip any more — display
names are short by construction, and the only clipping left is the board's own from the right
when the pane is narrow. It is the same split the board already makes — the board is a
picture, the plan's own listing is the full text. — confirmed 2026-08-19

**A step names what it comes after, and every step but the plan's first must.** The board is
a DAG drawn from the deps, so a plan recording no order between its steps renders as a loose
vertical stack with no arrows — which is what every early plan did. The first step is the
exempt root, and a second start is exempt too where the step SAYS it is one — `root: true`,
written into the file, and written for a step the library places ahead of everything already
in the plan. Nothing can tell a deliberate second root from a forgotten edge by looking at
it, so the plan says which it is: a marked start is complete and draws like anything else, an
unmarked one still reports, and a step carrying the mark AND a dep is reported too rather
than one half of it being quietly picked. The mark exists because the only other way off the
warning was an edge nobody meant, and a plan that misstates its own order to satisfy a
rendering rule is worse than the warning. Display and deps are required in more than one
place, because a plan is edited by hand as often as by command: the shape verbs (`create`,
`name-step`, `template use`) refuse to mint a step with no display; every other write warns
and still writes, naming the offending steps — a `tick` that would not land because of a
rendering rule is worse than the rendering; and the board draws the defect red.
Completeness is never a whole-file refusal — that is `_check`'s job and it stays
structure-only. — confirmed 2026-08-19, the deliberate second root confirmed 2026-08-20,
restated 2026-08-21 for the going of `dep` and `add-step`

### Scope

**Siblings are not invisible to each other; any other dispatcher's entire tree is
invisible.** Across that boundary agents cannot `sb tell` or anything else. Separating
two subtrees inside one dispatcher's tree is not something we have to do. —
confirmed 2026-08-09

**Only agents have the scope constraints.** The board is shared, and from it Andrew
crosses freely into any tree. — confirmed 2026-08-09

**Agents the dispatcher spawns directly are owned by it — no other agent owns
them — and they answer to it.** They can talk to each other, but they should not: keeping
it simple is the point. That set can grow without it spawning anything: a lead finishing
with `--preserve-children` hands its live children up to whoever it reported to. Nothing
takes one away, and nobody outside its tree ever gains one. — confirmed 2026-08-09, the
promote case added 2026-08-23

### Interface

**Every single view I see that is made by sb — `sb start`, dispatchers, leads, agents,
etc. — needs to be a split pane with `sb board`.** — confirmed 2026-08-09

**`sb board` stays as it is right now.** It shows the full tree with its nest structure;
an archived agent shows collapsed, which it already does. Clicking an agent's name in
the tree brings that agent into focus automatically — it is like a fake UI to move
around quickly. That is all it needs for now; the rest of what it has works fine and
auditing it comes later. — confirmed 2026-08-09

**The click is not working sometimes.** Andrew first suspected the side panel; the
evidenced cause is that board rows are measured in characters rather than terminal
columns, so one wide character (an emoji, CJK) wraps a row and every row below it is off
by one — the narrow default pane is why it looked like the panel. — confirmed 2026-08-09

**A plugin may draw its own section on the board, and the plans plugin draws PLANS.**
Rendering plans under the tree is the one thing the plugin cannot do from outside, so the
board grows an extension point — a seam that reads a `board.py` beside the plugin, hands it
the rows of each worktree group, and draws what it returns under a heading of the plugin's
own naming. The plans plugin uses it to draw each plan as a header and its steps as a
left-to-right flowchart, coloured by progress rather than columned, with the short display
name of each step in the cell, the plan's own display as the header, and any plan or step
still missing a display or a dep it has not marked deliberate drawn in red. A board that
ships no such plugin, or a plugin that ships no `board.py`, costs nothing: the seam imports
neither unless both are there. — confirmed 2026-08-17, display-and-defect clause confirmed 2026-08-19

**`sb start` focuses the pane. Nothing else ever focuses on spawn.** Clicking a name on
the board is navigation, not a spawn, and does bring that agent into focus. — confirmed
2026-08-09

**When something needs me, the board shows it, and `sb block`.** (To be explained
later.) — confirmed 2026-08-09

### Commands

**`sb delegate` works out where a spawn lands, and `--isolation` is the one flag that
overrides it.** A dispatcher's spawn gets a space and a worktree of its own whatever role
it is given — the code branches on the `is_top` stamp, not on the role. Below the top the
default is still a tab in the caller's own space with no flag passed at all, and
`--isolation own` is the one way a caller asks for something else. What a dispatcher hands
out is a lead or a single worker, and it chooses: a worker when one agent can carry the
whole thing to done, a lead otherwise and whenever it is unsure. A worker it hands out
gets exactly the same setup and environment a lead would have got — its own space, its own
worktree, all of it — and the only difference is the role it runs as, which now also means
the capability set that role's template seeds. — confirmed
2026-08-09, lead-or-worker 2026-08-15, superseding the 2026-08-14 rule that a dispatcher
hands out a lead every time; `--isolation` and the capability half 2026-08-23

**The lead handles cleanup itself, and it should do this aggressively** — probably
literally every agent that is done. Cleaning up a lead always cleans its children. What
stays open below a dispatcher is still decided by the person watching the board, and never
by the dispatcher sweeping on its own judgement — what changes is that the dispatcher
carries that decision out. It closes children when Andrew tells it to, and when a child
reports its task fully done it may ask him to approve closing it. The plans plugin can
override that ask: where a plan is running, its merge gate is the one approval and cleanup
follows it, so a finished child is not a separate ask. The automatic worktree sweep is not
an exception to that and not a judgement anybody is making: it closes whole workspaces
rather than agents, it only reaches one where every agent has already finished, and an
agent still working or blocked holds its worktree open. The agent rows under a workspace
it takes go with the workspace, which is that same whole-workspace act and not a decision
about any agent. — confirmed 2026-08-09, the dispatcher half 2026-08-15, superseding the
2026-08-14 wording that left closing below a dispatcher entirely off it; the sweep's place
in it 2026-08-16 and its agent rows 2026-08-25; the plans plugin's merge-gate override of
the separate close-approval 2026-08-17

**`sb done` keeps the agent open.** It is just a status update and a message for the
parent, which then decides whether to close it. It always uses the **when idle**
delivery mode — which is also how an idle dispatcher learns a child finished: the held
doorbell fires the moment it is idle, so it is woken rather than monitoring. — confirmed
2026-08-09

**Cleanup closes the agents, closes the tab, and closes the entire space and deletes the
worktree if everything else is closed too.** Pushing first is a convention and not a gate
here: `sb cleanup` and `sb workspace close`, both typed by hand, still delete a worktree
holding unpushed commits. The automatic sweep below is the one path where landing is a
rule rather than a habit. — confirmed 2026-08-09, the convention separated from the
sweep's rule 2026-08-16

**A board sweeps the fleet's worktrees twice an hour, at :00 and :30 on the system
clock.** A worktree goes only when nothing is left to lose: no live agent, nothing git can
see uncommitted, its commits merged or pushed — or the only unpushed ones docs-only, which
`DESIGN-TRUTH.md` is never part of — and quiet for over a day on both clocks, last agent
activity and last commit. Landed means merged **or** pushed, because origin is the bar,
and it is read off this machine's repository with nothing asked over the network, so a
branch pushed and never fetched back still counts. Docs-only is decided by path — a `.md`
anywhere, or anything under `notes/`, `design/`, `learnings/`, `research/` — never by
reading what a change really is. Every unknown holds: a git that will not answer is not
evidence that there is nothing to lose. Exactly one board sweeps per tick, and no board
running means no sweep, which is the accepted cost of having no daemon. Every worktree
deletion is `sb workspace close`'s, gates and all; the repository's own checkout and the
space the sweep is standing in are never candidates; and the gate answering "is anything
live in there" counts any process of Andrew's own sitting in the directory, agent or not,
which is deliberately left as it is. Ignored content does not hold a worktree back from a
sweep the way it holds back a close typed by hand — every worktree here carries
`__pycache__` and the like, so refusing on those would not be a conservative sweep but no
sweep at all — while work git can see holds one open unconditionally. The sweep takes rows
as well as directories: a workspace row whose checkout is already gone is swept too, and a
retired row is deleted outright along with the agent rows filed under it — what that costs
is under `sb restore` below. Everything held back is named with the reason, every half
hour, and that list is the half of this a person reads. `sb sweep` is the same run typed
by hand, and it is the human's: an agent asking for it is refused. — confirmed 2026-08-16,
the rows 2026-08-25

**`sb status` is for agents; `sb board` is Andrew's view of the tree.** A soft
convention about what each is for, not an enforced gate. — confirmed 2026-08-09, soft
rather than gated confirmed 2026-08-12

**There is `tell` only. No agent ever waits on another agent.** `tell --needs-reply`
inserts a static prompt saying you must reply to that agent at some point, since it is
waiting for a reply. — confirmed 2026-08-09

**`sb tell` has three delivery modes.** — confirmed 2026-08-09

- **next turn** (the default). The doorbell is sent instantly; the agent's own system
  queues it and delivers it at its next turn boundary — the same as sending a message to
  Claude while it is working. It waits for nothing and cancels nothing.
- **when idle.** sb holds the doorbell and sends it once the agent marks itself idle —
  no more turns, and if we waited an hour there would be no new activity. That is a safe
  idle signal, and herdr's status is the more accurate place to derive it from. A
  blocked agent is not idle: when-idle mail is held until its block is answered, so a
  reply is never buried under it.
- **interrupt.** Injected mid-turn, cancelling what the agent was doing. Used when we
  need to change course, or the agent is doing something wrong.

**A doorbell is checked afterwards, and rung again if nothing shows it landed.** herdr
pastes the text and presses Enter, and under load the paste lands while the Enter is
dropped — every layer above reports success and the message is stranded with nobody aware.
So a doorbell is no longer sent once and left: about 45 seconds later, housekeeping looks
for a submission in the recipient's own transcript, and re-sends the doorbell when it
cannot find one — a re-send and never a blind Enter, which could submit a half-typed line
of Andrew's or answer a modal. It runs off everybody's turn, so the sender still waits for
nothing, and after a couple of repairs it gives up and says so. — confirmed 2026-08-16,
superseding the 2026-08-09 reading that a doorbell was sent once and never checked

**`sb tell` is for agents only, both ways round.** Andrew does not use it — he types
directly into the session — and it cannot address a human. Anything needing a human is
`sb block`. — confirmed 2026-08-09

**An agent blocking writes the whole message in the chat first, then calls `sb block`.**
That chat message is the one Andrew reads, so it is written to the human-facing output
rules. He will not see the `why`; it is just bookkeeping. This must be made clear. —
confirmed 2026-08-09, "at full length" dropped for the human-facing output rules
2026-08-14

**After Andrew answers a block, the agent just continues.** It clears its own block on
receiving his reply, so answering by typing into the pane is what works. — confirmed
2026-08-09

**A parent is not told that its child blocked.** It is not needed: that is more layers
and more out-of-sync problems, and the board already shows it. — confirmed 2026-08-09

**A lead may only clean up a blocked child if it reads the block as stale** — already
resolved elsewhere, or the status simply has not updated. Not a hard rule for now: an
agent clearing its own block covers most of it, and we will see how it plays out. —
confirmed 2026-08-09

**`sb inspect` is how Andrew reads a blocked agent's full message, and it should show
more tail — like 100 lines.** — confirmed 2026-08-09

**`sb restore` is gone if the worktree is gone.** Aggressive cleanup therefore destroys
it, and so now does the sweep, with nobody typing anything — both accepted: the push is
the recovery path for the work, not restore. What the sweep costs is bounded by the rules
it deletes under, since it only ever reaches a worktree whose commits are on origin or are
docs-only, and a swept branch's ref is deleted with `git branch -d`, which refuses an
unmerged one. The agent rows under a swept workspace go with the workspace, so their
`sb restore` and their `sb inspect` history go with it too. So a sweep costs a checkout,
its restore, and that history — never a commit. — confirmed 2026-08-09, the sweep 2026-08-16,
the agent rows 2026-08-25

**`sb inbox --peek` stays, and it must be clear that once a message is read it will not
be brought up again.** — confirmed 2026-08-09

**A workspace forks from `origin/main` by default.** — confirmed 2026-08-09

**Pushing and merging are decided by the parent, which may or may not be a human.** An
agent can push if its parent says so; a lead can push if the dispatcher says so;
any agent can merge if Andrew tells some dispatcher and it passes that instruction
down. So it is never merge without asking your parent. The default shape of shipping work
is branch named for the workspace, push, open the PR, and put its URL in the summary. The
plans plugin can override this: where a plan is running, its merge gate decides pushing and
merging — the agent asks once, and once approved merges and cleans up without asking again.
`sb merge` is not the act this entry governs: it folds a child's branch into the caller's
own branch and reaches no push, no `main` and no pull request.
— confirmed 2026-08-12, superseding the 2026-08-09 rule that merging needed Andrew's own
explicit approval and that no agent merges without asking first; the plans plugin's
merge-gate override 2026-08-17

**`sb workspace new` is deleted, provided the other commands cover it fully and it is
clear how to use them.** — confirmed 2026-08-09

**`sb log` is likewise for agents rather than Andrew — also soft — but it stays, it
could be useful.** — confirmed 2026-08-09, soft rather than gated confirmed 2026-08-12

**`sb presets` needs a parameter to list, and one to apply the prompt to the current
chat or just read it.** Picking a preset should inject a prompt: sb pastes it in, the
same path as any other message. This must be known to all sessions. — confirmed
2026-08-09

**`sb models` is fine as it is.** — confirmed 2026-08-09

**Andrew will never call the spawn and lifecycle commands himself, other than
`sb start`.** The surfaces that are his are the board, the session he types into, and
`sb inspect` for reading a blocked agent. `sb sweep` is his rather than an agent's and does
not change that: it is the board's own housekeeping run by hand, and the board runs it
without anybody typing it. — confirmed 2026-08-09, `sb sweep` placed against it 2026-08-16

---

## Explicitly rejected

*Ruled out, so they stay ruled out. The decision each one came from is in Product
decisions; this is the list of what no longer exists.*

**The human inbox — 100% removed.** It is confusing, and Andrew cannot see the messages.
— confirmed 2026-08-09

**`sb ask`.** No agent waits on another agent. — confirmed 2026-08-09

**`sb wait`.** It has no reason to exist. — confirmed 2026-08-09

**`sb interrupt` as a verb.** Interrupting is a delivery mode of `tell`. — confirmed
2026-08-09

**`--keep`, `--ephemeral`, `--include-kept`, `--leave-children`.** Cleanup is the parent's,
and it always takes the children. — confirmed 2026-08-09, worded as the parent's rather
than the lead's 2026-08-15, since a dispatcher now closes on Andrew's say-so

**Hard tool-layer enforcement of what a dispatcher may do.** No gate, no blocked verbs: a
dispatcher legitimately writes a handoff file and legitimately reads one, and a rule that
cannot tell those from doing the work would either block the job or wave the work through.
A well-written prompt is judged sufficient. The capability set that arrived later did not
reopen this: there is no filesystem chokepoint anywhere in sb, so `write-tracked` is checked
after the fact at `sb merge` and only flagged at `sb done`, never at the write itself. —
confirmed 2026-08-14, the capability set placed against it 2026-08-23

**A revoke, and an expiry on a grant.** A grant is one shot and lasts the agent's
lifetime: `cleanup` ends the lifetime and `restore` starts a fresh one from the stored
seed. That bound is what makes a grant cheap to give and impossible to forget about. —
confirmed 2026-08-23

**A grantable `start`.** `sb start` stays a hardcoded, fail-closed, human-only gate and
`start` is not a capability string at all — a grantable version of it is how a top would
come to mint a second top. A repo naming it in a role template does not reopen it. —
confirmed 2026-08-23

**A capability for topology.** Promote is self-service and there is no topology capability
string: re-homing your own children onto your own parent takes a right over nobody, and the
one refusal on it is structural rather than a permission. — confirmed 2026-08-23

**A hard cap on worktrees or on fan-out width.** Nothing is refused and no number is
enforced. `sb status` carries the open-worktree count — the agent's own and its subtree's
— and the guidance ledger nudges past a soft threshold; a ceiling would refuse a legitimate
twenty-way fan-out at the moment the fleet is doing its most valuable work. — confirmed
2026-08-23

**`sb handoff` as its own verb, and a batch `sb merge`.** The handoff is a flag on the verb
that already exists, because the spawn half is `sb delegate` unchanged and the message half
is the `done` summary. Merging is one child at a time, because batching made assembly wait
for the last child. — confirmed 2026-08-23

**`--no-board`.** Every sb-made view is split with the board. — confirmed 2026-08-09

**Focus as a flag.** Only `sb start` focuses on spawn, and nothing can ask for it. —
confirmed 2026-08-09

---

## Open / undecided

*Questions that are open — listed here so they are visibly undecided rather than quietly
assumed.*

*The item that used to sit here — the mechanism distinguishing the top agent from a
nested one — was answered on 2026-08-09 by the `is_top` stamp and moved to Product
decisions. That answer covered where an agent's children go; it never covered what an
agent may do itself, which is now answered too, by the split into two roles with two
prompts. Both are in Product decisions and neither is open. What follows is.*

**Real cross-repo dispatch does not exist and is not close.** The store is per repo, so a
child in another repo would have no parentage, no messaging, no status, no board row and
no cleanup reaching it — that is a multi-store fleet, not a flag. What ships instead is a
stopping rule: the dispatcher notices, asks, and starts nothing. Whether the missing thing
is ever built is undecided. — open 2026-08-14
